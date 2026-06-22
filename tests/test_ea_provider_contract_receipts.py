from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.materialize_ea_provider_contract_receipts import build_receipts
from scripts.verify_ea_provider_contract_receipts import verify_contract_receipts


GENERATED_AT = "2026-06-18T12:00:00Z"
SOURCE_HEAD = "contract-head-123"
ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_materialize_provider_contract_receipts_writes_honest_contract_proofs(tmp_path: Path) -> None:
    output_dir = tmp_path / "provider_contracts"

    paths = build_receipts(output_dir=output_dir, generated_at=GENERATED_AT, source_git_head=SOURCE_HEAD)

    assert {path.name for path in paths} == {
        "HEDY_MEETING_EVIDENCE_CONTRACT.generated.json",
        "PREMIUM_DELIVERY_CONTRACT.generated.json",
        "APPROVETHIS_EXTERNAL_APPROVAL_CONTRACT.generated.json",
        "DOCUMENTATION_AI_PUBLICATION_CONTRACT.generated.json",
        "EA_QUALITY_GATES_CONTRACT.generated.json",
        "EA_PROVIDER_CONTRACTS_SUMMARY.generated.json",
    }
    summary = _load(output_dir / "EA_PROVIDER_CONTRACTS_SUMMARY.generated.json")
    assert summary["status"] == "contract_pass_live_provider_pending"
    assert summary["proof_scope"] == "local_contract_exercise"
    assert summary["source_git_head"] == SOURCE_HEAD
    assert summary["live_provider_runtime_verified"] is False
    assert summary["gold_claim_allowed"] is False
    assert summary["not_live_provider_proof"] is True
    assert summary["not_release_gold_proof"] is True
    assert len(summary["required_next_receipts"]) >= 10

    hedy = _load(output_dir / "HEDY_MEETING_EVIDENCE_CONTRACT.generated.json")
    assert hedy["sample_packet"]["webhook_verification"]["status"] == "pass"  # type: ignore[index]
    assert hedy["sample_packet"]["status"] == "review_required"  # type: ignore[index]
    assert hedy["sample_review_intake"]["created_review_task"] is True  # type: ignore[index]
    assert hedy["sample_review_intake"]["human_task"]["task_type"] == "hedy_meeting_review"  # type: ignore[index]
    assert hedy["sample_review_retry"]["duplicate"] is True  # type: ignore[index]
    assert hedy["verification"]["webhook_to_review_queue_contract"] == "pass"  # type: ignore[index]
    assert hedy["verification"]["idempotent_review_task_contract"] == "pass"  # type: ignore[index]
    assert hedy["verification"]["provider_capability_receipt_present"] is False  # type: ignore[index]

    premium = _load(output_dir / "PREMIUM_DELIVERY_CONTRACT.generated.json")
    assert premium["sample_packet"]["validation"]["direct_publish"] == "blocked"  # type: ignore[index]
    assert premium["sample_packet"]["presentation"]["owns_truth"] is False  # type: ignore[index]

    approvethis = _load(output_dir / "APPROVETHIS_EXTERNAL_APPROVAL_CONTRACT.generated.json")
    assert approvethis["sample_result"]["validation"]["downstream_action"] == "blocked"  # type: ignore[index]
    assert approvethis["sample_result"]["final_policy_required"] is True  # type: ignore[index]

    docs = _load(output_dir / "DOCUMENTATION_AI_PUBLICATION_CONTRACT.generated.json")
    assert docs["sample_packet"]["provider_agent_writeback_allowed"] is False  # type: ignore[index]
    assert docs["sample_packet"]["publication_truth_allowed"] is False  # type: ignore[index]

    quality = _load(output_dir / "EA_QUALITY_GATES_CONTRACT.generated.json")
    assert quality["sample_packet"]["provider_evidence_can_make_release_green"] is False  # type: ignore[index]
    assert quality["sample_packet"]["release_claim_supported"] is False  # type: ignore[index]


def test_verify_provider_contract_receipts_passes_for_materialized_output(tmp_path: Path) -> None:
    output_dir = tmp_path / "provider_contracts"
    build_receipts(output_dir=output_dir, generated_at=GENERATED_AT, source_git_head=SOURCE_HEAD)

    result = verify_contract_receipts(output_dir)

    assert result["status"] == "pass"
    assert result["issues"] == []


def test_verify_provider_contract_receipts_rejects_live_runtime_overclaim(tmp_path: Path) -> None:
    output_dir = tmp_path / "provider_contracts"
    build_receipts(output_dir=output_dir, generated_at=GENERATED_AT, source_git_head=SOURCE_HEAD)
    summary_path = output_dir / "EA_PROVIDER_CONTRACTS_SUMMARY.generated.json"
    summary = _load(summary_path)
    summary["live_provider_runtime_verified"] = True
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    result = verify_contract_receipts(output_dir)

    assert result["status"] == "fail"
    assert "summary_live_provider_runtime_overclaim" in result["issues"]


def test_provider_contract_receipt_clis_work(tmp_path: Path) -> None:
    output_dir = tmp_path / "provider_contracts"
    materialized = subprocess.run(
        [
            sys.executable,
            "scripts/materialize_ea_provider_contract_receipts.py",
            "--output-dir",
            str(output_dir),
            "--generated-at",
            GENERATED_AT,
            "--source-git-head",
            SOURCE_HEAD,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    materialized_body = json.loads(materialized.stdout)
    assert materialized_body["status"] == "ok"

    verified = subprocess.run(
        [
            sys.executable,
            "scripts/verify_ea_provider_contract_receipts.py",
            "--output-dir",
            str(output_dir),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    verified_body = json.loads(verified.stdout)
    assert verified_body["status"] == "pass"
