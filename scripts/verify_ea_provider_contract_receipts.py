#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "_completion" / "ea_provider_contracts"
SUMMARY_NAME = "EA_PROVIDER_CONTRACTS_SUMMARY.generated.json"
CONTRACT_STATUS = "contract_pass_live_provider_pending"
PROOF_SCOPE = "local_contract_exercise"


EXPECTED_RECEIPTS = {
    "HEDY_MEETING_EVIDENCE_CONTRACT.generated.json": "ea.provider_contract.hedy_meeting_evidence",
    "PREMIUM_DELIVERY_CONTRACT.generated.json": "ea.provider_contract.premium_delivery",
    "APPROVETHIS_EXTERNAL_APPROVAL_CONTRACT.generated.json": "ea.provider_contract.approvethis_external_approval",
    "DOCUMENTATION_AI_PUBLICATION_CONTRACT.generated.json": "ea.provider_contract.documentation_ai_publication",
    "EA_QUALITY_GATES_CONTRACT.generated.json": "ea.provider_contract.ea_quality_gates",
}


def _load_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def verify_contract_receipts(output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, object]:
    issues: list[str] = []
    summary_path = output_dir / SUMMARY_NAME
    summary = _load_json(summary_path)
    if not summary:
        issues.append(f"missing_summary:{summary_path}")
    else:
        if summary.get("contract_name") != "ea.provider_contract_receipts":
            issues.append("summary_contract_name_invalid")
        if summary.get("status") != CONTRACT_STATUS:
            issues.append("summary_status_must_remain_contract_pending")
        if summary.get("proof_scope") != PROOF_SCOPE:
            issues.append("summary_proof_scope_invalid")
        if summary.get("live_provider_runtime_verified") is not False:
            issues.append("summary_live_provider_runtime_overclaim")
        if summary.get("gold_claim_allowed") is not False:
            issues.append("summary_gold_claim_overclaim")
        if summary.get("not_live_provider_proof") is not True:
            issues.append("summary_not_live_provider_marker_missing")
        if summary.get("not_release_gold_proof") is not True:
            issues.append("summary_not_release_gold_marker_missing")
        if not summary.get("required_next_receipts"):
            issues.append("summary_required_next_receipts_missing")

    for filename, contract_name in EXPECTED_RECEIPTS.items():
        path = output_dir / filename
        receipt = _load_json(path)
        if not receipt:
            issues.append(f"missing_receipt:{filename}")
            continue
        if receipt.get("contract_name") != contract_name:
            issues.append(f"receipt_contract_name_invalid:{filename}")
        if receipt.get("status") != CONTRACT_STATUS:
            issues.append(f"receipt_status_must_remain_contract_pending:{filename}")
        if receipt.get("proof_scope") != PROOF_SCOPE:
            issues.append(f"receipt_proof_scope_invalid:{filename}")
        if receipt.get("live_provider_runtime_verified") is not False:
            issues.append(f"receipt_live_provider_runtime_overclaim:{filename}")
        if receipt.get("gold_claim_allowed") is not False:
            issues.append(f"receipt_gold_claim_overclaim:{filename}")
        if not receipt.get("required_next_receipts"):
            issues.append(f"receipt_required_next_receipts_missing:{filename}")
        verification = receipt.get("verification")
        if not isinstance(verification, dict) or verification.get("contract_exercised") is not True:
            issues.append(f"receipt_contract_not_exercised:{filename}")
        if filename == "HEDY_MEETING_EVIDENCE_CONTRACT.generated.json":
            if not isinstance(verification, dict) or verification.get("webhook_to_review_queue_contract") != "pass":
                issues.append("hedy_webhook_to_review_queue_contract_missing")
            if not isinstance(verification, dict) or verification.get("idempotent_review_task_contract") != "pass":
                issues.append("hedy_idempotent_review_task_contract_missing")
            review_intake = receipt.get("sample_review_intake")
            if not isinstance(review_intake, dict) or review_intake.get("created_review_task") is not True:
                issues.append("hedy_sample_review_task_missing")
            review_retry = receipt.get("sample_review_retry")
            if not isinstance(review_retry, dict) or review_retry.get("duplicate") is not True:
                issues.append("hedy_sample_review_retry_missing")

    return {
        "contract_name": "ea.verify_provider_contract_receipts",
        "status": "pass" if not issues else "fail",
        "output_dir": str(output_dir),
        "issues": issues,
        "checked_receipts": [SUMMARY_NAME, *EXPECTED_RECEIPTS.keys()],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify EA provider contract receipts do not overclaim live runtime proof.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()
    result = verify_contract_receipts(Path(args.output_dir))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
