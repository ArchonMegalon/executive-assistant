from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType


GENERATED_AT = "2026-06-19T21:15:00Z"


def _load_script(name: str) -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "ea" / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_office_loop_goal_receipt_materializes_seeded_local_loop(tmp_path: Path) -> None:
    materializer = _load_script("materialize_office_loop_goal_receipt")
    verifier = _load_script("verify_office_loop_goal_receipt")
    receipt_path = tmp_path / "office-loop.generated.json"

    receipt = materializer.materialize_office_loop_goal_receipt(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        proactive_operator_status_receipt_path=tmp_path / "missing-proactive-operator.generated.json",
        proactive_gold_acceptance_receipt_path=tmp_path / "missing-proactive-gold.generated.json",
    )

    assert receipt["status"] == "ready_local_evidence"
    assert receipt["goal_completion_claim_allowed"] is False
    assert receipt["live_daily_use_verified"] is False
    assert receipt["real_operator_acceptance_verified"] is False
    assert receipt["next_action"] == "collect a real proactive OODA packet that starts from an approved source or transcript signal, browses live options, auditor-checks provider and context fit, chooses a candidate, stages a reversible shortlist, cart, booking candidate, or Gmail draft, routes it honestly, mirrors delivery, current-packet, pending-approval, stale-approval, and decision facts into Teable, and captures the approval outcome"
    assert receipt["boundary_posture"]["ea_is_product_truth"] is False  # type: ignore[index]
    assert receipt["seeded_fixture"]["raw_private_context_exposed"] is False  # type: ignore[index]
    for key, row in receipt["components"].items():  # type: ignore[union-attr]
        assert row["status"] == "pass", key
        assert row["evidence_route"], key
    assert {"memo", "approvals", "operator"} <= set(receipt["diagnostics_summary"]["channel_loop_digest_keys"])  # type: ignore[index]
    assert "real approved outbound action with audit trail" in receipt["remaining_external_proofs"]
    additional_goals = {row["key"]: row for row in receipt["additional_goals"]}  # type: ignore[index]
    quality_goal = additional_goals["executive_assistant_quality_readiness"]
    assert quality_goal["status"] == "active_local_goal"
    assert quality_goal["claim_limit"] == "local_quality_readiness_not_real_daily_acceptance"
    assert "useful_morning_brief" in quality_goal["requires"]
    assert "real_daily_use_acceptance_before_good_ea_claim" in quality_goal["requires"]
    assert "approved_action_workflow" in quality_goal["protected_quality_dimensions"]
    acceptance_goal = additional_goals["executive_assistant_acceptance_evidence"]
    assert acceptance_goal["status"] == "active_local_goal"
    assert acceptance_goal["claim_limit"] == "hashed_acceptance_evidence_not_goal_completion"
    assert "real_provider_failure_recovered" in acceptance_goal["requires"]
    assert "privacy_and_redaction" in acceptance_goal["protected_acceptance_dimensions"]
    governor_goal = additional_goals["whole_project_product_governor_loop"]
    assert governor_goal["status"] == "active_local_goal"
    assert governor_goal["claim_limit"] == "local_goal_set_not_external_completion"
    assert "ready_tonight" in governor_goal["protected_pressures"]
    assert "human_acceptance_before_public_or_premium_claim" in governor_goal["requires"]
    scope_gap_goal = additional_goals["whole_project_scope_gap_audit"]
    assert scope_gap_goal["status"] == "active_local_goal"
    assert scope_gap_goal["claim_limit"] == "local_scope_audit_not_canonical_product_truth"
    assert "run_session" in scope_gap_goal["protected_scope_axes"]
    assert "privacy_retention_support_telemetry_check" in scope_gap_goal["requires"]
    signal_goal = additional_goals["whole_project_signal_to_decision_closure"]
    assert signal_goal["status"] == "active_local_goal"
    assert signal_goal["claim_limit"] == "local_signal_synthesis_not_canonical_queue_or_release_truth"
    assert "weekly_operator_decision_packet" in signal_goal["requires"]
    assert "human_acceptance_before_queue_or_release_claim" in signal_goal["requires"]
    assert "provider_runtime_failures" in signal_goal["protected_signal_sources"]
    assert "release_install_update_friction" in signal_goal["protected_signal_sources"]
    proactive_goal = additional_goals["proactive_ooda_gold_production"]
    assert proactive_goal["status"] == "active_local_goal"
    assert proactive_goal["claim_limit"] == "local_proactive_ooda_readiness_not_real_assistant_grade_acceptance"
    assert "pocket_ai_audio_transcript_signal_ingest" in proactive_goal["requires"]
    assert "generic_safe_work_packets" in proactive_goal["requires"]
    assert "context_aware_auditor_before_user_delivery" in proactive_goal["requires"]
    assert "candidate_provider_fit_and_locality_validation" in proactive_goal["requires"]
    assert "live_browse_backed_candidate_research" in proactive_goal["requires"]
    assert "reversible_candidate_staging" in proactive_goal["requires"]
    assert "gmail_draft_staging_when_requested" in proactive_goal["requires"]
    assert "action_required_only_telegram_delivery" in proactive_goal["requires"]
    assert "route_selection_and_blocked_fallback_honesty" in proactive_goal["requires"]
    assert "teable_projection_of_run_facts" in proactive_goal["requires"]
    assert "teable_projection_of_delivery_and_decision_facts" in proactive_goal["requires"]
    assert "teable_projection_of_pending_approval_surface" in proactive_goal["requires"]
    assert "current_packet_and_stale_approval_telemetry" in proactive_goal["requires"]
    assert "stale_approval_cleanup_or_expiry" in proactive_goal["requires"]
    assert "approval_outcome_capture_and_follow_through_receipts" in proactive_goal["requires"]
    assert "resume_without_repeat_research" in proactive_goal["requires"]
    assert "calendar_and_renewal_signals" in proactive_goal["protected_signal_sources"]
    assert "preference_budget_and_quiet_hours_state" in proactive_goal["protected_signal_sources"]
    assert "durable_profile_and_location_context" in proactive_goal["protected_signal_sources"]
    assert "pocket_ai_audio_transcripts" in proactive_goal["protected_signal_sources"]
    assert "browser_and_vendor_page_evidence" in proactive_goal["protected_signal_sources"]
    assert "context_and_locality_constraints" in proactive_goal["protected_signal_sources"]
    assert "delivery_route_readiness" in proactive_goal["protected_signal_sources"]
    assert "route_blocker_and_recovery_state" in proactive_goal["protected_signal_sources"]
    assert "approval_and_follow_through_state" in proactive_goal["protected_signal_sources"]
    assert "gmail_draft_execution_state" in proactive_goal["protected_signal_sources"]
    assert "telegram_interruption_action_required_state" in proactive_goal["protected_signal_sources"]
    assert "current_packet_and_stale_approval_state" in proactive_goal["protected_signal_sources"]
    assert "real whole-project scope gap audit reviewed against the current product spine" in receipt["remaining_external_proofs"]
    assert "real proactive OODA packet accepted with routed delivery, approved-source or transcript signal, live browse evidence, auditor-passed chosen candidate, staged reversible artifact, mirrored Teable delivery, current-packet, pending-approval, stale-approval, and decision facts, and explicit approval outcome" in receipt["remaining_external_proofs"]
    assert "real weekly signal-to-decision review accepted by the operator" in receipt["remaining_external_proofs"]

    verification = verifier.verify_office_loop_goal_receipt(receipt_path)

    assert verification["status"] == "pass"
    assert verification["issues"] == []


