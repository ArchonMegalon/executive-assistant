from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from materialize_executive_assistant_acceptance_evidence import ACCEPTANCE_CAPTURE_LABEL
from materialize_executive_assistant_acceptance_evidence import ACCEPTANCE_CAPTURE_METHOD
from materialize_executive_assistant_acceptance_evidence import ACCEPTANCE_CAPTURE_PATH
from materialize_executive_assistant_quality_readiness import REQUIRED_REAL_WORLD_PROOF
from materialize_executive_assistant_quality_readiness import LOCAL_REVIEW_LABEL
from materialize_executive_assistant_quality_readiness import LOCAL_REVIEW_PATH


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
DEFAULT_RECEIPT = REPO_ROOT / ".codex-studio" / "published" / "ea_executive_assistant_quality_readiness.generated.json"


def verify_executive_assistant_quality_readiness(receipt_path: str | Path) -> dict[str, Any]:
    receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    issues: list[str] = []
    next_action_href = str(receipt.get("next_action_href") or "").strip()
    next_action_label = str(receipt.get("next_action_label") or "").strip()
    next_action_method = str(receipt.get("next_action_method") or "").strip().lower()
    next_action_proof_key = str(receipt.get("next_action_proof_key") or "").strip()
    if receipt.get("goal_completion_claim_allowed") is True:
        issues.append("ea_quality_completion_overclaim")
    if receipt.get("ea_is_product_truth") is True:
        issues.append("ea_quality_product_truth_overclaim")
    if receipt.get("good_executive_assistant_claim_allowed") is True and receipt.get("blocked_checks"):
        issues.append("ea_quality_good_claim_flag_mismatch")
    privacy = dict(receipt.get("privacy") or {})
    for key, value in privacy.items():
        if value is not False:
            issues.append(f"ea_quality_privacy_flag_not_false:{key}")
    required = set(receipt.get("required_real_world_proof") or [])
    for proof in REQUIRED_REAL_WORLD_PROOF:
        if proof not in required:
            issues.append(f"ea_quality_required_proof_missing:{proof}")
    status = str(receipt.get("status") or "").strip()
    if status == "blocked_real_world_acceptance":
        if next_action_href != ACCEPTANCE_CAPTURE_PATH:
            issues.append("ea_quality_next_action_href_missing")
        if next_action_label != ACCEPTANCE_CAPTURE_LABEL:
            issues.append("ea_quality_next_action_label_missing")
        if next_action_method != ACCEPTANCE_CAPTURE_METHOD.lower():
            issues.append("ea_quality_next_action_method_missing")
        if not next_action_proof_key:
            issues.append("ea_quality_next_action_proof_key_missing")
    elif status == "blocked_local_quality_evidence":
        if next_action_href != LOCAL_REVIEW_PATH:
            issues.append("ea_quality_local_next_action_href_drift")
        if next_action_label != LOCAL_REVIEW_LABEL:
            issues.append("ea_quality_local_next_action_label_drift")
        if next_action_method != "get":
            issues.append("ea_quality_local_next_action_method_drift")
    else:
        if next_action_href or next_action_label or next_action_method or next_action_proof_key:
            issues.append("ea_quality_ready_next_action_should_be_empty")
    return {"contract_name": "ea.executive_assistant_quality_readiness.verify.v1", "status": "pass" if not issues else "fail", "issues": issues}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify EA quality readiness.")
    parser.add_argument("--receipt", default=str(DEFAULT_RECEIPT))
    args = parser.parse_args(argv)
    result = verify_executive_assistant_quality_readiness(args.receipt)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
