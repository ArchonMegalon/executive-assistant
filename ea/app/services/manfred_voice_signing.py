from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


SIGNATURE_ALGORITHM = "Ed25519"
SIGNATURE_SCOPE = "ea.manfred.voice_receipt.v2"
SIGNING_DOMAIN = b"EA_MANFRED_VOICE_RECEIPT_V2\x00"
VOICE_IDENTITY_SHA256_SEMANTICS = (
    "sha256_canonical_json_utf8_voice_identity_v1"
)
VOICE_ARTIFACT_DIGEST_SEMANTICS = "sha256_exact_file_bytes"
VOICE_REFERENCE_AGGREGATE_SHA256_SEMANTICS = (
    "sha256_canonical_json_utf8_sorted_reference_sha256_list_v1"
)
PROVIDER_VOICE_ID_SHA256_SEMANTICS = "sha256_utf8_provider_voice_id"
IMAGE_ID_SEMANTICS = "docker_image_id_sha256"
MANFRED_TTS_PROVIDER = "unmixr_clone"
MANFRED_TTS_MODEL = "unmixr"
MANFRED_PROVIDER_FREE_CANDIDATE_BOUNDARY = "provider_free_public_text_only"
MANFRED_PHASE_1_LIVE_REVIEW_SURFACE = "phase_1_live_private_review"

# This public key is the repository trust root for Manfred voice-authority and
# final voice-release receipts. Its private half is deliberately not in the
# repository. Rotation requires a reviewed source change and a new release.
MANFRED_VOICE_TRUSTED_PUBLIC_KEYS_B64 = {
    "sha256:5cf6ca3e2d24a5b906eeef66f693fe1ac52dcb32f21487a9a1c8a23758d5d709": (
        "4Q8oSrmUMGv7jcU5RlxJDfVpG1ggLWFKZwToxmKSizA="
    ),
}


class ManfredVoiceSignatureError(ValueError):
    """Raised when a signed Manfred voice receipt is not trustworthy."""


def valid_sha256(value: object) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def valid_image_id(value: object) -> bool:
    return bool(
        isinstance(value, str)
        and value.startswith("sha256:")
        and valid_sha256(value.removeprefix("sha256:"))
    )


def _validate_canonical_json_value(value: object, *, path: str = "$") -> None:
    if value is None or type(value) in {bool, int, str}:
        return
    if type(value) is list:
        for index, nested in enumerate(value):
            _validate_canonical_json_value(nested, path=f"{path}[{index}]")
        return
    if type(value) is dict:
        for key, nested in value.items():
            if type(key) is not str:
                raise ManfredVoiceSignatureError(
                    f"canonical_json_key_invalid:{path}"
                )
            _validate_canonical_json_value(nested, path=f"{path}.{key}")
        return
    raise ManfredVoiceSignatureError(f"canonical_json_type_invalid:{path}")


def canonical_json_bytes(value: object) -> bytes:
    _validate_canonical_json_value(value)
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (OverflowError, TypeError, ValueError) as exc:
        raise ManfredVoiceSignatureError("canonical_json_invalid") from exc


def voice_identity_projection(
    *,
    voice_config_sha256: str,
    voice_manifest_sha256: str,
    voice_reference_aggregate_sha256: str,
    provider_voice_id_sha256: str,
    tts_provider: str,
    tts_model: str,
) -> dict[str, str]:
    digests = {
        "voice_config_sha256": voice_config_sha256,
        "voice_manifest_sha256": voice_manifest_sha256,
        "voice_reference_aggregate_sha256": voice_reference_aggregate_sha256,
        "provider_voice_id_sha256": provider_voice_id_sha256,
    }
    if any(not valid_sha256(value) for value in digests.values()):
        raise ManfredVoiceSignatureError("voice_identity_digest_invalid")
    if tts_provider != MANFRED_TTS_PROVIDER:
        raise ManfredVoiceSignatureError("voice_identity_provider_invalid")
    if tts_model != MANFRED_TTS_MODEL:
        raise ManfredVoiceSignatureError("voice_identity_model_invalid")
    return {
        **digests,
        "tts_provider": tts_provider,
        "tts_model": tts_model,
    }


