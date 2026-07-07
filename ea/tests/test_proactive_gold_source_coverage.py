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


def test_gold_operator_runtime_blocks_when_source_health_requires_recovery() -> None:
    ready, detail = gold_acceptance._operator_runtime_source_health_posture(  # noqa: SLF001
        {
            "status": "ready_with_recovery_action",
            "reason": "source_health_google_workspace:google_oauth_invalid_grant",
            "next_action": "reauthorize_google_workspace_binding",
            "source_health": {
                "present": True,
                "status": "recovery_required",
                "operator_action_required": True,
                "user_action_required": True,
                "issues": [
                    {
                        "source_key": "google_workspace",
                        "source_type": "google_workspace",
                        "error_code": "google_oauth_invalid_grant",
                        "next_action": "reauthorize_google_workspace_binding",
                    }
                ],
            },
        }
    )

    assert ready is False
    assert detail["source_health_ready"] is False
    assert detail["source_health_status"] == "recovery_required"
    assert detail["source_health_issue_count"] == 1
    assert detail["source_health_blocking_sources"] == ["google_workspace"]
    assert detail["source_health_blocking_error_codes"] == ["google_oauth_invalid_grant"]
    assert detail["next_action"] == "reauthorize_google_workspace_binding"


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


def test_gold_operator_runtime_next_action_keeps_concrete_google_recovery_when_source_snapshot_is_stale(
    monkeypatch: object,
) -> None:
    monkeypatch.setattr(gold_acceptance, "_git_head", lambda path=gold_acceptance.ROOT: "new-head")
    monkeypatch.setattr(gold_acceptance, "_source_fingerprint", lambda path=gold_acceptance.ROOT: "new-fingerprint")

    action = gold_acceptance._operator_runtime_next_action(  # noqa: SLF001
        {
            "status": "ready_with_recovery_action",
            "reason": "google_workspace_signal_source_unhealthy:google_oauth_invalid_grant",
            "next_action": "reauthorize_google_workspace_binding",
            "source_git_head": "old-head",
            "source_state_fingerprint": "old-fingerprint",
        }
    )

    assert action == "reauthorize_google_workspace_binding"
    assert gold_acceptance._next_action_surface_fields(action)["next_action_label"] == "Reconnect Google workspace"  # noqa: SLF001


def test_gold_operator_runtime_next_action_uses_generic_repair_when_stale_snapshot_has_no_concrete_recovery(
    monkeypatch: object,
) -> None:
    monkeypatch.setattr(gold_acceptance, "_git_head", lambda path=gold_acceptance.ROOT: "new-head")
    monkeypatch.setattr(gold_acceptance, "_source_fingerprint", lambda path=gold_acceptance.ROOT: "new-fingerprint")

    action = gold_acceptance._operator_runtime_next_action(  # noqa: SLF001
        {
            "status": "ready_with_live_receipt",
            "source_git_head": "old-head",
            "source_state_fingerprint": "old-fingerprint",
        }
    )

    assert action == "repair_proactive_operator_runtime_posture"


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


def test_operator_status_approval_capture_surface_internal_action_is_not_recordable() -> None:
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
            "current_packet_callback_record_count": 0,
            "current_packet_callback_pending_count": 0,
            "current_packet_live_callback_record_count": 0,
            "current_packet_live_pending_count": 0,
            "current_packet_callback_latest_status": "superseded",
            "current_packet": {"present": True, "status": "internal_action"},
            "stage_packet": {
                "packet_ref": "stage_packet:google-setup",
                "approval": {"required": True},
                "stage": {"kind": "internal_action", "payload": {"work_type": "record_internal_action"}},
            },
            "safe_work_result": {
                "result_ref": "safe_work_result:google-setup",
                "status": "staged_for_user_decision",
                "work_type": "record_internal_action",
                "approval": {"required": True},
                "approval_prompt": "Retry Google auth",
                "staged_action_url": "https://myexternalbrain.com/integrations/google",
            },
            "source": "unit_test",
        },
    )

    assert surface["current_packet_approval_request_recordable"] is False
    assert surface["current_packet_user_action_required"] is False
    assert surface["manual_outcome_capture_ready"] is False
    assert surface["telegram_approval_surface_ready"] is False


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


