#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import sys
from typing import Any
from urllib.parse import urlsplit


REPO_ROOT = Path(__file__).resolve().parents[1]
EA_ROOT = REPO_ROOT / "ea"
if str(EA_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_ROOT))

from app.services.manfred_voice_signing import (  # noqa: E402
    IMAGE_ID_SEMANTICS,
    MANFRED_PHASE_1_LIVE_REVIEW_SURFACE,
    MANFRED_TTS_MODEL,
    MANFRED_TTS_PROVIDER,
    PROVIDER_VOICE_ID_SHA256_SEMANTICS,
    VOICE_ARTIFACT_DIGEST_SEMANTICS,
    VOICE_IDENTITY_SHA256_SEMANTICS,
    VOICE_REFERENCE_AGGREGATE_SHA256_SEMANTICS,
    ManfredVoiceSignatureError,
    load_ed25519_private_key,
    public_key_id,
    sign_receipt,
    trusted_public_keys,
    valid_image_id,
    valid_sha256,
    verify_signed_receipt,
    voice_identity_sha256,
)


READINESS_CONTRACT = "ea.manfred_realtime_conversation_readiness.v1"
READINESS_GENERATOR = (
    "ea/scripts/materialize_manfred_realtime_conversation_readiness.py"
)
OPERATOR_ACCEPTANCE_CONTRACT = "ea.manfred_spoken_conversation_operator_acceptance.v2"
VOICE_AUTHORITY_CONTRACT = "ea.manfred_voice_authority.v2"
RELEASE_CONTRACT = "ea.manfred_voice_release.v2"
RELEASE_GENERATOR = "scripts/materialize_manfred_voice_release.py"
MEMORIAL_SLUG = "manfred"
SOURCE_FINGERPRINT_SEMANTICS = (
    "worktree_source_files_sha256_excluding_generated_only_paths"
)
MAX_RECEIPT_BYTES = 4 * 1024 * 1024
READINESS_MAX_AGE_SECONDS = 24 * 60 * 60
OPERATOR_ACCEPTANCE_MAX_AGE_SECONDS = 24 * 60 * 60
MAX_FUTURE_SKEW_SECONDS = 60
READ_CHUNK_BYTES = 64 * 1024
ATTESTOR_REF_SHA256_SEMANTICS = (
    "sha256_utf8_pseudonymous_authority_reference_v1"
)
REVIEWER_REF_SHA256_SEMANTICS = (
    "sha256_utf8_pseudonymous_operator_reference_v1"
)

ROOM_AND_SPOKEN_TURN_CHECK_IDS = (
    "actual_device_checked",
    "actual_speaker_checked",
    "first_syllable_not_clipped",
    "intelligibility_confirmed",
    "answer_text_fallback_visible",
    "no_internet_search_confirmed",
    "normal_spoken_turn_confirmed",
    "interruption_behavior_confirmed",
    "retry_path_confirmed",
)

READINESS_EVIDENCE_KEYS = frozenset(
    {
        "stt_candidate",
        "stt_captured_benchmark",
        "stt_benchmark",
        "captured_candidate_diagnostic",
        "voice_roundtrip",
        "realtime_browser",
        "room_audio",
        "room_audio_attestation_packet",
    }
)

VOICE_BINDING_FIELDS = frozenset(
    {
        "voice_artifact_digest_semantics",
        "voice_config_sha256",
        "voice_identity_sha256",
        "voice_identity_sha256_semantics",
        "voice_manifest_sha256",
        "voice_reference_aggregate_sha256",
        "voice_reference_aggregate_sha256_semantics",
        "provider_voice_id_sha256",
        "provider_voice_id_sha256_semantics",
        "tts_model",
        "tts_provider",
    }
)

OPERATOR_ACCEPTANCE_FIELDS = frozenset(
    {
        "accepted",
        "checks",
        "contract_name",
        "deployed_source_revision",
        "generated_at",
        "image_id",
        "image_id_semantics",
        "memorial_slug",
        "native_realtime_claim_accepted",
        "public_origin",
        "review_surface",
        "reviewer_ref_sha256",
        "reviewer_ref_sha256_semantics",
        "spoken_turn_claim_accepted",
        *VOICE_BINDING_FIELDS,
    }
)

VOICE_AUTHORITY_FIELDS = frozenset(
    {
        "attested_at",
        "attestor_ref_sha256",
        "attestor_ref_sha256_semantics",
        "authority_verified",
        "contract_name",
        "conversational_use_authorized",
        "memorial_slug",
        "public_synthetic_voice_authorized",
        "revoked",
        "signature_algorithm",
        "signature_b64",
        "signature_scope",
        "signing_key_id",
        "source_material_authorized",
        *VOICE_BINDING_FIELDS,
    }
)

