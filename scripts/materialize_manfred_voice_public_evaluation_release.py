#!/usr/bin/env python3
"""Materialize a signed, explicitly limited Manfred public-evaluation release."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
EA_ROOT = REPO_ROOT / "ea"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(EA_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_ROOT))

from app.services.manfred_voice_signing import (  # noqa: E402
    IMAGE_ID_SEMANTICS,
    MANFRED_TTS_MODEL,
    MANFRED_TTS_PROVIDER,
    ManfredVoiceSignatureError,
    public_key_id,
    sign_receipt,
    valid_image_id,
    valid_sha256,
)
from app.services.memorial_release_policy import (  # noqa: E402
    MANFRED_VOICE_PUBLIC_EVALUATION_AUTHORIZATION_SCOPE,
    MANFRED_VOICE_PUBLIC_EVALUATION_BLOCKERS,
    MANFRED_VOICE_PUBLIC_EVALUATION_CONFIRMATION,
    MANFRED_VOICE_PUBLIC_EVALUATION_CONTRACT,
    MANFRED_VOICE_PUBLIC_EVALUATION_EVIDENCE_KEYS,
    MANFRED_VOICE_PUBLIC_EVALUATION_GENERATOR,
    MANFRED_VOICE_PUBLIC_EVALUATION_MANUAL_CHECK_IDS,
    MANFRED_VOICE_PUBLIC_EVALUATION_MAX_SECONDS,
    MANFRED_VOICE_PUBLIC_EVALUATION_MODE,
    PUBLIC_EVALUATION_AUTHORIZATION_REF_SHA256_SEMANTICS as POLICY_AUTHORIZATION_REF_SHA256_SEMANTICS,
    PUBLIC_EVALUATION_STATEMENT_SHA256_SEMANTICS as POLICY_STATEMENT_SHA256_SEMANTICS,
)
from scripts.materialize_manfred_voice_release import (  # noqa: E402
    MEMORIAL_SLUG,
    READINESS_CONTRACT,
    READINESS_EVIDENCE_KEYS,
    READINESS_GENERATOR,
    READINESS_MAX_AGE_SECONDS,
    ROOM_AND_SPOKEN_TURN_CHECK_IDS,
    SOURCE_FINGERPRINT_SEMANTICS,
    VoiceReleaseError,
    _assert_no_forbidden_raw_fields,
    _canonical_public_origin,
    _canonical_utc_now,
    _expected_voice_binding,
    _read_private_receipt,
    _read_signing_private_key,
    _timestamp as _validate_timestamp,
    _trusted_public_keys_with_identity,
    _valid_source_revision,
    _validate_voice_authority,
    _write_private_atomic,
)
from scripts.source_state_head import (  # noqa: E402
    resolve_source_worktree_fingerprint,
    source_worktree_metadata,
)


PUBLIC_EVALUATION_RELEASE_CONTRACT = (
    MANFRED_VOICE_PUBLIC_EVALUATION_CONTRACT
)
PUBLIC_EVALUATION_RELEASE_GENERATOR = (
    MANFRED_VOICE_PUBLIC_EVALUATION_GENERATOR
)
PUBLIC_EVALUATION_RELEASE_MODE = MANFRED_VOICE_PUBLIC_EVALUATION_MODE
PUBLIC_EVALUATION_RELEASE_STATUS = "public_evaluation_authorized"
PUBLIC_EVALUATION_AUTHORIZATION_SCOPE = (
    MANFRED_VOICE_PUBLIC_EVALUATION_AUTHORIZATION_SCOPE
)
PUBLIC_EVALUATION_AUTHORIZATION_REF_SHA256_SEMANTICS = (
    POLICY_AUTHORIZATION_REF_SHA256_SEMANTICS
)
PUBLIC_EVALUATION_AUTHORIZATION_STATEMENT_SHA256_SEMANTICS = (
    POLICY_STATEMENT_SHA256_SEMANTICS
)
PUBLIC_EVALUATION_CONFIRMATION = (
    MANFRED_VOICE_PUBLIC_EVALUATION_CONFIRMATION
)
PUBLIC_EVALUATION_DURATION = timedelta(
    seconds=MANFRED_VOICE_PUBLIC_EVALUATION_MAX_SECONDS
)

EXPECTED_READINESS_PRIVACY = {
    "candidate_raw_text_fields": False,
    "raw_private_context_exposed": False,
    "raw_transcript_fields": False,
    "redacted_text_fields": True,
}
EVIDENCE_CURRENT_FIELDS = (
    "present",
    "contract_valid",
    "fresh",
    "source_state_matches_current",
)
EVIDENCE_PRIVACY_FIELDS = (
    "raw_private_context_exposed",
    "raw_transcript_fields_exposed",
    "raw_credentials_exposed",
    "raw_receipt_payload_exposed",
)


def _utc_timestamp(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _canonical_check_ids(
    value: object,
    *,
    label: str,
    allow_empty: bool = False,
) -> list[str]:
    if type(value) is not list:
        raise VoiceReleaseError(f"{label}_invalid")
    result: list[str] = []
    for item in value:
        if (
            not isinstance(item, str)
            or not item
            or item != item.strip()
            or len(item) > 128
            or not item.replace("_", "").replace("-", "").isalnum()
        ):
            raise VoiceReleaseError(f"{label}_invalid")
        result.append(item)
    if len(result) != len(set(result)):
        raise VoiceReleaseError(f"{label}_duplicate")
    if not allow_empty and not result:
        raise VoiceReleaseError(f"{label}_missing")
    return result


def _validate_blocked_public_evaluation_readiness(
    receipt: dict[str, Any],
    *,
    now: datetime,
) -> tuple[str, list[str], list[str]]:
    if receipt.get("contract_name") != READINESS_CONTRACT:
        raise VoiceReleaseError("readiness_contract_mismatch")
    if receipt.get("generated_by") != READINESS_GENERATOR:
        raise VoiceReleaseError("readiness_generator_mismatch")
    _validate_timestamp(
        receipt.get("generated_at"),
        field="readiness_generated_at",
        now=now,
        max_age_seconds=READINESS_MAX_AGE_SECONDS,
    )
    if receipt.get("evidence_source") != "receipt_aggregation":
        raise VoiceReleaseError("readiness_evidence_source_invalid")
    if receipt.get("status") != "blocked_realtime_prerequisites":
        raise VoiceReleaseError("readiness_evaluation_status_invalid")
    if receipt.get("ready_for_realtime_conversation_review") is not False:
        raise VoiceReleaseError("readiness_evaluation_flag_invalid")

    blocked_checks = _canonical_check_ids(
        receipt.get("blocked_checks"),
        label="readiness_blocked_checks",
    )
    if any(
        check_id not in MANFRED_VOICE_PUBLIC_EVALUATION_BLOCKERS
        for check_id in blocked_checks
    ):
        raise VoiceReleaseError(
            "readiness_blocked_checks_unsupported"
        )
    baseline_readiness_source_revision = receipt.get("source_git_head")
    if not _valid_source_revision(baseline_readiness_source_revision):
        raise VoiceReleaseError("readiness_source_revision_invalid")
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
            raise VoiceReleaseError(
                f"readiness_evaluation_claim_invalid:{field}"
            )
    if receipt.get("privacy") != EXPECTED_READINESS_PRIVACY:
        raise VoiceReleaseError("readiness_privacy_invalid")

    raw_evidence = receipt.get("input_evidence")
    if (
        type(raw_evidence) is not dict
        or set(raw_evidence) != READINESS_EVIDENCE_KEYS
    ):
        raise VoiceReleaseError("readiness_input_evidence_incomplete")
    unverified_evidence: list[str] = []
    for key in sorted(READINESS_EVIDENCE_KEYS):
        row = raw_evidence.get(key)
        if type(row) is not dict:
            raise VoiceReleaseError(
                f"readiness_input_evidence_invalid:{key}"
            )
        if any(type(row.get(field)) is not bool for field in EVIDENCE_CURRENT_FIELDS):
            raise VoiceReleaseError(
                f"readiness_input_evidence_type_invalid:{key}"
            )
        for field in EVIDENCE_PRIVACY_FIELDS:
            if row.get(field) is not False:
                raise VoiceReleaseError(
                    f"readiness_input_evidence_privacy_invalid:{key}:{field}"
                )

        present = row.get("present") is True
        current = all(row.get(field) is True for field in EVIDENCE_CURRENT_FIELDS)
        receipt_sha256 = row.get("receipt_sha256")
        if present:
            if not valid_sha256(receipt_sha256):
                raise VoiceReleaseError(
                    f"readiness_input_evidence_digest_invalid:{key}"
                )
        elif (
            receipt_sha256 != ""
            or row.get("contract_valid") is not False
            or row.get("fresh") is not False
            or row.get("source_state_matches_current") is not False
        ):
            raise VoiceReleaseError(
                f"readiness_input_evidence_missing_inconsistent:{key}"
            )
        if not current:
            unverified_evidence.append(key)

    if not unverified_evidence:
        raise VoiceReleaseError(
            "readiness_unverified_evidence_missing"
        )
    if any(
        key not in MANFRED_VOICE_PUBLIC_EVALUATION_EVIDENCE_KEYS
        for key in unverified_evidence
    ):
        raise VoiceReleaseError(
            "readiness_unverified_evidence_unsupported"
        )
    _assert_no_forbidden_raw_fields(receipt, label="readiness")
    return (
        str(baseline_readiness_source_revision),
        blocked_checks,
        unverified_evidence,
    )


def _current_source_fingerprint(source_revision: str) -> str:
    try:
        head = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD^{commit}"],
            cwd=REPO_ROOT,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise VoiceReleaseError(
            "public_evaluation_source_revision_unverifiable"
        ) from exc
    if head != source_revision:
        raise VoiceReleaseError(
            "public_evaluation_source_revision_mismatch"
        )
    worktree = source_worktree_metadata(REPO_ROOT)
    if worktree.get("source_worktree_dirty") is not False:
        raise VoiceReleaseError(
            "public_evaluation_source_worktree_dirty"
        )
    fingerprint = resolve_source_worktree_fingerprint(REPO_ROOT)
    if not valid_sha256(fingerprint):
        raise VoiceReleaseError(
            "public_evaluation_source_fingerprint_invalid"
        )
    return fingerprint


def materialize_manfred_voice_public_evaluation_release(
    *,
    readiness_receipt_path: str | Path,
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
    authorization_ref_sha256: str,
    confirmation: str,
    trusted_public_key_path: str | Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if confirmation != PUBLIC_EVALUATION_CONFIRMATION:
        raise VoiceReleaseError(
            "public_evaluation_confirmation_missing"
        )
    if not valid_sha256(authorization_ref_sha256):
        raise VoiceReleaseError(
            "public_evaluation_authorization_ref_invalid"
        )
    if not _valid_source_revision(source_revision):
        raise VoiceReleaseError("source_revision_invalid")
    canonical_origin = _canonical_public_origin(public_origin)
    if not canonical_origin or canonical_origin != public_origin:
        raise VoiceReleaseError("public_origin_invalid")
    if not valid_image_id(image_id):
        raise VoiceReleaseError("image_id_invalid")
    if (
        tts_provider != MANFRED_TTS_PROVIDER
        or tts_model != MANFRED_TTS_MODEL
    ):
        raise VoiceReleaseError(
            "public_evaluation_tts_identity_invalid"
        )
    if tuple(MANFRED_VOICE_PUBLIC_EVALUATION_MANUAL_CHECK_IDS) != tuple(
        ROOM_AND_SPOKEN_TURN_CHECK_IDS
    ):
        raise VoiceReleaseError(
            "public_evaluation_manual_check_contract_mismatch"
        )
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

    observed_at = _canonical_utc_now(now).replace(microsecond=0)
    expires_at = observed_at + PUBLIC_EVALUATION_DURATION
    readiness, readiness_raw, readiness_identity = _read_private_receipt(
        readiness_receipt_path,
        label="readiness_receipt",
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

    (
        baseline_readiness_source_revision,
        blocked_checks,
        unverified_evidence,
    ) = _validate_blocked_public_evaluation_readiness(
        readiness,
        now=observed_at,
    )
    source_fingerprint = _current_source_fingerprint(source_revision)
    _validate_voice_authority(
        voice_authority,
        voice_binding=voice_binding,
        now=observed_at,
        trusted_public_key_path=trusted_public_key_path,
    )

    confirmation_sha256 = hashlib.sha256(
        PUBLIC_EVALUATION_CONFIRMATION.encode("utf-8")
    ).hexdigest()
    unsigned_release: dict[str, object] = {
        "authorization_ref_sha256": authorization_ref_sha256,
        "authorization_ref_sha256_semantics": (
            PUBLIC_EVALUATION_AUTHORIZATION_REF_SHA256_SEMANTICS
        ),
        "authorization_scope": PUBLIC_EVALUATION_AUTHORIZATION_SCOPE,
        "authorization_statement_sha256": confirmation_sha256,
        "authorization_statement_sha256_semantics": (
            PUBLIC_EVALUATION_AUTHORIZATION_STATEMENT_SHA256_SEMANTICS
        ),
        "blocked_checks": blocked_checks,
        "contract_name": PUBLIC_EVALUATION_RELEASE_CONTRACT,
        "conversational_use_authorized": True,
        "deployed_source_sha256": hashlib.sha256(
            source_revision.encode("ascii")
        ).hexdigest(),
        "deployed_source_sha256_semantics": "sha256_ascii_source_revision",
        "expires_at": _utc_timestamp(expires_at),
        "generated_at": _utc_timestamp(observed_at),
        "generated_by": PUBLIC_EVALUATION_RELEASE_GENERATOR,
        "goal_completion_claim_allowed": False,
        "head_semantics": "source_state",
        "image_id": image_id,
        "image_id_semantics": IMAGE_ID_SEMANTICS,
        "input_digest_semantics": "sha256_exact_input_bytes",
        "memorial_slug": MEMORIAL_SLUG,
        "native_realtime_claim_allowed": False,
        "operator_acceptance_verified": False,
        "premium_spoken_claim_allowed": False,
        "public_evaluation_allowed": True,
        "public_evaluation_disclosure_required": True,
        "public_origin": canonical_origin,
        "public_synthetic_voice_authorized": True,
        "baseline_readiness_receipt_contract_verified": True,
        "baseline_readiness_receipt_sha256": hashlib.sha256(
            readiness_raw
        ).hexdigest(),
        "baseline_readiness_same_source_revision": (
            baseline_readiness_source_revision == source_revision
        ),
        "baseline_readiness_source_revision": (
            baseline_readiness_source_revision
        ),
        "baseline_readiness_status": "blocked_realtime_prerequisites",
        "readiness_prerequisites_satisfied": False,
        "realtime_conversation_claim_allowed": False,
        "release_mode": PUBLIC_EVALUATION_RELEASE_MODE,
        "revoked": False,
        "room_and_spoken_turn_checks_verified": False,
        "runtime_enablement_allowed": True,
        "source_git_head": source_revision,
        "source_material_authorized": True,
        "source_revision": source_revision,
        "source_state_fingerprint": source_fingerprint,
        "source_state_fingerprint_semantics": SOURCE_FINGERPRINT_SEMANTICS,
        "spoken_turn_claim_allowed": False,
        "status": PUBLIC_EVALUATION_RELEASE_STATUS,
        "unverified_evidence_keys": unverified_evidence,
        "unverified_manual_check_ids": list(
            MANFRED_VOICE_PUBLIC_EVALUATION_MANUAL_CHECK_IDS
        ),
        "voice_authority_receipt_sha256": hashlib.sha256(
            authority_raw
        ).hexdigest(),
        "voice_authority_revoked": False,
        "voice_authority_verified": True,
        **voice_binding,
    }
    _assert_no_forbidden_raw_fields(
        unsigned_release,
        label="public_evaluation_release",
    )
    try:
        release = sign_receipt(unsigned_release, private_key=signing_key)
    except ManfredVoiceSignatureError as exc:
        raise VoiceReleaseError(str(exc)) from exc
    _assert_no_forbidden_raw_fields(
        release,
        label="public_evaluation_release",
    )

    input_identities = {
        readiness_identity,
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
            "Materialize a signed, seven-day Manfred public-evaluation "
            "release without converting blocked evidence into pass claims."
        )
    )
    parser.add_argument("--readiness-receipt", required=True)
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
    parser.add_argument("--authorization-ref-sha256", required=True)
    parser.add_argument("--confirmation", required=True)
    args = parser.parse_args(argv)
    try:
        release = materialize_manfred_voice_public_evaluation_release(
            readiness_receipt_path=args.readiness_receipt,
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
            authorization_ref_sha256=args.authorization_ref_sha256,
            confirmation=args.confirmation,
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
                "expires_at": release["expires_at"],
                "output": str(args.output),
                "status": release["status"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
