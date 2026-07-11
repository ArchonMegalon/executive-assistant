from __future__ import annotations

import argparse
import hashlib
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
DEFAULT_EVIDENCE_ROOT = DEFAULT_RECEIPT.parent
EVIDENCE_RECEIPTS = {
    "stt_benchmark": (
        "memorial_stt_provider_benchmark.generated.json",
        "ea.memorial_stt_provider_benchmark",
    ),
    "captured_candidate_diagnostic": (
        "memorial_stt_captured_candidate_diagnostic.generated.json",
        "ea.memorial_stt_captured_candidate_diagnostic",
    ),
    "voice_roundtrip": (
        "memorial_voice_roundtrip_public_origin.generated.json",
        "ea.memorial_voice_roundtrip_exit_gate",
    ),
    "realtime_browser": (
        "memorial_realtime_browser_public_origin.generated.json",
        "ea.memorial_realtime_browser_exit_gate",
    ),
    "room_audio": (
        "memorial_room_audio_public_origin.generated.json",
        "ea.memorial_room_audio_public_origin",
    ),
    "room_audio_attestation_packet": (
        "memorial_room_audio_attestation_packet.generated.json",
        "ea.memorial_room_audio_attestation_packet",
    ),
}
EVIDENCE_MAX_AGE_SECONDS = {
    "stt_benchmark": 72 * 60 * 60,
    "captured_candidate_diagnostic": 72 * 60 * 60,
    "voice_roundtrip": 72 * 60 * 60,
    "realtime_browser": 24 * 60 * 60,
    "room_audio": 30 * 24 * 60 * 60,
    "room_audio_attestation_packet": 7 * 24 * 60 * 60,
}
MANFRED_VOICE_GOLD_PATH = "/admin/memorials/manfred/gold"
MANFRED_VOICE_GOLD_LABEL = "Open voice gold"
MANFRED_PROOF_PATH = "/memorials/manfred/voice-config"
MANFRED_PROOF_LABEL = "Spoken conversation proof"
ACTION_METHOD = "get"
MANFRED_OPERATOR_ACTION_KEY = "manfred_stt_tts_realtime_conversation"


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


def _safe_nonnegative_int(value: object) -> int:
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError, OverflowError):
        return 0


def _safe_finite_float(value: object) -> float:
    try:
        parsed = float(value or 0.0)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if parsed != parsed or parsed in {float("inf"), float("-inf")}:
        return 0.0
    return round(parsed, 4)


