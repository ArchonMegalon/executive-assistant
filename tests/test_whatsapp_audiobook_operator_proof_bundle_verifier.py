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
            "live_processor_runtime_alignment_evaluated": True,
            "live_sidecar_inbox_accessible": True,
            "live_receipt_materialized": True,
            "live_receipt_has_explicit_next_action": True,
            "live_public_share_playback_verified_or_not_required": True,
            "live_voice_selection_text_fallback_ready_or_not_required": True,
            "live_voice_selection_shadow_passed_or_not_required": True,
        },
        runtime_alignment={"evaluated": True, "secret_values_exposed": False},
        live_readiness={"ready": True},
        live_processor={"status": "pass"},
        live_delivery={"status": "waiting_for_live_epub", "candidate_count": 0, "historical_live_path_proven": True},
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
            "live_processor_runtime_alignment_evaluated": True,
            "live_sidecar_inbox_accessible": True,
            "live_receipt_materialized": True,
            "live_receipt_has_explicit_next_action": True,
            "live_public_share_playback_verified_or_not_required": True,
            "live_voice_selection_text_fallback_ready_or_not_required": False,
            "live_voice_selection_shadow_passed_or_not_required": True,
        },
        runtime_alignment={"evaluated": False, "secret_values_exposed": True},
        live_readiness={"ready": True},
        live_processor={"status": "pass"},
        live_delivery={"status": "blocked", "candidate_count": 2, "historical_live_path_proven": False},
        public_share_playback={"status": "waiting", "passed": 0},
    )

    issues = verify(receipt)
    assert "waiting_for_live_epub requires all core checks to pass" in issues
    assert "waiting_for_live_epub bundle requires matching live_delivery.status" in issues
    assert "waiting_for_live_epub bundle requires live_delivery.candidate_count=0" in issues
    assert "waiting_for_live_epub bundle requires historical_live_path_proven=true" in issues
    assert "runtime_alignment.evaluated must remain true" in issues
    assert "runtime_alignment.secret_values_exposed must remain false" in issues
