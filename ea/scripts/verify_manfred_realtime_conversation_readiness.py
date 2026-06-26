from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from materialize_manfred_realtime_conversation_readiness import REQUIRED_LIVE_PROOF_AFTER_READINESS


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
DEFAULT_RECEIPT = REPO_ROOT / ".codex-studio" / "published" / "manfred_realtime_conversation_readiness.generated.json"


def verify_manfred_realtime_conversation_readiness(receipt_path: str | Path) -> dict[str, Any]:
    receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    issues: list[str] = []
    if receipt.get("goal_completion_claim_allowed") is True:
        issues.append("manfred_realtime_goal_completion_overclaim")
    if receipt.get("realtime_conversation_claim_allowed") is True and receipt.get("blocked_checks"):
        issues.append("manfred_realtime_claim_overclaim")
    if dict(receipt.get("captured_candidate_diagnostic") or {}).get("promotion_allowed") is True and receipt.get("blocked_checks"):
        issues.append("manfred_realtime_captured_diagnostic_overclaim")
    for key, value in dict(receipt.get("privacy") or {}).items():
        if key != "redacted_text_fields" and value is not False:
            issues.append(f"manfred_realtime_privacy_flag_not_false:{key}")
    proofs = set(receipt.get("required_live_proof_after_readiness") or [])
    if not set(REQUIRED_LIVE_PROOF_AFTER_READINESS) <= proofs:
        issues.append("manfred_realtime_required_live_proof_incomplete")
    return {"contract_name": "ea.manfred_realtime_conversation_readiness.verify.v1", "status": "pass" if not issues else "fail", "issues": issues}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify Manfred realtime conversation readiness.")
    parser.add_argument("--receipt", default=str(DEFAULT_RECEIPT))
    args = parser.parse_args(argv)
    result = verify_manfred_realtime_conversation_readiness(args.receipt)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
