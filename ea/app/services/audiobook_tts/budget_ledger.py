"""Strict durable VocalLab reservation, charge and materialization ledger."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import stat
from typing import Any, Iterator, Literal, Mapping


BUDGET_LEDGER_CONTRACT_NAME = "ea.audiobook_provider_budget_ledger.v1"
_LEDGER_VERSION = 3
_MAX_LEDGER_BYTES = 4 * 1024 * 1024
_SHA_LENGTH = 64
ReservationStatus = Literal[
    "reserved",
    "post_started",
    "generation_known",
    "charged_pending_materialization",
    "complete",
    "complete_budget_violation",
    "released",
    "unknown",
]
_STAT_IDENTITY = (
    "st_dev",
    "st_ino",
    "st_size",
    "st_mode",
    "st_uid",
    "st_nlink",
    "st_mtime_ns",
    "st_ctime_ns",
)


class BudgetLedgerError(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        charge_state: str = "not_charged",
        retry_after_seconds: int = 0,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.charge_state = charge_state
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True, slots=True)
class AccountBalance:
    monthly_points: int
    topup_points: int = 0

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in (self.monthly_points, self.topup_points)
        ):
            raise BudgetLedgerError("provider_balance_invalid")

    def spendable_monthly_only(self) -> int:
        return self.monthly_points


@dataclass(frozen=True, slots=True)
class BudgetReservation:
    reservation_id: str
    status: ReservationStatus
    points_estimated: int
    points_used: int = 0
    generation_id_private: str = field(default="", repr=False)
    generation_id_sha256: str = ""
    output_sha256: str = ""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _timestamp(value: datetime | None = None) -> str:
    return (value or _utc_now()).astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise BudgetLedgerError("budget_ledger_invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise BudgetLedgerError("budget_ledger_invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise BudgetLedgerError("budget_ledger_invalid")
    return parsed.astimezone(UTC)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _valid_sha(value: Any, *, allow_empty: bool = False) -> bool:
    if allow_empty and value == "":
        return True
    return (
        isinstance(value, str)
        and len(value) == _SHA_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _exact_keys(value: Mapping[str, Any], keys: set[str]) -> None:
    if set(value) != keys:
        raise BudgetLedgerError("budget_ledger_invalid")


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError("nonfinite_json_number")


class VocalLabBudgetLedger:
    def __init__(
        self,
        account_state_root: str | Path,
        *,
        credential_binding_sha256: str,
        minimum_account_reserve: int = 3000,
        maximum_points_per_job: int = 6000,
        maximum_segments_per_job: int = 10,
        allow_topup_points: bool = False,
    ) -> None:
        root_candidate = Path(account_state_root)
        if (
            not root_candidate.is_absolute()
            or any(part in {"", ".", ".."} for part in root_candidate.parts)
        ):
            raise BudgetLedgerError("budget_coordinator_root_invalid")
        self.account_state_root = root_candidate.absolute()
        if not _valid_sha(credential_binding_sha256):
            raise BudgetLedgerError("budget_credential_binding_invalid")
        self._credential_binding_sha256 = credential_binding_sha256
        self.path = self.account_state_root / (
            f"vocallab-account-state-{credential_binding_sha256}.json"
        )
        self._lock_name = f"{self.path.name}.lock"
        self._provider_lock_name = f"{self.path.name}.provider.lock"
        for value in (
            minimum_account_reserve,
            maximum_points_per_job,
            maximum_segments_per_job,
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise BudgetLedgerError("budget_policy_invalid")
        if (
            minimum_account_reserve < 3000
            or maximum_points_per_job <= 0
            or maximum_segments_per_job <= 0
        ):
            raise BudgetLedgerError("budget_policy_invalid")
        if type(allow_topup_points) is not bool or allow_topup_points:
            raise BudgetLedgerError("budget_policy_invalid")
        self.minimum_account_reserve = minimum_account_reserve
        self.maximum_points_per_job = maximum_points_per_job
        self.maximum_segments_per_job = maximum_segments_per_job
        self.allow_topup_points = False

    def assert_scope(
        self,
        *,
        credential_binding_sha256: str,
        canonical_account_state_root: str | Path,
    ) -> None:
        expected_root = Path(canonical_account_state_root).absolute()
        expected_path = expected_root / (
            f"vocallab-account-state-{credential_binding_sha256}.json"
        )
        if (
            not _valid_sha(credential_binding_sha256)
            or not hmac_compare(
                credential_binding_sha256,
                self._credential_binding_sha256,
            )
            or expected_root != self.account_state_root
            or expected_path != self.path
        ):
            raise BudgetLedgerError("budget_coordinator_scope_mismatch")

    def _check_components(self) -> None:
        current = Path(self.path.anchor)
        for part in self.path.parts[1:-1]:
            current /= part
            try:
                metadata = current.lstat()
            except OSError:
                if current == self.path.parent:
                    break
                raise BudgetLedgerError("budget_ledger_path_unavailable") from None
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise BudgetLedgerError("budget_ledger_path_unsafe")

    def _open_parent(self) -> int:
        self._check_components()
        if not self.path.parent.exists():
            try:
                self.path.parent.mkdir(parents=True, mode=0o700)
            except OSError:
                raise BudgetLedgerError("budget_ledger_parent_unavailable") from None
        try:
            before = self.path.parent.lstat()
            if (
                stat.S_ISLNK(before.st_mode)
                or not stat.S_ISDIR(before.st_mode)
                or before.st_uid != os.geteuid()
                or stat.S_IMODE(before.st_mode) != 0o700
            ):
                raise BudgetLedgerError("budget_ledger_parent_unsafe")
            descriptor = os.open(
                self.path.parent,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
            )
            opened = os.fstat(descriptor)
            if (
                opened.st_dev,
                opened.st_ino,
                opened.st_mode,
                opened.st_uid,
                opened.st_nlink,
            ) != (
                before.st_dev,
                before.st_ino,
                before.st_mode,
                before.st_uid,
                before.st_nlink,
            ):
                os.close(descriptor)
                raise BudgetLedgerError("budget_ledger_parent_changed")
            return descriptor
        except BudgetLedgerError:
            raise
        except OSError:
            raise BudgetLedgerError("budget_ledger_parent_unavailable") from None

    @contextmanager
    def _path_lock(self, name: str) -> Iterator[int]:
        parent_fd = self._open_parent()
        descriptor = -1
        try:
            try:
                before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                before = None
            flags = (
                os.O_RDWR
                | os.O_CREAT
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0)
            )
            descriptor = os.open(name, flags, 0o600, dir_fd=parent_fd)
            opened = os.fstat(descriptor)
            if before is not None and (before.st_dev, before.st_ino) != (
                opened.st_dev,
                opened.st_ino,
            ):
                raise BudgetLedgerError("budget_ledger_lock_changed")
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_uid != os.geteuid()
                or stat.S_IMODE(opened.st_mode) != 0o600
                or opened.st_nlink != 1
            ):
                raise BudgetLedgerError("budget_ledger_lock_unsafe")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            bound = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if (bound.st_dev, bound.st_ino) != (opened.st_dev, opened.st_ino):
                raise BudgetLedgerError("budget_ledger_lock_split")
            yield parent_fd
            after = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            current = os.fstat(descriptor)
            if (after.st_dev, after.st_ino) != (current.st_dev, current.st_ino):
                raise BudgetLedgerError("budget_ledger_lock_split")
            parent_after = self.path.parent.lstat()
            parent_current = os.fstat(parent_fd)
            if (
                parent_after.st_dev,
                parent_after.st_ino,
                parent_after.st_mode,
                parent_after.st_uid,
                parent_after.st_nlink,
            ) != (
                parent_current.st_dev,
                parent_current.st_ino,
                parent_current.st_mode,
                parent_current.st_uid,
                parent_current.st_nlink,
            ):
                raise BudgetLedgerError("budget_ledger_parent_changed")
        except BudgetLedgerError:
            raise
        except OSError:
            raise BudgetLedgerError("budget_ledger_lock_unavailable") from None
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            os.close(parent_fd)

    @contextmanager
    def provider_account_lock(self) -> Iterator[None]:
        with self._path_lock(self._provider_lock_name):
            yield

    @contextmanager
    def _transaction(self) -> Iterator[dict[str, Any]]:
        with self._path_lock(self._lock_name) as parent_fd:
            payload = self._read_locked(parent_fd)
            yield payload
            self._validate_payload(payload)
            self._write_locked(parent_fd, payload)

    def _policy(self) -> dict[str, object]:
        return {
            "minimum_account_reserve": self.minimum_account_reserve,
            "maximum_points_per_job": self.maximum_points_per_job,
            "maximum_segments_per_job": self.maximum_segments_per_job,
            "allow_topup_points": self.allow_topup_points,
        }

    def _empty(self) -> dict[str, Any]:
        now = _timestamp()
        return {
            "contract_name": BUDGET_LEDGER_CONTRACT_NAME,
            "version": _LEDGER_VERSION,
            "credential_binding_sha256": self._credential_binding_sha256,
            "updated_at": now,
            "policy": self._policy(),
            "last_observed_balance": {
                "monthly_points": 0,
                "topup_points": 0,
                "observed_at": now,
            },
            "rate_limit": {"last_request_started_at": ""},
            "circuit_breaker": {
                "status": "closed",
                "reason": "",
                "consecutive_upstream_failures": 0,
            },
            "reservations": {},
        }

    def _read_locked(self, parent_fd: int) -> dict[str, Any]:
        try:
            before = os.stat(
                self.path.name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return self._empty()
        except OSError:
            raise BudgetLedgerError("budget_ledger_unavailable") from None
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_nlink != 1
            or before.st_size <= 0
            or before.st_size > _MAX_LEDGER_BYTES
        ):
            raise BudgetLedgerError("budget_ledger_file_unsafe")
        descriptor = -1
        try:
            descriptor = os.open(
                self.path.name,
                os.O_RDONLY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=parent_fd,
            )
            opened = os.fstat(descriptor)
            if (
                (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
                or opened.st_size != before.st_size
                or opened.st_mode != before.st_mode
                or opened.st_uid != before.st_uid
                or opened.st_nlink != 1
            ):
                raise BudgetLedgerError("budget_ledger_file_changed")
            chunks: list[bytes] = []
            received = 0
            while True:
                chunk = os.read(descriptor, min(65536, _MAX_LEDGER_BYTES + 1 - received))
                if not chunk:
                    break
                received += len(chunk)
                if received > _MAX_LEDGER_BYTES:
                    raise BudgetLedgerError("budget_ledger_too_large")
                chunks.append(chunk)
            after = os.stat(
                self.path.name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
            if any(getattr(after, name) != getattr(before, name) for name in _STAT_IDENTITY):
                raise BudgetLedgerError("budget_ledger_file_changed")
        except BudgetLedgerError:
            raise
        except OSError:
            raise BudgetLedgerError("budget_ledger_unavailable") from None
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        try:
            payload = json.loads(
                b"".join(chunks).decode("utf-8"),
                object_pairs_hook=_strict_json_object,
                parse_constant=_reject_json_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            raise BudgetLedgerError("budget_ledger_invalid") from None
        if not isinstance(payload, dict):
            raise BudgetLedgerError("budget_ledger_invalid")
        self._validate_payload(payload)
        return payload

    def _write_locked(self, parent_fd: int, payload: dict[str, Any]) -> None:
        payload["updated_at"] = _timestamp()
        encoded = (
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        if len(encoded) > _MAX_LEDGER_BYTES:
            raise BudgetLedgerError("budget_ledger_too_large")
        temporary = ""
        descriptor = -1
        try:
            for _ in range(32):
                temporary = f".{self.path.name}.{secrets.token_hex(12)}.tmp"
                try:
                    descriptor = os.open(
                        temporary,
                        os.O_WRONLY
                        | os.O_CREAT
                        | os.O_EXCL
                        | getattr(os, "O_NOFOLLOW", 0)
                        | getattr(os, "O_CLOEXEC", 0),
                        0o600,
                        dir_fd=parent_fd,
                    )
                    break
                except FileExistsError:
                    continue
            if descriptor < 0:
                raise BudgetLedgerError("budget_ledger_write_failed")
            offset = 0
            while offset < len(encoded):
                written = os.write(descriptor, encoded[offset:])
                if written <= 0:
                    raise BudgetLedgerError("budget_ledger_write_failed")
                offset += written
            os.fsync(descriptor)
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_uid != os.geteuid()
                or stat.S_IMODE(opened.st_mode) != 0o600
                or opened.st_nlink != 1
            ):
                raise BudgetLedgerError("budget_ledger_write_failed")
            os.close(descriptor)
            descriptor = -1
            os.rename(
                temporary,
                self.path.name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            temporary = ""
            os.fsync(parent_fd)
        except BudgetLedgerError:
            raise
        except OSError:
            raise BudgetLedgerError("budget_ledger_write_failed") from None
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary:
                try:
                    os.unlink(temporary, dir_fd=parent_fd)
                except OSError:
                    pass

    def _validate_payload(self, payload: Mapping[str, Any]) -> None:
        _exact_keys(
            payload,
            {
                "contract_name",
                "version",
                "credential_binding_sha256",
                "updated_at",
                "policy",
                "last_observed_balance",
                "rate_limit",
                "circuit_breaker",
                "reservations",
            },
        )
        if (
            payload.get("contract_name") != BUDGET_LEDGER_CONTRACT_NAME
            or payload.get("version") != _LEDGER_VERSION
            or isinstance(payload.get("version"), bool)
            or payload.get("credential_binding_sha256")
            != self._credential_binding_sha256
            or payload.get("policy") != self._policy()
        ):
            raise BudgetLedgerError("budget_ledger_invalid")
        _parse_timestamp(payload.get("updated_at"))
        balance = payload.get("last_observed_balance")
        rate = payload.get("rate_limit")
        circuit = payload.get("circuit_breaker")
        reservations = payload.get("reservations")
        if not all(isinstance(value, dict) for value in (balance, rate, circuit, reservations)):
            raise BudgetLedgerError("budget_ledger_invalid")
        _exact_keys(balance, {"monthly_points", "topup_points", "observed_at"})
        if any(
            not isinstance(balance.get(key), int)
            or isinstance(balance.get(key), bool)
            or int(balance.get(key)) < 0
            for key in ("monthly_points", "topup_points")
        ):
            raise BudgetLedgerError("budget_ledger_invalid")
        _parse_timestamp(balance.get("observed_at"))
        _exact_keys(rate, {"last_request_started_at"})
        last_request = rate.get("last_request_started_at")
        if last_request != "":
            _parse_timestamp(last_request)
        _exact_keys(
            circuit,
            {"status", "reason", "consecutive_upstream_failures"},
        )
        failures = circuit.get("consecutive_upstream_failures")
        if type(failures) is not int or not 0 <= failures <= 3:
            raise BudgetLedgerError("budget_ledger_invalid")
        allowed_circuits = {
            ("closed", ""),
            ("open", "provider_points_exceeded_reservation"),
            ("open", "three_consecutive_upstream_failures"),
        }
        if (circuit.get("status"), circuit.get("reason")) not in allowed_circuits:
            raise BudgetLedgerError("budget_ledger_invalid")
        if (
            circuit.get("status") == "closed"
            and failures >= 3
        ) or (
            circuit.get("reason") == "three_consecutive_upstream_failures"
            and failures != 3
        ):
            raise BudgetLedgerError("budget_ledger_invalid")
        for key, row in reservations.items():
            if not isinstance(key, str) or not isinstance(row, dict):
                raise BudgetLedgerError("budget_ledger_invalid")
            self._validate_reservation(key, row)

    def _validate_reservation(self, key: str, row: Mapping[str, Any]) -> None:
        _exact_keys(
            row,
            {
                "reservation_id",
                "job_id_sha256",
                "idempotency_key_sha256",
                "request_fingerprint",
                "points_estimated",
                "points_used",
                "status",
                "generation_id_private",
                "generation_id_sha256",
                "output_sha256",
                "created_at",
                "updated_at",
            },
        )
        status = row.get("status")
        statuses = {
            "reserved",
            "post_started",
            "generation_known",
            "charged_pending_materialization",
            "complete",
            "complete_budget_violation",
            "released",
            "unknown",
        }
        if (
            row.get("reservation_id") != key
            or not _valid_sha(key)
            or not _valid_sha(row.get("job_id_sha256"))
            or not _valid_sha(row.get("idempotency_key_sha256"))
            or not _valid_sha(row.get("request_fingerprint"))
            or status not in statuses
        ):
            raise BudgetLedgerError("budget_ledger_invalid")
        estimated = row.get("points_estimated")
        used = row.get("points_used")
        if (
            not isinstance(estimated, int)
            or isinstance(estimated, bool)
            or estimated <= 0
            or not isinstance(used, int)
            or isinstance(used, bool)
            or used < 0
        ):
            raise BudgetLedgerError("budget_ledger_invalid")
        created = _parse_timestamp(row.get("created_at"))
        updated = _parse_timestamp(row.get("updated_at"))
        if updated < created:
            raise BudgetLedgerError("budget_ledger_invalid")
        generation = row.get("generation_id_private")
        generation_hash = row.get("generation_id_sha256")
        output_hash = row.get("output_sha256")
        if not isinstance(generation, str) or len(generation) > 256:
            raise BudgetLedgerError("budget_ledger_invalid")
        requires_generation = status in {
            "generation_known",
            "charged_pending_materialization",
            "complete",
            "complete_budget_violation",
        }
        if requires_generation:
            if (
                not generation
                or not _valid_sha(generation_hash)
                or not hmac_compare(generation_hash, _sha256_text(generation))
            ):
                raise BudgetLedgerError("budget_ledger_invalid")
        elif generation:
            if (
                status != "released"
                or not _valid_sha(generation_hash)
                or not hmac_compare(generation_hash, _sha256_text(generation))
            ):
                raise BudgetLedgerError("budget_ledger_invalid")
        elif generation_hash != "":
            raise BudgetLedgerError("budget_ledger_invalid")
        if status in {"reserved", "post_started", "generation_known", "released", "unknown"} and used != 0:
            raise BudgetLedgerError("budget_ledger_invalid")
        if status == "complete_budget_violation" and used <= estimated:
            raise BudgetLedgerError("budget_ledger_invalid")
        if status in {"charged_pending_materialization", "complete"} and used > estimated:
            raise BudgetLedgerError("budget_ledger_invalid")
        if status == "complete":
            if not _valid_sha(output_hash):
                raise BudgetLedgerError("budget_ledger_invalid")
        elif output_hash != "":
            raise BudgetLedgerError("budget_ledger_invalid")

    def _reservation_id(self, job_id: str, idempotency_key: str) -> str:
        return _sha256_text(
            "ea.audiobook.vocallab.reservation.v1\x00"
            f"{self._credential_binding_sha256}\x00{job_id}\x00{idempotency_key}"
        )

    @staticmethod
    def _result(row: Mapping[str, Any]) -> BudgetReservation:
        return BudgetReservation(
            reservation_id=str(row["reservation_id"]),
            status=str(row["status"]),  # type: ignore[arg-type]
            points_estimated=int(row["points_estimated"]),
            points_used=int(row["points_used"]),
            generation_id_private=str(row["generation_id_private"]),
            generation_id_sha256=str(row["generation_id_sha256"]),
            output_sha256=str(row["output_sha256"]),
        )

    def find_existing(
        self,
        *,
        job_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> BudgetReservation | None:
        """Resolve resumable account-global state without creating a reservation."""

        if (
            not isinstance(job_id, str)
            or not job_id
            or not isinstance(idempotency_key, str)
            or not idempotency_key
            or not _valid_sha(request_fingerprint)
        ):
            raise BudgetLedgerError("budget_reservation_invalid")
        reservation_id = self._reservation_id(job_id, idempotency_key)
        with self._path_lock(self._lock_name) as parent_fd:
            payload = self._read_locked(parent_fd)
        reservations: dict[str, Any] = payload["reservations"]
        existing = reservations.get(reservation_id)
        if existing is not None:
            if not isinstance(existing, dict):
                raise BudgetLedgerError("budget_ledger_invalid")
            if existing["request_fingerprint"] != request_fingerprint:
                raise BudgetLedgerError("idempotency_key_reused")
            status = existing["status"]
            if status in {"post_started", "unknown"}:
                raise BudgetLedgerError(
                    "budget_request_charge_unknown",
                    charge_state="unknown",
                )
            if status in {"complete", "complete_budget_violation"}:
                raise BudgetLedgerError(
                    "budget_request_already_completed",
                    charge_state="charged",
                )
            if status != "released":
                return self._result(existing)
        for other_id, other in reservations.items():
            if (
                other_id != reservation_id
                and other["request_fingerprint"] == request_fingerprint
                and other["status"] != "released"
            ):
                raise BudgetLedgerError(
                    "duplicate_synthesis_fingerprint",
                    charge_state=(
                        "charged"
                        if other["status"]
                        in {
                            "charged_pending_materialization",
                            "complete",
                            "complete_budget_violation",
                        }
                        else "unknown"
                    ),
                )
        if payload["circuit_breaker"]["status"] != "closed":
            raise BudgetLedgerError("budget_circuit_breaker_open")
        if any(row["status"] == "unknown" for row in reservations.values()):
            raise BudgetLedgerError(
                "budget_account_charge_unknown",
                charge_state="unknown",
            )
        return None

    def reserve(
        self,
        *,
        job_id: str,
        idempotency_key: str,
        request_fingerprint: str,
        points_estimated: int,
        balance: AccountBalance,
        observed_at: datetime | None = None,
    ) -> BudgetReservation:
        if (
            not isinstance(job_id, str)
            or not job_id
            or not isinstance(idempotency_key, str)
            or not idempotency_key
            or not _valid_sha(request_fingerprint)
            or not isinstance(points_estimated, int)
            or isinstance(points_estimated, bool)
            or points_estimated <= 0
        ):
            raise BudgetLedgerError("budget_reservation_invalid")
        reservation_id = self._reservation_id(job_id, idempotency_key)
        job_hash = _sha256_text(job_id)
        with self._transaction() as payload:
            reservations: dict[str, Any] = payload["reservations"]
            existing = reservations.get(reservation_id)
            if existing is not None and not isinstance(existing, dict):
                raise BudgetLedgerError("budget_ledger_invalid")
            if existing is not None:
                if existing["request_fingerprint"] != request_fingerprint:
                    raise BudgetLedgerError("idempotency_key_reused")
                status = existing["status"]
                if status in {"post_started", "unknown"}:
                    raise BudgetLedgerError(
                        "budget_request_charge_unknown",
                        charge_state="unknown",
                    )
                if status in {"complete", "complete_budget_violation"}:
                    raise BudgetLedgerError(
                        "budget_request_already_completed",
                        charge_state="charged",
                    )
                if status in {"generation_known", "charged_pending_materialization"}:
                    return self._result(existing)

            for other_id, other in reservations.items():
                if (
                    other_id != reservation_id
                    and other["request_fingerprint"] == request_fingerprint
                    and other["status"] != "released"
                ):
                    raise BudgetLedgerError(
                        "duplicate_synthesis_fingerprint",
                        charge_state=(
                            "charged"
                            if other["status"]
                            in {"complete", "complete_budget_violation", "charged_pending_materialization"}
                            else "unknown"
                        ),
                    )
            if payload["circuit_breaker"]["status"] != "closed":
                raise BudgetLedgerError("budget_circuit_breaker_open")
            if any(row["status"] == "unknown" for row in reservations.values()):
                raise BudgetLedgerError(
                    "budget_account_charge_unknown",
                    charge_state="unknown",
                )
            active = [
                row
                for key, row in reservations.items()
                if key != reservation_id
                and row["status"]
                in {"reserved", "post_started", "generation_known"}
            ]
            reserved_points = sum(row["points_estimated"] for row in active)
            job_rows = [
                row
                for key, row in reservations.items()
                if key != reservation_id
                and row["job_id_sha256"] == job_hash
                and row["status"] != "released"
            ]
            if len(job_rows) + 1 > self.maximum_segments_per_job:
                raise BudgetLedgerError("budget_job_segment_ceiling_reached")
            committed = sum(
                row["points_used"]
                if row["status"]
                in {"complete", "complete_budget_violation", "charged_pending_materialization"}
                else row["points_estimated"]
                for row in job_rows
            )
            if committed + points_estimated > self.maximum_points_per_job:
                raise BudgetLedgerError("budget_job_point_ceiling_reached")
            spendable = balance.spendable_monthly_only()
            if spendable - reserved_points - points_estimated < self.minimum_account_reserve:
                raise BudgetLedgerError("budget_account_reserve_reached")
            observed = observed_at or _utc_now()
            if not isinstance(observed, datetime) or observed.tzinfo is None:
                raise BudgetLedgerError("budget_balance_timestamp_invalid")
            payload["last_observed_balance"] = {
                "monthly_points": balance.monthly_points,
                "topup_points": balance.topup_points,
                "observed_at": _timestamp(observed),
            }
            if existing is not None and existing["status"] == "reserved":
                if existing["points_estimated"] != points_estimated:
                    raise BudgetLedgerError("budget_reservation_estimate_changed")
                return self._result(existing)
            now = _timestamp(observed)
            row = {
                "reservation_id": reservation_id,
                "job_id_sha256": job_hash,
                "idempotency_key_sha256": _sha256_text(idempotency_key),
                "request_fingerprint": request_fingerprint,
                "points_estimated": points_estimated,
                "points_used": 0,
                "status": "reserved",
                "generation_id_private": "",
                "generation_id_sha256": "",
                "output_sha256": "",
                "created_at": now,
                "updated_at": now,
            }
            reservations[reservation_id] = row
            return self._result(row)

    @staticmethod
    def _row(payload: Mapping[str, Any], reservation_id: str) -> dict[str, Any]:
        reservations = payload.get("reservations")
        row = reservations.get(reservation_id) if isinstance(reservations, dict) else None
        if not isinstance(row, dict):
            raise BudgetLedgerError("budget_reservation_not_found")
        return row

    def mark_post_started(
        self,
        reservation_id: str,
        *,
        started_at: datetime,
    ) -> BudgetReservation:
        if (
            not isinstance(started_at, datetime)
            or started_at.tzinfo is None
        ):
            raise BudgetLedgerError("budget_post_timestamp_invalid")
        current = started_at.astimezone(UTC)
        with self._transaction() as payload:
            row = self._row(payload, reservation_id)
            if row["status"] != "reserved":
                raise BudgetLedgerError("budget_reservation_state_invalid")
            row["status"] = "post_started"
            row["updated_at"] = _timestamp(current)
            return self._result(row)

    def record_request_started(
        self,
        *,
        started_at: datetime,
        requests_per_minute: int,
    ) -> None:
        """Persist one account-global HTTP start before any provider request."""

        if (
            not isinstance(started_at, datetime)
            or started_at.tzinfo is None
            or not isinstance(requests_per_minute, int)
            or isinstance(requests_per_minute, bool)
            or not 1 <= requests_per_minute <= 30
        ):
            raise BudgetLedgerError("budget_rate_policy_invalid")
        current = started_at.astimezone(UTC)
        with self._transaction() as payload:
            last_value = payload["rate_limit"]["last_request_started_at"]
            if last_value:
                last = _parse_timestamp(last_value)
                minimum = timedelta(seconds=60 / requests_per_minute)
                if current < last + minimum:
                    delay = max(
                        1,
                        math.ceil((last + minimum - current).total_seconds()),
                    )
                    raise BudgetLedgerError(
                        "provider_local_rate_limited",
                        retry_after_seconds=delay,
                    )
            payload["rate_limit"]["last_request_started_at"] = _timestamp(current)

    def record_generation(
        self, reservation_id: str, generation_id_private: str
    ) -> BudgetReservation:
        if (
            not isinstance(generation_id_private, str)
            or not generation_id_private
            or len(generation_id_private) > 256
            or any(
                character
                not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-"
                for character in generation_id_private
            )
            or not generation_id_private[0].isalnum()
        ):
            raise BudgetLedgerError("provider_generation_id_invalid", charge_state="unknown")
        with self._transaction() as payload:
            row = self._row(payload, reservation_id)
            if row["status"] != "post_started" or row["generation_id_private"]:
                raise BudgetLedgerError("provider_generation_id_immutable")
            row["status"] = "generation_known"
            row["generation_id_private"] = generation_id_private
            row["generation_id_sha256"] = _sha256_text(generation_id_private)
            row["updated_at"] = _timestamp()
            return self._result(row)

    def mark_unknown(self, reservation_id: str) -> BudgetReservation:
        with self._transaction() as payload:
            row = self._row(payload, reservation_id)
            if row["status"] != "post_started" or row["generation_id_private"]:
                raise BudgetLedgerError("budget_reservation_state_invalid")
            row["status"] = "unknown"
            row["updated_at"] = _timestamp()
            return self._result(row)

    def release_known_uncharged(self, reservation_id: str) -> BudgetReservation:
        with self._transaction() as payload:
            row = self._row(payload, reservation_id)
            # No current provider response contract proves a submitted POST
            # uncharged. Only a reservation that never entered POST may release.
            if row["status"] != "reserved":
                raise BudgetLedgerError("budget_reservation_state_invalid")
            row["status"] = "released"
            row["updated_at"] = _timestamp()
            return self._result(row)

    def reconcile_charge(
        self, reservation_id: str, *, points_used: int
    ) -> BudgetReservation:
        if (
            not isinstance(points_used, int)
            or isinstance(points_used, bool)
            or points_used < 0
        ):
            raise BudgetLedgerError("provider_points_invalid", charge_state="unknown")
        violation = False
        with self._transaction() as payload:
            row = self._row(payload, reservation_id)
            if row["status"] != "generation_known":
                raise BudgetLedgerError("budget_reservation_state_invalid")
            row["points_used"] = points_used
            if points_used > row["points_estimated"]:
                row["status"] = "complete_budget_violation"
                payload["circuit_breaker"] = {
                    "status": "open",
                    "reason": "provider_points_exceeded_reservation",
                    "consecutive_upstream_failures": payload[
                        "circuit_breaker"
                    ]["consecutive_upstream_failures"],
                }
                violation = True
            else:
                row["status"] = "charged_pending_materialization"
            row["updated_at"] = _timestamp()
            result = self._result(row)
        if violation:
            raise BudgetLedgerError(
                "provider_points_exceeded_reservation",
                charge_state="charged",
            )
        return result

    def commit_materialized(
        self, reservation_id: str, *, output_sha256: str
    ) -> BudgetReservation:
        if not _valid_sha(output_sha256):
            raise BudgetLedgerError("materialized_output_hash_invalid", charge_state="charged")
        with self._transaction() as payload:
            row = self._row(payload, reservation_id)
            if row["status"] != "charged_pending_materialization":
                raise BudgetLedgerError("budget_reservation_state_invalid")
            row["output_sha256"] = output_sha256
            row["status"] = "complete"
            row["updated_at"] = _timestamp()
            return self._result(row)

    def record_upstream_failure(self) -> None:
        with self._transaction() as payload:
            circuit = payload["circuit_breaker"]
            if circuit["status"] == "open":
                return
            failures = min(
                3,
                int(circuit["consecutive_upstream_failures"]) + 1,
            )
            circuit["consecutive_upstream_failures"] = failures
            if failures == 3:
                circuit["status"] = "open"
                circuit["reason"] = "three_consecutive_upstream_failures"

    def record_provider_success(self) -> None:
        with self._transaction() as payload:
            circuit = payload["circuit_breaker"]
            if circuit["status"] == "closed":
                circuit["consecutive_upstream_failures"] = 0

    def public_projection(self) -> dict[str, object]:
        with self._path_lock(self._lock_name) as parent_fd:
            payload = self._read_locked(parent_fd)
        statuses: dict[str, int] = {}
        for row in payload["reservations"].values():
            status = row["status"]
            statuses[status] = statuses.get(status, 0) + 1
        return {
            "contract_name": BUDGET_LEDGER_CONTRACT_NAME,
            "version": _LEDGER_VERSION,
            "reservation_status_counts": dict(sorted(statuses.items())),
            "circuit_breaker_status": payload["circuit_breaker"]["status"],
            "consecutive_upstream_failures": payload["circuit_breaker"][
                "consecutive_upstream_failures"
            ],
            "minimum_account_reserve": self.minimum_account_reserve,
            "maximum_points_per_job": self.maximum_points_per_job,
            "maximum_segments_per_job": self.maximum_segments_per_job,
            "provider_spend_authority": (
                "denied_without_verified_balance_partition"
            ),
            "credential_binding_exposed": False,
            "exact_balance_exposed": False,
            "raw_generation_ids_exposed": False,
            "raw_idempotency_keys_exposed": False,
        }


def hmac_compare(left: str, right: str) -> bool:
    """Constant-time digest comparison without exporting private ledger data."""

    import hmac

    return hmac.compare_digest(left, right)
