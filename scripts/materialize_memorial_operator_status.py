#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

try:
    from scripts.source_state_head import resolve_source_state_head, source_worktree_metadata
except ModuleNotFoundError:  # pragma: no cover - script execution path
    from source_state_head import resolve_source_state_head, source_worktree_metadata

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ".codex-design" / "product" / "MEMORIAL_OPERATOR_STATUS.generated.json"
WHOLE_PROJECT_GOLD_MAP = ROOT / ".codex-design" / "product" / "WHOLE_PROJECT_GOLD_MAP.generated.json"
MEANINGFUL_BROWSER_RECEIPT = ROOT / ".codex-studio" / "published" / "memorial_realtime_browser_meaningful_public_origin.generated.json"
PUBLIC_VOICE_RECEIPT = ROOT / ".codex-studio" / "published" / "memorial_voice_roundtrip_public_origin.generated.json"
PUBLIC_BROWSER_RECEIPT = ROOT / ".codex-studio" / "published" / "memorial_realtime_browser_public_origin.generated.json"
ROOM_AUDIO_RECEIPT = ROOT / ".codex-studio" / "published" / "memorial_room_audio_public_origin.generated.json"
ROOM_AUDIO_ATTESTATION_PACKET = ROOT / ".codex-studio" / "published" / "memorial_room_audio_attestation_packet.generated.json"
STT_PROVIDER_BENCHMARK_RECEIPT = ROOT / ".codex-studio" / "published" / "memorial_stt_provider_benchmark.generated.json"
STT_FIXTURE_CANDIDATE_RECEIPT = ROOT / ".codex-studio" / "published" / "memorial_stt_fixture_candidate.generated.json"
STT_CAPTURED_CANDIDATE_BENCHMARK_RECEIPT = (
    ROOT / ".codex-studio" / "published" / "memorial_stt_provider_benchmark_captured_candidate.generated.json"
)
STT_CAPTURED_CANDIDATE_DIAGNOSTIC_RECEIPT = (
    ROOT / ".codex-studio" / "published" / "memorial_stt_captured_candidate_diagnostic.generated.json"
)
STT_CAPTURE_DISCOVERY_RECEIPT = ROOT / ".codex-studio" / "published" / "memorial_stt_capture_discovery.generated.json"


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _run_json(script: str) -> dict:
    proc = subprocess.run(
        [sys.executable, str(ROOT / script)],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=ROOT,
    )
    output = (proc.stdout or "").strip() or (proc.stderr or "").strip()
    try:
        return json.loads(output or "{}")
    except Exception:
        return {"status": "error", "script": script, "stdout": proc.stdout[:800], "stderr": proc.stderr[:800]}


def _load_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _receipt_state(path: Path) -> str:
    payload = _load_json(path)
    if str(payload.get("status") or "").strip().lower() == "pass":
        return "pass"
    if path.exists():
        return "blocked"
    return "missing_or_blocked"


def _receipt_git_head(path: Path) -> str:
    payload = _load_json(path)
    return str(payload.get("git_head") or payload.get("source_git_head") or "").strip()


def _workflow_backing_status(*receipts: Path) -> dict[str, object]:
    for receipt in receipts:
        payload = _load_json(receipt)
        if not payload:
            continue
        run_id = str(payload.get("workflow_run_id") or payload.get("github_run_id") or "").strip()
        artifact_id = str(payload.get("workflow_artifact_id") or payload.get("github_artifact_id") or "").strip()
        if run_id or artifact_id:
            return {
                "status": "yes",
                "available": True,
                "workflow_run_id": run_id,
                "artifact_id": artifact_id,
            }
    return {
        "status": "no",
        "available": False,
        "reason": "no_workflow_receipt_marker_present",
    }


def _public_voice_receipt_semantics() -> dict[str, object]:
    payload = _load_json(PUBLIC_VOICE_RECEIPT)
    metrics = dict(payload.get("metrics") or {})
    direct = str(metrics.get("direct_tts_transcriber") or payload.get("direct_tts_transcriber") or "").strip()
    conversation = str(
        metrics.get("conversation_turn_transcriber") or payload.get("conversation_turn_transcriber") or ""
    ).strip()
    provenance_cache = {direct, conversation} == {"memorial_tts_provenance_cache"}
    return {
        "label": "Memorial public voice provenance proof" if provenance_cache else "Memorial public voice gold proof",
        "transcriber_mode": "provenance_cache" if provenance_cache else "runtime_or_external_stt",
        "direct_tts_transcriber": direct,
        "conversation_turn_transcriber": conversation,
    }


