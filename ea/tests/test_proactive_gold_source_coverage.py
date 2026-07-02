from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import materialize_proactive_ooda_gold_acceptance as gold_acceptance  # noqa: E402
from scripts import materialize_proactive_ooda_operator_status as operator_status_receipt  # noqa: E402
from scripts import verify_proactive_ooda_gold_acceptance as gold_acceptance_verifier  # noqa: E402


def test_gold_operator_runtime_blocks_when_source_coverage_has_missing_lane() -> None:
    ready, detail = gold_acceptance._operator_runtime_source_coverage_posture(  # noqa: SLF001
        {
            "source_coverage": {
                "checked": True,
                "status": "ready_with_gaps",
                "lane_count": 8,
                "observed_lane_count": 7,
                "missing_lane_keys": ["pocket_ai_audio_transcripts"],
                "lanes": [
                    {
                        "key": "pocket_ai_audio_transcripts",
                        "observed": False,
                        "next_action": "sync_pocket_ai_audio_transcripts",
                        "missing_required_event_types": ["pocket_recording_archive_indexed"],
                    }
                ],
            }
        }
    )

    assert ready is False
    assert detail["source_coverage_ready"] is False
    assert detail["source_coverage_status"] == "ready_with_gaps"
    assert detail["source_coverage_missing_lane_keys"] == ["pocket_ai_audio_transcripts"]
    assert detail["source_coverage_missing_required_event_types"] == ["pocket_recording_archive_indexed"]
    assert detail["next_action"] == "sync_pocket_ai_audio_transcripts"


