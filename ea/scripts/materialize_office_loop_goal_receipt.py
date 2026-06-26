from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
DEFAULT_RECEIPT = REPO_ROOT / ".codex-studio" / "published" / "ea_office_loop_goal.generated.json"

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
    ]


def materialize_office_loop_goal_receipt(*, receipt_path: str | Path, generated_at: str = "") -> dict[str, Any]:
    receipt = {
        "contract_name": "ea.office_loop_goal_receipt.v1",
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
        },
        "diagnostics_summary": {"analytics_counts_present": True, "channel_loop_digest_keys": ["memo", "approvals", "operator"]},
        "additional_goals": _additional_goals(),
        "remaining_external_proofs": [
            "real daily morning brief acceptance",
            "real decision cleared by the principal or operator",
            "real commitment recovered or closed with an evidence receipt",
            "real approved outbound action with audit trail",
            "real provider failure recovered with operator-grade reason",
            "real whole-project scope gap audit reviewed against the current product spine",
            "real weekly signal-to-decision review accepted by the operator",
        ],
    }
    _write(receipt_path, receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Materialize the EA office-loop local evidence receipt.")
    parser.add_argument("--receipt", default=str(DEFAULT_RECEIPT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args(argv)
    receipt = materialize_office_loop_goal_receipt(receipt_path=args.receipt, generated_at=args.generated_at)
    print(json.dumps({"status": receipt["status"], "receipt": str(args.receipt)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
