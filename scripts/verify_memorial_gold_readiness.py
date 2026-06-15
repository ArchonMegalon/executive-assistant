#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LOCAL_RECEIPT = ROOT / ".codex-studio/published/memorial_voice_roundtrip_exit_gate.generated.json"
PUBLIC_RECEIPT = ROOT / ".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json"
BROWSER_RECEIPT = ROOT / ".codex-studio/published/memorial_realtime_browser_public_origin.generated.json"
MEANINGFUL_BROWSER_RECEIPT = ROOT / ".codex-studio/published/memorial_realtime_browser_meaningful_public_origin.generated.json"
ROOM_RECEIPT = ROOT / ".codex-studio/published/memorial_room_audio_public_origin.generated.json"
GENERATED_RECEIPT_PATHS = {
    ".codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json",
    ".codex-design/product/MEMORIAL_OPERATOR_STATUS.generated.json",
    ".codex-design/product/PROJECT_MODES.generated.json",
    ".codex-design/product/SHOW_SURFACE_MANIFEST.generated.json",
    ".codex-design/product/WEEKLY_PRODUCT_PULSE.generated.json",
    ".codex-design/product/WHOLE_PROJECT_GOLD_MAP.generated.json",
    ".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json",
    ".codex-studio/published/memorial_voice_roundtrip_exit_gate.generated.json",
    ".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json",
    ".codex-studio/published/memorial_realtime_browser_public_origin.generated.json",
    ".codex-studio/published/memorial_realtime_browser_meaningful_public_origin.generated.json",
    ".codex-studio/published/memorial_room_audio_public_origin.generated.json",
}


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _git_head() -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except Exception:
        return ""


def _fresh_enough(recorded_head: str, *, current_head: str) -> bool:
    recorded = str(recorded_head or "").strip()
    if not recorded or not current_head:
        return False
    if recorded == current_head:
        return True
    try:
        proc = subprocess.run(
            ["git", "-C", str(ROOT), "diff", "--name-only", f"{recorded}..{current_head}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return False
    if proc.returncode != 0:
        return False
    changed = {line.strip() for line in proc.stdout.splitlines() if line.strip()}
    return bool(changed) and changed <= GENERATED_RECEIPT_PATHS


def _is_local_base_url(value: str) -> bool:
    lowered = str(value or "").strip().lower()
    return any(marker in lowered for marker in ("://127.0.0.1", "://localhost", "://0.0.0.0", "://[::1]"))


def _metric(receipt: dict[str, Any], key: str) -> float:
    try:
        return float(dict(receipt.get("metrics") or {}).get(key) or 0.0)
    except Exception:
        return 0.0


def _receipt_source_head(receipt: dict[str, Any]) -> str:
    return str(receipt.get("source_git_head") or receipt.get("git_head") or "")


def _generated_only_receipt_delta_ok(receipt: dict[str, Any], *, current_head: str) -> bool:
    return _fresh_enough(_receipt_source_head(receipt), current_head=current_head)


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name) or default)
    except Exception:
        return float(default)


def _check_receipt(
    receipt: dict[str, Any],
    *,
    current_head: str,
    public_required: bool,
    direct_min_f1: float,
    conversation_min_f1: float,
    max_conversation_turn_ms: float | None = None,
    max_speech_transcribe_ms: float | None = None,
) -> list[str]:
    issues: list[str] = []
    if not receipt:
        return ["receipt_missing_or_invalid"]
    if receipt.get("contract_name") != "ea.memorial_voice_roundtrip_exit_gate":
        issues.append("contract_name_invalid")
    if str(receipt.get("status") or "").strip().lower() != "pass":
        issues.append("receipt_status_not_pass")
    if current_head and not _fresh_enough(_receipt_source_head(receipt), current_head=current_head):
        issues.append("receipt_stale_relative_to_current_head")
    if bool(receipt.get("dirty_worktree")) and not _generated_only_receipt_delta_ok(receipt, current_head=current_head):
        issues.append("receipt_generated_from_dirty_worktree")
    if receipt.get("failed_codes"):
        issues.append("receipt_failed_codes_present")
    if receipt.get("warned_codes"):
        issues.append("receipt_warned_codes_present")
    if public_required:
        if _is_local_base_url(str(receipt.get("base_url") or "")):
            issues.append("public_origin_required_not_localhost")
        if receipt.get("gold_mode") is not True:
            issues.append("public_gold_receipt_must_use_gold_mode")
        if receipt.get("require_public_origin") is not True:
            issues.append("public_gold_receipt_must_require_public_origin")
        if receipt.get("gold_claim_allowed") is not True:
            issues.append("public_gold_claim_not_allowed_by_receipt")
    if _metric(receipt, "direct_tts_f1") < direct_min_f1:
        issues.append("direct_tts_f1_below_gold_threshold")
    if _metric(receipt, "conversation_turn_audio_f1") < conversation_min_f1:
        issues.append("conversation_turn_audio_f1_below_gold_threshold")
    if max_conversation_turn_ms is not None and _metric(receipt, "conversation_turn_total_ms") > float(max_conversation_turn_ms):
        issues.append("conversation_turn_total_ms_above_gold_threshold")
    if max_speech_transcribe_ms is not None and _metric(receipt, "speech_transcribe_ms") > float(max_speech_transcribe_ms):
        issues.append("speech_transcribe_ms_above_gold_threshold")
    checks = list(receipt.get("checks") or [])
    check_codes = {str(item.get("code") or "") for item in checks if isinstance(item, dict)}
    if "present_world_route_ok" not in check_codes:
        issues.append("local_source_current_world_check_missing")
    serialized = json.dumps(receipt, ensure_ascii=False).lower()
    if "present_world_search" in serialized:
        issues.append("present_world_search_reference_forbidden")
    return issues