def _spoken_stt_provider_benchmark_status() -> dict[str, object]:
    payload = _load_json(STT_PROVIDER_BENCHMARK_RECEIPT)
    if not payload:
        return {
            "status": "missing_or_blocked",
            "receipt_status": "missing",
            "production_eligible": False,
            "best_provider": "",
            "production_provider": "",
            "top_candidate_provider": "",
            "passed_samples": 0,
            "sample_count": 0,
            "receipt_path": _display_path(STT_PROVIDER_BENCHMARK_RECEIPT),
            "reason": "stt_provider_benchmark_receipt_missing",
        }
    ranking = [dict(item) for item in list(payload.get("provider_ranking") or []) if isinstance(item, dict)]
    best = ranking[0] if ranking else {}
    production_eligible = bool(best.get("production_eligible"))
    receipt_status = str(payload.get("status") or "blocked").strip().lower() or "blocked"
    status = "pass" if receipt_status == "pass" and production_eligible else "blocked"
    provider = str(best.get("provider") or "").strip()
    availability = dict(payload.get("availability") or {})
    cartesia = dict(availability.get("cartesia") or {})
    rows = [dict(item) for item in list(payload.get("rows") or []) if isinstance(item, dict)]
    provider_results = [dict(row.get(provider) or {}) for row in rows if isinstance(row.get(provider), dict)]
    transcribers = sorted(
        {
            str(result.get("transcriber") or "").strip()
            for result in provider_results
            if str(result.get("transcriber") or "").strip()
        }
    )
    production_transcriber = transcribers[0] if len(transcribers) == 1 else ""
    fallback_provider_statuses = [
        {
            "provider": str(item.get("provider") or "").strip(),
            "passed_samples": int(item.get("passed_samples") or 0),
            "sample_count": int(item.get("sample_count") or 0),
            "scored_samples": int(item.get("scored_samples") or 0),
            "avg_token_f1": float(item.get("avg_token_f1") or 0.0),
            "avg_wer": float(item.get("avg_wer") or 1.0),
            "production_eligible": bool(item.get("production_eligible")),
        }
        for item in ranking
        if str(item.get("provider") or "").strip() != provider
    ]
    fallback_production_eligible = any(item["production_eligible"] for item in fallback_provider_statuses)
    synthetic_rows = [
        row
        for row in rows
        if bool(dict(row.get("provenance") or {}).get("synthetic"))
    ]
    ground_truth_fixture_mode = (
        "synthetic_only"
        if rows and len(synthetic_rows) == len(rows)
        else ("mixed_or_captured" if rows else "unknown")
    )
    fixture_quality_status = str(payload.get("fixture_quality_status") or "unknown").strip().lower()
    fixture_quality_failed_codes = [
        str(item).strip()
        for item in list(payload.get("fixture_quality_failed_codes") or [])
        if str(item).strip()
    ]
    next_action = "maintain_memorial_stt_regression_corpus"
    if status == "pass" and ground_truth_fixture_mode == "synthetic_only":
        next_action = "add_real_captured_stt_fixture"
    elif fixture_quality_status == "blocked":
        next_action = "replace_memorial_stt_captured_fixtures"
    elif availability.get("cartesia_configured") is not True:
        next_action = "configure_cartesia_credentials"
    elif not production_eligible:
        next_action = "inspect_provider_accuracy_failures"
    try:
        avg_wer = float(best.get("avg_wer"))
    except (TypeError, ValueError):
        avg_wer = 1.0
    return {
        "status": status,
        "receipt_status": receipt_status,
        "production_eligible": production_eligible,
        "best_provider": provider if production_eligible else "",
        "production_provider": provider if production_eligible else "",
        "top_candidate_provider": provider,
        "provider_label": (production_transcriber or provider) if production_eligible else "no_production_stt_provider",
        "provider_key": provider,
        "production_transcriber": production_transcriber if production_eligible else "",
        "production_transcriber_set": transcribers if production_eligible else [],
        "fallback_provider_statuses": fallback_provider_statuses,
        "fallback_production_eligible": fallback_production_eligible,
        "fallback_health": "pass" if fallback_production_eligible else "blocked",
        "passed_samples": int(best.get("passed_samples") or 0),
        "sample_count": int(best.get("sample_count") or 0),
        "avg_token_f1": float(best.get("avg_token_f1") or 0.0),
        "avg_wer": avg_wer,
        "avg_latency_ms": float(best.get("avg_latency_ms") or 0.0),
        "receipt_path": _display_path(STT_PROVIDER_BENCHMARK_RECEIPT),
        "availability": availability,
        "fixture_quality_status": fixture_quality_status,
        "fixture_quality_failed_codes": fixture_quality_failed_codes,
        "ground_truth_fixture_mode": ground_truth_fixture_mode,
        "cartesia_credential_status": cartesia,
        "next_action": next_action,
        "scoring": dict(payload.get("scoring") or {}),
    }