def test_gold_approval_capture_surface_internal_action_is_not_recordable() -> None:
    surface, ready = gold_acceptance._approval_capture_surface_receipt(  # noqa: SLF001
        operator_status={
            "approval_capture_surface": {
                "selected_channel": "telegram",
                "callback_dir_exists": True,
                "callback_record_count": 23,
                "callback_pending_count": 0,
                "callback_recorded_count": 3,
                "current_packet_present": True,
                "current_packet_status": "internal_action",
                "current_packet_approval_request_recordable": True,
                "current_packet_user_action_required": False,
                "telegram_approval_surface_ready": False,
                "manual_outcome_capture_ready": False,
            },
        },
        bundle={
            "approval_callback_dir": ROOT / "state" / "proactive_ooda_approval_callbacks",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 23,
            "approval_callback_pending_count": 0,
            "stage_packet": {
                "packet_ref": "stage_packet:google-setup",
                "approval": {"required": True},
                "stage": {"kind": "internal_action", "payload": {"work_type": "record_internal_action"}},
            },
            "safe_work_result": {
                "result_ref": "safe_work_result:google-setup",
                "status": "staged_for_user_decision",
                "work_type": "record_internal_action",
                "approval": {"required": True},
                "approval_prompt": "Retry Google auth",
                "staged_action_url": "https://myexternalbrain.com/integrations/google",
            },
        },
        approval_outcome_path=ROOT / "state" / "proactive_ooda_latest_approval_outcome.generated.json",
        used_live_runtime_probe=True,
    )

    assert ready is False
    assert surface["current_packet_approval_request_recordable"] is False
    assert surface["current_packet_user_action_required"] is False
    assert surface["manual_outcome_capture_ready"] is False
    assert surface["telegram_approval_surface_ready"] is False


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
        approval_outcome_matches_selected_packet=False,
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
        approval_capture_readiness_ready=True,
        approval_row={"approval_outcome_recorded": False, "accepted": False},
        approval_capture_surface_ready=False,
        approval_capture_telegram_ready=True,
        approval_capture_manual_ready=True,
        approval_capture_surface_matches_packet_artifacts=False,
    )

    assert action == "record_proactive_ooda_approval_outcome"


def test_gold_next_action_uses_operator_recovery_when_current_packet_has_no_approval_to_capture() -> None:
    action = gold_acceptance._next_action(  # noqa: SLF001
        operator_runtime_ready=True,
        operator_status={
            "status": "ready_with_recovery_action",
            "reason": "source_health_google_workspace:google_oauth_invalid_grant",
            "next_action": "reauthorize_google_workspace_binding",
        },
        delivery_present=True,
        action_required_delivery_present=True,
        assistant_grade_present=True,
        browser_action_contract_present=True,
        browse_present=True,
        chosen_present=True,
        staged_present=True,
        teable_present=True,
        approval_capture_readiness_present=True,
        approval_capture_readiness_ready=False,
        approval_capture_required=False,
        approval_row={"approval_outcome_recorded": False, "accepted": False},
        approval_capture_surface_ready=False,
        approval_capture_telegram_ready=False,
        approval_capture_manual_ready=False,
        approval_capture_surface_matches_packet_artifacts=False,
    )

    assert action == "reauthorize_google_workspace_binding"


def test_gold_next_action_stages_fresh_packet_when_current_packet_has_no_approval_to_capture() -> None:
    action = gold_acceptance._next_action(  # noqa: SLF001
        operator_runtime_ready=True,
        operator_status={},
        delivery_present=True,
        action_required_delivery_present=True,
        assistant_grade_present=True,
        browser_action_contract_present=True,
        browse_present=True,
        chosen_present=True,
        staged_present=True,
        teable_present=True,
        approval_capture_readiness_present=True,
        approval_capture_readiness_ready=False,
        approval_capture_required=False,
        approval_row={"approval_outcome_recorded": False, "accepted": False},
        approval_capture_surface_ready=False,
        approval_capture_telegram_ready=False,
        approval_capture_manual_ready=False,
        approval_capture_surface_matches_packet_artifacts=False,
    )

    assert action == "stage_fresh_assistant_grade_proactive_packet"


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


