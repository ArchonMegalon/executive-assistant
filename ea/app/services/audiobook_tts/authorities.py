"""Strict private authorities required before VocalLab may spend points."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Mapping

from app.services.audiobook_tts.contracts import SpeechSynthesisRequest
from app.services.audiobook_tts.providers.vocallab_schema import (
    VOCALLAB_MODEL_KEYS,
    VOCALLAB_VERIFICATION_SYNTHETIC_POINTS,
    VOCALLAB_VERIFICATION_SYNTHETIC_TEXT_SHA256,
)


VERIFICATION_CONTRACT = "ea.audiobook_vocallab_provider_verification.v1"
VERIFICATION_PROVENANCE_CONTRACT = (
    "ea.audiobook_vocallab_verification_provenance.v1"
)
EXTERNAL_AUTHORIZATION_CONTRACT = (
    "ea.audiobook_external_processing_authorization.v2"
)
CAST_SNAPSHOT_CONTRACT = "ea.audiobook_speaker_cast_snapshot.v2"
AUDITION_AUTHORIZATION_CONTRACT = (
    "ea.audiobook_voice_audition_authorization.v1"
)
VOCALLAB_PROVIDER_CONTRACT_VERSION = "ea.audiobook_tts.vocallab.v1"
_SHA_LENGTH = 64
_MAX_PRIVATE_JSON_BYTES = 2 * 1024 * 1024
_FACTORY_TOKEN = object()
_RIGHTS_BASES = frozenset(
    {
        "owner_authored",
        "licensed_for_external_tts",
        "explicit_author_permission",
        "public_domain_verified",
    }
)
_SYNTHETIC_PROBE_TEXT_SHA256 = VOCALLAB_VERIFICATION_SYNTHETIC_TEXT_SHA256
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._:-]{1,256}$")


class AuthorityError(RuntimeError):
    """Code-only authority error safe for public projection."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _exact_keys(value: Mapping[str, Any], expected: set[str], code: str) -> None:
    if set(value) != expected:
        raise AuthorityError(code)


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError("nonfinite_json_number")


