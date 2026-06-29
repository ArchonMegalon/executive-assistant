from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType


GENERATED_AT = "2026-06-20T11:20:00Z"


def _load_script(name: str) -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "ea" / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _office_loop_receipt(*, local_ready: bool = True, accepted: bool = False) -> dict[str, object]:
    component_status = "pass" if local_ready else "fail"
    return {
        "contract_name": "ea.office_loop_goal_receipt.v1",
        "status": "ready_local_evidence" if local_ready else "blocked",
        "live_daily_use_verified": accepted,
        "real_operator_acceptance_verified": accepted,
        "external_provider_runtime_verified": accepted,
        "goal_completion_claim_allowed": False,
        "components": {
            "command_brief": {"status": component_status, "evidence_route": "/app/today"},
            "decision_queue": {"status": component_status, "evidence_route": "/app/queue"},
            "commitment_ledger": {"status": component_status, "evidence_route": "/app/commitments"},
            "approved_action_workflow": {"status": component_status, "evidence_route": "/app/channel-loop/approvals"},
            "evidence_audit_trail": {"status": component_status, "evidence_route": "/admin/audit-trail"},
            "support_recovery": {"status": component_status, "evidence_route": "/app/settings/support"},
            "operator_control": {"status": component_status, "evidence_route": "/admin/office"},
            "goal_evidence": {"status": component_status, "evidence_route": "/admin/goals"},
        },
        "diagnostics_summary": {
            "analytics_counts_present": local_ready,
            "channel_loop_digest_keys": ["memo", "approvals", "operator"] if local_ready else ["memo"],
        },
        "boundary_posture": {
            "ea_is_product_truth": False,
            "ea_is_memory_truth": False,
            "ea_owns_canonical_queue_truth": False,
            "ea_owns_release_authority": False,
            "assistant_local_prompts_are_canon": False,
            "provider_telemetry_is_product_authority": False,
        },
        "seeded_fixture": {"raw_private_context_exposed": False},
        "remaining_external_proofs": []
        if accepted
        else [
            "real daily morning brief acceptance",
            "real decision cleared by the principal or operator",
            "real commitment recovered or closed with an evidence receipt",
            "real approved outbound action with audit trail",
            "real provider failure recovered with operator-grade reason",
        ],
    }


def _raw_acceptance_input() -> dict[str, object]:
    return {
        "proofs": [
            {
                "key": "real_daily_morning_brief_accepted",
                "accepted": True,
                "source": "principal",
                "recorded_at": GENERATED_AT,
                "evidence": "Morning brief accepted because it made the day clearer.",
                "actor": "principal name",
                "object_ref": "telegram-message-1",
            },
            {
                "key": "real_decision_cleared",
                "accepted": True,
                "source": "operator",
                "recorded_at": GENERATED_AT,
                "evidence": "Decision cleared with owner, tradeoff, and stale-by signal.",
                "actor": "operator name",
                "object_ref": "decision-1",
            },
            {
                "key": "real_commitment_recovered_or_closed",
                "accepted": True,
                "source": "operator",
                "recorded_at": GENERATED_AT,
                "evidence": "Commitment recovered with due date and receipt.",
                "actor": "operator name",
                "object_ref": "commitment-1",
            },
            {
                "key": "real_approved_action_audited",
                "accepted": True,
                "source": "audit",
                "recorded_at": GENERATED_AT,
                "evidence": "Approved action executed through the adapter with audit trail.",
                "actor": "auditor name",
                "object_ref": "approval-1",
            },
            {
                "key": "real_provider_failure_recovered",
                "accepted": True,
                "source": "provider_runtime",
                "recorded_at": GENERATED_AT,
                "evidence": "Provider failure produced reason, recovery step, and redacted debug receipt.",
                "actor": "runtime operator",
                "object_ref": "provider-failure-1",
            },
        ],
    }


