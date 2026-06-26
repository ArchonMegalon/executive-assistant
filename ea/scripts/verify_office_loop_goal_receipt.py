from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
DEFAULT_RECEIPT = REPO_ROOT / ".codex-studio" / "published" / "ea_office_loop_goal.generated.json"


def verify_office_loop_goal_receipt(receipt_path: str | Path) -> dict[str, Any]:
    receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    issues: list[str] = []
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