def _stt_fixture_candidate_status() -> dict[str, object]:
    payload = _load_json(STT_FIXTURE_CANDIDATE_RECEIPT)
    if not payload:
        return {
            "status": "missing",
            "receipt_path": _display_path(STT_FIXTURE_CANDIDATE_RECEIPT),
            "next_action": "materialize_candidate_from_pcloud_with_operator_transcript_and_consent",
        }
    status = str(payload.get("status") or "blocked").strip().lower() or "blocked"
    failed_codes = [
        str(item).strip()
        for item in list(payload.get("failed_codes") or [])
        if str(item).strip()
    ]
    audio = dict(payload.get("audio") or {})
    candidate = dict(payload.get("candidate_manifest_entry") or {})
    promotion_gate = dict(payload.get("promotion_gate") or {})
    next_action = "review_candidate_for_fixture_manifest"
    if "input_wav_missing" in failed_codes:
        next_action = "select_error_bundle_with_stored_wav"
    elif "input_wav_too_large" in failed_codes:
        next_action = "cut_short_question_clip_before_fixture_promotion"
    elif "audio_not_wav" in failed_codes or "audio_duration_implausible" in failed_codes:
        next_action = "normalize_captured_audio_before_fixture_promotion"
    elif "expected_text_missing" in failed_codes or "required_tokens_missing" in failed_codes:
        next_action = "add_operator_supplied_ground_truth_transcript"
    elif "speaker_consent_missing" in failed_codes:
        next_action = "record_operator_speaker_consent"
    elif status != "pass":
        next_action = "fix_fixture_candidate_failed_codes"
    elif promotion_gate:
        next_action = str(
            promotion_gate.get("next_action")
            or "run_captured_candidate_benchmark_before_fixture_manifest"
        ).strip()
    return {
        "status": status,
        "receipt_path": _display_path(STT_FIXTURE_CANDIDATE_RECEIPT),
        "failed_codes": failed_codes,
        "candidate_scope": str(payload.get("candidate_scope") or "").strip(),
        "promotion_gate": promotion_gate,
        "bundle_id": str(dict(payload.get("bundle") or {}).get("id") or "").strip(),
        "sample": str(candidate.get("sample") or "").strip(),
        "synthetic": bool(candidate.get("synthetic")),
        "text_mode": str(payload.get("text_mode") or "").strip(),
        "raw_text_fields": bool(payload.get("raw_text_fields")),
        "audio_bytes": int(audio.get("bytes") or 0),
        "audio_duration_seconds": float(audio.get("duration_seconds") or 0.0),
        "next_action": next_action,
    }


