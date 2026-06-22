#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from scripts.source_state_head import resolve_source_state_head
except ModuleNotFoundError:  # pragma: no cover - script execution path
    from source_state_head import resolve_source_state_head


ROOT = Path(__file__).resolve().parents[1]
EA_PATH = ROOT / "ea"
if str(EA_PATH) not in sys.path:
    sys.path.insert(0, str(EA_PATH))

from app.api.routes import channels as channels_route  # noqa: E402
from app.services import telegram_delivery  # noqa: E402
from app.services import telegram_video_effects  # noqa: E402


DEFAULT_OUTPUT = ROOT / ".codex-studio/published/telegram_video_delivery_operator.generated.json"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@contextlib.contextmanager
def _without_env(*keys: str):
    saved = {key: os.environ.get(key) for key in keys}
    try:
        for key in keys:
            os.environ.pop(key, None)
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def build_receipt(*, output_path: Path = DEFAULT_OUTPUT, generated_at: str | None = None) -> dict[str, Any]:
    with _without_env(
        "EA_TELEGRAM_VIDEO_DOWNLOAD_ALLOWED_HOSTS",
        "EA_TELEGRAM_MAGICFIT_DOCKER_IMAGE",
        "EA_TELEGRAM_VIDEO_FALLBACK_TTS_ENABLED",
        "EA_TELEGRAM_VIDEO_FALLBACK_TTS_PROVIDERS",
    ):
        default_allowed_hosts = telegram_video_effects._allowed_video_hosts()  # noqa: SLF001
        default_magicfit_image = channels_route._telegram_magicfit_docker_image()  # noqa: SLF001
        audio_policy = telegram_delivery.telegram_video_delivery_audio_policy()

    redacted_context = channels_route._telegram_video_source_receipt_context(  # noqa: SLF001
        {
            "video_download_url": "https://api.telegram.org/file/bot123456:secret-token/videos/file.mp4",
            "video_duration_seconds": 12,
            "source_video_reference_frame_paths": ["/tmp/frame-1.jpg", "/tmp/frame-2.jpg"],
        }
    )
    pinned_image = "ea-runtime@sha256:" + ("a" * 64)
    checks = [
        {
            "code": "local_source_fire_edit_supported",
            "status": "pass"
            if telegram_video_effects.source_video_edit_supported(
                "Make the ring look like it is on fire and keep it photorealistic."
            )
            else "fail",
        },
        {
            "code": "default_download_allowlist_is_telegram_only",
            "status": "pass" if default_allowed_hosts == ("api.telegram.org",) else "fail",
            "allowed_hosts": list(default_allowed_hosts),
        },
        {
            "code": "download_byte_cap_configured",
            "status": "pass"
            if 1024 * 1024 <= int(telegram_video_effects._DEFAULT_MAX_VIDEO_BYTES) <= 80 * 1024 * 1024  # noqa: SLF001
            else "fail",
            "max_bytes": int(telegram_video_effects._DEFAULT_MAX_VIDEO_BYTES),  # noqa: SLF001
        },
        {
            "code": "magicfit_has_no_default_latest_image",
            "status": "pass" if default_magicfit_image == "" else "fail",
            "default_image": default_magicfit_image,
        },
        {
            "code": "magicfit_requires_digest_pinned_image",
            "status": "pass"
            if (
                channels_route._telegram_magicfit_docker_image_pinned(pinned_image)  # noqa: SLF001
                and not channels_route._telegram_magicfit_docker_image_pinned("ea-runtime:latest")  # noqa: SLF001
            )
            else "fail",
        },
        {
            "code": "delivery_receipt_redacts_source_url",
            "status": "pass"
            if (
                redacted_context.get("source_url_raw_stored") is False
                and "123456:secret-token" not in str(redacted_context.get("source_path_redacted") or "")
                and bool(redacted_context.get("source_url_sha256"))
            )
            else "fail",
            "source_context": redacted_context,
        },
        {
            "code": "video_delivery_requires_final_audio_probe",
            "status": "pass"
            if (
                audio_policy.get("local_video_final_audio_probe_required") is True
                and audio_policy.get("remote_video_audio_probe_required") is True
            )
            else "fail",
            "audio_policy": audio_policy,
        },
        {
            "code": "video_success_ack_requires_message_ids",
            "status": "pass"
            if (
                channels_route._telegram_video_delivery_sent(  # noqa: SLF001
                    {"status": "sent", "kind": "video", "message_ids": ["tg-video-proof"]}
                )
                and not channels_route._telegram_video_delivery_sent(  # noqa: SLF001
                    {"status": "sent", "kind": "video", "message_ids": []}
                )
                and not channels_route._telegram_video_delivery_sent(  # noqa: SLF001
                    {"status": "sent", "kind": "text", "message_ids": ["tg-text-ack"]}
                )
            )
            else "fail",
        },
        {
            "code": "fallback_narration_precedes_silent_track",
            "status": "pass"
            if (
                audio_policy.get("fallback_audio_text_preferred_before_silence") is True
                and audio_policy.get("silent_track_is_last_resort") is True
                and audio_policy.get("fallback_tts_enabled_default") is True
                and bool(audio_policy.get("fallback_tts_providers"))
            )
            else "fail",
            "audio_policy": audio_policy,
        },
    ]
    blocked = [str(item["code"]) for item in checks if item["status"] != "pass"]
    status = "bounded_pass" if not blocked else "blocked"
    payload = {
        "contract_name": "ea.telegram_video_delivery_operator_receipt",
        "generated_at": generated_at or _utc_now(),
        "generated_by": "scripts/materialize_telegram_video_delivery_receipt.py",
        "source_git_head": resolve_source_state_head(ROOT),
        "head_semantics": "source_state",
        "status": status,
        "claim": "Telegram video replies have a bounded, governed local source-video lane and durable delivery receipts; live operator Telegram delivery still requires a message-ID receipt.",
        "bounded_reason": "No live operator Telegram send/message-id proof is embedded in this generated receipt.",
        "live_operator_delivery_required_for_gold": True,
        "delivery_observation_event_type": "telegram.video_delivery_receipt",
        "supported_local_edits": telegram_video_effects.supported_source_video_edit_summary(),
        "audio_policy": audio_policy,
        "checks": checks,
        "blocking_checks": blocked,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize the Telegram video delivery bounded operator receipt.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    receipt = build_receipt(output_path=args.output)
    print(json.dumps({"status": receipt["status"], "output": args.output.as_posix()}))
    return 0 if receipt["status"] != "blocked" else 1


if __name__ == "__main__":
    raise SystemExit(main())
