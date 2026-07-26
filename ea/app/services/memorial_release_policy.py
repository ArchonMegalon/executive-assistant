from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import time
from typing import Any
from urllib.parse import urlsplit

from app.services.manfred_voice_signing import (
    IMAGE_ID_SEMANTICS,
    MANFRED_PHASE_1_LIVE_REVIEW_SURFACE,
    MANFRED_TTS_MODEL,
    MANFRED_TTS_PROVIDER,
    PROVIDER_VOICE_ID_SHA256_SEMANTICS,
    SIGNATURE_ALGORITHM,
    SIGNATURE_SCOPE,
    VOICE_ARTIFACT_DIGEST_SEMANTICS,
    VOICE_IDENTITY_SHA256_SEMANTICS,
    VOICE_REFERENCE_AGGREGATE_SHA256_SEMANTICS,
    ManfredVoiceSignatureError,
    valid_image_id,
    valid_sha256,
    verify_signed_receipt,
    voice_identity_sha256,
)


MANFRED_VOICE_RELEASE_CONTRACT = "ea.manfred_voice_release.v2"
MANFRED_VOICE_RELEASE_GENERATOR = "scripts/materialize_manfred_voice_release.py"
MANFRED_VOICE_PUBLIC_EVALUATION_CONTRACT = (
    "ea.manfred_voice_public_evaluation_release.v1"
)
MANFRED_VOICE_PUBLIC_EVALUATION_GENERATOR = (
    "scripts/materialize_manfred_voice_public_evaluation_release.py"
)
MANFRED_VOICE_PUBLIC_EVALUATION_CONFIRMATION = (
    "I authorize public evaluation of Manfred's synthetic spoken conversation "
    "while the listed STT, room-audio, and manual checks remain unverified and "
    "no release-quality claims are made."
)
MANFRED_VOICE_PUBLIC_EVALUATION_MODE = (
    "owner_authorized_public_evaluation"
)
MANFRED_VOICE_PUBLIC_EVALUATION_ACCESS_MODE = (
    "owner-authorized-public-evaluation"
)
MANFRED_VOICE_PUBLIC_EVALUATION_AUTHORIZATION_SCOPE = (
    "public_live_owner_evaluation_only"
)
MANFRED_VOICE_PUBLIC_EVALUATION_MAX_SECONDS = 7 * 24 * 60 * 60
MEMORIAL_VOICE_RELEASE_MAX_BYTES = 4 * 1024 * 1024
MEMORIAL_VOICE_RELEASE_MODES = frozenset({0o400, 0o440, 0o600})
MAX_FUTURE_SKEW_SECONDS = 60
MANFRED_VOICE_RELEASE_FIELDS = frozenset(
    {
        "blocked_checks",
        "contract_name",
        "conversational_use_authorized",
        "deployed_source_sha256",
        "deployed_source_sha256_semantics",
        "generated_at",
        "generated_by",
        "head_semantics",
        "image_id",
        "image_id_semantics",
        "input_digest_semantics",
        "memorial_slug",
        "native_realtime_claim_allowed",
        "operator_acceptance_receipt_sha256",
        "operator_acceptance_review_surface",
        "operator_acceptance_verified",
        "premium_spoken_claim_allowed",
        "provider_voice_id_sha256",
        "provider_voice_id_sha256_semantics",
        "public_origin",
        "public_synthetic_voice_authorized",
        "readiness_receipt_sha256",
        "readiness_status",
        "readiness_verified",
        "room_and_spoken_turn_checks_verified",
        "runtime_enablement_allowed",
        "signature_algorithm",
        "signature_b64",
        "signature_scope",
        "signing_key_id",
        "source_git_head",
        "source_material_authorized",
        "source_revision",
        "source_state_fingerprint",
        "source_state_fingerprint_semantics",
        "spoken_turn_claim_allowed",
        "status",
        "tts_model",
        "tts_provider",
        "voice_artifact_digest_semantics",
        "voice_authority_receipt_sha256",
        "voice_authority_revoked",
        "voice_authority_verified",
        "voice_config_sha256",
        "voice_identity_sha256",
        "voice_identity_sha256_semantics",
        "voice_manifest_sha256",
        "voice_reference_aggregate_sha256",
        "voice_reference_aggregate_sha256_semantics",
    }
)
MANFRED_VOICE_PUBLIC_EVALUATION_FIELDS = frozenset(
    {
        "authorization_ref_sha256",
        "authorization_ref_sha256_semantics",
        "authorization_scope",
        "authorization_statement_sha256",
        "authorization_statement_sha256_semantics",
        "blocked_checks",
        "contract_name",
        "conversational_use_authorized",
        "deployed_source_sha256",
        "deployed_source_sha256_semantics",
        "expires_at",
        "generated_at",
        "generated_by",
        "goal_completion_claim_allowed",
        "head_semantics",
        "image_id",
        "image_id_semantics",
        "input_digest_semantics",
        "memorial_slug",
        "native_realtime_claim_allowed",
        "operator_acceptance_verified",
        "premium_spoken_claim_allowed",
        "provider_voice_id_sha256",
        "provider_voice_id_sha256_semantics",
        "public_evaluation_allowed",
        "public_evaluation_disclosure_required",
        "public_origin",
        "public_synthetic_voice_authorized",
        "readiness_prerequisites_satisfied",
        "baseline_readiness_receipt_contract_verified",
        "baseline_readiness_receipt_sha256",
        "baseline_readiness_same_source_revision",
        "baseline_readiness_source_revision",
        "baseline_readiness_status",
        "realtime_conversation_claim_allowed",
        "release_mode",
        "revoked",
        "room_and_spoken_turn_checks_verified",
        "runtime_enablement_allowed",
        "signature_algorithm",
        "signature_b64",
        "signature_scope",
        "signing_key_id",
        "source_git_head",
        "source_material_authorized",
        "source_revision",
        "source_state_fingerprint",
        "source_state_fingerprint_semantics",
        "spoken_turn_claim_allowed",
        "status",
        "tts_model",
        "tts_provider",
        "unverified_evidence_keys",
        "unverified_manual_check_ids",
        "voice_artifact_digest_semantics",
        "voice_authority_receipt_sha256",
        "voice_authority_revoked",
        "voice_authority_verified",
        "voice_config_sha256",
        "voice_identity_sha256",
        "voice_identity_sha256_semantics",
        "voice_manifest_sha256",
        "voice_reference_aggregate_sha256",
        "voice_reference_aggregate_sha256_semantics",
    }
)
MANFRED_VOICE_PUBLIC_EVALUATION_BLOCKERS = frozenset(
    {
        "automated_voice_browser_tts_ready",
        "captured_candidate_diagnostic_clean",
        "manual_room_checks_confirmed",
        "real_captured_stt_fixture_ready",
        "room_audio_receipt_passed",
    }
)
MANFRED_VOICE_PUBLIC_EVALUATION_EVIDENCE_KEYS = frozenset(
    {
        "captured_candidate_diagnostic",
        "realtime_browser",
        "room_audio",
        "stt_benchmark",
        "stt_candidate",
        "stt_captured_benchmark",
        "voice_roundtrip",
    }
)
MANFRED_VOICE_PUBLIC_EVALUATION_MANUAL_CHECK_IDS = (
    "actual_device_checked",
    "actual_speaker_checked",
    "first_syllable_not_clipped",
    "intelligibility_confirmed",
    "answer_text_fallback_visible",
    "no_internet_search_confirmed",
    "normal_spoken_turn_confirmed",
    "interruption_behavior_confirmed",
    "retry_path_confirmed",
    "likeness_accepted",
    "warmth_accepted",
    "pronunciation_accepted",
)
PUBLIC_EVALUATION_AUTHORIZATION_REF_SHA256_SEMANTICS = (
    "sha256_utf8_pseudonymous_public_evaluation_authorization_reference_v1"
)
PUBLIC_EVALUATION_STATEMENT_SHA256_SEMANTICS = (
    "sha256_utf8_exact_public_evaluation_confirmation_v1"
)