def _captured_candidate_benchmark_status() -> dict[str, object]:
    payload = _load_json(STT_CAPTURED_CANDIDATE_BENCHMARK_RECEIPT)
    if not payload:
        return {
            "status": "missing",
            "receipt_path": _display_path(STT_CAPTURED_CANDIDATE_BENCHMARK_RECEIPT),
            "next_action": "run_opt_in_captured_candidate_benchmark",
        }
    ranking = [dict(item) for item in list(payload.get("provider_ranking") or []) if isinstance(item, dict)]
    best = ranking[0] if ranking else {}
    rows = [dict(item) for item in list(payload.get("rows") or []) if isinstance(item, dict)]
    captured_rows = [
        row
        for row in rows
        if bool(dict(row.get("provenance") or {}).get("external_bundle"))
    ]
    captured_full_runtime_rows = [dict(row.get("full_runtime") or {}) for row in captured_rows]
    captured_passed = captured_full_runtime_rows and all(row.get("passed") is True for row in captured_full_runtime_rows)
    status = str(payload.get("status") or "blocked").strip().lower() or "blocked"
    next_action = "promote_captured_candidate_to_fixture_manifest"
    if not captured_rows:
        next_action = "rerun_with_captured_candidate_bundle"
    elif not captured_passed:
        next_action = "inspect_captured_candidate_ground_truth_or_stt_failure"
    elif status != "pass":
        next_action = "inspect_non_captured_provider_failures"
    return {
        "status": status,
        "receipt_path": _display_path(STT_CAPTURED_CANDIDATE_BENCHMARK_RECEIPT),
        "best_provider": str(best.get("provider") or "").strip(),
        "production_eligible": bool(best.get("production_eligible")),
        "passed_samples": int(best.get("passed_samples") or 0),
        "sample_count": int(best.get("sample_count") or 0),
        "captured_rows": len(captured_rows),
        "captured_full_runtime_passed": bool(captured_passed),
        "captured_full_runtime_failures": [
            {
                "sample": str(row.get("sample") or "").strip(),
                "variant": str(row.get("variant") or "").strip(),
                "wer": float(dict(row.get("full_runtime") or {}).get("wer") or 1.0),
                "token_f1": float(dict(row.get("full_runtime") or {}).get("token_f1") or 0.0),
                "intent_correct": bool(dict(row.get("full_runtime") or {}).get("intent_correct")),
            }
            for row in captured_rows
            if dict(row.get("full_runtime") or {}).get("passed") is not True
        ],
        "next_action": next_action,
    }


def _captured_candidate_diagnostic_status() -> dict[str, object]:
    payload = _load_json(STT_CAPTURED_CANDIDATE_DIAGNOSTIC_RECEIPT)
    if not payload:
        return {
            "status": "missing",
            "receipt_path": _display_path(STT_CAPTURED_CANDIDATE_DIAGNOSTIC_RECEIPT),
            "promotion_allowed": False,
            "next_action": "materialize_captured_candidate_diagnostic",
        }
    blocker_summary = dict(payload.get("blocker_summary") or {})
    return {
        "status": str(payload.get("status") or "blocked").strip().lower() or "blocked",
        "diagnostic_status": str(payload.get("diagnostic_status") or "").strip(),
        "receipt_path": _display_path(STT_CAPTURED_CANDIDATE_DIAGNOSTIC_RECEIPT),
        "promotion_allowed": bool(payload.get("promotion_allowed")),
        "may_update_fixture_manifest": bool(payload.get("may_update_fixture_manifest")),
        "captured_row_count": int(payload.get("captured_row_count") or 0),
        "row_failure_codes": [
            str(code).strip()
            for code in list(blocker_summary.get("row_failure_codes") or [])
            if str(code).strip()
        ],
        "full_runtime_failed_rows": [
            {
                "sample": str(dict(row).get("sample") or "").strip(),
                "variant": str(dict(row).get("variant") or "").strip(),
                "failure_codes": [
                    str(code).strip()
                    for code in list(dict(row).get("failure_codes") or [])
                    if str(code).strip()
                ],
                "token_f1": float(dict(row).get("token_f1") or 0.0),
                "wer": float(dict(row).get("wer") or 1.0),
            }
            for row in list(blocker_summary.get("full_runtime_failed_rows") or [])
            if isinstance(row, dict)
        ],
        "privacy": dict(payload.get("privacy") or {}),
        "next_action": str(payload.get("next_action") or "").strip(),
    }


def _stt_capture_discovery_status() -> dict[str, object]:
    payload = _load_json(STT_CAPTURE_DISCOVERY_RECEIPT)
    if not payload:
        return {
            "status": "missing",
            "receipt_path": _display_path(STT_CAPTURE_DISCOVERY_RECEIPT),
            "next_action": "materialize_redacted_capture_discovery_from_selected_pcloud_bundles",
        }
    status = str(payload.get("status") or "blocked").strip().lower() or "blocked"
    failed_codes = [
        str(item).strip()
        for item in list(payload.get("failed_codes") or [])
        if str(item).strip()
    ]
    promotable_count = int(payload.get("promotable_count") or 0)
    matched_count = int(payload.get("matched_count") or 0)
    next_action = "use_promotable_discovered_capture_for_benchmark"
    if matched_count <= 0:
        next_action = "search_additional_pcloud_bundles_for_matching_capture"
    elif promotable_count <= 0 and "audio_too_short_for_expected_text" in failed_codes:
        next_action = "capture_new_real_question_audio_or_fix_truncated_logger"
    elif promotable_count <= 0:
        next_action = "inspect_discovery_failed_codes"
    return {
        "status": status,
        "receipt_path": _display_path(STT_CAPTURE_DISCOVERY_RECEIPT),
        "target_samples": list(payload.get("target_samples") or []),
        "bundle_count": int(payload.get("bundle_count") or 0),
        "matched_count": matched_count,
        "promotable_count": promotable_count,
        "failed_codes": failed_codes,
        "text_mode": str(payload.get("text_mode") or "").strip(),
        "raw_text_fields": bool(payload.get("raw_text_fields")),
        "next_action": next_action,
    }


