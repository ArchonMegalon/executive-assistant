from __future__ import annotations

import json
from pathlib import Path

from app.services.provider_contract_status import build_provider_contract_status
from scripts.materialize_ea_provider_contract_receipts import build_receipts


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_provider_contract_status_summarizes_valid_contract_receipts(tmp_path: Path) -> None:
    build_receipts(
        output_dir=tmp_path / "_completion" / "ea_provider_contracts",
        generated_at="2026-06-18T12:00:00Z",
        source_git_head="contract-head",
    )

    status = build_provider_contract_status(root=tmp_path)

    assert status["status"] == "pass"
    assert status["contract_receipt_count"] == 5
    assert status["contract_receipts_present"] == 5
    assert status["contract_receipts_valid"] == 5
    assert status["live_provider_runtime_verified"] is False
    assert status["gold_claim_allowed"] is False
    assert status["not_live_provider_proof"] is True
    assert status["not_release_gold_proof"] is True
    assert "live provider receipts" in status["operator_label"]
    assert {row["key"] for row in status["rows"]} == {
        "hedy_meeting_evidence",
        "premium_delivery",
        "approvethis_external_approval",
        "documentation_ai_publication",
        "ea_quality_gates",
    }
    assert all(row["status"] == "contract_pass" for row in status["rows"])
    assert any("_completion/hedy/HEDY_PROVIDER_CAPABILITY.generated.json" in value for value in status["required_next_receipts"])


def test_provider_contract_status_flags_missing_receipts(tmp_path: Path) -> None:
    status = build_provider_contract_status(root=tmp_path)

    assert status["status"] == "attention"
    assert status["summary_issues"] == ["summary_missing"]
    assert status["contract_receipts_present"] == 0
    assert all(row["status"] == "missing" for row in status["rows"])
    assert all(row["issues"] == ["receipt_missing"] for row in status["rows"])


def test_provider_contract_status_flags_live_runtime_overclaim(tmp_path: Path) -> None:
    output_dir = tmp_path / "_completion" / "ea_provider_contracts"
    build_receipts(
        output_dir=output_dir,
        generated_at="2026-06-18T12:00:00Z",
        source_git_head="contract-head",
    )
    receipt_path = output_dir / "HEDY_MEETING_EVIDENCE_CONTRACT.generated.json"
    receipt = _load(receipt_path)
    receipt["live_provider_runtime_verified"] = True
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    status = build_provider_contract_status(root=tmp_path)
    hedy = next(row for row in status["rows"] if row["key"] == "hedy_meeting_evidence")

    assert status["status"] == "attention"
    assert hedy["status"] == "invalid"
    assert "live_provider_runtime_overclaim" in hedy["issues"]
    assert status["live_provider_runtime_verified"] is False
    assert status["gold_claim_allowed"] is False