def voice_identity_sha256(**values: str) -> str:
    projection = voice_identity_projection(**values)
    return hashlib.sha256(canonical_json_bytes(projection)).hexdigest()


def reference_aggregate_sha256(reference_sha256s: list[str]) -> str:
    if (
        type(reference_sha256s) is not list
        or any(not valid_sha256(value) for value in reference_sha256s)
    ):
        raise ManfredVoiceSignatureError("voice_reference_hashes_invalid")
    return hashlib.sha256(
        canonical_json_bytes(sorted(reference_sha256s))
    ).hexdigest()


def public_key_id(public_key: Ed25519PublicKey) -> str:
    raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _decode_public_key_b64(value: object) -> Ed25519PublicKey:
    if not isinstance(value, str) or not value:
        raise ManfredVoiceSignatureError("trusted_public_key_invalid")
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ManfredVoiceSignatureError("trusted_public_key_invalid") from exc
    if len(raw) != 32 or base64.b64encode(raw).decode("ascii") != value:
        raise ManfredVoiceSignatureError("trusted_public_key_invalid")
    try:
        return Ed25519PublicKey.from_public_bytes(raw)
    except ValueError as exc:
        raise ManfredVoiceSignatureError("trusted_public_key_invalid") from exc


def _default_trusted_public_keys() -> dict[str, Ed25519PublicKey]:
    result: dict[str, Ed25519PublicKey] = {}
    for configured_key_id, encoded in MANFRED_VOICE_TRUSTED_PUBLIC_KEYS_B64.items():
        key = _decode_public_key_b64(encoded)
        if public_key_id(key) != configured_key_id:
            raise ManfredVoiceSignatureError("trusted_public_key_id_mismatch")
        result[configured_key_id] = key
    if not result:
        raise ManfredVoiceSignatureError("trusted_public_key_missing")
    return result


def _read_trusted_public_key(path: str | Path) -> Ed25519PublicKey:
    target = Path(path)
    descriptor = -1
    try:
        before = target.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != os.geteuid()
            or stat.S_IMODE(before.st_mode) & 0o022
            or before.st_size < 1
            or before.st_size > 8192
        ):
            raise ManfredVoiceSignatureError("trusted_public_key_path_unsafe")
        if not hasattr(os, "O_NOFOLLOW"):
            raise ManfredVoiceSignatureError("trusted_public_key_nofollow_unavailable")
        descriptor = os.open(
            target,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        )
        opened = os.fstat(descriptor)
        if (
            opened.st_dev != before.st_dev
            or opened.st_ino != before.st_ino
            or opened.st_size != before.st_size
            or opened.st_mtime_ns != before.st_mtime_ns
            or opened.st_ctime_ns != before.st_ctime_ns
        ):
            raise ManfredVoiceSignatureError("trusted_public_key_changed")
        raw = b""
        remaining = opened.st_size
        while remaining:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                raise ManfredVoiceSignatureError("trusted_public_key_short_read")
            raw += chunk
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise ManfredVoiceSignatureError("trusted_public_key_changed")
        after = os.fstat(descriptor)
        if (
            after.st_size != opened.st_size
            or after.st_mtime_ns != opened.st_mtime_ns
            or after.st_ctime_ns != opened.st_ctime_ns
        ):
            raise ManfredVoiceSignatureError("trusted_public_key_changed")
    except ManfredVoiceSignatureError:
        raise
    except OSError as exc:
        raise ManfredVoiceSignatureError("trusted_public_key_path_unsafe") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    stripped = raw.strip()
    try:
        loaded = serialization.load_pem_public_key(stripped)
    except (TypeError, ValueError):
        try:
            loaded = Ed25519PublicKey.from_public_bytes(
                base64.b64decode(stripped, validate=True)
            )
        except (binascii.Error, ValueError) as exc:
            raise ManfredVoiceSignatureError("trusted_public_key_invalid") from exc
    if not isinstance(loaded, Ed25519PublicKey):
        raise ManfredVoiceSignatureError("trusted_public_key_algorithm_invalid")
    return loaded


