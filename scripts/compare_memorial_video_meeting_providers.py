#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LTD_PATH = ROOT / "LTDs.md"
DEFAULT_AVATAR_PROVIDER_ROOT = Path(
    os.environ.get("CHUMMER6_AVATAR_PROVIDER_ROOT")
    or ROOT / ".codex-studio" / "published" / "avatar_presenter_provider"
)
DEFAULT_OUT = Path(
    os.environ.get("CHUMMER6_VIDEO_MEETING_PROVIDER_MATRIX_PATH")
    or DEFAULT_AVATAR_PROVIDER_ROOT / "memorial_video_meeting_provider_matrix.generated.json"
)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_ltd_notes() -> dict[str, str]:
    notes: dict[str, str] = {}
    if not LTD_PATH.is_file():
        return notes
    for raw_line in LTD_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line.startswith("| `"):
            continue
        parts = [part.strip() for part in line.strip("|").split("|")]
        if len(parts) < 8:
            continue
        service = parts[0].strip(" `")
        note = parts[-1].strip()
        notes[service] = note
    return notes


def build_matrix() -> dict[str, object]:
    ltd_notes = _read_ltd_notes()
    providers = [
        {
            "provider_key": "tavus",
            "provider": "Tavus",
            "source_type": "external_official",
            "fit": "strong_fit",
            "realtime_meeting_ready": True,
            "camera_optional": True,
            "web_rtc_native": True,
            "embed_model": "meeting_url_or_custom_ui",
            "why": "Official real-time conversational video interface with WebRTC sessions, custom UI support, persona/replica separation, and one-to-one conversation components.",
            "risks": [
                "Not an owned LTD in this repo",
                "Will require new vendor onboarding and cost review",
            ],
            "recommended_role": "primary_live_meeting_lane",
            "source_links": [
                "https://docs.tavus.io/sections/conversational-video-interface",
                "https://docs.tavus.io/sections/conversational-video-interface/conversation/overview",
                "https://docs.tavus.io/sections/conversational-video-interface/component-library/blocks",
            ],
        },
        {
            "provider_key": "did",
            "provider": "D-ID",
            "source_type": "external_official",
            "fit": "strong_fit",
            "realtime_meeting_ready": True,
            "camera_optional": True,
            "web_rtc_native": True,
            "embed_model": "sdk_or_client_key_embed",
            "why": "Official realtime agents over WebRTC with avatar output and optional knowledge base, closer to a true conversational meeting lane than a batch video generator.",
            "risks": [
                "Not an owned LTD in this repo",
                "Needs provider verification for latency, pricing, and export posture",
            ],
            "recommended_role": "secondary_live_meeting_lane",
            "source_links": [
                "https://docs.d-id.com/docs/realtime-overview",
            ],
        },
        {
            "provider_key": "heygen",
            "provider": "HeyGen",
            "source_type": "external_official",
            "fit": "possible_fit",
            "realtime_meeting_ready": True,
            "camera_optional": True,
            "web_rtc_native": True,
            "embed_model": "streaming_avatar_api",
            "why": "Has official streaming avatar and audio-to-video lanes, technically viable for a meeting surface but more API-orchestration-heavy than Tavus or D-ID.",
            "risks": [
                "Not an owned LTD in this repo",
                "Would need more custom integration work",
            ],
            "recommended_role": "api_heavy_live_alternative",
            "source_links": [
                "https://docs.heygen.com/",
                "https://docs.heygen.com/reference/heygen-interactive-avatar-realtime-api",
            ],
        },
        {
            "provider_key": "vidboard",
            "provider": "VidBoard",
            "source_type": "owned_ltd",
            "fit": "weak_fit_for_live_strong_fit_for_batch",
            "realtime_meeting_ready": False,
            "camera_optional": False,
            "web_rtc_native": False,
            "embed_model": "manual_batch_export",
            "why": "Good candidate for rendered talking-photo clips, but the current EA lane is blocked at login captcha and there is no proven live meeting/runtime path.",
            "risks": [
                "Login currently blocked by captcha in local BrowserAct flow",
                "No proven official live meeting SDK lane in the repo",
                "Verification proof is still fallback-only",
            ],
            "recommended_role": "special_clip_or_pre_render_fallback",
            "source_links": [
                "https://www.vidboard.ai/tool/accounts/login/",
            ],
            "local_notes": ltd_notes.get("VidBoard.ai", ""),
            "captcha_assessment": {
                "current_local_state": "captcha_required",
                "one_time_only": False,
                "operational_meaning": "This looks like an auth-session gate, not a render-once gate. If automation depends on login and the session expires, the blocker returns during ongoing operation.",
            },
        },
        {
            "provider_key": "nonverbia",
            "provider": "Nonverbia",
            "source_type": "owned_ltd",
            "fit": "possible_fit",
            "realtime_meeting_ready": False,
            "camera_optional": True,
            "web_rtc_native": False,
            "embed_model": "unknown_until_verified",
            "why": "Best owned LTD candidate after VidBoard for presenter/avatar behavior, but still not proven as a live meeting lane.",
            "risks": [
                "Structured verification incomplete",
                "No confirmed WebRTC/live-call posture in this repo",
            ],
            "recommended_role": "owned_ltd_backup_candidate",
            "local_notes": ltd_notes.get("Nonverbia", ""),
            "source_links": [
                "https://app.nonverbia.com/",
            ],
        },
        {
            "provider_key": "magicfit",
            "provider": "MagicFit",
            "source_type": "owned_ltd",
            "fit": "weak_fit",
            "realtime_meeting_ready": False,
            "camera_optional": False,
            "web_rtc_native": False,
            "embed_model": "batch_video_generation",
            "why": "Better for B-roll and short photoreal tests than for a direct Manfred meeting surface.",
            "risks": [
                "Not a meeting-native lane",
                "Provider verification still pending",
            ],
            "recommended_role": "b_roll_or_special_motion_support",
            "local_notes": ltd_notes.get("MagicFit", ""),
            "source_links": [],
        },
        {
            "provider_key": "mootion",
            "provider": "Mootion",
            "source_type": "owned_ltd",
            "fit": "weak_fit",
            "realtime_meeting_ready": False,
            "camera_optional": False,
            "web_rtc_native": False,
            "embed_model": "motion_video_generation",
            "why": "Motion/video scaffold, not the best basis for a live one-to-one Manfred meeting app.",
            "risks": [
                "Scaffold-stage only",
                "No proven live conversation stack",
            ],
            "recommended_role": "motion_fallback_only",
            "local_notes": ltd_notes.get("Mootion", ""),
            "source_links": [],
        },
    ]
    recommendation = {
        "primary": "tavus",
        "secondary": "did",
        "owned_ltd_backup": "nonverbia",
        "batch_clip_lane": "vidboard",
        "summary": (
            "Use Tavus as the primary live Manfred meeting lane, D-ID as the secondary live lane, "
            "keep Nonverbia as the best owned-LTD backup candidate, and demote VidBoard to batch/special-clip duty."
        ),
    }
    return {
        "generated_at": _utc_now(),
        "contract_name": "executive_assistant.memorial_video_meeting_provider_matrix.v1",
        "goal": "Select the most credible provider stack for a cool Manfred video meeting app without pretending an unverified batch tool is already a live meeting platform.",
        "recommendation": recommendation,
        "providers": providers,
        "vidboard_captcha_conclusion": (
            "The current VidBoard captcha looks like an auth gate that can recur whenever automation needs a fresh login/session. "
            "That makes it an ongoing operational risk, not a one-time setup chore."
        ),
        "next_steps": [
            "Verify Tavus live meeting feasibility and costs for the Manfred surface.",
            "Verify D-ID as the second live path.",
            "Run the existing Nonverbia custom-project analysis as the owned-LTD backup path.",
            "Keep VidBoard only for manual or semi-manual special clip exports until a durable non-captcha live lane is proven.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize a memorial video-meeting provider comparison and recommendation matrix.")
    parser.add_argument("--output", default=str(DEFAULT_OUT))
    args = parser.parse_args()
    payload = build_matrix()
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(path.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
