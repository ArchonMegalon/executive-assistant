from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.source_state_head import resolve_source_state_head
from scripts.source_state_head import resolve_source_worktree_fingerprint


REQUIRED_ROOM_CHECK_IDS = [
    "actual_device_checked",
    "actual_speaker_checked",
    "first_syllable_not_clipped",
    "intelligibility_confirmed",
    "answer_text_fallback_visible",
    "no_internet_search_confirmed",
    "normal_spoken_turn_confirmed",
    "interruption_behavior_confirmed",
    "retry_path_confirmed",
]

REQUIRED_LIVE_PROOF_AFTER_READINESS = [
    "operator acceptance that this behaves like an ongoing spoken conversation",
    "real room audio acceptance with actual device and speaker",
]

DEFAULT_RECEIPT = REPO_ROOT / ".codex-studio" / "published" / "manfred_realtime_conversation_readiness.generated.json"
MANFRED_VOICE_GOLD_PATH = "/admin/memorials/manfred/gold"
MANFRED_VOICE_GOLD_LABEL = "Open voice gold"
MANFRED_PROOF_PATH = "/memorials/manfred/voice-config"
MANFRED_PROOF_LABEL = "Spoken conversation proof"
ACTION_METHOD = "get"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _source_state() -> dict[str, str]:
    return {
        "source_git_head": resolve_source_state_head(REPO_ROOT),
        "head_semantics": "source_state",
        "source_state_fingerprint": resolve_source_worktree_fingerprint(REPO_ROOT),
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
    }


def _default_operator_status() -> dict[str, Any]:
    return {
        "status": "blocked",
        "current_label": "Memorial public-origin gold: blocked",
        "room_audio_receipt": "missing_or_blocked",
        "spoken_conversation_stt": {
            "status": "pass",
            "production_eligible": True,
            "ground_truth_fixture_mode": "synthetic_only",
            "real_captured_fixture_status": "captured_candidate_diagnostic_blocked",
        },
        "captured_candidate_diagnostic": {"status": "blocked", "promotion_allowed": False, "row_failure_codes": ["missing_live_candidate"]},
        "spoken_conversation_tts": {"status": "pass", "premium_status": "blocked", "room_audio_receipt": "blocked"},
        "room_audio_attestation_packet": {
            "status": "ready",
            "manual_only": True,
            "ci_must_not_auto_assert": True,
            "required_check_ids": REQUIRED_ROOM_CHECK_IDS,
        },
    }


def _next_action_surface(
    *,
    ready: bool,
    blocked_checks: list[str],
    stt: dict[str, Any],
    diagnostic: dict[str, Any],
    tts: dict[str, Any],
    attestation: dict[str, Any],
) -> dict[str, str]:
    if ready:
        return {
            "next_action": "review_realtime_conversation_in_real_room",
            "next_action_href": MANFRED_PROOF_PATH,
            "next_action_label": MANFRED_PROOF_LABEL,
            "next_action_method": ACTION_METHOD,
        }

    room_audio_blocked = bool(
        {"room_audio_receipt_passed", "manual_room_checks_confirmed"}.intersection(blocked_checks)
    )
    if room_audio_blocked:
        action = str(attestation.get("next_action") or tts.get("next_action") or "collect_real_room_audio_attestation").strip()
        return {
            "next_action": action,
            "next_action_href": MANFRED_PROOF_PATH,
            "next_action_label": MANFRED_PROOF_LABEL,
            "next_action_method": ACTION_METHOD,
        }

    diagnostic_action = str(
        diagnostic.get("next_action")
        or stt.get("next_action")
        or "rerun_operator_local_full_text_benchmark_or_correct_ground_truth_transcript"
    ).strip()
    return {
        "next_action": diagnostic_action,
        "next_action_href": MANFRED_VOICE_GOLD_PATH,
        "next_action_label": MANFRED_VOICE_GOLD_LABEL,
        "next_action_method": ACTION_METHOD,
    }


def materialize_manfred_realtime_conversation_readiness(
    *,
    receipt_path: str | Path,
    generated_at: str = "",
    operator_status: dict[str, Any] | None = None,
    refresh: bool = True,
) -> dict[str, Any]:
    del refresh
    status = operator_status or _default_operator_status()
    stt = dict(status.get("spoken_conversation_stt") or {})
    diagnostic = dict(status.get("captured_candidate_diagnostic") or {})
    tts = dict(status.get("spoken_conversation_tts") or {})
    attestation = dict(status.get("room_audio_attestation_packet") or {})
    blocked: list[str] = []
    if stt.get("real_captured_fixture_status") != "captured_candidate_benchmark_pass":
        blocked.append("real_captured_stt_fixture_ready")
    if diagnostic.get("status") != "ready" or diagnostic.get("promotion_allowed") is not True:
        blocked.append("captured_candidate_diagnostic_clean")
    if tts.get("room_audio_receipt") != "pass" or tts.get("premium_status") != "pass":
        blocked.append("room_audio_receipt_passed")
    if not all(check in list(attestation.get("required_check_ids") or []) for check in REQUIRED_ROOM_CHECK_IDS):
        blocked.append("manual_room_checks_confirmed")
    if (
        attestation.get("manual_only") is not True
        or attestation.get("ci_must_not_auto_assert") is not True
        or status.get("room_audio_receipt") != "pass"
    ):
        blocked.append("manual_room_checks_confirmed")
    ready = not blocked
    next_action_surface = _next_action_surface(
        ready=ready,
        blocked_checks=blocked,
        stt=stt,
        diagnostic=diagnostic,
        tts=tts,
        attestation=attestation,
    )
    receipt = {
        "contract_name": "ea.manfred_realtime_conversation_readiness.v1",
        "status": "ready_for_realtime_conversation_review" if ready else "blocked_realtime_prerequisites",
        "generated_at": generated_at or _now(),
        **_source_state(),
        "current_label": status.get("current_label"),
        "operator_status": status.get("status"),
        "ready_for_realtime_conversation_review": ready,
        "realtime_conversation_claim_allowed": ready,
        "premium_spoken_claim_allowed": ready,
        "goal_completion_claim_allowed": False,
        "blocked_checks": blocked,
        "stt": stt,
        "captured_candidate_diagnostic": diagnostic,
        "tts": tts,
        "room_audio_attestation": attestation,
        "interaction_acceptance": {"ongoing_cinematic_narration_not_scene_bound": True},
        "required_live_proof_after_readiness": REQUIRED_LIVE_PROOF_AFTER_READINESS,
        "privacy": {
            "raw_private_context_exposed": False,
            "raw_transcript_fields": False,
            "candidate_raw_text_fields": False,
            "redacted_text_fields": True,
        },
        **next_action_surface,
    }
    _write(receipt_path, receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Materialize Manfred realtime conversation readiness.")
    parser.add_argument("--receipt", default=str(DEFAULT_RECEIPT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--no-refresh", action="store_true")
    args = parser.parse_args(argv)
    receipt = materialize_manfred_realtime_conversation_readiness(receipt_path=args.receipt, generated_at=args.generated_at, refresh=not args.no_refresh)
    print(json.dumps({"status": receipt["status"], "receipt": str(args.receipt)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
