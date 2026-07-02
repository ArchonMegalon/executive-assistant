from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.source_state_head import resolve_source_state_head
from scripts.source_state_head import resolve_source_worktree_fingerprint

DEFAULT_RECEIPT = REPO_ROOT / ".codex-studio" / "published" / "ea_office_loop_goal.generated.json"
REMAINING_PROOF_LABELS = {
    "real_daily_morning_brief_accepted": "real daily morning brief acceptance",
    "real_decision_cleared": "real decision cleared by the principal or operator",
    "real_commitment_recovered_or_closed": "real commitment recovered or closed with an evidence receipt",
    "real_approved_action_audited": "real approved outbound action with audit trail",
    "real_provider_failure_recovered": "real provider failure recovered with operator-grade reason",
}
PROACTIVE_OODA_PROOF_LABEL = (
    "real proactive OODA packet accepted with routed delivery, approved-source or transcript signal, "
    "live browse evidence, auditor-passed chosen candidate, staged reversible artifact, mirrored Teable delivery, "
    "current-packet, pending-approval, stale-approval, and decision facts, and explicit approval outcome"
)
SIGNAL_REVIEW_PROOF_LABEL = "real weekly signal-to-decision review accepted by the operator"
SIGNAL_FOLLOWTHROUGH_PROOF_LABEL = "closed-loop signal-to-decision follow-through receipt accepted by the operator"
SCOPE_GAP_PROOF_LABEL = "real whole-project scope gap audit reviewed against the current product spine"


def _load(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _verify_source_state(receipt: dict[str, Any], issues: list[str]) -> None:
    if receipt.get("head_semantics") != "source_state":
        issues.append("office_loop_head_semantics_missing")
    if receipt.get("source_state_fingerprint_semantics") != "worktree_source_files_sha256_excluding_generated_only_paths":
        issues.append("office_loop_source_state_fingerprint_semantics_missing")
    recorded_head = str(receipt.get("source_git_head") or "").strip()
    recorded_fingerprint = str(receipt.get("source_state_fingerprint") or "").strip()
    current_head = resolve_source_state_head(REPO_ROOT)
    current_fingerprint = resolve_source_worktree_fingerprint(REPO_ROOT)
    if not recorded_head:
        issues.append("office_loop_source_git_head_missing")
    elif recorded_head != current_head and recorded_fingerprint != current_fingerprint:
        issues.append("office_loop_source_git_head_stale")
    if not recorded_fingerprint:
        issues.append("office_loop_source_state_fingerprint_missing")
    elif recorded_fingerprint != current_fingerprint:
        issues.append("office_loop_source_state_fingerprint_stale")


def _path_from_text(value: object) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text)
    return path if path.is_absolute() else REPO_ROOT / path


def _verify_surface(
    payload: dict[str, Any],
    issues: list[str],
    *,
    prefix: str,
) -> None:
    action = str(payload.get("next_action") or "").strip()
    href = str(payload.get("next_action_href") or "").strip()
    label = str(payload.get("next_action_label") or "").strip()
    method = str(payload.get("next_action_method") or "").strip().lower()
    if action == "reauthorize_google_workspace_binding":
        if "/app/actions/google/connect?" not in href:
            issues.append(f"{prefix} reauthorize_google_workspace_binding next_action_href must target the Google connect action")
        if label != "Reconnect Google workspace":
            issues.append(f"{prefix} reauthorize_google_workspace_binding next_action_label drifted")
        if method != "get":
            issues.append(f"{prefix} reauthorize_google_workspace_binding requires next_action_method=get")
    if action in {
        "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome",
        "record_proactive_ooda_approval_outcome",
    }:
        if not href.endswith("/admin/proactive-ooda/approval"):
            issues.append(f"{prefix} approval-capture next_action_href must target /admin/proactive-ooda/approval")
        if label != "Open approval capture":
            issues.append(f"{prefix} approval-capture next_action_label drifted")
        if method != "get":
            issues.append(f"{prefix} approval-capture next_action_method must be get")
    if action == "review_scope_gap_audit_against_current_product_spine_with_a_human_operator":
        if href != "/admin/goals":
            issues.append(f"{prefix} scope-gap-review next_action_href must target /admin/goals")
        if label != "Review scope gap audit":
            issues.append(f"{prefix} scope-gap-review next_action_label drifted")
        if method != "get":
            issues.append(f"{prefix} scope-gap-review next_action_method must be get")


