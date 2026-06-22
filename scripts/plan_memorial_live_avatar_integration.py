#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AVATAR_PROVIDER_ROOT = Path(
    os.environ.get("CHUMMER6_AVATAR_PROVIDER_ROOT")
    or ROOT / ".codex-studio" / "published" / "avatar_presenter_provider"
)
DEFAULT_OUT = Path(
    os.environ.get("CHUMMER6_LIVE_AVATAR_INTEGRATION_PLAN_PATH")
    or DEFAULT_AVATAR_PROVIDER_ROOT / "memorial_live_avatar_integration_plan.generated.json"
)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_plan() -> dict[str, object]:
    return {
        "generated_at": _utc_now(),
        "contract_name": "executive_assistant.memorial_live_avatar_integration_plan.v1",
        "goal": "Define the production integration plan for a cool Manfred video meeting app that starts safely from the current memorial surface and upgrades to a real live avatar lane.",
        "decision": {
            "primary_provider": "tavus",
            "secondary_provider": "did",
            "owned_ltd_backup": "nonverbia",
            "batch_special_clip_provider": "vidboard",
            "go_no_go_rule": "Do not promote a provider to the public Manfred video meeting lane until session creation, permission handling, and fallback recovery are proven end-to-end.",
        },
        "session_flow": [
            {
                "step": "landing_ready",
                "description": "Public memorial page warms the voice lane first; video call button remains explicit and optional.",
                "current_repo_anchor": "public_memorials.py hero-actions + warmup",
            },
            {
                "step": "video_call_opt_in",
                "description": "User explicitly taps `Video Call mit Manfred Hoza`.",
                "why": "No surprise camera prompt on a memorial surface.",
            },
            {
                "step": "provider_session_create",
                "description": "Server creates a provider conversation/session and returns only the safe client join payload.",
                "tavus_shape": "create conversation -> receive meeting URL or custom UI connection details",
                "did_shape": "create realtime agent session -> return client connection/key details",
            },
            {
                "step": "avatar_first_join",
                "description": "Manfred avatar joins first; user sees avatar presence before any self-camera request.",
                "why": "Preserve the wow effect without coercive permissions.",
            },
            {
                "step": "camera_optional_upgrade",
                "description": "Client offers camera access after the avatar is already present. `Ohne Kamera fortfahren` remains valid.",
                "why": "A cool meeting app should not fail just because the user declines camera.",
            },
            {
                "step": "conversation_runtime",
                "description": "Live turn-taking, mic capture, mute/unmute, reconnect, and exit all run through the provider session while memorial guardrails remain server-owned.",
            },
            {
                "step": "fallback_exit",
                "description": "If avatar session creation fails, the UI falls back to the existing portrait + voice memorial call instead of dying.",
            },
        ],
        "permission_gates": {
            "microphone": {
                "required_for_live_meeting": True,
                "request_timing": "before user speaks into the live provider call",
                "fallback": "typed or memorial voice fallback if browser microphone fails",
            },
            "camera": {
                "required_for_live_meeting": False,
                "request_timing": "only after avatar join or explicit user request",
                "fallback": "continue call with avatar + voice only",
            },
            "autoplay_audio": {
                "required_for_live_meeting": True,
                "request_timing": "bound to explicit click on video call CTA",
                "fallback": "show unmute/resume control and continue session",
            },
        },
        "ui_contract": {
            "must_keep": [
                "minimal memorial landing",
                "conversation CTA",
                "video call CTA",
                "camera-optional copy",
                "portrait fallback",
            ],
            "must_add_for_live_provider": [
                "provider session bootstrap endpoint",
                "provider join status",
                "reconnect state",
                "leave/end-call state",
                "visible fallback when live avatar session fails",
            ],
            "must_not_do": [
                "no surprise camera prompt on page load",
                "no fake avatar claim when provider session is absent",
                "no provider-specific admin noise on the public page",
            ],
        },
        "server_contract": {
            "new_endpoints_needed": [
                "/memorials/{slug}/video-meeting/session",
                "/memorials/{slug}/video-meeting/status",
            ],
            "owned_server_truth": [
                "memorial guardrails",
                "provider selection",
                "provider failure classification",
                "fallback decision",
            ],
            "provider_client_truth_only": [
                "live avatar transport state",
                "remote media join state",
            ],
        },
        "fallback_policy": {
            "provider_session_create_failed": "fallback_to_existing_memorial_voice_call",
            "provider_join_timeout": "show_portrait_plus_voice_and_offer_retry",
            "camera_denied": "continue_avatar_without_camera",
            "microphone_denied": "typed_or_push_to_talk_fallback",
            "avatar_provider_down": "portrait_preview_with_honest_status_copy",
        },
        "implementation_slices": [
            {
                "slice": "provider_bootstrap_contract",
                "description": "Add a provider-neutral server endpoint that returns a session payload for Tavus or D-ID without leaking raw provider secrets to the page.",
                "status": "next",
            },
            {
                "slice": "client_video_meeting_state_machine",
                "description": "Replace the current prelive-only video preview with a real provider session state machine while preserving portrait fallback.",
                "status": "next",
            },
            {
                "slice": "e2e_browser_proof",
                "description": "Run browser proof for CTA -> session create -> avatar visible -> camera optional -> exit/fallback.",
                "status": "after_runtime",
            },
        ],
        "provider_specific_notes": {
            "tavus": {
                "why_first": "Official one-to-one conversation component and managed WebRTC meeting model match the product shape best.",
                "source_links": [
                    "https://docs.tavus.io/sections/conversational-video-interface",
                    "https://docs.tavus.io/sections/conversational-video-interface/conversation/overview",
                    "https://docs.tavus.io/sections/conversational-video-interface/component-library/blocks",
                ],
            },
            "did": {
                "why_second": "Official realtime avatar sessions over WebRTC make it the strongest backup if Tavus onboarding or pricing fails.",
                "source_links": [
                    "https://docs.d-id.com/docs/realtime-overview",
                ],
            },
            "vidboard": {
                "role": "special_clip_only",
                "reason_not_primary": "Captcha/login risk plus no proven live meeting path in this repo.",
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize the memorial live avatar integration plan.")
    parser.add_argument("--output", default=str(DEFAULT_OUT))
    args = parser.parse_args()
    payload = build_plan()
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(path.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