def test_executive_assistant_acceptance_evidence_hashes_raw_inputs(tmp_path: Path) -> None:
    materializer = _load_script("materialize_executive_assistant_acceptance_evidence")
    verifier = _load_script("verify_executive_assistant_acceptance_evidence")
    receipt_path = tmp_path / "ea-acceptance.generated.json"

    receipt = materializer.materialize_executive_assistant_acceptance_evidence(
        receipt_path=receipt_path,
        input_payload=_raw_acceptance_input(),
        generated_at=GENERATED_AT,
    )

    serialized = json.dumps(receipt)
    assert receipt["status"] == "ready_real_world_acceptance_evidence"
    assert receipt["real_daily_use_verified"] is True
    assert receipt["real_principal_acceptance_verified"] is True
    assert receipt["goal_completion_claim_allowed"] is False
    assert receipt["acceptance_capture_surface"]["path"] == "/admin/actions/acceptance-evidence"  # type: ignore[index]
    assert receipt["acceptance_capture_surface"]["raw_input_not_persisted"] is True  # type: ignore[index]
    assert len(receipt["acceptance_capture_requirements"]) == 5
    assert receipt["acceptance_capture_requirements"][0]["status"] == "accepted_redacted"  # type: ignore[index]
    assert receipt["acceptance_capture_requirements"][0]["capture_path"] == "/admin/actions/acceptance-evidence"  # type: ignore[index]
    assert "Morning brief accepted" not in serialized
    assert "principal name" not in serialized
    assert receipt["acceptance_keys"]["real_daily_morning_brief_accepted"]["raw_evidence_exposed"] is False  # type: ignore[index]

    verification = verifier.verify_executive_assistant_acceptance_evidence(receipt_path)

    assert verification["status"] == "pass"
    assert verification["issues"] == []


def test_executive_assistant_acceptance_evidence_preserves_existing_redacted_rows(tmp_path: Path) -> None:
    materializer = _load_script("materialize_executive_assistant_acceptance_evidence")
    receipt_path = tmp_path / "ea-acceptance-preserved.generated.json"
    partial_input = {"proofs": [_raw_acceptance_input()["proofs"][0]]}  # type: ignore[index]

    first = materializer.materialize_executive_assistant_acceptance_evidence(
        receipt_path=receipt_path,
        input_payload=partial_input,
        generated_at=GENERATED_AT,
    )
    second = materializer.materialize_executive_assistant_acceptance_evidence(
        receipt_path=receipt_path,
        generated_at="2026-06-20T11:25:00Z",
    )

    assert first["status"] == "partial_real_world_acceptance_evidence"
    assert second["status"] == "partial_real_world_acceptance_evidence"
    assert second["accepted_keys"] == ["real_daily_morning_brief_accepted"]
    requirements = {item["key"]: item for item in second["acceptance_capture_requirements"]}  # type: ignore[index]
    assert requirements["real_daily_morning_brief_accepted"]["status"] == "accepted_redacted"
    assert requirements["real_decision_cleared"]["status"] == "pending_real_world_evidence"
    assert requirements["real_decision_cleared"]["next_action"] == "record_redacted_acceptance_evidence:real_decision_cleared"
    assert second["acceptance_keys"]["real_daily_morning_brief_accepted"]["evidence_sha256"] == first["acceptance_keys"]["real_daily_morning_brief_accepted"]["evidence_sha256"]  # type: ignore[index]
    assert "Morning brief accepted because" not in receipt_path.read_text(encoding="utf-8")

    reset = materializer.materialize_executive_assistant_acceptance_evidence(
        receipt_path=receipt_path,
        generated_at="2026-06-20T11:26:00Z",
        preserve_existing=False,
    )
    assert reset["status"] == "blocked_missing_real_world_acceptance_evidence"
    assert reset["accepted_keys"] == []


def test_executive_assistant_acceptance_verifier_requires_capture_contract(tmp_path: Path) -> None:
    materializer = _load_script("materialize_executive_assistant_acceptance_evidence")
    verifier = _load_script("verify_executive_assistant_acceptance_evidence")
    receipt_path = tmp_path / "tampered-acceptance.generated.json"
    materializer.materialize_executive_assistant_acceptance_evidence(
        receipt_path=receipt_path,
        input_payload={"proofs": [_raw_acceptance_input()["proofs"][0]]},  # type: ignore[index]
        generated_at=GENERATED_AT,
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt.pop("acceptance_capture_surface")
    receipt["acceptance_capture_requirements"] = []
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verifier.verify_executive_assistant_acceptance_evidence(receipt_path)

    assert verification["status"] == "fail"
    assert "ea_acceptance_capture_surface_path_missing" in verification["issues"]
    assert "ea_acceptance_capture_requirement_missing:real_daily_morning_brief_accepted" in verification["issues"]


def test_executive_assistant_quality_readiness_blocks_real_world_acceptance_without_overclaiming(tmp_path: Path) -> None:
    materializer = _load_script("materialize_executive_assistant_quality_readiness")
    verifier = _load_script("verify_executive_assistant_quality_readiness")
    receipt_path = tmp_path / "ea-quality.generated.json"

    receipt = materializer.materialize_executive_assistant_quality_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        office_loop=_office_loop_receipt(local_ready=True, accepted=False),
    )

    assert receipt["status"] == "blocked_real_world_acceptance"
    assert receipt["local_quality_evidence_ready"] is True
    assert receipt["ready_for_real_daily_use_review"] is True
    assert receipt["good_executive_assistant_claim_allowed"] is False
    assert receipt["goal_completion_claim_allowed"] is False
    assert "real_daily_morning_brief_accepted" in receipt["blocked_checks"]
    assert "real_provider_failure_recovered" in receipt["external_acceptance_blockers"]
    assert receipt["quality_dimensions"]["morning_brief"]["status"] == "ready"  # type: ignore[index]
    assert receipt["privacy"]["raw_private_context_exposed"] is False  # type: ignore[index]

    verification = verifier.verify_executive_assistant_quality_readiness(receipt_path)

    assert verification["status"] == "pass"
    assert verification["issues"] == []


