#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

try:
    from scripts.materialize_memorial_room_audio_receipt import ROOM_AUDIO_CHECK_REQUIREMENTS
    from scripts.source_state_head import resolve_source_state_head
    from scripts.source_state_head import resolve_source_worktree_fingerprint
except ModuleNotFoundError:  # pragma: no cover - script execution path
    from materialize_memorial_room_audio_receipt import ROOM_AUDIO_CHECK_REQUIREMENTS
    from source_state_head import resolve_source_state_head
    from source_state_head import resolve_source_worktree_fingerprint


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / ".codex-studio/published/memorial_room_audio_attestation_packet.generated.json"
ROOM_RECEIPT = ".codex-studio/published/memorial_room_audio_public_origin.generated.json"
DEFAULT_MEMORIAL_PUBLIC_ORIGIN = "https://memorial.example.test"
CHECK_FLAG_BY_ID = {
    key: "--" + key.replace("_", "-")
    for key in ROOM_AUDIO_CHECK_REQUIREMENTS
}


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_packet(args: argparse.Namespace, *, generated_at: str | None = None) -> dict[str, object]:
    base_url = str(
        args.base_url
        or os.getenv("MEMORIAL_PUBLIC_ORIGIN")
        or DEFAULT_MEMORIAL_PUBLIC_ORIGIN
    ).rstrip("/")
    slug = str(args.slug or "manfred").strip() or "manfred"
    required_env = {
        "MEMORIAL_PUBLIC_ORIGIN": base_url,
        "MEMORIAL_PUBLIC_SLUG": slug,
        "MEMORIAL_ROOM_REVIEWER": "actual listener/operator name",
        "MEMORIAL_ROOM_DEVICE_LABEL": "exact device, browser, and public-origin path",
        "MEMORIAL_ROOM_SPEAKER_LABEL": "exact speaker, headphones, or output route",
        "MEMORIAL_ROOM_LABEL": "actual room/location",
        "MEMORIAL_ROOM_NOTES": "volume, warmth, first syllable, intelligibility, interruption, retry behavior",
        "MEMORIAL_ROOM_ATTESTATION_ID": "signed-room-review-id",
        "MEMORIAL_ROOM_ATTESTATION_SIGNED_AT": "YYYY-MM-DDTHH:MM:SSZ",
        "MEMORIAL_ROOM_ATTESTATION_SOURCE": "operator_room_review",
    }
    check_flags = [CHECK_FLAG_BY_ID[key] for key in ROOM_AUDIO_CHECK_REQUIREMENTS]
    receipt_command_template = (
        "MEMORIAL_PUBLIC_ORIGIN=<public-origin> "
        "MEMORIAL_ROOM_REVIEWER=<actual-listener> "
        "MEMORIAL_ROOM_DEVICE_LABEL=<device-browser-public-path> "
        "MEMORIAL_ROOM_SPEAKER_LABEL=<speaker-or-output-route> "
        "MEMORIAL_ROOM_LABEL=<actual-room> "
        "MEMORIAL_ROOM_NOTES=<plain-language-observations> "
        "MEMORIAL_ROOM_ATTESTATION_ID=<signed-room-review-id> "
        "MEMORIAL_ROOM_ATTESTATION_SIGNED_AT=<YYYY-MM-DDTHH:MM:SSZ> "
        "make materialize-memorial-room-audio-gold-clean"
    )
    return {
        "contract_name": "ea.memorial_room_audio_attestation_packet",
        "generated_at": generated_at or _utc_now(),
        "generated_by": "scripts/materialize_memorial_room_audio_attestation_packet.py",
        "status": "ready",
        "source_git_head": resolve_source_state_head(ROOT),
        "head_semantics": "source_state",
        "source_state_fingerprint": resolve_source_worktree_fingerprint(ROOT),
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
        "slug": slug,
        "base_url": base_url,
        "proof_target": ROOM_RECEIPT,
        "claim": "Manfred premium spoken conversation requires a real public-origin room test, not a CI assertion.",
        "manual_only": True,
        "ci_must_not_auto_assert": True,
        "operator_command": "make materialize-memorial-room-audio-gold-clean",
        "receipt_command_template": receipt_command_template,
        "required_env": required_env,
        "required_cli_flags": check_flags,
        "required_checks": [
            {"id": key, "description": description, "cli_flag": CHECK_FLAG_BY_ID[key]}
            for key, description in ROOM_AUDIO_CHECK_REQUIREMENTS.items()
        ],
        "operator_steps": [
            f"Open {base_url}/memorials/{slug} and {base_url}/memorials/{slug}.json from the real public path.",
            "Ask at least one normal spoken question and wait for microphone capture, STT, answer generation, TTS, and audible playback.",
            "Confirm every required check manually; if a check is uncertain, do not set its flag.",
            "Use non-generic reviewer, room, device, speaker, and notes values; generic labels intentionally keep the receipt blocked.",
            "Set MEMORIAL_ROOM_ATTESTATION_ID and MEMORIAL_ROOM_ATTESTATION_SIGNED_AT from the signed operator review before recording the clean receipt.",
            "Run the clean materializer from a clean source tree; dirty source intentionally blocks final room-audio gold.",
        ],
        "conversation_prompts": [
            "Kannst du mir kurz antworten?",
            "Was war dir bei Gerechtigkeit wichtig?",
            "Wie stehst du zur Covid-Impfung?",
            "Ich unterbreche dich kurz, kannst du weitermachen?",
        ],
        "acceptance": [
            "The answer is audible without relying on fallback text.",
            "The transcript/fallback text remains visible.",
            "The first syllable is not clipped.",
            "A normal spoken turn completes from microphone to playback.",
            "Interruption or barge-in behavior is understandable.",
            "The retry path is clear after acoustic or turn-taking trouble.",
            "The memorial does not search the internet as Manfred.",
        ],
        "failure_policy": "If any check is uncertain, leave the room receipt blocked and record notes for replay/debugging.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Materialize the manual attestation packet for Manfred room-audio proof.")
    parser.add_argument(
        "--base-url",
        default="",
        help="Public memorial origin. Defaults to MEMORIAL_PUBLIC_ORIGIN or an example origin.",
    )
    parser.add_argument("--slug", default="manfred")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args(argv)

    packet = build_packet(args)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": packet["status"], "output": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
