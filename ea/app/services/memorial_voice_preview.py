from __future__ import annotations

"""Short-lived operator preview sessions for Manfred voice checks.

The signed cookie is a replayable bearer credential until it expires or every
write token to which it is bound is rotated out.  It is deliberately not a
release receipt, deploy permit, public-readiness decision, or human identity
attestation.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Sequence
from typing import Any


VOICE_PREVIEW_SESSION_CONTRACT = "ea.manfred_voice_preview_session.v1"
VOICE_PREVIEW_AUDIENCE = "ea.manfred_voice_preview"
VOICE_PREVIEW_MAX_TTL_SECONDS = 15 * 60
VOICE_PREVIEW_MIN_TTL_SECONDS = 60
VOICE_PREVIEW_CLOCK_SKEW_SECONDS = 30
VOICE_PREVIEW_MAX_TOKEN_CHARS = 4096

_SESSION_KEYS = {
    "audience",
    "contract_name",
    "deployment_id",
    "expires_at",
    "issued_at",
    "memorial_slug",
    "nonce",
    "operator_binding",
    "source_revision",
}


class VoicePreviewSessionError(ValueError):
    """Raised when trusted code attempts to issue an invalid preview session."""


def _b64url_encode(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _b64url_decode(payload: str) -> bytes:
    if not isinstance(payload, str) or not payload or any(
        character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        for character in payload
    ):
        raise ValueError("preview_session_encoding_invalid")
    padding = "=" * (-len(payload) % 4)
    return base64.b64decode(payload + padding, altchars=b"-_", validate=True)


def _strict_json_object(raw: bytes) -> dict[str, Any]:
    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("preview_session_duplicate_field")
            result[key] = value
        return result

    parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs_hook)
    if not isinstance(parsed, dict):
        raise ValueError("preview_session_shape_invalid")
    return parsed


def _valid_source_revision(value: object) -> bool:
    return isinstance(value, str) and len(value) == 40 and all(
        character in "0123456789abcdef" for character in value
    )


def _valid_deployment_id(value: object) -> bool:
    if not isinstance(value, str) or value != value.strip():
        return False
    raw = value
    lowered = raw.lower()
    return (
        8 <= len(raw) <= 160
        and "fallback" not in lowered
        and "local" not in lowered
        and all(
            character in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-"
            for character in raw
        )
    )


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _valid_nonce(value: object) -> bool:
    return isinstance(value, str) and 24 <= len(value) <= 160 and all(
        character in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        for character in value
    )


def _valid_write_token(value: object) -> bool:
    return (
        isinstance(value, str)
        and value == value.strip()
        and 24 <= len(value) <= 4096
        and "\x00" not in value
    )


def _signing_key(value: object) -> bytes:
    if not isinstance(value, str) or value != value.strip() or "\x00" in value:
        raise VoicePreviewSessionError("preview_session_signing_secret_invalid")
    raw = value.encode("utf-8")
    if len(raw) < 32:
        raise VoicePreviewSessionError("preview_session_signing_secret_invalid")
    return raw


def _purpose_key(signing_secret: str, *, purpose: bytes) -> bytes:
    return hmac.new(
        _signing_key(signing_secret),
        b"ea.manfred_voice_preview.v1\0" + purpose,
        hashlib.sha256,
    ).digest()


def preview_operator_binding(*, write_token: str, signing_secret: str) -> str:
    if not _valid_write_token(write_token):
        raise VoicePreviewSessionError("preview_operator_token_invalid")
    return hmac.new(
        _purpose_key(signing_secret, purpose=b"operator-binding"),
        b"current-write-token\0" + write_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def issue_memorial_voice_preview_session(
    *,
    source_revision: str,
    deployment_id: str,
    write_token: str,
    signing_secret: str,
    memorial_slug: str = "manfred",
    ttl_seconds: int = 10 * 60,
    now: float | None = None,
    nonce: str | None = None,
) -> str:
    slug = memorial_slug.strip().lower() if isinstance(memorial_slug, str) else ""
    if slug != "manfred":
        raise VoicePreviewSessionError("preview_session_slug_invalid")
    if not _valid_source_revision(source_revision):
        raise VoicePreviewSessionError("preview_session_source_revision_invalid")
    if not _valid_deployment_id(deployment_id):
        raise VoicePreviewSessionError("preview_session_deployment_id_invalid")
    operator_binding = preview_operator_binding(
        write_token=write_token,
        signing_secret=signing_secret,
    )
    try:
        ttl = int(ttl_seconds)
    except (TypeError, ValueError) as exc:
        raise VoicePreviewSessionError("preview_session_ttl_invalid") from exc
    if not VOICE_PREVIEW_MIN_TTL_SECONDS <= ttl <= VOICE_PREVIEW_MAX_TTL_SECONDS:
        raise VoicePreviewSessionError("preview_session_ttl_invalid")
    issued_at = int(time.time() if now is None else float(now))
    nonce_value = secrets.token_urlsafe(24) if nonce is None else nonce
    if not _valid_nonce(nonce_value):
        raise VoicePreviewSessionError("preview_session_nonce_invalid")
    payload = {
        "audience": VOICE_PREVIEW_AUDIENCE,
        "contract_name": VOICE_PREVIEW_SESSION_CONTRACT,
        "deployment_id": deployment_id,
        "expires_at": issued_at + ttl,
        "issued_at": issued_at,
        "memorial_slug": slug,
        "nonce": nonce_value,
        "operator_binding": operator_binding,
        "source_revision": source_revision,
    }
    encoded = _b64url_encode(
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    signed = f"v1.{encoded}".encode("ascii")
    signature = hmac.new(
        _purpose_key(signing_secret, purpose=b"session-signature"),
        signed,
        hashlib.sha256,
    ).digest()
    return f"v1.{encoded}.{_b64url_encode(signature)}"


def _blocked(reason: str) -> dict[str, object]:
    return {
        "preview_session_valid": False,
        "public_release_allowed": False,
        "reason": reason,
        "status": "blocked",
    }


def verify_memorial_voice_preview_session(
    value: str,
    *,
    source_revision: str,
    deployment_id: str,
    current_write_tokens: Sequence[str],
    signing_secret: str,
    memorial_slug: str = "manfred",
    now: float | None = None,
) -> dict[str, object]:
    if not isinstance(value, str):
        return _blocked("preview_session_missing_or_oversized")
    if value != value.strip():
        return _blocked("preview_session_format_invalid")
    token = value
    if not token or len(token) > VOICE_PREVIEW_MAX_TOKEN_CHARS:
        return _blocked("preview_session_missing_or_oversized")
    if not _valid_source_revision(source_revision) or not _valid_deployment_id(deployment_id):
        return _blocked("preview_session_deployment_binding_invalid")
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != "v1":
        return _blocked("preview_session_format_invalid")
    if len(parts[2]) != 43:
        return _blocked("preview_session_signature_invalid")
    try:
        # Decode both segments before any ASCII encoding.  This makes arbitrary
        # unauthenticated Unicode input fail closed rather than escaping as a
        # UnicodeEncodeError.
        raw_payload = _b64url_decode(parts[1])
        supplied_signature = _b64url_decode(parts[2])
    except (ValueError, VoicePreviewSessionError):
        return _blocked("preview_session_signature_invalid")
    if len(supplied_signature) != hashlib.sha256().digest_size or _b64url_encode(
        supplied_signature
    ) != parts[2]:
        return _blocked("preview_session_signature_invalid")
    try:
        expected_signature = hmac.new(
            _purpose_key(signing_secret, purpose=b"session-signature"),
            f"v1.{parts[1]}".encode("ascii"),
            hashlib.sha256,
        ).digest()
    except (UnicodeEncodeError, VoicePreviewSessionError):
        return _blocked("preview_session_signature_invalid")
    if len(supplied_signature) != len(expected_signature) or not hmac.compare_digest(
        supplied_signature,
        expected_signature,
    ):
        return _blocked("preview_session_signature_invalid")
    try:
        payload = _strict_json_object(raw_payload)
    except (UnicodeError, ValueError, json.JSONDecodeError):
        return _blocked("preview_session_payload_invalid")
    canonical_payload = _b64url_encode(
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    if canonical_payload != parts[1] or set(payload) != _SESSION_KEYS:
        return _blocked("preview_session_schema_invalid")
    if (
        payload.get("contract_name") != VOICE_PREVIEW_SESSION_CONTRACT
        or payload.get("audience") != VOICE_PREVIEW_AUDIENCE
        or not isinstance(memorial_slug, str)
        or payload.get("memorial_slug") != memorial_slug.strip().lower()
    ):
        return _blocked("preview_session_scope_mismatch")
    if (
        payload.get("source_revision") != source_revision
        or payload.get("deployment_id") != deployment_id
    ):
        return _blocked("preview_session_deployment_binding_mismatch")
    if not _valid_source_revision(payload.get("source_revision")) or not _valid_deployment_id(
        payload.get("deployment_id")
    ):
        return _blocked("preview_session_deployment_binding_invalid")
    supplied_binding = payload.get("operator_binding")
    if not _valid_sha256(supplied_binding):
        return _blocked("preview_session_operator_binding_invalid")
    if not isinstance(current_write_tokens, Sequence) or isinstance(
        current_write_tokens, (str, bytes)
    ):
        return _blocked("preview_session_operator_binding_invalid")
    valid_current_tokens = [token for token in current_write_tokens if _valid_write_token(token)]
    if not valid_current_tokens:
        return _blocked("preview_session_operator_binding_invalid")
    binding_matches = False
    for current_token in valid_current_tokens:
        current_binding = preview_operator_binding(
            write_token=current_token,
            signing_secret=signing_secret,
        )
        binding_matches = hmac.compare_digest(supplied_binding, current_binding) or binding_matches
    if not binding_matches:
        return _blocked("preview_session_operator_binding_mismatch")
    if not _valid_nonce(payload.get("nonce")):
        return _blocked("preview_session_nonce_invalid")
    issued_at = payload.get("issued_at")
    expires_at = payload.get("expires_at")
    if type(issued_at) is not int or type(expires_at) is not int:
        return _blocked("preview_session_time_invalid")
    checked_at = int(time.time() if now is None else float(now))
    if (
        issued_at > checked_at + VOICE_PREVIEW_CLOCK_SKEW_SECONDS
        or expires_at <= issued_at
        or expires_at - issued_at < VOICE_PREVIEW_MIN_TTL_SECONDS
        or expires_at - issued_at > VOICE_PREVIEW_MAX_TTL_SECONDS
    ):
        return _blocked("preview_session_time_invalid")
    if checked_at >= expires_at:
        return _blocked("preview_session_expired")
    return {
        "preview_session_valid": True,
        "public_release_allowed": False,
        "deployment_id": payload["deployment_id"],
        "expires_at": expires_at,
        "memorial_slug": payload["memorial_slug"],
        "reason": "",
        "source_revision": payload["source_revision"],
        "status": "operator_preview",
    }
