#!/usr/bin/env python3
"""Certificate-bound root authority for Manfred candidate Docker mutations.

The candidate producer and runner stay non-root.  They hold the fixed root
coordination lock and ask the fixed, independently installed permit manager to
validate the live schema-v6 state, exact-epoch certificate, and candidate-mode
permit.  No Python is imported from an operator checkout by the root authority.
"""

from __future__ import annotations

import fcntl
import json
import math
import os
import pwd
import stat
import subprocess  # nosec B404 - fixed interpreter and manager paths below
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, Mapping, Sequence


CANDIDATE_VEXP_MUTATION_PERMIT_CONTRACT_NAME = (
    "ea.vexp_manfred_candidate_mutation_permit.v2"
)
CANDIDATE_VEXP_MUTATION_PERMIT_VERSION = 2
CANDIDATE_VEXP_MUTATION_BOUNDARIES = (
    "before_candidate_image_build",
    "before_candidate_up",
    "before_candidate_exec",
    "before_candidate_interaction",
    "before_candidate_restart",
    "before_candidate_cleanup",
)
CANDIDATE_PERMIT_MODE = "candidate"
VEXP_QUALIFICATION_CERTIFICATE_SCHEMA = "ea.vexp_qualification_certificate.v2"

TRUSTED_MANAGER_PATH = Path(
    "/usr/local/libexec/ea/manage-manfred-vexp-mutation-permit"
)
TRUSTED_PYTHON_PATH = Path("/usr/bin/python3")
DEFAULT_SENTINEL_STATE_PATH = Path(pwd.getpwuid(os.geteuid()).pw_dir) / (
    ".local/state/vexp-sentinel/state.json"
)
MUTATION_PERMIT_LOCK_PATH = Path(
    "/run/ea/memorial-vexp-mutation-permit.lock"
)
MUTATION_AUTHORITY_TRUSTED_PARENT = Path("/run")
ROOT_UID = 0
ROOT_GID = 0
LOCK_MODE = 0o644
MAX_STATUS_BYTES = 16 * 1024
STATUS_TIMEOUT_SECONDS = 30
LEASE_EXPIRY_MARGIN_SECONDS = 1.0
SHA256_HEX_LENGTH = 64
PERMIT_COMMIT_CONTRACT_NAME = "ea.vexp_mutation_permit_commit.v1"
PERMIT_COMMIT_VERSION = 1
EPOCH_VOID_LEDGER_ROOT = Path("/var/lib/vexp-qualification-epoch-voids")
PERMIT_COMMIT_KEYS = frozenset(
    {"contract_name", "version", "status", "sha256"}
)
EPOCH_VOID_LEDGER_KEYS = frozenset(
    {"root", "entry", "entry_present", "root_trusted"}
)
CURRENT_PREDICATE_CONTRACT_NAME = "ea.vexp_current_predicate.v1"
CURRENT_PREDICATE_VERSION = 1
CURRENT_PREDICATE_KEYS = frozenset(
    {
        "contract_name",
        "version",
        "status",
        "epoch_started_ms",
        "generation",
        "record_sha256",
        "boot_id",
        "monotonic_ns",
        "sentinel_producer_sha256",
        "root_predicate_producer_sha256",
    }
)
CANDIDATE_EVIDENCE_KEYS = frozenset(
    {"attestor_sha256", "producer_manifest_sha256"}
)
# Deliberately exact. Never accept authority extensions through permissive
# forward compatibility.
STATUS_KEYS = frozenset(
    {
        "status",
        "contract_name",
        "epoch_started_ms",
        "qualified_at",
        "issued_at",
        "expires_at",
        "terminal_identity_sha256",
        "qualification_certificate_schema",
        "qualification_certificate_sha256",
        "qualification_certificate_identity",
        "qualification_certificate_event_hash",
        "permit_sha256",
        "permit_commit",
        "epoch_void_ledger",
        "current_predicate",
        "candidate_evidence",
        "mutation_boundaries",
    }
)


class CandidateAuthorityError(RuntimeError):
    """A fail-closed candidate authority error."""


StatusInvoker = Callable[
    [Sequence[str], Mapping[str, str]], subprocess.CompletedProcess[bytes]
]


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == SHA256_HEX_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _parse_utc(value: object, *, reason: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise CandidateAuthorityError(reason)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CandidateAuthorityError(reason) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise CandidateAuthorityError(reason)
    return parsed.astimezone(timezone.utc)


def _file_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _directory_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_gid,
    )


