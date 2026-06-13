#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = Path("/docker/fleet/state/chummer6/avatar_presenter_provider/JOGGAI_PROVIDER_VERIFICATION.generated.json")


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_ltds(path: Path) -> str:
    if not path.is_file():
        raise SystemExit(f"ltds_missing:{path}")
    return path.read_text(encoding="utf-8")


def build_receipt(*, ltds_path: Path, output_path: Path) -> dict[str, object]:
    ltds_text = _load_ltds(ltds_path)
    inventory_recorded = "`JoggAI`" in ltds_text and "License Tier 4" in ltds_text
    payload = {
        "contract_name": "executive_assistant.joggai_provider_verification.v1",
        "provider": "joggai",
        "provider_key": "joggai",
        "service": "JoggAI",
        "account_tier": "AppSumo Tier 4",
        "verified_at": _utc_now(),
        "status": "candidate_only",
        "verdict": "CANDIDATE_ONLY",
        "provider_ready": False,
        "runtime_enabled": False,
        "manual_workflow_allowed": True,
        "api_available": False,
        "api_notes": "AppSumo Tier 4 API availability is not proven in this account; default mode is manual export plus EA receipt verification.",
        "default_env": {
            "EA_MEMORIAL_JOGGAI_MODE": "manual",
            "EA_MEMORIAL_JOGGAI_ENABLED": "0",
            "EA_MEMORIAL_JOGGAI_API_ENABLED": "0",
        },
        "tier_facts": {
            "avatarlite_video": "unlimited",
            "monthly_non_video_credits": 15,
            "custom_avatars": 5,
            "max_video_length_minutes": 15,
            "concurrency": 2,
            "queue_tasks": 1,
            "fast_video_minutes_per_month": 100,
            "watermark_removal_included": True,
            "aspect_ratios": ["9:16", "16:9"],
        },
        "checks": {
            "inventory_recorded": inventory_recorded,
            "commercial_use_checked": False,
            "watermark_removed_verified": False,
            "privacy_review": False,
            "likeness_policy_review": False,
            "api_access_verified": False,
            "first_render_receipt": False,
        },
        "allowed_uses": [
            "approved_script_neutral_memorial_intro",
            "approved_public_archive_trailer",
            "family_review_clip",
            "avatar_candidate_render_after_consent",
        ],
        "forbidden_uses": [
            "live_memorial_conversation",
            "realtime_video_call_response",
            "private_memory_auto_processing",
            "unsupervised_manfred_likeness_generation",
            "direct_public_publish",
            "present_world_manfred_claims",
        ],
        "source_of_truth_boundary": "EA owns consent, script approval, safety review, publication manifest, and asset receipts; JoggAI only renders approved video candidates.",
        "blocking_reasons": [
            "Provider proof is candidate-only until commercial-use, watermark, privacy, likeness, and first-render receipts exist.",
            "API mode remains disabled until account/API access is proven.",
        ],
    }
    if not inventory_recorded:
        payload["blocking_reasons"].append("JoggAI is not recorded in LTDs.md.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize a candidate-only JoggAI provider verification receipt.")
    parser.add_argument("--ltds", default=str(ROOT / "LTDs.md"))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    payload = build_receipt(ltds_path=Path(args.ltds), output_path=Path(args.output))
    print(
        json.dumps(
            {
                "status": "warn",
                "receipt_type": "inventory_only",
                "provider_ready": bool(payload.get("provider_ready")),
                "output": str(args.output),
                "verdict": payload["verdict"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
