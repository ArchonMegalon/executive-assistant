from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType


GENERATED_AT = "2026-06-20T09:45:00Z"


def _load_script(name: str) -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "ea" / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_lower_receipts(tmp_path: Path) -> tuple[Path, Path, Path]:
    office = tmp_path / "office.generated.json"
    acceptance = tmp_path / "ea-acceptance.generated.json"
    quality = tmp_path / "ea-quality.generated.json"
    office.write_text(
        json.dumps(
            {
                "contract_name": "ea.office_loop_goal_receipt.v1",
                "status": "ready_local_evidence",
                "goal_completion_claim_allowed": False,
                "remaining_external_proofs": [
                    "real daily morning brief acceptance",
                    "real weekly signal-to-decision review accepted by the operator",
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    acceptance.write_text(
        json.dumps(
            {
                "contract_name": "ea.executive_assistant_acceptance_evidence.v1",
                "status": "blocked_missing_real_world_acceptance_evidence",
                "goal_completion_claim_allowed": False,
                "remaining_external_proofs": [
                    "real decision cleared by the principal or operator",
                    "real provider failure recovered with operator-grade reason",
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    quality.write_text(
        json.dumps(
            {
                "contract_name": "ea.executive_assistant_quality_readiness.v1",
                "status": "blocked_real_world_acceptance",
                "goal_completion_claim_allowed": False,
                "remaining_external_proofs": [
                    "real commitment recovered or closed with an evidence receipt",
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return office, acceptance, quality


def test_signal_to_decision_receipt_materializes_local_packet_without_overclaim(tmp_path: Path) -> None:
    materializer = _load_script("materialize_whole_project_signal_to_decision_receipt")
    verifier = _load_script("verify_whole_project_signal_to_decision_receipt")
    office, acceptance, quality = _write_lower_receipts(tmp_path)
    receipt_path = tmp_path / "signal.generated.json"

    receipt = materializer.materialize_whole_project_signal_to_decision_receipt(
        receipt_path=receipt_path,
        office_loop_receipt_path=office,
        acceptance_evidence_receipt_path=acceptance,
        ea_quality_receipt_path=quality,
        generated_at=GENERATED_AT,
    )

    assert receipt["status"] == "ready_local_packet_pending_operator_acceptance"
    assert receipt["generated_by"] == "ea/scripts/materialize_whole_project_signal_to_decision_receipt.py"
    assert receipt["goal_completion_claim_allowed"] is False
    assert receipt["queue_truth_claim_allowed"] is False
    assert receipt["release_authority_claim_allowed"] is False
    assert receipt["next_action"] == "record_redacted_signal_review_acceptance"
    assert receipt["next_action_href"] == "/admin/actions/signal-to-decision-evidence"
    assert receipt["next_action_label"] == "Record a signal-loop outcome"
    assert receipt["next_action_method"] == "post"
    assert (
        receipt["next_action_form_href"]
        == "/admin/actions/signal-to-decision-evidence?return_to=%2Fadmin%2Fgoals&evidence_part=review"
    )
    assert receipt["next_action_form_method"] == "get"
    assert receipt["next_action_evidence_part"] == "review"
    assert receipt["operator_action_key"] == "weekly_signal_to_decision_review_acceptance"
    packet = receipt["operator_action_packet"]
    assert packet["status"] == "action_required"
    assert packet["user_action_required"] is True
    assert packet["action_required_reason"] == "real_world_acceptance_missing"
    assert packet["next_action"] == "record_redacted_signal_review_acceptance"
    assert packet["next_action_form_href"] == receipt["next_action_form_href"]
    assert packet["next_action_evidence_part"] == "review"
    assert packet["delivery_policy"] == "action_required_only"
    assert packet["telegram_push_allowed"] is True
    assert packet["interruption_budget"] == "action_required"
    assert packet["quiet_hours_respected"] is True
    assert packet["non_action_progress_push_allowed"] is False
    assert packet["irreversible_actions_consent_gated"] is True
    assert packet["raw_acceptance_text_exposed"] is False
    assert packet["raw_actor_identity_exposed"] is False
    assert packet["accepted_parts"] == {"review": False, "followthrough": False}
    assert receipt["real_weekly_operator_review_accepted"] is False
    assert receipt["closed_loop_followthrough_receipt_verified"] is False
    assert receipt["signal_evidence_capture_surface"]["path"] == "/admin/actions/signal-to-decision-evidence"  # type: ignore[index]
    assert receipt["signal_evidence_capture_surface"]["form_method"] == "GET"  # type: ignore[index]
    assert receipt["signal_evidence_capture_surface"]["raw_input_not_persisted"] is True  # type: ignore[index]
    requirements = {item["evidence_part"]: item for item in receipt["signal_evidence_capture_requirements"]}  # type: ignore[index]
    assert requirements["review"]["status"] == "pending_real_world_evidence"
    assert (
        requirements["review"]["form_href"]
        == "/admin/actions/signal-to-decision-evidence?return_to=%2Fadmin%2Fgoals&evidence_part=review"
    )
    assert requirements["followthrough"]["status"] == "pending_real_world_evidence"
    assert requirements["review"]["raw_input_not_persisted"] is True
    assert "real weekly signal-to-decision review accepted by the operator" in receipt["remaining_external_proofs"]
    assert "closed-loop signal-to-decision follow-through receipt accepted by the operator" in receipt["remaining_external_proofs"]
    signal_sources = {row["key"]: row for row in receipt["signal_sources"]}  # type: ignore[index]
    for key in materializer.REQUIRED_SIGNAL_SOURCES:
        assert signal_sources[key]["status"] == "mapped_from_sources"
        assert signal_sources[key]["owner_truth_plane"]
        assert signal_sources[key]["journey_or_release_gate_mapping"]
    assert len(receipt["decision_packet"]["decision_items"]) >= 3  # type: ignore[index]

    verification = verifier.verify_whole_project_signal_to_decision_receipt(receipt_path)

    assert verification["status"] == "pass"
    assert verification["issues"] == []


def test_signal_to_decision_receipt_hashes_operator_review_and_followthrough(tmp_path: Path) -> None:
    materializer = _load_script("materialize_whole_project_signal_to_decision_receipt")
    verifier = _load_script("verify_whole_project_signal_to_decision_receipt")
    office, acceptance, quality = _write_lower_receipts(tmp_path)
    receipt_path = tmp_path / "accepted-signal.generated.json"
    raw_review = "Weekly packet was accepted after reviewing private support and media notes."
    raw_followthrough = "Operator routed provider recovery to the owner and closed the review loop."
    raw_actor = "operator-private-reviewer"
    raw_packet_ref = "weekly-signal-packet-private-123"

    receipt = materializer.materialize_whole_project_signal_to_decision_receipt(
        receipt_path=receipt_path,
        office_loop_receipt_path=office,
        acceptance_evidence_receipt_path=acceptance,
        ea_quality_receipt_path=quality,
        input_payload={
            "review": {
                "accepted": True,
                "source_kind": "operator",
                "review": raw_review,
                "actor": raw_actor,
                "packet_ref": raw_packet_ref,
                "recorded_at": GENERATED_AT,
            },
            "followthrough": {
                "accepted": True,
                "source_kind": "operator",
                "followthrough": raw_followthrough,
                "actor": raw_actor,
                "packet_ref": raw_packet_ref,
                "recorded_at": GENERATED_AT,
            },
        },
        generated_at=GENERATED_AT,
    )

    assert receipt["status"] == "ready_real_signal_to_decision_closure"
    assert receipt["next_action"] == "review_closed_signal_to_decision_claim"
    assert receipt["next_action_href"] == ""
    assert receipt["next_action_label"] == ""
    assert receipt["next_action_method"] == ""
    assert receipt["next_action_form_href"] == ""
    assert receipt["next_action_form_method"] == ""
    assert receipt["next_action_evidence_part"] == ""
    assert receipt["operator_action_key"] == ""
    assert receipt["operator_action_packet"]["status"] == "not_required"  # type: ignore[index]
    assert receipt["operator_action_packet"]["user_action_required"] is False  # type: ignore[index]
    assert receipt["operator_action_packet"]["delivery_policy"] == "queue_only"  # type: ignore[index]
    assert receipt["operator_action_packet"]["telegram_push_allowed"] is False  # type: ignore[index]
    assert receipt["operator_action_packet"]["interruption_budget"] == "none"  # type: ignore[index]
    assert receipt["real_weekly_operator_review_accepted"] is True
    assert receipt["closed_loop_followthrough_receipt_verified"] is True
    assert receipt["goal_completion_claim_allowed"] is False
    requirements = {item["evidence_part"]: item for item in receipt["signal_evidence_capture_requirements"]}  # type: ignore[index]
    assert requirements["review"]["status"] == "accepted_redacted"
    assert requirements["followthrough"]["status"] == "accepted_redacted"
    assert receipt["operator_review"]["status"] == "accepted_redacted"  # type: ignore[index]
    assert receipt["followthrough_receipt"]["status"] == "accepted_redacted"  # type: ignore[index]
    assert receipt["operator_review"]["raw_review_exposed"] is False  # type: ignore[index]
    assert receipt["followthrough_receipt"]["raw_followthrough_exposed"] is False  # type: ignore[index]
    receipt_text = receipt_path.read_text(encoding="utf-8")
    assert raw_review not in receipt_text
    assert raw_followthrough not in receipt_text
    assert raw_actor not in receipt_text
    assert raw_packet_ref not in receipt_text
    assert receipt["operator_review"]["review_sha256"]  # type: ignore[index]
    assert receipt["followthrough_receipt"]["followthrough_sha256"]  # type: ignore[index]

    verification = verifier.verify_whole_project_signal_to_decision_receipt(receipt_path)

    assert verification["status"] == "pass"
    assert verification["issues"] == []


def test_signal_to_decision_receipt_preserves_existing_redacted_operator_review(tmp_path: Path) -> None:
    materializer = _load_script("materialize_whole_project_signal_to_decision_receipt")
    office, acceptance, quality = _write_lower_receipts(tmp_path)
    receipt_path = tmp_path / "preserved-signal.generated.json"
    raw_review = "Weekly packet was accepted after reviewing private support and media notes."
    raw_actor = "operator-private-reviewer"
    raw_packet_ref = "weekly-signal-packet-private-123"

    first = materializer.materialize_whole_project_signal_to_decision_receipt(
        receipt_path=receipt_path,
        office_loop_receipt_path=office,
        acceptance_evidence_receipt_path=acceptance,
        ea_quality_receipt_path=quality,
        input_payload={
            "review": {
                "accepted": True,
                "source_kind": "operator",
                "review": raw_review,
                "actor": raw_actor,
                "packet_ref": raw_packet_ref,
                "recorded_at": GENERATED_AT,
            }
        },
        generated_at=GENERATED_AT,
    )
    second = materializer.materialize_whole_project_signal_to_decision_receipt(
        receipt_path=receipt_path,
        office_loop_receipt_path=office,
        acceptance_evidence_receipt_path=acceptance,
        ea_quality_receipt_path=quality,
        generated_at="2026-06-20T09:55:00Z",
    )

    assert first["status"] == "partial_real_signal_to_decision_closure"
    assert second["status"] == "partial_real_signal_to_decision_closure"
    assert second["real_weekly_operator_review_accepted"] is True
    assert second["closed_loop_followthrough_receipt_verified"] is False
    assert second["next_action"] == "record_redacted_signal_followthrough_acceptance"
    assert second["next_action_href"] == "/admin/actions/signal-to-decision-evidence"
    assert second["next_action_label"] == "Record a signal-loop outcome"
    assert second["next_action_method"] == "post"
    assert (
        second["next_action_form_href"]
        == "/admin/actions/signal-to-decision-evidence?return_to=%2Fadmin%2Fgoals&evidence_part=followthrough"
    )
    assert second["next_action_form_method"] == "get"
    assert second["next_action_evidence_part"] == "followthrough"
    assert second["operator_action_key"] == "weekly_signal_to_decision_review_acceptance"
    packet = second["operator_action_packet"]
    assert packet["status"] == "action_required"
    assert packet["next_action"] == "record_redacted_signal_followthrough_acceptance"
    assert packet["next_action_evidence_part"] == "followthrough"
    assert packet["accepted_parts"] == {"review": True, "followthrough": False}
    requirements = {item["evidence_part"]: item for item in second["signal_evidence_capture_requirements"]}  # type: ignore[index]
    assert requirements["review"]["status"] == "accepted_redacted"
    assert requirements["followthrough"]["status"] == "pending_real_world_evidence"
    assert second["operator_review"]["review_sha256"] == first["operator_review"]["review_sha256"]  # type: ignore[index]
    receipt_text = receipt_path.read_text(encoding="utf-8")
    assert raw_review not in receipt_text
    assert raw_actor not in receipt_text
    assert raw_packet_ref not in receipt_text

    reset = materializer.materialize_whole_project_signal_to_decision_receipt(
        receipt_path=receipt_path,
        office_loop_receipt_path=office,
        acceptance_evidence_receipt_path=acceptance,
        ea_quality_receipt_path=quality,
        generated_at="2026-06-20T09:56:00Z",
        preserve_existing=False,
    )

    assert reset["status"] == "ready_local_packet_pending_operator_acceptance"
    assert reset["real_weekly_operator_review_accepted"] is False
    assert reset["closed_loop_followthrough_receipt_verified"] is False


def test_signal_to_decision_verifier_rejects_overclaim_and_missing_source(tmp_path: Path) -> None:
    materializer = _load_script("materialize_whole_project_signal_to_decision_receipt")
    verifier = _load_script("verify_whole_project_signal_to_decision_receipt")
    office, acceptance, quality = _write_lower_receipts(tmp_path)
    receipt_path = tmp_path / "tampered.generated.json"
    materializer.materialize_whole_project_signal_to_decision_receipt(
        receipt_path=receipt_path,
        office_loop_receipt_path=office,
        acceptance_evidence_receipt_path=acceptance,
        ea_quality_receipt_path=quality,
        generated_at=GENERATED_AT,
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["goal_completion_claim_allowed"] = True
    receipt["generated_by"] = "wrong"
    receipt["queue_truth_claim_allowed"] = True
    receipt["boundary_posture"]["ea_is_product_truth"] = True
    receipt.pop("signal_evidence_capture_surface")
    receipt["signal_evidence_capture_requirements"] = []
    receipt.pop("operator_action_packet")
    receipt["next_action_href"] = ""
    receipt["next_action_label"] = ""
    receipt["next_action_method"] = ""
    receipt["signal_sources"] = [row for row in receipt["signal_sources"] if row["key"] != "provider_runtime_failures"]
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verifier.verify_whole_project_signal_to_decision_receipt(receipt_path)

    assert verification["status"] == "fail"
    assert "signal_decision_generated_by_mismatch" in verification["issues"]
    assert "signal_decision_completion_overclaim" in verification["issues"]
    assert "signal_decision_queue_truth_overclaim" in verification["issues"]
    assert "signal_decision_ea_product_truth_overclaim" in verification["issues"]
    assert "signal_decision_source_row_missing:provider_runtime_failures" in verification["issues"]
    assert "signal_decision_capture_surface_path_missing" in verification["issues"]
    assert "signal_decision_capture_requirement_missing:review" in verification["issues"]
    assert "signal_decision_operator_action_packet_missing" in verification["issues"]
    assert "signal_decision_next_action_href_missing" in verification["issues"]
    assert "signal_decision_next_action_label_missing" in verification["issues"]
    assert "signal_decision_next_action_method_missing" in verification["issues"]


def test_signal_to_decision_clis_work(tmp_path: Path) -> None:
    script_root = Path(__file__).resolve().parents[1] / "ea" / "scripts"
    office, acceptance, quality = _write_lower_receipts(tmp_path)
    receipt_path = tmp_path / "cli-signal.generated.json"
    materialized = subprocess.run(
        [
            sys.executable,
            str(script_root / "materialize_whole_project_signal_to_decision_receipt.py"),
            "--receipt",
            str(receipt_path),
            "--office-loop-receipt",
            str(office),
            "--acceptance-evidence-receipt",
            str(acceptance),
            "--ea-quality-receipt",
            str(quality),
            "--generated-at",
            GENERATED_AT,
        ],
        cwd=Path(__file__).resolve().parents[1] / "ea",
        text=True,
        capture_output=True,
        check=False,
    )
    assert materialized.returncode == 0, materialized.stderr + materialized.stdout
    receipt = json.loads(materialized.stdout)
    assert receipt["status"] == "ready_local_packet_pending_operator_acceptance"
    assert receipt["receipt"] == receipt_path.as_posix()

    verified = subprocess.run(
        [
            sys.executable,
            str(script_root / "verify_whole_project_signal_to_decision_receipt.py"),
            "--receipt",
            str(receipt_path),
        ],
        cwd=Path(__file__).resolve().parents[1] / "ea",
        text=True,
        capture_output=True,
        check=False,
    )
    assert verified.returncode == 0, verified.stderr + verified.stdout
    verification = json.loads(verified.stdout)
    assert verification["status"] == "pass"