FORBIDDEN_RAW_FIELD_NAMES = frozenset(
    {
        "access_token",
        "api_key",
        "attestor",
        "attestor_name",
        "email",
        "full_name",
        "notes",
        "private_context",
        "raw",
        "raw_response",
        "raw_text",
        "raw_transcript",
        "refresh_token",
        "reviewer",
        "reviewer_name",
        "secret",
        "token",
        "transcript_text",
    }
)


class VoiceReleaseError(ValueError):
    """Raised when the final voice-release transition cannot be proven safely."""


class _UnsafePathError(ValueError):
    pass


def _canonical_utc_now(now: datetime | None = None) -> datetime:
    observed = datetime.now(timezone.utc) if now is None else now
    if not isinstance(observed, datetime) or observed.tzinfo is None:
        raise VoiceReleaseError("clock_timezone_missing")
    return observed.astimezone(timezone.utc)


def _timestamp(
    value: object,
    *,
    field: str,
    now: datetime,
    max_age_seconds: int | None,
) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise VoiceReleaseError(f"{field}_missing")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (OverflowError, ValueError) as exc:
        raise VoiceReleaseError(f"{field}_invalid") from exc
    if parsed.tzinfo is None:
        raise VoiceReleaseError(f"{field}_timezone_missing")
    normalized = parsed.astimezone(timezone.utc)
    age_seconds = (now - normalized).total_seconds()
    if age_seconds < -float(MAX_FUTURE_SKEW_SECONDS):
        raise VoiceReleaseError(f"{field}_future")
    if max_age_seconds is not None and age_seconds > float(max_age_seconds):
        raise VoiceReleaseError(f"{field}_stale")
    return normalized


def _valid_source_revision(value: object) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == 40
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _canonical_public_origin(value: object) -> str:
    if not isinstance(value, str):
        return ""
    raw = value.strip().rstrip("/")
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except (TypeError, ValueError):
        return ""
    hostname = str(parsed.hostname or "").strip().rstrip(".").lower()
    if (
        parsed.scheme.lower() != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        return ""
    authority = f"[{hostname}]" if ":" in hostname else hostname
    if port is not None and port != 443:
        authority = f"{authority}:{port}"
    return f"https://{authority}"


def _open_parent_dirfd(path: str | Path, *, create: bool) -> tuple[int, str]:
    target = Path(path)
    target_name = target.name
    if (
        not target_name
        or target_name in {".", ".."}
        or Path(target_name).name != target_name
    ):
        raise _UnsafePathError("target_name_invalid")
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise _UnsafePathError("nofollow_unavailable")

    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    flags |= getattr(os, "O_CLOEXEC", 0)
    if target.is_absolute():
        if target.anchor != os.sep:
            raise _UnsafePathError("target_anchor_unsupported")
        components = target.parent.parts[1:]
        current_fd = os.open(os.sep, flags)
    else:
        components = target.parent.parts
        current_fd = os.open(".", flags)

    try:
        for component in components:
            if component in {"", "."}:
                continue
            if component == "..":
                raise _UnsafePathError("parent_traversal_forbidden")
            try:
                next_fd = os.open(component, flags, dir_fd=current_fd)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(component, mode=0o700, dir_fd=current_fd)
                except FileExistsError:
                    pass
                next_fd = os.open(component, flags, dir_fd=current_fd)
            except OSError as exc:
                raise _UnsafePathError("parent_component_unsafe") from exc
            try:
                if not stat.S_ISDIR(os.fstat(next_fd).st_mode):
                    raise _UnsafePathError("parent_component_not_directory")
            except Exception:
                os.close(next_fd)
                raise
            os.close(current_fd)
            current_fd = next_fd
        return current_fd, target_name
    except Exception:
        os.close(current_fd)
        raise


def _file_snapshot(metadata: os.stat_result) -> tuple[int, ...]:
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


def _strict_json_object(raw: bytes, *, label: str) -> dict[str, Any]:
    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise VoiceReleaseError(f"{label}_json_duplicate_key")
            result[key] = value
        return result

    def reject_constant(_value: str) -> None:
        raise VoiceReleaseError(f"{label}_json_nonfinite")

    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=object_pairs,
            parse_constant=reject_constant,
        )
    except VoiceReleaseError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VoiceReleaseError(f"{label}_json_invalid") from exc
    if type(payload) is not dict:
        raise VoiceReleaseError(f"{label}_json_not_object")
    return dict(payload)