def _blocked(reason: str, *, receipt_status: str = "") -> dict[str, object]:
    return {
        "allowed": False,
        "status": "blocked",
        "reason": reason,
        "receipt_status": receipt_status,
    }


def _parse_timestamp(value: object) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (OverflowError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).timestamp()


def _source_revision(value: object) -> bool:
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


def _read_release_receipt(path: Path) -> tuple[dict[str, Any] | None, str]:
    try:
        before_path = path.lstat()
    except OSError:
        return None, "release_receipt_missing"
    if stat.S_ISLNK(before_path.st_mode):
        return None, "release_receipt_symlink"
    if not stat.S_ISREG(before_path.st_mode):
        return None, "release_receipt_not_regular"
    if before_path.st_nlink != 1:
        return None, "release_receipt_multiply_linked"
    if before_path.st_uid != os.geteuid():
        return None, "release_receipt_owner_mismatch"
    if stat.S_IMODE(before_path.st_mode) not in MEMORIAL_VOICE_RELEASE_MODES:
        return None, "release_receipt_permissions_unsafe"
    if (
        before_path.st_size <= 0
        or before_path.st_size > MEMORIAL_VOICE_RELEASE_MAX_BYTES
    ):
        return None, "release_receipt_size_invalid"
    if not hasattr(os, "O_NOFOLLOW"):
        return None, "release_receipt_nofollow_unavailable"
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    descriptor = -1
    chunks: list[bytes] = []
    try:
        descriptor = os.open(path, flags)
        before_open = os.fstat(descriptor)
        if _file_snapshot(before_open) != _file_snapshot(before_path):
            return None, "release_receipt_changed_during_open"
        remaining = int(before_open.st_size)
        while remaining:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                return None, "release_receipt_short_read"
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            return None, "release_receipt_changed_during_read"
        after_open = os.fstat(descriptor)
        if _file_snapshot(after_open) != _file_snapshot(before_open):
            return None, "release_receipt_changed_during_read"
    except OSError:
        return None, "release_receipt_invalid"
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    duplicate_key = False

    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        nonlocal duplicate_key
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                duplicate_key = True
            result[key] = value
        return result

    def reject_constant(_value: str) -> None:
        raise ValueError

    try:
        payload: Any = json.loads(
            b"".join(chunks).decode("utf-8"),
            object_pairs_hook=object_pairs,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, ValueError):
        return None, "release_receipt_invalid"
    if duplicate_key or type(payload) is not dict:
        return None, "release_receipt_invalid"
    return dict(payload), ""


