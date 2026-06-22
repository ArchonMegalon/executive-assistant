from __future__ import annotations

import json
from pathlib import Path

from ea.scripts.verify_whatsapp_audiobook_live_delivery_receipt import verify


def _write(path: Path, **payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_whatsapp_audiobook_live_delivery_verifier_accepts_waiting_for_live_epub(tmp_path: Path) -> None:
    receipt = tmp_path / ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json"
    _write(
        receipt,
        contract_name="ea.whatsapp_audiobook_live_delivery_receipt.v1",
        generated_by="ea/scripts/materialize_whatsapp_audiobook_live_delivery_receipt.py",
        status="waiting_for_live_epub",
        live_delivery_claim_allowed=False,
        goal_completion_claim_allowed=False,
        candidate_count=0,
        failed_codes=["valid_live_audiobook_delivery_missing", "whatsapp_audiobook_job_missing"],
        next_action="send_epub_over_whatsapp_to_refresh_live_delivery_receipt",
        stage_summary={"counts": {}, "latest_by_stage": {}},
        historical_evidence={"historical_live_path_proven": True, "present": True},
        runtime_readiness={"ready": True, "receipt_present": True, "status": "ready"},
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
        goal_completion_claim_allowed=False,
        candidate_count=2,
        failed_codes=["valid_live_audiobook_delivery_missing"],
        next_action="send_epub_over_whatsapp_to_refresh_live_delivery_receipt",
        stage_summary={},
        historical_evidence={"historical_live_path_proven": False},
        runtime_readiness={"ready": False},
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
                "failed_codes": ["user_selected_voice_delivery_not_ready"],
                "next_action": "choose_whatsapp_audiobook_voice_sample",
                "candidate_count": 1,
                "stage_summary": {"counts": {"waiting_voice_choice": 1}},
                "historical_evidence": {},
                "runtime_readiness": {},
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
