#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LTD_PATH = ROOT / "LTDs.md"
OUTPUT_PATH = Path(os.environ.get("EA_AVATAR_PRESENTER_PROVIDER_OUTPUT") or ROOT / "ea" / "_completion" / "avatar_presenter_provider" / "AVATAR_PRESENTER_PROVIDER_VERIFICATION.generated.json")


PROVIDER_SPECS = [
    {
        "provider": "VidBoard",
        "service_key": "VidBoard.ai",
        "role": "photoreal_avatar_presenter_candidate",
        "status": "pilot",
        "commercial_use_allowed": False,
        "watermark_free": False,
        "lip_sync_verified": False,
        "viseme_quality_verified": False,
        "api_available": False,
        "manual_workflow_allowed": True,
        "privacy_terms_reviewed": False,
        "source_data_allowed": False,
        "max_duration": "unknown",
        "max_resolution": "unknown",
        "notes": "Best current LTD candidate for a photoreal speaking avatar, but still blocked until provider proof exists.",
    },
    {
        "provider": "Nonverbia",
        "service_key": "Nonverbia",
        "role": "avatar_presenter_candidate",
        "status": "pilot",
        "commercial_use_allowed": False,
        "watermark_free": False,
        "lip_sync_verified": False,
        "viseme_quality_verified": False,
        "api_available": False,
        "manual_workflow_allowed": True,
        "privacy_terms_reviewed": False,
        "source_data_allowed": False,
        "max_duration": "unknown",
        "max_resolution": "unknown",
        "notes": "Secondary presenter candidate; evaluate after or alongside VidBoard.",
    },
    {
        "provider": "Mootion",
        "service_key": "Mootion",
        "role": "motion_presenter_candidate",
        "status": "pilot",
        "commercial_use_allowed": False,
        "watermark_free": False,
        "lip_sync_verified": False,
        "viseme_quality_verified": False,
        "api_available": False,
        "manual_workflow_allowed": True,
        "privacy_terms_reviewed": False,
        "source_data_allowed": False,
        "max_duration": "unknown",
        "max_resolution": "unknown",
        "notes": "Motion/video scaffold candidate, not the first-choice lip-sync lane.",
    },
    {
        "provider": "MagicFit",
        "service_key": "MagicFit",
        "role": "video_render_candidate_not_avatar_primary",
        "status": "pilot",
        "commercial_use_allowed": False,
        "watermark_free": False,
        "lip_sync_verified": False,
        "viseme_quality_verified": False,
        "api_available": False,
        "manual_workflow_allowed": True,
        "privacy_terms_reviewed": False,
        "source_data_allowed": False,
        "max_duration": "unknown",
        "max_resolution": "unknown",
        "notes": "Useful for B-roll and scene clips; not yet a proven talking-avatar primary lane.",
    },
    {
        "provider": "Unmixr AI",
        "service_key": "Unmixr AI",
        "role": "voice_only_companion",
        "status": "pilot",
        "commercial_use_allowed": False,
        "watermark_free": True,
        "lip_sync_verified": False,
        "viseme_quality_verified": False,
        "api_available": True,
        "manual_workflow_allowed": True,
        "privacy_terms_reviewed": False,
        "source_data_allowed": False,
        "max_duration": "n/a",
        "max_resolution": "audio_only",
        "notes": "Audio lane only; pair with an avatar renderer, never treat as the avatar lane itself.",
    },
    {
        "provider": "BrowserAct",
        "service_key": "BrowserAct",
        "role": "provider_verification_and_route_qa",
        "status": "verified",
        "commercial_use_allowed": True,
        "watermark_free": True,
        "lip_sync_verified": False,
        "viseme_quality_verified": False,
        "api_available": True,
        "manual_workflow_allowed": True,
        "privacy_terms_reviewed": True,
        "source_data_allowed": False,
        "max_duration": "n/a",
        "max_resolution": "n/a",
        "notes": "Use to verify provider claims and capture proof; not an avatar renderer.",
    },
]


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_ltd_rows() -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    if not LTD_PATH.is_file():
        return rows
    headers = ["service", "plan_tier", "holding", "status", "redeem_by", "workspace_integration_tier", "local_integration", "notes"]
    for raw_line in LTD_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line.startswith("| `"):
            continue
        parts = [part.strip() for part in line.strip("|").split("|")]
        if len(parts) != len(headers):
            continue
        row = {header: value.strip(" `") for header, value in zip(headers, parts)}
        rows[row["service"]] = row
    return rows


def _provider_ready(row: dict[str, object]) -> bool:
    return bool(
        row["status"] == "verified"
        and row["commercial_use_allowed"]
        and row["watermark_free"]
        and row["lip_sync_verified"]
        and row["viseme_quality_verified"]
        and row["privacy_terms_reviewed"]
        and row["source_data_allowed"]
    )


def build_payload() -> dict[str, object]:
    ltd_rows = _parse_ltd_rows()
    providers: list[dict[str, object]] = []
    ready_avatar_providers: list[str] = []
    for spec in PROVIDER_SPECS:
        row = dict(ltd_rows.get(spec["service_key"]) or {})
        provider_row = {
            "provider": spec["provider"],
            "role": spec["role"],
            "account_status": str(row.get("status") or "tracked"),
            "tier": str(row.get("plan_tier") or "unknown"),
            "workspace_integration_tier": str(row.get("workspace_integration_tier") or "unknown"),
            "status": str(spec["status"]),
            "commercial_use_allowed": bool(spec["commercial_use_allowed"]),
            "watermark_free": bool(spec["watermark_free"]),
            "lip_sync_verified": bool(spec["lip_sync_verified"]),
            "viseme_quality_verified": bool(spec["viseme_quality_verified"]),
            "api_available": bool(spec["api_available"]),
            "manual_workflow_allowed": bool(spec["manual_workflow_allowed"]),
            "privacy_terms_reviewed": bool(spec["privacy_terms_reviewed"]),
            "source_data_allowed": bool(spec["source_data_allowed"]),
            "max_duration": str(spec["max_duration"]),
            "max_resolution": str(spec["max_resolution"]),
            "notes": str(row.get("notes") or spec["notes"]),
        }
        if provider_row["role"] in {
            "photoreal_avatar_presenter_candidate",
            "avatar_presenter_candidate",
            "motion_presenter_candidate",
        } and _provider_ready(provider_row):
            ready_avatar_providers.append(str(provider_row["provider"]))
        providers.append(provider_row)
    verdict = "VERIFIED_PROVIDER" if ready_avatar_providers else "READY_VIA_FALLBACK"
    return {
        "generated_at": _utc_now(),
        "contract_name": "executive_assistant.avatar_presenter_provider_verification.v1",
        "verdict": verdict,
        "avatar_provider_ready": bool(ready_avatar_providers),
        "ready_avatar_providers": ready_avatar_providers,
        "fallback_mode": "fallback_static_storyboard",
        "summary": (
            "Fail closed to storyboard/static-motion fallback until a named avatar provider proves commercial use, "
            "watermark-free export, privacy review, source-data allowance, and convincing lip-sync/viseme quality."
        ),
        "providers": providers,
    }


def write_payload(path: Path) -> Path:
    payload = build_payload()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize speaking-avatar provider verification proof.")
    parser.add_argument("--write", default=str(OUTPUT_PATH), help="Output JSON path.")
    args = parser.parse_args()
    path = write_payload(Path(args.write))
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