def test_executive_assistant_quality_readiness_uses_redacted_acceptance_evidence(tmp_path: Path) -> None:
    acceptance_materializer = _load_script("materialize_executive_assistant_acceptance_evidence")
    materializer = _load_script("materialize_executive_assistant_quality_readiness")
    verifier = _load_script("verify_executive_assistant_quality_readiness")
    receipt_path = tmp_path / "ea-quality-accepted.generated.json"
    acceptance_path = tmp_path / "ea-acceptance.generated.json"
    acceptance = acceptance_materializer.materialize_executive_assistant_acceptance_evidence(
        receipt_path=acceptance_path,
        input_payload=_raw_acceptance_input(),
        generated_at=GENERATED_AT,
    )

    receipt = materializer.materialize_executive_assistant_quality_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        office_loop=_office_loop_receipt(local_ready=True, accepted=False),
        acceptance_evidence=acceptance,
        acceptance_evidence_receipt_path=acceptance_path,
    )

    assert receipt["status"] == "ready_for_good_executive_assistant_claim_review"
    assert receipt["blocked_checks"] == []
    assert receipt["external_acceptance_blockers"] == []
    assert receipt["live_daily_use_verified"] is True
    assert receipt["real_principal_acceptance_verified"] is True
    assert receipt["real_provider_recovery_verified"] is True
    assert receipt["goal_completion_claim_allowed"] is False

    verification = verifier.verify_executive_assistant_quality_readiness(receipt_path)

    assert verification["status"] == "pass"
    assert verification["issues"] == []


def test_executive_assistant_quality_readiness_reports_local_quality_regression(tmp_path: Path) -> None:
    materializer = _load_script("materialize_executive_assistant_quality_readiness")
    verifier = _load_script("verify_executive_assistant_quality_readiness")
    receipt_path = tmp_path / "ea-quality-local-blocked.generated.json"

    receipt = materializer.materialize_executive_assistant_quality_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        office_loop=_office_loop_receipt(local_ready=False, accepted=False),
    )

    assert receipt["status"] == "blocked_local_quality_evidence"
    assert receipt["local_quality_evidence_ready"] is False
    assert "command_brief_local_ready" in receipt["local_blockers"]
    assert "api_digest_local_ready" in receipt["local_blockers"]

    verification = verifier.verify_executive_assistant_quality_readiness(receipt_path)

    assert verification["status"] == "pass"
    assert verification["issues"] == []


def test_executive_assistant_quality_readiness_can_be_claim_ready_without_closing_goal(tmp_path: Path) -> None:
    materializer = _load_script("materialize_executive_assistant_quality_readiness")
    verifier = _load_script("verify_executive_assistant_quality_readiness")
    receipt_path = tmp_path / "ea-quality-ready.generated.json"

    receipt = materializer.materialize_executive_assistant_quality_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        office_loop=_office_loop_receipt(local_ready=True, accepted=True),
    )

    assert receipt["status"] == "ready_for_good_executive_assistant_claim_review"
    assert receipt["blocked_checks"] == []
    assert receipt["good_executive_assistant_claim_allowed"] is True
    assert receipt["goal_completion_claim_allowed"] is False

    verification = verifier.verify_executive_assistant_quality_readiness(receipt_path)

    assert verification["status"] == "pass"
    assert verification["issues"] == []


def test_executive_assistant_quality_readiness_verifier_rejects_overclaims(tmp_path: Path) -> None:
    materializer = _load_script("materialize_executive_assistant_quality_readiness")
    verifier = _load_script("verify_executive_assistant_quality_readiness")
    receipt_path = tmp_path / "tampered.generated.json"
    materializer.materialize_executive_assistant_quality_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        office_loop=_office_loop_receipt(local_ready=True, accepted=False),
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["goal_completion_claim_allowed"] = True
    receipt["good_executive_assistant_claim_allowed"] = True
    receipt["ea_is_product_truth"] = True
    receipt["privacy"]["seeded_fixture_raw_private_context_exposed"] = True
    receipt["required_real_world_proof"] = []
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verifier.verify_executive_assistant_quality_readiness(receipt_path)

    assert verification["status"] == "fail"
    assert "ea_quality_completion_overclaim" in verification["issues"]
    assert "ea_quality_product_truth_overclaim" in verification["issues"]
    assert "ea_quality_good_claim_flag_mismatch" in verification["issues"]
    assert "ea_quality_privacy_flag_not_false:seeded_fixture_raw_private_context_exposed" in verification["issues"]
    assert "ea_quality_required_proof_missing:real daily morning brief acceptance" in verification["issues"]


