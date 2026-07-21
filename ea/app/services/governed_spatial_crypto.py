from __future__ import annotations

import base64
from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import stat
import threading

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.services.governed_spatial_contract import (
    bounded_jcs,
    bounded_sha256,
    parse_raw_json,
    signed_payload_bytes,
)


SIGNATURE_ALGORITHM = "ed25519"
SIGNATURE_ENCODING = "base64url_no_padding"
SIGNATURE_CANONICALIZATION = "rfc8785_jcs"
SIGNATURE_SCOPE = "entire_receipt_excluding_signature_value_and_signed_payload_digest"
MAXIMUM_CLOCK_SKEW = timedelta(seconds=300)
MAXIMUM_RECEIPT_AGE = timedelta(hours=24)

_SIGNATURE_VALUE_RE = re.compile(r"^[A-Za-z0-9_-]{85}[AQgw]$")
_FINGERPRINT_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_KEY_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_SIGNATURE_FIELDS = {
    "algorithm",
    "encoding",
    "signature_value",
    "key_ref",
    "key_fingerprint",
    "key_epoch",
    "canonicalization",
    "signed_payload_scope",
    "signed_payload_digest",
}


class SpatialCryptoError(ValueError):
    """Base class for safe local cryptographic failures."""


class KeyRegistryError(SpatialCryptoError):
    pass