def test_office_loop_goal_verifier_rejects_overclaim_and_route_regression(tmp_path: Path) -> None:
    materializer = _load_script("materialize_office_loop_goal_receipt")
    verifier = _load_script("verify_office_loop_goal_receipt")
    receipt_path = tmp_path / "tampered.generated.json"
    materializer.materialize_office_loop_goal_receipt(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["goal_completion_claim_allowed"] = True
    receipt["live_daily_use_verified"] = True
    receipt["boundary_posture"]["ea_is_product_truth"] = True
    receipt["components"]["decision_queue"]["status"] = "fail"
    receipt["route_snapshots"]["queue"]["markers_pass"] = False
    receipt["route_snapshots"]["queue"]["marker_results"]["Queue"] = False
    receipt["diagnostics_summary"]["channel_loop_digest_keys"] = ["memo"]
    additional_goals = {row["key"]: row for row in receipt["additional_goals"]}
    additional_goals["executive_assistant_quality_readiness"]["protected_quality_dimensions"].remove("approved_action_workflow")
    additional_goals["executive_assistant_acceptance_evidence"]["protected_acceptance_dimensions"].remove("privacy_and_redaction")
    additional_goals["whole_project_product_governor_loop"]["protected_pressures"].remove("ready_tonight")
    additional_goals["whole_project_scope_gap_audit"]["protected_scope_axes"].remove("run_session")
    additional_goals["whole_project_signal_to_decision_closure"]["protected_signal_sources"].remove("provider_runtime_failures")
    additional_goals["proactive_ooda_gold_production"]["requires"].remove("pocket_ai_audio_transcript_signal_ingest")
    additional_goals["proactive_ooda_gold_production"]["requires"].remove("context_aware_auditor_before_user_delivery")
    additional_goals["proactive_ooda_gold_production"]["requires"].remove("candidate_provider_fit_and_locality_validation")
    additional_goals["proactive_ooda_gold_production"]["requires"].remove("live_browse_backed_candidate_research")
    additional_goals["proactive_ooda_gold_production"]["requires"].remove("reversible_candidate_staging")
    additional_goals["proactive_ooda_gold_production"]["requires"].remove("gmail_draft_staging_when_requested")
    additional_goals["proactive_ooda_gold_production"]["requires"].remove("action_required_only_telegram_delivery")
    additional_goals["proactive_ooda_gold_production"]["requires"].remove("route_selection_and_blocked_fallback_honesty")
    additional_goals["proactive_ooda_gold_production"]["requires"].remove("teable_projection_of_run_facts")
    additional_goals["proactive_ooda_gold_production"]["requires"].remove("teable_projection_of_delivery_and_decision_facts")
    additional_goals["proactive_ooda_gold_production"]["requires"].remove("teable_projection_of_pending_approval_surface")
    additional_goals["proactive_ooda_gold_production"]["requires"].remove("current_packet_and_stale_approval_telemetry")
    additional_goals["proactive_ooda_gold_production"]["requires"].remove("stale_approval_cleanup_or_expiry")
    additional_goals["proactive_ooda_gold_production"]["requires"].remove("approval_outcome_capture_and_follow_through_receipts")
    additional_goals["proactive_ooda_gold_production"]["requires"].remove("resume_without_repeat_research")
    additional_goals["proactive_ooda_gold_production"]["protected_signal_sources"].remove("calendar_and_renewal_signals")
    additional_goals["proactive_ooda_gold_production"]["protected_signal_sources"].remove("preference_budget_and_quiet_hours_state")
    additional_goals["proactive_ooda_gold_production"]["protected_signal_sources"].remove("durable_profile_and_location_context")
    additional_goals["proactive_ooda_gold_production"]["protected_signal_sources"].remove("pocket_ai_audio_transcripts")
    additional_goals["proactive_ooda_gold_production"]["protected_signal_sources"].remove("browser_and_vendor_page_evidence")
    additional_goals["proactive_ooda_gold_production"]["protected_signal_sources"].remove("context_and_locality_constraints")
    additional_goals["proactive_ooda_gold_production"]["protected_signal_sources"].remove("delivery_route_readiness")
    additional_goals["proactive_ooda_gold_production"]["protected_signal_sources"].remove("route_blocker_and_recovery_state")
    additional_goals["proactive_ooda_gold_production"]["protected_signal_sources"].remove("approval_and_follow_through_state")
    additional_goals["proactive_ooda_gold_production"]["protected_signal_sources"].remove("gmail_draft_execution_state")
    additional_goals["proactive_ooda_gold_production"]["protected_signal_sources"].remove("telegram_interruption_action_required_state")
    additional_goals["proactive_ooda_gold_production"]["protected_signal_sources"].remove("current_packet_and_stale_approval_state")
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verifier.verify_office_loop_goal_receipt(receipt_path)

    assert verification["status"] == "fail"
    assert "office_loop_completion_overclaim" in verification["issues"]
    assert "office_loop_live_daily_use_overclaim" in verification["issues"]
    assert "office_loop_ea_product_truth_overclaim" in verification["issues"]
    assert "office_loop_component_not_pass:decision_queue" in verification["issues"]
    assert "office_loop_route_markers_not_pass:queue" in verification["issues"]
    assert "office_loop_channel_loop_digest_missing:approvals" in verification["issues"]
    assert "office_loop_channel_loop_digest_missing:operator" in verification["issues"]
    assert "office_loop_executive_assistant_quality_dimension_missing:approved_action_workflow" in verification["issues"]
    assert "office_loop_executive_assistant_acceptance_dimension_missing:privacy_and_redaction" in verification["issues"]
    assert "office_loop_product_governor_pressure_missing:ready_tonight" in verification["issues"]
    assert "office_loop_scope_gap_audit_axis_missing:run_session" in verification["issues"]
    assert "office_loop_signal_to_decision_source_missing:provider_runtime_failures" in verification["issues"]
    assert "office_loop_proactive_ooda_requirement_missing:pocket_ai_audio_transcript_signal_ingest" in verification["issues"]
    assert "office_loop_proactive_ooda_requirement_missing:context_aware_auditor_before_user_delivery" in verification["issues"]
    assert "office_loop_proactive_ooda_requirement_missing:candidate_provider_fit_and_locality_validation" in verification["issues"]
    assert "office_loop_proactive_ooda_requirement_missing:live_browse_backed_candidate_research" in verification["issues"]
    assert "office_loop_proactive_ooda_requirement_missing:reversible_candidate_staging" in verification["issues"]
    assert "office_loop_proactive_ooda_requirement_missing:gmail_draft_staging_when_requested" in verification["issues"]
    assert "office_loop_proactive_ooda_requirement_missing:action_required_only_telegram_delivery" in verification["issues"]
    assert "office_loop_proactive_ooda_requirement_missing:route_selection_and_blocked_fallback_honesty" in verification["issues"]
    assert "office_loop_proactive_ooda_requirement_missing:teable_projection_of_run_facts" in verification["issues"]
    assert "office_loop_proactive_ooda_requirement_missing:teable_projection_of_delivery_and_decision_facts" in verification["issues"]
    assert "office_loop_proactive_ooda_requirement_missing:teable_projection_of_pending_approval_surface" in verification["issues"]
    assert "office_loop_proactive_ooda_requirement_missing:current_packet_and_stale_approval_telemetry" in verification["issues"]
    assert "office_loop_proactive_ooda_requirement_missing:stale_approval_cleanup_or_expiry" in verification["issues"]
    assert "office_loop_proactive_ooda_requirement_missing:approval_outcome_capture_and_follow_through_receipts" in verification["issues"]
    assert "office_loop_proactive_ooda_requirement_missing:resume_without_repeat_research" in verification["issues"]
    assert "office_loop_proactive_ooda_source_missing:calendar_and_renewal_signals" in verification["issues"]
    assert "office_loop_proactive_ooda_source_missing:preference_budget_and_quiet_hours_state" in verification["issues"]
    assert "office_loop_proactive_ooda_source_missing:durable_profile_and_location_context" in verification["issues"]
    assert "office_loop_proactive_ooda_source_missing:pocket_ai_audio_transcripts" in verification["issues"]
    assert "office_loop_proactive_ooda_source_missing:browser_and_vendor_page_evidence" in verification["issues"]
    assert "office_loop_proactive_ooda_source_missing:context_and_locality_constraints" in verification["issues"]
    assert "office_loop_proactive_ooda_source_missing:delivery_route_readiness" in verification["issues"]
    assert "office_loop_proactive_ooda_source_missing:route_blocker_and_recovery_state" in verification["issues"]
    assert "office_loop_proactive_ooda_source_missing:approval_and_follow_through_state" in verification["issues"]
    assert "office_loop_proactive_ooda_source_missing:gmail_draft_execution_state" in verification["issues"]
    assert "office_loop_proactive_ooda_source_missing:telegram_interruption_action_required_state" in verification["issues"]
    assert "office_loop_proactive_ooda_source_missing:current_packet_and_stale_approval_state" in verification["issues"]


def test_office_loop_goal_receipt_clis_work(tmp_path: Path) -> None:
    script_root = Path(__file__).resolve().parents[1] / "ea" / "scripts"
    receipt_path = tmp_path / "cli-office-loop.generated.json"
    materialized = subprocess.run(
        [
            sys.executable,
            str(script_root / "materialize_office_loop_goal_receipt.py"),
            "--receipt",
            str(receipt_path),
            "--generated-at",
            GENERATED_AT,
        ],
        cwd=Path(__file__).resolve().parents[1] / "ea",
        text=True,
        capture_output=True,
        check=False,
    )
    assert materialized.returncode == 0, materialized.stderr + materialized.stdout
    receipt = json.loads(materialized.stdout)
    assert receipt["status"] == "ready_local_evidence"
    assert receipt["receipt"] == receipt_path.as_posix()

    verified = subprocess.run(
        [
            sys.executable,
            str(script_root / "verify_office_loop_goal_receipt.py"),
            "--receipt",
            str(receipt_path),
        ],
        cwd=Path(__file__).resolve().parents[1] / "ea",
        text=True,
        capture_output=True,
        check=False,
    )
    assert verified.returncode == 0, verified.stderr + verified.stdout
    verification = json.loads(verified.stdout)
    assert verification["status"] == "pass"
