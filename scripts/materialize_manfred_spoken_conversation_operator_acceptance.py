#!/usr/bin/env python3
"""Materialize the human Manfred spoken-conversation acceptance receipt."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
EA_ROOT = REPO_ROOT / "ea"
if str(EA_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_ROOT))

from app.services.manfred_voice_signing import (  # noqa: E402
    IMAGE_ID_SEMANTICS,
    MANFRED_PHASE_1_LIVE_REVIEW_SURFACE,
    MANFRED_TTS_MODEL,
    MANFRED_TTS_PROVIDER,
    valid_image_id,
    valid_sha256,
)
from scripts.materialize_manfred_voice_release import (  # noqa: E402
    MEMORIAL_SLUG,
    OPERATOR_ACCEPTANCE_CONTRACT,
    REVIEWER_REF_SHA256_SEMANTICS,
    ROOM_AND_SPOKEN_TURN_CHECK_IDS,
    VoiceReleaseError,
    _assert_no_forbidden_raw_fields,
    _canonical_public_origin,
    _canonical_utc_now,
    _expected_voice_binding,
    _valid_source_revision,
    _validate_operator_acceptance,
    _write_private_atomic,
)


OPERATOR_ACCEPTANCE_CONFIRMATION = (
    "I reviewed Manfred's bound synthetic spoken conversation on the phase-1 "
    "live private-review surface and confirm all nine room and spoken-turn "
    "checks."
)


def _timestamp(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def materialize_manfred_spoken_conversation_operator_acceptance(
    *,
    output_path: str | Path,
    reviewer_ref_sha256: str,
    source_revision: str,
    public_origin: str,
    image_id: str,
    voice_config_sha256: str,
    voice_manifest_sha256: str,
    voice_reference_aggregate_sha256: str,
    provider_voice_id_sha256: str,
    tts_provider: str,
    tts_model: str,
    checks: dict[str, bool],
    confirmation: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    observed_at = _canonical_utc_now(now)
    if confirmation != OPERATOR_ACCEPTANCE_CONFIRMATION:
        raise VoiceReleaseError("operator_acceptance_confirmation_missing")
    if not valid_sha256(reviewer_ref_sha256):
        raise VoiceReleaseError("operator_acceptance_reviewer_ref_invalid")
    if not _valid_source_revision(source_revision):
        raise VoiceReleaseError("operator_acceptance_source_revision_invalid")
    canonical_origin = _canonical_public_origin(public_origin)
    if not canonical_origin or canonical_origin != public_origin:
        raise VoiceReleaseError("operator_acceptance_public_origin_invalid")
    if not valid_image_id(image_id):
        raise VoiceReleaseError("operator_acceptance_image_id_invalid")
    if (
        tts_provider != MANFRED_TTS_PROVIDER
        or tts_model != MANFRED_TTS_MODEL
    ):
        raise VoiceReleaseError("operator_acceptance_tts_identity_invalid")
    if (
        type(checks) is not dict
        or set(checks) != set(ROOM_AND_SPOKEN_TURN_CHECK_IDS)
    ):
        raise VoiceReleaseError("operator_acceptance_checks_invalid")
    for check_id in ROOM_AND_SPOKEN_TURN_CHECK_IDS:
        if checks.get(check_id) is not True:
            raise VoiceReleaseError(
                f"operator_acceptance_check_failed:{check_id}"
            )

    voice_binding = _expected_voice_binding(
        voice_config_sha256=voice_config_sha256,
        voice_manifest_sha256=voice_manifest_sha256,
        voice_reference_aggregate_sha256=voice_reference_aggregate_sha256,
        provider_voice_id_sha256=provider_voice_id_sha256,
        tts_provider=tts_provider,
        tts_model=tts_model,
    )
    receipt: dict[str, Any] = {
        "accepted": True,
        "checks": {
            check_id: True for check_id in ROOM_AND_SPOKEN_TURN_CHECK_IDS
        },
        "contract_name": OPERATOR_ACCEPTANCE_CONTRACT,
        "deployed_source_revision": source_revision,
        "generated_at": _timestamp(observed_at),
        "image_id": image_id,
        "image_id_semantics": IMAGE_ID_SEMANTICS,
        "memorial_slug": MEMORIAL_SLUG,
        "native_realtime_claim_accepted": False,
        "public_origin": canonical_origin,
        "review_surface": MANFRED_PHASE_1_LIVE_REVIEW_SURFACE,
        "reviewer_ref_sha256": reviewer_ref_sha256,
        "reviewer_ref_sha256_semantics": REVIEWER_REF_SHA256_SEMANTICS,
        "spoken_turn_claim_accepted": True,
        **voice_binding,
    }
    _assert_no_forbidden_raw_fields(
        receipt,
        label="operator_acceptance",
    )
    _validate_operator_acceptance(
        receipt,
        source_revision=source_revision,
        public_origin=canonical_origin,
        image_id=image_id,
        voice_binding=voice_binding,
        now=observed_at,
    )
    _write_private_atomic(
        output_path,
        receipt,
        input_identities=set(),
    )
    return receipt


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize the private human acceptance receipt for Manfred's "
            "source-, image-, origin-, and voice-bound spoken conversation."
        )
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reviewer-ref-sha256", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--public-origin", required=True)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--voice-config-sha256", required=True)
    parser.add_argument("--voice-manifest-sha256", required=True)
    parser.add_argument("--voice-reference-aggregate-sha256", required=True)
    parser.add_argument("--provider-voice-id-sha256", required=True)
    parser.add_argument("--tts-provider", required=True)
    parser.add_argument("--tts-model", required=True)
    parser.add_argument("--confirmation", required=True)
    for check_id in ROOM_AND_SPOKEN_TURN_CHECK_IDS:
        parser.add_argument(
            f"--confirm-{check_id.replace('_', '-')}",
            action="store_true",
            required=True,
            help=f"Explicitly confirm {check_id}.",
        )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    checks = {
        check_id: bool(
            getattr(args, f"confirm_{check_id}")
        )
        for check_id in ROOM_AND_SPOKEN_TURN_CHECK_IDS
    }
    materialize_manfred_spoken_conversation_operator_acceptance(
        output_path=args.output,
        reviewer_ref_sha256=args.reviewer_ref_sha256,
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
        checks=checks,
        confirmation=args.confirmation,
    )
    print(str(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
