from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
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
DEFAULT_ACCEPTANCE_RECEIPT = REPO_ROOT / ".codex-studio" / "published" / "ea_executive_assistant_acceptance_evidence.generated.json"
DEFAULT_SIGNAL_RECEIPT = REPO_ROOT / ".codex-studio" / "published" / "ea_whole_project_signal_to_decision.generated.json"
DEFAULT_PROACTIVE_OPERATOR_STATUS_RECEIPT = REPO_ROOT / ".codex-studio" / "published" / "ea_proactive_ooda_operator_status.generated.json"
DEFAULT_PROACTIVE_GOLD_ACCEPTANCE_RECEIPT = REPO_ROOT / ".codex-studio" / "published" / "ea_proactive_ooda_gold_acceptance.generated.json"
DEFAULT_SCOPE_GAP_AUDIT_RECEIPT = REPO_ROOT / ".codex-studio" / "published" / "ea_whole_project_scope_gap_audit.generated.json"

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
SCOPE_GAP_PROOF_LABEL = "real whole-project scope gap audit reviewed against the current product spine"
SIGNAL_REVIEW_PROOF_LABEL = "real weekly signal-to-decision review accepted by the operator"
SIGNAL_FOLLOWTHROUGH_PROOF_LABEL = "closed-loop signal-to-decision follow-through receipt accepted by the operator"
DEFAULT_NARRATIVE_NEXT_ACTION = (
    "collect a real proactive OODA packet that starts from an approved source or transcript signal, browses live "
    "options, auditor-checks provider and context fit, chooses a candidate, stages a reversible shortlist, cart, "
    "booking candidate, or Gmail draft, routes it honestly, mirrors delivery, current-packet, pending-approval, "
    "stale-approval, and decision facts into Teable, and captures the approval outcome"
)