def _expected_voice_bindings(
    *,
    expected_voice_config_sha256: str,
    expected_voice_manifest_sha256: str,
    expected_voice_reference_aggregate_sha256: str,
    expected_provider_voice_id_sha256: str,
    expected_tts_provider: str,
    expected_tts_model: str,
) -> dict[str, str] | None:
    values = {
        "voice_config_sha256": expected_voice_config_sha256,
        "voice_manifest_sha256": expected_voice_manifest_sha256,
        "voice_reference_aggregate_sha256": (
            expected_voice_reference_aggregate_sha256
        ),
        "provider_voice_id_sha256": expected_provider_voice_id_sha256,
    }
    if any(not valid_sha256(value) for value in values.values()):
        return None
    if (
        expected_tts_provider != MANFRED_TTS_PROVIDER
        or expected_tts_model != MANFRED_TTS_MODEL
    ):
        return None
    return {
        **values,
        "tts_provider": expected_tts_provider,
        "tts_model": expected_tts_model,
    }


def _evaluate_manfred_public_evaluation_payload(
    *,
    payload: dict[str, object],
    expected_source_revision: str,
    expected_public_origin: str,
    expected_image_id: str,
    expected_voice_config_sha256: str,
    expected_voice_manifest_sha256: str,
    expected_voice_reference_aggregate_sha256: str,
    expected_provider_voice_id_sha256: str,
    expected_tts_provider: str,
    expected_tts_model: str,
    trusted_public_key_path: str | Path | None,
    now: float | None,
) -> dict[str, object]:
    receipt_status = (
        payload.get("status") if isinstance(payload.get("status"), str) else ""
    )
    if set(payload) != MANFRED_VOICE_PUBLIC_EVALUATION_FIELDS:
        return _blocked(
            "public_evaluation_receipt_fields_mismatch",
            receipt_status=receipt_status,
        )
    try:
        verify_signed_receipt(
            payload,
            trusted_public_key_path=trusted_public_key_path,
        )
    except ManfredVoiceSignatureError:
        return _blocked(
            "public_evaluation_receipt_signature_invalid",
            receipt_status=receipt_status,
        )

    if not _source_revision(expected_source_revision):
        return _blocked(
            "release_runtime_revision_missing", receipt_status=receipt_status
        )
    expected_origin = _canonical_public_origin(expected_public_origin)
    if not expected_origin:
        return _blocked(
            "release_runtime_public_origin_missing", receipt_status=receipt_status
        )
    if not valid_image_id(expected_image_id):
        return _blocked(
            "release_runtime_image_id_missing", receipt_status=receipt_status
        )
    expected_voice = _expected_voice_bindings(
        expected_voice_config_sha256=expected_voice_config_sha256,
        expected_voice_manifest_sha256=expected_voice_manifest_sha256,
        expected_voice_reference_aggregate_sha256=(
            expected_voice_reference_aggregate_sha256
        ),
        expected_provider_voice_id_sha256=expected_provider_voice_id_sha256,
        expected_tts_provider=expected_tts_provider,
        expected_tts_model=expected_tts_model,
    )
    if expected_voice is None:
        return _blocked(
            "release_runtime_voice_identity_missing",
            receipt_status=receipt_status,
        )

    if (
        payload.get("contract_name")
        != MANFRED_VOICE_PUBLIC_EVALUATION_CONTRACT
        or payload.get("generated_by")
        != MANFRED_VOICE_PUBLIC_EVALUATION_GENERATOR
        or payload.get("memorial_slug") != "manfred"
    ):
        return _blocked(
            "public_evaluation_receipt_contract_mismatch",
            receipt_status=receipt_status,
        )
    generated_at = _parse_timestamp(payload.get("generated_at"))
    expires_at = _parse_timestamp(payload.get("expires_at"))
    checked_at = time.time() if now is None else float(now)
    if (
        generated_at is None
        or expires_at is None
        or generated_at > checked_at + MAX_FUTURE_SKEW_SECONDS
        or expires_at <= generated_at
        or (
            expires_at - generated_at
            > MANFRED_VOICE_PUBLIC_EVALUATION_MAX_SECONDS
            + MAX_FUTURE_SKEW_SECONDS
        )
    ):
        return _blocked(
            "public_evaluation_receipt_timestamp_invalid",
            receipt_status=receipt_status,
        )
    if expires_at <= checked_at:
        return _blocked(
            "public_evaluation_expired", receipt_status=receipt_status
        )

    source_revision = payload.get("source_revision")
    if (
        not _source_revision(source_revision)
        or payload.get("source_git_head") != source_revision
        or payload.get("head_semantics") != "source_state"
    ):
        return _blocked(
            "release_receipt_source_binding_invalid",
            receipt_status=receipt_status,
        )
    if source_revision != expected_source_revision:
        return _blocked(
            "release_receipt_source_revision_mismatch",
            receipt_status=receipt_status,
        )
    if (
        not _source_revision(payload.get("baseline_readiness_source_revision"))
        or payload.get("baseline_readiness_same_source_revision")
        is not (
            payload.get("baseline_readiness_source_revision")
            == source_revision
        )
        or not valid_sha256(payload.get("source_state_fingerprint"))
        or payload.get("source_state_fingerprint_semantics")
        != "worktree_source_files_sha256_excluding_generated_only_paths"
    ):
        return _blocked(
            "public_evaluation_source_evidence_invalid",
            receipt_status=receipt_status,
        )
    expected_deployed_digest = hashlib.sha256(
        expected_source_revision.encode("ascii")
    ).hexdigest()
    if (
        payload.get("deployed_source_sha256") != expected_deployed_digest
        or payload.get("deployed_source_sha256_semantics")
        != "sha256_ascii_source_revision"
    ):
        return _blocked(
            "release_receipt_deployed_source_digest_invalid",
            receipt_status=receipt_status,
        )

    public_origin = _canonical_public_origin(payload.get("public_origin"))
    if not public_origin:
        return _blocked(
            "release_receipt_public_origin_invalid",
            receipt_status=receipt_status,
        )
    if public_origin != expected_origin:
        return _blocked(
            "release_receipt_public_origin_mismatch",
            receipt_status=receipt_status,
        )
    if (
        payload.get("image_id") != expected_image_id
        or payload.get("image_id_semantics") != IMAGE_ID_SEMANTICS
    ):
        return _blocked(
            "release_receipt_image_id_mismatch", receipt_status=receipt_status
        )

    observed_voice = {
        field: payload.get(field)
        for field in (
            "voice_config_sha256",
            "voice_manifest_sha256",
            "voice_reference_aggregate_sha256",
            "provider_voice_id_sha256",
            "tts_provider",
            "tts_model",
        )
    }
    if observed_voice != expected_voice:
        return _blocked(
            "release_receipt_voice_identity_mismatch",
            receipt_status=receipt_status,
        )
    if (
        payload.get("voice_artifact_digest_semantics")
        != VOICE_ARTIFACT_DIGEST_SEMANTICS
        or payload.get("voice_reference_aggregate_sha256_semantics")
        != VOICE_REFERENCE_AGGREGATE_SHA256_SEMANTICS
        or payload.get("provider_voice_id_sha256_semantics")
        != PROVIDER_VOICE_ID_SHA256_SEMANTICS
        or payload.get("voice_identity_sha256_semantics")
        != VOICE_IDENTITY_SHA256_SEMANTICS
    ):
        return _blocked(
            "release_receipt_voice_identity_semantics_invalid",
            receipt_status=receipt_status,
        )
    try:
        expected_identity = voice_identity_sha256(**expected_voice)
    except ManfredVoiceSignatureError:
        return _blocked(
            "release_runtime_voice_identity_missing",
            receipt_status=receipt_status,
        )
    if payload.get("voice_identity_sha256") != expected_identity:
        return _blocked(
            "release_receipt_voice_identity_digest_invalid",
            receipt_status=receipt_status,
        )

    blocked_checks = payload.get("blocked_checks")
    unverified_evidence = payload.get("unverified_evidence_keys")
    unverified_manual = payload.get("unverified_manual_check_ids")
    if (
        type(blocked_checks) is not list
        or not blocked_checks
        or any(type(item) is not str for item in blocked_checks)
        or len(blocked_checks) != len(set(blocked_checks))
        or any(
            item not in MANFRED_VOICE_PUBLIC_EVALUATION_BLOCKERS
            for item in blocked_checks
        )
        or type(unverified_evidence) is not list
        or not unverified_evidence
        or any(type(item) is not str for item in unverified_evidence)
        or len(unverified_evidence) != len(set(unverified_evidence))
        or any(
            item not in MANFRED_VOICE_PUBLIC_EVALUATION_EVIDENCE_KEYS
            for item in unverified_evidence
        )
        or unverified_manual
        != list(MANFRED_VOICE_PUBLIC_EVALUATION_MANUAL_CHECK_IDS)
    ):
        return _blocked(
            "public_evaluation_unverified_checks_invalid",
            receipt_status=receipt_status,
        )

    required_false = (
        "goal_completion_claim_allowed",
        "native_realtime_claim_allowed",
        "operator_acceptance_verified",
        "premium_spoken_claim_allowed",
        "readiness_prerequisites_satisfied",
        "realtime_conversation_claim_allowed",
        "room_and_spoken_turn_checks_verified",
        "spoken_turn_claim_allowed",
    )
    required_true = (
        "conversational_use_authorized",
        "public_evaluation_allowed",
        "public_evaluation_disclosure_required",
        "public_synthetic_voice_authorized",
        "baseline_readiness_receipt_contract_verified",
        "runtime_enablement_allowed",
        "source_material_authorized",
        "voice_authority_verified",
    )
    if (
        receipt_status != "public_evaluation_authorized"
        or payload.get("release_mode")
        != MANFRED_VOICE_PUBLIC_EVALUATION_MODE
        or payload.get("baseline_readiness_status")
        != "blocked_realtime_prerequisites"
        or any(payload.get(field) is not False for field in required_false)
        or any(payload.get(field) is not True for field in required_true)
        or payload.get("revoked") is not False
        or payload.get("voice_authority_revoked") is not False
    ):
        return _blocked(
            "public_evaluation_state_invalid", receipt_status=receipt_status
        )

    statement_sha256 = hashlib.sha256(
        MANFRED_VOICE_PUBLIC_EVALUATION_CONFIRMATION.encode("utf-8")
    ).hexdigest()
    if (
        payload.get("authorization_scope")
        != MANFRED_VOICE_PUBLIC_EVALUATION_AUTHORIZATION_SCOPE
        or not valid_sha256(payload.get("authorization_ref_sha256"))
        or payload.get("authorization_ref_sha256_semantics")
        != PUBLIC_EVALUATION_AUTHORIZATION_REF_SHA256_SEMANTICS
        or payload.get("authorization_statement_sha256") != statement_sha256
        or payload.get("authorization_statement_sha256_semantics")
        != PUBLIC_EVALUATION_STATEMENT_SHA256_SEMANTICS
    ):
        return _blocked(
            "public_evaluation_authorization_invalid",
            receipt_status=receipt_status,
        )
    if (
        payload.get("input_digest_semantics") != "sha256_exact_input_bytes"
        or not valid_sha256(
            payload.get("baseline_readiness_receipt_sha256")
        )
        or not valid_sha256(payload.get("voice_authority_receipt_sha256"))
    ):
        return _blocked(
            "release_digest_binding_missing", receipt_status=receipt_status
        )
    if (
        payload.get("signature_algorithm") != SIGNATURE_ALGORITHM
        or payload.get("signature_scope") != SIGNATURE_SCOPE
    ):
        return _blocked(
            "public_evaluation_receipt_signature_invalid",
            receipt_status=receipt_status,
        )

    return {
        "allowed": False,
        "public_evaluation": True,
        "status": "public_evaluation",
        "reason": "",
        "receipt_status": receipt_status,
        "access_mode": MANFRED_VOICE_PUBLIC_EVALUATION_ACCESS_MODE,
        "disclosure_required": True,
    }