def _reconcile_spoken_stt_next_action(
    spoken_stt_status: dict[str, object],
    stt_fixture_candidate: dict[str, object],
    captured_candidate_benchmark: dict[str, object],
    captured_candidate_diagnostic: dict[str, object] | None = None,
) -> dict[str, object]:
    status = dict(spoken_stt_status)
    if str(status.get("next_action") or "") != "add_real_captured_stt_fixture":
        return status
    diagnostic = dict(captured_candidate_diagnostic or {})
    if diagnostic and str(diagnostic.get("status") or "").strip().lower() == "blocked":
        status["real_captured_fixture_status"] = "captured_candidate_diagnostic_blocked"
        status["next_action"] = str(
            diagnostic.get("next_action")
            or "rerun_operator_local_full_text_benchmark_or_correct_ground_truth_transcript"
        ).strip()
        return status
    if diagnostic.get("promotion_allowed") is True:
        status["real_captured_fixture_status"] = "captured_candidate_diagnostic_ready"
        status["next_action"] = "promote_captured_candidate_to_fixture_manifest"
        return status
    captured_status = str(captured_candidate_benchmark.get("status") or "").strip().lower()
    captured_rows = _int_value(captured_candidate_benchmark.get("captured_rows"), 0)
    if captured_status == "pass":
        status["real_captured_fixture_status"] = "captured_candidate_benchmark_pass"
        status["next_action"] = "promote_captured_candidate_to_fixture_manifest"
        return status
    if captured_rows > 0:
        status["real_captured_fixture_status"] = "captured_candidate_benchmark_blocked"
        status["next_action"] = "inspect_captured_candidate_ground_truth_or_capture_new_audio"
        return status
    fixture_status = str(stt_fixture_candidate.get("status") or "").strip().lower()
    if fixture_status == "pass":
        status["real_captured_fixture_status"] = "candidate_ready_for_benchmark"
        status["next_action"] = "run_captured_candidate_benchmark_before_fixture_manifest"
    return status


def _int_value(value: object, default: int = 0) -> int:
    try:
        return int(float(str(value if value is not None else default).strip() or str(default)))
    except (TypeError, ValueError):
        return default


def _float_value(value: object, default: float = 0.0) -> float:
    try:
        return float(str(value if value is not None else default).strip() or str(default))
    except (TypeError, ValueError):
        return default


