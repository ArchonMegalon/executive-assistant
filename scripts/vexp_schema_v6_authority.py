#!/usr/bin/env python3
"""Read-only verifier for issuer-coordinated schema-v6 terminal evidence.

This module does not issue a certificate or grant mutation authority.  It accepts
the existing root-owned memorial mutation permit only as evidence that the
schema-v6 terminal identity was independently observed by its issuer.  The
permit's memorial-specific mutation boundaries are deliberately not transferable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Mapping


UTC = timezone.utc
STATE_VERSION = 6
PERMIT_CONTRACT_NAME = "ea.vexp_memorial_mutation_permit.v1"
PERMIT_VERSION = 1
PERMIT_BOUNDARIES = (
    "before_ensure_redis",
    "before_protect_previous_image",
    "before_recreate_api",
)
PERMIT_KEYS = frozenset(
    {
        "contract_name",
        "version",
        "status",
        "epoch_started_at",
        "epoch_started_ms",
        "qualification_earliest_completion_at",
        "qualified_at",
        "terminal_identity_sha256",
        "issued_at",
        "expires_at",
        "mutation_boundaries",
    }
)
UTC_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MINIMUM_QUALIFICATION_AT = datetime(
    2026, 7, 20, 9, 43, 56, 206_000, tzinfo=UTC
)
MAX_STATE_AGE = timedelta(minutes=5)
MAX_FUTURE_SKEW = timedelta(seconds=30)
MAX_PERMIT_LIFETIME = timedelta(hours=1)
MAX_STATE_BYTES = 1024 * 1024
MAX_PERMIT_BYTES = 16 * 1024
ROOT_AUTHORITY_UID = 0


class SchemaV6AuthorityError(RuntimeError):
    """Stable, content-free qualification denial."""


@dataclass(frozen=True)
class QualificationEvidence:
    state_sha256: str
    terminal_identity_sha256: str
    qualified_at: str
    permit_contract_name: str
    permit_sha256: str
    permit_expires_at: str
    mutation_authority_transferred: bool = False

    def projection(self) -> dict[str, object]:
        return {
            "state_version": STATE_VERSION,
            "state_sha256": self.state_sha256,
            "terminal_identity_sha256": self.terminal_identity_sha256,
            "qualified_at": self.qualified_at,
            "permit_contract_name": self.permit_contract_name,
            "permit_sha256": self.permit_sha256,
            "permit_expires_at": self.permit_expires_at,
            "evidence_scope": "schema_v6_terminal_qualification_only",
            "mutation_authority_transferred": self.mutation_authority_transferred,
        }


def _parse_utc(value: object, *, reason: str) -> datetime:
    if not isinstance(value, str) or not UTC_TIMESTAMP_RE.fullmatch(value):
        raise SchemaV6AuthorityError(reason)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SchemaV6AuthorityError(reason) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise SchemaV6AuthorityError(reason)
    return parsed.astimezone(UTC)


def _epoch_ms(value: datetime) -> int:
    delta = value - datetime(1970, 1, 1, tzinfo=UTC)
    return (
        delta.days * 86_400_000
        + delta.seconds * 1_000
        + delta.microseconds // 1_000
    )


def terminal_identity(state: Mapping[str, Any]) -> dict[str, object]:
    return {
        "epoch_started_at": state.get("epoch_started_at"),
        "epoch_started_ms": state.get("epoch_started_ms"),
        "qualification_earliest_completion_at": state.get(
            "qualification_earliest_completion_at"
        ),
        "qualified_at": state.get("qualified_at"),
    }


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def terminal_identity_sha256(state: Mapping[str, Any]) -> str:
    return canonical_sha256(terminal_identity(state))


def _validate_clock(now: datetime) -> datetime:
    if (
        not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() != timedelta(0)
    ):
        raise SchemaV6AuthorityError("schema_v6_clock_invalid")
    return now.astimezone(UTC)


def validate_schema_v6_qualification(
    state: Mapping[str, Any],
    permit: Mapping[str, Any],
    *,
    state_sha256: str,
    permit_sha256: str,
    now: datetime,
) -> QualificationEvidence:
    """Validate exact terminal identity and the existing issuer permit.

    The returned evidence explicitly denies authority transfer.  An independent
    owner permit remains mandatory for every non-memorial staging consumer.
    """

    checked_now = _validate_clock(now)
    if not SHA256_RE.fullmatch(state_sha256):
        raise SchemaV6AuthorityError("schema_v6_state_digest_invalid")
    if not SHA256_RE.fullmatch(permit_sha256):
        raise SchemaV6AuthorityError("schema_v6_permit_digest_invalid")
    if type(state.get("version")) is not int or state["version"] != STATE_VERSION:
        raise SchemaV6AuthorityError("schema_v6_state_version_invalid")
    if state.get("qualification_phase") != "qualified" or state.get("qualified_at") is None:
        raise SchemaV6AuthorityError("schema_v6_state_not_terminal")
    if state.get("current_resources_healthy") is not True:
        raise SchemaV6AuthorityError("schema_v6_resources_unhealthy")
    blockers = state.get("certification_blockers")
    if not isinstance(blockers, list) or blockers:
        raise SchemaV6AuthorityError("schema_v6_blockers_present")

    epoch_started_at = _parse_utc(
        state.get("epoch_started_at"), reason="schema_v6_epoch_invalid"
    )
    epoch_started_ms = state.get("epoch_started_ms")
    if (
        type(epoch_started_ms) is not int
        or epoch_started_ms <= 0
        or epoch_started_at.microsecond % 1_000 != 0
        or _epoch_ms(epoch_started_at) != epoch_started_ms
    ):
        raise SchemaV6AuthorityError("schema_v6_epoch_invalid")
    earliest = _parse_utc(
        state.get("qualification_earliest_completion_at"),
        reason="schema_v6_earliest_completion_invalid",
    )
    qualified_at = _parse_utc(
        state.get("qualified_at"), reason="schema_v6_qualified_at_invalid"
    )
    updated_at = _parse_utc(
        state.get("updated_at"), reason="schema_v6_updated_at_invalid"
    )
    seven_day_floor = epoch_started_at + timedelta(days=7)
    if earliest < seven_day_floor:
        raise SchemaV6AuthorityError("schema_v6_earliest_completion_invalid")
    required_completion = max(MINIMUM_QUALIFICATION_AT, seven_day_floor, earliest)
    if qualified_at < required_completion:
        raise SchemaV6AuthorityError("schema_v6_qualification_before_minimum")
    if checked_now < required_completion or qualified_at > checked_now:
        raise SchemaV6AuthorityError("schema_v6_qualification_not_elapsed")
    if updated_at < checked_now - MAX_STATE_AGE:
        raise SchemaV6AuthorityError("schema_v6_state_stale")
    if updated_at > checked_now + MAX_FUTURE_SKEW:
        raise SchemaV6AuthorityError("schema_v6_state_from_future")

    if set(permit) != PERMIT_KEYS:
        raise SchemaV6AuthorityError("schema_v6_permit_schema_invalid")
    if permit.get("contract_name") != PERMIT_CONTRACT_NAME:
        raise SchemaV6AuthorityError("schema_v6_permit_contract_invalid")
    if type(permit.get("version")) is not int or permit["version"] != PERMIT_VERSION:
        raise SchemaV6AuthorityError("schema_v6_permit_version_invalid")
    if permit.get("status") != "allow":
        raise SchemaV6AuthorityError("schema_v6_permit_not_positive")
    if permit.get("mutation_boundaries") != list(PERMIT_BOUNDARIES):
        raise SchemaV6AuthorityError("schema_v6_permit_boundaries_invalid")
    expected_identity = terminal_identity(state)
    if any(permit.get(key) != value for key, value in expected_identity.items()):
        raise SchemaV6AuthorityError("schema_v6_permit_terminal_binding_invalid")
    identity_digest = terminal_identity_sha256(state)
    if permit.get("terminal_identity_sha256") != identity_digest:
        raise SchemaV6AuthorityError("schema_v6_permit_identity_digest_invalid")
    issued_at = _parse_utc(
        permit.get("issued_at"), reason="schema_v6_permit_issued_at_invalid"
    )
    expires_at = _parse_utc(
        permit.get("expires_at"), reason="schema_v6_permit_expires_at_invalid"
    )
    if (
        issued_at < qualified_at
        or expires_at <= issued_at
        or expires_at - issued_at > MAX_PERMIT_LIFETIME
    ):
        raise SchemaV6AuthorityError("schema_v6_permit_validity_invalid")
    if checked_now < issued_at or checked_now >= expires_at:
        raise SchemaV6AuthorityError("schema_v6_permit_not_current")
    return QualificationEvidence(
        state_sha256=state_sha256,
        terminal_identity_sha256=identity_digest,
        qualified_at=str(state["qualified_at"]),
        permit_contract_name=PERMIT_CONTRACT_NAME,
        permit_sha256=permit_sha256,
        permit_expires_at=str(permit["expires_at"]),
    )


def _trusted_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _root_authority_anchor_is_trusted(
    opened: os.stat_result,
    current: os.stat_result,
) -> bool:
    """Return whether both views identify the same safe filesystem root."""

    return (
        stat.S_ISDIR(opened.st_mode)
        and stat.S_ISDIR(current.st_mode)
        and opened.st_uid == ROOT_AUTHORITY_UID
        and current.st_uid == ROOT_AUTHORITY_UID
        and stat.S_IMODE(opened.st_mode) & 0o022 == 0
        and stat.S_IMODE(current.st_mode) & 0o022 == 0
        and opened.st_dev == current.st_dev
        and opened.st_ino == current.st_ino
    )


def _open_absolute_nofollow(
    path: Path,
    *,
    flags: int,
    reason: str,
    require_root_parents: bool,
) -> int:
    """Open an absolute path without following any path-component symlink."""

    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise SchemaV6AuthorityError(f"{reason}_location_invalid")
    required = ("O_NOFOLLOW", "O_NONBLOCK", "O_DIRECTORY")
    if any(not hasattr(os, name) for name in required):
        raise SchemaV6AuthorityError(f"{reason}_safe_open_unavailable")
    components = path.parts[1:]
    if not components or any(component in {"", ".", ".."} for component in components):
        raise SchemaV6AuthorityError(f"{reason}_location_invalid")
    directory_fd = -1
    try:
        directory_fd = os.open(
            "/",
            os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW,
        )
        if require_root_parents:
            opened_root = os.fstat(directory_fd)
            current_root = os.stat("/", follow_symlinks=False)
            if not _root_authority_anchor_is_trusted(opened_root, current_root):
                raise SchemaV6AuthorityError(f"{reason}_root_anchor_untrusted")
        for component in components[:-1]:
            next_fd = os.open(
                component,
                os.O_RDONLY
                | os.O_CLOEXEC
                | os.O_DIRECTORY
                | os.O_NOFOLLOW
                | os.O_NONBLOCK,
                dir_fd=directory_fd,
            )
            os.close(directory_fd)
            directory_fd = next_fd
            metadata = os.fstat(directory_fd)
            if not stat.S_ISDIR(metadata.st_mode):
                raise SchemaV6AuthorityError(f"{reason}_parent_untrusted")
            if require_root_parents and (
                metadata.st_uid != ROOT_AUTHORITY_UID
                or stat.S_IMODE(metadata.st_mode) & 0o022
            ):
                raise SchemaV6AuthorityError(f"{reason}_parent_untrusted")
        descriptor = os.open(
            components[-1],
            flags | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory_fd,
        )
    except SchemaV6AuthorityError:
        raise
    except OSError as exc:
        raise SchemaV6AuthorityError(f"{reason}_unavailable") from exc
    finally:
        if directory_fd >= 0:
            os.close(directory_fd)
    return descriptor


def read_trusted_json(
    path: Path,
    *,
    expected_uid: int,
    expected_mode: int,
    max_bytes: int,
    reason: str,
) -> tuple[dict[str, Any], str]:
    """Read one fixed authority file without following links or leaking content."""

    if not path.is_absolute() or expected_uid < 0:
        raise SchemaV6AuthorityError(f"{reason}_location_invalid")
    descriptor = -1
    try:
        descriptor = _open_absolute_nofollow(
            path,
            flags=os.O_RDONLY,
            reason=reason,
            require_root_parents=expected_uid == ROOT_AUTHORITY_UID,
        )
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != expected_uid
            or stat.S_IMODE(before.st_mode) != expected_mode
            or not 0 < before.st_size <= max_bytes
        ):
            raise SchemaV6AuthorityError(f"{reason}_untrusted")
        chunks: list[bytes] = []
        remaining = int(before.st_size)
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                raise SchemaV6AuthorityError(f"{reason}_changed_during_read")
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        current_descriptor = _open_absolute_nofollow(
            path,
            flags=os.O_RDONLY,
            reason=reason,
            require_root_parents=expected_uid == ROOT_AUTHORITY_UID,
        )
        try:
            current = os.fstat(current_descriptor)
        finally:
            os.close(current_descriptor)
        if _trusted_identity(before) != _trusted_identity(after) or _trusted_identity(
            before
        ) != _trusted_identity(current):
            raise SchemaV6AuthorityError(f"{reason}_changed_during_read")
    except SchemaV6AuthorityError:
        raise
    except OSError as exc:
        raise SchemaV6AuthorityError(f"{reason}_unavailable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    raw = b"".join(chunks)
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
        raise SchemaV6AuthorityError(f"{reason}_json_invalid") from exc
    if not isinstance(payload, dict):
        raise SchemaV6AuthorityError(f"{reason}_json_invalid")
    return payload, hashlib.sha256(raw).hexdigest()


def load_schema_v6_qualification(
    *,
    state_path: Path,
    state_owner_uid: int,
    permit_path: Path,
    now: datetime,
) -> QualificationEvidence:
    """Read, validate, and re-read state around the issuer permit."""

    state, state_digest = read_trusted_json(
        state_path,
        expected_uid=state_owner_uid,
        expected_mode=0o600,
        max_bytes=MAX_STATE_BYTES,
        reason="schema_v6_state",
    )
    permit, permit_digest = read_trusted_json(
        permit_path,
        expected_uid=ROOT_AUTHORITY_UID,
        expected_mode=0o644,
        max_bytes=MAX_PERMIT_BYTES,
        reason="schema_v6_permit",
    )
    evidence = validate_schema_v6_qualification(
        state,
        permit,
        state_sha256=state_digest,
        permit_sha256=permit_digest,
        now=now,
    )
    final_state, final_state_digest = read_trusted_json(
        state_path,
        expected_uid=state_owner_uid,
        expected_mode=0o600,
        max_bytes=MAX_STATE_BYTES,
        reason="schema_v6_state",
    )
    if (
        terminal_identity(final_state) != terminal_identity(state)
        or terminal_identity_sha256(final_state) != evidence.terminal_identity_sha256
    ):
        raise SchemaV6AuthorityError("schema_v6_terminal_identity_changed")
    # Revalidate liveness and blockers after the permit read. The full state may
    # legitimately receive a fresh updated_at, so terminal identity is the stable
    # binding while the final digest is recorded as the observed state.
    final_evidence = validate_schema_v6_qualification(
        final_state,
        permit,
        state_sha256=final_state_digest,
        permit_sha256=permit_digest,
        now=now,
    )
    return final_evidence