def evaluate_memorial_voice_release_payload(
    *,
    slug: str,
    payload: dict[str, object],
    expected_source_revision: str = "",
    expected_public_origin: str = "",
    expected_image_id: str = "",
    expected_voice_config_sha256: str = "",
    expected_voice_manifest_sha256: str = "",
    expected_voice_reference_aggregate_sha256: str = "",
    expected_provider_voice_id_sha256: str = "",
    expected_tts_provider: str = "",
    expected_tts_model: str = "",
    trusted_public_key_path: str | Path | None = None,
    now: float | None = None,
) -> dict[str, object]:
    """Evaluate the signed, durable Manfred voice-release transition."""

    if not isinstance(slug, str) or slug.strip().lower() != "manfred":
        return _blocked("release_receipt_not_configured")
    if (
        payload.get("contract_name")
        == MANFRED_VOICE_PUBLIC_EVALUATION_CONTRACT
    ):
        return _evaluate_manfred_public_evaluation_payload(
            payload=payload,
            expected_source_revision=expected_source_revision,
            expected_public_origin=expected_public_origin,
            expected_image_id=expected_image_id,
            expected_voice_config_sha256=expected_voice_config_sha256,
            expected_voice_manifest_sha256=expected_voice_manifest_sha256,
            expected_voice_reference_aggregate_sha256=(
                expected_voice_reference_aggregate_sha256
            ),
            expected_provider_voice_id_sha256=(
                expected_provider_voice_id_sha256
            ),
            expected_tts_provider=expected_tts_provider,
            expected_tts_model=expected_tts_model,
            trusted_public_key_path=trusted_public_key_path,
            now=now,
        )
    normalized_slug = "manfred"
    receipt_status = (
        payload.get("status") if isinstance(payload.get("status"), str) else ""
    )

    if set(payload) != MANFRED_VOICE_RELEASE_FIELDS:
        return _blocked(
            "release_receipt_fields_mismatch", receipt_status=receipt_status
        )
    if payload.get("contract_name") != MANFRED_VOICE_RELEASE_CONTRACT:
        return _blocked(
            "release_receipt_contract_mismatch", receipt_status=receipt_status
        )
    try:
        verify_signed_receipt(
            payload,
            trusted_public_key_path=trusted_public_key_path,
        )
    except ManfredVoiceSignatureError:
        return _blocked(
            "release_receipt_signature_invalid", receipt_status=receipt_status
        )

    if not _source_revision(expected_source_revision):
        return _blocked(
            "release_runtime_revision_missing", receipt_status=receipt_status
        )
    expected_origin = _canonical_public_origin(expected_public_origin)
    if not expected_origin:
        return _blocked(
            "release_runtime_public_origin_missing", receipt_status=receipt_status
        )
    if not valid_image_id(expected_image_id):
        return _blocked(
            "release_runtime_image_id_missing", receipt_status=receipt_status
        )
    expected_voice = _expected_voice_bindings(
        expected_voice_config_sha256=expected_voice_config_sha256,
        expected_voice_manifest_sha256=expected_voice_manifest_sha256,
        expected_voice_reference_aggregate_sha256=(
            expected_voice_reference_aggregate_sha256
        ),
        expected_provider_voice_id_sha256=expected_provider_voice_id_sha256,
        expected_tts_provider=expected_tts_provider,
        expected_tts_model=expected_tts_model,
    )
    if expected_voice is None:
        return _blocked(
            "release_runtime_voice_identity_missing", receipt_status=receipt_status
        )

    if payload.get("generated_by") != MANFRED_VOICE_RELEASE_GENERATOR:
        return _blocked(
            "release_receipt_generator_mismatch", receipt_status=receipt_status
        )
    if payload.get("memorial_slug") != normalized_slug:
        return _blocked("release_receipt_slug_unbound", receipt_status=receipt_status)
    generated_at = _parse_timestamp(payload.get("generated_at"))
    checked_at = time.time() if now is None else float(now)
    if generated_at is None or generated_at > checked_at + MAX_FUTURE_SKEW_SECONDS:
        return _blocked(
            "release_receipt_timestamp_invalid", receipt_status=receipt_status
        )

    source_revision = payload.get("source_revision")
    if (
        not _source_revision(source_revision)
        or payload.get("source_git_head") != source_revision
        or payload.get("head_semantics") != "source_state"
    ):
        return _blocked(
            "release_receipt_source_binding_invalid", receipt_status=receipt_status
        )
    if source_revision != expected_source_revision:
        return _blocked(
            "release_receipt_source_revision_mismatch",
            receipt_status=receipt_status,
        )
    if (
        not valid_sha256(payload.get("source_state_fingerprint"))
        or payload.get("source_state_fingerprint_semantics")
        != "worktree_source_files_sha256_excluding_generated_only_paths"
    ):
        return _blocked(
            "release_receipt_source_fingerprint_invalid",
            receipt_status=receipt_status,
        )
    expected_deployed_digest = hashlib.sha256(
        expected_source_revision.encode("ascii")
    ).hexdigest()
    if (
        payload.get("deployed_source_sha256") != expected_deployed_digest
        or payload.get("deployed_source_sha256_semantics")
        != "sha256_ascii_source_revision"
    ):
        return _blocked(
            "release_receipt_deployed_source_digest_invalid",
            receipt_status=receipt_status,
        )

    public_origin = _canonical_public_origin(payload.get("public_origin"))
    if not public_origin:
        return _blocked(
            "release_receipt_public_origin_invalid", receipt_status=receipt_status
        )
    if public_origin != expected_origin:
        return _blocked(
            "release_receipt_public_origin_mismatch", receipt_status=receipt_status
        )
    if (
        payload.get("image_id") != expected_image_id
        or payload.get("image_id_semantics") != IMAGE_ID_SEMANTICS
    ):
        return _blocked(
            "release_receipt_image_id_mismatch", receipt_status=receipt_status
        )

    observed_voice = {
        field: payload.get(field)
        for field in (
            "voice_config_sha256",
            "voice_manifest_sha256",
            "voice_reference_aggregate_sha256",
            "provider_voice_id_sha256",
            "tts_provider",
            "tts_model",
        )
    }
    if observed_voice != expected_voice:
        return _blocked(
            "release_receipt_voice_identity_mismatch",
            receipt_status=receipt_status,
        )
    if (
        payload.get("voice_artifact_digest_semantics")
        != VOICE_ARTIFACT_DIGEST_SEMANTICS
        or payload.get("voice_reference_aggregate_sha256_semantics")
        != VOICE_REFERENCE_AGGREGATE_SHA256_SEMANTICS
        or payload.get("provider_voice_id_sha256_semantics")
        != PROVIDER_VOICE_ID_SHA256_SEMANTICS
        or payload.get("voice_identity_sha256_semantics")
        != VOICE_IDENTITY_SHA256_SEMANTICS
    ):
        return _blocked(
            "release_receipt_voice_identity_semantics_invalid",
            receipt_status=receipt_status,
        )
    try:
        expected_identity = voice_identity_sha256(**expected_voice)
    except ManfredVoiceSignatureError:
        return _blocked(
            "release_runtime_voice_identity_missing", receipt_status=receipt_status
        )
    if payload.get("voice_identity_sha256") != expected_identity:
        return _blocked(
            "release_receipt_voice_identity_digest_invalid",
            receipt_status=receipt_status,
        )

    blocked_checks = payload.get("blocked_checks")
    if (
        receipt_status != "released"
        or payload.get("readiness_status") != "ready_for_spoken_turn_release"
        or type(blocked_checks) is not list
        or blocked_checks != []
    ):
        return _blocked("release_prerequisites_blocked", receipt_status=receipt_status)

    required_true = (
        "readiness_verified",
        "operator_acceptance_verified",
        "room_and_spoken_turn_checks_verified",
        "runtime_enablement_allowed",
        "voice_authority_verified",
        "public_synthetic_voice_authorized",
        "conversational_use_authorized",
        "source_material_authorized",
        "spoken_turn_claim_allowed",
        "premium_spoken_claim_allowed",
    )
    if (
        any(payload.get(field) is not True for field in required_true)
        or payload.get("operator_acceptance_review_surface")
        != MANFRED_PHASE_1_LIVE_REVIEW_SURFACE
        or payload.get("voice_authority_revoked") is not False
        or payload.get("native_realtime_claim_allowed") is not False
    ):
        return _blocked(
            "release_human_acceptance_missing", receipt_status=receipt_status
        )

    digest_bindings = (
        "readiness_receipt_sha256",
        "operator_acceptance_receipt_sha256",
        "voice_authority_receipt_sha256",
    )
    if (
        payload.get("input_digest_semantics") != "sha256_exact_input_bytes"
        or any(not valid_sha256(payload.get(field)) for field in digest_bindings)
    ):
        return _blocked("release_digest_binding_missing", receipt_status=receipt_status)
    if (
        payload.get("signature_algorithm") != SIGNATURE_ALGORITHM
        or payload.get("signature_scope") != SIGNATURE_SCOPE
    ):
        return _blocked(
            "release_receipt_signature_invalid", receipt_status=receipt_status
        )

    return {
        "allowed": True,
        "status": "released",
        "reason": "",
        "receipt_status": receipt_status,
    }