def _spoken_tts_playback_status() -> dict[str, object]:
    voice = _load_json(PUBLIC_VOICE_RECEIPT)
    browser = _load_json(PUBLIC_BROWSER_RECEIPT)
    voice_metrics = dict(voice.get("metrics") or {})
    browser_turn_payload = dict(browser.get("conversation_turn_payload") or {})

    direct_audio_status = str(voice_metrics.get("direct_tts_audio_status") or "").strip().lower()
    conversation_audio_status = str(voice_metrics.get("conversation_turn_audio_status") or "").strip().lower()
    direct_f1 = _float_value(voice_metrics.get("direct_tts_f1"), 0.0)
    conversation_f1 = _float_value(voice_metrics.get("conversation_turn_audio_f1"), 0.0)
    browser_status = str(browser.get("status") or "").strip().lower()
    browser_audio_ready = bool(browser.get("audio_ready_for_ui"))
    browser_audio_payload_ready = bool(browser.get("audio_payload_ready"))
    browser_audio_unavailable = bool(browser.get("audio_unavailable"))
    browser_play_calls = _int_value(browser.get("ui_audio_play_calls"))
    browser_play_ended = _int_value(browser.get("ui_audio_play_ended"))
    browser_play_error = str(browser.get("ui_audio_play_error") or "").strip()
    room_state = _receipt_state(ROOM_AUDIO_RECEIPT)

    failed_codes: list[str] = []
    if str(voice.get("status") or "").strip().lower() != "pass":
        failed_codes.append("public_voice_receipt_not_pass")
    if direct_audio_status != "pass":
        failed_codes.append("direct_tts_audio_not_pass")
    if conversation_audio_status != "pass":
        failed_codes.append("conversation_turn_audio_not_pass")
    if browser_status != "pass":
        failed_codes.append("browser_receipt_not_pass")
    if not browser_audio_ready:
        failed_codes.append("browser_audio_not_ready")
    if browser_audio_unavailable:
        failed_codes.append("browser_audio_unavailable")
    if browser_play_calls < 1:
        failed_codes.append("browser_play_call_missing")
    if browser_play_ended < 1:
        failed_codes.append("browser_play_completion_missing")
    if browser_play_error:
        failed_codes.append("browser_play_error")

    status = "pass" if not failed_codes else "blocked"
    premium_failed_codes = list(failed_codes)
    if room_state != "pass":
        premium_failed_codes.append("room_audio_attestation_not_pass")
    premium_status = "pass" if not premium_failed_codes else "blocked"
    next_action = "maintain_tts_playback_regression"
    if "room_audio_attestation_not_pass" in premium_failed_codes:
        next_action = "collect_real_room_audio_attestation"
    elif failed_codes:
        next_action = "fix_tts_or_browser_playback"

    return {
        "status": status,
        "premium_status": premium_status,
        "receipt_path": _display_path(PUBLIC_VOICE_RECEIPT),
        "browser_receipt_path": _display_path(PUBLIC_BROWSER_RECEIPT),
        "room_audio_receipt_path": _display_path(ROOM_AUDIO_RECEIPT),
        "direct_tts_audio_status": direct_audio_status,
        "conversation_turn_audio_status": conversation_audio_status,
        "direct_tts_f1": direct_f1,
        "conversation_turn_audio_f1": conversation_f1,
        "browser_audio_ready_for_ui": browser_audio_ready,
        "browser_audio_payload_ready": browser_audio_payload_ready,
        "browser_audio_transport": "embedded_payload" if browser_audio_payload_ready else "ui_playback_probe",
        "browser_audio_unavailable": browser_audio_unavailable,
        "browser_play_calls": browser_play_calls,
        "browser_play_ended": browser_play_ended,
        "browser_play_error": browser_play_error,
        "conversation_turn_payload_audio_embedded": bool(str(browser_turn_payload.get("audio_base64") or "").strip()),
        "room_audio_receipt": room_state,
        "failed_codes": list(dict.fromkeys(failed_codes)),
        "premium_failed_codes": list(dict.fromkeys(premium_failed_codes)),
        "next_action": next_action,
    }


def _room_audio_attestation_packet_status() -> dict[str, object]:
    payload = _load_json(ROOM_AUDIO_ATTESTATION_PACKET)
    if not payload:
        return {
            "status": "missing",
            "receipt_path": _display_path(ROOM_AUDIO_ATTESTATION_PACKET),
            "manual_only": True,
            "operator_command": "make materialize-memorial-room-audio-attestation-packet",
            "next_action": "materialize_manual_attestation_packet",
        }
    status = str(payload.get("status") or "").strip().lower() or "blocked"
    proof_target = str(payload.get("proof_target") or "").strip()
    required_env = dict(payload.get("required_env") or {})
    required_checks = [
        dict(item)
        for item in list(payload.get("required_checks") or [])
        if isinstance(item, dict)
    ]
    return {
        "status": status,
        "receipt_path": _display_path(ROOM_AUDIO_ATTESTATION_PACKET),
        "manual_only": bool(payload.get("manual_only") is True),
        "ci_must_not_auto_assert": bool(payload.get("ci_must_not_auto_assert") is True),
        "proof_target": proof_target,
        "operator_command": str(payload.get("operator_command") or "make materialize-memorial-room-audio-gold-clean").strip(),
        "required_env_keys": sorted(required_env.keys()),
        "required_check_ids": [
            str(item.get("id") or "").strip()
            for item in required_checks
            if str(item.get("id") or "").strip()
        ],
        "next_action": "collect_real_room_audio_attestation",
    }


