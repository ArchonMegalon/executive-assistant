from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType


GENERATED_AT = "2026-06-20T08:15:00Z"


def _load_script(name: str) -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "ea" / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_lower_receipts(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    office = tmp_path / "office.generated.json"
    acceptance = tmp_path / "ea-acceptance.generated.json"
    quality = tmp_path / "ea-quality.generated.json"
    active = tmp_path / "active-media.generated.json"
    signal = tmp_path / "signal-to-decision.generated.json"
    office.write_text(
        json.dumps(
            {
                "contract_name": "ea.office_loop_goal_receipt.v1",
                "status": "ready_local_evidence",
                "goal_completion_claim_allowed": False,
                "additional_goals": [
                    {
                        "key": "whole_project_scope_gap_audit",
                        "label": "Whole-project scope gap audit",
                        "status": "active_local_goal",
                        "claim_limit": "local_scope_audit_not_canonical_product_truth",
                        "requires": [
                            "core_product_loop_mapping",
                            "privacy_retention_support_telemetry_check",
                            "next_external_or_human_proof",
                        ],
                        "protected_scope_axes": [
                            "build_character_and_rules",
                            "run_session",
                            "privacy_retention",
                        ],
                    },
                    {
                        "key": "whole_project_signal_to_decision_closure",
                        "label": "Whole-project signal-to-decision closure",
                        "status": "active_local_goal",
                        "source_path": ".codex-design/ea/CONTINUOUS_IMPROVEMENT_GOAL.md",
                        "claim_limit": "local_signal_synthesis_not_canonical_queue_or_release_truth",
                        "requires": [
                            "cross_surface_signal_intake",
                            "journey_or_release_gate_mapping",
                            "owner_truth_plane_routing",
                            "weekly_operator_decision_packet",
                            "closed_loop_followthrough_receipt",
                            "human_acceptance_before_queue_or_release_claim",
                        ],
                        "protected_signal_sources": [
                            "real_usage_telemetry",
                            "support_and_recovery_cases",
                            "feedback_and_crash_reports",
                            "public_or_premium_publication_reactions",
                            "provider_runtime_failures",
                            "audiobook_and_media_acceptance",
                            "manfred_spoken_conversation_acceptance",
                            "telegram_whatsapp_email_channel_friction",
                            "release_install_update_friction",
                            "privacy_or_boundary_incidents",
                        ],
                    }
                ],
                "remaining_external_proofs": [
                    "real daily morning brief acceptance",
                    "real whole-project scope gap audit reviewed against the current product spine",
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
                    "real daily morning brief acceptance",
                    "real decision cleared by the principal or operator",
                    "real commitment recovered or closed with an evidence receipt",
                    "real approved outbound action with audit trail",
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
                    "real daily morning brief acceptance",
                    "real decision cleared by the principal or operator",
                    "real commitment recovered or closed with an evidence receipt",
                    "real approved outbound action with audit trail",
                    "real provider failure recovered with operator-grade reason",
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    active.write_text(
        json.dumps(
            {
                "contract_name": "ea.active_media_ltd_goal_bundle.v1",
                "status": "ready_local_evidence",
                "goal_completion_claim_allowed": False,
                "remaining_external_proofs": [
                    "ChatLab live runtime probe receipt",
                    "real Manfred spoken-conversation STT/TTS roundtrip evidence",
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    signal.write_text(
        json.dumps(
            {
                "contract_name": "ea.whole_project_signal_to_decision_receipt.v1",
                "status": "ready_local_packet_pending_operator_acceptance",
                "goal_completion_claim_allowed": False,
                "remaining_external_proofs": [
                    "real weekly signal-to-decision review accepted by the operator",
                    "closed-loop signal-to-decision follow-through receipt accepted by the operator",
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return office, acceptance, quality, active, signal


def test_whole_project_scope_gap_audit_materializes_axis_receipt(tmp_path: Path) -> None:
    materializer = _load_script("materialize_whole_project_scope_gap_audit")
    verifier = _load_script("verify_whole_project_scope_gap_audit")
    office, acceptance, quality, active, signal = _write_lower_receipts(tmp_path)
    receipt_path = tmp_path / "scope-gap.generated.json"

    receipt = materializer.materialize_whole_project_scope_gap_audit(
        receipt_path=receipt_path,
        office_loop_receipt_path=office,
        acceptance_evidence_receipt_path=acceptance,
        ea_quality_receipt_path=quality,
        active_media_receipt_path=active,
        signal_to_decision_receipt_path=signal,
        generated_at=GENERATED_AT,
    )

    assert receipt["status"] == "ready_local_audit"
    assert receipt["head_semantics"] == "source_state"
    assert receipt["source_git_head"]
    assert receipt["source_state_fingerprint"]
    assert (
        receipt["source_state_fingerprint_semantics"]
        == "worktree_source_files_sha256_excluding_generated_only_paths"
    )
    assert receipt["summary"]
    assert receipt["next_action"] == "review_scope_gap_audit_against_current_product_spine_with_a_human_operator"
    assert receipt["next_action_href"] == "/admin/goals"
    assert receipt["next_action_label"] == "Review scope gap audit"
    assert receipt["next_action_method"] == "get"
    assert receipt["reviewed_against_current_product_spine"] is False
    assert receipt["operator_review_accepted"] is False
    assert receipt["review_capture_surface"]["raw_input_not_persisted"] is True  # type: ignore[index]
    assert receipt["review_capture_surface"]["privacy_contract"]["raw_review_text_persisted"] is False  # type: ignore[index]
    assert receipt["goal_completion_claim_allowed"] is False
    assert receipt["public_or_premium_claim_allowed"] is False
    assert receipt["boundary_posture"]["ea_is_product_truth"] is False  # type: ignore[index]
    assert receipt["scope_goal"]["key"] == "whole_project_scope_gap_audit"  # type: ignore[index]
    assert receipt["project_learning_goal"]["key"] == "whole_project_signal_to_decision_closure"  # type: ignore[index]
    assert "weekly_operator_decision_packet" in receipt["project_learning_goal"]["requires"]  # type: ignore[index]
    assert "provider_runtime_failures" in receipt["project_learning_goal"]["protected_signal_sources"]  # type: ignore[index]
    axes = {row["key"]: row for row in receipt["scope_axes"]}  # type: ignore[index]
    for axis in materializer.REQUIRED_SCOPE_AXES:
        assert axes[axis]["status"] == "mapped_from_mirrored_sources"
        assert axes[axis]["source_files"]
        assert axes[axis]["next_external_or_human_proof"]
    assert "ChatLab live runtime probe receipt" in receipt["remaining_external_proofs"]
    assert "real daily morning brief acceptance" in receipt["remaining_external_proofs"]
    assert "real whole-project scope gap audit reviewed against the current product spine" in receipt["remaining_external_proofs"]
    assert "real weekly signal-to-decision review accepted by the operator" in receipt["remaining_external_proofs"]
    assert "closed-loop signal-to-decision follow-through receipt accepted by the operator" in receipt["remaining_external_proofs"]
    assert receipt["evidence_receipts"]["executive_assistant_acceptance_evidence"]["contract_name"] == "ea.executive_assistant_acceptance_evidence.v1"  # type: ignore[index]
    assert receipt["evidence_receipts"]["signal_to_decision"]["contract_name"] == "ea.whole_project_signal_to_decision_receipt.v1"  # type: ignore[index]

    verification = verifier.verify_whole_project_scope_gap_audit(receipt_path)

    assert verification["status"] == "pass"
    assert verification["issues"] == []


def test_whole_project_scope_gap_audit_verifier_rejects_missing_axis_and_overclaim(tmp_path: Path) -> None:
    materializer = _load_script("materialize_whole_project_scope_gap_audit")
    verifier = _load_script("verify_whole_project_scope_gap_audit")
    office, acceptance, quality, active, signal = _write_lower_receipts(tmp_path)
    receipt_path = tmp_path / "tampered.generated.json"
    materializer.materialize_whole_project_scope_gap_audit(
        receipt_path=receipt_path,
        office_loop_receipt_path=office,
        acceptance_evidence_receipt_path=acceptance,
        ea_quality_receipt_path=quality,
        active_media_receipt_path=active,
        signal_to_decision_receipt_path=signal,
        generated_at=GENERATED_AT,
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt.pop("source_git_head", None)
    receipt["next_action"] = "wrong_action"
    receipt["goal_completion_claim_allowed"] = True
    receipt["boundary_posture"]["ea_is_product_truth"] = True
    receipt["scope_axes"] = [row for row in receipt["scope_axes"] if row["key"] != "run_session"]
    receipt["review_capture_surface"]["privacy_contract"]["raw_review_text_persisted"] = True
    receipt["project_learning_goal"]["protected_signal_sources"].remove("provider_runtime_failures")
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verifier.verify_whole_project_scope_gap_audit(receipt_path)

    assert verification["status"] == "fail"
    assert "scope_gap_source_git_head_missing" in verification["issues"]
    assert "scope_gap_next_action_drifted" in verification["issues"]
    assert "scope_gap_completion_overclaim" in verification["issues"]
    assert "scope_gap_ea_product_truth_overclaim" in verification["issues"]
    assert "scope_gap_axis_missing:run_session" in verification["issues"]
    assert "scope_gap_review_capture_privacy_drifted:raw_review_text_persisted" in verification["issues"]
    assert "scope_gap_signal_to_decision_source_missing:provider_runtime_failures" in verification["issues"]


def test_whole_project_scope_gap_audit_clis_work(tmp_path: Path) -> None:
    script_root = Path(__file__).resolve().parents[1] / "ea" / "scripts"
    office, acceptance, quality, active, signal = _write_lower_receipts(tmp_path)
    receipt_path = tmp_path / "cli-scope-gap.generated.json"
    materialized = subprocess.run(
        [
            sys.executable,
            str(script_root / "materialize_whole_project_scope_gap_audit.py"),
            "--receipt",
            str(receipt_path),
            "--office-loop-receipt",
            str(office),
            "--acceptance-evidence-receipt",
            str(acceptance),
            "--ea-quality-receipt",
            str(quality),
            "--active-media-receipt",
            str(active),
            "--signal-to-decision-receipt",
            str(signal),
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
    assert receipt["status"] == "ready_local_audit"
    assert receipt["receipt"] == receipt_path.as_posix()

    verified = subprocess.run(
        [
            sys.executable,
            str(script_root / "verify_whole_project_scope_gap_audit.py"),
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