def trusted_public_keys(
    trusted_public_key_path: str | Path | None = None,
) -> dict[str, Ed25519PublicKey]:
    if trusted_public_key_path is None:
        return _default_trusted_public_keys()
    key = _read_trusted_public_key(trusted_public_key_path)
    return {public_key_id(key): key}


def load_ed25519_private_key(raw: bytes) -> Ed25519PrivateKey:
    try:
        loaded = serialization.load_pem_private_key(raw, password=None)
    except (TypeError, ValueError):
        try:
            loaded = Ed25519PrivateKey.from_private_bytes(raw)
        except ValueError as exc:
            raise ManfredVoiceSignatureError("signing_private_key_invalid") from exc
    if not isinstance(loaded, Ed25519PrivateKey):
        raise ManfredVoiceSignatureError("signing_private_key_algorithm_invalid")
    return loaded


def _signature_message(payload: Mapping[str, object]) -> bytes:
    unsigned = dict(payload)
    signature = unsigned.pop("signature_b64", None)
    if not isinstance(signature, str) or not signature:
        raise ManfredVoiceSignatureError("signature_missing")
    if unsigned.get("signature_algorithm") != SIGNATURE_ALGORITHM:
        raise ManfredVoiceSignatureError("signature_algorithm_invalid")
    if unsigned.get("signature_scope") != SIGNATURE_SCOPE:
        raise ManfredVoiceSignatureError("signature_scope_invalid")
    return SIGNING_DOMAIN + canonical_json_bytes(unsigned)


def sign_receipt(
    payload: Mapping[str, object],
    *,
    private_key: Ed25519PrivateKey,
) -> dict[str, object]:
    if any(
        field in payload
        for field in (
            "signature_algorithm",
            "signature_b64",
            "signature_scope",
            "signing_key_id",
        )
    ):
        raise ManfredVoiceSignatureError("signature_fields_already_present")
    signed: dict[str, object] = {
        **dict(payload),
        "signature_algorithm": SIGNATURE_ALGORITHM,
        "signature_scope": SIGNATURE_SCOPE,
        "signing_key_id": public_key_id(private_key.public_key()),
    }
    message = SIGNING_DOMAIN + canonical_json_bytes(signed)
    signed["signature_b64"] = base64.b64encode(private_key.sign(message)).decode(
        "ascii"
    )
    return signed


def verify_signed_receipt(
    payload: Mapping[str, object],
    *,
    trusted_public_key_path: str | Path | None = None,
) -> None:
    key_id = payload.get("signing_key_id")
    if not isinstance(key_id, str) or not key_id:
        raise ManfredVoiceSignatureError("signing_key_id_missing")
    keys = trusted_public_keys(trusted_public_key_path)
    key = keys.get(key_id)
    if key is None:
        raise ManfredVoiceSignatureError("signing_key_untrusted")
    signature_b64 = payload.get("signature_b64")
    if not isinstance(signature_b64, str):
        raise ManfredVoiceSignatureError("signature_missing")
    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ManfredVoiceSignatureError("signature_invalid") from exc
    if (
        len(signature) != 64
        or base64.b64encode(signature).decode("ascii") != signature_b64
    ):
        raise ManfredVoiceSignatureError("signature_invalid")
    try:
        key.verify(signature, _signature_message(payload))
    except InvalidSignature as exc:
        raise ManfredVoiceSignatureError("signature_invalid") from exc