def _read_private_bytes(
    path: str | Path,
    *,
    label: str,
    exact_mode: int | None = 0o600,
    maximum_bytes: int = MAX_RECEIPT_BYTES,
) -> tuple[bytes, tuple[int, int]]:
    parent_fd = -1
    file_fd = -1
    try:
        try:
            parent_fd, target_name = _open_parent_dirfd(path, create=False)
            before_path = os.stat(
                target_name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError as exc:
            raise VoiceReleaseError(f"{label}_missing") from exc
        except (OSError, _UnsafePathError) as exc:
            raise VoiceReleaseError(f"{label}_path_unsafe") from exc
        if not stat.S_ISREG(before_path.st_mode):
            raise VoiceReleaseError(f"{label}_not_regular")
        if before_path.st_nlink != 1:
            raise VoiceReleaseError(f"{label}_multiply_linked")
        if before_path.st_uid != os.geteuid():
            raise VoiceReleaseError(f"{label}_owner_invalid")
        observed_mode = stat.S_IMODE(before_path.st_mode)
        if (
            (exact_mode is None and observed_mode & 0o022)
            or (exact_mode is not None and observed_mode != exact_mode)
        ):
            raise VoiceReleaseError(f"{label}_permissions_invalid")
        if before_path.st_size < 1 or before_path.st_size > maximum_bytes:
            raise VoiceReleaseError(f"{label}_size_invalid")

        open_flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        try:
            file_fd = os.open(target_name, open_flags, dir_fd=parent_fd)
        except OSError as exc:
            raise VoiceReleaseError(f"{label}_open_failed") from exc
        before_open = os.fstat(file_fd)
        if _file_snapshot(before_open) != _file_snapshot(before_path):
            raise VoiceReleaseError(f"{label}_changed_during_open")

        chunks: list[bytes] = []
        remaining = before_open.st_size
        while remaining:
            chunk = os.read(file_fd, min(remaining, READ_CHUNK_BYTES))
            if not chunk:
                raise VoiceReleaseError(f"{label}_short_read")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(file_fd, 1):
            raise VoiceReleaseError(f"{label}_grew_during_read")
        after_open = os.fstat(file_fd)
        if _file_snapshot(after_open) != _file_snapshot(before_open):
            raise VoiceReleaseError(f"{label}_changed_during_read")
        return b"".join(chunks), (before_open.st_dev, before_open.st_ino)
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        if parent_fd >= 0:
            os.close(parent_fd)


def _read_private_receipt(
    path: str | Path,
    *,
    label: str,
) -> tuple[dict[str, Any], bytes, tuple[int, int]]:
    raw, identity = _read_private_bytes(path, label=label)
    return _strict_json_object(raw, label=label), raw, identity


def _read_signing_private_key(
    path: str | Path,
) -> tuple[Any, tuple[int, int]]:
    raw, identity = _read_private_bytes(path, label="signing_private_key")
    try:
        key = load_ed25519_private_key(raw)
    except ManfredVoiceSignatureError as exc:
        raise VoiceReleaseError(str(exc)) from exc
    return key, identity


def _trusted_public_keys_with_identity(
    path: str | Path | None,
) -> tuple[dict[str, Any], tuple[int, int] | None]:
    if path is None:
        return trusted_public_keys(), None

    before_raw, before_identity = _read_private_bytes(
        path,
        label="trusted_public_key",
        exact_mode=None,
        maximum_bytes=8192,
    )
    keys = trusted_public_keys(path)
    after_raw, after_identity = _read_private_bytes(
        path,
        label="trusted_public_key",
        exact_mode=None,
        maximum_bytes=8192,
    )
    if before_identity != after_identity or before_raw != after_raw:
        raise VoiceReleaseError("trusted_public_key_changed_during_validation")
    return keys, before_identity


def _assert_no_forbidden_raw_fields(value: object, *, label: str) -> None:
    if type(value) is dict:
        for raw_key, nested in value.items():
            key = str(raw_key).strip().casefold().replace("-", "_")
            if key in FORBIDDEN_RAW_FIELD_NAMES:
                raise VoiceReleaseError(f"{label}_raw_or_identity_field_forbidden")
            _assert_no_forbidden_raw_fields(nested, label=label)
    elif type(value) is list:
        for nested in value:
            _assert_no_forbidden_raw_fields(nested, label=label)


def _require_exact_fields(
    receipt: dict[str, Any],
    *,
    expected: frozenset[str],
    label: str,
) -> None:
    if set(receipt) != expected:
        raise VoiceReleaseError(f"{label}_fields_invalid")


def _expected_voice_binding(
    *,
    voice_config_sha256: str,
    voice_manifest_sha256: str,
    voice_reference_aggregate_sha256: str,
    provider_voice_id_sha256: str,
    tts_provider: str,
    tts_model: str,
) -> dict[str, str]:
    try:
        identity = voice_identity_sha256(
            voice_config_sha256=voice_config_sha256,
            voice_manifest_sha256=voice_manifest_sha256,
            voice_reference_aggregate_sha256=voice_reference_aggregate_sha256,
            provider_voice_id_sha256=provider_voice_id_sha256,
            tts_provider=tts_provider,
            tts_model=tts_model,
        )
    except ManfredVoiceSignatureError as exc:
        raise VoiceReleaseError(str(exc)) from exc
    return {
        "voice_artifact_digest_semantics": VOICE_ARTIFACT_DIGEST_SEMANTICS,
        "voice_config_sha256": voice_config_sha256,
        "voice_identity_sha256": identity,
        "voice_identity_sha256_semantics": VOICE_IDENTITY_SHA256_SEMANTICS,
        "voice_manifest_sha256": voice_manifest_sha256,
        "voice_reference_aggregate_sha256": voice_reference_aggregate_sha256,
        "voice_reference_aggregate_sha256_semantics": (
            VOICE_REFERENCE_AGGREGATE_SHA256_SEMANTICS
        ),
        "provider_voice_id_sha256": provider_voice_id_sha256,
        "provider_voice_id_sha256_semantics": (
            PROVIDER_VOICE_ID_SHA256_SEMANTICS
        ),
        "tts_model": tts_model,
        "tts_provider": tts_provider,
    }


def _validate_readiness(
    receipt: dict[str, Any],
    *,
    source_revision: str,
    now: datetime,
) -> str:
    if receipt.get("contract_name") != READINESS_CONTRACT:
        raise VoiceReleaseError("readiness_contract_mismatch")
    if receipt.get("generated_by") != READINESS_GENERATOR:
        raise VoiceReleaseError("readiness_generator_mismatch")
    _timestamp(
        receipt.get("generated_at"),
        field="readiness_generated_at",
        now=now,
        max_age_seconds=READINESS_MAX_AGE_SECONDS,
    )
    if receipt.get("evidence_source") != "receipt_aggregation":
        raise VoiceReleaseError("readiness_evidence_source_invalid")
    if receipt.get("status") != "ready_for_realtime_conversation_review":
        raise VoiceReleaseError("readiness_status_invalid")
    if receipt.get("ready_for_realtime_conversation_review") is not True:
        raise VoiceReleaseError("readiness_flag_invalid")
    blocked_checks = receipt.get("blocked_checks")
    if type(blocked_checks) is not list or blocked_checks != []:
        raise VoiceReleaseError("readiness_blocked_checks_present")
    if receipt.get("source_git_head") != source_revision:
        raise VoiceReleaseError("readiness_source_revision_mismatch")
    if receipt.get("head_semantics") != "source_state":
        raise VoiceReleaseError("readiness_head_semantics_invalid")
    source_fingerprint = receipt.get("source_state_fingerprint")
    if not valid_sha256(source_fingerprint):
        raise VoiceReleaseError("readiness_source_fingerprint_invalid")
    if (
        receipt.get("source_state_fingerprint_semantics")
        != SOURCE_FINGERPRINT_SEMANTICS
    ):
        raise VoiceReleaseError("readiness_source_fingerprint_semantics_invalid")
    for field in (
        "realtime_conversation_claim_allowed",
        "premium_spoken_claim_allowed",
        "goal_completion_claim_allowed",
    ):
        if receipt.get(field) is not False:
            raise VoiceReleaseError(f"readiness_review_boundary_invalid:{field}")

    expected_privacy = {
        "candidate_raw_text_fields": False,
        "raw_private_context_exposed": False,
        "raw_transcript_fields": False,
        "redacted_text_fields": True,
    }
    if receipt.get("privacy") != expected_privacy:
        raise VoiceReleaseError("readiness_privacy_invalid")
    raw_evidence = receipt.get("input_evidence")
    if type(raw_evidence) is not dict or set(raw_evidence) != READINESS_EVIDENCE_KEYS:
        raise VoiceReleaseError("readiness_input_evidence_incomplete")
    for key in sorted(READINESS_EVIDENCE_KEYS):
        row = raw_evidence.get(key)
        if type(row) is not dict:
            raise VoiceReleaseError(f"readiness_input_evidence_invalid:{key}")
        for field in (
            "present",
            "contract_valid",
            "fresh",
            "source_state_matches_current",
        ):
            if row.get(field) is not True:
                raise VoiceReleaseError(
                    f"readiness_input_evidence_not_current:{key}:{field}"
                )
        for field in (
            "raw_private_context_exposed",
            "raw_transcript_fields_exposed",
            "raw_credentials_exposed",
            "raw_receipt_payload_exposed",
        ):
            if row.get(field) is not False:
                raise VoiceReleaseError(
                    f"readiness_input_evidence_privacy_invalid:{key}:{field}"
                )
        if not valid_sha256(row.get("receipt_sha256")):
            raise VoiceReleaseError(f"readiness_input_evidence_digest_invalid:{key}")
    _assert_no_forbidden_raw_fields(receipt, label="readiness")
    return str(source_fingerprint)


def _validate_operator_acceptance(
    receipt: dict[str, Any],
    *,
    source_revision: str,
    public_origin: str,
    image_id: str,
    voice_binding: dict[str, str],
    now: datetime,
) -> None:
    _require_exact_fields(
        receipt,
        expected=OPERATOR_ACCEPTANCE_FIELDS,
        label="operator_acceptance",
    )
    _assert_no_forbidden_raw_fields(receipt, label="operator_acceptance")
    if receipt.get("contract_name") != OPERATOR_ACCEPTANCE_CONTRACT:
        raise VoiceReleaseError("operator_acceptance_contract_mismatch")
    if receipt.get("memorial_slug") != MEMORIAL_SLUG:
        raise VoiceReleaseError("operator_acceptance_slug_mismatch")
    if receipt.get("deployed_source_revision") != source_revision:
        raise VoiceReleaseError("operator_acceptance_source_revision_mismatch")
    if receipt.get("public_origin") != public_origin:
        raise VoiceReleaseError("operator_acceptance_public_origin_mismatch")
    if (
        receipt.get("review_surface")
        != MANFRED_PHASE_1_LIVE_REVIEW_SURFACE
    ):
        raise VoiceReleaseError("operator_acceptance_review_surface_invalid")
    if (
        receipt.get("image_id") != image_id
        or receipt.get("image_id_semantics") != IMAGE_ID_SEMANTICS
    ):
        raise VoiceReleaseError("operator_acceptance_image_id_mismatch")
    for field, expected in voice_binding.items():
        if receipt.get(field) != expected:
            raise VoiceReleaseError(f"operator_acceptance_voice_mismatch:{field}")
    _timestamp(
        receipt.get("generated_at"),
        field="operator_acceptance_generated_at",
        now=now,
        max_age_seconds=OPERATOR_ACCEPTANCE_MAX_AGE_SECONDS,
    )
    if receipt.get("accepted") is not True:
        raise VoiceReleaseError("operator_acceptance_missing")
    if receipt.get("spoken_turn_claim_accepted") is not True:
        raise VoiceReleaseError("operator_acceptance_spoken_turn_missing")
    if receipt.get("native_realtime_claim_accepted") is not False:
        raise VoiceReleaseError("operator_acceptance_native_realtime_invalid")
    if not valid_sha256(receipt.get("reviewer_ref_sha256")):
        raise VoiceReleaseError("operator_acceptance_reviewer_ref_invalid")
    if (
        receipt.get("reviewer_ref_sha256_semantics")
        != REVIEWER_REF_SHA256_SEMANTICS
    ):
        raise VoiceReleaseError(
            "operator_acceptance_reviewer_ref_semantics_invalid"
        )
    checks = receipt.get("checks")
    if (
        type(checks) is not dict
        or set(checks) != set(ROOM_AND_SPOKEN_TURN_CHECK_IDS)
    ):
        raise VoiceReleaseError("operator_acceptance_checks_invalid")
    for check_id in ROOM_AND_SPOKEN_TURN_CHECK_IDS:
        if checks.get(check_id) is not True:
            raise VoiceReleaseError(f"operator_acceptance_check_failed:{check_id}")


def _validate_voice_authority(
    receipt: dict[str, Any],
    *,
    voice_binding: dict[str, str],
    now: datetime,
    trusted_public_key_path: str | Path | None,
) -> None:
    _require_exact_fields(
        receipt,
        expected=VOICE_AUTHORITY_FIELDS,
        label="voice_authority",
    )
    _assert_no_forbidden_raw_fields(receipt, label="voice_authority")
    if receipt.get("contract_name") != VOICE_AUTHORITY_CONTRACT:
        raise VoiceReleaseError("voice_authority_contract_mismatch")
    try:
        verify_signed_receipt(
            receipt,
            trusted_public_key_path=trusted_public_key_path,
        )
    except ManfredVoiceSignatureError as exc:
        raise VoiceReleaseError("voice_authority_signature_invalid") from exc
    if receipt.get("memorial_slug") != MEMORIAL_SLUG:
        raise VoiceReleaseError("voice_authority_slug_mismatch")
    for field in (
        "authority_verified",
        "public_synthetic_voice_authorized",
        "conversational_use_authorized",
        "source_material_authorized",
    ):
        if receipt.get(field) is not True:
            raise VoiceReleaseError(f"voice_authority_missing:{field}")
    if receipt.get("revoked") is not False:
        raise VoiceReleaseError("voice_authority_revoked")
    _timestamp(
        receipt.get("attested_at"),
        field="voice_authority_attested_at",
        now=now,
        max_age_seconds=None,
    )
    if not valid_sha256(receipt.get("attestor_ref_sha256")):
        raise VoiceReleaseError("voice_authority_attestor_ref_invalid")
    if (
        receipt.get("attestor_ref_sha256_semantics")
        != ATTESTOR_REF_SHA256_SEMANTICS
    ):
        raise VoiceReleaseError("voice_authority_attestor_ref_semantics_invalid")
    for field, expected in voice_binding.items():
        if receipt.get(field) != expected:
            raise VoiceReleaseError(f"voice_authority_voice_mismatch:{field}")


def _render_release(receipt: dict[str, Any]) -> bytes:
    try:
        rendered = (
            json.dumps(
                receipt,
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (OverflowError, TypeError, ValueError) as exc:
        raise VoiceReleaseError("release_json_invalid") from exc
    if len(rendered) > MAX_RECEIPT_BYTES:
        raise VoiceReleaseError("release_json_too_large")
    return rendered


def _target_identity(
    parent_fd: int,
    target_name: str,
) -> tuple[int, int, int] | None:
    try:
        metadata = os.stat(
            target_name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise _UnsafePathError("target_stat_failed") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise _UnsafePathError("target_not_regular")
    if metadata.st_nlink != 1:
        raise _UnsafePathError("target_multiply_linked")
    if metadata.st_uid != os.geteuid():
        raise _UnsafePathError("target_owner_invalid")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise _UnsafePathError("target_permissions_invalid")
    return (metadata.st_dev, metadata.st_ino, stat.S_IFMT(metadata.st_mode))


def _assert_safe_output_parent(parent_fd: int) -> os.stat_result:
    metadata = os.fstat(parent_fd)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        raise _UnsafePathError("output_parent_permissions_invalid")
    return metadata


def _write_private_atomic(
    path: str | Path,
    payload: dict[str, Any],
    *,
    input_identities: set[tuple[int, int]],
) -> None:
    rendered = _render_release(payload)
    rendered_sha256 = hashlib.sha256(rendered).digest()
    parent_fd = -1
    temp_fd = -1
    temp_name = ""
    try:
        try:
            parent_fd, target_name = _open_parent_dirfd(path, create=True)
            parent_before = _assert_safe_output_parent(parent_fd)
            initial_identity = _target_identity(parent_fd, target_name)
        except (OSError, _UnsafePathError) as exc:
            raise VoiceReleaseError("release_output_path_unsafe") from exc
        if initial_identity is not None and initial_identity[:2] in input_identities:
            raise VoiceReleaseError("release_output_matches_input")

        flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        flags |= getattr(os, "O_CLOEXEC", 0)
        for _attempt in range(32):
            candidate = f".{target_name[:32]}.tmp-{os.getpid()}-{secrets.token_hex(12)}"
            try:
                temp_fd = os.open(candidate, flags, 0o600, dir_fd=parent_fd)
            except FileExistsError:
                continue
            except OSError as exc:
                raise VoiceReleaseError("release_output_temp_open_failed") from exc
            temp_name = candidate
            break
        if temp_fd < 0 or not temp_name:
            raise VoiceReleaseError("release_output_temp_unavailable")

        view = memoryview(rendered)
        offset = 0
        while offset < len(view):
            written = os.write(temp_fd, view[offset:])
            if written <= 0:
                raise VoiceReleaseError("release_output_short_write")
            offset += written
        os.fchmod(temp_fd, 0o600)
        os.fsync(temp_fd)
        written_metadata = os.fstat(temp_fd)
        if (
            not stat.S_ISREG(written_metadata.st_mode)
            or stat.S_IMODE(written_metadata.st_mode) != 0o600
            or written_metadata.st_uid != os.geteuid()
            or written_metadata.st_nlink != 1
            or written_metadata.st_size != len(rendered)
        ):
            raise VoiceReleaseError("release_output_temp_invalid")

        try:
            current_identity = _target_identity(parent_fd, target_name)
            parent_current = _assert_safe_output_parent(parent_fd)
        except _UnsafePathError as exc:
            raise VoiceReleaseError("release_output_changed_before_commit") from exc
        if current_identity != initial_identity or (
            parent_current.st_dev,
            parent_current.st_ino,
            parent_current.st_uid,
            stat.S_IMODE(parent_current.st_mode),
        ) != (
            parent_before.st_dev,
            parent_before.st_ino,
            parent_before.st_uid,
            stat.S_IMODE(parent_before.st_mode),
        ):
            raise VoiceReleaseError("release_output_changed_before_commit")
        try:
            os.replace(
                temp_name,
                target_name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            temp_name = ""
            os.fsync(parent_fd)
        except OSError as exc:
            raise VoiceReleaseError("release_output_commit_failed") from exc

        committed_fd = os.fstat(temp_fd)
        committed_path = os.stat(
            target_name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(committed_fd.st_mode)
            or committed_fd.st_dev != committed_path.st_dev
            or committed_fd.st_ino != committed_path.st_ino
            or committed_fd.st_uid != os.geteuid()
            or committed_path.st_uid != os.geteuid()
            or committed_fd.st_nlink != 1
            or committed_path.st_nlink != 1
            or stat.S_IMODE(committed_fd.st_mode) != 0o600
            or stat.S_IMODE(committed_path.st_mode) != 0o600
            or committed_fd.st_size != len(rendered)
            or committed_path.st_size != len(rendered)
        ):
            raise VoiceReleaseError("release_output_commit_invalid")

        os.lseek(temp_fd, 0, os.SEEK_SET)
        installed_chunks: list[bytes] = []
        remaining = len(rendered)
        while remaining:
            chunk = os.read(temp_fd, min(remaining, READ_CHUNK_BYTES))
            if not chunk:
                raise VoiceReleaseError("release_output_verify_short_read")
            installed_chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(temp_fd, 1):
            raise VoiceReleaseError("release_output_verify_grew")
        installed = b"".join(installed_chunks)
        if (
            hashlib.sha256(installed).digest() != rendered_sha256
            or installed != rendered
        ):
            raise VoiceReleaseError("release_output_content_mismatch")
        verified_fd = os.fstat(temp_fd)
        verified_path = os.stat(
            target_name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        if (
            _file_snapshot(verified_fd) != _file_snapshot(committed_fd)
            or _file_snapshot(verified_path) != _file_snapshot(committed_path)
            or verified_fd.st_dev != verified_path.st_dev
            or verified_fd.st_ino != verified_path.st_ino
        ):
            raise VoiceReleaseError("release_output_changed_after_commit")
    finally:
        if temp_fd >= 0:
            os.close(temp_fd)
        if parent_fd >= 0:
            if temp_name:
                try:
                    os.unlink(temp_name, dir_fd=parent_fd)
                except OSError:
                    pass
            os.close(parent_fd)


def materialize_manfred_voice_release(
    *,
    readiness_receipt_path: str | Path,
    operator_acceptance_receipt_path: str | Path,
    voice_authority_receipt_path: str | Path,
    signing_private_key_path: str | Path,
    output_path: str | Path,
    source_revision: str,
    public_origin: str,
    image_id: str,
    voice_config_sha256: str,
    voice_manifest_sha256: str,
    voice_reference_aggregate_sha256: str,
    provider_voice_id_sha256: str,
    tts_provider: str,
    tts_model: str,
    trusted_public_key_path: str | Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not _valid_source_revision(source_revision):
        raise VoiceReleaseError("source_revision_invalid")
    canonical_origin = _canonical_public_origin(public_origin)
    if not canonical_origin or canonical_origin != public_origin:
        raise VoiceReleaseError("public_origin_invalid")
    if not valid_image_id(image_id):
        raise VoiceReleaseError("image_id_invalid")
    voice_binding = _expected_voice_binding(
        voice_config_sha256=voice_config_sha256,
        voice_manifest_sha256=voice_manifest_sha256,
        voice_reference_aggregate_sha256=voice_reference_aggregate_sha256,
        provider_voice_id_sha256=provider_voice_id_sha256,
        tts_provider=tts_provider,
        tts_model=tts_model,
    )

    distinct_paths: list[str | Path] = [
        readiness_receipt_path,
        operator_acceptance_receipt_path,
        voice_authority_receipt_path,
        signing_private_key_path,
        output_path,
    ]
    if trusted_public_key_path is not None:
        distinct_paths.append(trusted_public_key_path)
    normalized_paths = [
        os.path.abspath(os.fspath(path))
        for path in distinct_paths
    ]
    if len(set(normalized_paths)) != len(normalized_paths):
        raise VoiceReleaseError("release_paths_not_distinct")

    observed_at = _canonical_utc_now(now)
    readiness, readiness_raw, readiness_identity = _read_private_receipt(
        readiness_receipt_path,
        label="readiness_receipt",
    )
    operator_acceptance, operator_raw, operator_identity = _read_private_receipt(
        operator_acceptance_receipt_path,
        label="operator_acceptance_receipt",
    )
    voice_authority, authority_raw, authority_identity = _read_private_receipt(
        voice_authority_receipt_path,
        label="voice_authority_receipt",
    )
    signing_key, signing_key_identity = _read_signing_private_key(
        signing_private_key_path
    )
    try:
        trusted_keys, trusted_public_key_identity = (
            _trusted_public_keys_with_identity(
                trusted_public_key_path
            )
        )
        if public_key_id(signing_key.public_key()) not in trusted_keys:
            raise VoiceReleaseError("signing_private_key_untrusted")
    except ManfredVoiceSignatureError as exc:
        raise VoiceReleaseError(str(exc)) from exc

    source_fingerprint = _validate_readiness(
        readiness,
        source_revision=source_revision,
        now=observed_at,
    )
    _validate_operator_acceptance(
        operator_acceptance,
        source_revision=source_revision,
        public_origin=canonical_origin,
        image_id=image_id,
        voice_binding=voice_binding,
        now=observed_at,
    )
    _validate_voice_authority(
        voice_authority,
        voice_binding=voice_binding,
        now=observed_at,
        trusted_public_key_path=trusted_public_key_path,
    )

    unsigned_release: dict[str, object] = {
        "blocked_checks": [],
        "contract_name": RELEASE_CONTRACT,
        "conversational_use_authorized": True,
        "deployed_source_sha256": hashlib.sha256(
            source_revision.encode("ascii")
        ).hexdigest(),
        "deployed_source_sha256_semantics": "sha256_ascii_source_revision",
        "generated_at": observed_at.replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "generated_by": RELEASE_GENERATOR,
        "head_semantics": "source_state",
        "image_id": image_id,
        "image_id_semantics": IMAGE_ID_SEMANTICS,
        "input_digest_semantics": "sha256_exact_input_bytes",
        "memorial_slug": MEMORIAL_SLUG,
        "native_realtime_claim_allowed": False,
        "operator_acceptance_receipt_sha256": hashlib.sha256(
            operator_raw
        ).hexdigest(),
        "operator_acceptance_review_surface": (
            MANFRED_PHASE_1_LIVE_REVIEW_SURFACE
        ),
        "operator_acceptance_verified": True,
        "premium_spoken_claim_allowed": True,
        "public_origin": canonical_origin,
        "public_synthetic_voice_authorized": True,
        "readiness_receipt_sha256": hashlib.sha256(readiness_raw).hexdigest(),
        "readiness_status": "ready_for_spoken_turn_release",
        "readiness_verified": True,
        "room_and_spoken_turn_checks_verified": True,
        "runtime_enablement_allowed": True,
        "source_git_head": source_revision,
        "source_material_authorized": True,
        "source_revision": source_revision,
        "source_state_fingerprint": source_fingerprint,
        "source_state_fingerprint_semantics": SOURCE_FINGERPRINT_SEMANTICS,
        "spoken_turn_claim_allowed": True,
        "status": "released",
        "voice_authority_receipt_sha256": hashlib.sha256(authority_raw).hexdigest(),
        "voice_authority_revoked": False,
        "voice_authority_verified": True,
        **voice_binding,
    }
    try:
        release = sign_receipt(unsigned_release, private_key=signing_key)
    except ManfredVoiceSignatureError as exc:
        raise VoiceReleaseError(str(exc)) from exc
    input_identities = {
        readiness_identity,
        operator_identity,
        authority_identity,
        signing_key_identity,
    }
    if trusted_public_key_identity is not None:
        input_identities.add(trusted_public_key_identity)
    _write_private_atomic(
        output_path,
        release,
        input_identities=input_identities,
    )
    return release


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize the signed, image-bound Manfred spoken-turn release."
        )
    )
    parser.add_argument("--readiness-receipt", required=True)
    parser.add_argument("--operator-acceptance-receipt", required=True)
    parser.add_argument("--voice-authority-receipt", required=True)
    parser.add_argument("--signing-private-key", required=True)
    parser.add_argument("--trusted-public-key")
    parser.add_argument("--output", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--public-origin", required=True)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--voice-config-sha256", required=True)
    parser.add_argument("--voice-manifest-sha256", required=True)
    parser.add_argument("--voice-reference-aggregate-sha256", required=True)
    parser.add_argument("--provider-voice-id-sha256", required=True)
    parser.add_argument("--tts-provider", required=True)
    parser.add_argument("--tts-model", required=True)
    args = parser.parse_args(argv)
    try:
        release = materialize_manfred_voice_release(
            readiness_receipt_path=args.readiness_receipt,
            operator_acceptance_receipt_path=args.operator_acceptance_receipt,
            voice_authority_receipt_path=args.voice_authority_receipt,
            signing_private_key_path=args.signing_private_key,
            trusted_public_key_path=args.trusted_public_key,
            output_path=args.output,
            source_revision=args.source_revision,
            public_origin=args.public_origin,
            image_id=args.image_id,
            voice_config_sha256=args.voice_config_sha256,
            voice_manifest_sha256=args.voice_manifest_sha256,
            voice_reference_aggregate_sha256=(
                args.voice_reference_aggregate_sha256
            ),
            provider_voice_id_sha256=args.provider_voice_id_sha256,
            tts_provider=args.tts_provider,
            tts_model=args.tts_model,
        )
    except VoiceReleaseError as exc:
        print(
            json.dumps(
                {"status": "blocked", "reason": str(exc)},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {
                "contract_name": release["contract_name"],
                "output": str(args.output),
                "status": release["status"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