def _decode_status(raw: bytes) -> dict[str, object]:
    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        payload: dict[str, object] = {}
        for key, value in pairs:
            if key in payload:
                raise ValueError("duplicate_json_key")
            payload[key] = value
        return payload

    def reject_constant(_value: str) -> None:
        raise ValueError("non_finite_json_constant")

    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise CandidateAuthorityError(
            "manfred_candidate_vexp_status_invalid"
        ) from exc
    if not isinstance(payload, dict):
        raise CandidateAuthorityError("manfred_candidate_vexp_status_invalid")
    return payload


@dataclass(frozen=True)
class CandidateMutationLease:
    boundary: str
    deadline_monotonic: float
    authority_evidence: dict[str, object]
    monotonic: Callable[[], float]

    def command_timeout(self, requested_seconds: float) -> float:
        if (
            isinstance(requested_seconds, bool)
            or not isinstance(requested_seconds, (int, float))
            or not math.isfinite(float(requested_seconds))
            or float(requested_seconds) <= 0
        ):
            raise CandidateAuthorityError(
                "manfred_candidate_vexp_action_timeout_invalid"
            )
        try:
            current = self.monotonic()
        except Exception as exc:
            raise CandidateAuthorityError(
                "manfred_candidate_vexp_monotonic_invalid"
            ) from exc
        if (
            isinstance(current, bool)
            or not isinstance(current, (int, float))
            or not math.isfinite(float(current))
        ):
            raise CandidateAuthorityError(
                "manfred_candidate_vexp_monotonic_invalid"
            )
        remaining = self.deadline_monotonic - float(current)
        timeout = min(float(requested_seconds), remaining)
        if not math.isfinite(timeout) or timeout <= 0:
            raise CandidateAuthorityError(
                "manfred_candidate_vexp_action_authority_expired"
            )
        return timeout