def _next_action_surface(payload: dict[str, Any]) -> dict[str, str]:
    return {
        "next_action": str(payload.get("next_action") or "").strip(),
        "next_action_href": str(payload.get("next_action_href") or "").strip(),
        "next_action_label": str(payload.get("next_action_label") or "").strip(),
        "next_action_method": str(payload.get("next_action_method") or "").strip(),
    }


def _preferred_action_surface(*surfaces: dict[str, str]) -> dict[str, str]:
    selected: dict[str, str] = {}
    fallback_same_action: dict[str, str] = {}
    for surface in surfaces:
        action = str(surface.get("next_action") or "").strip()
        if not action:
            continue
        if not selected:
            selected = {
                "next_action": action,
                "next_action_href": str(surface.get("next_action_href") or "").strip(),
                "next_action_label": str(surface.get("next_action_label") or "").strip(),
                "next_action_method": str(surface.get("next_action_method") or "").strip(),
            }
            continue
        if action == selected["next_action"] and not fallback_same_action:
            fallback_same_action = {
                "next_action": action,
                "next_action_href": str(surface.get("next_action_href") or "").strip(),
                "next_action_label": str(surface.get("next_action_label") or "").strip(),
                "next_action_method": str(surface.get("next_action_method") or "").strip(),
            }
    if not selected:
        return {}
    if fallback_same_action:
        for key in ("next_action_href", "next_action_label", "next_action_method"):
            if not str(selected.get(key) or "").strip():
                selected[key] = str(fallback_same_action.get(key) or "").strip()
    return selected


