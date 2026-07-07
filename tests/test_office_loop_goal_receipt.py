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
        google_workspace_oauth_readiness_receipt_path=tmp_path / "missing-google-oauth.generated.json",
    )

    assert receipt["status"] == "ready_local_evidence"
    assert receipt["head_semantics"] == "source_state"
    assert receipt["source_git_head"]
    assert receipt["source_state_fingerprint"]
    assert (
        receipt["source_state_fingerprint_semantics"]
        == "worktree_source_files_sha256_excluding_generated_only_paths"
    )
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
    assert receipt["diagnostics_summary"]["google_workspace_oauth_status"] == "missing"
    assert "real approved outbound action with audit trail" not in receipt["remaining_external_proofs"]
    assert "real provider failure recovered with operator-grade reason" not in receipt["remaining_external_proofs"]
    assert "Google Workspace OAuth test-user or verified app access for Full Workspace auth" in receipt["remaining_external_proofs"]
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
    assert "cost_aware_background_model_routing_to_1min_ai" in proactive_goal["requires"]
    assert "gemini_vertex_token_telemetry_and_soft_cap" in proactive_goal["requires"]
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
    assert "provider_token_usage_and_cost_pressure_state" in proactive_goal["protected_signal_sources"]
    assert proactive_goal["provider_cost_controls"] == {
        "background_work_primary_provider": "onemin",
        "background_work_primary_provider_label": "1min.ai",
        "background_work_route_authority": "active_onemin_manager_when_usable",
        "background_work_prefer_onemin_whenever_usable": True,
        "gemini_vertex_alias": "gemini_vortex",
        "gemini_token_tracking_required": True,
        "gemini_soft_cap_required": True,
        "gemini_fallback_only_when_onemin_unavailable_or_explicit": True,
        "explicit_gemini_requests_allowed": True,
        "billing_truth_boundary": "token_ledger_is_cost_pressure_telemetry_not_google_cloud_billing_truth",
    }
    cost_posture = receipt["provider_cost_routing_posture"]
    assert cost_posture["status"] == "active_cost_control"
    assert cost_posture["background_routing"]["primary_background_provider"] == "onemin"
    assert cost_posture["background_routing"]["default_provider_order"] == [
        "onemin",
        "magixai",
        "gemini_vortex",
    ]
    assert cost_posture["background_routing"]["fast_provider_order"] == [
        "onemin",
        "magixai",
        "gemini_vortex",
    ]
    assert cost_posture["background_routing"]["cheap_provider_order"] == [
        "onemin",
        "magixai",
        "gemini_vortex",
    ]
    assert cost_posture["background_routing"]["groundwork_provider_order"] == [
        "onemin",
        "magixai",
        "gemini_vortex",
    ]
    assert cost_posture["background_routing"]["hard_provider_order"] == [
        "onemin",
        "magixai",
        "gemini_vortex",
    ]
    assert cost_posture["background_routing"]["onemin_preferred_when_speed_is_not_critical"] is True
    assert cost_posture["background_routing"]["onemin_preferred_whenever_usable"] is True
    assert cost_posture["background_routing"]["route_through_active_onemin_manager_when_available"] is True
    assert cost_posture["background_routing"]["gemini_fallback_only_when_onemin_unavailable_or_explicit"] is True
    assert cost_posture["gemini_vertex"]["provider_key"] == "gemini_vortex"
    assert cost_posture["gemini_vertex"]["token_tracking_required"] is True
    assert cost_posture["gemini_vertex"]["fallback_only"] is True
    assert cost_posture["gemini_vertex"]["dispatch_ledger"] == "provider_dispatch_events.jsonl"
    assert (
        cost_posture["gemini_vertex"]["live_pressure_probe_command"]
        == "python3 scripts/ea_live_ops.py probe-provider-cost-pressure --window 24h --format json"
    )
    assert cost_posture["gemini_vertex"]["live_pressure_probe_source"] == "runtime_container_exec:provider_ledger_cache"
    assert "tokens_in" in cost_posture["gemini_vertex"]["tracked_dispatch_fields"]
    assert "tokens_out" in cost_posture["gemini_vertex"]["tracked_dispatch_fields"]
    assert "total_tokens" in cost_posture["gemini_vertex"]["tracked_dispatch_fields"]
    assert cost_posture["gemini_vertex"]["soft_cap_env"] == "EA_RESPONSES_GEMINI_VORTEX_TOKEN_SOFT_CAP_24H"
    assert cost_posture["gemini_vertex"]["soft_cap_action"] == "remove_gemini_vortex_from_cost_gated_background_candidate_lists"
    assert cost_posture["gemini_vertex"]["explicit_gemini_requests_allowed"] is True
    assert (
        cost_posture["gemini_vertex"]["billing_truth_boundary"]
        == "token_ledger_is_cost_pressure_telemetry_not_google_cloud_billing_truth"
    )
    assert cost_posture["privacy"]["raw_provider_secret_exposed"] is False
    assert cost_posture["privacy"]["raw_prompt_or_response_text_exposed"] is False
    assert cost_posture["privacy"]["raw_google_cloud_billing_account_exposed"] is False
    assert "real whole-project scope gap audit reviewed against the current product spine" in receipt["remaining_external_proofs"]
    assert "real proactive OODA packet accepted with routed delivery, approved-source or transcript signal, live browse evidence, auditor-passed chosen candidate, staged reversible artifact, mirrored Teable delivery, current-packet, pending-approval, stale-approval, and decision facts, and explicit approval outcome" in receipt["remaining_external_proofs"]
    assert "real weekly signal-to-decision review accepted by the operator" in receipt["remaining_external_proofs"]
    scope_gap_evidence = receipt["evidence_receipts"]["whole_project_scope_gap_audit"]  # type: ignore[index]
    assert scope_gap_evidence["path"].endswith("ea_whole_project_scope_gap_audit.generated.json")
    assert scope_gap_evidence["reviewed_against_current_product_spine"] is False
    assert scope_gap_evidence["operator_review_accepted"] is False
    google_workspace_evidence = receipt["evidence_receipts"]["google_workspace_oauth_readiness"]  # type: ignore[index]
    assert google_workspace_evidence["present"] is False
    assert google_workspace_evidence["ready"] is False

    verification = verifier.verify_office_loop_goal_receipt(receipt_path)

    assert verification["status"] == "pass"
    assert verification["issues"] == []


