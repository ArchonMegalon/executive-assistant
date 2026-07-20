#!/usr/bin/env python3
"""Issue, inspect, and revoke the root authority for memorial mutations.

This installed program is intentionally self-contained.  It must never import
Python from an operator checkout while running as root.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import sys
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence


ROOT_UID = 0
ROOT_GID = 0
TRUSTED_EXECUTABLE_PATH = Path(
    "/usr/local/libexec/ea/manage-manfred-vexp-mutation-permit"
)
TRUSTED_PYTHON_EXECUTABLE = Path("/usr/bin/python3")
TRUSTED_EXECUTABLE_MODE = 0o555
TRUSTED_EXECUTABLE_PARENT_MODE = 0o755
RUNTIME_DIRECTORY_MODE = 0o755
PERMIT_MODE = 0o644
LOCK_MODE = 0o644
STATE_MODE = 0o600
MIN_TTL_SECONDS = 1
MAX_TTL_SECONDS = 3600
MAX_STATE_AGE = timedelta(minutes=5)
MAX_STATE_FUTURE_SKEW = timedelta(seconds=30)
MAX_VEXP_SENTINEL_STATE_BYTES = 1024 * 1024
MAX_VEXP_QUALIFICATION_CERTIFICATE_BYTES = 2 * 1024 * 1024
MAX_VEXP_QUALIFICATION_CERTIFICATE_SIDECAR_BYTES = 72
MAX_VEXP_MUTATION_PERMIT_BYTES = 16 * 1024
PERMIT_PATH = Path("/run/ea/memorial-vexp-mutation-permit.json")
LOCK_PATH = Path("/run/ea/memorial-vexp-mutation-permit.lock")
QUALIFICATION_CERTIFICATE_ROOT = Path("/var/lib/vexp-qualification-certificate")
QUALIFICATION_CERTIFICATE_DIRECTORY = (
    QUALIFICATION_CERTIFICATE_ROOT / "certificates"
)
QUALIFICATION_CERTIFICATE_OWNER_UID = 0
QUALIFICATION_CERTIFICATE_OWNER_GID = 1000
QUALIFICATION_CERTIFICATE_MODE = 0o640
QUALIFICATION_CERTIFICATE_DIRECTORY_MODE = 0o750
VEXP_QUALIFICATION_CERTIFICATE_SCHEMA = "ea.vexp_qualification_certificate.v2"
VEXP_SENTINEL_STATE_VERSION = 6
VEXP_MUTATION_PERMIT_CONTRACT_NAME = "ea.vexp_memorial_mutation_permit.v2"
VEXP_MUTATION_PERMIT_VERSION = 2
VEXP_MUTATION_BOUNDARIES = (
    "before_ensure_redis",
    "before_protect_previous_image",
    "before_recreate_api",
)
JOINT_VEXP_MUTATION_PERMIT_CONTRACT_NAME = "ea.vexp_memorial_joint_mutation_permit.v2"
JOINT_VEXP_MUTATION_PERMIT_VERSION = 2
JOINT_VEXP_MUTATION_BOUNDARIES = (
    *VEXP_MUTATION_BOUNDARIES,
    "before_recreate_cloudflared",
)
API_PERMIT_MODE = "api"
JOINT_PERMIT_MODE = "joint"
PERMIT_MODES = (API_PERMIT_MODE, JOINT_PERMIT_MODE)
VEXP_MUTATION_PERMIT_KEYS = frozenset(
    {
        "contract_name",
        "version",
        "status",
        "epoch_started_at",
        "epoch_started_ms",
        "qualification_earliest_completion_at",
        "qualified_at",
        "terminal_identity_sha256",
        "qualification_certificate_schema",
        "qualification_certificate_sha256",
        "qualification_certificate_identity",
        "qualification_certificate_event_hash",
        "issued_at",
        "expires_at",
        "mutation_boundaries",
    }
)
VEXP_UTC_TIMESTAMP_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$"
)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SHA256_IDENTITY_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
MINIMUM_QUALIFICATION_DURATION_MS = 7 * 24 * 60 * 60 * 1000
MINIMUM_VEXP_QUALIFICATION_AT = datetime(2026, 7, 20, 9, 43, 56, 206_000, tzinfo=UTC)

ACTIVE_CHAIN_KEYS = frozenset(
    {
        "anchor",
        "qualification_event",
        "tail_sequence",
        "tail_hash",
        "event_count",
        "index",
        "index_sha256",
    }
)
CHAIN_INDEX_ROW_KEYS = frozenset(
    {"at", "event", "sequence", "previous_hash", "hash"}
)
SOURCE_ATTESTATION_KEYS = frozenset(
    {
        "sentinel_state_sha256",
        "event_generations",
        "event_log_guard_sha256",
        "event_log_guard",
        "apparmor_audit_sha256",
        "apparmor_audit",
        "implementation",
    }
)
IMPLEMENTATION_ATTESTATION_KEYS = frozenset(
    {
        "sentinel_executable",
        "sentinel_systemd_unit",
        "predicate_contract",
        "finalizer_executable",
        "finalizer_checksum_manifest",
        "finalizer_checksum_binding",
        "finalizer_systemd_unit",
        "systemd_runtime",
        "apparmor_policy",
    }
)
SEAL_KEYS = frozenset(
    {
        "writer",
        "write_policy",
        "telegram_sent_by_finalizer",
        "docker_socket_used",
    }
)


class PermitError(RuntimeError):
    """A fail-closed permit authority error."""


def _utc_now_datetime() -> datetime:
    return datetime.now(UTC)


def _format_utc_timestamp(value: datetime) -> str:
    return (
        value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    )


def _parse_utc_timestamp(value: object, *, reason: str) -> datetime:
    if not isinstance(value, str) or not VEXP_UTC_TIMESTAMP_PATTERN.fullmatch(value):
        raise PermitError(reason)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PermitError(reason) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise PermitError(reason)
    return parsed.astimezone(UTC)


def _require_utc_clock(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise PermitError("vexp_permit_clock_invalid")
    return value.astimezone(UTC)


def _datetime_epoch_ms(value: datetime) -> int:
    delta = value - datetime(1970, 1, 1, tzinfo=UTC)
    return delta.days * 86_400_000 + delta.seconds * 1_000 + delta.microseconds // 1_000


def _trusted_file_identity(metadata: os.stat_result) -> tuple[int, ...]:
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


def _decode_guard_json(raw: bytes, *, reason: str) -> dict[str, Any]:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        payload: dict[str, Any] = {}
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
        raise PermitError(reason) from exc
    if not isinstance(payload, dict):
        raise PermitError(reason)
    return payload


def _terminal_identity(state: Mapping[str, Any]) -> dict[str, object]:
    return {
        "epoch_started_at": state.get("epoch_started_at"),
        "epoch_started_ms": state.get("epoch_started_ms"),
        "qualification_earliest_completion_at": state.get(
            "qualification_earliest_completion_at"
        ),
        "qualified_at": state.get("qualified_at"),
    }


def _terminal_identity_sha256(state: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        _terminal_identity(state),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_json_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _qualification_certificate_paths(epoch_started_ms: int) -> tuple[Path, Path]:
    if type(epoch_started_ms) is not int or epoch_started_ms <= 0:
        raise PermitError("vexp_qualification_certificate_epoch_invalid")
    certificate_path = QUALIFICATION_CERTIFICATE_DIRECTORY / f"{epoch_started_ms}.json"
    return certificate_path, certificate_path.with_suffix(".json.sha256")


def _validate_qualification_certificate_directory(path: Path, *, reason: str) -> None:
    try:
        metadata = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise PermitError(reason) from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode)
        != QUALIFICATION_CERTIFICATE_DIRECTORY_MODE
        or metadata.st_uid != QUALIFICATION_CERTIFICATE_OWNER_UID
        or metadata.st_gid != QUALIFICATION_CERTIFICATE_OWNER_GID
    ):
        raise PermitError(reason)


def _require_sha256(value: object, *, reason: str) -> str:
    if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
        raise PermitError(reason)
    return value


def _validate_qualification_certificate(
    certificate: Mapping[str, Any],
    *,
    state: Mapping[str, Any],
) -> dict[str, str]:
    reason = "vexp_qualification_certificate_contract_invalid"
    if certificate.get("schema") != VEXP_QUALIFICATION_CERTIFICATE_SCHEMA:
        raise PermitError(reason)
    if (
        type(certificate.get("sentinel_version")) is not int
        or certificate["sentinel_version"] != VEXP_SENTINEL_STATE_VERSION
    ):
        raise PermitError("vexp_qualification_certificate_sentinel_version_invalid")

    epoch_started_ms = state.get("epoch_started_ms")
    if (
        type(epoch_started_ms) is not int
        or certificate.get("epoch_started_ms") != epoch_started_ms
        or certificate.get("epoch_started_at") != state.get("epoch_started_at")
        or certificate.get("qualified_at") != state.get("qualified_at")
    ):
        raise PermitError("vexp_qualification_certificate_terminal_binding_invalid")
    epoch_started_at = _parse_utc_timestamp(
        certificate.get("epoch_started_at"),
        reason="vexp_qualification_certificate_terminal_binding_invalid",
    )
    qualified_at = _parse_utc_timestamp(
        certificate.get("qualified_at"),
        reason="vexp_qualification_certificate_terminal_binding_invalid",
    )
    if (
        epoch_started_at.microsecond % 1_000 != 0
        or _datetime_epoch_ms(epoch_started_at) != epoch_started_ms
    ):
        raise PermitError("vexp_qualification_certificate_terminal_binding_invalid")
    wall_duration_ms = _datetime_epoch_ms(qualified_at) - epoch_started_ms
    qualification_duration_ms = certificate.get("qualification_duration_ms")
    monotonic_duration_ms = certificate.get("qualification_monotonic_duration_ms")
    if (
        type(qualification_duration_ms) is not int
        or qualification_duration_ms != wall_duration_ms
        or qualification_duration_ms < MINIMUM_QUALIFICATION_DURATION_MS
        or type(monotonic_duration_ms) is not int
        or monotonic_duration_ms < MINIMUM_QUALIFICATION_DURATION_MS
    ):
        raise PermitError("vexp_qualification_certificate_duration_invalid")

    active_chain = certificate.get("active_chain")
    if not isinstance(active_chain, dict) or set(active_chain) != ACTIVE_CHAIN_KEYS:
        raise PermitError("vexp_qualification_certificate_chain_invalid")
    anchor = active_chain.get("anchor")
    if not isinstance(anchor, dict) or anchor.get("event") != "qualification_reset":
        raise PermitError("vexp_qualification_certificate_chain_invalid")
    try:
        anchor_row = {key: anchor[key] for key in CHAIN_INDEX_ROW_KEYS}
    except KeyError as exc:
        raise PermitError("vexp_qualification_certificate_chain_invalid") from exc
    index = active_chain.get("index")
    event_count = active_chain.get("event_count")
    if (
        not isinstance(index, list)
        or not index
        or type(event_count) is not int
        or event_count != len(index)
    ):
        raise PermitError("vexp_qualification_certificate_chain_invalid")
    normalized_rows: list[dict[str, Any]] = []
    previous_hash: str | None = None
    previous_sequence: int | None = None
    for row_index, row in enumerate(index):
        if not isinstance(row, dict) or set(row) != CHAIN_INDEX_ROW_KEYS:
            raise PermitError("vexp_qualification_certificate_chain_invalid")
        sequence = row.get("sequence")
        row_previous_hash = _require_sha256(
            row.get("previous_hash"),
            reason="vexp_qualification_certificate_chain_invalid",
        )
        if (
            type(sequence) is not int
            or sequence < 0
            or (previous_sequence is not None and sequence != previous_sequence + 1)
            or (row_index > 0 and row_previous_hash != previous_hash)
            or not isinstance(row.get("event"), str)
            or not row["event"]
        ):
            raise PermitError("vexp_qualification_certificate_chain_invalid")
        _parse_utc_timestamp(
            row.get("at"), reason="vexp_qualification_certificate_chain_invalid"
        )
        row_hash = _require_sha256(
            row.get("hash"), reason="vexp_qualification_certificate_chain_invalid"
        )
        normalized_rows.append(dict(row))
        previous_hash = row_hash
        previous_sequence = sequence
    if (
        anchor_row != normalized_rows[0]
        or active_chain.get("tail_sequence") != previous_sequence
        or active_chain.get("tail_hash") != previous_hash
        or _require_sha256(
            active_chain.get("index_sha256"),
            reason="vexp_qualification_certificate_chain_invalid",
        )
        != _canonical_json_sha256(normalized_rows)
    ):
        raise PermitError("vexp_qualification_certificate_chain_invalid")
    qualification_event = active_chain.get("qualification_event")
    if not isinstance(qualification_event, dict):
        raise PermitError("vexp_qualification_certificate_chain_invalid")
    try:
        qualification_row = {
            key: qualification_event[key] for key in CHAIN_INDEX_ROW_KEYS
        }
    except KeyError as exc:
        raise PermitError("vexp_qualification_certificate_chain_invalid") from exc
    if (
        qualification_event.get("event") != "seven_day_qualification_achieved"
        or qualification_event.get("at") != certificate.get("qualified_at")
        or sum(row == qualification_row for row in normalized_rows) != 1
    ):
        raise PermitError("vexp_qualification_certificate_chain_invalid")
    qualification_event_hash = _require_sha256(
        qualification_event.get("hash"),
        reason="vexp_qualification_certificate_chain_invalid",
    )

    terminal_state = certificate.get("terminal_state")
    if not isinstance(terminal_state, dict):
        raise PermitError("vexp_qualification_certificate_terminal_state_invalid")
    if (
        terminal_state.get("version") != VEXP_SENTINEL_STATE_VERSION
        or terminal_state.get("epoch_started_at") != state.get("epoch_started_at")
        or terminal_state.get("epoch_started_ms") != epoch_started_ms
        or terminal_state.get("qualified_at") != state.get("qualified_at")
        or terminal_state.get("qualification_phase") != "qualified"
        or terminal_state.get("certification_blockers") != []
        or terminal_state.get("certification_deferments") != []
        or terminal_state.get("last_event_hash") != previous_hash
    ):
        raise PermitError("vexp_qualification_certificate_terminal_state_invalid")

    attestations = certificate.get("source_attestations")
    if not isinstance(attestations, dict) or set(attestations) != SOURCE_ATTESTATION_KEYS:
        raise PermitError("vexp_qualification_certificate_attestations_invalid")
    for key in (
        "sentinel_state_sha256",
        "event_log_guard_sha256",
        "apparmor_audit_sha256",
    ):
        _require_sha256(
            attestations.get(key),
            reason="vexp_qualification_certificate_attestations_invalid",
        )
    if (
        not isinstance(attestations.get("event_generations"), (list, dict))
        or not attestations["event_generations"]
        or not isinstance(attestations.get("event_log_guard"), dict)
        or not attestations["event_log_guard"]
        or not isinstance(attestations.get("apparmor_audit"), dict)
        or not attestations["apparmor_audit"]
    ):
        raise PermitError("vexp_qualification_certificate_attestations_invalid")
    implementation = attestations.get("implementation")
    if (
        not isinstance(implementation, dict)
        or set(implementation) != IMPLEMENTATION_ATTESTATION_KEYS
        or any(value in (None, "", [], {}) for value in implementation.values())
    ):
        raise PermitError("vexp_qualification_certificate_attestations_invalid")
    predicate_contract = implementation.get("predicate_contract")
    if (
        not isinstance(predicate_contract, dict)
        or set(predicate_contract) != {"value", "sha256"}
        or predicate_contract.get("value") in (None, "", [], {})
    ):
        raise PermitError("vexp_qualification_certificate_attestations_invalid")
    _require_sha256(
        predicate_contract.get("sha256"),
        reason="vexp_qualification_certificate_attestations_invalid",
    )
    if (
        terminal_state.get("predicate_contract") != predicate_contract["value"]
        or terminal_state.get("predicate_contract_sha256")
        != predicate_contract["sha256"]
        or state.get("predicate_contract") != predicate_contract["value"]
        or state.get("predicate_contract_sha256") != predicate_contract["sha256"]
    ):
        raise PermitError(
            "vexp_qualification_certificate_predicate_contract_binding_invalid"
        )

    seal = certificate.get("seal")
    if (
        not isinstance(seal, dict)
        or set(seal) != SEAL_KEYS
        or seal.get("writer") != "root_owned_systemd_oneshot"
        or seal.get("write_policy") != "create_exclusive_never_overwrite"
        or seal.get("telegram_sent_by_finalizer") is not False
        or seal.get("docker_socket_used") is not False
    ):
        raise PermitError("vexp_qualification_certificate_seal_invalid")

    identity = certificate.get("identity")
    if not isinstance(identity, str) or not SHA256_IDENTITY_PATTERN.fullmatch(identity):
        raise PermitError("vexp_qualification_certificate_identity_invalid")
    identity_payload = dict(certificate)
    identity_payload.pop("identity", None)
    if identity != f"sha256:{_canonical_json_sha256(identity_payload)}":
        raise PermitError("vexp_qualification_certificate_identity_invalid")
    return {
        "schema": VEXP_QUALIFICATION_CERTIFICATE_SCHEMA,
        "identity": identity,
        "event_hash": qualification_event_hash,
    }


def _read_qualification_certificate(
    state: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    epoch_started_ms = state.get("epoch_started_ms")
    if type(epoch_started_ms) is not int or epoch_started_ms <= 0:
        raise PermitError("vexp_qualification_certificate_epoch_invalid")
    _validate_qualification_certificate_directory(
        QUALIFICATION_CERTIFICATE_ROOT,
        reason="vexp_qualification_certificate_root_untrusted",
    )
    _validate_qualification_certificate_directory(
        QUALIFICATION_CERTIFICATE_DIRECTORY,
        reason="vexp_qualification_certificate_directory_untrusted",
    )
    certificate_path, sidecar_path = _qualification_certificate_paths(
        epoch_started_ms
    )
    raw, _metadata = _trusted_read(
        certificate_path,
        expected_mode=QUALIFICATION_CERTIFICATE_MODE,
        expected_uid=QUALIFICATION_CERTIFICATE_OWNER_UID,
        expected_gid=QUALIFICATION_CERTIFICATE_OWNER_GID,
        max_bytes=MAX_VEXP_QUALIFICATION_CERTIFICATE_BYTES,
        reason_prefix="vexp_qualification_certificate",
    )
    sidecar, _sidecar_metadata = _trusted_read(
        sidecar_path,
        expected_mode=QUALIFICATION_CERTIFICATE_MODE,
        expected_uid=QUALIFICATION_CERTIFICATE_OWNER_UID,
        expected_gid=QUALIFICATION_CERTIFICATE_OWNER_GID,
        max_bytes=MAX_VEXP_QUALIFICATION_CERTIFICATE_SIDECAR_BYTES,
        reason_prefix="vexp_qualification_certificate_sidecar",
    )
    raw_sha256 = hashlib.sha256(raw).hexdigest()
    if sidecar != f"sha256:{raw_sha256}\n".encode("ascii"):
        raise PermitError("vexp_qualification_certificate_sidecar_invalid")
    certificate = _decode_guard_json(
        raw, reason="vexp_qualification_certificate_json_invalid"
    )
    evidence = _validate_qualification_certificate(certificate, state=state)
    evidence["sha256"] = raw_sha256
    return certificate, evidence


def _current_executable_path() -> Path:
    return Path(os.path.abspath(__file__))


def _current_python_executable() -> Path:
    return Path(os.path.abspath(sys.executable))


def _isolated_mode_enabled() -> bool:
    return sys.flags.isolated == 1


def _verify_trusted_execution_path() -> None:
    """Require the reviewed, immutable root installation before any operation."""

    if not _isolated_mode_enabled():
        raise PermitError("vexp_permit_manager_isolated_mode_required")
    if _current_python_executable() != TRUSTED_PYTHON_EXECUTABLE:
        raise PermitError("vexp_permit_manager_python_untrusted")
    current_path = _current_executable_path()
    if current_path != TRUSTED_EXECUTABLE_PATH:
        raise PermitError("vexp_permit_manager_execution_path_untrusted")
    parent = TRUSTED_EXECUTABLE_PATH.parent
    try:
        parent_metadata = os.stat(parent, follow_symlinks=False)
    except OSError as exc:
        raise PermitError("vexp_permit_manager_parent_unavailable") from exc
    if (
        not stat.S_ISDIR(parent_metadata.st_mode)
        or stat.S_IMODE(parent_metadata.st_mode) != TRUSTED_EXECUTABLE_PARENT_MODE
        or parent_metadata.st_uid != ROOT_UID
        or parent_metadata.st_gid != ROOT_GID
    ):
        raise PermitError("vexp_permit_manager_parent_untrusted")
    _require_safe_open_flags("vexp_permit_manager")
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    descriptor = -1
    try:
        descriptor = os.open(TRUSTED_EXECUTABLE_PATH, flags)
        metadata = os.fstat(descriptor)
        path_metadata = os.stat(TRUSTED_EXECUTABLE_PATH, follow_symlinks=False)
    except OSError as exc:
        raise PermitError("vexp_permit_manager_executable_unavailable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != TRUSTED_EXECUTABLE_MODE
        or metadata.st_uid != ROOT_UID
        or metadata.st_gid != ROOT_GID
        or _trusted_file_identity(path_metadata) != _trusted_file_identity(metadata)
    ):
        raise PermitError("vexp_permit_manager_executable_untrusted")


def _require_safe_open_flags(reason_prefix: str) -> None:
    if not hasattr(os, "O_NOFOLLOW"):
        raise PermitError(f"{reason_prefix}_nofollow_unavailable")
    if not hasattr(os, "O_NONBLOCK"):
        raise PermitError(f"{reason_prefix}_nonblock_unavailable")


def _trusted_read(
    path: Path,
    *,
    expected_mode: int,
    expected_uid: int,
    expected_gid: int | None,
    max_bytes: int,
    reason_prefix: str,
) -> tuple[bytes, os.stat_result]:
    _require_safe_open_flags(reason_prefix)
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise PermitError(f"{reason_prefix}_unavailable") from exc
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != expected_mode
            or metadata.st_uid != expected_uid
            or (expected_gid is not None and metadata.st_gid != expected_gid)
        ):
            raise PermitError(f"{reason_prefix}_untrusted")
        if not 0 < metadata.st_size <= max_bytes:
            raise PermitError(f"{reason_prefix}_size_invalid")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            raw = handle.read(max_bytes + 1)
            final_metadata = os.fstat(handle.fileno())
    except OSError as exc:
        raise PermitError(f"{reason_prefix}_unreadable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    try:
        final_path_metadata = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise PermitError(f"{reason_prefix}_changed_during_read") from exc
    if (
        len(raw) != metadata.st_size
        or len(raw) > max_bytes
        or _trusted_file_identity(final_metadata) != _trusted_file_identity(metadata)
        or _trusted_file_identity(final_path_metadata)
        != _trusted_file_identity(metadata)
    ):
        raise PermitError(f"{reason_prefix}_changed_during_read")
    return raw, final_metadata


def _read_state(path: Path, *, owner_uid: int) -> dict[str, Any]:
    raw, _metadata = _trusted_read(
        path,
        expected_mode=STATE_MODE,
        expected_uid=owner_uid,
        expected_gid=None,
        max_bytes=MAX_VEXP_SENTINEL_STATE_BYTES,
        reason_prefix="vexp_sentinel_state",
    )
    payload = _decode_guard_json(raw, reason="vexp_sentinel_state_json_invalid")
    if (
        type(payload.get("version")) is not int
        or payload["version"] != VEXP_SENTINEL_STATE_VERSION
    ):
        raise PermitError("vexp_sentinel_state_version_invalid")
    if (
        type(payload.get("epoch_started_ms")) is not int
        or payload["epoch_started_ms"] <= 0
    ):
        raise PermitError("vexp_sentinel_state_epoch_invalid")
    epoch_started_at = _parse_utc_timestamp(
        payload.get("epoch_started_at"), reason="vexp_sentinel_state_epoch_invalid"
    )
    if (
        epoch_started_at.microsecond % 1_000 != 0
        or _datetime_epoch_ms(epoch_started_at) != payload["epoch_started_ms"]
    ):
        raise PermitError("vexp_sentinel_state_epoch_invalid")
    return payload


def _validate_terminal_state(state: Mapping[str, Any], *, now: datetime) -> datetime:
    now = _require_utc_clock(now)
    updated_at = _parse_utc_timestamp(
        state.get("updated_at"), reason="vexp_sentinel_updated_at_invalid"
    )
    if updated_at > now + MAX_STATE_FUTURE_SKEW:
        raise PermitError("vexp_sentinel_updated_at_future")
    if now - updated_at > MAX_STATE_AGE:
        raise PermitError("vexp_sentinel_updated_at_stale")
    if state.get("qualification_phase") != "qualified":
        raise PermitError("vexp_sentinel_state_not_terminal")
    qualified_at = _parse_utc_timestamp(
        state.get("qualified_at"), reason="vexp_sentinel_qualified_at_invalid"
    )
    epoch_started_at = _parse_utc_timestamp(
        state.get("epoch_started_at"), reason="vexp_sentinel_state_epoch_invalid"
    )
    earliest_completion_at = _parse_utc_timestamp(
        state.get("qualification_earliest_completion_at"),
        reason="vexp_sentinel_earliest_completion_invalid",
    )
    try:
        qualification_floor = epoch_started_at + timedelta(days=7)
    except OverflowError as exc:
        raise PermitError("vexp_sentinel_qualification_time_invalid") from exc
    if earliest_completion_at < qualification_floor:
        raise PermitError("vexp_sentinel_earliest_completion_invalid")
    required_completion_at = max(
        MINIMUM_VEXP_QUALIFICATION_AT,
        qualification_floor,
        earliest_completion_at,
    )
    if qualified_at < required_completion_at:
        raise PermitError("vexp_sentinel_qualification_before_minimum")
    if qualified_at > now or now < required_completion_at:
        raise PermitError("vexp_sentinel_qualification_not_elapsed")
    if state.get("current_resources_healthy") is not True:
        raise PermitError("vexp_sentinel_resources_not_healthy")
    if "certification_blockers" not in state:
        raise PermitError("vexp_sentinel_certification_blockers_missing")
    if (
        type(state["certification_blockers"]) is not list
        or state["certification_blockers"] != []
    ):
        raise PermitError("vexp_sentinel_certification_blockers_present")
    if state.get("certification_deferments") != []:
        raise PermitError("vexp_sentinel_certification_deferments_present")
    return qualified_at


def _permit_contract(permit_mode: str) -> tuple[str, int, tuple[str, ...]]:
    if permit_mode == API_PERMIT_MODE:
        return (
            VEXP_MUTATION_PERMIT_CONTRACT_NAME,
            VEXP_MUTATION_PERMIT_VERSION,
            VEXP_MUTATION_BOUNDARIES,
        )
    if permit_mode == JOINT_PERMIT_MODE:
        return (
            JOINT_VEXP_MUTATION_PERMIT_CONTRACT_NAME,
            JOINT_VEXP_MUTATION_PERMIT_VERSION,
            JOINT_VEXP_MUTATION_BOUNDARIES,
        )
    raise PermitError("vexp_mutation_permit_mode_invalid")


def _permit_payload(
    state: Mapping[str, Any],
    *,
    qualification_certificate: Mapping[str, str],
    now: datetime,
    ttl_seconds: int,
    permit_mode: str = API_PERMIT_MODE,
) -> dict[str, object]:
    contract_name, version, boundaries = _permit_contract(permit_mode)
    return {
        "contract_name": contract_name,
        "version": version,
        "status": "allow",
        **_terminal_identity(state),
        "terminal_identity_sha256": _terminal_identity_sha256(state),
        "qualification_certificate_schema": qualification_certificate["schema"],
        "qualification_certificate_sha256": qualification_certificate["sha256"],
        "qualification_certificate_identity": qualification_certificate["identity"],
        "qualification_certificate_event_hash": qualification_certificate[
            "event_hash"
        ],
        "issued_at": _format_utc_timestamp(now),
        "expires_at": _format_utc_timestamp(now + timedelta(seconds=ttl_seconds)),
        "mutation_boundaries": list(boundaries),
    }


def _validate_permit(
    permit: Mapping[str, Any],
    *,
    now: datetime,
    require_current: bool,
    permit_mode: str = API_PERMIT_MODE,
) -> None:
    now = _require_utc_clock(now)
    contract_name, version, boundaries = _permit_contract(permit_mode)
    if set(permit) != VEXP_MUTATION_PERMIT_KEYS:
        raise PermitError("vexp_mutation_permit_schema_invalid")
    if permit.get("contract_name") != contract_name:
        raise PermitError("vexp_mutation_permit_contract_invalid")
    if type(permit.get("version")) is not int or permit["version"] != version:
        raise PermitError("vexp_mutation_permit_version_invalid")
    if permit.get("status") != "allow":
        raise PermitError("vexp_mutation_permit_not_positive")
    if permit.get("mutation_boundaries") != list(boundaries):
        raise PermitError("vexp_mutation_permit_boundaries_invalid")
    if (
        permit.get("qualification_certificate_schema")
        != VEXP_QUALIFICATION_CERTIFICATE_SCHEMA
        or not isinstance(permit.get("qualification_certificate_sha256"), str)
        or not SHA256_PATTERN.fullmatch(permit["qualification_certificate_sha256"])
        or not isinstance(permit.get("qualification_certificate_identity"), str)
        or not SHA256_IDENTITY_PATTERN.fullmatch(
            permit["qualification_certificate_identity"]
        )
        or not isinstance(
            permit.get("qualification_certificate_event_hash"), str
        )
        or not SHA256_PATTERN.fullmatch(
            permit["qualification_certificate_event_hash"]
        )
    ):
        raise PermitError("vexp_mutation_permit_certificate_binding_invalid")
    if (
        type(permit.get("epoch_started_ms")) is not int
        or permit["epoch_started_ms"] <= 0
    ):
        raise PermitError("vexp_mutation_permit_terminal_binding_invalid")
    epoch_started_at = _parse_utc_timestamp(
        permit.get("epoch_started_at"),
        reason="vexp_mutation_permit_terminal_binding_invalid",
    )
    if (
        epoch_started_at.microsecond % 1_000 != 0
        or _datetime_epoch_ms(epoch_started_at) != permit["epoch_started_ms"]
    ):
        raise PermitError("vexp_mutation_permit_terminal_binding_invalid")
    earliest_completion_at = _parse_utc_timestamp(
        permit.get("qualification_earliest_completion_at"),
        reason="vexp_mutation_permit_terminal_binding_invalid",
    )
    qualified_at = _parse_utc_timestamp(
        permit.get("qualified_at"),
        reason="vexp_mutation_permit_terminal_binding_invalid",
    )
    try:
        qualification_floor = epoch_started_at + timedelta(days=7)
    except OverflowError as exc:
        raise PermitError("vexp_mutation_permit_terminal_binding_invalid") from exc
    required_completion_at = max(
        MINIMUM_VEXP_QUALIFICATION_AT,
        qualification_floor,
        earliest_completion_at,
    )
    if (
        earliest_completion_at < qualification_floor
        or qualified_at < required_completion_at
    ):
        raise PermitError("vexp_mutation_permit_terminal_binding_invalid")
    identity = {
        "epoch_started_at": permit.get("epoch_started_at"),
        "epoch_started_ms": permit.get("epoch_started_ms"),
        "qualification_earliest_completion_at": permit.get(
            "qualification_earliest_completion_at"
        ),
        "qualified_at": permit.get("qualified_at"),
    }
    digest = permit.get("terminal_identity_sha256")
    if (
        not isinstance(digest, str)
        or not SHA256_PATTERN.fullmatch(digest)
        or digest != _terminal_identity_sha256(identity)
    ):
        raise PermitError("vexp_mutation_permit_identity_digest_invalid")
    issued_at = _parse_utc_timestamp(
        permit.get("issued_at"), reason="vexp_mutation_permit_issued_at_invalid"
    )
    expires_at = _parse_utc_timestamp(
        permit.get("expires_at"), reason="vexp_mutation_permit_expires_at_invalid"
    )
    if (
        issued_at < qualified_at
        or expires_at <= issued_at
        or expires_at - issued_at > timedelta(seconds=MAX_TTL_SECONDS)
    ):
        raise PermitError("vexp_mutation_permit_validity_invalid")
    if require_current and (now < issued_at or now >= expires_at):
        raise PermitError("vexp_mutation_permit_not_current")


def _validate_permit_certificate_binding(
    permit: Mapping[str, Any],
    qualification_certificate: Mapping[str, str],
) -> None:
    expected = {
        "qualification_certificate_schema": qualification_certificate["schema"],
        "qualification_certificate_sha256": qualification_certificate["sha256"],
        "qualification_certificate_identity": qualification_certificate["identity"],
        "qualification_certificate_event_hash": qualification_certificate[
            "event_hash"
        ],
    }
    if any(permit.get(key) != value for key, value in expected.items()):
        raise PermitError("vexp_mutation_permit_certificate_binding_mismatch")


def _read_permit(
    *,
    now: datetime,
    require_current: bool,
    permit_mode: str = API_PERMIT_MODE,
) -> tuple[dict[str, Any], str]:
    raw, _metadata = _trusted_read(
        PERMIT_PATH,
        expected_mode=PERMIT_MODE,
        expected_uid=ROOT_UID,
        expected_gid=ROOT_GID,
        max_bytes=MAX_VEXP_MUTATION_PERMIT_BYTES,
        reason_prefix="vexp_mutation_permit",
    )
    permit = _decode_guard_json(raw, reason="vexp_mutation_permit_json_invalid")
    _validate_permit(
        permit,
        now=now,
        require_current=require_current,
        permit_mode=permit_mode,
    )
    return permit, hashlib.sha256(raw).hexdigest()


def _validate_runtime_directory(path: Path) -> None:
    try:
        metadata = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise PermitError("vexp_mutation_runtime_directory_unavailable") from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != RUNTIME_DIRECTORY_MODE
        or metadata.st_uid != ROOT_UID
        or metadata.st_gid != ROOT_GID
    ):
        raise PermitError("vexp_mutation_runtime_directory_untrusted")


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise PermitError("vexp_mutation_runtime_directory_unreadable") from exc
    try:
        os.fsync(descriptor)
    except OSError as exc:
        raise PermitError("vexp_mutation_runtime_directory_fsync_failed") from exc
    finally:
        os.close(descriptor)


def _ensure_runtime_directory() -> Path:
    parent = PERMIT_PATH.parent
    if (
        not PERMIT_PATH.is_absolute()
        or not LOCK_PATH.is_absolute()
        or LOCK_PATH.parent != parent
    ):
        raise PermitError("vexp_mutation_authority_paths_invalid")
    created = False
    try:
        os.mkdir(parent, RUNTIME_DIRECTORY_MODE)
        created = True
    except FileExistsError:
        pass
    except OSError as exc:
        raise PermitError("vexp_mutation_runtime_directory_unavailable") from exc
    if created:
        try:
            os.chown(parent, ROOT_UID, ROOT_GID)
            os.chmod(parent, RUNTIME_DIRECTORY_MODE)
            _fsync_directory(parent.parent)
        except OSError as exc:
            raise PermitError("vexp_mutation_runtime_directory_setup_failed") from exc
    _validate_runtime_directory(parent)
    return parent


@contextmanager
def _authority_lock(*, exclusive: bool, create: bool) -> Iterator[None]:
    _require_safe_open_flags("vexp_mutation_permit_lock")
    access = os.O_RDWR if exclusive else os.O_RDONLY
    flags = access | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    descriptor = -1
    created = False
    try:
        if create:
            try:
                descriptor = os.open(
                    LOCK_PATH,
                    flags | os.O_CREAT | os.O_EXCL,
                    LOCK_MODE,
                )
                created = True
                os.fchmod(descriptor, LOCK_MODE)
                os.fchown(descriptor, ROOT_UID, ROOT_GID)
                os.fsync(descriptor)
            except FileExistsError:
                descriptor = os.open(LOCK_PATH, flags)
        else:
            descriptor = os.open(LOCK_PATH, flags)
    except OSError as exc:
        if descriptor >= 0:
            os.close(descriptor)
        raise PermitError("vexp_mutation_permit_lock_unavailable") from exc
    locked = False
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != LOCK_MODE
            or metadata.st_uid != ROOT_UID
            or metadata.st_gid != ROOT_GID
        ):
            raise PermitError("vexp_mutation_permit_lock_untrusted")
        try:
            mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            fcntl.flock(descriptor, mode | fcntl.LOCK_NB)
            locked = True
        except BlockingIOError as exc:
            raise PermitError("vexp_mutation_permit_lock_busy") from exc
        except OSError as exc:
            raise PermitError("vexp_mutation_permit_lock_unavailable") from exc
        final_metadata = os.fstat(descriptor)
        try:
            final_path_metadata = os.stat(LOCK_PATH, follow_symlinks=False)
        except OSError as exc:
            raise PermitError(
                "vexp_mutation_permit_lock_changed_during_acquire"
            ) from exc
        if _trusted_file_identity(final_metadata) != _trusted_file_identity(
            metadata
        ) or _trusted_file_identity(final_path_metadata) != _trusted_file_identity(
            metadata
        ):
            raise PermitError("vexp_mutation_permit_lock_changed_during_acquire")
        yield
    finally:
        if locked:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(descriptor)
        if created:
            _fsync_directory(LOCK_PATH.parent)


def _existing_permit_is_absent_or_trusted(
    now: datetime, *, permit_mode: str = API_PERMIT_MODE
) -> None:
    try:
        _read_permit(
            now=now,
            require_current=False,
            permit_mode=permit_mode,
        )
    except PermitError as exc:
        if str(exc) == "vexp_mutation_permit_unavailable":
            try:
                os.stat(PERMIT_PATH, follow_symlinks=False)
            except FileNotFoundError:
                return
            except OSError as stat_exc:
                raise PermitError("vexp_mutation_permit_target_untrusted") from stat_exc
        raise


def _atomic_write_permit(
    payload: Mapping[str, object],
    *,
    now: datetime,
    permit_mode: str = API_PERMIT_MODE,
) -> str:
    _existing_permit_is_absent_or_trusted(now, permit_mode=permit_mode)
    encoded = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")
    if not 0 < len(encoded) <= MAX_VEXP_MUTATION_PERMIT_BYTES:
        raise PermitError("vexp_mutation_permit_size_invalid")
    temporary = PERMIT_PATH.with_name(
        f".{PERMIT_PATH.name}.tmp.{os.getpid()}.{secrets.token_hex(8)}"
    )
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | os.O_CLOEXEC
        | os.O_NOFOLLOW
        | os.O_NONBLOCK
    )
    descriptor = -1
    replaced = False
    try:
        descriptor = os.open(temporary, flags, 0o600)
        os.fchmod(descriptor, PERMIT_MODE)
        os.fchown(descriptor, ROOT_UID, ROOT_GID)
        written = 0
        while written < len(encoded):
            count = os.write(descriptor, encoded[written:])
            if count <= 0:
                raise PermitError("vexp_mutation_permit_write_failed")
            written += count
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, PERMIT_PATH)
        replaced = True
        _fsync_directory(PERMIT_PATH.parent)
    except PermitError:
        raise
    except OSError as exc:
        raise PermitError("vexp_mutation_permit_write_failed") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if not replaced:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            except OSError:
                pass
    raw, _metadata = _trusted_read(
        PERMIT_PATH,
        expected_mode=PERMIT_MODE,
        expected_uid=ROOT_UID,
        expected_gid=ROOT_GID,
        max_bytes=MAX_VEXP_MUTATION_PERMIT_BYTES,
        reason_prefix="vexp_mutation_permit",
    )
    if raw != encoded:
        raise PermitError("vexp_mutation_permit_postwrite_mismatch")
    return hashlib.sha256(raw).hexdigest()


def _remove_just_written_permit(
    *,
    expected_sha256: str,
    now: datetime,
    permit_mode: str = API_PERMIT_MODE,
) -> None:
    _permit, observed_sha256 = _read_permit(
        now=now,
        require_current=False,
        permit_mode=permit_mode,
    )
    if observed_sha256 != expected_sha256:
        raise PermitError("vexp_mutation_permit_postwrite_cleanup_target_changed")
    try:
        os.unlink(PERMIT_PATH)
    except OSError as exc:
        raise PermitError("vexp_mutation_permit_postwrite_cleanup_failed") from exc
    _fsync_directory(PERMIT_PATH.parent)


def _validate_state_arguments(*, state_path: Path, state_owner_uid: int) -> None:
    if not state_path.is_absolute():
        raise PermitError("vexp_sentinel_state_path_not_absolute")
    if state_owner_uid < 0:
        raise PermitError("vexp_sentinel_state_owner_uid_invalid")


def _require_root() -> None:
    if os.geteuid() != ROOT_UID:
        raise PermitError("vexp_mutation_permit_root_required")


def issue(
    *,
    state_path: Path,
    state_owner_uid: int,
    ttl_seconds: int,
    permit_mode: str = API_PERMIT_MODE,
) -> dict[str, object]:
    _verify_trusted_execution_path()
    _require_root()
    _validate_state_arguments(state_path=state_path, state_owner_uid=state_owner_uid)
    if not MIN_TTL_SECONDS <= ttl_seconds <= MAX_TTL_SECONDS:
        raise PermitError("vexp_mutation_permit_ttl_invalid")
    initial_now = _utc_now_datetime()
    initial_state = _read_state(state_path, owner_uid=state_owner_uid)
    _validate_terminal_state(initial_state, now=initial_now)
    _ensure_runtime_directory()
    with _authority_lock(exclusive=True, create=True):
        now = _utc_now_datetime()
        state = _read_state(state_path, owner_uid=state_owner_uid)
        qualified_at = _validate_terminal_state(state, now=now)
        _certificate, qualification_certificate = (
            _read_qualification_certificate(state)
        )
        prewrite_state = _read_state(state_path, owner_uid=state_owner_uid)
        _validate_terminal_state(prewrite_state, now=now)
        if _terminal_identity(prewrite_state) != _terminal_identity(state):
            raise PermitError("vexp_sentinel_terminal_identity_changed")
        payload = _permit_payload(
            prewrite_state,
            qualification_certificate=qualification_certificate,
            now=now,
            ttl_seconds=ttl_seconds,
            permit_mode=permit_mode,
        )
        _validate_permit(
            payload,
            now=now,
            require_current=True,
            permit_mode=permit_mode,
        )
        _validate_permit_certificate_binding(payload, qualification_certificate)
        permit_sha256 = _atomic_write_permit(
            payload,
            now=now,
            permit_mode=permit_mode,
        )
        postwrite_now = _utc_now_datetime()
        try:
            postwrite_state = _read_state(state_path, owner_uid=state_owner_uid)
            _validate_terminal_state(postwrite_state, now=postwrite_now)
            if _terminal_identity(postwrite_state) != _terminal_identity(
                prewrite_state
            ):
                raise PermitError("vexp_sentinel_terminal_identity_changed")
            _postwrite_certificate, postwrite_certificate = (
                _read_qualification_certificate(postwrite_state)
            )
            if postwrite_certificate != qualification_certificate:
                raise PermitError("vexp_qualification_certificate_changed")
            _validate_permit_certificate_binding(payload, postwrite_certificate)
        except PermitError:
            _remove_just_written_permit(
                expected_sha256=permit_sha256,
                now=postwrite_now,
                permit_mode=permit_mode,
            )
            raise
    return {
        "status": "issued",
        "contract_name": payload["contract_name"],
        "epoch_started_ms": prewrite_state["epoch_started_ms"],
        "qualified_at": _format_utc_timestamp(qualified_at),
        "expires_at": payload["expires_at"],
        "terminal_identity_sha256": payload["terminal_identity_sha256"],
        "qualification_certificate_schema": qualification_certificate["schema"],
        "qualification_certificate_sha256": qualification_certificate["sha256"],
        "qualification_certificate_identity": qualification_certificate["identity"],
        "qualification_certificate_event_hash": qualification_certificate[
            "event_hash"
        ],
        "permit_sha256": permit_sha256,
    }


def status(
    *,
    state_path: Path,
    state_owner_uid: int,
    permit_mode: str = API_PERMIT_MODE,
) -> dict[str, object]:
    _verify_trusted_execution_path()
    _validate_state_arguments(state_path=state_path, state_owner_uid=state_owner_uid)
    _validate_runtime_directory(PERMIT_PATH.parent)
    with _authority_lock(exclusive=False, create=False):
        now = _utc_now_datetime()
        state = _read_state(state_path, owner_uid=state_owner_uid)
        _validate_terminal_state(state, now=now)
        permit, permit_sha256 = _read_permit(
            now=now,
            require_current=True,
            permit_mode=permit_mode,
        )
        if _terminal_identity(permit) != _terminal_identity(state):
            raise PermitError("vexp_mutation_permit_state_binding_mismatch")
        _certificate, qualification_certificate = (
            _read_qualification_certificate(state)
        )
        _validate_permit_certificate_binding(permit, qualification_certificate)
        final_now = _utc_now_datetime()
        final_state = _read_state(state_path, owner_uid=state_owner_uid)
        _validate_terminal_state(final_state, now=final_now)
        if _terminal_identity(final_state) != _terminal_identity(state):
            raise PermitError("vexp_sentinel_terminal_identity_changed")
        _final_certificate, final_qualification_certificate = (
            _read_qualification_certificate(final_state)
        )
        _validate_permit(
            permit,
            now=final_now,
            require_current=True,
            permit_mode=permit_mode,
        )
        if _terminal_identity(permit) != _terminal_identity(final_state):
            raise PermitError("vexp_mutation_permit_state_binding_mismatch")
        if final_qualification_certificate != qualification_certificate:
            raise PermitError("vexp_qualification_certificate_changed")
        _validate_permit_certificate_binding(
            permit, final_qualification_certificate
        )
    return {
        "status": "valid",
        "contract_name": permit["contract_name"],
        "epoch_started_ms": permit["epoch_started_ms"],
        "qualified_at": permit["qualified_at"],
        "issued_at": permit["issued_at"],
        "expires_at": permit["expires_at"],
        "terminal_identity_sha256": permit["terminal_identity_sha256"],
        "qualification_certificate_schema": permit[
            "qualification_certificate_schema"
        ],
        "qualification_certificate_sha256": permit[
            "qualification_certificate_sha256"
        ],
        "qualification_certificate_identity": permit[
            "qualification_certificate_identity"
        ],
        "qualification_certificate_event_hash": permit[
            "qualification_certificate_event_hash"
        ],
        "permit_sha256": permit_sha256,
        "mutation_boundaries": permit["mutation_boundaries"],
    }


def revoke(*, permit_mode: str = API_PERMIT_MODE) -> dict[str, object]:
    _verify_trusted_execution_path()
    _require_root()
    now = _utc_now_datetime()
    _validate_runtime_directory(PERMIT_PATH.parent)
    with _authority_lock(exclusive=True, create=False):
        _permit, permit_sha256 = _read_permit(
            now=now,
            require_current=False,
            permit_mode=permit_mode,
        )
        try:
            os.unlink(PERMIT_PATH)
        except OSError as exc:
            raise PermitError("vexp_mutation_permit_revoke_failed") from exc
        _fsync_directory(PERMIT_PATH.parent)
    return {"status": "revoked", "permit_sha256": permit_sha256}


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Manage the root-owned exact-epoch Manfred mutation permit."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    issue_parser = subparsers.add_parser("issue")
    issue_parser.add_argument("--state-path", required=True, type=Path)
    issue_parser.add_argument("--state-owner-uid", required=True, type=int)
    issue_parser.add_argument("--ttl-seconds", type=int, default=900)
    issue_parser.add_argument(
        "--permit-mode",
        choices=PERMIT_MODES,
        default=API_PERMIT_MODE,
    )
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--state-path", required=True, type=Path)
    status_parser.add_argument("--state-owner-uid", required=True, type=int)
    status_parser.add_argument(
        "--permit-mode",
        choices=PERMIT_MODES,
        default=API_PERMIT_MODE,
    )
    revoke_parser = subparsers.add_parser("revoke")
    revoke_parser.add_argument(
        "--permit-mode",
        choices=PERMIT_MODES,
        default=API_PERMIT_MODE,
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.command == "issue":
            result = issue(
                state_path=args.state_path,
                state_owner_uid=args.state_owner_uid,
                ttl_seconds=args.ttl_seconds,
                permit_mode=args.permit_mode,
            )
        elif args.command == "status":
            result = status(
                state_path=args.state_path,
                state_owner_uid=args.state_owner_uid,
                permit_mode=args.permit_mode,
            )
        else:
            result = revoke(permit_mode=args.permit_mode)
    except PermitError as exc:
        print(f"permit_error:{exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
