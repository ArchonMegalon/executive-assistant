from __future__ import annotations

import json
from pathlib import Path

from ea.scripts.verify_whatsapp_audiobook_local_intake_proof import verify


def _write_receipt(path: Path, **payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _base_receipt() -> dict[str, object]:
    checks = {
        "intake_processor_passed": True,
        "voice_selection_processor_passed": True,
        "epub_processed_once": True,
        "three_voice_samples_sent": True,
        "job_created": True,
        "intake_job_waiting_for_voice_choice": True,
        "use_callback_captured": True,
        "voice_choice_callback_processed": True,
        "voice_selected_by_user": True,
        "chapter_audio_rendered": True,
        "m4b_ready": True,
        "audiobookshelf_imported": True,
        "player_scoped_reference_ready": True,
        "player_scoped_reference_resolves": True,
        "player_scoped_audio_probe_passed": True,
        "player_http_metadata_ready": True,
        "player_http_audio_download_works": True,
        "public_share_ready": True,
        "whatsapp_public_share_sent": True,
        "chapters_extracted": True,
        "whatsapp_sender_bound": True,
        "whatsapp_session_bound": True,
        "whatsapp_message_hash_present": True,
        "receipt_voice_delivery_sent": True,
        "intake_stage_waits_for_voice_choice": True,
        "local_delivery_tracks_machine_playback_gap": True,
    }
    return {
        "contract_name": "ea.whatsapp_audiobook_local_epub_intake_proof.v1",
        "generated_by": "ea/scripts/materialize_whatsapp_audiobook_local_intake_proof.py",
        "status": "pass",
        "checks": checks,
        "processor_report": {
            "intake": {
                "status": "pass",
                "epub_processed": 1,
                "voice_sample_sent": 3,
            },
            "voice_selection": {
                "status": "pass",
                "processed": 1,
                "share_link_sent": 1,
            },
        },
        "intake_summary": {
            "status": "waiting_voice_selection",
            "stage_next_action": "choose_whatsapp_audiobook_voice_sample",
        },
        "job_summary": {
            "status": "audiobookshelf_imported",
            "chapter_count": 2,
            "voice_selection_status": "selected_by_user",
            "pending_voice_sample_count": 0,
            "render_status": "rendered",
            "m4b_status": "m4b_ready",
            "audiobookshelf_import_status": "imported",
            "public_share_status": "public_share_ready",
        },
        "sanitized_receipt_summary": {
            "status": "audiobookshelf_imported",
            "m4b_output_ready": True,
            "chapter_metadata_embedded": True,
            "player_scoped_reference_status": "signed_reference_ready",
            "public_share_status": "public_share_ready",
            "public_share_whatsapp_delivery_status": "sent",
            "public_share_whatsapp_message_id_present": True,
            "whatsapp_sender_bound": True,
            "whatsapp_session_bound": True,
            "whatsapp_message_hash_present": True,
            "whatsapp_voice_sample_delivery_status": "sent",
        },
        "player_probe_summary": {
            "status": "pass",
            "metadata_status": "ready",
            "content_type": "audio/mp4",
            "file_ready": True,
            "file_sha256": "abc123",
            "audio_streams": 1,
            "duration_seconds": 1.0,
            "raw_path_exposed": False,
            "raw_token_exposed": False,
        },
        "player_http_probe_summary": {
            "status": "pass",
            "metadata_status_code": 200,
            "metadata_status": "ready",
            "metadata_cache_control": "no-store",
            "metadata_download_url_present": True,
            "metadata_vendor_token_exposed": False,
            "metadata_raw_library_path_exposed": False,
            "download_status_code": 200,
            "download_content_type": "audio/mp4",
            "download_cache_control": "no-store",
            "download_bytes": 12,
            "raw_path_exposed": False,
            "raw_token_exposed": False,
        },
        "local_stage_receipt_summary": {
            "intake": {
                "status": "waiting_voice_choice",
                "live_delivery_claim_allowed": False,
                "next_action": "choose_whatsapp_audiobook_voice_sample",
                "stage_counts": {"waiting_voice_choice": 1},
            },
            "delivery": {
                "status": "blocked",
                "live_delivery_claim_allowed": False,
                "next_action": "finish_user_selected_voice_audiobook_before_sending_whatsapp_public_share_link",
                "stage_counts": {"waiting_machine_playback_verification": 1},
            },
        },
        "privacy": {
            "live_whatsapp_claim": False,
            "raw_epub_text_persisted": False,
            "raw_sender_ref_exposed": False,
            "raw_message_id_exposed": False,
            "callback_tokens_exposed": False,
            "public_share_token_exposed": False,
            "player_access_token_exposed": False,
            "audiobookshelf_raw_path_exposed": False,
            "provider_voice_ids_exposed": False,
            "provider_secret_exposed": False,
            "local_temp_job_root_removed_after_run": True,
        },
    }


def test_whatsapp_audiobook_local_intake_proof_verifier_accepts_valid_receipt(tmp_path: Path) -> None:
    receipt = tmp_path / ".codex-studio/published/whatsapp_audiobook_local_intake_proof.generated.json"
    _write_receipt(receipt, **_base_receipt())

    assert verify(receipt) == []


def test_whatsapp_audiobook_local_intake_proof_verifier_rejects_missing_check_and_drift(tmp_path: Path) -> None:
    payload = _base_receipt()
    payload["checks"] = dict(payload["checks"])
    del payload["checks"]["three_voice_samples_sent"]
    payload["player_http_probe_summary"] = dict(payload["player_http_probe_summary"])
    payload["player_http_probe_summary"]["download_status_code"] = 500

    receipt = tmp_path / ".codex-studio/published/whatsapp_audiobook_local_intake_proof.generated.json"
    _write_receipt(receipt, **payload)

    issues = verify(receipt)
    assert "missing required checks: three_voice_samples_sent" in issues
    assert "player_http_probe_summary.download_status_code must be 200" in issues
