from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from materialize_executive_assistant_acceptance_evidence import REQUIRED_ACCEPTANCE_KEYS


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
DEFAULT_RECEIPT = REPO_ROOT / ".codex-studio" / "published" / "ea_executive_assistant_acceptance_evidence.generated.json"


def verify_executive_assistant_acceptance_evidence(receipt_path: str | Path) -> dict[str, Any]:
    receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    issues: list[str] = []
    if receipt.get("goal_completion_claim_allowed") is True:
        issues.append("ea_acceptance_completion_overclaim")
    privacy = dict(receipt.get("privacy") or {})
    for key in ("raw_acceptance_text_exposed", "raw_actor_identity_exposed", "raw_object_reference_exposed", "raw_private_context_exposed"):
        if privacy.get(key) is not False:
            issues.append(f"ea_acceptance_privacy_flag_not_false:{key}")
    rows = dict(receipt.get("acceptance_keys") or {})
    for key in REQUIRED_ACCEPTANCE_KEYS:
        if key not in rows:
            issues.append(f"ea_acceptance_key_missing:{key}")
    for key, row in rows.items():
        if dict(row).get("accepted") is True and not dict(row).get("evidence_sha256"):
            issues.append(f"ea_acceptance_hash_missing:{key}")
        for raw_key in ("raw_evidence_exposed", "raw_actor_exposed", "raw_object_ref_exposed"):
            if dict(row).get(raw_key) is not False:
                issues.append(f"ea_acceptance_raw_field_flag_not_false:{key}:{raw_key}")
    return {"contract_name": "ea.executive_assistant_acceptance_evidence.verify.v1", "status": "pass" if not issues else "fail", "issues": issues}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify redacted Executive Assistant acceptance evidence.")
    parser.add_argument("--receipt", default=str(DEFAULT_RECEIPT))
    args = parser.parse_args(argv)
    result = verify_executive_assistant_acceptance_evidence(args.receipt)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