def test_executive_assistant_quality_readiness_clis_work(tmp_path: Path) -> None:
    script_root = Path(__file__).resolve().parents[1] / "ea" / "scripts"
    receipt_path = tmp_path / "cli-ea-quality.generated.json"
    office_receipt = tmp_path / "office.generated.json"
    acceptance_receipt = tmp_path / "acceptance.generated.json"
    office_receipt.write_text(json.dumps(_office_loop_receipt(local_ready=True, accepted=False)) + "\n", encoding="utf-8")
    acceptance = subprocess.run(
        [
            sys.executable,
            str(script_root / "materialize_executive_assistant_acceptance_evidence.py"),
            "--receipt",
            str(acceptance_receipt),
            "--generated-at",
            GENERATED_AT,
        ],
        cwd=Path(__file__).resolve().parents[1] / "ea",
        text=True,
        capture_output=True,
        check=False,
    )
    assert acceptance.returncode == 0, acceptance.stderr + acceptance.stdout
    materialized = subprocess.run(
        [
            sys.executable,
            str(script_root / "materialize_executive_assistant_quality_readiness.py"),
            "--receipt",
            str(receipt_path),
            "--office-loop-receipt",
            str(office_receipt),
            "--acceptance-evidence-receipt",
            str(acceptance_receipt),
            "--generated-at",
            GENERATED_AT,
            "--no-refresh",
        ],
        cwd=Path(__file__).resolve().parents[1] / "ea",
        text=True,
        capture_output=True,
        check=False,
    )
    assert materialized.returncode == 0, materialized.stderr + materialized.stdout
    assert receipt_path.is_file()

    verified = subprocess.run(
        [
            sys.executable,
            str(script_root / "verify_executive_assistant_quality_readiness.py"),
            "--receipt",
            str(receipt_path),
        ],
        cwd=Path(__file__).resolve().parents[1] / "ea",
        text=True,
        capture_output=True,
        check=False,
    )

    assert verified.returncode == 0, verified.stderr + verified.stdout
    assert json.loads(verified.stdout)["status"] == "pass"


def test_executive_assistant_acceptance_cli_preserves_existing_redacted_rows(tmp_path: Path) -> None:
    script_root = Path(__file__).resolve().parents[1] / "ea" / "scripts"
    receipt_path = tmp_path / "cli-acceptance.generated.json"
    input_path = tmp_path / "raw-acceptance-input.json"
    input_path.write_text(
        json.dumps({"proofs": [_raw_acceptance_input()["proofs"][0]]}) + "\n",  # type: ignore[index]
        encoding="utf-8",
    )

    captured = subprocess.run(
        [
            sys.executable,
            str(script_root / "materialize_executive_assistant_acceptance_evidence.py"),
            "--receipt",
            str(receipt_path),
            "--input",
            str(input_path),
            "--generated-at",
            GENERATED_AT,
        ],
        cwd=Path(__file__).resolve().parents[1] / "ea",
        text=True,
        capture_output=True,
        check=False,
    )
    assert captured.returncode == 0, captured.stderr + captured.stdout

    refreshed = subprocess.run(
        [
            sys.executable,
            str(script_root / "materialize_executive_assistant_acceptance_evidence.py"),
            "--receipt",
            str(receipt_path),
            "--generated-at",
            "2026-06-20T11:27:00Z",
        ],
        cwd=Path(__file__).resolve().parents[1] / "ea",
        text=True,
        capture_output=True,
        check=False,
    )
    assert refreshed.returncode == 0, refreshed.stderr + refreshed.stdout
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "partial_real_world_acceptance_evidence"
    assert receipt["accepted_keys"] == ["real_daily_morning_brief_accepted"]
    assert "Morning brief accepted because" not in receipt_path.read_text(encoding="utf-8")

    reset = subprocess.run(
        [
            sys.executable,
            str(script_root / "materialize_executive_assistant_acceptance_evidence.py"),
            "--receipt",
            str(receipt_path),
            "--reset",
            "--generated-at",
            "2026-06-20T11:28:00Z",
        ],
        cwd=Path(__file__).resolve().parents[1] / "ea",
        text=True,
        capture_output=True,
        check=False,
    )
    assert reset.returncode == 0, reset.stderr + reset.stdout
    assert json.loads(receipt_path.read_text(encoding="utf-8"))["status"] == "blocked_missing_real_world_acceptance_evidence"
