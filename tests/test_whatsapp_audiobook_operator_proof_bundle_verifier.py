from __future__ import annotations

import json
from pathlib import Path

from ea.scripts.verify_whatsapp_audiobook_operator_proof_bundle import verify


def _write(path: Path, **payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_whatsapp_audiobook_operator_proof_bundle_verifier_accepts_waiting_for_live_epub(tmp_path: Path) -> None:
    receipt = tmp_path / ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json"
    _write(
        receipt,
        contract_name="ea.whatsapp_audiobook_operator_proof_bundle.v1",
        generated_by="ea/scripts/materialize_whatsapp_audiobook_operator_proof_bundle.py",
        status="waiting_for_live_epub",
        recommended_action="send_epub_over_whatsapp_to_refresh_live_audiobook_flow",
        checks={
            "local_epub_intake_proof_passed": True,
            "historical_public_share_playback_proven": True,
            "live_action_processor_ready": True,
            "live_action_processor_ran": True,
            "live_action_processor_no_runtime_errors": True,
            "live_processor_button_callbacks_drained": True,
            "live_processor_voice_text_drained": True,
            "live_processor_runtime_alignment_evaluated": True,
            "live_sidecar_inbox_accessible": True,
            "live_receipt_materialized": True,
            "live_receipt_has_explicit_next_action": True,
            "live_public_share_playback_verified_or_not_required": True,
            "live_delivery_semantics_from_live_receipt_or_explicit_nonpass_default": True,
            "live_delivery_claim_scope_explicit": True,
            "human_playback_acceptance_status_explicit": True,
            "rejected_playback_feedback_hashed_or_not_operator_grade": True,
            "machine_delivery_does_not_imply_human_acceptance": True,
            "live_voice_selection_text_fallback_ready_or_not_required": True,
            "live_voice_selection_shadow_passed_or_not_required": True,
        },
        proof_semantics={
            "machine_playable_delivery_evidence": "not_proven",
            "human_acceptance_evidence": "not_human_verified",
            "live_delivery_claim_scope": "none",
            "machine_playable_delivery_does_not_imply_human_acceptance": True,
        },
        runtime_alignment={"evaluated": True, "secret_values_exposed": False},
        live_readiness={"ready": True},
        live_processor={"status": "pass"},
        live_delivery={
            "status": "waiting_for_live_epub",
            "candidate_count": 0,
            "historical_live_path_proven": True,
            "live_delivery_claim_allowed": False,
            "live_delivery_claim_scope": "none",
            "fresh_live_job_receipt_proven": False,
            "human_playback_acceptance_claim_allowed": False,
            "human_playback_acceptance_evidence": {"status": "not_human_verified", "claim_allowed": False},
            "proof_semantics": {
                "machine_playable_delivery_does_not_imply_human_acceptance": True,
            },
            "goal_completion_claim_allowed": False,
        },
        public_share_playback={"status": "pass", "passed": 1},
    )

    assert verify(receipt) == []


def test_whatsapp_audiobook_operator_proof_bundle_verifier_rejects_bad_waiting_for_live_epub(tmp_path: Path) -> None:
    receipt = tmp_path / ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json"
    _write(
        receipt,
        contract_name="ea.whatsapp_audiobook_operator_proof_bundle.v1",
        generated_by="ea/scripts/materialize_whatsapp_audiobook_operator_proof_bundle.py",
        status="waiting_for_live_epub",
        recommended_action="send_epub_over_whatsapp_to_refresh_live_audiobook_flow",
        checks={
            "local_epub_intake_proof_passed": True,
            "historical_public_share_playback_proven": False,
            "live_action_processor_ready": False,
            "live_action_processor_ran": True,
            "live_action_processor_no_runtime_errors": True,
            "live_processor_button_callbacks_drained": True,
            "live_processor_voice_text_drained": False,
            "live_processor_runtime_alignment_evaluated": True,
            "live_sidecar_inbox_accessible": True,
            "live_receipt_materialized": True,
            "live_receipt_has_explicit_next_action": True,
            "live_public_share_playback_verified_or_not_required": True,
            "live_delivery_semantics_from_live_receipt_or_explicit_nonpass_default": True,
            "live_delivery_claim_scope_explicit": True,
            "human_playback_acceptance_status_explicit": True,
            "rejected_playback_feedback_hashed_or_not_operator_grade": True,
            "machine_delivery_does_not_imply_human_acceptance": True,
            "live_voice_selection_text_fallback_ready_or_not_required": False,
            "live_voice_selection_shadow_passed_or_not_required": True,
        },
        proof_semantics={
            "machine_playable_delivery_evidence": "not_proven",
            "human_acceptance_evidence": "not_human_verified",
            "live_delivery_claim_scope": "none",
            "machine_playable_delivery_does_not_imply_human_acceptance": True,
        },
        runtime_alignment={"evaluated": False, "secret_values_exposed": True},
        live_readiness={"ready": True},
        live_processor={"status": "pass"},
        live_delivery={
            "status": "blocked",
            "candidate_count": 2,
            "historical_live_path_proven": False,
            "live_delivery_claim_allowed": False,
            "live_delivery_claim_scope": "none",
            "fresh_live_job_receipt_proven": False,
            "human_playback_acceptance_claim_allowed": False,
            "human_playback_acceptance_evidence": {"status": "not_human_verified", "claim_allowed": False},
            "proof_semantics": {
                "machine_playable_delivery_does_not_imply_human_acceptance": True,
            },
            "goal_completion_claim_allowed": False,
        },
        public_share_playback={"status": "waiting", "passed": 0},
    )

    issues = verify(receipt)
    assert "waiting_for_live_epub requires all core checks to pass" in issues
    assert "waiting_for_live_epub bundle requires matching live_delivery.status" in issues
    assert "waiting_for_live_epub bundle requires live_delivery.candidate_count=0" in issues
    assert "waiting_for_live_epub bundle requires historical_live_path_proven=true" in issues
    assert "runtime_alignment.evaluated must remain true" in issues
    assert "runtime_alignment.secret_values_exposed must remain false" in issues


def test_whatsapp_audiobook_operator_proof_bundle_verifier_rejects_pass_without_fresh_drained_proof(tmp_path: Path) -> None:
    receipt = tmp_path / ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json"
    _write(
        receipt,
        contract_name="ea.whatsapp_audiobook_operator_proof_bundle.v1",
        generated_by="ea/scripts/materialize_whatsapp_audiobook_operator_proof_bundle.py",
        status="pass",
        recommended_action="capture_real_user_playback_acceptance_or_close_operator_loop",
        checks={
            "local_epub_intake_proof_passed": True,
            "historical_public_share_playback_proven": True,
            "live_action_processor_ready": True,
            "live_action_processor_ran": True,
            "live_action_processor_no_runtime_errors": True,
            "live_processor_button_callbacks_drained": False,
            "live_processor_voice_text_drained": False,
            "live_processor_runtime_alignment_evaluated": True,
            "live_sidecar_inbox_accessible": True,
            "live_receipt_materialized": True,
            "live_receipt_has_explicit_next_action": True,
            "live_public_share_playback_verified_or_not_required": True,
            "live_delivery_semantics_from_live_receipt_or_explicit_nonpass_default": True,
            "live_delivery_claim_scope_explicit": True,
            "human_playback_acceptance_status_explicit": True,
            "rejected_playback_feedback_hashed_or_not_operator_grade": True,
            "machine_delivery_does_not_imply_human_acceptance": True,
            "live_voice_selection_text_fallback_ready_or_not_required": True,
            "live_voice_selection_shadow_passed_or_not_required": True,
        },
        proof_semantics={
            "machine_playable_delivery_evidence": "fresh_job_receipt_and_machine_playback_e2e",
            "human_acceptance_evidence": "not_human_verified",
            "live_delivery_claim_scope": "machine_playable_delivery_only",
            "machine_playable_delivery_does_not_imply_human_acceptance": True,
        },
        runtime_alignment={"evaluated": True, "secret_values_exposed": False},
        live_readiness={"ready": True},
        live_processor={"status": "pass"},
        live_delivery={
            "status": "pass",
            "candidate_count": 1,
            "live_delivery_claim_allowed": True,
            "live_delivery_claim_scope": "machine_playable_delivery_only",
            "machine_playback_e2e_verified": True,
            "fresh_live_job_receipt_proven": False,
            "historical_or_shadow_proof_only": True,
            "real_user_playback_acceptance_verified": False,
            "human_playback_acceptance_claim_allowed": False,
            "human_playback_acceptance_evidence": {"status": "not_human_verified", "claim_allowed": False},
            "proof_semantics": {
                "machine_playable_delivery_does_not_imply_human_acceptance": True,
            },
            "goal_completion_claim_allowed": False,
        },
        public_share_playback={"status": "pass", "passed": 1},
    )

    issues = verify(receipt)
    assert "pass bundle requires fresh_live_job_receipt_proven=true" in issues
    assert "pass bundle cannot rely on historical_or_shadow_proof_only" in issues
    assert "pass bundle requires live processor button callbacks to be drained" in issues
    assert "pass bundle requires live processor voice text choices to be drained" in issues


def test_whatsapp_audiobook_operator_proof_bundle_verifier_rejects_rejected_playback_flattened_to_generic_pass(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json"
    _write(
        receipt,
        contract_name="ea.whatsapp_audiobook_operator_proof_bundle.v1",
        generated_by="ea/scripts/materialize_whatsapp_audiobook_operator_proof_bundle.py",
        status="pass",
        recommended_action="capture_real_user_playback_acceptance_or_close_operator_loop",
        checks={
            "local_epub_intake_proof_passed": True,
            "historical_public_share_playback_proven": True,
            "live_action_processor_ready": True,
            "live_action_processor_ran": True,
            "live_action_processor_no_runtime_errors": True,
            "live_processor_button_callbacks_drained": True,
            "live_processor_voice_text_drained": True,
            "live_processor_runtime_alignment_evaluated": True,
            "live_sidecar_inbox_accessible": True,
            "live_receipt_materialized": True,
            "live_receipt_has_explicit_next_action": True,
            "live_public_share_playback_verified_or_not_required": True,
            "live_delivery_semantics_from_live_receipt_or_explicit_nonpass_default": True,
            "live_delivery_claim_scope_explicit": True,
            "human_playback_acceptance_status_explicit": True,
            "rejected_playback_feedback_hashed_or_not_operator_grade": False,
            "machine_delivery_does_not_imply_human_acceptance": True,
            "live_voice_selection_text_fallback_ready_or_not_required": True,
            "live_voice_selection_shadow_passed_or_not_required": True,
        },
        proof_semantics={
            "machine_playable_delivery_evidence": "fresh_job_receipt_and_machine_playback_e2e",
            "human_acceptance_evidence": "rejected",
            "live_delivery_claim_scope": "machine_playable_delivery_only",
            "machine_playable_delivery_does_not_imply_human_acceptance": True,
        },
        runtime_alignment={"evaluated": True, "secret_values_exposed": False},
        live_readiness={"ready": True},
        live_processor={"status": "pass"},
        live_delivery={
            "status": "pass",
            "candidate_count": 1,
            "live_delivery_claim_allowed": True,
            "live_delivery_claim_scope": "machine_playable_delivery_only",
            "machine_playback_e2e_verified": True,
            "fresh_live_job_receipt_proven": True,
            "historical_or_shadow_proof_only": False,
            "real_user_playback_acceptance_verified": False,
            "human_playback_acceptance_claim_allowed": False,
            "human_playback_acceptance_evidence": {
                "status": "rejected",
                "rejected": True,
                "claim_allowed": False,
            },
            "proof_semantics": {
                "machine_playable_delivery_does_not_imply_human_acceptance": True,
            },
            "goal_completion_claim_allowed": False,
        },
        public_share_playback={"status": "pass", "passed": 1},
    )

    issues = verify(receipt)
    assert "rejected human playback evidence requires feedback_sha256_valid=true" in issues
    assert "pass bundle requires rejected playback evidence to carry hashed feedback" in issues
