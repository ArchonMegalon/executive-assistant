from __future__ import annotations

from pathlib import Path

from app.services import proactive_ooda_approval_reissue


def _current_bundle() -> dict[str, object]:
    return {
        "current_packet_live_pending_count": 1,
        "stage_packet": {
            "packet_ref": "stage_packet:packet-1",
            "approval": {"required": True},
            "stage": {
                "kind": "approval_packet",
                "payload": {
                    "approved_execution_mode": "explicit_approval",
                    "approved_action": "stage_reversible_next_step",
                },
            },
        },
        "safe_work_result": {
            "result_ref": "safe_work_result:result-1",
            "status": "staged_for_user_decision",
            "approval": {"required": True},
            "approval_prompt": "Approve the staged packet?",
            "staged_action_url": "https://example.com/app/queue",
        },
        "approval_outcome": {},
    }


def test_record_current_proactive_ooda_approval_outcome_dry_run_uses_current_packet() -> None:
    result = proactive_ooda_approval_reissue.record_current_proactive_ooda_approval_outcome(
        principal_id="principal-1",
        outcome="approved",
        evidence="Reviewed in operator console.",
        actor="operator@example.com",
        root=Path("/tmp/ea"),
        state_path="state/proactive_ooda_notified.json",
        dry_run=True,
        bundle_loader=lambda **_: _current_bundle(),
    )

    assert result["status"] == "dry_run"
    assert result["reason"] == "approval_outcome_ready_to_record"
    assert result["current_packet_live_pending_count"] == 1
    assert result["stage_kind"] == "approval_packet"
    assert result["safe_work_status"] == "staged_for_user_decision"
    assert result["has_staged_action_url"] is True


def test_record_current_proactive_ooda_approval_outcome_blocks_on_stale_expected_refs() -> None:
    result = proactive_ooda_approval_reissue.record_current_proactive_ooda_approval_outcome(
        principal_id="principal-1",
        outcome="approved",
        evidence="Reviewed in operator console.",
        actor="operator@example.com",
        root=Path("/tmp/ea"),
        state_path="state/proactive_ooda_notified.json",
        expected_packet_ref="stage_packet:stale-packet",
        bundle_loader=lambda **_: _current_bundle(),
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "current_packet_ref_mismatch"
    assert result["current_packet_live_pending_count"] == 1
    assert result["expected_packet_ref_sha256"]
    assert result["current_packet_ref_sha256"]


def test_record_current_proactive_ooda_approval_outcome_records_and_returns_materialization() -> None:
    captured: dict[str, object] = {}

    def _finalizer(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "approval_outcome": {
                "approval_outcome_recorded": True,
                "status": "accepted_redacted",
                "accepted": True,
                "source_kind": "operator_manual",
                "recorded_at": "2026-06-30T08:00:00Z",
            },
            "operator_status_materialization": {"status": "materialized"},
            "gold_acceptance_materialization": {"status": "materialized"},
            "teable_sync": {"status": "disabled", "sync_attempted": False},
        }

    result = proactive_ooda_approval_reissue.record_current_proactive_ooda_approval_outcome(
        principal_id="principal-1",
        outcome="approved",
        evidence="Reviewed in operator console.",
        actor="operator@example.com",
        root=Path("/tmp/ea"),
        state_path="state/proactive_ooda_notified.json",
        expected_packet_ref="stage_packet:packet-1",
        expected_staged_artifact_ref="safe_work_result:result-1",
        bundle_loader=lambda **_: _current_bundle(),
        finalizer=_finalizer,
    )

    assert captured["packet_ref"] == "stage_packet:packet-1"
    assert captured["staged_artifact_ref"] == "safe_work_result:result-1"
    assert captured["principal_id"] == "principal-1"
    assert result["status"] == "recorded"
    assert result["approval_outcome_status"] == "accepted_redacted"
    assert result["approval_outcome_accepted"] is True
    assert result["current_packet_live_pending_count"] == 1
    assert result["operator_status_materialization"] == {"status": "materialized"}
    assert result["gold_acceptance_materialization"] == {"status": "materialized"}
    assert result["teable_sync"] == {"status": "disabled", "sync_attempted": False}


def test_record_current_proactive_ooda_approval_outcome_detects_current_decision() -> None:
    bundle = _current_bundle()
    approval_request = proactive_ooda_approval_reissue.current_proactive_ooda_approval_request(bundle)
    bundle["approval_outcome"] = {
        "approval_outcome_recorded": True,
        "status": "accepted_redacted",
        "packet_ref_sha256": proactive_ooda_approval_reissue._hash_value(approval_request["packet_ref"]),  # noqa: SLF001
        "staged_artifact_sha256": proactive_ooda_approval_reissue._hash_value(approval_request["staged_artifact_ref"]),  # noqa: SLF001
    }

    result = proactive_ooda_approval_reissue.record_current_proactive_ooda_approval_outcome(
        principal_id="principal-1",
        outcome="approved",
        evidence="Reviewed in operator console.",
        actor="operator@example.com",
        root=Path("/tmp/ea"),
        state_path="state/proactive_ooda_notified.json",
        bundle_loader=lambda **_: bundle,
    )

    assert result["status"] == "already_decided"
    assert result["reason"] == "current_packet_approval_outcome_already_recorded"
    assert result["approval_outcome_status"] == "accepted_redacted"