def test_historical_accepted_bundle_lookup_finds_matching_artifacts(tmp_path: Path) -> None:
    stage_dir = tmp_path / "proactive_ooda_stage_packets"
    safe_dir = tmp_path / "proactive_ooda_safe_work_results"
    run_dir = tmp_path / "proactive_ooda_run_receipts"
    stage_dir.mkdir()
    safe_dir.mkdir()
    run_dir.mkdir()

    stage_packet = {
        "packet_ref": "stage_packet:historical-packet",
        "generated_at": "2026-07-02T11:39:32Z",
        "stage": {"payload": {"work_type": "record_internal_action"}},
    }
    safe_work_result = {
        "result_ref": "safe_work_result:historical-safe",
        "generated_at": "2026-07-02T11:39:33Z",
        "status": "staged_for_user_decision",
        "work_type": "record_internal_action",
    }
    stage_path = stage_dir / "historical-stage.json"
    safe_path = safe_dir / "historical-safe.json"
    stage_path.write_text(json.dumps(stage_packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    safe_path.write_text(json.dumps(safe_work_result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    stage_hash = gold_acceptance._hash_value(stage_packet["packet_ref"])  # noqa: SLF001
    safe_hash = gold_acceptance._hash_value(safe_work_result["result_ref"])  # noqa: SLF001
    run_receipt = {
        "generated_at": "2026-07-02T11:39:32Z",
        "notification_status": "sent",
        "item_count": 1,
        "stage_packet_ref_hashes": [stage_hash],
        "safe_work_result_ref_hashes": [safe_hash],
    }
    run_path = run_dir / "historical-run.json"
    run_path.write_text(json.dumps(run_receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    approval_row = {
        "approval_outcome_recorded": True,
        "accepted": True,
        "packet_ref_sha256": stage_hash,
        "staged_artifact_sha256": safe_hash,
    }

    bundle = gold_acceptance._historical_accepted_bundle_from_approval_outcome(  # noqa: SLF001
        approval_row=approval_row,
        run_receipt_path=run_path,
        stage_packet_dir=stage_dir,
        safe_work_result_dir=safe_dir,
    )

    assert bundle["selection_source"] == "historical_accepted_approval_outcome"
    assert bundle["run_receipt_path"] == run_path
    assert bundle["stage_packet_path"] == stage_path
    assert bundle["safe_work_result_path"] == safe_path
    assert bundle["run_receipt"]["notification_status"] == "sent"


def test_historical_accepted_bundle_lookup_uses_snapshot_when_artifacts_rotated_away() -> None:
    stage_packet = {
        "packet_ref": "stage_packet:historical-snapshot",
        "generated_at": "2026-07-02T11:39:32Z",
        "stage": {"kind": "research_packet", "payload": {"work_type": "compare_options"}},
        "safe_work_order": {"work_type": "compare_options"},
    }
    safe_work_result = {
        "result_ref": "safe_work_result:historical-snapshot",
        "generated_at": "2026-07-02T11:39:33Z",
        "status": "staged_for_user_decision",
        "work_type": "compare_options",
        "audit": {"status": "pass", "issues": []},
        "recommended_option_or_draft": {"kind": "shortlist_candidate", "value": {"label": "Snapshot candidate"}},
        "shortlist": [{"label": "Snapshot candidate"}],
    }
    run_receipt = {
        "generated_at": "2026-07-02T11:39:32Z",
        "notification_status": "sent",
        "item_count": 1,
        "stage_packet_ref_hashes": [gold_acceptance._hash_value(stage_packet["packet_ref"])],  # noqa: SLF001
        "safe_work_result_ref_hashes": [gold_acceptance._hash_value(safe_work_result["result_ref"])],  # noqa: SLF001
    }
    approval_row = {
        "approval_outcome_recorded": True,
        "accepted": True,
        "packet_ref_sha256": gold_acceptance._hash_value(stage_packet["packet_ref"]),  # noqa: SLF001
        "staged_artifact_sha256": gold_acceptance._hash_value(safe_work_result["result_ref"]),  # noqa: SLF001
        "bundle_snapshot": {
            "present": True,
            "schema": "ea.proactive_ooda.approved_bundle_snapshot.v1",
            "source": "approval_record_time_runtime_bundle",
            "recorded_at": "2026-07-02T15:20:09Z",
            "run_receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/historical-run.json",
            "run_receipt": run_receipt,
            "stage_packet_path": "/data/provider-ledger/proactive_ooda_stage_packets/historical-stage.json",
            "stage_packet": gold_acceptance._redact_snapshot_bundle_refs(stage_packet),  # noqa: SLF001
            "safe_work_result_path": "/data/provider-ledger/proactive_ooda_safe_work_results/historical-safe.json",
            "safe_work_result": gold_acceptance._redact_snapshot_bundle_refs(safe_work_result),  # noqa: SLF001
        },
    }

    bundle = gold_acceptance._historical_accepted_bundle_from_approval_outcome(  # noqa: SLF001
        approval_row=approval_row,
        run_receipt_path=Path("/data/provider-ledger/proactive_ooda_latest_run.generated.json"),
        stage_packet_dir=Path("/data/provider-ledger/proactive_ooda_stage_packets"),
        safe_work_result_dir=Path("/data/provider-ledger/proactive_ooda_safe_work_results"),
    )

    assert bundle["selection_source"] == "historical_accepted_approval_outcome"
    assert str(bundle["run_receipt_path"]).endswith("historical-run.json")
    assert bundle["stage_packet"]["packet_ref_sha256"] == gold_acceptance._hash_value(stage_packet["packet_ref"])  # noqa: SLF001
    assert bundle["safe_work_result"]["result_ref_sha256"] == gold_acceptance._hash_value(safe_work_result["result_ref"])  # noqa: SLF001
    assert bundle["run_receipt"]["notification_status"] == "sent"


def test_live_historical_accepted_bundle_lookup_uses_docker_compose_exec_for_container_only_paths(
    monkeypatch: object,
) -> None:
    approval_row = {
        "approval_outcome_recorded": True,
        "accepted": True,
        "packet_ref_sha256": "packet-hash",
        "staged_artifact_sha256": "safe-hash",
    }
    captured: dict[str, object] = {}

    def _fake_exec_json(**kwargs: object) -> tuple[int, dict[str, object], str, str]:
        captured.update(kwargs)
        return (
            0,
            {
                "ok": True,
                "selection_source": "historical_accepted_approval_outcome",
                "run_receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/historical-run.json",
                "run_receipt": {"notification_status": "sent"},
                "stage_packet_path": "/data/provider-ledger/proactive_ooda_stage_packets/historical-stage.json",
                "stage_packet": {"packet_ref": "stage_packet:historical"},
                "safe_work_result_path": "/data/provider-ledger/proactive_ooda_safe_work_results/historical-safe.json",
                "safe_work_result": {"result_ref": "safe_work_result:historical"},
            },
            "{\"ok\":true}",
            "",
        )

    monkeypatch.setattr(gold_acceptance.ea_live_ops, "_docker_compose_exec_json", _fake_exec_json)

    bundle = gold_acceptance._live_historical_accepted_bundle_from_approval_outcome(  # noqa: SLF001
        approval_row=approval_row,
        run_receipt_path=Path("/data/provider-ledger/proactive_ooda_latest_run.generated.json"),
        stage_packet_dir=Path("/data/provider-ledger/proactive_ooda_stage_packets"),
        safe_work_result_dir=Path("/data/provider-ledger/proactive_ooda_safe_work_results"),
    )

    assert captured["service"] == gold_acceptance.ea_live_ops.DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE
    assert bundle["selection_source"] == "historical_accepted_approval_outcome"
    assert str(bundle["run_receipt_path"]).endswith("historical-run.json")
    assert bundle["run_receipt"]["notification_status"] == "sent"
    assert bundle["stage_packet"]["packet_ref"] == "stage_packet:historical"
    assert bundle["safe_work_result"]["result_ref"] == "safe_work_result:historical"


def test_run_receipt_dir_prefers_sibling_run_receipts_for_latest_run_pointer(tmp_path: Path) -> None:
    state_dir = tmp_path / "provider-ledger"
    run_receipts_dir = state_dir / "proactive_ooda_run_receipts"
    run_receipts_dir.mkdir(parents=True)
    latest_run_path = state_dir / "proactive_ooda_latest_run.generated.json"
    latest_run_path.write_text("{}", encoding="utf-8")

    resolved = gold_acceptance._run_receipt_dir(  # noqa: SLF001
        run_receipt_path=latest_run_path,
        stage_packet_dir=None,
        safe_work_result_dir=None,
    )

    assert resolved == run_receipts_dir


def test_materializer_prefers_historical_accepted_bundle_when_current_packet_is_unrelated(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    operator_status_path = tmp_path / "operator_status.json"
    output_path = tmp_path / "gold.json"
    stage_dir = tmp_path / "proactive_ooda_stage_packets"
    safe_dir = tmp_path / "proactive_ooda_safe_work_results"
    run_dir = tmp_path / "proactive_ooda_run_receipts"
    stage_dir.mkdir()
    safe_dir.mkdir()
    run_dir.mkdir()

    historical_stage = {
        "packet_ref": "stage_packet:historical-packet",
        "generated_at": "2026-07-02T11:39:32Z",
        "approval": {"required": True},
        "safe_work_order": {
            "work_type": "compare_options",
            "handoff_policy": {
                "safe_to_execute_before_approval": True,
                "external_actions_remain_staged_only": True,
            },
        },
        "stage": {
            "kind": "research_packet",
            "payload": {
                "work_type": "compare_options",
                "request_text": "Find a shortlist of electricians for a new outlet near the AC vent in 1200 Wien.",
                "research_query": "Elektriker 1200 Wien neue Steckdose Klimageraet",
                "search_queries": ["Elektriker 1200 Wien neue Steckdose Klimageraet"],
            },
        },
    }
    historical_safe = {
        "result_ref": "safe_work_result:historical-safe",
        "generated_at": "2026-07-02T11:39:33Z",
        "status": "staged_for_user_decision",
        "work_type": "compare_options",
        "approval": {"required": True},
        "audit": {"status": "pass", "issues": []},
        "browser_action_receipt": {},
        "execution_receipt": {
            "network_fetch_count": 2,
            "network_fetch_success_count": 2,
            "page_checks": [
                {"url": "https://elektriker.example.test/a", "reachable": True},
                {"url": "https://elektriker.example.test/b", "reachable": True},
            ],
            "irreversible_actions_attempted": [],
            "search_candidate_count": 2,
            "search_queries_used": ["Elektriker 1200 Wien neue Steckdose Klimageraet"],
            "research_search_plan": {"mode": "web_search"},
        },
        "recommended_option_or_draft": {
            "kind": "shortlist_candidate",
            "value": {
                "label": "Elektriker Musterbetrieb",
                "url": "https://elektriker.example.test/a",
                "source": "business_listing",
            },
        },
        "shortlist": [
            {"label": "Elektriker Musterbetrieb", "url": "https://elektriker.example.test/a"},
            {"label": "Wien Elektro Team", "url": "https://elektriker.example.test/b"},
        ],
        "staged_action_url": "https://elektriker.example.test/a",
    }
    historical_stage_path = stage_dir / "historical-stage.json"
    historical_safe_path = safe_dir / "historical-safe.json"
    historical_stage_path.write_text(
        json.dumps(historical_stage, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    historical_safe_path.write_text(
        json.dumps(historical_safe, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    historical_stage_hash = gold_acceptance._hash_value(historical_stage["packet_ref"])  # noqa: SLF001
    historical_safe_hash = gold_acceptance._hash_value(historical_safe["result_ref"])  # noqa: SLF001
    historical_run_receipt = {
        "generated_at": "2026-07-02T11:39:32Z",
        "notification_status": "sent",
        "item_count": 1,
        "delivery_channel": "telegram",
        "stage_packet_ref_hashes": [historical_stage_hash],
        "safe_work_result_ref_hashes": [historical_safe_hash],
        "teable_sync": {
            "sync_attempted": True,
            "status": "synced",
            "projection_summary": {
                "record_count": 4,
                "tables": {
                    "proactive_ooda_items": {"record_count": 1},
                    "proactive_ooda_safe_work": {"record_count": 1},
                    "proactive_ooda_approval_surfaces": {"record_count": 1},
                },
            },
        },
    }
    historical_run_path = run_dir / "historical-run.json"
    historical_run_path.write_text(
        json.dumps(historical_run_receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    current_stage = {
        "packet_ref": "stage_packet:current-unrelated",
        "generated_at": "2026-07-02T12:00:00Z",
        "stage": {"payload": {"work_type": "record_internal_action", "request_text": "Current unrelated packet."}},
        "safe_work_order": {"work_type": "record_internal_action"},
    }
    current_safe = {
        "result_ref": "safe_work_result:current-unrelated",
        "generated_at": "2026-07-02T12:00:01Z",
        "status": "staged_for_user_decision",
        "work_type": "record_internal_action",
        "recommended_option_or_draft": {"kind": "internal_action", "value": {"label": "Current unrelated"}},
        "audit": {"status": "pass", "issues": []},
        "browser_action_receipt": {},
        "execution_receipt": {"research_search_plan": {"mode": "internal_action_surface"}},
    }
    current_run_path = run_dir / "current-run.json"
    current_run_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-07-02T12:00:00Z",
                "notification_status": "sent",
                "item_count": 1,
                "stage_packet_ref_hashes": [gold_acceptance._hash_value(current_stage["packet_ref"])],  # noqa: SLF001
                "safe_work_result_ref_hashes": [gold_acceptance._hash_value(current_safe["result_ref"])],  # noqa: SLF001
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    operator_status_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.proactive_ooda_operator_status.v1",
                "status": "ready_with_live_receipt",
                "generated_at": "2026-07-02T12:30:00Z",
                "live_receipt_checked": True,
                "delivery_route_ready": True,
                "delivery_route": {"selected_channel": "telegram"},
                "live_receipt": {"ok": True, "delivery_channel": "telegram"},
                "runtime_actionable_count": 0,
                "delivery_guard": {
                    "delivery_state": "no_actionable_items",
                    "has_high_priority": False,
                },
                "approval_capture": {"checked": True, "probe_ok": True, "ready": True, "status": "ready"},
                "approval_capture_surface": {
                    "present": False,
                    "ready": False,
                    "telegram_approval_surface_ready": False,
                    "manual_outcome_capture_ready": False,
                    "current_packet_approval_request_recordable": False,
                    "current_packet_matches_packet_artifacts": False,
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        gold_acceptance,
        "_runtime_artifact_bundle",
        lambda **_kwargs: (
            {
                "run_receipt_path": current_run_path,
                "run_receipt": json.loads(current_run_path.read_text(encoding="utf-8")),
                "action_required_only_quiet_receipt_path": None,
                "action_required_only_quiet_receipt": {},
                "stage_packet_dir": stage_dir,
                "safe_work_result_dir": safe_dir,
                "approval_outcome_path": tmp_path / "approval.json",
                "approval_callback_dir": tmp_path / "callbacks",
                "stage_packet_path": stage_dir / "current-stage.json",
                "stage_packet": current_stage,
                "safe_work_result_path": safe_dir / "current-safe.json",
                "safe_work_result": current_safe,
                "approval_outcome": {},
            },
            False,
        ),
    )
    monkeypatch.setattr(gold_acceptance, "_refresh_operator_status_snapshot", lambda path, current: current)
    monkeypatch.setattr(gold_acceptance, "_git_head", lambda path=gold_acceptance.ROOT: "head")
    monkeypatch.setattr(gold_acceptance, "_source_fingerprint", lambda path=gold_acceptance.ROOT: "fingerprint")
    monkeypatch.setattr(
        gold_acceptance,
        "_operator_status_source_posture",
        lambda *args, **kwargs: (True, {"operator_status_source_current": True}),
    )
    monkeypatch.setattr(
        gold_acceptance,
        "_operator_runtime_source_coverage_posture",
        lambda *args, **kwargs: (True, {"source_coverage_ready": True}),
    )
    monkeypatch.setattr(
        gold_acceptance,
        "_operator_runtime_context_grounding_posture_for_packet",
        lambda *args, **kwargs: (True, {"context_grounding_ready": True}),
    )
    monkeypatch.setattr(
        gold_acceptance,
        "_operator_runtime_safe_work_audit_posture",
        lambda *args, **kwargs: (True, {"safe_work_audit_ready": True}),
    )
    monkeypatch.setattr(
        gold_acceptance,
        "_operator_runtime_current_artifact_filter_posture",
        lambda *args, **kwargs: (True, {"current_artifact_filter_ready": True}),
    )
    monkeypatch.setattr(
        gold_acceptance,
        "_operator_runtime_suppressed_projection_posture",
        lambda *args, **kwargs: (True, {"suppressed_projection_ready": True}),
    )
    monkeypatch.setattr(
        gold_acceptance,
        "_approval_capture_surface_receipt",
        lambda **kwargs: (
            {
                "present": False,
                "ready": False,
                "telegram_approval_surface_ready": False,
                "manual_outcome_capture_ready": False,
                "current_packet_approval_request_recordable": False,
                "current_packet_matches_packet_artifacts": False,
            },
            False,
        ),
    )
    monkeypatch.setattr(
        gold_acceptance,
        "_action_required_only_policy_probe",
        lambda: {
            "checked": True,
            "status": "pass",
            "low_value_research_prompt_requires_user_action": False,
            "internal_proof_packet_requires_user_action": False,
            "executable_draft_prompt_requires_user_action": True,
            "raw_policy_prompt_exposed": False,
        },
    )

    receipt = gold_acceptance.materialize_proactive_ooda_gold_acceptance(
        output_path=output_path,
        operator_status_path=operator_status_path,
        approval_outcome_input={
            "outcome": "approved",
            "evidence": "redacted-evidence",
            "actor": "operator",
            "packet_ref": historical_stage["packet_ref"],
            "staged_artifact_ref": historical_safe["result_ref"],
            "source_kind": "operator_manual",
            "recorded_at": "2026-07-02T15:20:09Z",
        },
    )

    assert receipt["status"] == "pass"
    assert receipt["gold_claim_allowed"] is True
    assert receipt["selected_bundle_source"] == "historical_accepted_approval_outcome"
    assert receipt["proofs"]["approval_outcome"]["accepted"] is True
    assert receipt["proofs"]["chosen_candidate"]["present"] is True
    assert receipt["proofs"]["staged_reversible_artifact"]["present"] is True
    assert receipt["proofs"]["teable_projection"]["present"] is True
    assert receipt["proofs"]["action_required_only_delivery"]["present"] is True
    assert receipt["evidence_receipts"]["stage_packet"]["path"].endswith("historical-stage.json")


def test_gold_materializer_blocks_when_source_health_requires_recovery(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    operator_status_path = tmp_path / "operator_status.json"
    output_path = tmp_path / "gold.json"
    operator_status_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.proactive_ooda_operator_status.v1",
                "status": "ready_with_recovery_action",
                "generated_at": "2026-07-02T12:30:00Z",
                "reason": "source_health_google_workspace:google_oauth_invalid_grant",
                "next_action": "reauthorize_google_workspace_binding",
                "source_health": {
                    "present": True,
                    "status": "recovery_required",
                    "operator_action_required": True,
                    "user_action_required": True,
                    "issues": [
                        {
                            "source_key": "google_workspace",
                            "source_type": "google_workspace",
                            "error_code": "google_oauth_invalid_grant",
                            "next_action": "reauthorize_google_workspace_binding",
                        }
                    ],
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        gold_acceptance,
        "_runtime_artifact_bundle",
        lambda **_kwargs: (
            {
                "run_receipt_path": None,
                "run_receipt": {},
                "action_required_only_quiet_receipt_path": None,
                "action_required_only_quiet_receipt": {},
                "stage_packet_dir": tmp_path,
                "safe_work_result_dir": tmp_path,
                "approval_outcome_path": tmp_path / "approval.json",
                "approval_callback_dir": tmp_path / "callbacks",
                "stage_packet_path": None,
                "stage_packet": {},
                "safe_work_result_path": None,
                "safe_work_result": {},
                "approval_outcome": {},
            },
            False,
        ),
    )
    monkeypatch.setattr(gold_acceptance, "_refresh_operator_status_snapshot", lambda path, current: current)
    monkeypatch.setattr(gold_acceptance, "_git_head", lambda path=gold_acceptance.ROOT: "head")
    monkeypatch.setattr(gold_acceptance, "_source_fingerprint", lambda path=gold_acceptance.ROOT: "fingerprint")
    monkeypatch.setattr(
        gold_acceptance,
        "_operator_status_source_posture",
        lambda *args, **kwargs: (True, {"operator_status_source_current": True}),
    )
    monkeypatch.setattr(
        gold_acceptance,
        "_operator_runtime_source_coverage_posture",
        lambda *args, **kwargs: (True, {"source_coverage_ready": True}),
    )
    monkeypatch.setattr(
        gold_acceptance,
        "_operator_runtime_context_grounding_posture_for_packet",
        lambda *args, **kwargs: (True, {"context_grounding_ready": True}),
    )
    monkeypatch.setattr(
        gold_acceptance,
        "_operator_runtime_safe_work_audit_posture",
        lambda *args, **kwargs: (True, {"safe_work_audit_ready": True}),
    )
    monkeypatch.setattr(
        gold_acceptance,
        "_operator_runtime_current_artifact_filter_posture",
        lambda *args, **kwargs: (True, {"current_artifact_filter_ready": True}),
    )
    monkeypatch.setattr(
        gold_acceptance,
        "_operator_runtime_suppressed_projection_posture",
        lambda *args, **kwargs: (True, {"suppressed_projection_ready": True}),
    )
    monkeypatch.setattr(
        gold_acceptance,
        "_approval_capture_surface_receipt",
        lambda **kwargs: (
            {
                "present": False,
                "ready": False,
                "telegram_approval_surface_ready": False,
                "manual_outcome_capture_ready": False,
                "current_packet_approval_request_recordable": False,
                "current_packet_matches_packet_artifacts": False,
            },
            False,
        ),
    )
    monkeypatch.setattr(
        gold_acceptance,
        "_action_required_only_policy_probe",
        lambda: {
            "checked": True,
            "status": "pass",
            "low_value_research_prompt_requires_user_action": False,
            "internal_proof_packet_requires_user_action": False,
            "executable_draft_prompt_requires_user_action": True,
            "raw_policy_prompt_exposed": False,
        },
    )

    receipt = gold_acceptance.materialize_proactive_ooda_gold_acceptance(
        output_path=output_path,
        operator_status_path=operator_status_path,
    )

    assert receipt["status"] == "blocked_operator_runtime_posture"
    assert receipt["next_action"] == "reauthorize_google_workspace_binding"
    assert receipt["proofs"]["operator_runtime_posture"]["present"] is False
    assert receipt["proofs"]["operator_runtime_posture"]["source_health_ready"] is False
    assert receipt["proofs"]["operator_runtime_posture"]["source_health_blocking_sources"] == ["google_workspace"]


def test_materializer_prefers_live_historical_bundle_when_current_paths_are_container_only(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    operator_status_path = tmp_path / "operator_status.json"
    output_path = tmp_path / "gold.json"
    operator_status_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.proactive_ooda_operator_status.v1",
                "status": "ready_with_live_receipt",
                "generated_at": "2026-07-02T12:30:00Z",
                "live_receipt_checked": True,
                "delivery_route_ready": True,
                "delivery_route": {"selected_channel": "telegram"},
                "live_receipt": {"ok": True, "delivery_channel": "telegram"},
                "runtime_actionable_count": 0,
                "approval_capture": {"checked": True, "probe_ok": True, "ready": True, "status": "ready"},
                "approval_capture_surface": {
                    "present": False,
                    "ready": False,
                    "telegram_approval_surface_ready": False,
                    "manual_outcome_capture_ready": False,
                    "current_packet_approval_request_recordable": False,
                    "current_packet_matches_packet_artifacts": False,
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        gold_acceptance,
        "_runtime_artifact_bundle",
        lambda **_kwargs: (
            {
                "run_receipt_path": Path("/data/provider-ledger/proactive_ooda_latest_run.generated.json"),
                "run_receipt": {
                    "notification_status": "sent",
                    "item_count": 1,
                    "stage_packet_ref_hashes": [gold_acceptance._hash_value("stage_packet:current-unrelated")],  # noqa: SLF001
                    "safe_work_result_ref_hashes": [gold_acceptance._hash_value("safe_work_result:current-unrelated")],  # noqa: SLF001
                },
                "action_required_only_quiet_receipt_path": None,
                "action_required_only_quiet_receipt": {},
                "stage_packet_dir": Path("/data/provider-ledger/proactive_ooda_stage_packets"),
                "safe_work_result_dir": Path("/data/provider-ledger/proactive_ooda_safe_work_results"),
                "approval_outcome_path": Path("/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json"),
                "approval_callback_dir": Path("/data/provider-ledger/proactive_ooda_approval_callbacks"),
                "stage_packet_path": Path("/data/provider-ledger/proactive_ooda_stage_packets/current-stage.json"),
                "stage_packet": {
                    "packet_ref": "stage_packet:current-unrelated",
                    "stage": {"payload": {"work_type": "record_internal_action", "request_text": "Current unrelated packet."}},
                    "safe_work_order": {"work_type": "record_internal_action"},
                },
                "safe_work_result_path": Path("/data/provider-ledger/proactive_ooda_safe_work_results/current-safe.json"),
                "safe_work_result": {
                    "result_ref": "safe_work_result:current-unrelated",
                    "status": "staged_for_user_decision",
                    "work_type": "record_internal_action",
                    "recommended_option_or_draft": {"kind": "internal_action", "value": {"label": "Current unrelated"}},
                    "audit": {"status": "pass", "issues": []},
                    "browser_action_receipt": {},
                    "execution_receipt": {"research_search_plan": {"mode": "internal_action_surface"}},
                },
                "approval_outcome": {},
            },
            True,
        ),
    )
    monkeypatch.setattr(
        gold_acceptance,
        "_live_historical_accepted_bundle_from_approval_outcome",
        lambda **_kwargs: {
            "run_receipt_path": Path("/data/provider-ledger/proactive_ooda_run_receipts/historical-run.json"),
            "run_receipt": {
                "notification_status": "sent",
                "delivery_channel": "telegram",
                "item_count": 1,
                "stage_packet_ref_hashes": [gold_acceptance._hash_value("stage_packet:historical-packet")],  # noqa: SLF001
                "safe_work_result_ref_hashes": [gold_acceptance._hash_value("safe_work_result:historical-safe")],  # noqa: SLF001
                "teable_sync": {
                    "sync_attempted": True,
                    "status": "synced",
                    "projection_summary": {
                        "record_count": 4,
                        "tables": {
                            "proactive_ooda_items": {"record_count": 1},
                            "proactive_ooda_safe_work": {"record_count": 1},
                            "proactive_ooda_approval_surfaces": {"record_count": 1},
                        },
                    },
                },
            },
            "stage_packet_path": Path("/data/provider-ledger/proactive_ooda_stage_packets/historical-stage.json"),
            "stage_packet": {
                "packet_ref": "stage_packet:historical-packet",
                "approval": {"required": True},
                "safe_work_order": {
                    "work_type": "compare_options",
                    "handoff_policy": {
                        "safe_to_execute_before_approval": True,
                        "external_actions_remain_staged_only": True,
                    },
                },
                "stage": {
                    "kind": "research_packet",
                    "payload": {
                        "work_type": "compare_options",
                        "request_text": "Find a shortlist of electricians for a new outlet near the AC vent in 1200 Wien.",
                        "research_query": "Elektriker 1200 Wien neue Steckdose Klimageraet",
                        "search_queries": ["Elektriker 1200 Wien neue Steckdose Klimageraet"],
                    },
                },
            },
            "safe_work_result_path": Path("/data/provider-ledger/proactive_ooda_safe_work_results/historical-safe.json"),
            "safe_work_result": {
                "result_ref": "safe_work_result:historical-safe",
                "status": "staged_for_user_decision",
                "work_type": "compare_options",
                "approval": {"required": True},
                "audit": {"status": "pass", "issues": []},
                "browser_action_receipt": {},
                "execution_receipt": {
                    "network_fetch_count": 2,
                    "network_fetch_success_count": 2,
                    "page_checks": [
                        {"url": "https://elektriker.example.test/a", "reachable": True},
                        {"url": "https://elektriker.example.test/b", "reachable": True},
                    ],
                    "irreversible_actions_attempted": [],
                    "search_candidate_count": 2,
                    "search_queries_used": ["Elektriker 1200 Wien neue Steckdose Klimageraet"],
                    "research_search_plan": {"mode": "web_search"},
                },
                "recommended_option_or_draft": {
                    "kind": "shortlist_candidate",
                    "value": {
                        "label": "Elektriker Musterbetrieb",
                        "url": "https://elektriker.example.test/a",
                        "source": "business_listing",
                    },
                },
                "shortlist": [
                    {"label": "Elektriker Musterbetrieb", "url": "https://elektriker.example.test/a"},
                    {"label": "Wien Elektro Team", "url": "https://elektriker.example.test/b"},
                ],
                "staged_action_url": "https://elektriker.example.test/a",
            },
            "selection_source": "historical_accepted_approval_outcome",
        },
    )
    monkeypatch.setattr(gold_acceptance, "_refresh_operator_status_snapshot", lambda path, current: current)
    monkeypatch.setattr(gold_acceptance, "_git_head", lambda path=gold_acceptance.ROOT: "head")
    monkeypatch.setattr(gold_acceptance, "_source_fingerprint", lambda path=gold_acceptance.ROOT: "fingerprint")
    monkeypatch.setattr(
        gold_acceptance,
        "_operator_status_source_posture",
        lambda *args, **kwargs: (True, {"operator_status_source_current": True}),
    )
    monkeypatch.setattr(
        gold_acceptance,
        "_operator_runtime_source_coverage_posture",
        lambda *args, **kwargs: (True, {"source_coverage_ready": True}),
    )
    monkeypatch.setattr(
        gold_acceptance,
        "_operator_runtime_context_grounding_posture_for_packet",
        lambda *args, **kwargs: (True, {"context_grounding_ready": True}),
    )
    monkeypatch.setattr(
        gold_acceptance,
        "_operator_runtime_safe_work_audit_posture",
        lambda *args, **kwargs: (True, {"safe_work_audit_ready": True}),
    )
    monkeypatch.setattr(
        gold_acceptance,
        "_operator_runtime_current_artifact_filter_posture",
        lambda *args, **kwargs: (True, {"current_artifact_filter_ready": True}),
    )
    monkeypatch.setattr(
        gold_acceptance,
        "_operator_runtime_suppressed_projection_posture",
        lambda *args, **kwargs: (True, {"suppressed_projection_ready": True}),
    )
    monkeypatch.setattr(
        gold_acceptance,
        "_approval_capture_surface_receipt",
        lambda **kwargs: (
            {
                "present": False,
                "ready": False,
                "telegram_approval_surface_ready": False,
                "manual_outcome_capture_ready": False,
                "current_packet_approval_request_recordable": False,
                "current_packet_matches_packet_artifacts": False,
            },
            False,
        ),
    )
    monkeypatch.setattr(
        gold_acceptance,
        "_action_required_only_policy_probe",
        lambda: {
            "checked": True,
            "status": "pass",
            "low_value_research_prompt_requires_user_action": False,
            "internal_proof_packet_requires_user_action": False,
            "executable_draft_prompt_requires_user_action": True,
            "raw_policy_prompt_exposed": False,
        },
    )

    receipt = gold_acceptance.materialize_proactive_ooda_gold_acceptance(
        output_path=output_path,
        operator_status_path=operator_status_path,
        approval_outcome_input={
            "outcome": "approved",
            "evidence": "redacted-evidence",
            "actor": "operator",
            "packet_ref": "stage_packet:historical-packet",
            "staged_artifact_ref": "safe_work_result:historical-safe",
            "source_kind": "operator_manual",
            "recorded_at": "2026-07-02T15:20:09Z",
        },
    )

    assert receipt["selected_bundle_source"] == "historical_accepted_approval_outcome"
    assert receipt["proofs"]["approval_outcome"]["accepted"] is True
    assert receipt["evidence_receipts"]["run_receipt"]["path"].endswith("historical-run.json")
    assert receipt["evidence_receipts"]["stage_packet"]["path"].endswith("historical-stage.json")
