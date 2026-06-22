from __future__ import annotations

import json
from pathlib import Path


SUMMARY_NAME = "EA_PROVIDER_CONTRACTS_SUMMARY.generated.json"
EXPECTED_RECEIPTS: tuple[tuple[str, str, str], ...] = (
    (
        "hedy_meeting_evidence",
        "HEDY_MEETING_EVIDENCE_CONTRACT.generated.json",
        "Hedy meeting evidence",
    ),
    (
        "premium_delivery",
        "PREMIUM_DELIVERY_CONTRACT.generated.json",
        "Premium delivery",
    ),
    (
        "approvethis_external_approval",
        "APPROVETHIS_EXTERNAL_APPROVAL_CONTRACT.generated.json",
        "ApproveThis external approval",
    ),
    (
        "documentation_ai_publication",
        "DOCUMENTATION_AI_PUBLICATION_CONTRACT.generated.json",
        "Documentation.AI publication",
    ),
    (
        "ea_quality_gates",
        "EA_QUALITY_GATES_CONTRACT.generated.json",
        "EA quality gates",
    ),
)


def _repo_root() -> Path:
    resolved = Path(__file__).resolve()
    return resolved.parents[3]


def _receipt_dir(root: Path) -> Path:
    for candidate in (
        root / "_completion" / "ea_provider_contracts",
        root / "ea" / "_completion" / "ea_provider_contracts",
    ):
        if candidate.exists():
            return candidate
    return root / "_completion" / "ea_provider_contracts"


def _load_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def build_provider_contract_status(*, root: Path | None = None) -> dict[str, object]:
    resolved_root = Path(root or _repo_root())
    output_dir = _receipt_dir(resolved_root)
    summary = _load_json(output_dir / SUMMARY_NAME)
    summary_issues: list[str] = []
    rows: list[dict[str, object]] = []
    required_next_receipts: list[str] = []
    contract_receipts_present = 0
    contract_receipts_valid = 0

    if not summary:
        summary_issues.append("summary_missing")

    for key, filename, title in EXPECTED_RECEIPTS:
        path = output_dir / filename
        receipt = _load_json(path)
        if not receipt:
            rows.append(
                {
                    "key": key,
                    "title": title,
                    "path": str(path),
                    "status": "missing",
                    "issues": ["receipt_missing"],
                    "live_provider_runtime_verified": False,
                    "required_next_receipts": [],
                }
            )
            continue
        contract_receipts_present += 1
        issues: list[str] = []
        if receipt.get("live_provider_runtime_verified") is not False:
            issues.append("live_provider_runtime_overclaim")
        if receipt.get("gold_claim_allowed") is not False:
            issues.append("gold_claim_overclaim")
        if not isinstance(receipt.get("verification"), dict) or receipt["verification"].get("contract_exercised") is not True:
            issues.append("contract_not_exercised")
        row_required = list(receipt.get("required_next_receipts") or [])
        required_next_receipts.extend(str(item) for item in row_required if str(item).strip())
        if not issues:
            contract_receipts_valid += 1
        rows.append(
            {
                "key": key,
                "title": title,
                "path": str(path),
                "status": "contract_pass" if not issues else "invalid",
                "issues": issues,
                "live_provider_runtime_verified": False,
                "required_next_receipts": row_required,
            }
        )

    live_provider_runtime_verified = False
    gold_claim_allowed = False
    if summary:
        live_provider_runtime_verified = bool(summary.get("live_provider_runtime_verified") is True)
        gold_claim_allowed = bool(summary.get("gold_claim_allowed") is True)
        if live_provider_runtime_verified:
            summary_issues.append("summary_live_provider_runtime_overclaim")
        if gold_claim_allowed:
            summary_issues.append("summary_gold_claim_overclaim")
        if not required_next_receipts:
            required_next_receipts = [str(item) for item in list(summary.get("required_next_receipts") or []) if str(item).strip()]

    status = "pass" if not summary_issues and contract_receipts_valid == len(EXPECTED_RECEIPTS) else "attention"
    operator_label = (
        "Provider contract layer is exercised; live provider receipts and E2E proof are still pending."
        if status == "pass"
        else "Provider contract layer needs attention before any live-runtime or release-quality claim widens."
    )
    return {
        "contract_name": "ea.provider_contract_status",
        "status": status,
        "contract_receipt_count": len(EXPECTED_RECEIPTS),
        "contract_receipts_present": contract_receipts_present,
        "contract_receipts_valid": contract_receipts_valid,
        "live_provider_runtime_verified": False if live_provider_runtime_verified else False,
        "gold_claim_allowed": False if gold_claim_allowed else False,
        "not_live_provider_proof": True,
        "not_release_gold_proof": True,
        "operator_label": operator_label,
        "summary_issues": summary_issues,
        "required_next_receipts": sorted(set(required_next_receipts)),
        "rows": rows,
    }