def _check_browser_receipt(
    receipt: dict[str, Any],
    *,
    current_head: str,
    max_first_answer_ms: float,
    require_live_stt: bool = True,
) -> list[str]:
    issues: list[str] = []
    if not receipt:
        return ["browser_receipt_missing_or_invalid"]
    if receipt.get("contract_name") != "ea.memorial_realtime_browser_exit_gate":
        issues.append("browser_contract_name_invalid")
    if str(receipt.get("status") or "").strip().lower() != "pass":
        issues.append("browser_receipt_status_not_pass")
    if current_head and not _fresh_enough(_receipt_source_head(receipt), current_head=current_head):
        issues.append("browser_receipt_stale_relative_to_current_head")
    if bool(receipt.get("dirty_worktree")) and not _generated_only_receipt_delta_ok(receipt, current_head=current_head):
        issues.append("browser_receipt_generated_from_dirty_worktree")
    if _is_local_base_url(str(receipt.get("base_url") or "")):
        issues.append("browser_public_origin_required_not_localhost")
    if receipt.get("gold_mode") is not True:
        issues.append("browser_gold_receipt_must_use_gold_mode")
    if receipt.get("require_public_origin") is not True:
        issues.append("browser_gold_receipt_must_require_public_origin")
    if receipt.get("gold_claim_allowed") is not True:
        issues.append("browser_gold_claim_not_allowed_by_receipt")
    mode = str(receipt.get("speech_transcribe_mode") or "").strip().lower()
    if require_live_stt and mode != "live":
        issues.append("browser_gold_receipt_must_use_live_stt")
    if not require_live_stt and mode not in {"text_prompt", "live"}:
        issues.append("browser_meaningful_receipt_mode_invalid")
    if receipt.get("failed_codes"):
        issues.append("browser_failed_codes_present")
    if float(receipt.get("first_answer_ms") or 0.0) > float(max_first_answer_ms):
        issues.append("browser_first_answer_ms_above_gold_threshold")
    if not bool(receipt.get("audio_ready_for_ui")):
        issues.append("browser_audio_not_ready_for_ui")
    if not bool(receipt.get("answer_text_visible")):
        issues.append("browser_answer_text_not_visible")
    if not bool(receipt.get("ui_audio_play_calls")):
        issues.append("browser_audio_playback_not_started")
    if not bool(receipt.get("ui_audio_play_ended")) and not receipt.get("ui_audio_play_error"):
        issues.append("browser_audio_playback_not_completed")
    if not bool(receipt.get("answer_semantic_passed")):
        issues.append("browser_answer_semantics_not_proven")
    return issues


def _check_room_receipt(
    receipt: dict[str, Any],
    *,
    current_head: str,
) -> list[str]:
    issues: list[str] = []
    if not receipt:
        return ["room_receipt_missing_or_invalid"]
    if receipt.get("contract_name") != "ea.memorial_room_audio_public_origin":
        issues.append("room_contract_name_invalid")
    if str(receipt.get("status") or "").strip().lower() != "pass":
        issues.append("room_receipt_status_not_pass")
    if current_head and not _fresh_enough(_receipt_source_head(receipt), current_head=current_head):
        issues.append("room_receipt_stale_relative_to_current_head")
    if bool(receipt.get("dirty_worktree")) and not _generated_only_receipt_delta_ok(receipt, current_head=current_head):
        issues.append("room_receipt_generated_from_dirty_worktree")
    if _is_local_base_url(str(receipt.get("base_url") or "")):
        issues.append("room_public_origin_required_not_localhost")
    if receipt.get("require_public_origin") is not True:
        issues.append("room_receipt_must_require_public_origin")
    required = {
        "actual_device_checked",
        "actual_speaker_checked",
        "first_syllable_not_clipped",
        "intelligibility_confirmed",
        "answer_text_fallback_visible",
        "no_internet_search_confirmed",
    }
    checks = dict(receipt.get("checks") or {})
    for key in sorted(required):
        if checks.get(key) is not True:
            issues.append(f"room_{key}_missing")
    if not str(receipt.get("reviewer") or "").strip():
        issues.append("room_reviewer_missing")
    return issues