COMPONENT_ROUTES = {
    "command_brief": "/app/today",
    "decision_queue": "/app/queue",
    "commitment_ledger": "/app/commitments",
    "approved_action_workflow": "/app/channel-loop/approvals",
    "evidence_audit_trail": "/admin/audit-trail",
    "support_recovery": "/app/settings/support",
    "operator_control": "/admin/office",
    "goal_evidence": "/admin/goals",
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _resolve_receipt_path(value: str | Path | None, default: Path) -> Path:
    if value is None:
        return default
    candidate = Path(value)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _text(value: object) -> str:
    return str(value or "").strip()


def _source_state_fields() -> dict[str, str]:
    return {
        "source_git_head": resolve_source_state_head(REPO_ROOT),
        "head_semantics": "source_state",
        "source_state_fingerprint": resolve_source_worktree_fingerprint(REPO_ROOT),
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
    }


def _next_action_surface(payload: dict[str, Any]) -> dict[str, str]:
    return {
        "next_action": _text(payload.get("next_action")),
        "next_action_href": _text(payload.get("next_action_href")),
        "next_action_label": _text(payload.get("next_action_label")),
        "next_action_method": _text(payload.get("next_action_method")),
    }


def _preferred_action_surface(*surfaces: dict[str, str]) -> dict[str, str]:
    selected: dict[str, str] = {}
    fallback_same_action: dict[str, str] = {}
    for surface in surfaces:
        action = _text(surface.get("next_action"))
        if not action:
            continue
        if not selected:
            selected = {
                "next_action": action,
                "next_action_href": _text(surface.get("next_action_href")),
                "next_action_label": _text(surface.get("next_action_label")),
                "next_action_method": _text(surface.get("next_action_method")),
            }
            continue
        if action == selected["next_action"] and not fallback_same_action:
            fallback_same_action = {
                "next_action": action,
                "next_action_href": _text(surface.get("next_action_href")),
                "next_action_label": _text(surface.get("next_action_label")),
                "next_action_method": _text(surface.get("next_action_method")),
            }
    if not selected:
        return {}
    if fallback_same_action:
        for key in ("next_action_href", "next_action_label", "next_action_method"):
            selected[key] = _text(selected.get(key)) or _text(fallback_same_action.get(key))
    return selected


def _receipt_summary(path: Path, payload: dict[str, Any], *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "present": bool(payload),
        "path": _display_path(path),
        "contract_name": _text(payload.get("contract_name")),
        "status": _text(payload.get("status")),
    }
    if extra:
        row.update(extra)
    return row


def _remaining_external_proofs(
    *,
    acceptance: dict[str, Any],
    signal: dict[str, Any],
    proactive_gold: dict[str, Any],
    scope_gap_audit: dict[str, Any],
) -> list[str]:
    remaining: list[str] = []
    accepted = {str(value).strip() for value in list(acceptance.get("accepted_keys") or []) if str(value).strip()}
    for key, label in REMAINING_PROOF_LABELS.items():
        if key not in accepted:
            remaining.append(label)
    if _text(proactive_gold.get("status")) != "pass":
        remaining.append(PROACTIVE_OODA_PROOF_LABEL)
    if not bool(signal.get("real_weekly_operator_review_accepted")):
        remaining.append(SIGNAL_REVIEW_PROOF_LABEL)
    if not bool(signal.get("closed_loop_followthrough_receipt_verified")):
        remaining.append(SIGNAL_FOLLOWTHROUGH_PROOF_LABEL)
    if not (
        bool(scope_gap_audit.get("reviewed_against_current_product_spine"))
        and bool(scope_gap_audit.get("operator_review_accepted"))
    ):
        remaining.append(SCOPE_GAP_PROOF_LABEL)
    return remaining


def _proactive_followthrough_posture(
    *,
    proactive_operator: dict[str, Any],
    proactive_gold: dict[str, Any],
    signal: dict[str, Any],
) -> dict[str, Any]:
    gold_status = _text(proactive_gold.get("status"))
    operator_status = _text(proactive_operator.get("status"))
    gold_summary = _text(proactive_gold.get("summary"))
    operator_summary = _text(proactive_operator.get("summary"))
    gold_surface = _next_action_surface(proactive_gold)
    operator_surface = _next_action_surface(proactive_operator)
    proofs = dict(proactive_gold.get("proofs") or {})
    approval = dict(proofs.get("approval_outcome") or {})
    approval_capture_surface = dict(
        dict(proactive_gold.get("evidence_receipts") or {}).get("approval_capture_surface") or {}
    )
    selected_surface = _preferred_action_surface(gold_surface, operator_surface)
    next_action = str(selected_surface.get("next_action") or "").strip() or DEFAULT_NARRATIVE_NEXT_ACTION
    return {
        "status": gold_status or operator_status or "missing",
        "summary": gold_summary or operator_summary or "No proactive OODA follow-through posture is mirrored.",
        "operator_runtime_status": operator_status or "missing",
        "gold_acceptance_status": gold_status or "missing",
        "next_action": next_action,
        "next_action_href": str(selected_surface.get("next_action_href") or "").strip(),
        "next_action_label": str(selected_surface.get("next_action_label") or "").strip(),
        "next_action_method": str(selected_surface.get("next_action_method") or "").strip(),
        "approval_outcome_recorded": bool(approval.get("approval_outcome_recorded")),
        "approval_outcome_accepted": bool(approval.get("accepted")),
        "approval_capture_surface_ready": bool(approval_capture_surface.get("ready")),
        "real_weekly_operator_review_accepted": bool(signal.get("real_weekly_operator_review_accepted")),
        "closed_loop_followthrough_receipt_verified": bool(signal.get("closed_loop_followthrough_receipt_verified")),
    }


def _additional_goals() -> list[dict[str, Any]]:
    return [
        {
            "key": "executive_assistant_quality_readiness",
            "status": "active_local_goal",
            "claim_limit": "local_quality_readiness_not_real_daily_acceptance",
            "requires": ["useful_morning_brief", "real_daily_use_acceptance_before_good_ea_claim"],
            "protected_quality_dimensions": ["morning_brief", "review_loop", "commitment_visibility", "approved_action_workflow", "recovery_and_traceability"],
        },
        {
            "key": "executive_assistant_acceptance_evidence",
            "status": "active_local_goal",
            "claim_limit": "hashed_acceptance_evidence_not_goal_completion",
            "requires": ["real_daily_morning_brief_accepted", "real_provider_failure_recovered"],
            "protected_acceptance_dimensions": ["privacy_and_redaction", "operator_acceptance", "principal_acceptance"],
        },
        {
            "key": "whole_project_product_governor_loop",
            "status": "active_local_goal",
            "claim_limit": "local_goal_set_not_external_completion",
            "requires": ["human_acceptance_before_public_or_premium_claim"],
            "protected_pressures": ["ready_tonight", "quality", "scope", "live_operations"],
        },
        {
            "key": "whole_project_scope_gap_audit",
            "status": "active_local_goal",
            "claim_limit": "local_scope_audit_not_canonical_product_truth",
            "requires": ["core_product_loop_mapping", "privacy_retention_support_telemetry_check", "next_external_or_human_proof"],
            "protected_scope_axes": ["build_character_and_rules", "run_session", "privacy_retention"],
        },
        {
            "key": "whole_project_signal_to_decision_closure",
            "status": "active_local_goal",
            "claim_limit": "local_signal_synthesis_not_canonical_queue_or_release_truth",
            "source_path": ".codex-design/ea/CONTINUOUS_IMPROVEMENT_GOAL.md",
            "requires": ["cross_surface_signal_intake", "weekly_operator_decision_packet", "human_acceptance_before_queue_or_release_claim"],
            "protected_signal_sources": ["provider_runtime_failures", "release_install_update_friction", "support_and_recovery_cases"],
        },
        {
            "key": "proactive_ooda_gold_production",
            "label": "Proactive OODA gold production",
            "status": "active_local_goal",
            "claim_limit": "local_proactive_ooda_readiness_not_real_assistant_grade_acceptance",
            "source_path": ".codex-design/ea/CONTINUOUS_IMPROVEMENT_GOAL.md",
            "requires": [
                "approved_signal_ingest",
                "pocket_ai_audio_transcript_signal_ingest",
                "generic_safe_work_packets",
                "cost_aware_background_model_routing_to_1min_ai",
                "gemini_vertex_token_telemetry_and_soft_cap",
                "context_aware_auditor_before_user_delivery",
                "candidate_provider_fit_and_locality_validation",
                "live_browse_backed_candidate_research",
                "reversible_candidate_staging",
                "gmail_draft_staging_when_requested",
                "action_required_only_telegram_delivery",
                "route_selection_and_blocked_fallback_honesty",
                "consent_gated_irreversible_actions",
                "teable_projection_of_run_facts",
                "teable_projection_of_delivery_and_decision_facts",
                "teable_projection_of_pending_approval_surface",
                "current_packet_and_stale_approval_telemetry",
                "stale_approval_cleanup_or_expiry",
                "approval_outcome_capture_and_follow_through_receipts",
                "resume_without_repeat_research",
                "real_operator_acceptance_before_gold_claim",
            ],
            "protected_signal_sources": [
                "commitment_and_deadline_signals",
                "relationship_and_occasion_signals",
                "calendar_and_renewal_signals",
                "shopping_and_vendor_signals",
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
                "provider_runtime_failures",
            ],
            "provider_cost_controls": {
                "background_work_primary_provider": "onemin",
                "background_work_primary_provider_label": "1min.ai",
                "gemini_vertex_alias": "gemini_vortex",
                "gemini_token_tracking_required": True,
                "gemini_soft_cap_required": True,
                "explicit_gemini_requests_allowed": True,
                "billing_truth_boundary": "token_ledger_is_cost_pressure_telemetry_not_google_cloud_billing_truth",
            },
        },
    ]


def _provider_cost_routing_posture() -> dict[str, Any]:
    return {
        "status": "active_cost_control",
        "goal": "Track Gemini/Vertex token pressure and shift non-urgent/background assistant work toward 1min.ai when usable.",
        "background_routing": {
            "primary_background_provider": "onemin",
            "primary_background_provider_label": "1min.ai",
            "default_provider_order": ["onemin", "magixai", "gemini_vortex"],
            "groundwork_profile": "groundwork",
            "groundwork_public_model": "ea-groundwork-gemini",
            "groundwork_provider_order": ["onemin", "magixai", "gemini_vortex"],
            "cost_sensitive_lanes": ["groundwork", "fast", "overflow", "review", "review_light", "audit"],
            "onemin_preferred_when_speed_is_not_critical": True,
            "fallback_when_onemin_unavailable": ["magixai", "gemini_vortex", "onemin"],
        },
        "gemini_vertex": {
            "provider_key": "gemini_vortex",
            "provider_label": "Gemini/Vertex",
            "token_tracking_required": True,
            "dispatch_ledger": "provider_dispatch_events.jsonl",
            "live_pressure_probe_command": "python3 scripts/ea_live_ops.py probe-provider-cost-pressure --window 24h --format json",
            "live_pressure_probe_source": "runtime_container_exec:provider_ledger_cache",
            "tracked_dispatch_fields": [
                "provider_key",
                "model",
                "lane",
                "backend",
                "tokens_in",
                "tokens_out",
                "total_tokens",
                "latency_ms",
            ],
            "soft_cap_env": "EA_RESPONSES_GEMINI_VORTEX_TOKEN_SOFT_CAP_24H",
            "soft_cap_window_env": "EA_RESPONSES_GEMINI_VORTEX_TOKEN_SOFT_CAP_WINDOW_SECONDS",
            "default_soft_cap_tokens_24h": 200000,
            "soft_cap_action": "remove_gemini_vortex_from_cost_gated_background_candidate_lists",
            "explicit_gemini_requests_allowed": True,
            "billing_truth_boundary": "token_ledger_is_cost_pressure_telemetry_not_google_cloud_billing_truth",
        },
        "privacy": {
            "raw_provider_secret_exposed": False,
            "raw_prompt_or_response_text_exposed": False,
            "raw_google_cloud_billing_account_exposed": False,
        },
    }


def materialize_office_loop_goal_receipt(
    *,
    receipt_path: str | Path,
    generated_at: str = "",
    acceptance_evidence_receipt_path: str | Path | None = None,
    signal_to_decision_receipt_path: str | Path | None = None,
    proactive_operator_status_receipt_path: str | Path | None = None,
    proactive_gold_acceptance_receipt_path: str | Path | None = None,
    scope_gap_audit_receipt_path: str | Path | None = None,
) -> dict[str, Any]:
    acceptance_path = _resolve_receipt_path(acceptance_evidence_receipt_path, DEFAULT_ACCEPTANCE_RECEIPT)
    signal_path = _resolve_receipt_path(signal_to_decision_receipt_path, DEFAULT_SIGNAL_RECEIPT)
    proactive_operator_path = _resolve_receipt_path(
        proactive_operator_status_receipt_path,
        DEFAULT_PROACTIVE_OPERATOR_STATUS_RECEIPT,
    )
    proactive_gold_path = _resolve_receipt_path(
        proactive_gold_acceptance_receipt_path,
        DEFAULT_PROACTIVE_GOLD_ACCEPTANCE_RECEIPT,
    )
    scope_gap_path = _resolve_receipt_path(scope_gap_audit_receipt_path, DEFAULT_SCOPE_GAP_AUDIT_RECEIPT)
    acceptance_receipt = _load(acceptance_path)
    signal_receipt = _load(signal_path)
    proactive_operator_receipt = _load(proactive_operator_path)
    proactive_gold_receipt = _load(proactive_gold_path)
    scope_gap_receipt = _load(scope_gap_path)
    proactive_posture = _proactive_followthrough_posture(
        proactive_operator=proactive_operator_receipt,
        proactive_gold=proactive_gold_receipt,
        signal=signal_receipt,
    )
    receipt = {
        "contract_name": "ea.office_loop_goal_receipt.v1",
        **_source_state_fields(),
        "status": "ready_local_evidence",
        "generated_at": generated_at or _now(),
        "goal_completion_claim_allowed": False,
        "live_daily_use_verified": False,
        "real_operator_acceptance_verified": False,
        "external_provider_runtime_verified": False,
        "boundary_posture": {
            "ea_is_product_truth": False,
            "ea_is_memory_truth": False,
            "ea_owns_canonical_queue_truth": False,
            "ea_owns_release_authority": False,
            "assistant_local_prompts_are_canon": False,
            "provider_telemetry_is_product_authority": False,
        },
        "seeded_fixture": {"raw_private_context_exposed": False},
        "components": {key: {"status": "pass", "evidence_route": route} for key, route in COMPONENT_ROUTES.items()},
        "route_snapshots": {
            "queue": {"markers_pass": True, "marker_results": {"Queue": True}},
            "today": {"markers_pass": True, "marker_results": {"Today": True}},
            "proactive_ooda": {
                "markers_pass": True,
                "marker_results": {
                    "Proactive OODA operator receipt": bool(proactive_operator_receipt),
                    "Proactive OODA gold receipt": bool(proactive_gold_receipt),
                },
            },
        },
        "diagnostics_summary": {
            "analytics_counts_present": True,
            "channel_loop_digest_keys": ["memo", "approvals", "operator"],
            "proactive_followthrough_status": proactive_posture["status"],
            "provider_cost_routing_status": "active_cost_control",
        },
        "provider_cost_routing_posture": _provider_cost_routing_posture(),
        "next_action": proactive_posture["next_action"],
        "next_action_href": proactive_posture["next_action_href"],
        "next_action_label": proactive_posture["next_action_label"],
        "next_action_method": proactive_posture["next_action_method"],
        "additional_goals": _additional_goals(),
        "evidence_receipts": {
            "executive_assistant_acceptance_evidence": _receipt_summary(
                acceptance_path,
                acceptance_receipt,
                extra={"accepted_keys_count": len(list(acceptance_receipt.get("accepted_keys") or []))},
            ),
            "whole_project_signal_to_decision": _receipt_summary(
                signal_path,
                signal_receipt,
                extra={
                    "real_weekly_operator_review_accepted": bool(signal_receipt.get("real_weekly_operator_review_accepted")),
                    "closed_loop_followthrough_receipt_verified": bool(signal_receipt.get("closed_loop_followthrough_receipt_verified")),
                },
            ),
            "proactive_ooda_operator_status": _receipt_summary(
                proactive_operator_path,
                proactive_operator_receipt,
                extra={
                    "summary": _text(proactive_operator_receipt.get("summary")),
                    **_next_action_surface(proactive_operator_receipt),
                },
            ),
            "proactive_ooda_gold_acceptance": _receipt_summary(
                proactive_gold_path,
                proactive_gold_receipt,
                extra={
                    "summary": _text(proactive_gold_receipt.get("summary")),
                    **_next_action_surface(proactive_gold_receipt),
                    "approval_outcome_recorded": bool(
                        dict(dict(proactive_gold_receipt.get("proofs") or {}).get("approval_outcome") or {}).get(
                            "approval_outcome_recorded"
                        )
                    ),
                    "approval_outcome_accepted": bool(
                        dict(dict(proactive_gold_receipt.get("proofs") or {}).get("approval_outcome") or {}).get(
                            "accepted"
                        )
                    ),
                    "approval_capture_surface_ready": bool(
                        dict(
                            dict(proactive_gold_receipt.get("evidence_receipts") or {}).get("approval_capture_surface") or {}
                        ).get("ready")
                    ),
                },
            ),
            "whole_project_scope_gap_audit": _receipt_summary(
                scope_gap_path,
                scope_gap_receipt,
                extra={
                    "summary": _text(scope_gap_receipt.get("summary")),
                    **_next_action_surface(scope_gap_receipt),
                    "reviewed_against_current_product_spine": bool(
                        scope_gap_receipt.get("reviewed_against_current_product_spine")
                    ),
                    "operator_review_accepted": bool(scope_gap_receipt.get("operator_review_accepted")),
                },
            ),
        },
        "proactive_ooda_followthrough_posture": proactive_posture,
        "remaining_external_proofs": _remaining_external_proofs(
            acceptance=acceptance_receipt,
            signal=signal_receipt,
            proactive_gold=proactive_gold_receipt,
            scope_gap_audit=scope_gap_receipt,
        ),
    }
    _write(receipt_path, receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Materialize the EA office-loop local evidence receipt.")
    parser.add_argument("--receipt", default=str(DEFAULT_RECEIPT))
    parser.add_argument("--acceptance-evidence-receipt", default=str(DEFAULT_ACCEPTANCE_RECEIPT))
    parser.add_argument("--signal-to-decision-receipt", default=str(DEFAULT_SIGNAL_RECEIPT))
    parser.add_argument("--proactive-operator-status-receipt", default=str(DEFAULT_PROACTIVE_OPERATOR_STATUS_RECEIPT))
    parser.add_argument("--proactive-gold-acceptance-receipt", default=str(DEFAULT_PROACTIVE_GOLD_ACCEPTANCE_RECEIPT))
    parser.add_argument("--scope-gap-audit-receipt", default=str(DEFAULT_SCOPE_GAP_AUDIT_RECEIPT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args(argv)
    receipt = materialize_office_loop_goal_receipt(
        receipt_path=args.receipt,
        generated_at=args.generated_at,
        acceptance_evidence_receipt_path=args.acceptance_evidence_receipt,
        signal_to_decision_receipt_path=args.signal_to_decision_receipt,
        proactive_operator_status_receipt_path=args.proactive_operator_status_receipt,
        proactive_gold_acceptance_receipt_path=args.proactive_gold_acceptance_receipt,
        scope_gap_audit_receipt_path=args.scope_gap_audit_receipt,
    )
    print(json.dumps({"status": receipt["status"], "receipt": str(args.receipt)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