def main() -> int:
    source_head = resolve_source_state_head(ROOT)
    source_worktree = source_worktree_metadata(ROOT)
    readiness = _run_json("scripts/verify_memorial_gold_readiness.py")
    whole_project = _run_json("scripts/verify_whole_project_gold_map.py")
    whole_project_map = _load_json(WHOLE_PROJECT_GOLD_MAP)
    whole_project_gold = "blocked"
    whole_project_verifier_status = str(whole_project.get("status") or "blocked").strip().lower()
    if (
        whole_project_verifier_status == "pass"
        and whole_project_map.get("gold_claim_allowed") is True
        and str(whole_project_map.get("overall_status") or "").strip().lower() == "gold"
    ):
        whole_project_gold = "pass"
    elif whole_project_map:
        whole_project_gold = "blocked"
    else:
        whole_project_gold = "unknown"

    readiness_status = str(readiness.get("status") or "blocked").strip().lower()
    has_any_readiness_issues = bool(
        list(readiness.get("local_release_issues") or [])
        or list(readiness.get("public_gold_issues") or [])
        or list(readiness.get("public_browser_gold_issues") or [])
        or list(readiness.get("room_audio_issues") or [])
    )
    memorial_public_gold_claim_allowed = (
        readiness_status == "pass"
        or (
            readiness.get("memorial_voice_gold_claim_allowed") is True
            and not has_any_readiness_issues
        )
    )
    memorial_public_gold_allowed = memorial_public_gold_claim_allowed
    final_status = "pass" if memorial_public_gold_allowed else "blocked"
    workflow_backing = _workflow_backing_status(
        PUBLIC_VOICE_RECEIPT,
        PUBLIC_BROWSER_RECEIPT,
        MEANINGFUL_BROWSER_RECEIPT,
        ROOM_AUDIO_RECEIPT,
    )
    public_voice_semantics = _public_voice_receipt_semantics()
    spoken_stt_status = _spoken_stt_provider_benchmark_status()
    stt_fixture_candidate = _stt_fixture_candidate_status()
    stt_capture_discovery = _stt_capture_discovery_status()
    captured_candidate_benchmark = _captured_candidate_benchmark_status()
    captured_candidate_diagnostic = _captured_candidate_diagnostic_status()
    spoken_stt_status = _reconcile_spoken_stt_next_action(
        spoken_stt_status,
        stt_fixture_candidate,
        captured_candidate_benchmark,
        captured_candidate_diagnostic,
    )
    spoken_tts_status = _spoken_tts_playback_status()
    room_attestation_packet = _room_audio_attestation_packet_status()
    payload = {
        "contract_name": "ea.memorial_operator_status",
        "generated_by": "scripts/materialize_memorial_operator_status.py",
        "source_git_head": source_head,
        "head_semantics": "source_state",
        "source_worktree_dirty": bool(source_worktree.get("source_worktree_dirty")),
        "source_dirty_count": int(source_worktree.get("source_dirty_count") or 0),
        "source_dirty_files": list(source_worktree.get("source_dirty_files") or []),
        "source_dirty_omitted_count": int(source_worktree.get("source_dirty_omitted_count") or 0),
        "source_dirty_status_sha256": str(source_worktree.get("source_dirty_status_sha256") or ""),
        "slug": "manfred",
        "status": final_status,
        "current_label": "Memorial public-origin gold: pass" if final_status == "pass" else "Memorial public-origin gold: blocked",
        "local_release_candidate": "pass" if not list(readiness.get("local_release_issues") or []) else "blocked",
        "public_voice_receipt": "pass" if not list(readiness.get("public_gold_issues") or []) else "missing_or_blocked",
        "public_browser_receipt": "pass" if not list(readiness.get("public_browser_gold_issues") or []) else "missing_or_blocked",
        "public_browser_meaningful_receipt": _receipt_state(MEANINGFUL_BROWSER_RECEIPT),
        "room_audio_receipt": "pass" if not list(readiness.get("room_audio_issues") or []) else "missing_or_blocked",
        "whole_project_gold": whole_project_gold,
        "operator_notes": [
            "Use labels only: Memorial local release candidate / Memorial public-origin gold: blocked|pass.",
            "Public-origin gold requires voice, browser, and room receipts at current HEAD/public origin.",
            "The current public voice receipt is a provenance proof when its transcriber mode is provenance_cache; browser + room receipts carry the intelligibility proof.",
            "source_git_head records the proved source state; a later artifact-only commit may differ without making the proof stale.",
            "whole_project_gold is reported separately and must not block a memorial-specific public-origin pass when unrelated planes remain not_gold.",
            "Manfred premium spoken conversation additionally requires spoken_conversation_stt.status=pass and spoken_conversation_tts.premium_status=pass; memorial public-origin gold alone is not a production STT/TTS claim.",
            "If source_worktree_dirty is true, the receipt is an operator snapshot with pending source changes and must not be used as final release evidence.",
            "If room_audio_receipt is missing_or_blocked, use room_audio_attestation_packet to collect the required real-room evidence; CI must not auto-assert manual room checks.",
            "If spoken_conversation_stt.ground_truth_fixture_mode is synthetic_only, use stt_fixture_candidate to promote only a consented, plausible captured clip; normalize suspect WAV/WebM captures first.",
            "If stt_capture_discovery matched bundles but has no promotable captures, the logged audio is not enough for real captured STT regression proof.",
            "If captured_candidate_benchmark is blocked, do not promote the captured clip until the operator confirms ground truth or the STT lane recognizes the captured speech.",
            "If captured_candidate_diagnostic is blocked with transcript_hash_mismatch, rerun full-text diagnostics only operator-locally or correct the ground-truth transcript; do not commit raw transcript receipts.",
        ],
        "source_head_note": "source_git_head records the source state the receipts prove. Generated-only follow-up commits may change repository HEAD without invalidating those receipts. source_worktree_dirty records whether source-relevant local changes were present when this operator snapshot was generated.",
        "artifact_paths": {
            "local_release_receipt": _display_path(ROOT / ".codex-studio/published/memorial_voice_roundtrip_exit_gate.generated.json"),
            "public_gold_receipt": _display_path(ROOT / ".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json"),
            "public_browser_gold_receipt": _display_path(ROOT / ".codex-studio/published/memorial_realtime_browser_public_origin.generated.json"),
            "public_meaningful_browser_gold_receipt": _display_path(MEANINGFUL_BROWSER_RECEIPT),
            "room_audio_receipt": _display_path(ROOT / ".codex-studio/published/memorial_room_audio_public_origin.generated.json"),
            "room_audio_attestation_packet": _display_path(ROOM_AUDIO_ATTESTATION_PACKET),
            "spoken_stt_provider_benchmark": _display_path(STT_PROVIDER_BENCHMARK_RECEIPT),
            "stt_fixture_candidate": _display_path(STT_FIXTURE_CANDIDATE_RECEIPT),
            "stt_capture_discovery": _display_path(STT_CAPTURE_DISCOVERY_RECEIPT),
            "captured_candidate_benchmark": _display_path(STT_CAPTURED_CANDIDATE_BENCHMARK_RECEIPT),
            "captured_candidate_diagnostic": _display_path(STT_CAPTURED_CANDIDATE_DIAGNOSTIC_RECEIPT),
        },
        "readiness": readiness,
        "evidence_heads": {
            "whole_project_map": str(whole_project_map.get("source_git_head") or whole_project_map.get("git_head") or "").strip(),
            "public_voice_receipt": _receipt_git_head(PUBLIC_VOICE_RECEIPT),
            "public_browser_receipt": _receipt_git_head(PUBLIC_BROWSER_RECEIPT),
            "public_meaningful_browser_receipt": _receipt_git_head(MEANINGFUL_BROWSER_RECEIPT),
            "room_audio_receipt": _receipt_git_head(ROOM_AUDIO_RECEIPT),
        },
        "workflow_backing": workflow_backing,
        "public_voice_receipt_semantics": public_voice_semantics,
        "room_audio_attestation_packet": room_attestation_packet,
        "spoken_conversation_stt": spoken_stt_status,
        "stt_fixture_candidate": stt_fixture_candidate,
        "stt_capture_discovery": stt_capture_discovery,
        "captured_candidate_benchmark": captured_candidate_benchmark,
        "captured_candidate_diagnostic": captured_candidate_diagnostic,
        "spoken_conversation_tts": spoken_tts_status,
        "whole_project": whole_project,
        "whole_project_map_summary": {
            "overall_status": whole_project_map.get("overall_status", ""),
            "gold_claim_allowed": whole_project_map.get("gold_claim_allowed"),
            "blocking_planes": list(whole_project_map.get("blocking_planes") or []),
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": final_status,
                "output": OUTPUT.as_posix(),
                "current_label": payload["current_label"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