def _should_require_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def main() -> int:
    current_head = _git_head()
    max_conversation_turn_ms = _float_env("MEMORIAL_GOLD_MAX_CONVERSATION_TURN_MS", 4500.0)
    max_speech_transcribe_ms = _float_env("MEMORIAL_GOLD_MAX_SPEECH_TRANSCRIBE_MS", 2500.0)
    max_browser_first_answer_ms = _float_env("MEMORIAL_GOLD_MAX_BROWSER_FIRST_ANSWER_MS", 4500.0)
    local = _json(LOCAL_RECEIPT)
    local_issues = _check_receipt(
        local,
        current_head=current_head,
        public_required=False,
        direct_min_f1=0.90,
        conversation_min_f1=0.90,
    )

    public_receipt_path = Path(os.getenv("MEMORIAL_PUBLIC_VOICE_RECEIPT") or PUBLIC_RECEIPT)
    public = _json(public_receipt_path)
    public_issues = _check_receipt(
        public,
        current_head=current_head,
        public_required=True,
        direct_min_f1=0.92,
        conversation_min_f1=0.90,
        max_conversation_turn_ms=max_conversation_turn_ms,
        max_speech_transcribe_ms=max_speech_transcribe_ms,
    )
    browser_receipt_path = Path(os.getenv("MEMORIAL_PUBLIC_BROWSER_RECEIPT") or BROWSER_RECEIPT)
    browser = _json(browser_receipt_path)
    browser_issues = _check_browser_receipt(
        browser,
        current_head=current_head,
        max_first_answer_ms=max_browser_first_answer_ms,
    )

    meaningful_browser_issues: list[str] = []
    meaningful_browser_receipt_path = Path(os.getenv("MEMORIAL_PUBLIC_MEANINGFUL_BROWSER_RECEIPT") or MEANINGFUL_BROWSER_RECEIPT)
    if _should_require_truthy(os.getenv("MEMORIAL_REQUIRE_MEANINGFUL_BROWSER_RECEIPT")):
        meaningful_browser_receipt = _json(meaningful_browser_receipt_path)
        meaningful_browser_issues = _check_browser_receipt(
            meaningful_browser_receipt,
            current_head=current_head,
            max_first_answer_ms=_float_env(
                "MEMORIAL_GOLD_MAX_MEANINGFUL_BROWSER_FIRST_ANSWER_MS",
                8000.0,
            ),
            require_live_stt=False,
        )
    room_receipt_path = Path(os.getenv("MEMORIAL_ROOM_AUDIO_RECEIPT") or ROOM_RECEIPT)
    room = _json(room_receipt_path)
    room_issues = _check_room_receipt(
        room,
        current_head=current_head,
    )

    status = (
        "pass"
        if not local_issues
        and not public_issues
        and not browser_issues
        and not meaningful_browser_issues
        and not room_issues
        else "blocked"
    )
    payload = {
        "status": status,
        "current_head": current_head,
        "claim_labels": {
            "ea_receipt_set": "EA receipt-set gold",
            "memorial_local": "Memorial local release candidate",
            "memorial_public": "Memorial public-origin gold",
        },
        "local_release_receipt": _display_path(LOCAL_RECEIPT),
        "local_release_issues": local_issues,
        "public_gold_receipt": _display_path(public_receipt_path),
        "public_gold_issues": public_issues,
        "public_browser_gold_receipt": _display_path(browser_receipt_path),
        "public_browser_gold_issues": browser_issues,
        "public_meaningful_browser_gold_receipt": _display_path(meaningful_browser_receipt_path),
        "public_meaningful_browser_gold_issues": meaningful_browser_issues,
        "room_audio_receipt": _display_path(room_receipt_path),
        "room_audio_issues": room_issues,
        "gold_thresholds": {
            "direct_tts_f1_min": 0.92,
            "conversation_turn_audio_f1_min": 0.90,
            "conversation_turn_total_ms_max": max_conversation_turn_ms,
            "speech_transcribe_ms_max": max_speech_transcribe_ms,
            "browser_first_answer_ms_max": max_browser_first_answer_ms,
        },
        "memorial_voice_gold_claim_allowed": status == "pass",
        "labels": {
            "local_receipt": "Memorial voice release-candidate proof",
            "public_receipt": "Memorial public voice provenance proof",
            "browser_receipt": "Memorial public browser realtime proof",
            "room_receipt": "Memorial public room/device playback proof",
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