def _sha(value: Any, code: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != _SHA_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise AuthorityError(code)
    return value


def _string(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuthorityError(code)
    return value.strip()


def _identifier(value: Any, code: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise AuthorityError(code)
    return value


def _timestamp(value: Any, code: str) -> datetime:
    text = _string(value, code)
    if not text.endswith("Z"):
        raise AuthorityError(code)
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError:
        raise AuthorityError(code) from None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise AuthorityError(code)
    return parsed.astimezone(UTC)


def _validate_window(
    *,
    generated_at: datetime,
    expires_at: datetime,
    now: datetime,
    maximum_lifetime: timedelta,
    exact_lifetime: timedelta | None = None,
) -> None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise AuthorityError("authority_time_window_invalid")
    current = now.astimezone(UTC)
    lifetime = expires_at - generated_at
    if (
        generated_at > current + timedelta(minutes=5)
        or expires_at <= current
        or lifetime <= timedelta(0)
        or lifetime > maximum_lifetime
        or (exact_lifetime is not None and lifetime != exact_lifetime)
    ):
        raise AuthorityError("authority_time_window_invalid")


def _check_no_symlink_components(path: Path) -> None:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:-1]:
        current /= part
        try:
            metadata = current.lstat()
        except OSError:
            raise AuthorityError("private_authority_path_unavailable") from None
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise AuthorityError("private_authority_path_unsafe")


def read_private_json(path: str | Path) -> tuple[dict[str, Any], bytes, str]:
    """Read one owner-only JSON file with descriptor/identity binding."""

    target = Path(path).absolute()
    _check_no_symlink_components(target)
    parent = target.parent
    try:
        parent_before = parent.lstat()
    except OSError:
        raise AuthorityError("private_authority_path_unavailable") from None
    if (
        stat.S_ISLNK(parent_before.st_mode)
        or not stat.S_ISDIR(parent_before.st_mode)
        or parent_before.st_uid != os.geteuid()
        or stat.S_IMODE(parent_before.st_mode) & 0o077
    ):
        raise AuthorityError("private_authority_parent_unsafe")
    try:
        before = target.lstat()
    except OSError:
        raise AuthorityError("private_authority_unavailable") from None
    if (
        stat.S_ISLNK(before.st_mode)
        or not stat.S_ISREG(before.st_mode)
        or before.st_uid != os.geteuid()
        or stat.S_IMODE(before.st_mode) != 0o600
        or before.st_nlink != 1
        or before.st_size <= 0
        or before.st_size > _MAX_PRIVATE_JSON_BYTES
    ):
        raise AuthorityError("private_authority_file_unsafe")
    parent_fd = -1
    descriptor = -1
    try:
        parent_fd = os.open(
            parent,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        parent_open = os.fstat(parent_fd)
        if (parent_open.st_dev, parent_open.st_ino) != (
            parent_before.st_dev,
            parent_before.st_ino,
        ):
            raise AuthorityError("private_authority_parent_changed")
        descriptor = os.open(
            target.name,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent_fd,
        )
        opened = os.fstat(descriptor)
        if (
            (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
            or not stat.S_ISREG(opened.st_mode)
            or opened.st_uid != os.geteuid()
            or stat.S_IMODE(opened.st_mode) != 0o600
            or opened.st_nlink != 1
            or opened.st_size != before.st_size
        ):
            raise AuthorityError("private_authority_file_changed")
        chunks: list[bytes] = []
        received = 0
        while True:
            chunk = os.read(descriptor, min(65536, _MAX_PRIVATE_JSON_BYTES + 1 - received))
            if not chunk:
                break
            received += len(chunk)
            if received > _MAX_PRIVATE_JSON_BYTES:
                raise AuthorityError("private_authority_file_too_large")
            chunks.append(chunk)
        raw = b"".join(chunks)
        after = target.lstat()
        parent_after = parent.lstat()
        identity = (
            "st_dev",
            "st_ino",
            "st_size",
            "st_mode",
            "st_uid",
            "st_nlink",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if any(getattr(after, name) != getattr(before, name) for name in identity):
            raise AuthorityError("private_authority_file_changed")
        if (
            parent_after.st_dev,
            parent_after.st_ino,
            parent_after.st_mode,
            parent_after.st_uid,
            parent_after.st_nlink,
        ) != (
            parent_before.st_dev,
            parent_before.st_ino,
            parent_before.st_mode,
            parent_before.st_uid,
            parent_before.st_nlink,
        ):
            raise AuthorityError("private_authority_parent_changed")
    except AuthorityError:
        raise
    except OSError:
        raise AuthorityError("private_authority_read_failed") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if parent_fd >= 0:
            os.close(parent_fd)
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_strict_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise AuthorityError("private_authority_json_invalid") from None
    if not isinstance(payload, dict):
        raise AuthorityError("private_authority_json_invalid")
    return payload, raw, hashlib.sha256(raw).hexdigest()


class AuthenticatedVocalLabVerification:
    """Opaque proof object constructible only by the HMAC-verifying loader."""

    __slots__ = (
        "catalog_sha256",
        "discovered_voice_hashes",
        "expires_at",
        "models",
        "receipt_sha256",
    )

    def __init__(
        self,
        *,
        catalog_sha256: str,
        discovered_voice_hashes: tuple[str, ...],
        expires_at: datetime,
        models: tuple[str, ...],
        receipt_sha256: str,
        _token: object,
    ) -> None:
        if _token is not _FACTORY_TOKEN:
            raise TypeError("authenticated_verification_loader_required")
        self.catalog_sha256 = catalog_sha256
        self.discovered_voice_hashes = discovered_voice_hashes
        self.expires_at = expires_at
        self.models = models
        self.receipt_sha256 = receipt_sha256


def _authenticate_verification_payload(
    payload: Mapping[str, Any],
    *,
    hmac_key: bytes,
) -> None:
    authentication = payload.get("authentication")
    if not isinstance(authentication, dict):
        raise AuthorityError("verification_authentication_invalid")
    _exact_keys(
        authentication,
        {
            "contract_name",
            "version",
            "algorithm",
            "signed_contract_name",
            "key_id_sha256",
            "payload_sha256",
            "hmac_sha256",
        },
        "verification_authentication_invalid",
    )
    unsigned = dict(payload)
    del unsigned["authentication"]
    try:
        unsigned_bytes = (
            json.dumps(
                unsigned,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise AuthorityError("verification_authentication_invalid") from None
    message = (
        b"ea-vocallab-verification-provenance-v1\x00"
        + VERIFICATION_CONTRACT.encode("ascii")
        + b"\x00"
        + unsigned_bytes
    )
    expected_auth = {
        "contract_name": VERIFICATION_PROVENANCE_CONTRACT,
        "version": 1,
        "algorithm": "HMAC-SHA256",
        "signed_contract_name": VERIFICATION_CONTRACT,
        "key_id_sha256": hashlib.sha256(hmac_key).hexdigest(),
        "payload_sha256": hashlib.sha256(unsigned_bytes).hexdigest(),
        "hmac_sha256": hmac.new(hmac_key, message, hashlib.sha256).hexdigest(),
    }
    for key, expected in expected_auth.items():
        actual = authentication.get(key)
        if type(actual) is not type(expected):
            raise AuthorityError("verification_authentication_invalid")
        if isinstance(expected, str):
            if not hmac.compare_digest(actual, expected):
                raise AuthorityError("verification_authentication_invalid")
        elif actual != expected:
            raise AuthorityError("verification_authentication_invalid")


def load_authenticated_vocallab_verification(
    path: str | Path,
    *,
    hmac_key: bytes,
    expected_catalog_sha256: str,
    expected_credential_binding_sha256: str,
    now: datetime,
) -> AuthenticatedVocalLabVerification:
    if not isinstance(hmac_key, bytes) or not 32 <= len(hmac_key) <= 256:
        raise AuthorityError("verification_hmac_key_invalid")
    catalog_sha256 = _sha(expected_catalog_sha256, "verification_catalog_invalid")
    credential_binding_sha256 = _sha(
        expected_credential_binding_sha256,
        "verification_credential_binding_invalid",
    )
    payload, raw, receipt_sha256 = read_private_json(path)
    _authenticate_verification_payload(payload, hmac_key=hmac_key)
    expected_root = {
        "contract_name",
        "version",
        "status",
        "generated_at",
        "expires_at",
        "provider",
        "provider_contract_version",
        "api_contract_version",
        "probe_sha256",
        "catalog_sha256",
        "credential_binding_sha256",
        "credential_rotation_required",
        "credential_production_eligible",
        "discovered_voice_hashes",
        "ping",
        "account",
        "models",
        "voices",
        "smoke",
        "request_safety",
        "retention",
        "blockers",
        "secrets_exposed",
        "manuscript_text_exposed",
        "authentication",
    }
    _exact_keys(payload, expected_root, "verification_schema_invalid")
    if (
        payload.get("contract_name") != VERIFICATION_CONTRACT
        or payload.get("version") != 2
        or isinstance(payload.get("version"), bool)
        or payload.get("status") != "pass"
        or payload.get("provider") != "vocallab"
        or payload.get("provider_contract_version")
        != VOCALLAB_PROVIDER_CONTRACT_VERSION
        or not isinstance(payload.get("api_contract_version"), str)
        or not payload.get("api_contract_version")
        or payload.get("secrets_exposed") is not False
        or payload.get("manuscript_text_exposed") is not False
        or payload.get("credential_rotation_required") is not False
        or payload.get("credential_production_eligible") is not True
        or payload.get("blockers") != []
    ):
        raise AuthorityError("verification_schema_invalid")
    generated = _timestamp(payload["generated_at"], "verification_time_invalid")
    expires = _timestamp(payload["expires_at"], "verification_time_invalid")
    _validate_window(
        generated_at=generated,
        expires_at=expires,
        now=now,
        maximum_lifetime=timedelta(hours=24),
        exact_lifetime=timedelta(hours=24),
    )
    _sha(payload["probe_sha256"], "verification_probe_invalid")
    if not hmac.compare_digest(
        _sha(payload["catalog_sha256"], "verification_catalog_invalid"),
        catalog_sha256,
    ):
        raise AuthorityError("verification_catalog_mismatch")
    if not hmac.compare_digest(
        _sha(
            payload["credential_binding_sha256"],
            "verification_credential_binding_invalid",
        ),
        credential_binding_sha256,
    ):
        raise AuthorityError("verification_credential_binding_mismatch")
    hashes = payload["discovered_voice_hashes"]
    if not isinstance(hashes, list) or not hashes:
        raise AuthorityError("verification_voices_invalid")
    discovered = tuple(_sha(value, "verification_voices_invalid") for value in hashes)
    if list(discovered) != sorted(set(discovered)):
        raise AuthorityError("verification_voices_invalid")

    ping = payload["ping"]
    account = payload["account"]
    models = payload["models"]
    voices = payload["voices"]
    smoke = payload["smoke"]
    safety = payload["request_safety"]
    retention = payload["retention"]
    for value in (ping, account, models, voices, smoke, safety, retention):
        if not isinstance(value, dict):
            raise AuthorityError("verification_schema_invalid")
    _exact_keys(ping, {"status"}, "verification_ping_invalid")
    _exact_keys(
        account,
        {
            "status",
            "api_access",
            "balance_sufficient_for_smoke",
            "exact_balance_exposed",
        },
        "verification_account_invalid",
    )
    _exact_keys(models, {"status", "keys"}, "verification_models_invalid")
    _exact_keys(
        voices,
        {"status", "voice_count", "raw_voice_ids_exposed"},
        "verification_voices_invalid",
    )
    _exact_keys(
        smoke,
        {
            "status",
            "source_text_sha256",
            "audio_sha256",
            "content_type",
            "sample_rate",
            "points_used",
            "generation_id_sha256",
        },
        "verification_smoke_invalid",
    )
    _exact_keys(
        safety,
        {
            "status",
            "max_chars_per_request",
            "requests_per_minute",
            "max_in_flight",
            "minimum_remaining_points",
            "blind_post_retry_allowed",
            "url_fallback_enabled",
        },
        "verification_safety_invalid",
    )
    _exact_keys(
        retention,
        {
            "status",
            "generation_history_days",
            "clone_retention",
            "subprocessors",
        },
        "verification_retention_invalid",
    )
    model_keys = models.get("keys")
    if (
        ping != {"status": "pass"}
        or account
        != {
            "status": "pass",
            "api_access": True,
            "balance_sufficient_for_smoke": True,
            "exact_balance_exposed": False,
        }
        or model_keys != list(VOCALLAB_MODEL_KEYS)
        or models.get("status") != "pass"
        or voices.get("status") != "pass"
        or not isinstance(voices.get("voice_count"), int)
        or isinstance(voices.get("voice_count"), bool)
        or voices.get("voice_count") != len(discovered)
        or voices.get("raw_voice_ids_exposed") is not False
        or smoke.get("status") != "pass"
        or smoke.get("content_type") != "audio/wav"
        or smoke.get("sample_rate") != 44100
        or isinstance(smoke.get("sample_rate"), bool)
        or not isinstance(smoke.get("points_used"), int)
        or isinstance(smoke.get("points_used"), bool)
        or smoke.get("points_used")
        != VOCALLAB_VERIFICATION_SYNTHETIC_POINTS
        or safety
        != {
            "status": "pass",
            "max_chars_per_request": 1800,
            "requests_per_minute": 30,
            "max_in_flight": 1,
            "minimum_remaining_points": 3000,
            "blind_post_retry_allowed": False,
            "url_fallback_enabled": False,
        }
        or retention
        != {
            "status": "acknowledged",
            "generation_history_days": 90,
            "clone_retention": "active_account",
            "subprocessors": ["inworld_ai"],
        }
    ):
        raise AuthorityError("verification_schema_invalid")
    for key in (
        "source_text_sha256",
        "audio_sha256",
        "generation_id_sha256",
    ):
        _sha(smoke.get(key), "verification_smoke_invalid")
    if smoke.get("source_text_sha256") != _SYNTHETIC_PROBE_TEXT_SHA256:
        raise AuthorityError("verification_smoke_invalid")

    return AuthenticatedVocalLabVerification(
        catalog_sha256=catalog_sha256,
        discovered_voice_hashes=discovered,
        expires_at=expires,
        models=tuple(model_keys),
        receipt_sha256=receipt_sha256,
        _token=_FACTORY_TOKEN,
    )


@dataclass(frozen=True, slots=True)
class ExternalProcessingAuthorization:
    authorization_id: str
    artifact_sha256: str
    rights_basis: str


def load_external_processing_authorization(
    path: str | Path,
    *,
    request: SpeechSynthesisRequest,
    now: datetime,
) -> ExternalProcessingAuthorization:
    payload, _raw, artifact_sha256 = read_private_json(path)
    _exact_keys(
        payload,
        {
            "contract_name",
            "version",
            "authorization_id",
            "job_id_sha256",
            "source_sha256",
            "authorized_segment_sha256s",
            "rights_basis",
            "allowed_providers",
            "allowed_subprocessors",
            "allowed_content_scope",
            "generated_at",
            "expires_at",
            "approved_by_sha256",
            "revoked",
        },
        "external_authorization_schema_invalid",
    )
    generated = _timestamp(payload.get("generated_at"), "external_authorization_time_invalid")
    expires = _timestamp(payload.get("expires_at"), "external_authorization_time_invalid")
    _validate_window(
        generated_at=generated,
        expires_at=expires,
        now=now,
        maximum_lifetime=timedelta(days=31),
    )
    segments = payload.get("authorized_segment_sha256s")
    if not isinstance(segments, list) or not segments:
        raise AuthorityError("external_authorization_scope_invalid")
    segment_hashes = tuple(
        _sha(value, "external_authorization_scope_invalid") for value in segments
    )
    expected_segment = hashlib.sha256(request.segment_id.encode("utf-8")).hexdigest()
    rights_basis = payload.get("rights_basis")
    authorization_id = _identifier(
        payload.get("authorization_id"),
        "external_authorization_schema_invalid",
    )
    if (
        payload.get("contract_name") != EXTERNAL_AUTHORIZATION_CONTRACT
        or payload.get("version") != 2
        or isinstance(payload.get("version"), bool)
        or authorization_id != request.external_processing_authorization_id
        or artifact_sha256
        != request.external_processing_authorization_sha256
        or payload.get("job_id_sha256")
        != hashlib.sha256(request.job_id.encode("utf-8")).hexdigest()
        or payload.get("source_sha256") != request.source_text_sha256
        or list(segment_hashes) != sorted(set(segment_hashes))
        or expected_segment not in segment_hashes
        or rights_basis not in _RIGHTS_BASES
        or payload.get("allowed_providers") != ["vocallab"]
        or payload.get("allowed_subprocessors") != ["inworld_ai"]
        or payload.get("allowed_content_scope") != "selected_segments"
        or payload.get("revoked") is not False
    ):
        raise AuthorityError("external_authorization_binding_invalid")
    _sha(payload.get("approved_by_sha256"), "external_authorization_schema_invalid")
    return ExternalProcessingAuthorization(
        authorization_id=authorization_id,
        artifact_sha256=artifact_sha256,
        rights_basis=str(rights_basis),
    )


def verify_cast_snapshot(
    path: str | Path,
    *,
    request: SpeechSynthesisRequest,
    now: datetime,
) -> str:
    payload, _raw, artifact_sha256 = read_private_json(path)
    _exact_keys(
        payload,
        {
            "contract_name",
            "version",
            "snapshot_id",
            "job_id_sha256",
            "generated_at",
            "expires_at",
            "entries",
        },
        "cast_snapshot_schema_invalid",
    )
    generated = _timestamp(payload.get("generated_at"), "cast_snapshot_time_invalid")
    expires = _timestamp(payload.get("expires_at"), "cast_snapshot_time_invalid")
    _validate_window(
        generated_at=generated,
        expires_at=expires,
        now=now,
        maximum_lifetime=timedelta(days=366),
    )
    rows = payload.get("entries")
    if not isinstance(rows, list) or not rows:
        raise AuthorityError("cast_snapshot_schema_invalid")
    expected_speaker = hashlib.sha256(request.speaker_id.encode("utf-8")).hexdigest()
    matches: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise AuthorityError("cast_snapshot_schema_invalid")
        _exact_keys(
            row,
            {
                "speaker_id_sha256",
                "provider",
                "voice_id_sha256",
                "model",
                "rights_receipt_sha256",
                "consent_receipt_sha256",
            },
            "cast_snapshot_schema_invalid",
        )
        speaker_hash = _sha(row.get("speaker_id_sha256"), "cast_snapshot_schema_invalid")
        if speaker_hash in seen:
            raise AuthorityError("cast_snapshot_duplicate_speaker")
        seen.add(speaker_hash)
        _sha(row.get("voice_id_sha256"), "cast_snapshot_schema_invalid")
        _sha(row.get("rights_receipt_sha256"), "cast_snapshot_schema_invalid")
        consent_hash = row.get("consent_receipt_sha256")
        if consent_hash != "":
            _sha(consent_hash, "cast_snapshot_schema_invalid")
        if row.get("provider") not in {"unmixr", "vocallab", "piper_local"}:
            raise AuthorityError("cast_snapshot_schema_invalid")
        _identifier(row.get("model"), "cast_snapshot_schema_invalid")
        if speaker_hash == expected_speaker:
            matches.append(row)
    if (
        payload.get("contract_name") != CAST_SNAPSHOT_CONTRACT
        or payload.get("version") != 2
        or isinstance(payload.get("version"), bool)
        or not _identifier(
            payload.get("snapshot_id"), "cast_snapshot_schema_invalid"
        )
        or payload.get("job_id_sha256")
        != hashlib.sha256(request.job_id.encode("utf-8")).hexdigest()
        or artifact_sha256 != request.cast_snapshot_sha256
        or len(matches) != 1
    ):
        raise AuthorityError("cast_snapshot_binding_invalid")
    row = matches[0]
    rights_hash = hashlib.sha256(
        request.voice.rights_receipt_id.encode("utf-8")
    ).hexdigest()
    consent_hash = (
        hashlib.sha256(request.voice.consent_receipt_id.encode("utf-8")).hexdigest()
        if request.voice.consent_receipt_id
        else ""
    )
    if (
        row.get("provider") != "vocallab"
        or row.get("voice_id_sha256") != request.voice.voice_id_sha256
        or row.get("model") != request.model
        or row.get("rights_receipt_sha256") != rights_hash
        or row.get("consent_receipt_sha256") != consent_hash
    ):
        raise AuthorityError("cast_snapshot_voice_drift")
    return artifact_sha256


def verify_audition_authorization(
    path: str | Path,
    *,
    request: SpeechSynthesisRequest,
    now: datetime,
) -> str:
    payload, _raw, artifact_sha256 = read_private_json(path)
    _exact_keys(
        payload,
        {
            "contract_name",
            "version",
            "authorization_id",
            "job_id_sha256",
            "speaker_id_sha256",
            "provider",
            "voice_id_sha256",
            "model",
            "generated_at",
            "expires_at",
            "revoked",
        },
        "audition_authorization_schema_invalid",
    )
    generated = _timestamp(payload.get("generated_at"), "audition_authorization_time_invalid")
    expires = _timestamp(payload.get("expires_at"), "audition_authorization_time_invalid")
    _validate_window(
        generated_at=generated,
        expires_at=expires,
        now=now,
        maximum_lifetime=timedelta(days=7),
    )
    authorization_id = _identifier(
        payload.get("authorization_id"),
        "audition_authorization_schema_invalid",
    )
    _identifier(payload.get("model"), "audition_authorization_schema_invalid")
    if (
        payload.get("contract_name") != AUDITION_AUTHORIZATION_CONTRACT
        or payload.get("version") != 1
        or isinstance(payload.get("version"), bool)
        or authorization_id != request.audition_authorization_id
        or artifact_sha256 != request.audition_authorization_sha256
        or payload.get("job_id_sha256")
        != hashlib.sha256(request.job_id.encode("utf-8")).hexdigest()
        or payload.get("speaker_id_sha256")
        != hashlib.sha256(request.speaker_id.encode("utf-8")).hexdigest()
        or payload.get("provider") != "vocallab"
        or payload.get("voice_id_sha256") != request.voice.voice_id_sha256
        or payload.get("model") != request.model
        or payload.get("revoked") is not False
    ):
        raise AuthorityError("audition_authorization_binding_invalid")
    return artifact_sha256


@dataclass(frozen=True, slots=True)
class VocalLabAuthorityStore:
    verification_path: Path
    verification_hmac_key: bytes = field(repr=False)
    external_authorization_path: Path
    cast_snapshot_path: Path | None = None
    audition_authorization_path: Path | None = None

    def authorize(
        self,
        request: SpeechSynthesisRequest,
        *,
        catalog_sha256: str,
        credential_binding_sha256: str,
        now: datetime,
    ) -> AuthenticatedVocalLabVerification:
        verification = load_authenticated_vocallab_verification(
            self.verification_path,
            hmac_key=self.verification_hmac_key,
            expected_catalog_sha256=catalog_sha256,
            expected_credential_binding_sha256=credential_binding_sha256,
            now=now,
        )
        load_external_processing_authorization(
            self.external_authorization_path,
            request=request,
            now=now,
        )
        if request.workload == "voice_audition":
            if request.publication_intent or self.audition_authorization_path is None:
                raise AuthorityError("audition_authorization_missing")
            verify_audition_authorization(
                self.audition_authorization_path,
                request=request,
                now=now,
            )
        else:
            if self.cast_snapshot_path is None:
                raise AuthorityError("cast_snapshot_missing")
            verify_cast_snapshot(
                self.cast_snapshot_path,
                request=request,
                now=now,
            )
        return verification