def test_office_loop_goal_verifier_rejects_missing_source_state(tmp_path: Path) -> None:
    materializer = _load_script("materialize_office_loop_goal_receipt")
    verifier = _load_script("verify_office_loop_goal_receipt")
    receipt_path = tmp_path / "missing-source-state.generated.json"
    materializer.materialize_office_loop_goal_receipt(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        google_workspace_oauth_readiness_receipt_path=tmp_path / "missing-google-oauth.generated.json",
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt.pop("source_git_head", None)
    receipt.pop("source_state_fingerprint", None)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verifier.verify_office_loop_goal_receipt(receipt_path)

    assert verification["status"] == "fail"
    assert "office_loop_source_git_head_missing" in verification["issues"]
    assert "office_loop_source_state_fingerprint_missing" in verification["issues"]


def test_office_loop_goal_receipt_propagates_proactive_approval_capture_surface(tmp_path: Path) -> None:
    materializer = _load_script("materialize_office_loop_goal_receipt")
    verifier = _load_script("verify_office_loop_goal_receipt")
    receipt_path = tmp_path / "office-loop-approval-surface.generated.json"
    proactive_gold_path = tmp_path / "ea_proactive_ooda_gold_acceptance.generated.json"
    proactive_operator_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"

    proactive_gold_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.proactive_ooda_gold_acceptance.v1",
                "status": "ready_for_approval_outcome_capture",
                "summary": "A proactive OODA packet has local gold-proof runtime evidence and a live Telegram approval capture surface; capture the redacted approval outcome next.",
                "next_action": "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome",
                "next_action_href": "https://myexternalbrain.com/admin/proactive-ooda/approval",
                "next_action_label": "Record packet verdict",
                "next_action_method": "get",
                "proofs": {"approval_outcome": {"approval_outcome_recorded": False, "accepted": False}},
                "evidence_receipts": {"approval_capture_surface": {"ready": True}},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    proactive_operator_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.proactive_ooda_operator_status.v1",
                "status": "ready_with_live_receipt",
                "summary": "Proactive OODA route, packet runtime, latest host-visible live receipt, and Telegram approval capture surface are ready for operator follow-through.",
                "next_action": "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome",
                "next_action_href": "https://myexternalbrain.com/admin/proactive-ooda/approval",
                "next_action_label": "Record packet verdict",
                "next_action_method": "get",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    receipt = materializer.materialize_office_loop_goal_receipt(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        proactive_operator_status_receipt_path=proactive_operator_path,
        proactive_gold_acceptance_receipt_path=proactive_gold_path,
        google_workspace_oauth_readiness_receipt_path=tmp_path / "missing-google-oauth.generated.json",
    )

    assert receipt["next_action"] == "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome"
    assert receipt["next_action_href"] == "https://myexternalbrain.com/admin/proactive-ooda/approval"
    assert receipt["next_action_label"] == "Record packet verdict"
    assert receipt["next_action_method"] == "get"
    assert receipt["operator_next_action_source"] == "proactive_ooda_followthrough"
    assert receipt["proactive_ooda_followthrough_posture"]["next_action"] == receipt["next_action"]
    assert receipt["proactive_ooda_followthrough_posture"]["next_action_href"] == receipt["next_action_href"]
    assert receipt["proactive_ooda_followthrough_posture"]["next_action_label"] == receipt["next_action_label"]
    assert receipt["proactive_ooda_followthrough_posture"]["next_action_method"] == receipt["next_action_method"]

    verification = verifier.verify_office_loop_goal_receipt(receipt_path)
    assert verification["status"] == "pass"
    assert verification["issues"] == []


def test_office_loop_goal_receipt_prioritizes_google_workspace_oauth_when_blocked(tmp_path: Path) -> None:
    materializer = _load_script("materialize_office_loop_goal_receipt")
    verifier = _load_script("verify_office_loop_goal_receipt")
    receipt_path = tmp_path / "office-loop-google-oauth-blocked.generated.json"
    proactive_gold_path = tmp_path / "ea_proactive_ooda_gold_acceptance.generated.json"
    proactive_operator_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    google_oauth_path = tmp_path / "ea_google_workspace_oauth_readiness.generated.json"

    proactive_gold_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.proactive_ooda_gold_acceptance.v1",
                "status": "pass",
                "summary": "Gold proactive OODA proof is present.",
                "next_action": "maintain_proactive_ooda_gold_acceptance_evidence",
                "next_action_href": "https://myexternalbrain.com/admin/goals",
                "next_action_label": "Open goals",
                "next_action_method": "get",
                "proofs": {"approval_outcome": {"approval_outcome_recorded": True, "accepted": True}},
                "evidence_receipts": {"approval_capture_surface": {"ready": True}},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    proactive_operator_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.proactive_ooda_operator_status.v1",
                "status": "ready_with_live_receipt",
                "summary": "Operator runtime ready.",
                "next_action": "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome",
                "next_action_href": "https://myexternalbrain.com/admin/proactive-ooda/approval",
                "next_action_label": "Record packet verdict",
                "next_action_method": "get",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    google_oauth_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.google_workspace_oauth_readiness.v1",
                "status": "blocked_setup_required",
                "next_action": "retry_full_workspace_auth_with_approved_account",
                "next_action_href": "/integrations/google",
                "next_action_label": "Retry Google auth",
                "next_action_method": "get",
                "operator_action": {
                    "instruction": "Retry the Full Workspace auth link with the approved work account.",
                    "next_action": "retry_full_workspace_auth_with_approved_account",
                    "next_action_href": "/integrations/google",
                    "next_action_label": "Retry Google auth",
                    "next_action_method": "get",
                    "user_action_required": True,
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    receipt = materializer.materialize_office_loop_goal_receipt(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        proactive_operator_status_receipt_path=proactive_operator_path,
        proactive_gold_acceptance_receipt_path=proactive_gold_path,
        google_workspace_oauth_readiness_receipt_path=google_oauth_path,
    )

    assert receipt["next_action"] == "retry_full_workspace_auth_with_approved_account"
    assert receipt["next_action_href"] == "/integrations/google"
    assert receipt["next_action_label"] == "Retry Google auth"
    assert receipt["next_action_method"] == "get"
    assert receipt["operator_next_action_source"] == "google_workspace_oauth_readiness"
    assert receipt["proactive_ooda_followthrough_posture"]["next_action"] == "maintain_proactive_ooda_gold_acceptance_evidence"
    google_workspace_evidence = receipt["evidence_receipts"]["google_workspace_oauth_readiness"]
    assert google_workspace_evidence["present"] is True
    assert google_workspace_evidence["ready"] is False
    assert google_workspace_evidence["user_action_required"] is True
    assert google_workspace_evidence["summary"] == "Retry the Full Workspace auth link with the approved work account."
    assert "Google Workspace OAuth test-user or verified app access for Full Workspace auth" in receipt["remaining_external_proofs"]

    verification = verifier.verify_office_loop_goal_receipt(receipt_path)
    assert verification["status"] == "pass"
    assert verification["issues"] == []


def test_office_loop_goal_receipt_prefers_operator_runtime_recovery_surface_for_blocked_proactive_followthrough(
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_office_loop_goal_receipt")
    verifier = _load_script("verify_office_loop_goal_receipt")
    receipt_path = tmp_path / "office-loop-proactive-runtime-recovery.generated.json"
    proactive_gold_path = tmp_path / "ea_proactive_ooda_gold_acceptance.generated.json"
    proactive_operator_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"

    proactive_gold_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.proactive_ooda_gold_acceptance.v1",
                "status": "blocked_operator_runtime_posture",
                "summary": (
                    "The proactive OODA packet proofs exist, but operator runtime posture is blocked and gold "
                    "cannot be claimed until approved source health is restored."
                ),
                "next_action": "repair_proactive_operator_runtime_posture",
                "next_action_href": "https://myexternalbrain.com/admin/goals",
                "next_action_label": "Open goals",
                "next_action_method": "get",
                "proofs": {"approval_outcome": {"approval_outcome_recorded": False, "accepted": False}},
                "evidence_receipts": {"approval_capture_surface": {"ready": False}},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    proactive_operator_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.proactive_ooda_operator_status.v1",
                "status": "ready_with_recovery_action",
                "summary": (
                    "Proactive OODA routing is available, but Google workspace needs reauthorization before EA "
                    "can rely on that source (google_oauth_invalid_grant)."
                ),
                "next_action": "reauthorize_google_workspace_binding",
                "next_action_href": (
                    "https://myexternalbrain.com/app/actions/google/connect?"
                    "return_to=%2Fapp%2Fsettings%2Fgoogle&scope_bundle=full_workspace"
                ),
                "next_action_label": "Reconnect Google workspace",
                "next_action_method": "get",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    receipt = materializer.materialize_office_loop_goal_receipt(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        proactive_operator_status_receipt_path=proactive_operator_path,
        proactive_gold_acceptance_receipt_path=proactive_gold_path,
        google_workspace_oauth_readiness_receipt_path=tmp_path / "missing-google-oauth.generated.json",
    )

    assert receipt["next_action"] == "reauthorize_google_workspace_binding"
    assert receipt["next_action_href"] == (
        "https://myexternalbrain.com/app/actions/google/connect?"
        "return_to=%2Fapp%2Fsettings%2Fgoogle&scope_bundle=full_workspace"
    )
    assert receipt["next_action_label"] == "Reconnect Google workspace"
    assert receipt["next_action_method"] == "get"
    assert receipt["operator_next_action_source"] == "proactive_ooda_followthrough"
    assert receipt["proactive_ooda_followthrough_posture"]["next_action"] == "reauthorize_google_workspace_binding"
    assert receipt["proactive_ooda_followthrough_posture"]["next_action_href"] == receipt["next_action_href"]
    assert receipt["proactive_ooda_followthrough_posture"]["next_action_label"] == receipt["next_action_label"]
    assert receipt["proactive_ooda_followthrough_posture"]["next_action_method"] == receipt["next_action_method"]

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
        google_workspace_oauth_readiness_receipt_path=tmp_path / "missing-google-oauth.generated.json",
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["goal_completion_claim_allowed"] = True
    receipt["live_daily_use_verified"] = True
    receipt["boundary_posture"]["ea_is_product_truth"] = True
    receipt["components"]["decision_queue"]["status"] = "fail"
    receipt["route_snapshots"]["queue"]["markers_pass"] = False
    receipt["route_snapshots"]["queue"]["marker_results"]["Queue"] = False
    receipt["diagnostics_summary"]["channel_loop_digest_keys"] = ["memo"]
    receipt["diagnostics_summary"]["provider_cost_routing_status"] = "missing"
    receipt["provider_cost_routing_posture"]["background_routing"]["primary_background_provider"] = "gemini_vortex"
    receipt["provider_cost_routing_posture"]["background_routing"]["default_provider_order"] = [
        "gemini_vortex",
        "onemin",
    ]
    receipt["provider_cost_routing_posture"]["background_routing"]["fast_provider_order"] = [
        "gemini_vortex",
        "onemin",
    ]
    receipt["provider_cost_routing_posture"]["background_routing"]["cheap_provider_order"] = [
        "gemini_vortex",
        "onemin",
    ]
    receipt["provider_cost_routing_posture"]["background_routing"]["groundwork_provider_order"] = [
        "gemini_vortex",
        "onemin",
    ]
    receipt["provider_cost_routing_posture"]["background_routing"]["hard_provider_order"] = [
        "gemini_vortex",
        "onemin",
    ]
    receipt["provider_cost_routing_posture"]["background_routing"]["onemin_preferred_when_speed_is_not_critical"] = False
    receipt["provider_cost_routing_posture"]["background_routing"]["onemin_preferred_whenever_usable"] = False
    receipt["provider_cost_routing_posture"]["gemini_vertex"]["token_tracking_required"] = False
    receipt["provider_cost_routing_posture"]["gemini_vertex"]["tracked_dispatch_fields"].remove("tokens_in")
    receipt["provider_cost_routing_posture"]["gemini_vertex"]["soft_cap_env"] = "WRONG"
    receipt["provider_cost_routing_posture"]["gemini_vertex"].pop("live_pressure_probe_command", None)
    receipt["provider_cost_routing_posture"]["gemini_vertex"]["billing_truth_boundary"] = "google_cloud_invoice_truth"
    receipt["provider_cost_routing_posture"]["privacy"]["raw_provider_secret_exposed"] = True
    additional_goals = {row["key"]: row for row in receipt["additional_goals"]}
    additional_goals["executive_assistant_quality_readiness"]["protected_quality_dimensions"].remove("approved_action_workflow")
    additional_goals["executive_assistant_acceptance_evidence"]["protected_acceptance_dimensions"].remove("privacy_and_redaction")
    additional_goals["whole_project_product_governor_loop"]["protected_pressures"].remove("ready_tonight")
    additional_goals["whole_project_scope_gap_audit"]["protected_scope_axes"].remove("run_session")
    additional_goals["whole_project_signal_to_decision_closure"]["protected_signal_sources"].remove("provider_runtime_failures")
    additional_goals["proactive_ooda_gold_production"]["requires"].remove("pocket_ai_audio_transcript_signal_ingest")
    additional_goals["proactive_ooda_gold_production"]["requires"].remove("cost_aware_background_model_routing_to_1min_ai")
    additional_goals["proactive_ooda_gold_production"]["requires"].remove("gemini_vertex_token_telemetry_and_soft_cap")
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
    additional_goals["proactive_ooda_gold_production"]["protected_signal_sources"].remove("provider_token_usage_and_cost_pressure_state")
    additional_goals["proactive_ooda_gold_production"]["provider_cost_controls"]["background_work_primary_provider"] = "gemini_vortex"
    additional_goals["proactive_ooda_gold_production"]["provider_cost_controls"]["background_work_prefer_onemin_whenever_usable"] = False
    additional_goals["proactive_ooda_gold_production"]["provider_cost_controls"]["gemini_token_tracking_required"] = False
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
    assert "office_loop_diagnostics_missing:provider_cost_routing_status" in verification["issues"]
    assert "office_loop_executive_assistant_quality_dimension_missing:approved_action_workflow" in verification["issues"]
    assert "office_loop_executive_assistant_acceptance_dimension_missing:privacy_and_redaction" in verification["issues"]
    assert "office_loop_product_governor_pressure_missing:ready_tonight" in verification["issues"]
    assert "office_loop_scope_gap_audit_axis_missing:run_session" in verification["issues"]
    assert "office_loop_signal_to_decision_source_missing:provider_runtime_failures" in verification["issues"]
    assert "office_loop_proactive_ooda_requirement_missing:pocket_ai_audio_transcript_signal_ingest" in verification["issues"]
    assert "office_loop_proactive_ooda_requirement_missing:cost_aware_background_model_routing_to_1min_ai" in verification["issues"]
    assert "office_loop_proactive_ooda_requirement_missing:gemini_vertex_token_telemetry_and_soft_cap" in verification["issues"]
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
    assert "office_loop_proactive_ooda_source_missing:provider_token_usage_and_cost_pressure_state" in verification["issues"]
    assert "office_loop_provider_cost_control_background_provider_not_onemin" in verification["issues"]
    assert "office_loop_provider_cost_control_onemin_preference_missing" in verification["issues"]
    assert "office_loop_provider_cost_control_gemini_token_tracking_not_required" in verification["issues"]
    assert "office_loop_provider_cost_background_primary_not_onemin" in verification["issues"]
    assert "office_loop_provider_cost_fast_order_drifted" in verification["issues"]
    assert "office_loop_provider_cost_cheap_order_drifted" in verification["issues"]
    assert "office_loop_provider_cost_groundwork_order_drifted" in verification["issues"]
    assert "office_loop_provider_cost_hard_order_drifted" in verification["issues"]
    assert "office_loop_provider_cost_onemin_preference_missing" in verification["issues"]
    assert "office_loop_provider_cost_onemin_preference_scope_missing" in verification["issues"]
    assert "office_loop_provider_cost_gemini_token_tracking_missing" in verification["issues"]
    assert "office_loop_provider_cost_tracked_field_missing:tokens_in" in verification["issues"]
    assert "office_loop_provider_cost_gemini_soft_cap_env_drifted" in verification["issues"]
    assert "office_loop_provider_cost_live_pressure_probe_command_missing" in verification["issues"]
    assert "office_loop_provider_cost_billing_truth_boundary_missing" in verification["issues"]
    assert "office_loop_provider_cost_privacy_leak:raw_provider_secret_exposed" in verification["issues"]


def test_office_loop_goal_verifier_rejects_missing_proactive_action_surface(tmp_path: Path) -> None:
    materializer = _load_script("materialize_office_loop_goal_receipt")
    verifier = _load_script("verify_office_loop_goal_receipt")
    receipt_path = tmp_path / "missing-action-surface.generated.json"
    proactive_gold_path = tmp_path / "ea_proactive_ooda_gold_acceptance.generated.json"
    proactive_operator_path = tmp_path / "ea_proactive_ooda_operator_status.generated.json"

    proactive_gold_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.proactive_ooda_gold_acceptance.v1",
                "status": "ready_for_approval_outcome_capture",
                "summary": "Ready to capture approval outcome.",
                "next_action": "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome",
                "next_action_href": "https://myexternalbrain.com/admin/proactive-ooda/approval",
                "next_action_label": "Record packet verdict",
                "next_action_method": "get",
                "proofs": {"approval_outcome": {"approval_outcome_recorded": False, "accepted": False}},
                "evidence_receipts": {"approval_capture_surface": {"ready": True}},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    proactive_operator_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.proactive_ooda_operator_status.v1",
                "status": "ready_with_live_receipt",
                "summary": "Operator runtime ready for follow-through.",
                "next_action": "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome",
                "next_action_href": "https://myexternalbrain.com/admin/proactive-ooda/approval",
                "next_action_label": "Record packet verdict",
                "next_action_method": "get",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    materializer.materialize_office_loop_goal_receipt(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        proactive_operator_status_receipt_path=proactive_operator_path,
        proactive_gold_acceptance_receipt_path=proactive_gold_path,
        google_workspace_oauth_readiness_receipt_path=tmp_path / "missing-google-oauth.generated.json",
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["next_action"] = "collect a real proactive OODA packet"
    receipt["next_action_href"] = ""
    receipt["next_action_label"] = ""
    receipt["next_action_method"] = ""
    receipt["proactive_ooda_followthrough_posture"]["next_action"] = "collect a real proactive OODA packet"
    receipt["proactive_ooda_followthrough_posture"]["next_action_href"] = ""
    receipt["proactive_ooda_followthrough_posture"]["next_action_label"] = ""
    receipt["proactive_ooda_followthrough_posture"]["next_action_method"] = ""
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verifier.verify_office_loop_goal_receipt(receipt_path)
    assert verification["status"] == "fail"
    assert "office_loop_followthrough_posture_missing_action_surface" in verification["issues"]
    assert "office_loop_followthrough_posture_missing_action_href" in verification["issues"]
    assert "office_loop_followthrough_posture_missing_action_label" in verification["issues"]
    assert "office_loop_followthrough_posture_missing_action_method" in verification["issues"]


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