def _safe_timestamp(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return ""
    if parsed.tzinfo is None:
        return ""
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _evidence_is_fresh(generated_at: str, *, max_age_seconds: int) -> bool:
    if not generated_at or max_age_seconds <= 0:
        return False
    try:
        observed = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return False
    if observed.tzinfo is None:
        return False
    age_seconds = (datetime.now(timezone.utc) - observed.astimezone(timezone.utc)).total_seconds()
    return -300.0 <= age_seconds <= float(max_age_seconds)


def _safe_failure_codes(value: object) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    codes: list[str] = []
    for item in list(value or []):
        normalized = str(item or "").strip()[:80]
        if normalized and normalized.replace("_", "").replace("-", "").isalnum():
            codes.append(normalized)
    return sorted(set(codes))


def _failure_codes_are_empty(value: object) -> bool:
    return isinstance(value, (list, tuple, set)) and not list(value)


def _load_evidence_receipt(
    *,
    root: Path,
    receipt_name: str,
    expected_contract: str,
    current_head: str,
    current_fingerprint: str,
    max_age_seconds: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    path = root / receipt_name
    evidence: dict[str, Any] = {
        "receipt_name": receipt_name,
        "present": False,
        "contract_name": expected_contract,
        "contract_valid": False,
        "status": "missing",
        "generated_at": "",
        "max_age_seconds": int(max_age_seconds),
        "fresh": False,
        "receipt_sha256": "",
        "source_git_head_present": False,
        "source_git_head_matches_current": False,
        "source_state_fingerprint_present": False,
        "source_state_matches_current": False,
        "raw_private_context_exposed": False,
        "raw_transcript_fields_exposed": False,
        "raw_credentials_exposed": False,
        "raw_receipt_payload_exposed": False,
    }
    try:
        raw = path.read_bytes()
    except OSError:
        return {}, evidence
    evidence["present"] = True
    evidence["receipt_sha256"] = hashlib.sha256(raw).hexdigest()
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        evidence["status"] = "invalid_json"
        return {}, evidence
    if not isinstance(parsed, dict):
        evidence["status"] = "invalid_shape"
        return {}, evidence
    payload = dict(parsed)
    contract_name = str(payload.get("contract_name") or "").strip()
    contract_valid = contract_name == expected_contract
    recorded_head = str(payload.get("source_git_head") or "").strip()
    recorded_fingerprint = str(payload.get("source_state_fingerprint") or "").strip()
    raw_status = str(payload.get("status") or "unknown").strip()
    safe_status = (
        raw_status
        if raw_status
        in {
            "blocked",
            "fail",
            "invalid",
            "pass",
            "ready",
            "skipped",
            "unknown",
            "warn",
        }
        else "unknown"
    )
    generated_at = _safe_timestamp(payload.get("generated_at") or payload.get("checked_at"))
    evidence.update(
        {
            "contract_valid": contract_valid,
            "status": safe_status,
            "generated_at": generated_at,
            "fresh": _evidence_is_fresh(
                generated_at,
                max_age_seconds=max_age_seconds,
            ),
            "source_git_head_present": bool(recorded_head),
            "source_git_head_matches_current": bool(
                recorded_head and current_head and recorded_head == current_head
            ),
            "source_state_fingerprint_present": bool(recorded_fingerprint),
            "source_state_matches_current": bool(
                recorded_fingerprint
                and current_fingerprint
                and recorded_fingerprint == current_fingerprint
                and payload.get("source_state_fingerprint_semantics")
                == "worktree_source_files_sha256_excluding_generated_only_paths"
            ),
        }
    )
    return payload if contract_valid else {}, evidence


def _full_runtime_ranking(benchmark: dict[str, Any]) -> dict[str, Any]:
    for row in list(benchmark.get("provider_ranking") or []):
        if isinstance(row, dict) and str(row.get("provider") or "").strip() == "full_runtime":
            return dict(row)
    return {}


def _operator_status_from_receipts(
    receipt_root: str | Path = DEFAULT_EVIDENCE_ROOT,
) -> dict[str, Any]:
    root = Path(receipt_root)
    current_head = resolve_source_state_head(REPO_ROOT)
    current_fingerprint = resolve_source_worktree_fingerprint(REPO_ROOT)
    receipts: dict[str, dict[str, Any]] = {}
    evidence: dict[str, dict[str, Any]] = {}
    for key, (receipt_name, expected_contract) in EVIDENCE_RECEIPTS.items():
        payload, receipt_evidence = _load_evidence_receipt(
            root=root,
            receipt_name=receipt_name,
            expected_contract=expected_contract,
            current_head=current_head,
            current_fingerprint=current_fingerprint,
            max_age_seconds=EVIDENCE_MAX_AGE_SECONDS[key],
        )
        receipts[key] = payload
        evidence[key] = receipt_evidence

    benchmark = receipts["stt_benchmark"]
    benchmark_evidence = evidence["stt_benchmark"]
    ranking = _full_runtime_ranking(benchmark)
    captured_rows = [
        dict(row)
        for row in list(benchmark.get("rows") or [])
        if isinstance(row, dict) and str(row.get("variant") or "").strip() == "captured"
    ]
    captured_rows_pass = bool(captured_rows) and all(
        dict(row.get("full_runtime") or {}).get("passed") is True for row in captured_rows
    )
    captured_benchmark_ready = bool(
        benchmark_evidence.get("contract_valid")
        and benchmark_evidence.get("source_state_matches_current")
        and benchmark_evidence.get("fresh")
        and benchmark.get("status") == "pass"
        and benchmark.get("fixture_quality_status") == "pass"
        and _failure_codes_are_empty(benchmark.get("fixture_quality_failed_codes"))
        and captured_rows_pass
        and ranking.get("production_eligible") is True
    )
    stt = {
        "status": "pass" if captured_benchmark_ready else "blocked",
        "production_eligible": captured_benchmark_ready,
        "production_provider": "full_runtime",
        "provider_label": "full_runtime",
        "passed_samples": _safe_nonnegative_int(ranking.get("passed_samples")),
        "sample_count": _safe_nonnegative_int(ranking.get("sample_count")),
        "avg_token_f1": _safe_finite_float(ranking.get("avg_token_f1")),
        "avg_wer": _safe_finite_float(ranking.get("avg_wer")),
        "ground_truth_fixture_mode": "captured_external" if captured_rows else "synthetic_only",
        "real_captured_fixture_status": (
            "captured_candidate_benchmark_pass"
            if captured_benchmark_ready
            else "captured_candidate_diagnostic_blocked"
        ),
        "next_action": (
            "" if captured_benchmark_ready else "rerun_operator_local_full_text_benchmark_or_correct_ground_truth_transcript"
        ),
        "receipt_path": f".codex-studio/published/{EVIDENCE_RECEIPTS['stt_benchmark'][0]}",
        "scoring": {
            "raw_transcript_fields": False,
            "redacted_text_fields": True,
        },
    }

    diagnostic_receipt = receipts["captured_candidate_diagnostic"]
    diagnostic_evidence = evidence["captured_candidate_diagnostic"]
    diagnostic_ready = bool(
        diagnostic_evidence.get("contract_valid")
        and diagnostic_evidence.get("source_state_matches_current")
        and diagnostic_evidence.get("fresh")
        and diagnostic_receipt.get("status") in {"pass", "ready"}
        and diagnostic_receipt.get("promotion_allowed") is True
        and diagnostic_receipt.get("may_update_fixture_manifest") is True
        and _failure_codes_are_empty(
            dict(diagnostic_receipt.get("blocker_summary") or {}).get("row_failure_codes")
        )
    )
    blocker_summary = dict(diagnostic_receipt.get("blocker_summary") or {})
    raw_diagnostic_status = str(diagnostic_receipt.get("diagnostic_status") or "missing").strip()
    diagnostic = {
        "status": "ready" if diagnostic_ready else "blocked",
        "diagnostic_status": (
            raw_diagnostic_status
            if raw_diagnostic_status in {"blocked", "fail", "missing", "pass", "ready"}
            else "unknown"
        ),
        "promotion_allowed": diagnostic_ready,
        "may_update_fixture_manifest": diagnostic_ready,
        "captured_row_count": _safe_nonnegative_int(diagnostic_receipt.get("captured_row_count")),
        "row_failure_codes": _safe_failure_codes(blocker_summary.get("row_failure_codes")),
        "next_action": (
            "" if diagnostic_ready else "rerun_operator_local_full_text_benchmark_or_correct_ground_truth_transcript"
        ),
        "receipt_path": f".codex-studio/published/{EVIDENCE_RECEIPTS['captured_candidate_diagnostic'][0]}",
        "privacy": {
            "candidate_raw_text_fields": False,
            "raw_transcript_fields": False,
            "redacted_text_fields": True,
        },
    }

    roundtrip = receipts["voice_roundtrip"]
    roundtrip_evidence = evidence["voice_roundtrip"]
    roundtrip_ready = bool(
        roundtrip_evidence.get("contract_valid")
        and roundtrip_evidence.get("source_state_matches_current")
        and roundtrip_evidence.get("fresh")
        and roundtrip.get("status") == "pass"
        and roundtrip.get("gold_claim_allowed") is True
        and _failure_codes_are_empty(roundtrip.get("failed_codes"))
    )
    browser = receipts["realtime_browser"]
    browser_evidence = evidence["realtime_browser"]
    browser_ready = bool(
        browser_evidence.get("contract_valid")
        and browser_evidence.get("source_state_matches_current")
        and browser_evidence.get("fresh")
        and browser.get("status") == "pass"
        and _failure_codes_are_empty(browser.get("failed_codes"))
        and browser.get("audio_ready_for_ui") is True
        and _safe_nonnegative_int(browser.get("ui_audio_play_ended")) >= 1
    )
    room_audio = receipts["room_audio"]
    room_evidence = evidence["room_audio"]
    room_audio_ready = bool(
        room_evidence.get("contract_valid")
        and room_evidence.get("source_state_matches_current")
        and room_evidence.get("fresh")
        and room_audio.get("status") == "pass"
        and room_audio.get("gold_claim_allowed") is True
        and _failure_codes_are_empty(room_audio.get("failed_codes"))
    )
    roundtrip_metrics = dict(roundtrip.get("metrics") or {})
    tts_automated_ready = roundtrip_ready and browser_ready
    tts = {
        "status": "pass" if tts_automated_ready else "blocked",
        "premium_status": "pass" if tts_automated_ready and room_audio_ready else "blocked",
        "direct_tts_audio_status": "pass" if roundtrip_ready else "blocked",
        "conversation_turn_audio_status": "pass" if roundtrip_ready else "blocked",
        "direct_tts_f1": _safe_finite_float(roundtrip_metrics.get("direct_tts_f1")),
        "conversation_turn_audio_f1": _safe_finite_float(
            roundtrip_metrics.get("conversation_turn_audio_f1")
        ),
        "browser_audio_ready_for_ui": browser_ready,
        "browser_audio_transport": "ui_playback_probe",
        "browser_play_calls": _safe_nonnegative_int(browser.get("ui_audio_play_calls")),
        "browser_play_ended": _safe_nonnegative_int(browser.get("ui_audio_play_ended")),
        "room_audio_receipt": "pass" if room_audio_ready else "blocked",
        "premium_failed_codes": sorted(
            set(
                ([] if roundtrip_ready else ["voice_roundtrip_not_current"])
                + ([] if browser_ready else ["browser_audio_not_current"])
                + ([] if room_audio_ready else ["room_audio_attestation_not_pass"])
            )
        ),
        "next_action": "" if room_audio_ready else "collect_real_room_audio_attestation",
        "receipt_path": f".codex-studio/published/{EVIDENCE_RECEIPTS['voice_roundtrip'][0]}",
        "browser_receipt_path": f".codex-studio/published/{EVIDENCE_RECEIPTS['realtime_browser'][0]}",
        "room_audio_receipt_path": f".codex-studio/published/{EVIDENCE_RECEIPTS['room_audio'][0]}",
    }

    packet = receipts["room_audio_attestation_packet"]
    packet_evidence = evidence["room_audio_attestation_packet"]
    packet_required_ids = [
        str(item.get("id") or "").strip()
        for item in list(packet.get("required_checks") or [])
        if isinstance(item, dict) and str(item.get("id") or "").strip() in REQUIRED_ROOM_CHECK_IDS
    ]
    attestation_ready = bool(
        packet_evidence.get("contract_valid")
        and packet_evidence.get("source_state_matches_current")
        and packet_evidence.get("fresh")
        and packet.get("status") == "ready"
        and packet.get("manual_only") is True
        and packet.get("ci_must_not_auto_assert") is True
        and all(check_id in packet_required_ids for check_id in REQUIRED_ROOM_CHECK_IDS)
    )
    attestation = {
        "status": "ready" if attestation_ready else "blocked",
        "manual_only": packet.get("manual_only") is True,
        "ci_must_not_auto_assert": packet.get("ci_must_not_auto_assert") is True,
        "required_check_ids": packet_required_ids,
        "operator_command": (
            "make materialize-memorial-room-audio-gold-clean"
            if packet.get("operator_command") == "make materialize-memorial-room-audio-gold-clean"
            else ""
        ),
        "next_action": "collect_real_room_audio_attestation",
        "receipt_path": f".codex-studio/published/{EVIDENCE_RECEIPTS['room_audio_attestation_packet'][0]}",
        "source_state_matches_current": bool(packet_evidence.get("source_state_matches_current")),
        "evidence_fresh": bool(packet_evidence.get("fresh")),
    }

    ready = (
        captured_benchmark_ready
        and diagnostic_ready
        and tts_automated_ready
        and room_audio_ready
        and attestation_ready
    )
    return {
        "status": "pass" if ready else "blocked",
        "current_label": (
            "Memorial public-origin gold: pass" if ready else "Memorial public-origin gold: blocked"
        ),
        "room_audio_receipt": "pass" if room_audio_ready else "missing_or_blocked",
        "spoken_conversation_stt": stt,
        "captured_candidate_diagnostic": diagnostic,
        "spoken_conversation_tts": tts,
        "room_audio_attestation_packet": attestation,
        "input_evidence": evidence,
    }


def _sanitize_provided_operator_status(status: dict[str, Any]) -> dict[str, Any]:
    raw_stt = dict(status.get("spoken_conversation_stt") or {})
    captured_ready = (
        raw_stt.get("status") == "pass"
        and raw_stt.get("production_eligible") is True
        and raw_stt.get("real_captured_fixture_status") == "captured_candidate_benchmark_pass"
    )
    stt = {
        "status": "pass" if captured_ready else "blocked",
        "production_eligible": captured_ready,
        "production_provider": "full_runtime",
        "provider_label": "full_runtime",
        "passed_samples": _safe_nonnegative_int(raw_stt.get("passed_samples")),
        "sample_count": _safe_nonnegative_int(raw_stt.get("sample_count")),
        "avg_token_f1": _safe_finite_float(raw_stt.get("avg_token_f1")),
        "avg_wer": _safe_finite_float(raw_stt.get("avg_wer")),
        "ground_truth_fixture_mode": (
            "captured_external"
            if raw_stt.get("ground_truth_fixture_mode") == "captured_external"
            else "synthetic_only"
        ),
        "real_captured_fixture_status": (
            "captured_candidate_benchmark_pass"
            if captured_ready
            else "captured_candidate_diagnostic_blocked"
        ),
        "next_action": (
            "" if captured_ready else "rerun_operator_local_full_text_benchmark_or_correct_ground_truth_transcript"
        ),
        "receipt_path": ".codex-studio/published/memorial_stt_provider_benchmark.generated.json",
        "scoring": {
            "raw_transcript_fields": False,
            "redacted_text_fields": True,
        },
    }

    raw_diagnostic = dict(status.get("captured_candidate_diagnostic") or {})
    diagnostic_ready = bool(
        raw_diagnostic.get("status") in {"pass", "ready"}
        and raw_diagnostic.get("promotion_allowed") is True
    )
    diagnostic = {
        "status": "ready" if diagnostic_ready else "blocked",
        "diagnostic_status": "ready" if diagnostic_ready else "blocked",
        "promotion_allowed": diagnostic_ready,
        "may_update_fixture_manifest": diagnostic_ready,
        "captured_row_count": _safe_nonnegative_int(raw_diagnostic.get("captured_row_count")),
        "row_failure_codes": _safe_failure_codes(raw_diagnostic.get("row_failure_codes")),
        "next_action": (
            "" if diagnostic_ready else "rerun_operator_local_full_text_benchmark_or_correct_ground_truth_transcript"
        ),
        "receipt_path": ".codex-studio/published/memorial_stt_captured_candidate_diagnostic.generated.json",
        "privacy": {
            "candidate_raw_text_fields": False,
            "raw_transcript_fields": False,
            "redacted_text_fields": True,
        },
    }

    raw_tts = dict(status.get("spoken_conversation_tts") or {})
    tts_automated_ready = bool(
        raw_tts.get("status") == "pass"
        and raw_tts.get("direct_tts_audio_status") == "pass"
        and raw_tts.get("conversation_turn_audio_status") == "pass"
        and raw_tts.get("browser_audio_ready_for_ui") is True
    )
    room_audio_ready = bool(
        status.get("room_audio_receipt") == "pass"
        and raw_tts.get("room_audio_receipt") == "pass"
        and raw_tts.get("premium_status") == "pass"
    )
    tts = {
        "status": "pass" if tts_automated_ready else "blocked",
        "premium_status": "pass" if tts_automated_ready and room_audio_ready else "blocked",
        "direct_tts_audio_status": "pass" if tts_automated_ready else "blocked",
        "conversation_turn_audio_status": "pass" if tts_automated_ready else "blocked",
        "direct_tts_f1": _safe_finite_float(raw_tts.get("direct_tts_f1")),
        "conversation_turn_audio_f1": _safe_finite_float(
            raw_tts.get("conversation_turn_audio_f1")
        ),
        "browser_audio_ready_for_ui": tts_automated_ready,
        "browser_audio_transport": "ui_playback_probe",
        "browser_play_calls": _safe_nonnegative_int(raw_tts.get("browser_play_calls")),
        "browser_play_ended": _safe_nonnegative_int(raw_tts.get("browser_play_ended")),
        "room_audio_receipt": "pass" if room_audio_ready else "blocked",
        "premium_failed_codes": (
            [] if tts_automated_ready and room_audio_ready else ["room_audio_attestation_not_pass"]
        ),
        "next_action": "" if room_audio_ready else "collect_real_room_audio_attestation",
        "receipt_path": ".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json",
        "browser_receipt_path": ".codex-studio/published/memorial_realtime_browser_public_origin.generated.json",
        "room_audio_receipt_path": ".codex-studio/published/memorial_room_audio_public_origin.generated.json",
    }

    raw_attestation = dict(status.get("room_audio_attestation_packet") or {})
    required_check_ids = [
        check_id
        for check_id in REQUIRED_ROOM_CHECK_IDS
        if check_id in list(raw_attestation.get("required_check_ids") or [])
    ]
    attestation_ready = bool(
        raw_attestation.get("status") == "ready"
        and raw_attestation.get("manual_only") is True
        and raw_attestation.get("ci_must_not_auto_assert") is True
        and all(check_id in required_check_ids for check_id in REQUIRED_ROOM_CHECK_IDS)
    )
    attestation = {
        "status": "ready" if attestation_ready else "blocked",
        "manual_only": raw_attestation.get("manual_only") is True,
        "ci_must_not_auto_assert": raw_attestation.get("ci_must_not_auto_assert") is True,
        "required_check_ids": required_check_ids,
        "operator_command": (
            "make materialize-memorial-room-audio-gold-clean"
            if raw_attestation.get("operator_command") == "make materialize-memorial-room-audio-gold-clean"
            else ""
        ),
        "next_action": "collect_real_room_audio_attestation",
        "receipt_path": ".codex-studio/published/memorial_room_audio_attestation_packet.generated.json",
    }
    # Supplied status is a test/in-process compatibility seam, not authenticated
    # current evidence. It may describe nested readiness, but it cannot promote
    # the public claim without the receipt-aggregation path.
    all_ready = False
    return {
        "status": "pass" if all_ready else "blocked",
        "current_label": (
            "Memorial public-origin gold: pass"
            if all_ready
            else "Memorial public-origin gold: blocked"
        ),
        "room_audio_receipt": "pass" if room_audio_ready else "missing_or_blocked",
        "spoken_conversation_stt": stt,
        "captured_candidate_diagnostic": diagnostic,
        "spoken_conversation_tts": tts,
        "room_audio_attestation_packet": attestation,
    }


def _readiness_blocked_checks(
    *,
    stt: dict[str, Any],
    diagnostic: dict[str, Any],
    tts: dict[str, Any],
    attestation: dict[str, Any],
    room_audio_receipt: object,
    evidence_source: str,
) -> list[str]:
    blocked: list[str] = []
    if evidence_source != "receipt_aggregation":
        blocked.append("current_evidence_aggregation_required")
    if stt.get("real_captured_fixture_status") != "captured_candidate_benchmark_pass":
        blocked.append("real_captured_stt_fixture_ready")
    if diagnostic.get("status") != "ready" or diagnostic.get("promotion_allowed") is not True:
        blocked.append("captured_candidate_diagnostic_clean")
    if tts.get("room_audio_receipt") != "pass" or tts.get("premium_status") != "pass":
        blocked.append("room_audio_receipt_passed")
    required_ids = list(attestation.get("required_check_ids") or [])
    attestation_ready = bool(
        attestation.get("status") == "ready"
        and attestation.get("manual_only") is True
        and attestation.get("ci_must_not_auto_assert") is True
        and all(check in required_ids for check in REQUIRED_ROOM_CHECK_IDS)
    )
    if evidence_source == "receipt_aggregation":
        attestation_ready = bool(
            attestation_ready
            and attestation.get("source_state_matches_current") is True
            and attestation.get("evidence_fresh") is True
        )
    if not attestation_ready or room_audio_receipt != "pass":
        blocked.append("manual_room_checks_confirmed")
    return blocked


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


def _operator_action_packet(
    *,
    ready: bool,
    blocked_checks: list[str],
    next_action_surface: dict[str, str],
    attestation: dict[str, Any],
) -> dict[str, Any]:
    required_check_ids = [
        str(item).strip()
        for item in list(attestation.get("required_check_ids") or [])
        if str(item).strip()
    ]
    manual_only = attestation.get("manual_only") is True
    common = {
        "operator_action_key": MANFRED_OPERATOR_ACTION_KEY if not ready else "",
        "kind": "manual_room_audio_attestation",
        "next_action": str(next_action_surface.get("next_action") or ""),
        "next_action_href": str(next_action_surface.get("next_action_href") or ""),
        "next_action_label": str(next_action_surface.get("next_action_label") or ""),
        "next_action_method": str(next_action_surface.get("next_action_method") or ACTION_METHOD).lower(),
        "manual_only": manual_only,
        "ci_must_not_auto_assert": attestation.get("ci_must_not_auto_assert") is True,
        "required_check_ids": required_check_ids,
        "required_check_count": len(required_check_ids),
        "blocked_checks": list(blocked_checks),
        "quiet_hours_respected": True,
        "non_action_progress_push_allowed": False,
        "irreversible_actions_consent_gated": True,
        "raw_private_context_exposed": False,
        "raw_chat_ids_exposed": False,
        "raw_token_exposed": False,
        "raw_secret_exposed": False,
        "raw_transcript_fields_exposed": False,
        "candidate_raw_text_fields_exposed": False,
        "raw_voice_ids_exposed": False,
    }
    if ready:
        return {
            **common,
            "status": "not_required",
            "user_action_required": False,
            "action_required_reason": "",
            "instruction": "Review the Manfred realtime conversation in a real room before widening product claims.",
            "delivery_policy": "queue_only",
            "telegram_push_allowed": False,
            "interruption_budget": "none",
        }
    return {
        **common,
        "status": "action_required",
        "user_action_required": True,
        "action_required_reason": "real_room_realtime_proof_missing",
        "instruction": "Capture the manual real-room audio attestation for the Manfred spoken conversation proof. CI must not auto-assert this.",
        "delivery_policy": "action_required_only",
        "telegram_push_allowed": True,
        "interruption_budget": "action_required",
        "required_next_receipt": "consented Manfred STT/TTS realtime conversation proof",
        "claim_boundary": "does_not_prove_realtime_conversation_until_real_room_audio_and_operator_acceptance_are_recorded",
    }


def materialize_manfred_realtime_conversation_readiness(
    *,
    receipt_path: str | Path,
    generated_at: str = "",
    operator_status: dict[str, Any] | None = None,
    refresh: bool = True,
) -> dict[str, Any]:
    if operator_status is not None:
        status = _sanitize_provided_operator_status(operator_status)
        evidence_source = "provided_operator_status"
    elif refresh:
        status = _operator_status_from_receipts()
        evidence_source = "receipt_aggregation"
    else:
        status = _sanitize_provided_operator_status(_default_operator_status())
        evidence_source = "conservative_default"
    stt = dict(status.get("spoken_conversation_stt") or {})
    diagnostic = dict(status.get("captured_candidate_diagnostic") or {})
    tts = dict(status.get("spoken_conversation_tts") or {})
    attestation = dict(status.get("room_audio_attestation_packet") or {})
    blocked = _readiness_blocked_checks(
        stt=stt,
        diagnostic=diagnostic,
        tts=tts,
        attestation=attestation,
        room_audio_receipt=status.get("room_audio_receipt"),
        evidence_source=evidence_source,
    )
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
        "generated_by": "ea/scripts/materialize_manfred_realtime_conversation_readiness.py",
        "status": "ready_for_realtime_conversation_review" if ready else "blocked_realtime_prerequisites",
        "generated_at": generated_at or _now(),
        **_source_state(),
        "current_label": status.get("current_label"),
        "operator_status": status.get("status"),
        "ready_for_realtime_conversation_review": ready,
        "realtime_conversation_claim_allowed": False,
        "premium_spoken_claim_allowed": False,
        "goal_completion_claim_allowed": False,
        "blocked_checks": blocked,
        "evidence_source": evidence_source,
        "input_evidence": (
            dict(status.get("input_evidence") or {})
            if evidence_source == "receipt_aggregation"
            else {}
        ),
        "operator_action_key": "" if ready else MANFRED_OPERATOR_ACTION_KEY,
        "operator_action": _operator_action_packet(
            ready=ready,
            blocked_checks=blocked,
            next_action_surface=next_action_surface,
            attestation=attestation,
        ),
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