class SignatureVerificationError(SpatialCryptoError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise SignatureVerificationError("timestamp_required")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise SignatureVerificationError("timestamp_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SignatureVerificationError("timestamp_offset_required")
    return parsed.astimezone(UTC)


def canonical_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("offset_aware_timestamp_required")
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode_canonical(value: str, *, expected_size: int, code: str) -> bytes:
    if "=" in value:
        raise SignatureVerificationError(f"{code}_padding_forbidden")
    try:
        padding = "=" * (-len(value) % 4)
        decoded = base64.b64decode((value + padding).encode("ascii"), altchars=b"-_", validate=True)
    except (ValueError, UnicodeEncodeError) as exc:
        raise SignatureVerificationError(f"{code}_decode") from exc
    if len(decoded) != expected_size or _b64url_encode(decoded) != value:
        raise SignatureVerificationError(f"{code}_canonical")
    return decoded


def encode_ed25519_signature(signature: bytes) -> str:
    if len(signature) != 64:
        raise SpatialCryptoError("ed25519_signature_length_invalid")
    encoded = _b64url_encode(signature)
    if not _SIGNATURE_VALUE_RE.fullmatch(encoded):
        raise SpatialCryptoError("ed25519_signature_encoding_invalid")
    return encoded


def decode_ed25519_signature(value: object) -> bytes:
    if not isinstance(value, str) or not _SIGNATURE_VALUE_RE.fullmatch(value):
        raise SpatialCryptoError("ed25519_signature_encoding_invalid")
    try:
        return _b64url_decode_canonical(value, expected_size=64, code="ed25519_signature")
    except SignatureVerificationError as exc:
        raise SpatialCryptoError(exc.code) from exc


def public_key_fingerprint(public_key: bytes | Ed25519PublicKey | object) -> str:
    if isinstance(public_key, Ed25519PublicKey):
        public_key_bytes = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    elif isinstance(public_key, bytes):
        public_key_bytes = public_key
    else:
        raise KeyRegistryError("ed25519_public_key_type")
    if len(public_key_bytes) != 32:
        raise KeyRegistryError("ed25519_public_key_size")
    return "sha256:" + hashlib.sha256(public_key_bytes).hexdigest()


@dataclass(frozen=True, slots=True)
class Ed25519KeyRecord:
    issuer: str
    environment: str
    key_ref: str
    key_epoch: int
    public_key_bytes: bytes
    not_before: str
    not_after: str
    state: str = "active"
    revoked_at: str | None = None
    revocation_reason_digest: str | None = None

    def __post_init__(self) -> None:
        if not self.issuer or not self.environment:
            raise KeyRegistryError("key_owner_and_environment_required")
        if not _KEY_REF_RE.fullmatch(self.key_ref):
            raise KeyRegistryError("key_ref_invalid")
        if isinstance(self.key_epoch, bool) or not isinstance(self.key_epoch, int) or self.key_epoch < 0:
            raise KeyRegistryError("key_epoch_invalid")
        if len(self.public_key_bytes) != 32:
            raise KeyRegistryError("ed25519_public_key_size")
        not_before = parse_timestamp(self.not_before)
        not_after = parse_timestamp(self.not_after)
        if not_before >= not_after:
            raise KeyRegistryError("key_window_invalid")
        if self.state not in {"active", "revoked"}:
            raise KeyRegistryError("key_state_invalid")
        if self.state == "active" and (self.revoked_at is not None or self.revocation_reason_digest is not None):
            raise KeyRegistryError("active_key_revocation_fields_forbidden")
        if self.state == "revoked":
            if self.revoked_at is None or self.revocation_reason_digest is None:
                raise KeyRegistryError("revoked_key_evidence_required")
            revoked_at = parse_timestamp(self.revoked_at)
            if not not_before <= revoked_at <= not_after:
                raise KeyRegistryError("revoked_at_outside_key_window")
            if not _DIGEST_RE.fullmatch(self.revocation_reason_digest):
                raise KeyRegistryError("revocation_reason_digest_invalid")

    @property
    def fingerprint(self) -> str:
        return public_key_fingerprint(self.public_key_bytes)

    @property
    def identity(self) -> tuple[str, str, str, int]:
        return self.issuer, self.environment, self.key_ref, self.key_epoch

    def as_dict(self) -> dict[str, object]:
        return {
            "issuer": self.issuer,
            "environment": self.environment,
            "key_ref": self.key_ref,
            "key_epoch": self.key_epoch,
            "algorithm": SIGNATURE_ALGORITHM,
            "public_key": _b64url_encode(self.public_key_bytes),
            "key_fingerprint": self.fingerprint,
            "not_before": self.not_before,
            "not_after": self.not_after,
            "state": self.state,
            "revoked_at": self.revoked_at,
            "revocation_reason_digest": self.revocation_reason_digest,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Ed25519KeyRecord:
        if payload.get("algorithm") != SIGNATURE_ALGORITHM:
            raise KeyRegistryError("key_algorithm_invalid")
        public_value = payload.get("public_key")
        if not isinstance(public_value, str):
            raise KeyRegistryError("public_key_encoding_required")
        try:
            public_bytes = _b64url_decode_canonical(
                public_value,
                expected_size=32,
                code="public_key",
            )
        except SignatureVerificationError as exc:
            raise KeyRegistryError(exc.code) from exc
        record = cls(
            issuer=str(payload.get("issuer") or ""),
            environment=str(payload.get("environment") or ""),
            key_ref=str(payload.get("key_ref") or ""),
            key_epoch=payload.get("key_epoch") if isinstance(payload.get("key_epoch"), int) else -1,
            public_key_bytes=public_bytes,
            not_before=str(payload.get("not_before") or ""),
            not_after=str(payload.get("not_after") or ""),
            state=str(payload.get("state") or ""),
            revoked_at=payload.get("revoked_at") if isinstance(payload.get("revoked_at"), str) else None,
            revocation_reason_digest=(
                payload.get("revocation_reason_digest")
                if isinstance(payload.get("revocation_reason_digest"), str)
                else None
            ),
        )
        if payload.get("key_fingerprint") != record.fingerprint:
            raise KeyRegistryError("persisted_key_fingerprint_mismatch")
        return record


class Ed25519KeyRegistry:
    _SCHEMA = "governed_spatial_ed25519_key_registry_v1"

    def __init__(
        self,
        records: Iterable[Ed25519KeyRecord] = (),
        *,
        path: Path | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self.path = (
            Path(os.path.abspath(os.path.expanduser(os.fspath(path))))
            if path is not None
            else None
        )
        self._records: list[Ed25519KeyRecord] = []
        self._revocation_events: list[dict[str, object]] = []
        supplied = list(records)
        if self.path is not None and os.path.lexists(self.path):
            if supplied:
                raise KeyRegistryError("persisted_registry_and_supplied_records_conflict")
            self._load()
        else:
            self._validate_global_invariants(supplied)
            if self.path is not None:
                self._persist_candidate(supplied, [])
            self._records = supplied

    @property
    def records(self) -> tuple[Ed25519KeyRecord, ...]:
        with self._lock:
            return tuple(self._records)

    @property
    def revocation_events(self) -> tuple[dict[str, object], ...]:
        with self._lock:
            return tuple(deepcopy(self._revocation_events))

    def _validate_global_invariants(
        self,
        records: Iterable[Ed25519KeyRecord] | None = None,
    ) -> None:
        identities: set[tuple[str, str, str, int]] = set()
        fingerprints: set[str] = set()
        epoch_by_ref: dict[tuple[str, str, str], int] = {}
        for record in self._records if records is None else records:
            if record.identity in identities:
                raise KeyRegistryError("key_identity_duplicate")
            if record.fingerprint in fingerprints:
                raise KeyRegistryError("global_key_fingerprint_duplicate")
            identities.add(record.identity)
            fingerprints.add(record.fingerprint)
            family = record.identity[:3]
            previous = epoch_by_ref.get(family)
            if previous is not None and record.key_epoch <= previous:
                raise KeyRegistryError("key_epoch_not_monotonic")
            epoch_by_ref[family] = record.key_epoch

    def _material(
        self,
        records: Iterable[Ed25519KeyRecord] | None = None,
        revocation_events: Iterable[Mapping[str, object]] | None = None,
    ) -> dict[str, object]:
        return {
            "schema_name": self._SCHEMA,
            "records": [record.as_dict() for record in (self._records if records is None else records)],
            "revocation_events": deepcopy(
                self._revocation_events if revocation_events is None else list(revocation_events)
            ),
        }

    @staticmethod
    def _require_regular_target(path: Path, *, allow_missing: bool) -> os.stat_result | None:
        try:
            details = os.lstat(path)
        except FileNotFoundError:
            if allow_missing:
                return None
            raise KeyRegistryError("registry_file_invalid")
        if stat.S_ISLNK(details.st_mode) or not stat.S_ISREG(details.st_mode):
            raise KeyRegistryError("registry_file_invalid")
        return details

    @staticmethod
    def _write_private(path: Path, payload: Mapping[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.parent.chmod(0o700)
        Ed25519KeyRegistry._require_regular_target(path, allow_missing=True)
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
            for _ in range(32):
                candidate = path.parent / f".{path.name}.{secrets.token_hex(16)}.tmp"
                try:
                    descriptor = os.open(candidate, flags, 0o600)
                except FileExistsError:
                    continue
                temporary = candidate
                break
            if descriptor is None or temporary is None:
                raise KeyRegistryError("registry_unique_temp_unavailable")
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                descriptor = None
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            Ed25519KeyRegistry._require_regular_target(path, allow_missing=True)
            directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
            directory = os.open(path.parent, directory_flags)
            os.replace(temporary, path)
            temporary = None
            os.fsync(directory)
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            if directory is not None:
                os.close(directory)
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass

    def _persist_candidate(
        self,
        records: Iterable[Ed25519KeyRecord],
        revocation_events: Iterable[Mapping[str, object]],
    ) -> None:
        if self.path is None:
            return
        material = self._material(records, revocation_events)
        payload = {**material, "registry_digest": bounded_sha256(material, prefixed=True)}
        self._write_private(self.path, payload)

    def _load(self) -> None:
        if self.path is None:
            raise KeyRegistryError("registry_path_missing")
        details = self._require_regular_target(self.path, allow_missing=False)
        if details is None or details.st_mode & 0o077:
            raise KeyRegistryError("registry_permissions_not_private")
        try:
            payload = parse_raw_json(self.path.read_bytes())
        except (OSError, ValueError) as exc:
            raise KeyRegistryError("registry_payload_invalid") from exc
        material = {
            "schema_name": payload.get("schema_name"),
            "records": payload.get("records"),
            "revocation_events": payload.get("revocation_events"),
        }
        if material["schema_name"] != self._SCHEMA:
            raise KeyRegistryError("registry_schema_invalid")
        if payload.get("registry_digest") != bounded_sha256(material, prefixed=True):
            raise KeyRegistryError("registry_integrity_failed")
        raw_records = material["records"]
        raw_events = material["revocation_events"]
        if not isinstance(raw_records, list) or not isinstance(raw_events, list):
            raise KeyRegistryError("registry_collections_invalid")
        loaded_records = [Ed25519KeyRecord.from_dict(item) for item in raw_records if isinstance(item, dict)]
        if len(loaded_records) != len(raw_records) or any(not isinstance(item, dict) for item in raw_events):
            raise KeyRegistryError("registry_entry_invalid")
        self._validate_global_invariants(loaded_records)
        self._records = loaded_records
        self._revocation_events = deepcopy(raw_events)

    def register(self, record: Ed25519KeyRecord) -> None:
        with self._lock:
            if any(existing.identity == record.identity for existing in self._records):
                raise KeyRegistryError("key_identity_duplicate")
            if any(existing.fingerprint == record.fingerprint for existing in self._records):
                raise KeyRegistryError("global_key_fingerprint_duplicate")
            family_epochs = [
                existing.key_epoch
                for existing in self._records
                if existing.identity[:3] == record.identity[:3]
            ]
            if family_epochs and record.key_epoch <= max(family_epochs):
                raise KeyRegistryError("key_epoch_regression")
            candidate_records = [*self._records, record]
            self._validate_global_invariants(candidate_records)
            self._persist_candidate(candidate_records, self._revocation_events)
            self._records = candidate_records

    def revoke(
        self,
        identity: tuple[str, str, str, int],
        *,
        revoked_at: datetime,
        reason_digest: str,
    ) -> Ed25519KeyRecord:
        if not _DIGEST_RE.fullmatch(reason_digest):
            raise KeyRegistryError("revocation_reason_digest_invalid")
        timestamp = canonical_timestamp(revoked_at)
        with self._lock:
            matches = [index for index, record in enumerate(self._records) if record.identity == identity]
            if len(matches) != 1:
                raise KeyRegistryError("key_identity_missing_or_ambiguous")
            index = matches[0]
            current = self._records[index]
            if current.state == "revoked":
                if current.revoked_at == timestamp and current.revocation_reason_digest == reason_digest:
                    return current
                raise KeyRegistryError("key_already_revoked")
            revoked = replace(
                current,
                state="revoked",
                revoked_at=timestamp,
                revocation_reason_digest=reason_digest,
            )
            candidate_records = list(self._records)
            candidate_records[index] = revoked
            candidate_events = [
                *self._revocation_events,
                {
                    "sequence": len(self._revocation_events) + 1,
                    "issuer": current.issuer,
                    "environment": current.environment,
                    "key_ref": current.key_ref,
                    "key_epoch": current.key_epoch,
                    "key_fingerprint": current.fingerprint,
                    "revoked_at": timestamp,
                    "reason_digest": reason_digest,
                },
            ]
            self._validate_global_invariants(candidate_records)
            self._persist_candidate(candidate_records, candidate_events)
            self._records = candidate_records
            self._revocation_events = candidate_events
            return revoked

    def resolve(
        self,
        issuer: str,
        environment: str,
        key_ref: str,
        key_epoch: int,
    ) -> Ed25519KeyRecord:
        with self._lock:
            matches = [
                record
                for record in self._records
                if record.identity == (issuer, environment, key_ref, key_epoch)
            ]
            if len(matches) != 1:
                raise SignatureVerificationError("key_identity_non_unique_or_missing")
            record = matches[0]
            if sum(candidate.fingerprint == record.fingerprint for candidate in self._records) != 1:
                raise SignatureVerificationError("global_key_fingerprint_duplicate")
            return record


@dataclass(frozen=True, slots=True)
class Ed25519EnvelopeSigner:
    private_key: Ed25519PrivateKey
    key_record: Ed25519KeyRecord

    def __post_init__(self) -> None:
        actual_public = self.private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        if not hmac.compare_digest(actual_public, self.key_record.public_key_bytes):
            raise KeyRegistryError("private_public_key_mismatch")
        if self.key_record.state != "active":
            raise KeyRegistryError("signing_key_not_active")

    @classmethod
    def from_seed(
        cls,
        seed: bytes,
        *,
        issuer: str,
        environment: str,
        key_ref: str,
        key_epoch: int,
        not_before: str,
        not_after: str,
    ) -> Ed25519EnvelopeSigner:
        if len(seed) != 32:
            raise KeyRegistryError("ed25519_seed_size")
        private_key = Ed25519PrivateKey.from_private_bytes(seed)
        public = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        return cls(
            private_key=private_key,
            key_record=Ed25519KeyRecord(
                issuer=issuer,
                environment=environment,
                key_ref=key_ref,
                key_epoch=key_epoch,
                public_key_bytes=public,
                not_before=not_before,
                not_after=not_after,
            ),
        )

    @classmethod
    def for_test_secret(
        cls,
        secret: str,
        *,
        issuer: str,
        environment: str,
        key_ref: str,
        key_epoch: int,
        not_before: str,
        not_after: str,
    ) -> Ed25519EnvelopeSigner:
        if not secret:
            raise KeyRegistryError("test_secret_required")
        return cls.from_seed(
            hashlib.sha256(secret.encode("utf-8")).digest(),
            issuer=issuer,
            environment=environment,
            key_ref=key_ref,
            key_epoch=key_epoch,
            not_before=not_before,
            not_after=not_after,
        )


@dataclass(frozen=True, slots=True)
class SignatureVerification:
    payload_digest: str
    key_fingerprint: str
    key_identity: tuple[str, str, str, int]


def sign_envelope(
    envelope: Mapping[str, object],
    signer: Ed25519EnvelopeSigner,
) -> dict[str, object]:
    result = deepcopy(dict(envelope))
    result["signature"] = {
        "algorithm": SIGNATURE_ALGORITHM,
        "encoding": SIGNATURE_ENCODING,
        "signature_value": "A" * 86,
        "key_ref": signer.key_record.key_ref,
        "key_fingerprint": signer.key_record.fingerprint,
        "key_epoch": signer.key_record.key_epoch,
        "canonicalization": SIGNATURE_CANONICALIZATION,
        "signed_payload_scope": SIGNATURE_SCOPE,
        "signed_payload_digest": "sha256:" + ("0" * 64),
    }
    payload = signed_payload_bytes(result)
    signature = signer.private_key.sign(payload)
    signature_value = encode_ed25519_signature(signature)
    signature_object = result["signature"]
    if not isinstance(signature_object, dict):
        raise SpatialCryptoError("signature_object_internal_error")
    signature_object["signed_payload_digest"] = "sha256:" + hashlib.sha256(payload).hexdigest()
    signature_object["signature_value"] = signature_value
    return result


def _require_signature_profile(signature: Mapping[str, object]) -> None:
    if set(signature) != _SIGNATURE_FIELDS:
        raise SignatureVerificationError("signature_members_invalid")
    expected = {
        "algorithm": SIGNATURE_ALGORITHM,
        "encoding": SIGNATURE_ENCODING,
        "canonicalization": SIGNATURE_CANONICALIZATION,
        "signed_payload_scope": SIGNATURE_SCOPE,
    }
    for field, value in expected.items():
        if signature.get(field) != value:
            raise SignatureVerificationError(f"signature_profile:{field}")
    if not isinstance(signature.get("key_ref"), str) or not _KEY_REF_RE.fullmatch(signature["key_ref"]):
        raise SignatureVerificationError("signature_key_ref_invalid")
    epoch = signature.get("key_epoch")
    if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 0:
        raise SignatureVerificationError("signature_key_epoch_invalid")
    fingerprint = signature.get("key_fingerprint")
    if not isinstance(fingerprint, str) or not _FINGERPRINT_RE.fullmatch(fingerprint):
        raise SignatureVerificationError("signature_key_fingerprint_invalid")
    digest = signature.get("signed_payload_digest")
    if not isinstance(digest, str) or not _DIGEST_RE.fullmatch(digest):
        raise SignatureVerificationError("signed_payload_digest_invalid")


def _bounded_duration(
    value: object,
    *,
    field: str,
    maximum: timedelta,
) -> timedelta:
    if not isinstance(value, timedelta):
        raise SignatureVerificationError(f"{field}_invalid")
    if value < timedelta(0):
        raise SignatureVerificationError(f"{field}_negative")
    if value > maximum:
        raise SignatureVerificationError(f"{field}_exceeds_maximum")
    return value


def verify_signed_envelope(
    envelope: Mapping[str, object],
    registry: Ed25519KeyRegistry,
    *,
    observed_at: datetime,
    allowed_clock_skew: timedelta = MAXIMUM_CLOCK_SKEW,
    maximum_receipt_age: timedelta = MAXIMUM_RECEIPT_AGE,
) -> SignatureVerification:
    if not isinstance(observed_at, datetime) or observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise SignatureVerificationError("observed_at_offset_required")
    checked_clock_skew = _bounded_duration(
        allowed_clock_skew,
        field="allowed_clock_skew",
        maximum=MAXIMUM_CLOCK_SKEW,
    )
    checked_maximum_age = _bounded_duration(
        maximum_receipt_age,
        field="maximum_receipt_age",
        maximum=MAXIMUM_RECEIPT_AGE,
    )
    receipt = deepcopy(dict(envelope))
    signature = receipt.get("signature")
    if not isinstance(signature, dict):
        raise SignatureVerificationError("signature_object_required")
    _require_signature_profile(signature)
    signature_value = signature.get("signature_value")
    if not isinstance(signature_value, str) or not _SIGNATURE_VALUE_RE.fullmatch(signature_value):
        raise SignatureVerificationError("signature_value_shape")
    signature_bytes = _b64url_decode_canonical(
        signature_value,
        expected_size=64,
        code="signature_value",
    )
    payload = signed_payload_bytes(receipt)
    expected_digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    supplied_digest = signature.get("signed_payload_digest")
    if not isinstance(supplied_digest, str) or not hmac.compare_digest(supplied_digest, expected_digest):
        raise SignatureVerificationError("signed_payload_digest_mismatch")

    issuer = receipt.get("issuer")
    environment = receipt.get("environment")
    if not isinstance(issuer, str) or not isinstance(environment, str):
        raise SignatureVerificationError("receipt_owner_environment_required")
    key_ref = signature.get("key_ref")
    key_epoch = signature.get("key_epoch")
    if not isinstance(key_ref, str) or not isinstance(key_epoch, int) or isinstance(key_epoch, bool):
        raise SignatureVerificationError("signature_key_identity_invalid")
    record = registry.resolve(issuer, environment, key_ref, key_epoch)
    if record.state != "active":
        raise SignatureVerificationError("key_revoked_or_inactive")
    fingerprint = signature.get("key_fingerprint")
    if not isinstance(fingerprint, str) or not hmac.compare_digest(fingerprint, record.fingerprint):
        raise SignatureVerificationError("key_fingerprint_mismatch")

    issued_at = parse_timestamp(receipt.get("issued_at"))
    expires_at = parse_timestamp(receipt.get("expires_at"))
    key_not_before = parse_timestamp(record.not_before)
    key_not_after = parse_timestamp(record.not_after)
    if issued_at >= expires_at:
        raise SignatureVerificationError("receipt_chronology_invalid")
    if not key_not_before <= issued_at < expires_at <= key_not_after:
        raise SignatureVerificationError("key_or_receipt_chronology_invalid")
    if expires_at - issued_at > checked_maximum_age:
        raise SignatureVerificationError("receipt_freshness_window_exceeded")
    observed = observed_at.astimezone(UTC)
    if observed + checked_clock_skew < issued_at:
        raise SignatureVerificationError("receipt_not_yet_current")
    if observed - checked_clock_skew > expires_at:
        raise SignatureVerificationError("receipt_expired")

    try:
        Ed25519PublicKey.from_public_bytes(record.public_key_bytes).verify(signature_bytes, payload)
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise SignatureVerificationError("ed25519_signature_invalid") from exc
    return SignatureVerification(
        payload_digest=expected_digest,
        key_fingerprint=record.fingerprint,
        key_identity=record.identity,
    )


def signature_verification_errors(
    envelope: Mapping[str, object],
    registry: Ed25519KeyRegistry,
    *,
    observed_at: datetime,
    allowed_clock_skew: timedelta = MAXIMUM_CLOCK_SKEW,
    maximum_receipt_age: timedelta = MAXIMUM_RECEIPT_AGE,
) -> list[str]:
    try:
        verify_signed_envelope(
            envelope,
            registry,
            observed_at=observed_at,
            allowed_clock_skew=allowed_clock_skew,
            maximum_receipt_age=maximum_receipt_age,
        )
    except SignatureVerificationError as exc:
        return [exc.code]
    return []


__all__ = [
    "Ed25519EnvelopeSigner",
    "Ed25519KeyRecord",
    "Ed25519KeyRegistry",
    "KeyRegistryError",
    "MAXIMUM_CLOCK_SKEW",
    "MAXIMUM_RECEIPT_AGE",
    "SIGNATURE_ALGORITHM",
    "SIGNATURE_CANONICALIZATION",
    "SIGNATURE_ENCODING",
    "SIGNATURE_SCOPE",
    "SignatureVerification",
    "SignatureVerificationError",
    "SpatialCryptoError",
    "canonical_timestamp",
    "decode_ed25519_signature",
    "encode_ed25519_signature",
    "parse_timestamp",
    "public_key_fingerprint",
    "sign_envelope",
    "signature_verification_errors",
    "verify_signed_envelope",
]
