"""Persistent quota, audit, review, and rollback controls for WorkLLM."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from app.services.workllm_sidecar import (
    WORKLLM_RUN_RECEIPT_SCHEMA,
    WorkLLMConfig,
    WorkLLMPolicyError,
    WorkLLMSidecar,
    WorkLLMTaskPacket,
    redact_workllm_text,
)

WORKLLM_AUDIT_EVENT_SCHEMA = "executive_assistant.workllm_audit_event.v1"
WORKLLM_CREDIT_LEDGER_SCHEMA = "executive_assistant.workllm_credit_ledger.v1"
WORKLLM_CONTROL_STATE_SCHEMA = "executive_assistant.workllm_control_state.v1"
WORKLLM_ROLLBACK_RECEIPT_SCHEMA = "executive_assistant.workllm_rollback_receipt.v1"

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_SAFE_TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ALLOWED_AUDIT_EVENTS = frozenset(
    {
        "task_prepared",
        "submission_authorized",
        "result_captured",
        "review_completed",
        "credit_reservation_cancelled",
        "rollback_engaged",
    }
)


class WorkLLMGovernanceError(WorkLLMPolicyError):
    """Raised when persistent WorkLLM governance evidence is invalid."""


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _month_from_timestamp(value: str | None = None) -> str:
    normalized = str(value or _utc_now()).strip()
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        raise WorkLLMGovernanceError("workllm_timestamp_invalid") from None
    return parsed.astimezone(UTC).strftime("%Y-%m")


def _timestamp_slug(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise WorkLLMGovernanceError("workllm_timestamp_invalid") from None
    return parsed.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha256_payload(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            raise OSError("workllm_governance_write_failed")
        offset += written


def _ensure_private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.chmod(0o700)
    except OSError:
        pass


def _assert_private_regular_file(path: Path) -> None:
    if not path.exists():
        return
    try:
        metadata = path.lstat()
    except OSError:
        raise WorkLLMGovernanceError("workllm_governance_file_unavailable") from None
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise WorkLLMGovernanceError("workllm_governance_file_unsafe")


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    _ensure_private_directory(path.parent)
    _assert_private_regular_file(path)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        encoded = (
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
        ).encode("utf-8")
        _write_all(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    path.chmod(0o600)


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    _ensure_private_directory(path.parent)
    descriptor = os.open(
        path,
        os.O_RDWR
        | os.O_CREAT
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _redact_structure(value: object, *, depth: int = 0) -> object:
    if depth > 8:
        raise WorkLLMGovernanceError("workllm_audit_detail_too_deep")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        redacted, _ = redact_workllm_text(value)
        return redacted
    if isinstance(value, Mapping):
        redacted_mapping: dict[str, object] = {}
        for key, item in value.items():
            redacted_key, _ = redact_workllm_text(str(key))
            redacted_mapping[redacted_key] = _redact_structure(
                item,
                depth=depth + 1,
            )
        return redacted_mapping
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [_redact_structure(item, depth=depth + 1) for item in value]
    raise WorkLLMGovernanceError("workllm_audit_detail_invalid")


class WorkLLMAuditLedger:
    """Append-only hash-chained audit ledger with private local storage."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.path = self.root / "audit.jsonl"
        self.lock_path = self.root / "audit.lock"

    def _read_entries_unlocked(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        _assert_private_regular_file(self.path)
        entries: list[dict[str, object]] = []
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for line_number, raw_line in enumerate(handle, start=1):
                    if len(raw_line.encode("utf-8")) > 1024 * 1024:
                        raise WorkLLMGovernanceError(
                            "workllm_audit_event_too_large"
                        )
                    if not raw_line.strip():
                        raise WorkLLMGovernanceError(
                            f"workllm_audit_blank_line:{line_number}"
                        )
                    loaded = json.loads(raw_line)
                    if not isinstance(loaded, dict):
                        raise WorkLLMGovernanceError(
                            f"workllm_audit_event_invalid:{line_number}"
                        )
                    entries.append(dict(loaded))
        except WorkLLMGovernanceError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise WorkLLMGovernanceError("workllm_audit_ledger_invalid") from None
        return entries

    @staticmethod
    def _verify_entries(entries: Sequence[Mapping[str, object]]) -> dict[str, object]:
        previous = ""
        for expected_sequence, raw_entry in enumerate(entries, start=1):
            entry = dict(raw_entry)
            if entry.get("schema") != WORKLLM_AUDIT_EVENT_SCHEMA:
                raise WorkLLMGovernanceError("workllm_audit_schema_mismatch")
            if entry.get("sequence") != expected_sequence:
                raise WorkLLMGovernanceError("workllm_audit_sequence_mismatch")
            if entry.get("previous_event_sha256") != previous:
                raise WorkLLMGovernanceError("workllm_audit_chain_mismatch")
            supplied = str(entry.pop("event_sha256", ""))
            expected = _sha256_payload(entry)
            if supplied != expected:
                raise WorkLLMGovernanceError("workllm_audit_digest_mismatch")
            previous = supplied
        return {
            "schema": "executive_assistant.workllm_audit_verification.v1",
            "valid": True,
            "event_count": len(entries),
            "head_event_sha256": previous,
        }

    def append(
        self,
        *,
        event_type: str,
        actor_ref: str,
        task_id: str = "",
        correlation_id: str = "",
        receipt: Mapping[str, object] | None = None,
        details: Mapping[str, object] | None = None,
        occurred_at: str | None = None,
    ) -> dict[str, object]:
        normalized_event_type = str(event_type or "").strip().lower()
        if normalized_event_type not in _ALLOWED_AUDIT_EVENTS:
            raise WorkLLMGovernanceError("workllm_audit_event_type_forbidden")
        normalized_actor = str(actor_ref or "").strip()
        if not normalized_actor:
            raise WorkLLMGovernanceError("workllm_audit_actor_missing")
        normalized_task_id = str(task_id or "").strip()
        if normalized_task_id and _SAFE_TASK_ID_RE.fullmatch(normalized_task_id) is None:
            raise WorkLLMGovernanceError("workllm_task_identifier_invalid")
        redacted_details = _redact_structure(dict(details or {}))
        if not isinstance(redacted_details, dict):
            raise WorkLLMGovernanceError("workllm_audit_detail_invalid")
        with _exclusive_lock(self.lock_path):
            entries = self._read_entries_unlocked()
            verification = self._verify_entries(entries)
            event: dict[str, object] = {
                "schema": WORKLLM_AUDIT_EVENT_SCHEMA,
                "sequence": len(entries) + 1,
                "event_type": normalized_event_type,
                "occurred_at": str(occurred_at or _utc_now()).strip(),
                "task_id": normalized_task_id,
                "correlation_id": str(correlation_id or "").strip(),
                "actor_ref_sha256": _sha256_text(normalized_actor),
                "receipt_sha256": (
                    _sha256_payload(dict(receipt)) if receipt is not None else ""
                ),
                "details": redacted_details,
                "previous_event_sha256": verification["head_event_sha256"],
            }
            event["event_sha256"] = _sha256_payload(event)
            _ensure_private_directory(self.path.parent)
            _assert_private_regular_file(self.path)
            descriptor = os.open(
                self.path,
                os.O_WRONLY
                | os.O_APPEND
                | os.O_CREAT
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                0o600,
            )
            try:
                os.fchmod(descriptor, 0o600)
                _write_all(
                    descriptor,
                    (_canonical_json(event) + "\n").encode("utf-8"),
                )
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            return event

    def verify(self) -> dict[str, object]:
        with _exclusive_lock(self.lock_path):
            return self._verify_entries(self._read_entries_unlocked())

    def entries_for_task(self, task_id: str) -> list[dict[str, object]]:
        normalized_task_id = str(task_id or "").strip()
        if _SAFE_TASK_ID_RE.fullmatch(normalized_task_id) is None:
            raise WorkLLMGovernanceError("workllm_task_identifier_invalid")
        with _exclusive_lock(self.lock_path):
            entries = self._read_entries_unlocked()
            self._verify_entries(entries)
            return [
                dict(entry)
                for entry in entries
                if entry.get("task_id") == normalized_task_id
            ]


class WorkLLMCreditLedger:
    """Idempotent monthly credit reservations and consumption."""

    def __init__(self, root: Path, config: WorkLLMConfig) -> None:
        self.root = Path(root)
        self.config = config
        self.path = self.root / "credit_ledger.json"
        self.lock_path = self.root / "credit_ledger.lock"
        self.history_root = self.root / "credit_history"

    def _new_state(self, month: str) -> dict[str, object]:
        if _MONTH_RE.fullmatch(month) is None:
            raise WorkLLMGovernanceError("workllm_credit_month_invalid")
        return {
            "schema": WORKLLM_CREDIT_LEDGER_SCHEMA,
            "month": month,
            "monthly_credit_limit": self.config.monthly_credit_limit,
            "soft_credit_limit": self.config.soft_credit_limit,
            "hard_credit_limit": self.config.hard_credit_limit,
            "reservations": {},
            "updated_at": _utc_now(),
        }

    def _validate_state(self, state: Mapping[str, object]) -> None:
        if state.get("schema") != WORKLLM_CREDIT_LEDGER_SCHEMA:
            raise WorkLLMGovernanceError("workllm_credit_ledger_schema_mismatch")
        if _MONTH_RE.fullmatch(str(state.get("month") or "")) is None:
            raise WorkLLMGovernanceError("workllm_credit_month_invalid")
        expected_limits = (
            self.config.monthly_credit_limit,
            self.config.soft_credit_limit,
            self.config.hard_credit_limit,
        )
        actual_limits = (
            state.get("monthly_credit_limit"),
            state.get("soft_credit_limit"),
            state.get("hard_credit_limit"),
        )
        if actual_limits != expected_limits:
            raise WorkLLMGovernanceError("workllm_credit_ledger_limit_mismatch")
        reservations = state.get("reservations")
        if not isinstance(reservations, dict):
            raise WorkLLMGovernanceError("workllm_credit_ledger_invalid")
        committed = 0
        for task_id, raw_reservation in reservations.items():
            if (
                not isinstance(task_id, str)
                or _SAFE_TASK_ID_RE.fullmatch(task_id) is None
                or not isinstance(raw_reservation, dict)
                or raw_reservation.get("task_id") != task_id
                or _SHA256_RE.fullmatch(
                    str(raw_reservation.get("request_sha256") or "")
                )
                is None
            ):
                raise WorkLLMGovernanceError(
                    "workllm_credit_ledger_invalid"
                )
            reserved_credits = raw_reservation.get("reserved_credits")
            consumed_credits = raw_reservation.get("consumed_credits")
            if (
                not isinstance(reserved_credits, int)
                or isinstance(reserved_credits, bool)
                or reserved_credits <= 0
                or reserved_credits > self.config.max_task_credits
                or not isinstance(consumed_credits, int)
                or isinstance(consumed_credits, bool)
                or consumed_credits < 0
                or consumed_credits > reserved_credits
            ):
                raise WorkLLMGovernanceError(
                    "workllm_credit_ledger_invalid"
                )
            status_value = str(raw_reservation.get("status") or "")
            reserved_at = str(
                raw_reservation.get("reserved_at") or ""
            ).strip()
            finalized_at = str(
                raw_reservation.get("finalized_at") or ""
            ).strip()
            if (
                not reserved_at
                or _month_from_timestamp(reserved_at) != state["month"]
                or status_value
                not in {"reserved", "consumed", "cancelled"}
            ):
                raise WorkLLMGovernanceError(
                    "workllm_credit_ledger_invalid"
                )
            if status_value == "reserved":
                if consumed_credits != 0 or finalized_at:
                    raise WorkLLMGovernanceError(
                        "workllm_credit_ledger_invalid"
                    )
                committed += reserved_credits
            elif status_value == "consumed":
                if not finalized_at:
                    raise WorkLLMGovernanceError(
                        "workllm_credit_ledger_invalid"
                    )
                _month_from_timestamp(finalized_at)
                committed += consumed_credits
            else:
                if (
                    consumed_credits != 0
                    or not finalized_at
                    or not str(
                        raw_reservation.get("cancellation_reason") or ""
                    ).strip()
                ):
                    raise WorkLLMGovernanceError(
                        "workllm_credit_ledger_invalid"
                    )
                _month_from_timestamp(finalized_at)
        if committed > self.config.hard_credit_limit:
            raise WorkLLMGovernanceError(
                "workllm_hard_credit_limit_exceeded"
            )

    def _load_state_unlocked(self, month: str) -> dict[str, object]:
        if not self.path.exists():
            return self._new_state(month)
        _assert_private_regular_file(self.path)
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise WorkLLMGovernanceError("workllm_credit_ledger_invalid") from None
        if not isinstance(loaded, dict):
            raise WorkLLMGovernanceError("workllm_credit_ledger_invalid")
        state = dict(loaded)
        self._validate_state(state)
        existing_month = str(state["month"])
        if existing_month == month:
            return state
        archive = dict(state)
        archive["ledger_sha256"] = _sha256_payload(state)
        archive_path = self.history_root / f"credit_ledger-{existing_month}.json"
        if archive_path.exists():
            try:
                current_archive = json.loads(archive_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                raise WorkLLMGovernanceError(
                    "workllm_credit_history_invalid"
                ) from None
            if current_archive != archive:
                raise WorkLLMGovernanceError(
                    "workllm_credit_history_conflict"
                )
        else:
            _atomic_write_json(archive_path, archive)
        return self._new_state(month)

    @staticmethod
    def _summary_from_state(state: Mapping[str, object]) -> dict[str, object]:
        reservations = state.get("reservations")
        if not isinstance(reservations, Mapping):
            raise WorkLLMGovernanceError("workllm_credit_ledger_invalid")
        reserved = 0
        consumed = 0
        cancelled = 0
        for raw in reservations.values():
            if not isinstance(raw, Mapping):
                raise WorkLLMGovernanceError("workllm_credit_ledger_invalid")
            status_value = str(raw.get("status") or "")
            if status_value == "reserved":
                reserved += int(raw.get("reserved_credits") or 0)
            elif status_value == "consumed":
                consumed += int(raw.get("consumed_credits") or 0)
            elif status_value == "cancelled":
                cancelled += 1
            else:
                raise WorkLLMGovernanceError("workllm_credit_status_invalid")
        committed = consumed + reserved
        return {
            "schema": "executive_assistant.workllm_credit_summary.v1",
            "month": state["month"],
            "consumed_credits": consumed,
            "active_reserved_credits": reserved,
            "committed_credits": committed,
            "cancelled_reservations": cancelled,
            "soft_limit": state["soft_credit_limit"],
            "hard_limit": state["hard_credit_limit"],
            "monthly_limit": state["monthly_credit_limit"],
            "soft_limit_exceeded": committed > int(state["soft_credit_limit"]),
            "hard_limit_exceeded": committed > int(state["hard_credit_limit"]),
            "remaining_before_hard_limit": max(
                0,
                int(state["hard_credit_limit"]) - committed,
            ),
        }

    def summary(self, *, at: str | None = None) -> dict[str, object]:
        month = _month_from_timestamp(at)
        with _exclusive_lock(self.lock_path):
            state = self._load_state_unlocked(month)
            _atomic_write_json(self.path, state)
            return self._summary_from_state(state)

    def reserve(
        self,
        packet: WorkLLMTaskPacket,
        *,
        reserved_at: str | None = None,
    ) -> dict[str, object]:
        packet.verify_digest()
        month = _month_from_timestamp(reserved_at)
        with _exclusive_lock(self.lock_path):
            state = self._load_state_unlocked(month)
            reservations = state["reservations"]
            if not isinstance(reservations, dict):
                raise WorkLLMGovernanceError("workllm_credit_ledger_invalid")
            existing = reservations.get(packet.task_id)
            if existing is not None:
                if not isinstance(existing, dict):
                    raise WorkLLMGovernanceError("workllm_credit_ledger_invalid")
                if (
                    existing.get("request_sha256") == packet.request_sha256
                    and existing.get("reserved_credits") == packet.max_credits
                    and existing.get("status") == "reserved"
                ):
                    return {
                        **dict(existing),
                        "idempotent": True,
                        "summary": self._summary_from_state(state),
                    }
                raise WorkLLMGovernanceError(
                    "workllm_credit_reservation_conflict"
                )
            summary = self._summary_from_state(state)
            projected = int(summary["committed_credits"]) + packet.max_credits
            if projected > self.config.hard_credit_limit:
                raise WorkLLMGovernanceError(
                    "workllm_hard_credit_limit_exceeded"
                )
            reservation: dict[str, object] = {
                "task_id": packet.task_id,
                "request_sha256": packet.request_sha256,
                "reserved_credits": packet.max_credits,
                "consumed_credits": 0,
                "status": "reserved",
                "reserved_at": str(reserved_at or _utc_now()).strip(),
                "finalized_at": "",
            }
            reservations[packet.task_id] = reservation
            state["updated_at"] = str(reserved_at or _utc_now()).strip()
            _atomic_write_json(self.path, state)
            return {
                **reservation,
                "idempotent": False,
                "summary": self._summary_from_state(state),
            }

    def consume(
        self,
        *,
        task_id: str,
        request_sha256: str,
        credits_consumed: int,
        consumed_at: str | None = None,
    ) -> dict[str, object]:
        if credits_consumed < 0:
            raise WorkLLMGovernanceError("workllm_credit_usage_invalid")
        month = _month_from_timestamp(consumed_at)
        with _exclusive_lock(self.lock_path):
            state = self._load_state_unlocked(month)
            reservations = state["reservations"]
            if not isinstance(reservations, dict):
                raise WorkLLMGovernanceError("workllm_credit_ledger_invalid")
            reservation = reservations.get(task_id)
            if not isinstance(reservation, dict):
                raise WorkLLMGovernanceError(
                    "workllm_credit_reservation_missing"
                )
            if reservation.get("request_sha256") != request_sha256:
                raise WorkLLMGovernanceError(
                    "workllm_credit_reservation_conflict"
                )
            if reservation.get("status") == "consumed":
                if reservation.get("consumed_credits") == credits_consumed:
                    return {
                        **dict(reservation),
                        "idempotent": True,
                        "summary": self._summary_from_state(state),
                    }
                raise WorkLLMGovernanceError(
                    "workllm_credit_consumption_conflict"
                )
            if reservation.get("status") != "reserved":
                raise WorkLLMGovernanceError(
                    "workllm_credit_reservation_finalized"
                )
            if credits_consumed > int(reservation.get("reserved_credits") or 0):
                raise WorkLLMGovernanceError(
                    "workllm_result_credit_usage_invalid"
                )
            reservation["status"] = "consumed"
            reservation["consumed_credits"] = credits_consumed
            reservation["finalized_at"] = str(consumed_at or _utc_now()).strip()
            state["updated_at"] = reservation["finalized_at"]
            _atomic_write_json(self.path, state)
            return {
                **dict(reservation),
                "idempotent": False,
                "summary": self._summary_from_state(state),
            }

    def reservation(
        self,
        *,
        task_id: str,
        request_sha256: str,
        at: str | None = None,
    ) -> dict[str, object]:
        month = _month_from_timestamp(at)
        with _exclusive_lock(self.lock_path):
            state = self._load_state_unlocked(month)
            reservations = state["reservations"]
            if not isinstance(reservations, dict):
                raise WorkLLMGovernanceError("workllm_credit_ledger_invalid")
            reservation = reservations.get(task_id)
            if not isinstance(reservation, dict):
                raise WorkLLMGovernanceError(
                    "workllm_credit_reservation_missing"
                )
            if reservation.get("request_sha256") != request_sha256:
                raise WorkLLMGovernanceError(
                    "workllm_credit_reservation_conflict"
                )
            return dict(reservation)

    def cancel(
        self,
        *,
        task_id: str,
        request_sha256: str,
        reason: str,
        cancelled_at: str | None = None,
    ) -> dict[str, object]:
        normalized_reason, redactions = redact_workllm_text(reason)
        if not normalized_reason.strip():
            raise WorkLLMGovernanceError("workllm_cancellation_reason_missing")
        month = _month_from_timestamp(cancelled_at)
        with _exclusive_lock(self.lock_path):
            state = self._load_state_unlocked(month)
            reservations = state["reservations"]
            if not isinstance(reservations, dict):
                raise WorkLLMGovernanceError("workllm_credit_ledger_invalid")
            reservation = reservations.get(task_id)
            if not isinstance(reservation, dict):
                raise WorkLLMGovernanceError(
                    "workllm_credit_reservation_missing"
                )
            if reservation.get("request_sha256") != request_sha256:
                raise WorkLLMGovernanceError(
                    "workllm_credit_reservation_conflict"
                )
            if reservation.get("status") == "cancelled":
                return {
                    **dict(reservation),
                    "idempotent": True,
                    "summary": self._summary_from_state(state),
                }
            if reservation.get("status") != "reserved":
                raise WorkLLMGovernanceError(
                    "workllm_credit_reservation_finalized"
                )
            reservation["status"] = "cancelled"
            reservation["cancellation_reason"] = normalized_reason
            reservation["cancellation_redactions"] = list(redactions)
            reservation["finalized_at"] = str(cancelled_at or _utc_now()).strip()
            state["updated_at"] = reservation["finalized_at"]
            _atomic_write_json(self.path, state)
            return {
                **dict(reservation),
                "idempotent": False,
                "summary": self._summary_from_state(state),
            }


class GovernedWorkLLMManualLane:
    """Local operator boundary around a governed, still-manual WorkLLM run."""

    def __init__(
        self,
        sidecar: WorkLLMSidecar,
        *,
        governance_root: Path | None = None,
    ) -> None:
        self.sidecar = sidecar
        root = Path(
            governance_root
            or (self.sidecar.config.receipt_root / "governance")
        )
        self.audit = WorkLLMAuditLedger(root)
        self.credits = WorkLLMCreditLedger(root, self.sidecar.config)

    def stage_packet(
        self,
        packet: WorkLLMTaskPacket,
        *,
        actor_ref: str,
        occurred_at: str | None = None,
    ) -> dict[str, object]:
        packet.verify_digest()
        packet_path = (
            self.sidecar.config.receipt_root
            / packet.task_id
            / "task_packet.json"
        )
        _atomic_write_json(packet_path, packet.to_dict())
        audit_event = self.audit.append(
            event_type="task_prepared",
            actor_ref=actor_ref,
            task_id=packet.task_id,
            correlation_id=packet.correlation_id,
            receipt=packet.to_dict(),
            details={
                "lane": packet.lane,
                "data_classification": packet.data_classification,
                "request_sha256": packet.request_sha256,
                "max_credits": packet.max_credits,
            },
            occurred_at=occurred_at,
        )
        return {
            "task_packet_path": str(packet_path),
            "request_sha256": packet.request_sha256,
            "audit_event_sha256": audit_event["event_sha256"],
        }

    def authorize(
        self,
        packet: WorkLLMTaskPacket,
        *,
        actor_ref: str,
        authorized_at: str | None = None,
    ) -> dict[str, object]:
        summary = self.credits.summary(at=authorized_at)
        authorization = self.sidecar.authorize_submission(
            packet,
            mode="manual_browser",
            monthly_credits_used=int(summary["committed_credits"]),
        )
        reservation = self.credits.reserve(
            packet,
            reserved_at=authorized_at,
        )
        audit_event = self.audit.append(
            event_type="submission_authorized",
            actor_ref=actor_ref,
            task_id=packet.task_id,
            correlation_id=packet.correlation_id,
            receipt=authorization,
            details={
                "request_sha256": packet.request_sha256,
                "reserved_credits": packet.max_credits,
                "projected_monthly_credits": authorization[
                    "projected_monthly_credits"
                ],
            },
            occurred_at=authorized_at,
        )
        return {
            "authorization": authorization,
            "reservation": reservation,
            "audit_event_sha256": audit_event["event_sha256"],
        }

    def capture(
        self,
        packet: WorkLLMTaskPacket,
        *,
        output_text: str,
        actor_ref: str,
        observed_models: Sequence[str] = (),
        credits_consumed: int,
        provider_job_ref: str = "",
        provider_surface_receipt_sha256: str,
        captured_at: str | None = None,
    ) -> dict[str, object]:
        reservation = self.credits.reservation(
            task_id=packet.task_id,
            request_sha256=packet.request_sha256,
            at=captured_at,
        )
        if reservation.get("status") != "reserved":
            raise WorkLLMGovernanceError(
                "workllm_credit_reservation_finalized"
            )
        receipt = self.sidecar.persist_manual_result(
            packet,
            output_text=output_text,
            observed_models=observed_models,
            credits_consumed=credits_consumed,
            provider_job_ref=provider_job_ref,
            provider_interaction_observed=True,
            provider_surface_receipt_sha256=(
                provider_surface_receipt_sha256
            ),
            captured_at=captured_at,
        )
        consumption = self.credits.consume(
            task_id=packet.task_id,
            request_sha256=packet.request_sha256,
            credits_consumed=credits_consumed,
            consumed_at=captured_at,
        )
        audit_event = self.audit.append(
            event_type="result_captured",
            actor_ref=actor_ref,
            task_id=packet.task_id,
            correlation_id=packet.correlation_id,
            receipt=receipt,
            details={
                "request_sha256": packet.request_sha256,
                "output_sha256": receipt["output_sha256"],
                "credits_consumed": credits_consumed,
                "model_provenance_status": receipt[
                    "model_provenance_status"
                ],
            },
            occurred_at=captured_at,
        )
        return {
            "receipt": receipt,
            "consumption": consumption,
            "audit_event_sha256": audit_event["event_sha256"],
        }

    def review(
        self,
        receipt: Mapping[str, object],
        *,
        actor_ref: str,
        decision: str,
        schema_valid: bool,
        safety_valid: bool,
        reviewed_at: str | None = None,
    ) -> dict[str, object]:
        if receipt.get("schema") != WORKLLM_RUN_RECEIPT_SCHEMA:
            raise WorkLLMGovernanceError("workllm_run_receipt_schema_mismatch")
        task_id = str(receipt.get("task_id") or "").strip()
        if _SAFE_TASK_ID_RE.fullmatch(task_id) is None:
            raise WorkLLMGovernanceError("workllm_task_identifier_invalid")
        reviewed = self.sidecar.mark_reviewed(
            receipt,
            reviewer_ref=actor_ref,
            decision=decision,
            schema_valid=schema_valid,
            safety_valid=safety_valid,
            reviewed_at=reviewed_at,
        )
        receipt_path = (
            self.sidecar.config.receipt_root
            / task_id
            / "run_receipt.json"
        )
        _atomic_write_json(receipt_path, reviewed)
        audit_event = self.audit.append(
            event_type="review_completed",
            actor_ref=actor_ref,
            task_id=task_id,
            correlation_id=str(receipt.get("correlation_id") or ""),
            receipt=reviewed,
            details={
                "request_sha256": str(
                    receipt.get("request_sha256") or ""
                ),
                "decision": decision,
                "schema_valid": schema_valid,
                "safety_valid": safety_valid,
                "candidate_accepted": reviewed["candidate_accepted"],
            },
            occurred_at=reviewed_at,
        )
        return {
            "receipt": reviewed,
            "receipt_path": str(receipt_path),
            "audit_event_sha256": audit_event["event_sha256"],
        }

    def cancel(
        self,
        packet: WorkLLMTaskPacket,
        *,
        actor_ref: str,
        reason: str,
        cancelled_at: str | None = None,
    ) -> dict[str, object]:
        cancellation = self.credits.cancel(
            task_id=packet.task_id,
            request_sha256=packet.request_sha256,
            reason=reason,
            cancelled_at=cancelled_at,
        )
        audit_event = self.audit.append(
            event_type="credit_reservation_cancelled",
            actor_ref=actor_ref,
            task_id=packet.task_id,
            correlation_id=packet.correlation_id,
            receipt=cancellation,
            details={
                "request_sha256": packet.request_sha256,
                "reason": reason,
            },
            occurred_at=cancelled_at,
        )
        return {
            "cancellation": cancellation,
            "audit_event_sha256": audit_event["event_sha256"],
        }

    def engage_rollback(
        self,
        *,
        actor_ref: str,
        reason: str,
        engaged_at: str | None = None,
    ) -> dict[str, object]:
        normalized_reason, redactions = redact_workllm_text(reason)
        if not normalized_reason.strip():
            raise WorkLLMGovernanceError("workllm_rollback_reason_missing")
        timestamp = str(engaged_at or _utc_now()).strip()
        posture_before = self.sidecar.config.public_posture()
        control_state: dict[str, object] = {
            "schema": WORKLLM_CONTROL_STATE_SCHEMA,
            "kill_switch_engaged": True,
            "engaged_at": timestamp,
            "reason": normalized_reason,
            "reason_redactions": list(redactions),
            "actor_ref_sha256": _sha256_text(str(actor_ref or "").strip()),
            "release_supported_by_runtime": False,
        }
        if not str(actor_ref or "").strip():
            raise WorkLLMGovernanceError("workllm_audit_actor_missing")
        _atomic_write_json(
            self.sidecar.config.control_state_file,
            control_state,
        )
        rollback_receipt: dict[str, object] = {
            "schema": WORKLLM_ROLLBACK_RECEIPT_SCHEMA,
            "provider": "workllm",
            "engaged_at": timestamp,
            "reason": normalized_reason,
            "reason_redactions": list(redactions),
            "actor_ref_sha256": control_state["actor_ref_sha256"],
            "posture_before": posture_before,
            "control_state_sha256": _sha256_payload(control_state),
            "kill_switch_effective": self.sidecar.config.kill_switch_active(),
            "required_runtime_posture": {
                "EA_WORKLLM_KILL_SWITCH": "1",
                "EA_WORKLLM_MANUAL_LANE_ENABLED": "0",
                "EA_WORKLLM_INTERNAL_NONSECRET_ENABLED": "0",
                "WORKLLM_RUNTIME_ENABLED": "0",
                "EA_WORKLLM_API_LANE_ENABLED": "0",
            },
            "release_requires_manual_control_file_removal": True,
            "canonical_promotion_authority": False,
        }
        receipt_path = (
            self.sidecar.config.receipt_root
            / "governance"
            / f"rollback-{_timestamp_slug(timestamp)}.json"
        )
        _atomic_write_json(receipt_path, rollback_receipt)
        audit_event = self.audit.append(
            event_type="rollback_engaged",
            actor_ref=actor_ref,
            receipt=rollback_receipt,
            details={
                "reason": normalized_reason,
                "kill_switch_effective": rollback_receipt[
                    "kill_switch_effective"
                ],
            },
            occurred_at=timestamp,
        )
        return {
            "receipt": rollback_receipt,
            "receipt_path": str(receipt_path),
            "control_state_path": str(
                self.sidecar.config.control_state_file
            ),
            "audit_event_sha256": audit_event["event_sha256"],
        }
