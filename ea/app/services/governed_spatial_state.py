from __future__ import annotations

from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import stat
import threading
from typing import Iterator

from app.services.governed_spatial_contract import (
    bounded_sha256,
    normalize_compatibility_numbers,
    parse_raw_transport_json,
)


AUDIT_ONLY_STATE = "audit_only"
GENERIC_BLOCKED_STATE = "blocked"
BUILD_STATES = (
    "authorization_verified",
    "reservation_held",
    "released",
    "attempt_committed",
    "charge_pending",
    "cancelled_reconciliation_pending",
    "consumed",
    "closed_consumed",
    "compensation_pending",
    "compensated",
    "compensation_failed_blocked",
)
ATTEMPTED_STATES = frozenset(
    {
        "attempt_committed",
        "charge_pending",
        "cancelled_reconciliation_pending",
        "consumed",
        "closed_consumed",
        "compensation_pending",
        "compensated",
        "compensation_failed_blocked",
    }
)
CONSUMED_STATES = frozenset(
    {
        "consumed",
        "closed_consumed",
        "compensation_pending",
        "compensated",
        "compensation_failed_blocked",
    }
)
COMPENSATED_STATES = frozenset({"compensated", "compensation_failed_blocked"})
TERMINAL_STATES = frozenset(
    {
        GENERIC_BLOCKED_STATE,
        "released",
        "closed_consumed",
        "compensated",
        "compensation_failed_blocked",
    }
)

_ALLOWED_TRANSITIONS = {
    "authorization_verified": {"authorization_verified", "reservation_held", GENERIC_BLOCKED_STATE},
    "reservation_held": {"reservation_held", "released", "attempt_committed"},
    "attempt_committed": {
        "attempt_committed",
        "charge_pending",
        "cancelled_reconciliation_pending",
        "consumed",
        "released",
    },
    "charge_pending": {
        "attempt_committed",
        "released",
        "cancelled_reconciliation_pending",
        "consumed",
    },
    "cancelled_reconciliation_pending": {"released", "consumed"},
    "consumed": {"closed_consumed", "compensation_pending"},
    "compensation_pending": {"compensated", "compensation_failed_blocked"},
}

_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class SpatialStateError(ValueError):
    pass


class SpatialStateIntegrityError(SpatialStateError):
    pass


class SpatialIdempotencyConflict(SpatialStateError):
    pass


class SpatialTransitionError(SpatialStateError):
    pass


class SpatialPrivacyError(SpatialStateError):
    pass


_LIFECYCLE_AUTHORITY_MARKER = object()
_LIFECYCLE_GUARD_MARKER = object()


class SpatialLifecycleAuthority:
    """Opaque in-process identity for one DurableSpatialLedger instance."""

    __slots__ = ("_identity",)

    def __init__(self, *, marker: object) -> None:
        if marker is not _LIFECYCLE_AUTHORITY_MARKER:
            raise SpatialStateError("composition_lifecycle_authority_invalid")
        self._identity = object()

    def __repr__(self) -> str:
        return "SpatialLifecycleAuthority(<redacted>)"

    def __reduce__(self) -> object:
        raise TypeError("composition_lifecycle_authority_not_serializable")


class SpatialCompositionLifecycleGuard:
    """Active proof that one composition/privacy scope holds the ledger lock."""

    __slots__ = (
        "scope_digest",
        "_authority",
        "_privacy_status",
        "_active",
        "_owner_thread",
    )

    def __init__(
        self,
        scope_digest: str,
        privacy_status: Mapping[str, object] | None,
        *,
        authority: SpatialLifecycleAuthority,
        marker: object,
    ) -> None:
        if (
            marker is not _LIFECYCLE_GUARD_MARKER
            or not isinstance(authority, SpatialLifecycleAuthority)
        ):
            raise SpatialStateError("composition_lifecycle_guard_invalid")
        self.scope_digest = scope_digest
        self._authority = authority
        self._privacy_status = (
            deepcopy(dict(privacy_status)) if privacy_status is not None else None
        )
        self._active = True
        self._owner_thread = threading.get_ident()

    @property
    def privacy_status(self) -> dict[str, object] | None:
        return deepcopy(self._privacy_status)

    def assert_active(
        self,
        scope_digest: str,
        *,
        authority: SpatialLifecycleAuthority,
        allow_privacy: bool = False,
    ) -> None:
        if (
            not self._active
            or self._owner_thread != threading.get_ident()
            or self.scope_digest != scope_digest
            or self._authority is not authority
        ):
            raise SpatialStateError("composition_lifecycle_guard_inactive")
        if self._privacy_status is not None and not allow_privacy:
            raise SpatialPrivacyError("composition_lifecycle_privacy_tombstone_active")

    def _record_privacy_status(self, status: Mapping[str, object]) -> None:
        self._privacy_status = deepcopy(dict(status))

    def _close(self) -> None:
        self._active = False


