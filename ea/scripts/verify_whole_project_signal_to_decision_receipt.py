from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from materialize_whole_project_signal_to_decision_receipt import REQUIRED_SIGNAL_SOURCES


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
DEFAULT_RECEIPT = REPO_ROOT / ".codex-studio" / "published" / "ea_whole_project_signal_to_decision.generated.json"


def _load(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def verify_whole_project_signal_to_decision_receipt(receipt_path: str | Path) -> dict[str, Any]:
    receipt = _load(receipt_path)
    issues: list[str] = []
    if receipt.get("goal_completion_claim_allowed") is True:
        issues.append("signal_decision_completion_overclaim")
    if receipt.get("queue_truth_claim_allowed") is True:
        issues.append("signal_decision_queue_truth_overclaim")
    if dict(receipt.get("boundary_posture") or {}).get("ea_is_product_truth") is True:
        issues.append("signal_decision_ea_product_truth_overclaim")
    rows = {dict(row).get("key"): row for row in receipt.get("signal_sources") or []}
    for key in REQUIRED_SIGNAL_SOURCES:
        if key not in rows:
            issues.append(f"signal_decision_source_row_missing:{key}")
    return {"contract_name": "ea.whole_project_signal_to_decision_receipt.verify.v1", "status": "pass" if not issues else "fail", "issues": issues}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the whole-project signal-to-decision receipt.")
    parser.add_argument("--receipt", default=str(DEFAULT_RECEIPT))
    args = parser.parse_args(argv)
    result = verify_whole_project_signal_to_decision_receipt(args.receipt)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