class CandidateVexpMutationAuthority:
    """Validate and lease the fixed candidate-mode root authority."""

    def __init__(
        self,
        *,
        state_path: Path,
        state_owner_uid: int,
        lock_path: Path = MUTATION_PERMIT_LOCK_PATH,
        lock_owner_uid: int = ROOT_UID,
        lock_owner_gid: int = ROOT_GID,
        authority_trusted_parent: Path = MUTATION_AUTHORITY_TRUSTED_PARENT,
        authority_directory_owner_uid: int = ROOT_UID,
        authority_directory_owner_gid: int = ROOT_GID,
        manager_path: Path = TRUSTED_MANAGER_PATH,
        python_path: Path = TRUSTED_PYTHON_PATH,
        utc_now: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        status_invoker: StatusInvoker | None = None,
    ) -> None:
        self.state_path = Path(state_path)
        self.state_owner_uid = state_owner_uid
        self.lock_path = Path(lock_path)
        self.lock_owner_uid = lock_owner_uid
        self.lock_owner_gid = lock_owner_gid
        self.authority_trusted_parent = Path(authority_trusted_parent)
        self.authority_directory_owner_uid = authority_directory_owner_uid
        self.authority_directory_owner_gid = authority_directory_owner_gid
        self.manager_path = Path(manager_path)
        self.python_path = Path(python_path)
        self._utc_now = utc_now or (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic or time.monotonic
        self._status_invoker = status_invoker
        self._validate_configuration()

    def _validate_configuration(self) -> None:
        if not self.state_path.is_absolute():
            raise CandidateAuthorityError(
                "manfred_candidate_vexp_state_path_not_absolute"
            )
        if (
            type(self.state_owner_uid) is not int
            or self.state_owner_uid < 0
            or self.state_owner_uid != os.geteuid()
        ):
            raise CandidateAuthorityError(
                "manfred_candidate_vexp_state_owner_invalid"
            )
        for path in (self.lock_path, self.manager_path, self.python_path):
            if not path.is_absolute():
                raise CandidateAuthorityError(
                    "manfred_candidate_vexp_authority_path_invalid"
                )
        if (
            type(self.lock_owner_uid) is not int
            or self.lock_owner_uid < 0
            or type(self.lock_owner_gid) is not int
            or self.lock_owner_gid < 0
        ):
            raise CandidateAuthorityError(
                "manfred_candidate_vexp_lock_owner_invalid"
            )
        if (
            not self.authority_trusted_parent.is_absolute()
            or ".." in self.authority_trusted_parent.parts
            or type(self.authority_directory_owner_uid) is not int
            or self.authority_directory_owner_uid < 0
            or type(self.authority_directory_owner_gid) is not int
            or self.authority_directory_owner_gid < 0
        ):
            raise CandidateAuthorityError(
                "manfred_candidate_vexp_authority_directory_invalid"
            )
        expected_directory = self.authority_trusted_parent
        if self.authority_trusted_parent == MUTATION_AUTHORITY_TRUSTED_PARENT:
            expected_directory = self.authority_trusted_parent / "ea"
        if self.lock_path.parent != expected_directory:
            raise CandidateAuthorityError(
                "manfred_candidate_vexp_authority_directory_invalid"
            )

    def _authority_directory_chain_identity(self) -> tuple[tuple[int, ...], ...]:
        trusted_parent = self.authority_trusted_parent
        if trusted_parent == MUTATION_AUTHORITY_TRUSTED_PARENT:
            chain = (Path("/"), trusted_parent, self.lock_path.parent)
        else:
            chain = (trusted_parent,)
        identities: list[tuple[int, ...]] = []
        for path in chain:
            try:
                metadata = os.stat(path, follow_symlinks=False)
            except OSError as exc:
                raise CandidateAuthorityError(
                    "manfred_candidate_vexp_authority_directory_unavailable"
                ) from exc
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o755
                or metadata.st_uid != self.authority_directory_owner_uid
                or metadata.st_gid != self.authority_directory_owner_gid
            ):
                raise CandidateAuthorityError(
                    "manfred_candidate_vexp_authority_directory_untrusted"
                )
            identities.append(_directory_identity(metadata))
        return tuple(identities)

    def _now(self) -> datetime:
        try:
            now = self._utc_now()
        except Exception as exc:
            raise CandidateAuthorityError(
                "manfred_candidate_vexp_clock_invalid"
            ) from exc
        if (
            not isinstance(now, datetime)
            or now.tzinfo is None
            or now.utcoffset() != timezone.utc.utcoffset(now)
        ):
            raise CandidateAuthorityError("manfred_candidate_vexp_clock_invalid")
        return now.astimezone(timezone.utc)

    def _monotonic_now(self) -> float:
        try:
            value = self._monotonic()
        except Exception as exc:
            raise CandidateAuthorityError(
                "manfred_candidate_vexp_monotonic_invalid"
            ) from exc
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise CandidateAuthorityError(
                "manfred_candidate_vexp_monotonic_invalid"
            )
        return float(value)

    def _invoke_status(self) -> subprocess.CompletedProcess[bytes]:
        argv = [
            str(self.python_path),
            "-I",
            str(self.manager_path),
            "status",
            "--state-path",
            str(self.state_path),
            "--state-owner-uid",
            str(self.state_owner_uid),
            "--permit-mode",
            CANDIDATE_PERMIT_MODE,
        ]
        environment = {
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": "/usr/bin:/bin",
        }
        try:
            if self._status_invoker is not None:
                completed = self._status_invoker(argv, environment)
            else:
                completed = subprocess.run(  # nosec B603 - fixed argv contract
                    argv,
                    check=False,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=STATUS_TIMEOUT_SECONDS,
                    env=environment,
                )
        except (OSError, subprocess.SubprocessError) as exc:
            raise CandidateAuthorityError(
                "manfred_candidate_vexp_authority_unavailable"
            ) from exc
        if (
            not isinstance(completed, subprocess.CompletedProcess)
            or type(completed.returncode) is not int
            or completed.returncode != 0
            or not isinstance(completed.stdout, bytes)
            or not isinstance(completed.stderr, bytes)
            or len(completed.stdout) <= 0
            or len(completed.stdout) > MAX_STATUS_BYTES
            or len(completed.stderr) > MAX_STATUS_BYTES
        ):
            raise CandidateAuthorityError("manfred_candidate_vexp_authority_denied")
        return completed

    def _current_status(self) -> tuple[dict[str, object], datetime]:
        payload = _decode_status(self._invoke_status().stdout)
        if set(payload) != STATUS_KEYS:
            raise CandidateAuthorityError("manfred_candidate_vexp_status_invalid")
        if (
            payload.get("status") != "valid"
            or payload.get("contract_name")
            != CANDIDATE_VEXP_MUTATION_PERMIT_CONTRACT_NAME
            or payload.get("qualification_certificate_schema")
            != VEXP_QUALIFICATION_CERTIFICATE_SCHEMA
            or payload.get("mutation_boundaries")
            != list(CANDIDATE_VEXP_MUTATION_BOUNDARIES)
            or type(payload.get("epoch_started_ms")) is not int
            or int(payload["epoch_started_ms"]) <= 0
            or not _is_sha256(payload.get("terminal_identity_sha256"))
            or not _is_sha256(payload.get("qualification_certificate_sha256"))
            or not _is_sha256(
                payload.get("qualification_certificate_event_hash")
            )
            or not _is_sha256(payload.get("permit_sha256"))
        ):
            raise CandidateAuthorityError("manfred_candidate_vexp_status_invalid")
        certificate_identity = payload.get("qualification_certificate_identity")
        if (
            not isinstance(certificate_identity, str)
            or not certificate_identity.startswith("sha256:")
            or not _is_sha256(certificate_identity.removeprefix("sha256:"))
        ):
            raise CandidateAuthorityError("manfred_candidate_vexp_status_invalid")
        permit_commit = payload.get("permit_commit")
        if (
            not isinstance(permit_commit, dict)
            or set(permit_commit) != PERMIT_COMMIT_KEYS
            or permit_commit.get("contract_name") != PERMIT_COMMIT_CONTRACT_NAME
            or type(permit_commit.get("version")) is not int
            or permit_commit["version"] != PERMIT_COMMIT_VERSION
            or permit_commit.get("status") != "committed"
            or not _is_sha256(permit_commit.get("sha256"))
        ):
            raise CandidateAuthorityError("manfred_candidate_vexp_status_invalid")
        void_ledger = payload.get("epoch_void_ledger")
        expected_entry = EPOCH_VOID_LEDGER_ROOT / f"{payload['epoch_started_ms']}.json"
        if (
            not isinstance(void_ledger, dict)
            or set(void_ledger) != EPOCH_VOID_LEDGER_KEYS
            or void_ledger.get("root") != str(EPOCH_VOID_LEDGER_ROOT)
            or void_ledger.get("entry") != str(expected_entry)
            or void_ledger.get("entry_present") is not False
            or void_ledger.get("root_trusted") is not True
        ):
            raise CandidateAuthorityError("manfred_candidate_vexp_status_invalid")
        predicate = payload.get("current_predicate")
        if (
            not isinstance(predicate, dict)
            or set(predicate) != CURRENT_PREDICATE_KEYS
            or predicate.get("contract_name") != CURRENT_PREDICATE_CONTRACT_NAME
            or predicate.get("version") != CURRENT_PREDICATE_VERSION
            or predicate.get("status") != "positive"
            or predicate.get("epoch_started_ms") != payload.get("epoch_started_ms")
            or type(predicate.get("generation")) is not int
            or predicate["generation"] <= 0
            or type(predicate.get("monotonic_ns")) is not int
            or predicate["monotonic_ns"] <= 0
            or any(
                not _is_sha256(predicate.get(name))
                for name in (
                    "record_sha256",
                    "sentinel_producer_sha256",
                    "root_predicate_producer_sha256",
                )
            )
            or not isinstance(predicate.get("boot_id"), str)
            or len(predicate["boot_id"]) != 36
        ):
            raise CandidateAuthorityError("manfred_candidate_vexp_status_invalid")
        candidate_evidence = payload.get("candidate_evidence")
        if (
            not isinstance(candidate_evidence, dict)
            or set(candidate_evidence) != CANDIDATE_EVIDENCE_KEYS
            or not _is_sha256(candidate_evidence.get("attestor_sha256"))
            or not _is_sha256(
                candidate_evidence.get("producer_manifest_sha256")
            )
        ):
            raise CandidateAuthorityError("manfred_candidate_vexp_status_invalid")
        qualified_at = _parse_utc(
            payload.get("qualified_at"),
            reason="manfred_candidate_vexp_status_invalid",
        )
        issued_at = _parse_utc(
            payload.get("issued_at"),
            reason="manfred_candidate_vexp_status_invalid",
        )
        expires_at = _parse_utc(
            payload.get("expires_at"),
            reason="manfred_candidate_vexp_status_invalid",
        )
        now = self._now()
        if issued_at < qualified_at or now < issued_at or now >= expires_at:
            raise CandidateAuthorityError(
                "manfred_candidate_vexp_authority_not_current"
            )
        return payload, expires_at

    def _safe_evidence(
        self,
        payload: Mapping[str, object],
        *,
        boundary: str,
        phase: str,
    ) -> dict[str, object]:
        return {
            "status": "pass",
            "phase": phase,
            "boundary": boundary,
            "contract_name": payload["contract_name"],
            "version": CANDIDATE_VEXP_MUTATION_PERMIT_VERSION,
            "epoch_started_ms": payload["epoch_started_ms"],
            "qualified_at": payload["qualified_at"],
            "terminal_identity_sha256": payload["terminal_identity_sha256"],
            "qualification_certificate_schema": payload[
                "qualification_certificate_schema"
            ],
            "qualification_certificate_sha256": payload[
                "qualification_certificate_sha256"
            ],
            "qualification_certificate_identity": payload[
                "qualification_certificate_identity"
            ],
            "qualification_certificate_event_hash": payload[
                "qualification_certificate_event_hash"
            ],
            "permit_sha256": payload["permit_sha256"],
            "permit_commit": dict(payload["permit_commit"]),
            "epoch_void_ledger": dict(payload["epoch_void_ledger"]),
            "permit_issued_at": payload["issued_at"],
            "permit_expires_at": payload["expires_at"],
            # This is the exact fresh predicate observed by the independently
            # installed manager for this authority row.  It is intentionally
            # not folded into the immutable permit tuple: predicate generations
            # may advance between operations while the terminal epoch and
            # certificate remain unchanged.
            "current_predicate": dict(payload["current_predicate"]),
        }

    @contextmanager
    def _shared_lock(self) -> Iterator[tuple[int, tuple[int, ...]]]:
        if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_NONBLOCK"):
            raise CandidateAuthorityError(
                "manfred_candidate_vexp_lock_safe_open_unavailable"
            )
        flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
        descriptor = -1
        locked = False
        initial_directory_chain = self._authority_directory_chain_identity()
        try:
            try:
                descriptor = os.open(self.lock_path, flags)
                metadata = os.fstat(descriptor)
            except OSError as exc:
                raise CandidateAuthorityError(
                    "manfred_candidate_vexp_lock_unavailable"
                ) from exc
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or stat.S_IMODE(metadata.st_mode) != LOCK_MODE
                or metadata.st_uid != self.lock_owner_uid
                or metadata.st_gid != self.lock_owner_gid
            ):
                raise CandidateAuthorityError(
                    "manfred_candidate_vexp_lock_untrusted"
                )
            try:
                fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
                locked = True
            except BlockingIOError as exc:
                raise CandidateAuthorityError(
                    "manfred_candidate_vexp_lock_busy"
                ) from exc
            except OSError as exc:
                raise CandidateAuthorityError(
                    "manfred_candidate_vexp_lock_unavailable"
                ) from exc
            initial_identity = _file_identity(metadata)
            self._require_same_lock(
                descriptor,
                initial_identity,
                initial_directory_chain,
            )
            try:
                yield descriptor, initial_identity
            except BaseException as action_error:
                try:
                    self._require_same_lock(
                        descriptor,
                        initial_identity,
                        initial_directory_chain,
                    )
                except BaseException as postcheck_error:
                    raise postcheck_error from action_error
                raise
            else:
                self._require_same_lock(
                    descriptor,
                    initial_identity,
                    initial_directory_chain,
                )
        finally:
            release_error: CandidateAuthorityError | None = None
            if locked:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                except OSError as exc:
                    release_error = CandidateAuthorityError(
                        "manfred_candidate_vexp_lock_release_failed"
                    )
                    release_error.__cause__ = exc
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError as exc:
                    release_error = CandidateAuthorityError(
                        "manfred_candidate_vexp_lock_close_failed"
                    )
                    release_error.__cause__ = exc
            if release_error is not None:
                raise release_error

    def _require_same_lock(
        self,
        descriptor: int,
        expected_identity: tuple[int, ...],
        expected_directory_chain: tuple[tuple[int, ...], ...],
    ) -> None:
        try:
            descriptor_metadata = os.fstat(descriptor)
            path_metadata = os.stat(self.lock_path, follow_symlinks=False)
        except OSError as exc:
            raise CandidateAuthorityError(
                "manfred_candidate_vexp_lock_changed"
            ) from exc
        if (
            _file_identity(descriptor_metadata) != expected_identity
            or _file_identity(path_metadata) != expected_identity
            or self._authority_directory_chain_identity()
            != expected_directory_chain
        ):
            raise CandidateAuthorityError("manfred_candidate_vexp_lock_changed")

    def require_current(self) -> dict[str, object]:
        with self._shared_lock():
            payload, _expires_at = self._current_status()
            return self._safe_evidence(
                payload,
                boundary="candidate_entry",
                phase="entry",
            )

    @contextmanager
    def mutation(
        self,
        boundary: str,
        *,
        minimum_validity_seconds: float,
    ) -> Iterator[CandidateMutationLease]:
        if boundary not in CANDIDATE_VEXP_MUTATION_BOUNDARIES:
            raise CandidateAuthorityError(
                "manfred_candidate_vexp_boundary_invalid"
            )
        if (
            isinstance(minimum_validity_seconds, bool)
            or not isinstance(minimum_validity_seconds, (int, float))
            or not math.isfinite(float(minimum_validity_seconds))
            or float(minimum_validity_seconds) <= 0
        ):
            raise CandidateAuthorityError(
                "manfred_candidate_vexp_minimum_validity_invalid"
            )
        with self._shared_lock():
            before, expires_at = self._current_status()
            remaining = (expires_at - self._now()).total_seconds()
            required = (
                float(minimum_validity_seconds)
                + STATUS_TIMEOUT_SECONDS
                + LEASE_EXPIRY_MARGIN_SECONDS
            )
            if not math.isfinite(remaining) or remaining <= required:
                raise CandidateAuthorityError(
                    "manfred_candidate_vexp_authority_window_too_short"
                )
            deadline = (
                self._monotonic_now()
                + remaining
                - STATUS_TIMEOUT_SECONDS
                - LEASE_EXPIRY_MARGIN_SECONDS
            )
            if not math.isfinite(deadline):
                raise CandidateAuthorityError(
                    "manfred_candidate_vexp_monotonic_invalid"
                )
            lease = CandidateMutationLease(
                boundary=boundary,
                deadline_monotonic=deadline,
                authority_evidence=self._safe_evidence(
                    before,
                    boundary=boundary,
                    phase="pre_mutation",
                ),
                monotonic=self._monotonic_now,
            )

            def require_postconditions() -> None:
                after, _after_expires_at = self._current_status()
                if after != before:
                    raise CandidateAuthorityError(
                        "manfred_candidate_vexp_authority_changed"
                    )
                if self._monotonic_now() >= deadline:
                    raise CandidateAuthorityError(
                        "manfred_candidate_vexp_action_authority_expired"
                    )

            try:
                yield lease
            except BaseException as action_error:
                try:
                    require_postconditions()
                except BaseException as postcheck_error:
                    raise postcheck_error from action_error
                raise
            else:
                require_postconditions()

    @contextmanager
    def finalization(self) -> Iterator[dict[str, object]]:
        """Hold current candidate authority through no-replace receipt publication."""

        with self._shared_lock():
            before, expires_at = self._current_status()
            remaining = (expires_at - self._now()).total_seconds()
            if (
                not math.isfinite(remaining)
                or remaining <= STATUS_TIMEOUT_SECONDS + LEASE_EXPIRY_MARGIN_SECONDS
            ):
                raise CandidateAuthorityError(
                    "manfred_candidate_vexp_finalization_window_too_short"
                )
            evidence = self._safe_evidence(
                before,
                boundary="candidate_receipt_publication",
                phase="finalization",
            )

            def require_postconditions() -> None:
                after, after_expires_at = self._current_status()
                if after != before or after_expires_at != expires_at:
                    raise CandidateAuthorityError(
                        "manfred_candidate_vexp_authority_changed"
                    )

            try:
                yield evidence
            except BaseException as action_error:
                try:
                    require_postconditions()
                except BaseException as postcheck_error:
                    raise postcheck_error from action_error
                raise
            else:
                require_postconditions()


def candidate_vexp_authority(
    *, state_path: Path, state_owner_uid: int
) -> CandidateVexpMutationAuthority:
    """Production factory with no path or trust-boundary overrides."""

    if os.geteuid() == ROOT_UID:
        raise CandidateAuthorityError(
            "manfred_candidate_vexp_non_root_operator_required"
        )
    if (
        Path(state_path) != DEFAULT_SENTINEL_STATE_PATH
        or type(state_owner_uid) is not int
        or state_owner_uid != os.geteuid()
    ):
        raise CandidateAuthorityError(
            "manfred_candidate_vexp_canonical_state_required"
        )
    return CandidateVexpMutationAuthority(
        state_path=DEFAULT_SENTINEL_STATE_PATH,
        state_owner_uid=state_owner_uid,
    )
