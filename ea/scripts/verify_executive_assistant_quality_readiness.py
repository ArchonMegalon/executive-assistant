from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from materialize_executive_assistant_quality_readiness import REQUIRED_REAL_WORLD_PROOF


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
DEFAULT_RECEIPT = REPO_ROOT / ".codex-studio" / "published" / "ea_executive_assistant_quality_readiness.generated.json"


def verify_executive_assistant_quality_readiness(receipt_path: str | Path) -> dict[str, Any]:
    receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    issues: list[str] = []
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