def test_gold_materializer_prefers_live_runtime_probe_when_operator_status_is_live(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    operator_status_path = tmp_path / "operator_status.json"
    output_path = tmp_path / "gold.json"
    operator_status_path.write_text(
        json.dumps(
            {
                "status": "ready_with_live_receipt",
                "live_receipt_checked": True,
                "approval_capture_surface": {"source": "docker_compose_exec"},
            }
        ),
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    def _fake_runtime_bundle(**kwargs: object) -> tuple[dict[str, object], bool]:
        captured.update(kwargs)
        return (
            {
                "run_receipt": {},
                "stage_packet": {},
                "safe_work_result": {},
                "approval_outcome": {},
            },
            False,
        )

    monkeypatch.setattr(gold_acceptance, "_runtime_artifact_bundle", _fake_runtime_bundle)
    monkeypatch.setattr(gold_acceptance, "_refresh_operator_status_snapshot", lambda path, current: current)
    monkeypatch.setattr(gold_acceptance, "_git_head", lambda path=gold_acceptance.ROOT: "head")
    monkeypatch.setattr(gold_acceptance, "_source_fingerprint", lambda path=gold_acceptance.ROOT: "fingerprint")

    receipt = gold_acceptance.materialize_proactive_ooda_gold_acceptance(
        output_path=output_path,
        operator_status_path=operator_status_path,
    )

    assert captured["allow_live_runtime_probe"] is True
    assert receipt["evidence_receipts"]["operator_status"]["status"] == "ready_with_live_receipt"


def test_gold_runtime_bundle_live_probe_prefers_current_packet_over_browse_backed_override(
    monkeypatch: object,
) -> None:
    captured: dict[str, object] = {}

    def _fake_probe(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "probe_ok": True,
            "run_receipt": {"notification_status": "sent"},
            "stage_packet": {"packet_ref": "stage_packet:current"},
            "safe_work_result": {"result_ref": "safe_work_result:current", "status": "staged_for_user_decision"},
            "approval_outcome": {},
        }

    monkeypatch.setattr(gold_acceptance.ea_live_ops, "probe_proactive_artifacts", _fake_probe)
    monkeypatch.setattr(gold_acceptance, "load_runtime_artifact_bundle", lambda **_: {})

    bundle, used_live = gold_acceptance._runtime_artifact_bundle(  # noqa: SLF001
        run_receipt_path=None,
        stage_packet_dir=None,
        safe_work_result_dir=None,
        allow_live_runtime_probe=True,
        allow_default_local_artifacts=False,
    )

    assert used_live is True
    assert captured["prefer_browse_backed_delivery"] is False
    assert dict(bundle.get("stage_packet") or {})["packet_ref"] == "stage_packet:current"


def test_gold_operator_runtime_accepts_complete_source_coverage() -> None:
    ready, detail = gold_acceptance._operator_runtime_source_coverage_posture(  # noqa: SLF001
        {
            "source_coverage": {
                "checked": True,
                "status": "ready",
                "lane_count": 8,
                "observed_lane_count": 8,
                "missing_lane_keys": [],
                "lanes": [
                    {
                        "key": "pocket_ai_audio_transcripts",
                        "observed": True,
                        "next_action": "",
                        "missing_required_event_types": [],
                    }
                ],
            }
        }
    )

    assert ready is True
    assert detail["source_coverage_ready"] is True
    assert detail["source_coverage_missing_lane_keys"] == []
    assert detail["source_coverage_missing_required_event_types"] == []


def test_gold_operator_runtime_blocks_when_operator_status_receipt_is_stale_for_current_source() -> None:
    ready, detail = gold_acceptance._operator_status_source_posture(  # noqa: SLF001
        {
            "source_git_head": "old-head",
            "source_state_fingerprint": "old-fingerprint",
        },
        current_source_git_head="new-head",
        current_source_fingerprint="new-fingerprint",
    )

    assert ready is False
    assert detail["operator_status_source_current"] is False
    assert detail["operator_status_source_git_head_matches_current"] is False
    assert detail["operator_status_source_fingerprint_matches_current"] is False
    assert detail["next_action"] == "repair_proactive_operator_runtime_posture"


def test_gold_operator_runtime_accepts_operator_status_receipt_for_current_source() -> None:
    ready, detail = gold_acceptance._operator_status_source_posture(  # noqa: SLF001
        {
            "source_git_head": "same-head",
            "source_state_fingerprint": "same-fingerprint",
        },
        current_source_git_head="same-head",
        current_source_fingerprint="same-fingerprint",
    )

    assert ready is True
    assert detail["operator_status_source_current"] is True
    assert detail["operator_status_source_git_head_matches_current"] is True
    assert detail["operator_status_source_fingerprint_matches_current"] is True


def test_browse_evidence_not_required_for_internal_action_packet() -> None:
    required, reason = gold_acceptance._browse_evidence_required(  # noqa: SLF001
        stage_packet={
            "stage": {"payload": {"work_type": "record_internal_action"}},
            "safe_work_order": {"work_type": "record_internal_action"},
        },
        safe_work_result={
            "work_type": "record_internal_action",
            "execution_receipt": {"research_search_plan": {"mode": "internal_action_surface"}},
        },
    )

    assert required is False
    assert reason in {"work_type:record_internal_action", "research_mode:internal_action_surface"}


def test_browse_evidence_required_for_compare_options_packet() -> None:
    required, reason = gold_acceptance._browse_evidence_required(  # noqa: SLF001
        stage_packet={
            "stage": {"payload": {"work_type": "compare_options", "research_query": "compare options"}},
            "safe_work_order": {"work_type": "compare_options"},
        },
        safe_work_result={
            "work_type": "compare_options",
            "execution_receipt": {"research_search_plan": {"mode": "web_search"}},
        },
    )

    assert required is True
    assert reason in {"research_or_browser_payload", "work_type:compare_options"}


def test_gold_context_grounding_blocks_assistant_grade_shortlist_without_any_grounding() -> None:
    ready, detail = gold_acceptance._operator_runtime_context_grounding_posture_for_packet(  # noqa: SLF001
        {
            "context_grounding": {
                "grounded": False,
                "item_count": 0,
                "grounded_item_count": 0,
                "ungrounded_item_count": 0,
                "applied_context_count": 0,
            }
        },
        stage_packet={
            "stage": {
                "kind": "approval_packet",
                "payload": {
                    "research_query": "Elektriker 1200 Wien",
                    "search_queries": ["Elektriker 1200 Wien"],
                },
            },
            "safe_work_order": {"work_type": "prepare_shortlist"},
        },
        safe_work_result={
            "work_type": "prepare_shortlist",
            "recommended_option_or_draft": {
                "kind": "shortlist_candidate",
                "value": {"label": "Elektriker 1200 Wien"},
            },
            "shortlist": [{"label": "Elektriker 1200 Wien"}],
        },
    )

    assert ready is False
    assert detail["context_grounding_required_for_packet"] is True
    assert detail["context_grounding_requirement_reason"] == "shortlist_present"
    assert detail["context_grounding_ready"] is False
    assert detail["next_action"] == "repair_proactive_context_grounding"


def test_gold_context_grounding_accepts_grounded_shortlist_packet() -> None:
    ready, detail = gold_acceptance._operator_runtime_context_grounding_posture_for_packet(  # noqa: SLF001
        {
            "context_grounding": {
                "grounded": True,
                "item_count": 1,
                "grounded_item_count": 1,
                "ungrounded_item_count": 0,
                "applied_context_count": 3,
                "preference_count": 1,
                "requirement_count": 1,
                "recipient_context_count": 1,
                "recipient_location_count": 1,
            }
        },
        stage_packet={
            "stage": {
                "kind": "approval_packet",
                "payload": {
                    "research_query": "Elektriker 1200 Wien",
                    "search_queries": ["Elektriker 1200 Wien"],
                },
            },
            "safe_work_order": {"work_type": "prepare_shortlist"},
        },
        safe_work_result={
            "work_type": "prepare_shortlist",
            "recommended_option_or_draft": {
                "kind": "shortlist_candidate",
                "value": {"label": "Elektriker 1200 Wien"},
            },
            "shortlist": [{"label": "Elektriker 1200 Wien"}],
        },
    )

    assert ready is True
    assert detail["context_grounding_required_for_packet"] is True
    assert detail["context_grounding_grounded"] is True
    assert detail["context_grounding_ready"] is True


def test_operator_status_surfaces_current_packet_context_grounding_from_runtime_artifacts() -> None:
    normalized = operator_status_receipt._normalized_context_grounding(  # noqa: SLF001
        {"context_grounding": {"grounded": False, "item_count": 0, "grounded_item_count": 0, "applied_context_count": 0}},
        artifact_probe={
            "stage_packet": {
                "stage": {
                    "payload": {
                        "notes": ["real_world_acceptance_missing"],
                        "requirements": ["real_review_acceptance"],
                        "recipient_context": {
                            "location": {
                                "phrases": ["1200 Wien"],
                                "postal_codes": ["1200"],
                                "city_terms": ["Wien"],
                                "country_codes": ["AT"],
                            }
                        },
                        "candidate_items": [
                            {
                                "label": "Record a signal-loop outcome",
                                "preference_assessment": {"recommendation": "ask_for_clarification"},
                            }
                        ],
                    }
                },
                "safe_work_order": {"input_contract": {}},
            },
            "safe_work_result": {
                "recommended_option_or_draft": {"kind": "shortlist_candidate", "value": {"label": "Record a signal-loop outcome"}},
                "shortlist": [{"label": "Record a signal-loop outcome"}],
            },
        },
    )

    current_packet = normalized["current_packet_context_grounding"]
    assert current_packet["grounded"] is True
    assert current_packet["item_count"] == 1
    assert current_packet["applied_context_count"] >= 4
    assert current_packet["recipient_location_count"] == 1
    assert current_packet["candidate_assessment_count"] == 1


def test_gold_context_grounding_prefers_current_packet_context_from_operator_status() -> None:
    ready, detail = gold_acceptance._operator_runtime_context_grounding_posture_for_packet(  # noqa: SLF001
        {
            "context_grounding": {
                "grounded": False,
                "item_count": 0,
                "grounded_item_count": 0,
                "ungrounded_item_count": 0,
                "applied_context_count": 0,
                "current_packet_context_grounding": {
                    "grounded": True,
                    "item_count": 1,
                    "grounded_item_count": 1,
                    "ungrounded_item_count": 0,
                    "applied_context_count": 4,
                    "notes_count": 1,
                    "requirement_count": 1,
                    "recipient_context_count": 1,
                    "recipient_location_count": 1,
                    "candidate_assessment_count": 1,
                },
            }
        },
        stage_packet={
            "stage": {"kind": "approval_packet", "payload": {"request_text": "Record a signal-loop outcome"}},
            "safe_work_order": {"work_type": "prepare_shortlist"},
        },
        safe_work_result={
            "work_type": "prepare_shortlist",
            "recommended_option_or_draft": {"kind": "shortlist_candidate", "value": {"label": "Record a signal-loop outcome"}},
            "shortlist": [{"label": "Record a signal-loop outcome"}],
        },
    )

    assert ready is True
    assert detail["context_grounding_source"] == "current_packet_context_grounding"
    assert detail["context_grounding_grounded"] is True


def test_assistant_grade_quality_accepts_clean_safe_work_from_noisy_transcript() -> None:
    proof, present = gold_acceptance._assistant_grade_packet_quality_proof(  # noqa: SLF001
        stage_packet={
            "stage": {
                "kind": "approval_packet",
                "payload": {
                    "adapter_hint": "transcript_signal",
                    "work_type": "draft",
                    "draft_request_text": (
                        "[Mikrofongeraeusche] Also ich bin ein bisschen nervoes. "
                        "Ich bin entlassen worden."
                    ),
                    "research_query": "Elektriker fuer zusaetzliche Steckdosen",
                    "search_queries": ["Elektriker fuer zusaetzliche Steckdosen"],
                },
            },
            "safe_work_order": {"work_type": "draft"},
        },
        safe_work_result={
            "work_type": "draft",
            "audit": {"status": "pass", "issues": []},
            "execution_receipt": {
                "search_queries_used": ["Elektriker fuer zusaetzliche Steckdosen 1200 Wien"],
            },
            "recommended_option_or_draft": {
                "kind": "draft_text",
                "value": "Draft to review: Elektriker fuer zusaetzliche Steckdosen",
            },
            "shortlist": [{"label": "Elektriker 1200 Wien"}],
        },
        packet_artifacts_match_run_receipt=True,
    )

    assert present is True
    assert proof["status"] == "pass"
    assert proof["issues"] == []


def test_gold_approval_capture_surface_uses_live_operator_surface_counts_when_local_callbacks_absent() -> None:
    surface, ready = gold_acceptance._approval_capture_surface_receipt(  # noqa: SLF001
        operator_status={
            "approval_capture": {
                "current_packet_ref_sha256": gold_acceptance._hash_value("stage_packet:live"),  # noqa: SLF001
                "current_staged_artifact_ref_sha256": gold_acceptance._hash_value("safe_work_result:live"),  # noqa: SLF001
            },
            "approval_capture_surface": {
                "selected_channel": "telegram",
                "callback_dir_exists": True,
                "callback_record_count": 47,
                "callback_pending_count": 1,
                "callback_recorded_count": 12,
                "current_packet_present": True,
                "current_packet_status": "pending_approval",
                "current_packet_approval_request_recordable": True,
                "current_packet_callback_record_count": 1,
                "current_packet_callback_pending_count": 1,
                "current_packet_live_callback_record_count": 1,
                "current_packet_live_pending_count": 1,
                "current_packet_callback_latest_status": "pending",
                "current_packet_callback_latest_created_at": "2026-07-02T10:52:41Z",
                "current_packet_callback_latest_expires_at": "2026-07-09T10:52:41Z",
                "current_packet_callback_latest_seconds_until_expiry": 604000,
                "telegram_approval_surface_ready": True,
                "manual_outcome_capture_ready": True,
            }
        },
        bundle={
            "stage_packet": {"packet_ref": "stage_packet:live"},
            "safe_work_result": {"result_ref": "safe_work_result:live"},
        },
        approval_outcome_path=ROOT / "state" / "proactive_ooda_latest_approval_outcome.generated.json",
        used_live_runtime_probe=False,
    )

    assert ready is True
    assert surface["current_packet_live_pending_count"] == 1
    assert surface["current_packet_callback_latest_status"] == "pending"
    assert surface["telegram_approval_surface_ready"] is True


def test_gold_approval_capture_surface_uses_live_operator_surface_counts_for_runtime_probe() -> None:
    surface, ready = gold_acceptance._approval_capture_surface_receipt(  # noqa: SLF001
        operator_status={
            "approval_capture": {
                "current_packet_ref_sha256": gold_acceptance._hash_value("stage_packet:older-browse-proof"),  # noqa: SLF001
                "current_staged_artifact_ref_sha256": gold_acceptance._hash_value("safe_work_result:older-browse-proof"),  # noqa: SLF001
            },
            "approval_capture_surface": {
                "selected_channel": "telegram",
                "callback_dir_exists": True,
                "callback_record_count": 49,
                "callback_pending_count": 1,
                "callback_recorded_count": 13,
                "current_packet_present": True,
                "current_packet_status": "pending_approval",
                "current_packet_approval_request_recordable": True,
                "current_packet_callback_record_count": 1,
                "current_packet_callback_pending_count": 1,
                "current_packet_live_callback_record_count": 1,
                "current_packet_live_pending_count": 1,
                "current_packet_callback_latest_status": "pending",
                "current_packet_callback_latest_created_at": "2026-07-02T10:52:41Z",
                "current_packet_callback_latest_expires_at": "2026-07-09T10:52:41Z",
                "current_packet_callback_latest_seconds_until_expiry": 604000,
                "telegram_approval_surface_ready": True,
                "manual_outcome_capture_ready": True,
            }
        },
        bundle={
            "approval_callback_dir": ROOT / "state" / "proactive_ooda_approval_callbacks",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 48,
            "approval_callback_pending_count": 0,
            "approval_callback_recorded_count": 12,
            "current_packet_callback_record_count": 0,
            "current_packet_callback_pending_count": 0,
            "current_packet_live_callback_record_count": 0,
            "current_packet_live_pending_count": 0,
            "stage_packet": {"packet_ref": "stage_packet:older-browse-proof"},
            "safe_work_result": {"result_ref": "safe_work_result:older-browse-proof"},
        },
        approval_outcome_path=ROOT / "state" / "proactive_ooda_latest_approval_outcome.generated.json",
        used_live_runtime_probe=True,
    )

    assert ready is True
    assert surface["callback_record_count"] == 49
    assert surface["current_packet_callback_record_count"] == 1
    assert surface["current_packet_live_pending_count"] == 1
    assert surface["current_packet_callback_latest_status"] == "pending"


def test_operator_status_approval_capture_surface_blocks_duplicate_live_pending_callbacks() -> None:
    surface = operator_status_receipt._approval_capture_surface(  # noqa: SLF001
        report={
            "delivery_route": {"ready": True, "selected_channel": "telegram"},
            "stage_packets": {"ready": True},
            "safe_work_results": {"ready": True},
        },
        artifact_probe={
            "approval_outcome_path": str(ROOT / "state" / "proactive_ooda_latest_approval_outcome.generated.json"),
            "approval_callback_dir": str(ROOT / "state" / "proactive_ooda_approval_callbacks"),
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "current_packet_callback_record_count": 2,
            "current_packet_callback_pending_count": 2,
            "current_packet_live_callback_record_count": 2,
            "current_packet_live_pending_count": 2,
            "current_packet_callback_latest_status": "pending",
            "current_packet": {"present": True, "status": "pending_approval"},
            "stage_packet": {"packet_ref": "stage_packet:live"},
            "safe_work_result": {"result_ref": "safe_work_result:live", "status": "staged_for_user_decision"},
            "source": "unit_test",
        },
    )

    assert surface["ready"] is False
    assert surface["telegram_approval_surface_ready"] is False
    assert surface["duplicate_live_pending_callbacks_present"] is True
    assert surface["current_packet_duplicate_live_pending_count"] == 1


def test_gold_approval_capture_surface_blocks_duplicate_live_pending_callbacks() -> None:
    surface, ready = gold_acceptance._approval_capture_surface_receipt(  # noqa: SLF001
        operator_status={
            "approval_capture": {
                "current_packet_ref_sha256": gold_acceptance._hash_value("stage_packet:live"),  # noqa: SLF001
                "current_staged_artifact_ref_sha256": gold_acceptance._hash_value("safe_work_result:live"),  # noqa: SLF001
            },
            "approval_capture_surface": {
                "selected_channel": "telegram",
                "callback_dir_exists": True,
                "callback_record_count": 2,
                "callback_pending_count": 2,
                "callback_recorded_count": 0,
                "current_packet_present": True,
                "current_packet_status": "pending_approval",
                "current_packet_approval_request_recordable": True,
                "current_packet_callback_record_count": 2,
                "current_packet_callback_pending_count": 2,
                "current_packet_live_callback_record_count": 2,
                "current_packet_live_pending_count": 2,
                "current_packet_callback_latest_status": "pending",
                "telegram_approval_surface_ready": False,
                "manual_outcome_capture_ready": False,
            },
        },
        bundle={
            "approval_callback_dir": ROOT / "state" / "proactive_ooda_approval_callbacks",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 2,
            "approval_callback_pending_count": 2,
            "stage_packet": {"packet_ref": "stage_packet:live"},
            "safe_work_result": {"result_ref": "safe_work_result:live"},
        },
        approval_outcome_path=ROOT / "state" / "proactive_ooda_latest_approval_outcome.generated.json",
        used_live_runtime_probe=True,
    )

    assert ready is False
    assert surface["telegram_approval_surface_ready"] is False
    assert surface["duplicate_live_pending_callbacks_present"] is True
    assert surface["current_packet_duplicate_live_pending_count"] == 1


def test_gold_approval_capture_surface_fails_closed_when_operator_current_packet_hashes_do_not_match_bundle() -> None:
    surface, ready = gold_acceptance._approval_capture_surface_receipt(  # noqa: SLF001
        operator_status={
            "approval_capture": {
                "current_packet_ref_sha256": gold_acceptance._hash_value("stage_packet:other"),  # noqa: SLF001
                "current_staged_artifact_ref_sha256": gold_acceptance._hash_value("safe_work_result:other"),  # noqa: SLF001
            },
            "approval_capture_surface": {
                "selected_channel": "telegram",
                "callback_dir_exists": True,
                "callback_record_count": 49,
                "callback_pending_count": 1,
                "callback_recorded_count": 13,
                "current_packet_present": True,
                "current_packet_status": "pending_approval",
                "current_packet_approval_request_recordable": True,
                "current_packet_callback_record_count": 1,
                "current_packet_callback_pending_count": 1,
                "current_packet_live_callback_record_count": 1,
                "current_packet_live_pending_count": 1,
                "current_packet_callback_latest_status": "pending",
                "telegram_approval_surface_ready": True,
                "manual_outcome_capture_ready": True,
            },
        },
        bundle={
            "approval_callback_dir": ROOT / "state" / "proactive_ooda_approval_callbacks",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 48,
            "approval_callback_pending_count": 0,
            "approval_callback_recorded_count": 12,
            "current_packet_callback_record_count": 0,
            "current_packet_callback_pending_count": 0,
            "current_packet_live_callback_record_count": 0,
            "current_packet_live_pending_count": 0,
            "stage_packet": {"packet_ref": "stage_packet:assistant-grade-packet"},
            "safe_work_result": {"result_ref": "safe_work_result:assistant-grade-packet"},
        },
        approval_outcome_path=ROOT / "state" / "proactive_ooda_latest_approval_outcome.generated.json",
        used_live_runtime_probe=True,
    )

    assert ready is False
    assert surface["telegram_approval_surface_ready"] is True
    assert surface["current_packet_matches_packet_artifacts"] is False


def test_gold_approval_capture_readiness_rejects_mismatched_current_packet_surface() -> None:
    proof, present = gold_acceptance._approval_capture_readiness_proof(  # noqa: SLF001
        operator_status={
            "approval_capture": {
                "checked": True,
                "probe_ok": True,
                "ready": True,
                "status": "ready",
                "current_packet_refs_present": True,
                "current_packet_callback_record_count": 1,
                "current_packet_live_pending_count": 1,
                "callback_principal_hash_present": True,
                "candidate_principal_hash_count": 1,
                "principal_match_ready": True,
                "telegram_binding_ready": True,
                "telegram_chat_ref_present": True,
                "telegram_bot_token_present": True,
                "privacy": {
                    "raw_callback_token_exposed": False,
                    "raw_principal_id_exposed": False,
                    "raw_chat_ref_exposed": False,
                    "raw_packet_ref_exposed": False,
                    "raw_staged_artifact_ref_exposed": False,
                },
            }
        },
        approval_capture_surface={
            "present": True,
            "ready": False,
            "telegram_approval_surface_ready": True,
            "manual_outcome_capture_ready": True,
            "current_packet_approval_request_recordable": True,
            "current_packet_matches_packet_artifacts": False,
        },
        required=True,
        approval_outcome_recorded=False,
        approval_outcome_matches_current_packet=False,
    )

    assert present is False
    assert proof["current_packet_matches_packet_artifacts"] is False
    assert proof["manual_capture_present"] is False
    assert proof["live_callback_present"] is False


def test_gold_next_action_uses_manual_outcome_capture_when_live_surface_targets_other_packet() -> None:
    action = gold_acceptance._next_action(  # noqa: SLF001
        operator_runtime_ready=True,
        operator_status={"approval_capture": {"next_action": "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome"}},
        delivery_present=True,
        action_required_delivery_present=False,
        assistant_grade_present=True,
        browser_action_contract_present=True,
        browse_present=True,
        chosen_present=True,
        staged_present=True,
        teable_present=True,
        approval_capture_readiness_present=False,
        approval_row={"approval_outcome_recorded": False, "accepted": False},
        approval_capture_surface_ready=False,
        approval_capture_telegram_ready=True,
        approval_capture_manual_ready=True,
        approval_capture_surface_matches_packet_artifacts=False,
    )

    assert action == "record_proactive_ooda_approval_outcome"


def test_gold_verifier_blocks_linked_operator_status_that_is_stale_for_current_source(tmp_path: Path) -> None:
    current_head = gold_acceptance_verifier._git_head(gold_acceptance_verifier.ROOT)  # noqa: SLF001
    current_fingerprint = gold_acceptance_verifier._source_fingerprint(gold_acceptance_verifier.ROOT)  # noqa: SLF001
    operator_status_path = tmp_path / "operator_status.json"
    operator_status_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.proactive_ooda_operator_status.v1",
                "status": "ready_with_live_receipt",
                "generated_at": "2026-07-02T15:00:00Z",
                "source_git_head": "stale-head",
                "source_state_fingerprint": "stale-fingerprint",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    receipt_path = tmp_path / "gold_receipt.json"
    receipt_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.proactive_ooda_gold_acceptance.v1",
                "generated_by": "scripts/materialize_proactive_ooda_gold_acceptance.py",
                "head_semantics": "source_state",
                "source_git_head": current_head,
                "source_state_fingerprint": current_fingerprint,
                "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
                "status": "ready_for_approval_outcome_capture",
                "goal_completion_claim_allowed": False,
                "gold_claim_allowed": False,
                "summary": "x",
                "next_action": "repair_proactive_operator_runtime_posture",
                "next_action_href": "https://myexternalbrain.com/admin/goals",
                "next_action_label": "Open goals",
                "next_action_method": "get",
                "rules": sorted(gold_acceptance_verifier.EXPECTED_RULES),
                "proofs": {key: {"present": False} for key in gold_acceptance_verifier.EXPECTED_PROOF_KEYS},
                "evidence_receipts": {
                    "operator_status": {
                        "present": True,
                        "path": str(operator_status_path),
                        "contract_name": "ea.proactive_ooda_operator_status.v1",
                        "status": "ready_with_live_receipt",
                        "generated_at": "2026-07-02T15:00:00Z",
                        "source_git_head": "stale-head",
                        "source_state_fingerprint": "stale-fingerprint",
                    }
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    issues = gold_acceptance_verifier.verify(receipt_path)

    assert "linked operator_status is stale relative to gold receipt source HEAD" in issues
    assert "linked operator_status is stale relative to gold receipt source fingerprint" in issues