def evaluate_memorial_voice_release(
    *,
    slug: str,
    receipt_path: str | Path,
    expected_source_revision: str = "",
    expected_public_origin: str = "",
    expected_image_id: str = "",
    expected_voice_config_sha256: str = "",
    expected_voice_manifest_sha256: str = "",
    expected_voice_reference_aggregate_sha256: str = "",
    expected_provider_voice_id_sha256: str = "",
    expected_tts_provider: str = "",
    expected_tts_model: str = "",
    trusted_public_key_path: str | Path | None = None,
    now: float | None = None,
) -> dict[str, object]:
    """Evaluate a stable owner-controlled final voice-release receipt."""

    if not isinstance(slug, str) or slug.strip().lower() != "manfred":
        return _blocked("release_receipt_not_configured")
    payload, error = _read_release_receipt(Path(receipt_path))
    if payload is None:
        return _blocked(error)
    return evaluate_memorial_voice_release_payload(
        slug="manfred",
        payload=payload,
        expected_source_revision=expected_source_revision,
        expected_public_origin=expected_public_origin,
        expected_image_id=expected_image_id,
        expected_voice_config_sha256=expected_voice_config_sha256,
        expected_voice_manifest_sha256=expected_voice_manifest_sha256,
        expected_voice_reference_aggregate_sha256=(
            expected_voice_reference_aggregate_sha256
        ),
        expected_provider_voice_id_sha256=expected_provider_voice_id_sha256,
        expected_tts_provider=expected_tts_provider,
        expected_tts_model=expected_tts_model,
        trusted_public_key_path=trusted_public_key_path,
        now=now,
    )
