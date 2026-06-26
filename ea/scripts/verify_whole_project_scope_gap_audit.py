from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from materialize_whole_project_scope_gap_audit import REQUIRED_SCOPE_AXES


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
DEFAULT_RECEIPT = REPO_ROOT / ".codex-studio" / "published" / "ea_whole_project_scope_gap_audit.generated.json"


def _load(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def verify_whole_project_scope_gap_audit(receipt_path: str | Path) -> dict[str, Any]:
    receipt = _load(receipt_path)
    issues: list[str] = []
    if receipt.get("goal_completion_claim_allowed") is True:
        issues.append("scope_gap_completion_overclaim")
    if dict(receipt.get("boundary_posture") or {}).get("ea_is_product_truth") is True:
        issues.append("scope_gap_ea_product_truth_overclaim")
    axes = {dict(row).get("key"): row for row in receipt.get("scope_axes") or []}
    for key in REQUIRED_SCOPE_AXES:
        if key not in axes:
            issues.append(f"scope_gap_axis_missing:{key}")
    protected = set(dict(receipt.get("project_learning_goal") or {}).get("protected_signal_sources") or [])
    if "provider_runtime_failures" not in protected:
        issues.append("scope_gap_signal_to_decision_source_missing:provider_runtime_failures")
    return {"contract_name": "ea.whole_project_scope_gap_audit.verify.v1", "status": "pass" if not issues else "fail", "issues": issues}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the whole-project scope gap audit.")
    parser.add_argument("--receipt", default=str(DEFAULT_RECEIPT))
    args = parser.parse_args(argv)
    result = verify_whole_project_scope_gap_audit(args.receipt)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
