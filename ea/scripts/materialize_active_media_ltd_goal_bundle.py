from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CONTRACT_NAME = "ea.active_media_ltd_goal_bundle.v1"
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
PUBLISHED_ROOT = REPO_ROOT / ".codex-studio" / "published"
DEFAULT_RECEIPT = PUBLISHED_ROOT / "active_media_ltd_goal_bundle.generated.json"

VERIFICATION_RECEIPTS: dict[str, str | None] = {
    "audiobook_live_readiness": ".codex-studio/published/telegram_audiobook_live_readiness.generated.json",
    "audiobook_m4b_structure": ".codex-studio/published/audiobook_m4b_structure_probe/audiobook_m4b_structure_probe.generated.json",
    "audiobook_quality": ".codex-studio/published/ea_audiobook_epub_quality_contract.generated.json",
    "cinematic_continuity_demo": ".codex-studio/published/cinematic_narration_continuity_demo/cinematic_narration_continuity_demo.generated.json",
    "cinematic_media_contract": None,
    "promo_public_route_surface": ".codex-studio/published/ea_promo_public_route_surface.generated.json",
    "promo_quality_rubric": ".codex-studio/published/ea_promo_video_fallback/ashline-circle/promo_quality_rubric.generated.json",
    "promo_review_bundle": ".codex-studio/published/ea_promo_video_fallback/ashline-circle/promo_review_bundle.generated.json",
}

REMAINING_EXTERNAL_PROOFS = [
    "named promo video provider account/runtime proof",
    "deployed public promo route browser proof",
    "human review approval for public promo publication",
    "real user EPUB render and playback acceptance evidence",
]


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _repo_path(path: str) -> Path:
    return REPO_ROOT / path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _receipt_row(relative_path: str | None) -> dict[str, Any]:
    if relative_path is None:
        return {"status": "pass", "issues": []}
    path = _repo_path(relative_path)
    exists = path.is_file()
    row: dict[str, Any] = {
        "status": "pass" if exists else "fail",
        "issues": [] if exists else ["receipt_missing"],
        "receipt": {
            "exists": exists,
            "path": relative_path,
            "bytes": path.stat().st_size if exists else 0,
            "sha256": _sha256(path) if exists else "",
        },
    }
    return row


def _default_external_posture(template: dict[str, Any]) -> dict[str, Any]:
    posture = dict(template.get("external_proof_posture") or {})
    posture.setdefault(
        "audiobook_live_delivery",
        {
            "status": "missing",
            "goal_completion_claim_allowed": False,
            "real_user_playback_acceptance_verified": False,
            "privacy": {"raw_public_share_url_included": False},
        },
    )
    posture.setdefault(
        "spoken_conversation",
        {
            "status": "blocked_external_proof",
            "premium_spoken_claim_allowed": False,
            "privacy": {"raw_private_context_exposed": False},
            "room_audio_attestation_packet": {
                "manual_only": True,
                "ci_must_not_auto_assert": True,
                "required_check_ids": ["normal_spoken_turn_confirmed"],
            },
            "blocking_actions": ["collect_real_room_audio_attestation"],
            "stt": {"real_captured_fixture_required": False},
            "tts": {"premium_status": "blocked"},
            "captured_candidate_diagnostic": {"status": "blocked", "promotion_allowed": False, "row_failure_codes": []},
        },
    )
    spoken = dict(posture["spoken_conversation"])
    spoken["premium_spoken_claim_allowed"] = spoken.get("status") == "ready_for_premium_review"
    spoken.setdefault("privacy", {})["raw_private_context_exposed"] = False
    attestation = dict(spoken.get("room_audio_attestation_packet") or {})
    attestation.setdefault("manual_only", True)
    attestation.setdefault("ci_must_not_auto_assert", True)
    required = list(attestation.get("required_check_ids") or [])
    if "normal_spoken_turn_confirmed" not in required:
        required.append("normal_spoken_turn_confirmed")
    attestation["required_check_ids"] = required
    spoken["room_audio_attestation_packet"] = attestation
    posture["spoken_conversation"] = spoken
    return posture


def _template() -> dict[str, Any]:
    if DEFAULT_RECEIPT.is_file():
        return _read_json(DEFAULT_RECEIPT)
    return {
        "contract_name": CONTRACT_NAME,
        "status": "ready_local_evidence",
        "goal_scope": [
            "telegram_epub_audiobook_voice_quality",
            "telegram_epub_audiobook_live_readiness",
            "chaptered_m4b_with_cover_art",
            "spoken_conversation_provider_boundary",
            "realtime_conversation_speaker_readiness",
            "continuous_cinematic_narration",
            "local_fallback_promo_video_quality",
        ],
        "lane_summary": {},
    }


def materialize_active_media_ltd_goal_bundle(
    *,
    receipt_path: str | Path = DEFAULT_RECEIPT,
    generated_at: str = "",
    refresh: bool = False,
) -> dict[str, Any]:
    del refresh  # Refresh is local-only here; external provider proofs remain manual gates.
    template = _template()
    receipt = dict(template)
    receipt.update(
        {
            "contract_name": CONTRACT_NAME,
            "status": "ready_local_evidence",
            "generated_at": generated_at or _now(),
            "goal_completion_claim_allowed": False,
            "gold_claim_allowed": False,
            "provider_ready": False,
            "live_provider_runtime_verified": False,
            "verified_provider_claim_allowed": False,
            "provider_output_truth_allowed": False,
            "provider_publication_allowed": False,
            "public_route_claim_allowed": False,
            "public_route_deployment_verified": False,
            "credential_values_exposed": False,
            "raw_private_context_exposed": False,
            "remaining_external_proofs": REMAINING_EXTERNAL_PROOFS,
            "external_proof_posture": _default_external_posture(template),
            "verifications": {key: _receipt_row(path) for key, path in VERIFICATION_RECEIPTS.items()},
        }
    )
    _write_json(Path(receipt_path), receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Materialize the Active Media LTD local evidence bundle.")
    parser.add_argument("--receipt", default=str(DEFAULT_RECEIPT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--no-refresh", action="store_true")
    args = parser.parse_args(argv)
    receipt = materialize_active_media_ltd_goal_bundle(
        receipt_path=args.receipt,
        generated_at=args.generated_at,
        refresh=not args.no_refresh,
    )
    print(json.dumps({"status": receipt["status"], "receipt": str(args.receipt)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
