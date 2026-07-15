from __future__ import annotations

import json
from pathlib import Path

from ea.scripts.verify_whatsapp_audiobook_live_delivery_receipt import verify
from scripts.source_state_head import resolve_source_state_head
from scripts.source_state_head import resolve_source_worktree_fingerprint


ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, **payload: object) -> None:
    payload.setdefault("source_git_head", resolve_source_state_head(ROOT))
    payload.setdefault("head_semantics", "source_state")
    payload.setdefault("source_state_fingerprint", resolve_source_worktree_fingerprint(ROOT))
    payload.setdefault(
        "source_state_fingerprint_semantics",
        "worktree_source_files_sha256_excluding_generated_only_paths",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _pass_receipt(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "contract_name": "ea.whatsapp_audiobook_live_delivery_receipt.v1",
        "generated_by": "ea/scripts/materialize_whatsapp_audiobook_live_delivery_receipt.py",
        "status": "pass",
        "live_delivery_claim_allowed": True,
        "live_delivery_claim_scope": "machine_playable_delivery_only",
        "fresh_live_job_receipt_proven": True,
        "historical_or_shadow_proof_only": False,
        "proof_freshness": {"fresh_live_job_receipt_passed": True},
        "machine_playback_e2e_verified": True,
        "real_user_playback_acceptance_verified": False,
        "human_playback_acceptance_claim_allowed": False,
        "human_playback_acceptance_evidence": {
            "status": "not_human_verified",
            "claim_allowed": False,
            "accepted": False,
            "rejected": False,
        },
        "proof_semantics": {
            "machine_playable_delivery_does_not_imply_human_acceptance": True,
        },
        "goal_completion_claim_allowed": False,
        "failed_codes": [],
        "next_action": "capture_real_user_playback_acceptance_or_close_operator_loop",
        "stage_summary": {"counts": {"delivered_playable": 1}},
        "historical_evidence": {},
        "runtime_readiness": {},
        "audiobook_runtime": {},
    }
    payload.update(overrides)
    payload["proof_semantics"] = {
        **dict(payload.get("proof_semantics") or {}),
        "live_delivery_claim_scope": str(payload.get("live_delivery_claim_scope") or ""),
        "human_acceptance_evidence": str(
            dict(payload.get("human_playback_acceptance_evidence") or {}).get("status") or ""
        ),
    }
    return payload


def test_whatsapp_audiobook_live_delivery_verifier_accepts_machine_playable_without_human_acceptance(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json"
    _write(receipt, **_pass_receipt())

    assert verify(receipt) == []


def test_whatsapp_audiobook_live_delivery_verifier_accepts_rejected_human_acceptance_only_with_review_action(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json"
    _write(
        receipt,
        **_pass_receipt(
            human_playback_acceptance_evidence={
                "status": "rejected",
                "claim_allowed": False,
                "accepted": False,
                "rejected": True,
                "rejected_claim_observed": True,
                "feedback_sha256_present": True,
                "feedback_sha256_valid": True,
                "feedback_sha256_required": True,
                "operator_grade": True,
            },
            next_action="review_audiobook_playback_problem",
        ),
    )

    assert verify(receipt) == []


def test_whatsapp_audiobook_live_delivery_verifier_requires_hash_capture_for_unhashed_rejected_claim(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json"
    _write(
        receipt,
        **_pass_receipt(
            human_playback_acceptance_evidence={
                "status": "not_human_verified",
                "claim_allowed": False,
                "accepted": False,
                "rejected": False,
                "rejected_claim_observed": True,
                "feedback_sha256_present": False,
                "feedback_sha256_valid": False,
                "feedback_sha256_required": True,
            },
            next_action="capture_real_user_playback_acceptance_or_close_operator_loop",
        ),
    )

    assert "unhashed rejected human playback claims require hashed playback-problem feedback capture" in verify(receipt)


def test_whatsapp_audiobook_live_delivery_verifier_rejects_human_claim_without_accepted_evidence(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json"
    _write(
        receipt,
        **_pass_receipt(
            human_playback_acceptance_claim_allowed=True,
            live_delivery_claim_scope="machine_playable_delivery_and_human_accepted",
        ),
    )

    issues = verify(receipt)
    assert "human acceptance claim requires real_user_playback_acceptance_verified=true" in issues
    assert "human acceptance claim requires accepted human evidence" in issues


def test_whatsapp_audiobook_live_delivery_verifier_accepts_human_accepted_scope(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json"
    _write(
        receipt,
        **_pass_receipt(
            live_delivery_claim_scope="machine_playable_delivery_and_human_accepted",
            real_user_playback_acceptance_verified=True,
            human_playback_acceptance_claim_allowed=True,
            human_playback_acceptance_evidence={
                "status": "accepted",
                "claim_allowed": True,
                "accepted": True,
                "rejected": False,
            },
            next_action="close_operator_loop",
        ),
    )

    assert verify(receipt) == []


def test_whatsapp_audiobook_live_delivery_verifier_accepts_waiting_for_live_epub(tmp_path: Path) -> None:
    receipt = tmp_path / ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json"
    _write(
        receipt,
        contract_name="ea.whatsapp_audiobook_live_delivery_receipt.v1",
        generated_by="ea/scripts/materialize_whatsapp_audiobook_live_delivery_receipt.py",
        status="waiting_for_live_epub",
        live_delivery_claim_allowed=False,
        live_delivery_claim_scope="none",
        fresh_live_job_receipt_proven=False,
        historical_or_shadow_proof_only=True,
        proof_freshness={
            "fresh_live_job_receipt_present": False,
            "fresh_live_job_receipt_passed": False,
            "historical_evidence_present": True,
            "historical_live_path_proven": True,
        },
        goal_completion_claim_allowed=False,
        candidate_count=0,
        failed_codes=["valid_live_audiobook_delivery_missing", "whatsapp_audiobook_job_missing"],
        next_action="send_epub_over_whatsapp_to_refresh_live_delivery_receipt",
        stage_summary={"counts": {}, "latest_by_stage": {}},
        historical_evidence={"historical_live_path_proven": True, "present": True},
        runtime_readiness={"ready": True, "receipt_present": True, "status": "ready"},
        audiobook_runtime={"ready_for_live_intake": True, "status": "pass"},
        human_playback_acceptance_claim_allowed=False,
        human_playback_acceptance_evidence={"status": "not_human_verified", "claim_allowed": False},
        proof_semantics={
            "machine_playable_delivery_does_not_imply_human_acceptance": True,
            "live_delivery_claim_scope": "none",
            "human_acceptance_evidence": "not_human_verified",
        },
    )

    assert verify(receipt) == []


def test_whatsapp_audiobook_live_delivery_verifier_rejects_bad_waiting_for_live_epub(tmp_path: Path) -> None:
    receipt = tmp_path / ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json"
    _write(
        receipt,
        contract_name="ea.whatsapp_audiobook_live_delivery_receipt.v1",
        generated_by="ea/scripts/materialize_whatsapp_audiobook_live_delivery_receipt.py",
        status="waiting_for_live_epub",
        live_delivery_claim_allowed=False,
        live_delivery_claim_scope="none",
        fresh_live_job_receipt_proven=False,
        historical_or_shadow_proof_only=False,
        proof_freshness={},
        goal_completion_claim_allowed=False,
        candidate_count=2,
        failed_codes=["valid_live_audiobook_delivery_missing"],
        next_action="send_epub_over_whatsapp_to_refresh_live_delivery_receipt",
        stage_summary={},
        historical_evidence={"historical_live_path_proven": False},
        runtime_readiness={"ready": False},
        audiobook_runtime={"ready_for_live_intake": False},
        human_playback_acceptance_claim_allowed=False,
        human_playback_acceptance_evidence={"status": "not_human_verified", "claim_allowed": False},
        proof_semantics={"machine_playable_delivery_does_not_imply_human_acceptance": True},
    )

    issues = verify(receipt)
    assert "waiting_for_live_epub requires candidate_count=0" in issues
    assert "waiting_for_live_epub requires runtime_readiness.ready=true" in issues
    assert "waiting_for_live_epub requires historical_live_path_proven=true" in issues


def test_whatsapp_audiobook_live_delivery_verifier_requires_text_fallback_signal_for_waiting_voice_choice(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(
        json.dumps(
            {
                "contract_name": "ea.whatsapp_audiobook_live_delivery_receipt.v1",
                "generated_by": "ea/scripts/materialize_whatsapp_audiobook_live_delivery_receipt.py",
                "status": "waiting_voice_choice",
                "live_delivery_claim_allowed": False,
                "live_delivery_claim_scope": "none",
                "fresh_live_job_receipt_proven": False,
                "historical_or_shadow_proof_only": False,
                "proof_freshness": {},
                "failed_codes": ["user_selected_voice_delivery_not_ready"],
                "next_action": "choose_whatsapp_audiobook_voice_sample",
                "candidate_count": 1,
                "stage_summary": {"counts": {"waiting_voice_choice": 1}},
                "historical_evidence": {},
                "runtime_readiness": {},
                "audiobook_runtime": {},
                "human_playback_acceptance_claim_allowed": False,
                "human_playback_acceptance_evidence": {
                    "status": "not_human_verified",
                    "claim_allowed": False,
                },
                "proof_semantics": {
                    "machine_playable_delivery_does_not_imply_human_acceptance": True,
                },
                "goal_completion_claim_allowed": False,
                "pending_user_selected_voice_jobs": [
                    {
                        "voice_selection_waiting": True,
                        "replacement_choice_pending": False,
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    issues = verify(receipt)
    assert "waiting_voice_choice must expose voice_selection_text_fallback_ready" in issues
    assert "waiting voice-choice pending jobs must expose voice_selection_text_fallback_ready" in issues