def utc_iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SpatialStateError("offset_aware_timestamp_required")
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise SpatialStateError("timestamp_required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SpatialStateError("timestamp_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SpatialStateError("timestamp_offset_required")
    return parsed.astimezone(UTC)


def payload_digest(value: object) -> str:
    return bounded_sha256(normalize_compatibility_numbers(value), prefixed=True)


def authorization_binding_digest(authorization: Mapping[str, object]) -> str:
    material = {
        "owner": authorization.get("owner"),
        "authorization_ref": authorization.get("authorization_ref"),
        "issued_at": authorization.get("issued_at"),
        "expires_at": authorization.get("expires_at"),
        "maximum_provider_attempts": authorization.get("maximum_provider_attempts"),
        "quota_limit_digest": authorization.get("quota_limit_digest"),
    }
    return payload_digest(material)


def _exact_nonnegative_integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _required_digest(value: object, field: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        errors.append(f"{field}:sha256_digest_required")


def validate_build_state_receipt(
    receipt: Mapping[str, object],
    *,
    prior: Mapping[str, object] | None = None,
) -> None:
    errors: list[str] = []
    state = str(receipt.get("state") or "")
    authorization = receipt.get("authorization")
    idempotency = receipt.get("idempotency")
    quota = receipt.get("quota")
    parentage = receipt.get("parentage")
    if not isinstance(authorization, Mapping):
        raise SpatialTransitionError("authorization_object_required")
    if not isinstance(idempotency, Mapping):
        raise SpatialTransitionError("idempotency_object_required")
    if not isinstance(quota, Mapping):
        raise SpatialTransitionError("quota_object_required")
    if not isinstance(parentage, Mapping):
        raise SpatialTransitionError("parentage_object_required")

    attempt = _exact_nonnegative_integer(quota.get("attempt_number"))
    if attempt is None:
        errors.append("quota.attempt_number:exact_nonnegative_integer_required")
        attempt = -1
    reservation = quota.get("reservation_ref_digest")
    reservation_expires = quota.get("reservation_expires_at")
    mutation = quota.get("mutation_token_digest")
    consumption = quota.get("consumption_receipt_digest")
    compensation = quota.get("compensation_receipt_digest")
    release_receipt = receipt.get("release_receipt_digest")
    output_digest = receipt.get("output_digest")
    output_manifest_ref = receipt.get("output_manifest_ref")

    build_lineage_fields = (
        "scope_digest",
        "key_digest",
        "normalized_request_digest",
        "composition_digest",
        "authorization_binding_digest",
    )
    authorization_fields = (
        "owner",
        "authorization_ref",
        "issued_at",
        "expires_at",
        "maximum_provider_attempts",
        "quota_limit_digest",
    )
    parentage_fields = (
        "request_digest",
        "source_digest",
        "source_packet_digest",
        "style_digest",
    )

    if state in BUILD_STATES:
        for field in build_lineage_fields:
            _required_digest(idempotency.get(field), f"idempotency.{field}", errors)
        for field in parentage_fields:
            _required_digest(parentage.get(field), f"parentage.{field}", errors)
        for field in authorization_fields:
            value = authorization.get(field)
            if value is None or value == "":
                errors.append(f"authorization.{field}:original_lineage_required")
        maximum_attempts = _exact_nonnegative_integer(authorization.get("maximum_provider_attempts"))
        if maximum_attempts not in {1, 2}:
            errors.append("authorization.maximum_provider_attempts:bounded_positive_integer_required")
            maximum_attempts = 0
        try:
            expected_binding = authorization_binding_digest(authorization)
        except (TypeError, ValueError):
            expected_binding = ""
        if idempotency.get("authorization_binding_digest") != expected_binding:
            errors.append("idempotency.authorization_binding_digest:mismatch")
        if attempt > maximum_attempts:
            errors.append("quota.attempt_number:exceeds_authorization")

    if state == AUDIT_ONLY_STATE:
        if authorization.get("state") != "not_present_audit_only":
            errors.append("authorization:audit_only_state_required")
        if any(idempotency.get(field) is not None for field in build_lineage_fields[1:]):
            errors.append("idempotency:audit_only_build_lineage_must_be_null")
        if attempt != 0 or any(
            value is not None
            for value in (reservation, reservation_expires, mutation, consumption, compensation)
        ):
            errors.append("quota:audit_only_execution_lineage_must_be_null")
    elif state == GENERIC_BLOCKED_STATE:
        if any(idempotency.get(field) is not None for field in build_lineage_fields[1:]):
            errors.append("idempotency:generic_blocked_build_lineage_must_be_null")
        if attempt != 0 or any(
            value is not None
            for value in (reservation, reservation_expires, mutation, consumption, compensation)
        ):
            errors.append("quota:generic_blocked_execution_lineage_must_be_null")
        if output_digest not in {None, ""} or output_manifest_ref not in {None, ""}:
            errors.append("generic_blocked:success_fields_forbidden")
    elif state == "authorization_verified":
        if attempt != 0 or any(
            value is not None
            for value in (reservation, reservation_expires, mutation, consumption, compensation)
        ):
            errors.append("authorization_verified:execution_lineage_must_be_null")
    elif state in {"reservation_held", "released"}:
        _required_digest(reservation, "quota.reservation_ref_digest", errors)
        if reservation_expires is None:
            errors.append("quota.reservation_expires_at:required")
        if attempt != 0 or any(value is not None for value in (mutation, consumption, compensation)):
            errors.append(f"{state}:later_execution_lineage_must_be_null")
        if state == "released":
            _required_digest(release_receipt, "release_receipt_digest", errors)
    elif state in {"attempt_committed", "charge_pending", "cancelled_reconciliation_pending"}:
        _required_digest(reservation, "quota.reservation_ref_digest", errors)
        _required_digest(mutation, "quota.mutation_token_digest", errors)
        if reservation_expires is None or attempt < 1:
            errors.append(f"{state}:attempt_lineage_required")
        if consumption is not None or compensation is not None:
            errors.append(f"{state}:later_receipts_must_be_null")
    elif state in CONSUMED_STATES:
        _required_digest(reservation, "quota.reservation_ref_digest", errors)
        _required_digest(mutation, "quota.mutation_token_digest", errors)
        _required_digest(consumption, "quota.consumption_receipt_digest", errors)
        if attempt < 1:
            errors.append(f"{state}:attempt_lineage_required")
        if state not in COMPENSATED_STATES and compensation is not None:
            errors.append(f"{state}:compensation_receipt_must_be_null")
        if state in COMPENSATED_STATES:
            _required_digest(compensation, "quota.compensation_receipt_digest", errors)
    else:
        errors.append("state:unsupported")

    if state != "released" and release_receipt not in {None, ""}:
        errors.append(f"{state}:release_receipt_digest_forbidden")

    if state == "closed_consumed":
        _required_digest(output_digest, "output_digest", errors)
        if not isinstance(output_manifest_ref, str) or not output_manifest_ref:
            errors.append("output_manifest_ref:required")
    elif state != "consumed" and (output_digest not in {None, ""} or output_manifest_ref not in {None, ""}):
        errors.append(f"{state}:success_fields_forbidden")

    if state == "compensation_failed_blocked":
        if receipt.get("quota_posture") != "blocked" or receipt.get("readiness_projection") != "blocked":
            errors.append("compensation_failed_blocked:blocked_posture_required")
        route_state = receipt.get("route_state")
        if route_state not in {"blocked", "kill_switch_engaged"}:
            errors.append("compensation_failed_blocked:blocked_route_required")

    if prior is not None:
        prior_state = str(prior.get("state") or "")
        if state not in _ALLOWED_TRANSITIONS.get(prior_state, set()):
            errors.append(f"transition:{prior_state}_to_{state}_forbidden")
        prior_auth = prior.get("authorization")
        prior_idempotency = prior.get("idempotency")
        prior_parentage = prior.get("parentage")
        if isinstance(prior_auth, Mapping):
            for field in authorization_fields:
                if authorization.get(field) != prior_auth.get(field):
                    errors.append(f"authorization.{field}:immutable_lineage_changed")
        if isinstance(prior_idempotency, Mapping):
            for field in build_lineage_fields:
                if idempotency.get(field) != prior_idempotency.get(field):
                    errors.append(f"idempotency.{field}:immutable_lineage_changed")
        if isinstance(prior_parentage, Mapping):
            for field in parentage_fields:
                if parentage.get(field) != prior_parentage.get(field):
                    errors.append(f"parentage.{field}:immutable_lineage_changed")
        prior_attempt = _exact_nonnegative_integer(
            prior.get("quota", {}).get("attempt_number")
            if isinstance(prior.get("quota"), Mapping)
            else None
        )
        if prior_attempt is not None and attempt < prior_attempt:
            errors.append("quota.attempt_number:regression")

    if errors:
        raise SpatialTransitionError(";".join(errors))


class DurableSpatialLedger:
    _SCHEMA = "governed_spatial_private_ledger_v1"
    _RECORD_FAMILIES = frozenset({"compositions", "builds", "privacy"})

    def __init__(self, root: Path | None = None) -> None:
        self.root = (
            Path(os.path.abspath(os.path.expanduser(os.fspath(root))))
            if root is not None
            else None
        )
        self._thread_lock = threading.RLock()
        self._lifecycle_authority = SpatialLifecycleAuthority(
            marker=_LIFECYCLE_AUTHORITY_MARKER
        )
        self._guard_depth = 0
        self._active_lifecycle_guards: list[SpatialCompositionLifecycleGuard] = []
        self._lock_descriptor: int | None = None
        self._compositions: dict[str, dict[str, object]] = {}
        self._composition_index: dict[str, dict[str, object]] = {}
        self._build_histories: dict[str, list[dict[str, object]]] = {}
        self._build_index: dict[str, dict[str, object]] = {}
        self._privacy_histories: dict[str, list[dict[str, object]]] = {}
        self._privacy_index: dict[str, dict[str, object]] = {}
        if self.root is not None:
            self._prepare_root()
            with self._guard(reload=False):
                self._load_locked()

    @property
    def lifecycle_authority(self) -> SpatialLifecycleAuthority:
        return self._lifecycle_authority

    @staticmethod
    def _regular_or_missing(path: Path, *, allow_missing: bool) -> os.stat_result | None:
        try:
            details = os.lstat(path)
        except FileNotFoundError:
            if allow_missing:
                return None
            raise SpatialStateIntegrityError("private_ledger_path_missing")
        if stat.S_ISLNK(details.st_mode) or not stat.S_ISREG(details.st_mode):
            raise SpatialStateIntegrityError("private_ledger_path_not_regular")
        return details

    def _prepare_root(self) -> None:
        if self.root is None:
            return
        if os.path.lexists(self.root):
            details = os.lstat(self.root)
            if stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
                raise SpatialStateIntegrityError("private_ledger_root_invalid")
        else:
            self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        self._ensure_owned_directory(self.root, create=False)
        lock_path = self.root / ".ledger.lock"
        if os.path.lexists(lock_path):
            details = self._regular_or_missing(lock_path, allow_missing=False)
            if details is None or details.st_mode & 0o077:
                raise SpatialStateIntegrityError("private_ledger_lock_permissions")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        self._lock_descriptor = os.open(lock_path, flags, 0o600)
        os.fchmod(self._lock_descriptor, 0o600)

    @contextmanager
    def _guard(self, *, reload: bool = True) -> Iterator[None]:
        with self._thread_lock:
            outermost = self._guard_depth == 0
            if outermost and self._lock_descriptor is not None:
                fcntl.flock(self._lock_descriptor, fcntl.LOCK_EX)
            self._guard_depth += 1
            try:
                if reload and self.root is not None:
                    self._load_locked()
                yield
            finally:
                self._guard_depth -= 1
                if outermost and self._lock_descriptor is not None:
                    fcntl.flock(self._lock_descriptor, fcntl.LOCK_UN)

    @contextmanager
    def composition_privacy_lifecycle_guard(
        self,
        scope_digest: str,
    ) -> Iterator[SpatialCompositionLifecycleGuard]:
        """Hold ledger privacy ordering; callers must acquire material locks second."""

        if not isinstance(scope_digest, str) or not _DIGEST_RE.fullmatch(scope_digest):
            raise SpatialPrivacyError("privacy_scope_digest_required")
        with self._guard():
            history = self._privacy_histories.get(scope_digest, [])
            status = deepcopy(history[-1]) if history else None
            guard = SpatialCompositionLifecycleGuard(
                scope_digest,
                status,
                authority=self._lifecycle_authority,
                marker=_LIFECYCLE_GUARD_MARKER,
            )
            self._active_lifecycle_guards.append(guard)
            try:
                yield guard
            finally:
                self._active_lifecycle_guards.remove(guard)
                guard._close()

    @staticmethod
    def _safe_name(value: str) -> str:
        prefix = _SAFE_NAME_RE.sub("-", value).strip("-.")[:64] or "record"
        return f"{prefix}-{payload_digest(value)[7:23]}"

    def _ensure_owned_directory(self, directory: Path, *, create: bool) -> bool:
        if self.root is None:
            raise SpatialStateIntegrityError("private_ledger_root_missing")
        lexical = Path(os.path.abspath(os.fspath(directory)))
        if lexical == self.root:
            relative_parts: tuple[str, ...] = ()
        else:
            try:
                relative_parts = lexical.relative_to(self.root).parts
            except ValueError as exc:
                raise SpatialStateIntegrityError("private_ledger_directory_escape") from exc
            if len(relative_parts) != 1 or relative_parts[0] not in self._RECORD_FAMILIES:
                raise SpatialStateIntegrityError("private_ledger_directory_invalid")

        try:
            root_details = os.lstat(self.root)
        except FileNotFoundError as exc:
            raise SpatialStateIntegrityError("private_ledger_root_missing") from exc
        if stat.S_ISLNK(root_details.st_mode) or not stat.S_ISDIR(root_details.st_mode):
            raise SpatialStateIntegrityError("private_ledger_root_invalid")
        root_flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        root_descriptor = os.open(self.root, root_flags)
        try:
            os.fchmod(root_descriptor, 0o700)
            if not relative_parts:
                return True
            name = relative_parts[0]
            try:
                details = os.stat(name, dir_fd=root_descriptor, follow_symlinks=False)
            except FileNotFoundError:
                if not create:
                    return False
                os.mkdir(name, mode=0o700, dir_fd=root_descriptor)
                details = os.stat(name, dir_fd=root_descriptor, follow_symlinks=False)
            if stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
                raise SpatialStateIntegrityError("private_ledger_directory_not_regular")
            child_descriptor = os.open(name, root_flags, dir_fd=root_descriptor)
            try:
                os.fchmod(child_descriptor, 0o700)
            finally:
                os.close(child_descriptor)
            return True
        finally:
            os.close(root_descriptor)

    def _write_private(self, path: Path, payload: Mapping[str, object]) -> None:
        self._ensure_owned_directory(path.parent, create=True)
        self._regular_or_missing(path, allow_missing=True)
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        temporary: Path | None = None
        descriptor: int | None = None
        directory: int | None = None
        try:
            directory = os.open(
                path.parent,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            for _ in range(32):
                candidate = path.parent / f".{path.name}.{secrets.token_hex(16)}.tmp"
                try:
                    descriptor = os.open(candidate.name, flags, 0o600, dir_fd=directory)
                except FileExistsError:
                    continue
                temporary = candidate
                break
            if descriptor is None or temporary is None:
                raise SpatialStateIntegrityError("private_ledger_unique_temp_unavailable")
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                descriptor = None
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._regular_or_missing(path, allow_missing=True)
            os.replace(
                temporary.name,
                path.name,
                src_dir_fd=directory,
                dst_dir_fd=directory,
            )
            temporary = None
            os.fsync(directory)
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            if temporary is not None:
                try:
                    if directory is None:
                        os.unlink(temporary)
                    else:
                        os.unlink(temporary.name, dir_fd=directory)
                except FileNotFoundError:
                    pass
            if directory is not None:
                os.close(directory)

    def _read_private(self, path: Path) -> dict[str, object]:
        if not self._ensure_owned_directory(path.parent, create=False):
            raise SpatialStateIntegrityError("private_record_parent_missing")
        try:
            directory = os.open(
                path.parent,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
        except OSError as exc:
            raise SpatialStateIntegrityError("private_record_parent_invalid") from exc
        descriptor: int | None = None
        try:
            descriptor = os.open(
                path.name,
                os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory,
            )
            details = os.fstat(descriptor)
            if not stat.S_ISREG(details.st_mode) or details.st_mode & 0o077:
                raise SpatialStateIntegrityError("private_record_permissions")
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = None
                raw = handle.read()
            return parse_raw_transport_json(raw)
        except (OSError, ValueError) as exc:
            raise SpatialStateIntegrityError("private_record_payload_invalid") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            os.close(directory)

    def _index_material(
        self,
        *,
        composition_index: Mapping[str, object] | None = None,
        build_index: Mapping[str, object] | None = None,
        privacy_index: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        return {
            "schema_name": self._SCHEMA,
            "compositions": deepcopy(self._composition_index if composition_index is None else composition_index),
            "builds": deepcopy(self._build_index if build_index is None else build_index),
            "privacy": deepcopy(self._privacy_index if privacy_index is None else privacy_index),
        }

    def _persist_index(
        self,
        *,
        composition_index: Mapping[str, object] | None = None,
        build_index: Mapping[str, object] | None = None,
        privacy_index: Mapping[str, object] | None = None,
    ) -> None:
        if self.root is None:
            return
        material = self._index_material(
            composition_index=composition_index,
            build_index=build_index,
            privacy_index=privacy_index,
        )
        self._write_private(
            self.root / "index.json",
            {**material, "index_digest": payload_digest(material)},
        )

    def _record_path(self, family: str, identity: str, sequence: int = 0) -> Path:
        if self.root is None:
            raise SpatialStateIntegrityError("private_ledger_root_missing")
        if family not in self._RECORD_FAMILIES:
            raise SpatialStateIntegrityError("private_ledger_record_family_invalid")
        self._ensure_owned_directory(self.root / family, create=True)
        suffix = f"-{sequence:04d}" if sequence else ""
        return self.root / family / f"{self._safe_name(identity)}{suffix}.json"

    def _load_indexed_record(self, entry: Mapping[str, object]) -> tuple[Path, dict[str, object]]:
        if self.root is None:
            raise SpatialStateIntegrityError("private_ledger_root_missing")
        raw_path = entry.get("path")
        if not isinstance(raw_path, str):
            raise SpatialStateIntegrityError("private_index_path_invalid")
        relative = Path(raw_path)
        if (
            relative.is_absolute()
            or relative.suffix != ".json"
            or len(relative.parts) != 2
            or relative.parts[0] not in self._RECORD_FAMILIES
            or ".." in relative.parts
        ):
            raise SpatialStateIntegrityError("private_index_path_invalid")
        candidate = self.root / relative
        self._ensure_owned_directory(candidate.parent, create=False)
        if os.path.lexists(candidate) and stat.S_ISLNK(os.lstat(candidate).st_mode):
            raise SpatialStateIntegrityError("private_index_symlink_forbidden")
        record = self._read_private(candidate)
        if entry.get("receipt_digest") != payload_digest(record):
            raise SpatialStateIntegrityError("private_receipt_digest_integrity_failed")
        return candidate, record

    def _load_locked(self) -> None:
        if self.root is None:
            return
        index_path = self.root / "index.json"
        if not os.path.lexists(index_path):
            for family in self._RECORD_FAMILIES:
                directory = self.root / family
                if self._ensure_owned_directory(directory, create=False) and any(directory.iterdir()):
                    raise SpatialStateIntegrityError("private_index_missing_with_orphans")
            self._compositions = {}
            self._composition_index = {}
            self._build_histories = {}
            self._build_index = {}
            self._privacy_histories = {}
            self._privacy_index = {}
            return
        index = self._read_private(index_path)
        material = {
            "schema_name": index.get("schema_name"),
            "compositions": index.get("compositions"),
            "builds": index.get("builds"),
            "privacy": index.get("privacy"),
        }
        if material["schema_name"] != self._SCHEMA:
            raise SpatialStateIntegrityError("private_index_schema_invalid")
        if index.get("index_digest") != payload_digest(material):
            raise SpatialStateIntegrityError("private_index_digest_integrity_failed")
        if not all(isinstance(material[field], dict) for field in ("compositions", "builds", "privacy")):
            raise SpatialStateIntegrityError("private_index_collections_invalid")

        compositions: dict[str, dict[str, object]] = {}
        builds: dict[str, list[dict[str, object]]] = {}
        privacy: dict[str, list[dict[str, object]]] = {}
        indexed_paths: set[Path] = set()
        for key, raw_entry in material["compositions"].items():  # type: ignore[union-attr]
            if not isinstance(raw_entry, Mapping):
                raise SpatialStateIntegrityError("private_composition_index_invalid")
            path, receipt = self._load_indexed_record(raw_entry)
            if receipt.get("idempotency_key") != key:
                raise SpatialStateIntegrityError("private_composition_identity_integrity_failed")
            receipt_material_digest = receipt.get("material_digest") or payload_digest(
                {
                    "request_digest": receipt.get("request_digest"),
                    "source_packet_digest": receipt.get("source_packet_digest"),
                    "style_digest": receipt.get("style_digest"),
                    "composition_digest": receipt.get("composition_digest"),
                }
            )
            if (
                receipt.get("composition_digest") != raw_entry.get("composition_digest")
                or receipt_material_digest != raw_entry.get("material_digest")
            ):
                raise SpatialStateIntegrityError("private_composition_index_binding_failed")
            compositions[str(key)] = receipt
            indexed_paths.add(path)
        for key, raw_entry in material["builds"].items():  # type: ignore[union-attr]
            if not isinstance(raw_entry, Mapping) or not isinstance(raw_entry.get("transitions"), list):
                raise SpatialStateIntegrityError("private_build_index_invalid")
            build_request_digest = raw_entry.get("build_request_digest")
            if not isinstance(build_request_digest, str) or not build_request_digest:
                raise SpatialStateIntegrityError("private_build_request_digest_invalid")
            history: list[dict[str, object]] = []
            for sequence, transition in enumerate(raw_entry["transitions"], start=1):
                if not isinstance(transition, Mapping):
                    raise SpatialStateIntegrityError("private_build_transition_index_invalid")
                path, receipt = self._load_indexed_record(transition)
                expected_prior = payload_digest(history[-1]) if history else None
                if (
                    transition.get("sequence") != sequence
                    or receipt.get("transition_sequence") != sequence
                    or transition.get("state") != (receipt.get("state") or receipt.get("status"))
                    or receipt.get("prior_receipt_digest") != expected_prior
                    or receipt.get("build_request_digest") != build_request_digest
                ):
                    raise SpatialStateIntegrityError("private_build_transition_chain_invalid")
                if "state" in receipt:
                    try:
                        validate_build_state_receipt(receipt, prior=history[-1] if history else None)
                    except SpatialTransitionError as exc:
                        raise SpatialStateIntegrityError("private_build_state_semantics_invalid") from exc
                history.append(receipt)
                indexed_paths.add(path)
            if not history or any(receipt.get("build_idempotency_key") != key for receipt in history):
                raise SpatialStateIntegrityError("private_build_identity_integrity_failed")
            builds[str(key)] = history
        for scope, raw_entry in material["privacy"].items():  # type: ignore[union-attr]
            if not isinstance(raw_entry, Mapping) or not isinstance(raw_entry.get("transitions"), list):
                raise SpatialStateIntegrityError("private_privacy_index_invalid")
            history = []
            for sequence, transition in enumerate(raw_entry["transitions"], start=1):
                if not isinstance(transition, Mapping):
                    raise SpatialStateIntegrityError("private_privacy_transition_index_invalid")
                path, receipt = self._load_indexed_record(transition)
                if (
                    transition.get("sequence") != sequence
                    or receipt.get("sequence") != sequence
                    or transition.get("action") != receipt.get("action")
                    or transition.get("material_digest") != receipt.get("material_digest")
                ):
                    raise SpatialStateIntegrityError("private_privacy_transition_chain_invalid")
                history.append(receipt)
                indexed_paths.add(path)
            if not history or any(receipt.get("scope_digest") != scope for receipt in history):
                raise SpatialStateIntegrityError("private_privacy_identity_integrity_failed")
            privacy[str(scope)] = history

        actual_paths: set[Path] = set()
        for family in self._RECORD_FAMILIES:
            directory = self.root / family
            if not self._ensure_owned_directory(directory, create=False):
                continue
            for path in directory.iterdir():
                details = os.lstat(path)
                if stat.S_ISLNK(details.st_mode) or not stat.S_ISREG(details.st_mode):
                    raise SpatialStateIntegrityError("private_record_path_not_regular")
                actual_paths.add(path)
        if actual_paths != indexed_paths:
            raise SpatialStateIntegrityError("private_index_orphan_or_missing_entry")
        self._compositions = compositions
        self._composition_index = deepcopy(material["compositions"])  # type: ignore[arg-type]
        self._build_histories = builds
        self._build_index = deepcopy(material["builds"])  # type: ignore[arg-type]
        self._privacy_histories = privacy
        self._privacy_index = deepcopy(material["privacy"])  # type: ignore[arg-type]

    @staticmethod
    def _unlink_new_record(path: Path | None) -> None:
        if path is not None:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass

    def integrity_summary(self) -> dict[str, object]:
        with self._guard():
            material = self._index_material()
            return {
                "status": "pass",
                "index_digest": payload_digest(material),
                "composition_count": len(self._compositions),
                "build_count": len(self._build_histories),
                "privacy_scope_count": len(self._privacy_histories),
                "persistent": self.root is not None,
            }

    def find_composition(self, digest: str) -> dict[str, object] | None:
        with self._guard():
            for receipt in self._compositions.values():
                if receipt.get("composition_digest") == digest:
                    return deepcopy(receipt)
            return None

    def find_composition_by_key(self, key: str) -> dict[str, object] | None:
        with self._guard():
            receipt = self._compositions.get(key)
            return deepcopy(receipt) if receipt is not None else None

    def save_composition(self, receipt: Mapping[str, object]) -> dict[str, object]:
        candidate_receipt = deepcopy(dict(receipt))
        key = candidate_receipt.get("idempotency_key")
        composition_digest = candidate_receipt.get("composition_digest")
        if not isinstance(key, str) or not key or not isinstance(composition_digest, str):
            raise SpatialStateError("composition_identity_required")
        material_digest = str(
            candidate_receipt.get("material_digest")
            or payload_digest(
                {
                    "request_digest": candidate_receipt.get("request_digest"),
                    "source_packet_digest": candidate_receipt.get("source_packet_digest"),
                    "style_digest": candidate_receipt.get("style_digest"),
                    "composition_digest": composition_digest,
                }
            )
        )
        with self._guard():
            existing = self._compositions.get(key)
            existing_entry = self._composition_index.get(key)
            if existing is not None and isinstance(existing_entry, Mapping):
                if existing_entry.get("material_digest") != material_digest:
                    raise SpatialIdempotencyConflict("idempotency_key_payload_conflict")
                return deepcopy(existing)
            candidate_index = deepcopy(self._composition_index)
            path: Path | None = None
            if self.root is not None:
                path = self._record_path("compositions", composition_digest)
                self._write_private(path, candidate_receipt)
                relative_path = str(path.relative_to(self.root))
            else:
                relative_path = ""
            candidate_index[key] = {
                "path": relative_path,
                "material_digest": material_digest,
                "composition_digest": composition_digest,
                "receipt_digest": payload_digest(candidate_receipt),
            }
            try:
                self._persist_index(composition_index=candidate_index)
            except Exception:
                self._unlink_new_record(path)
                raise
            self._composition_index = candidate_index
            self._compositions[key] = candidate_receipt
            return deepcopy(candidate_receipt)

    def find_build(self, key: str) -> dict[str, object] | None:
        with self._guard():
            history = self._build_histories.get(key, [])
            return deepcopy(history[-1]) if history else None

    def build_history(self, key: str) -> list[dict[str, object]]:
        with self._guard():
            return deepcopy(self._build_histories.get(key, []))

    def save_build(self, key: str, receipt: Mapping[str, object]) -> dict[str, object]:
        candidate = deepcopy(dict(receipt))
        candidate.setdefault("build_idempotency_key", key)
        return self._save_build_transition(key, candidate, first_only=True)

    def append_build_transition(self, key: str, receipt: Mapping[str, object]) -> dict[str, object]:
        return self._save_build_transition(key, deepcopy(dict(receipt)), first_only=False)

    def _save_build_transition(
        self,
        key: str,
        receipt: dict[str, object],
        *,
        first_only: bool,
    ) -> dict[str, object]:
        if not key or receipt.get("build_idempotency_key") != key:
            raise SpatialStateError("build_identity_required")
        request_digest = receipt.get("build_request_digest")
        if not isinstance(request_digest, str) or not request_digest:
            raise SpatialStateError("build_request_digest_required")
        with self._guard():
            history = self._build_histories.get(key, [])
            entry = self._build_index.get(key)
            if history:
                if not isinstance(entry, Mapping) or entry.get("build_request_digest") != request_digest:
                    raise SpatialIdempotencyConflict("build_idempotency_key_payload_conflict")
                if first_only:
                    return deepcopy(history[-1])
                if receipt.get("state") == history[-1].get("state"):
                    candidate_intent = receipt.get("pending_operation")
                    prior_intent = history[-1].get("pending_operation")
                    distinct_release_intent = (
                        receipt.get("state") == "reservation_held"
                        and (prior_intent is None or prior_intent == "")
                        and isinstance(candidate_intent, Mapping)
                        and candidate_intent.get("operation") == "release"
                        and candidate_intent.get("outcome") == "pending_or_unknown"
                        and isinstance(candidate_intent.get("intent_digest"), str)
                        and bool(_DIGEST_RE.fullmatch(candidate_intent["intent_digest"]))
                        and receipt.get("reconciliation_required") is True
                        and receipt.get("automatic_retry_allowed") is False
                    )
                    failure_evidence = receipt.get("operation_failure_evidence")
                    matched_unknown_outcome = (
                        isinstance(prior_intent, Mapping)
                        and isinstance(failure_evidence, Mapping)
                        and failure_evidence.get("operation") == prior_intent.get("operation")
                        and failure_evidence.get("outcome") == "unknown"
                        and isinstance(failure_evidence.get("evidence_digest"), str)
                        and bool(_DIGEST_RE.fullmatch(failure_evidence["evidence_digest"]))
                        and receipt.get("pending_operation") is None
                        and receipt.get("reconciliation_required") is True
                        and receipt.get("automatic_retry_allowed") is False
                    )
                    if not matched_unknown_outcome and not distinct_release_intent:
                        raise SpatialTransitionError("duplicate_same_state_transition_forbidden")
            elif not first_only and receipt.get("state") != "authorization_verified":
                raise SpatialTransitionError("first_build_state_must_be_authorization_verified")
            if "state" in receipt:
                validate_build_state_receipt(receipt, prior=history[-1] if history else None)
            sequence = len(history) + 1
            receipt["transition_sequence"] = sequence
            receipt["prior_receipt_digest"] = payload_digest(history[-1]) if history else None
            candidate_index = deepcopy(self._build_index)
            transition_entry: dict[str, object]
            path: Path | None = None
            if self.root is not None:
                path = self._record_path("builds", key, sequence)
                self._write_private(path, receipt)
                relative_path = str(path.relative_to(self.root))
            else:
                relative_path = ""
            transition_entry = {
                "path": relative_path,
                "receipt_digest": payload_digest(receipt),
                "state": receipt.get("state") or receipt.get("status"),
                "sequence": sequence,
            }
            if key not in candidate_index:
                candidate_index[key] = {
                    "build_request_digest": request_digest,
                    "transitions": [transition_entry],
                }
            else:
                transitions = candidate_index[key].get("transitions")
                if not isinstance(transitions, list):
                    self._unlink_new_record(path)
                    raise SpatialStateIntegrityError("private_build_transition_index_invalid")
                transitions.append(transition_entry)
            try:
                self._persist_index(build_index=candidate_index)
            except Exception:
                self._unlink_new_record(path)
                raise
            self._build_index = candidate_index
            self._build_histories.setdefault(key, []).append(receipt)
            return deepcopy(receipt)

    @staticmethod
    def _validate_legal_hold(
        hold: Mapping[str, object] | None,
        *,
        scope_digest: str,
        observed_at: datetime,
    ) -> dict[str, object]:
        if hold is None:
            return {"state": "not_present"}
        required = ("case_ref", "authority_ref", "owner_ref", "issued_at", "expires_at", "review_due_at")
        if any(not isinstance(hold.get(field), str) or not hold.get(field) for field in required):
            raise SpatialPrivacyError("legal_hold_required_fields_missing")
        if hold.get("scope_digest") != scope_digest:
            raise SpatialPrivacyError("legal_hold_scope_mismatch")
        issued = parse_time(hold["issued_at"])
        expires = parse_time(hold["expires_at"])
        review_due = parse_time(hold["review_due_at"])
        if not issued < expires <= issued + timedelta(days=90):
            raise SpatialPrivacyError("legal_hold_window_invalid")
        if not issued <= review_due <= issued + timedelta(days=30):
            raise SpatialPrivacyError("legal_hold_review_window_invalid")
        if not issued <= observed_at < expires:
            raise SpatialPrivacyError("legal_hold_not_current")
        if observed_at > review_due:
            raise SpatialPrivacyError("legal_hold_review_overdue")
        return {
            "state": "valid_evidence_only",
            "case_ref_digest": payload_digest(hold["case_ref"]),
            "authority_ref_digest": payload_digest(hold["authority_ref"]),
            "owner_ref_digest": payload_digest(hold["owner_ref"]),
            "scope_digest": scope_digest,
            "issued_at": hold["issued_at"],
            "expires_at": hold["expires_at"],
            "review_due_at": hold["review_due_at"],
            "serving_allowed": False,
            "restoration_allowed": False,
        }

    def record_privacy_action(
        self,
        *,
        scope_digest: str,
        action: str,
        reason_digest: str,
        observed_at: datetime,
        cascade_evidence_digests: Iterable[str] = (),
        legal_hold: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        if not _DIGEST_RE.fullmatch(scope_digest) or not _DIGEST_RE.fullmatch(reason_digest):
            raise SpatialPrivacyError("privacy_scope_and_reason_digests_required")
        if action not in {"revoked", "withdrawn", "deleted"}:
            raise SpatialPrivacyError("privacy_action_invalid")
        evidence = sorted(set(cascade_evidence_digests))
        if any(not _DIGEST_RE.fullmatch(value) for value in evidence):
            raise SpatialPrivacyError("privacy_cascade_evidence_digest_invalid")
        timestamp = utc_iso(observed_at)
        normalized_observed_at = parse_time(timestamp)
        try:
            hold_projection = self._validate_legal_hold(
                legal_hold,
                scope_digest=scope_digest,
                observed_at=normalized_observed_at,
            )
        except SpatialPrivacyError as exc:
            hold_projection = {
                "state": "blocked_invalid",
                "reason_code": str(exc),
                "scope_digest": scope_digest,
                "serving_allowed": False,
                "restoration_allowed": False,
            }
        material_digest = payload_digest(
            {
                "scope_digest": scope_digest,
                "action": action,
                "reason_digest": reason_digest,
                "cascade_evidence_digests": evidence,
                "legal_hold": hold_projection,
            }
        )
        with self._guard():
            history = self._privacy_histories.get(scope_digest, [])
            entry = self._privacy_index.get(scope_digest)
            if history and isinstance(entry, Mapping):
                for existing in history:
                    if existing.get("material_digest") == material_digest:
                        return deepcopy(existing)
            sequence = len(history) + 1
            receipt = {
                "contract_name": "governed_spatial_privacy_tombstone_v1",
                "scope_digest": scope_digest,
                "action": action,
                "reason_digest": reason_digest,
                "recorded_at": timestamp,
                "sequence": sequence,
                "material_digest": material_digest,
                "cascade_evidence_digests": evidence,
                "legal_hold": hold_projection,
                "serving_allowed": False,
                "build_allowed": False,
                "restoration_allowed": False,
                "source_bytes_retained": hold_projection.get("state") == "valid_evidence_only",
                "public_projection": {"state": "unavailable", "reason": action},
            }
            candidate_index = deepcopy(self._privacy_index)
            path: Path | None = None
            if self.root is not None:
                path = self._record_path("privacy", scope_digest, sequence)
                self._write_private(path, receipt)
                relative_path = str(path.relative_to(self.root))
            else:
                relative_path = ""
            transition = {
                "path": relative_path,
                "receipt_digest": payload_digest(receipt),
                "material_digest": material_digest,
                "sequence": sequence,
                "action": action,
            }
            if scope_digest not in candidate_index:
                candidate_index[scope_digest] = {"transitions": [transition]}
            else:
                transitions = candidate_index[scope_digest].get("transitions")
                if not isinstance(transitions, list):
                    self._unlink_new_record(path)
                    raise SpatialStateIntegrityError("private_privacy_transition_index_invalid")
                transitions.append(transition)
            try:
                self._persist_index(privacy_index=candidate_index)
            except Exception:
                self._unlink_new_record(path)
                raise
            self._privacy_index = candidate_index
            self._privacy_histories.setdefault(scope_digest, []).append(receipt)
            for lifecycle_guard in self._active_lifecycle_guards:
                if lifecycle_guard.scope_digest == scope_digest:
                    lifecycle_guard._record_privacy_status(receipt)
            return deepcopy(receipt)

    def privacy_status(self, scope_digest: str) -> dict[str, object] | None:
        with self._guard():
            history = self._privacy_histories.get(scope_digest, [])
            return deepcopy(history[-1]) if history else None

    def privacy_history(self, scope_digest: str) -> list[dict[str, object]]:
        with self._guard():
            return deepcopy(self._privacy_histories.get(scope_digest, []))

    def restore_privacy_scope(self, scope_digest: str) -> None:
        del scope_digest
        raise SpatialPrivacyError("privacy_self_restoration_forbidden")


__all__ = [
    "ATTEMPTED_STATES",
    "AUDIT_ONLY_STATE",
    "BUILD_STATES",
    "COMPENSATED_STATES",
    "CONSUMED_STATES",
    "DurableSpatialLedger",
    "GENERIC_BLOCKED_STATE",
    "SpatialCompositionLifecycleGuard",
    "SpatialIdempotencyConflict",
    "SpatialLifecycleAuthority",
    "SpatialPrivacyError",
    "SpatialStateError",
    "SpatialStateIntegrityError",
    "SpatialTransitionError",
    "TERMINAL_STATES",
    "authorization_binding_digest",
    "parse_time",
    "payload_digest",
    "utc_iso",
    "validate_build_state_receipt",
]