def verify_office_loop_goal_receipt(receipt_path: str | Path) -> dict[str, Any]:
    receipt = _load(Path(receipt_path))
    issues: list[str] = []
    _verify_source_state(receipt, issues)
    if receipt.get("goal_completion_claim_allowed") is True:
        issues.append("office_loop_completion_overclaim")
    if receipt.get("live_daily_use_verified") is True:
        issues.append("office_loop_live_daily_use_overclaim")
    if dict(receipt.get("boundary_posture") or {}).get("ea_is_product_truth") is True:
        issues.append("office_loop_ea_product_truth_overclaim")
    for key, row in dict(receipt.get("components") or {}).items():
        if dict(row).get("status") != "pass":
            issues.append(f"office_loop_component_not_pass:{key}")
    for key, row in dict(receipt.get("route_snapshots") or {}).items():
        if dict(row).get("markers_pass") is not True:
            issues.append(f"office_loop_route_markers_not_pass:{key}")
    digests = set(dict(receipt.get("diagnostics_summary") or {}).get("channel_loop_digest_keys") or [])
    for key in ("approvals", "operator"):
        if key not in digests:
            issues.append(f"office_loop_channel_loop_digest_missing:{key}")
    if not str(dict(receipt.get("diagnostics_summary") or {}).get("proactive_followthrough_status") or "").strip():
        issues.append("office_loop_diagnostics_missing:proactive_followthrough_status")
    if str(dict(receipt.get("diagnostics_summary") or {}).get("provider_cost_routing_status") or "").strip() != "active_cost_control":
        issues.append("office_loop_diagnostics_missing:provider_cost_routing_status")
    goals = {dict(row).get("key"): row for row in receipt.get("additional_goals") or []}
    if "approved_action_workflow" not in dict(goals.get("executive_assistant_quality_readiness") or {}).get("protected_quality_dimensions", []):
        issues.append("office_loop_executive_assistant_quality_dimension_missing:approved_action_workflow")
    if "privacy_and_redaction" not in dict(goals.get("executive_assistant_acceptance_evidence") or {}).get("protected_acceptance_dimensions", []):
        issues.append("office_loop_executive_assistant_acceptance_dimension_missing:privacy_and_redaction")
    if "ready_tonight" not in dict(goals.get("whole_project_product_governor_loop") or {}).get("protected_pressures", []):
        issues.append("office_loop_product_governor_pressure_missing:ready_tonight")
    if "run_session" not in dict(goals.get("whole_project_scope_gap_audit") or {}).get("protected_scope_axes", []):
        issues.append("office_loop_scope_gap_audit_axis_missing:run_session")
    if "provider_runtime_failures" not in dict(goals.get("whole_project_signal_to_decision_closure") or {}).get("protected_signal_sources", []):
        issues.append("office_loop_signal_to_decision_source_missing:provider_runtime_failures")
    proactive_goal = dict(goals.get("proactive_ooda_gold_production") or {})
    proactive_requires = list(proactive_goal.get("requires", []))
    for key in (
        "live_browse_backed_candidate_research",
        "cost_aware_background_model_routing_to_1min_ai",
        "gemini_vertex_token_telemetry_and_soft_cap",
        "pocket_ai_audio_transcript_signal_ingest",
        "context_aware_auditor_before_user_delivery",
        "candidate_provider_fit_and_locality_validation",
        "reversible_candidate_staging",
        "gmail_draft_staging_when_requested",
        "action_required_only_telegram_delivery",
        "route_selection_and_blocked_fallback_honesty",
        "teable_projection_of_run_facts",
        "teable_projection_of_delivery_and_decision_facts",
        "teable_projection_of_pending_approval_surface",
        "current_packet_and_stale_approval_telemetry",
        "stale_approval_cleanup_or_expiry",
        "approval_outcome_capture_and_follow_through_receipts",
        "resume_without_repeat_research",
    ):
        if key not in proactive_requires:
            issues.append(f"office_loop_proactive_ooda_requirement_missing:{key}")
    proactive_sources = list(proactive_goal.get("protected_signal_sources", []))
    for key in (
        "calendar_and_renewal_signals",
        "preference_budget_and_quiet_hours_state",
        "durable_profile_and_location_context",
        "pocket_ai_audio_transcripts",
        "browser_and_vendor_page_evidence",
        "context_and_locality_constraints",
        "delivery_route_readiness",
        "route_blocker_and_recovery_state",
        "approval_and_follow_through_state",
        "gmail_draft_execution_state",
        "telegram_interruption_action_required_state",
        "current_packet_and_stale_approval_state",
        "provider_token_usage_and_cost_pressure_state",
    ):
        if key not in proactive_sources:
            issues.append(f"office_loop_proactive_ooda_source_missing:{key}")
    provider_cost_controls = dict(proactive_goal.get("provider_cost_controls") or {})
    if provider_cost_controls.get("background_work_primary_provider") != "onemin":
        issues.append("office_loop_provider_cost_control_background_provider_not_onemin")
    if provider_cost_controls.get("gemini_vertex_alias") != "gemini_vortex":
        issues.append("office_loop_provider_cost_control_gemini_alias_missing")
    if provider_cost_controls.get("gemini_token_tracking_required") is not True:
        issues.append("office_loop_provider_cost_control_gemini_token_tracking_not_required")
    if provider_cost_controls.get("gemini_soft_cap_required") is not True:
        issues.append("office_loop_provider_cost_control_gemini_soft_cap_not_required")
    if provider_cost_controls.get("explicit_gemini_requests_allowed") is not True:
        issues.append("office_loop_provider_cost_control_explicit_gemini_not_allowed")
    if (
        provider_cost_controls.get("billing_truth_boundary")
        != "token_ledger_is_cost_pressure_telemetry_not_google_cloud_billing_truth"
    ):
        issues.append("office_loop_provider_cost_control_billing_truth_boundary_missing")

    provider_cost_posture = dict(receipt.get("provider_cost_routing_posture") or {})
    if provider_cost_posture.get("status") != "active_cost_control":
        issues.append("office_loop_provider_cost_routing_posture_not_active")
    background_routing = dict(provider_cost_posture.get("background_routing") or {})
    if background_routing.get("primary_background_provider") != "onemin":
        issues.append("office_loop_provider_cost_background_primary_not_onemin")
    if list(background_routing.get("default_provider_order") or [])[:3] != ["onemin", "magixai", "gemini_vortex"]:
        issues.append("office_loop_provider_cost_default_order_drifted")
    if list(background_routing.get("groundwork_provider_order") or [])[:3] != ["onemin", "magixai", "gemini_vortex"]:
        issues.append("office_loop_provider_cost_groundwork_order_drifted")
    if background_routing.get("onemin_preferred_when_speed_is_not_critical") is not True:
        issues.append("office_loop_provider_cost_onemin_preference_missing")
    if "groundwork" not in list(background_routing.get("cost_sensitive_lanes") or []):
        issues.append("office_loop_provider_cost_groundwork_lane_missing")
    gemini_vertex = dict(provider_cost_posture.get("gemini_vertex") or {})
    if gemini_vertex.get("provider_key") != "gemini_vortex":
        issues.append("office_loop_provider_cost_gemini_provider_key_drifted")
    if gemini_vertex.get("token_tracking_required") is not True:
        issues.append("office_loop_provider_cost_gemini_token_tracking_missing")
    if gemini_vertex.get("dispatch_ledger") != "provider_dispatch_events.jsonl":
        issues.append("office_loop_provider_cost_dispatch_ledger_drifted")
    if gemini_vertex.get("live_pressure_probe_command") != "python3 scripts/ea_live_ops.py probe-provider-cost-pressure --window 24h --format json":
        issues.append("office_loop_provider_cost_live_pressure_probe_command_missing")
    if gemini_vertex.get("live_pressure_probe_source") != "runtime_container_exec:provider_ledger_cache":
        issues.append("office_loop_provider_cost_live_pressure_probe_source_missing")
    tracked_fields = set(str(item) for item in list(gemini_vertex.get("tracked_dispatch_fields") or []))
    for field in ("tokens_in", "tokens_out", "total_tokens", "lane", "model", "backend"):
        if field not in tracked_fields:
            issues.append(f"office_loop_provider_cost_tracked_field_missing:{field}")
    if gemini_vertex.get("soft_cap_env") != "EA_RESPONSES_GEMINI_VORTEX_TOKEN_SOFT_CAP_24H":
        issues.append("office_loop_provider_cost_gemini_soft_cap_env_drifted")
    if gemini_vertex.get("soft_cap_window_env") != "EA_RESPONSES_GEMINI_VORTEX_TOKEN_SOFT_CAP_WINDOW_SECONDS":
        issues.append("office_loop_provider_cost_gemini_soft_cap_window_env_drifted")
    if int(gemini_vertex.get("default_soft_cap_tokens_24h") or 0) <= 0:
        issues.append("office_loop_provider_cost_gemini_soft_cap_default_missing")
    if gemini_vertex.get("soft_cap_action") != "remove_gemini_vortex_from_cost_gated_background_candidate_lists":
        issues.append("office_loop_provider_cost_gemini_soft_cap_action_drifted")
    if gemini_vertex.get("explicit_gemini_requests_allowed") is not True:
        issues.append("office_loop_provider_cost_explicit_gemini_not_allowed")
    if gemini_vertex.get("billing_truth_boundary") != "token_ledger_is_cost_pressure_telemetry_not_google_cloud_billing_truth":
        issues.append("office_loop_provider_cost_billing_truth_boundary_missing")
    privacy = dict(provider_cost_posture.get("privacy") or {})
    for privacy_key in (
        "raw_provider_secret_exposed",
        "raw_prompt_or_response_text_exposed",
        "raw_google_cloud_billing_account_exposed",
    ):
        if privacy.get(privacy_key) is not False:
            issues.append(f"office_loop_provider_cost_privacy_leak:{privacy_key}")

    evidence_receipts = dict(receipt.get("evidence_receipts") or {})
    required_evidence_keys = {
        "executive_assistant_acceptance_evidence",
        "whole_project_signal_to_decision",
        "proactive_ooda_operator_status",
        "proactive_ooda_gold_acceptance",
        "whole_project_scope_gap_audit",
    }
    missing_evidence_keys = required_evidence_keys - set(evidence_receipts)
    for key in sorted(missing_evidence_keys):
        issues.append(f"office_loop_evidence_receipt_missing:{key}")

    acceptance_evidence = dict(evidence_receipts.get("executive_assistant_acceptance_evidence") or {})
    signal_evidence = dict(evidence_receipts.get("whole_project_signal_to_decision") or {})
    proactive_operator_evidence = dict(evidence_receipts.get("proactive_ooda_operator_status") or {})
    proactive_gold_evidence = dict(evidence_receipts.get("proactive_ooda_gold_acceptance") or {})
    scope_gap_evidence = dict(evidence_receipts.get("whole_project_scope_gap_audit") or {})
    proactive_posture = dict(receipt.get("proactive_ooda_followthrough_posture") or {})
    expected_followthrough_surface = _preferred_action_surface(
        _next_action_surface(proactive_gold_evidence),
        _next_action_surface(proactive_operator_evidence),
    )
    if not proactive_posture:
        issues.append("office_loop_followthrough_posture_missing")
    else:
        if str(proactive_posture.get("next_action") or "").strip() != str(receipt.get("next_action") or "").strip():
            issues.append("office_loop_next_action_drifted_from_followthrough_posture")
        for key in ("next_action_href", "next_action_label", "next_action_method"):
            if str(proactive_posture.get(key) or "").strip() != str(receipt.get(key) or "").strip():
                issues.append(f"office_loop_{key}_drifted_from_followthrough_posture")
        if expected_followthrough_surface:
            for key, issue in (
                ("next_action", "office_loop_followthrough_posture_missing_action_surface"),
                ("next_action_href", "office_loop_followthrough_posture_missing_action_href"),
                ("next_action_label", "office_loop_followthrough_posture_missing_action_label"),
                ("next_action_method", "office_loop_followthrough_posture_missing_action_method"),
            ):
                if str(proactive_posture.get(key) or "").strip() != str(expected_followthrough_surface.get(key) or "").strip():
                    issues.append(issue)
        _verify_surface(proactive_posture, issues, prefix="office_loop_followthrough_posture")

    for key, linked in (
        ("executive_assistant_acceptance_evidence", acceptance_evidence),
        ("whole_project_signal_to_decision", signal_evidence),
        ("proactive_ooda_operator_status", proactive_operator_evidence),
        ("proactive_ooda_gold_acceptance", proactive_gold_evidence),
        ("whole_project_scope_gap_audit", scope_gap_evidence),
    ):
        path = _path_from_text(linked.get("path"))
        if path is None:
            issues.append(f"office_loop_evidence_receipt_path_missing:{key}")
            continue
        if bool(linked.get("present")) and not path.is_file():
            issues.append(f"office_loop_linked_receipt_missing_on_disk:{key}")
            continue
        if not bool(linked.get("present")):
            continue
        payload = _load(path)
        if not payload:
            issues.append(f"office_loop_linked_receipt_invalid:{key}")
            continue
        if str(linked.get("contract_name") or "").strip() != str(payload.get("contract_name") or "").strip():
            issues.append(f"office_loop_linked_receipt_contract_drifted:{key}")
        if str(linked.get("status") or "").strip() != str(payload.get("status") or "").strip():
            issues.append(f"office_loop_linked_receipt_status_drifted:{key}")
        if key == "whole_project_signal_to_decision":
            if bool(linked.get("real_weekly_operator_review_accepted")) != bool(payload.get("real_weekly_operator_review_accepted")):
                issues.append("office_loop_linked_receipt_drifted:whole_project_signal_to_decision.review")
            if bool(linked.get("closed_loop_followthrough_receipt_verified")) != bool(
                payload.get("closed_loop_followthrough_receipt_verified")
            ):
                issues.append("office_loop_linked_receipt_drifted:whole_project_signal_to_decision.followthrough")
        if key == "proactive_ooda_operator_status":
            if str(linked.get("summary") or "").strip() != str(payload.get("summary") or "").strip():
                issues.append("office_loop_linked_receipt_drifted:proactive_ooda_operator_status.summary")
            if str(linked.get("next_action") or "").strip() != str(payload.get("next_action") or "").strip():
                issues.append("office_loop_linked_receipt_drifted:proactive_ooda_operator_status.next_action")
            _verify_surface(linked, issues, prefix="office_loop linked proactive_ooda_operator_status")
        if key == "proactive_ooda_gold_acceptance":
            approval = dict(dict(payload.get("proofs") or {}).get("approval_outcome") or {})
            approval_capture_surface = dict(dict(payload.get("evidence_receipts") or {}).get("approval_capture_surface") or {})
            if str(linked.get("summary") or "").strip() != str(payload.get("summary") or "").strip():
                issues.append("office_loop_linked_receipt_drifted:proactive_ooda_gold_acceptance.summary")
            if str(linked.get("next_action") or "").strip() != str(payload.get("next_action") or "").strip():
                issues.append("office_loop_linked_receipt_drifted:proactive_ooda_gold_acceptance.next_action")
            if bool(linked.get("approval_outcome_recorded")) != bool(approval.get("approval_outcome_recorded")):
                issues.append("office_loop_linked_receipt_drifted:proactive_ooda_gold_acceptance.approval_outcome_recorded")
            if bool(linked.get("approval_outcome_accepted")) != bool(approval.get("accepted")):
                issues.append("office_loop_linked_receipt_drifted:proactive_ooda_gold_acceptance.approval_outcome_accepted")
            if bool(linked.get("approval_capture_surface_ready")) != bool(approval_capture_surface.get("ready")):
                issues.append("office_loop_linked_receipt_drifted:proactive_ooda_gold_acceptance.approval_capture_surface_ready")
            _verify_surface(linked, issues, prefix="office_loop linked proactive_ooda_gold_acceptance")
        if key == "whole_project_scope_gap_audit":
            if str(linked.get("summary") or "").strip() != str(payload.get("summary") or "").strip():
                issues.append("office_loop_linked_receipt_drifted:whole_project_scope_gap_audit.summary")
            if str(linked.get("next_action") or "").strip() != str(payload.get("next_action") or "").strip():
                issues.append("office_loop_linked_receipt_drifted:whole_project_scope_gap_audit.next_action")
            if bool(linked.get("reviewed_against_current_product_spine")) != bool(
                payload.get("reviewed_against_current_product_spine")
            ):
                issues.append("office_loop_linked_receipt_drifted:whole_project_scope_gap_audit.reviewed")
            if bool(linked.get("operator_review_accepted")) != bool(payload.get("operator_review_accepted")):
                issues.append("office_loop_linked_receipt_drifted:whole_project_scope_gap_audit.operator_review")
            _verify_surface(linked, issues, prefix="office_loop linked whole_project_scope_gap_audit")

    if proactive_posture:
        if proactive_gold_evidence and bool(proactive_gold_evidence.get("present")):
            if str(proactive_posture.get("gold_acceptance_status") or "").strip() != str(proactive_gold_evidence.get("status") or "").strip():
                issues.append("office_loop_followthrough_posture_gold_status_drifted")
            if bool(proactive_posture.get("approval_outcome_recorded")) != bool(proactive_gold_evidence.get("approval_outcome_recorded")):
                issues.append("office_loop_followthrough_posture_approval_recorded_drifted")
            if bool(proactive_posture.get("approval_outcome_accepted")) != bool(proactive_gold_evidence.get("approval_outcome_accepted")):
                issues.append("office_loop_followthrough_posture_approval_accepted_drifted")
            if bool(proactive_posture.get("approval_capture_surface_ready")) != bool(
                proactive_gold_evidence.get("approval_capture_surface_ready")
            ):
                issues.append("office_loop_followthrough_posture_approval_capture_surface_ready_drifted")
        if proactive_operator_evidence and bool(proactive_operator_evidence.get("present")):
            if str(proactive_posture.get("operator_runtime_status") or "").strip() != str(proactive_operator_evidence.get("status") or "").strip():
                issues.append("office_loop_followthrough_posture_operator_status_drifted")
        if signal_evidence and bool(signal_evidence.get("present")):
            if bool(proactive_posture.get("real_weekly_operator_review_accepted")) != bool(
                signal_evidence.get("real_weekly_operator_review_accepted")
            ):
                issues.append("office_loop_followthrough_posture_signal_review_drifted")
            if bool(proactive_posture.get("closed_loop_followthrough_receipt_verified")) != bool(
                signal_evidence.get("closed_loop_followthrough_receipt_verified")
            ):
                issues.append("office_loop_followthrough_posture_signal_followthrough_drifted")

    remaining = {str(item).strip() for item in list(receipt.get("remaining_external_proofs") or []) if str(item).strip()}
    accepted_keys_count = int(acceptance_evidence.get("accepted_keys_count") or 0)
    expected_acceptance_proofs = set(REMAINING_PROOF_LABELS.values()) if accepted_keys_count == 0 else set()
    for proof in expected_acceptance_proofs:
        if proof not in remaining:
            issues.append(f"office_loop_remaining_external_proof_missing:{proof}")
    proactive_status = str(proactive_gold_evidence.get("status") or "").strip()
    if proactive_status == "pass" and PROACTIVE_OODA_PROOF_LABEL in remaining:
        issues.append("office_loop_remaining_external_proof_stale:proactive_ooda")
    if proactive_status != "pass" and PROACTIVE_OODA_PROOF_LABEL not in remaining:
        issues.append("office_loop_remaining_external_proof_missing:proactive_ooda")
    review_accepted = bool(signal_evidence.get("real_weekly_operator_review_accepted"))
    followthrough_accepted = bool(signal_evidence.get("closed_loop_followthrough_receipt_verified"))
    scope_review_accepted = bool(
        scope_gap_evidence.get("reviewed_against_current_product_spine")
        and scope_gap_evidence.get("operator_review_accepted")
    )
    if review_accepted and SIGNAL_REVIEW_PROOF_LABEL in remaining:
        issues.append("office_loop_remaining_external_proof_stale:signal_review")
    if not review_accepted and SIGNAL_REVIEW_PROOF_LABEL not in remaining:
        issues.append("office_loop_remaining_external_proof_missing:signal_review")
    if followthrough_accepted and SIGNAL_FOLLOWTHROUGH_PROOF_LABEL in remaining:
        issues.append("office_loop_remaining_external_proof_stale:signal_followthrough")
    if not followthrough_accepted and SIGNAL_FOLLOWTHROUGH_PROOF_LABEL not in remaining:
        issues.append("office_loop_remaining_external_proof_missing:signal_followthrough")
    if scope_review_accepted and SCOPE_GAP_PROOF_LABEL in remaining:
        issues.append("office_loop_remaining_external_proof_stale:scope_gap_review")
    if not scope_review_accepted and SCOPE_GAP_PROOF_LABEL not in remaining:
        issues.append("office_loop_remaining_external_proof_missing:scope_gap_review")
    return {"contract_name": "ea.office_loop_goal_receipt.verify.v1", "status": "pass" if not issues else "fail", "issues": issues}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the EA office-loop local evidence receipt.")
    parser.add_argument("--receipt", default=str(DEFAULT_RECEIPT))
    args = parser.parse_args(argv)
    result = verify_office_loop_goal_receipt(args.receipt)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
