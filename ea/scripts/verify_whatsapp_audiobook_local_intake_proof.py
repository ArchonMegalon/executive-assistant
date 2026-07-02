from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RECEIPT = ROOT / ".codex-studio" / "published" / "whatsapp_audiobook_local_intake_proof.generated.json"

REQUIRED_CHECKS = {
    "intake_processor_passed",
    "voice_selection_processor_passed",
    "epub_processed_once",
    "three_voice_samples_sent",
    "job_created",
    "intake_job_waiting_for_voice_choice",
    "use_callback_captured",
    "voice_choice_callback_processed",
    "voice_selected_by_user",
    "chapter_audio_rendered",
    "m4b_ready",
    "audiobookshelf_imported",
    "player_scoped_reference_ready",
    "player_scoped_reference_resolves",
    "player_scoped_audio_probe_passed",
    "player_http_metadata_ready",
    "player_http_audio_download_works",
    "public_share_ready",
    "whatsapp_public_share_sent",
    "chapters_extracted",
    "whatsapp_sender_bound",
    "whatsapp_session_bound",
    "whatsapp_message_hash_present",
    "receipt_voice_delivery_sent",
    "intake_stage_waits_for_voice_choice",
    "local_delivery_tracks_machine_playback_gap",
}


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def verify(path: Path = DEFAULT_RECEIPT) -> list[str]:
    issues: list[str] = []
    receipt = _json(path)
    if not receipt:
        return [f"whatsapp audiobook local intake proof missing or invalid: {path}"]

    if receipt.get("contract_name") != "ea.whatsapp_audiobook_local_epub_intake_proof.v1":
        issues.append("contract_name must be ea.whatsapp_audiobook_local_epub_intake_proof.v1")
    if receipt.get("generated_by") != "ea/scripts/materialize_whatsapp_audiobook_local_intake_proof.py":
        issues.append("generated_by must point at the WhatsApp local-intake materializer")

    status = str(receipt.get("status") or "").strip()
    if status not in {"pass", "fail"}:
        issues.append("status must stay pass or fail")

    checks = dict(receipt.get("checks") or {})
    missing_checks = sorted(REQUIRED_CHECKS - set(checks))
    if missing_checks:
        issues.append(f"missing required checks: {', '.join(missing_checks)}")
    if status == "pass" and not all(bool(checks.get(key)) for key in REQUIRED_CHECKS):
        issues.append("pass status requires all required checks to be true")

    processor_report = dict(receipt.get("processor_report") or {})
    intake = dict(processor_report.get("intake") or {})
    voice_selection = dict(processor_report.get("voice_selection") or {})
    if intake.get("status") != "pass":
        issues.append("processor_report.intake.status must be pass")
    if voice_selection.get("status") != "pass":
        issues.append("processor_report.voice_selection.status must be pass")
    if int(intake.get("epub_processed") or 0) != 1:
        issues.append("processor_report.intake.epub_processed must be 1")
    if int(intake.get("voice_sample_sent") or 0) != 3:
        issues.append("processor_report.intake.voice_sample_sent must be 3")
    if int(voice_selection.get("processed") or 0) != 1:
        issues.append("processor_report.voice_selection.processed must be 1")
    if int(voice_selection.get("share_link_sent") or 0) != 1:
        issues.append("processor_report.voice_selection.share_link_sent must be 1")

    intake_summary = dict(receipt.get("intake_summary") or {})
    if intake_summary.get("status") != "waiting_voice_selection":
        issues.append("intake_summary.status must be waiting_voice_selection")
    if intake_summary.get("stage_next_action") != "choose_whatsapp_audiobook_voice_sample":
        issues.append("intake_summary.stage_next_action must be choose_whatsapp_audiobook_voice_sample")

    job_summary = dict(receipt.get("job_summary") or {})
    expected_job_summary = {
        "status": "audiobookshelf_imported",
        "voice_selection_status": "selected_by_user",
        "render_status": "rendered",
        "m4b_status": "m4b_ready",
        "audiobookshelf_import_status": "imported",
        "public_share_status": "public_share_ready",
    }
    for key, expected in expected_job_summary.items():
        if str(job_summary.get(key) or "") != expected:
            issues.append(f"job_summary.{key} must be {expected}")
    if int(job_summary.get("chapter_count") or 0) != 2:
        issues.append("job_summary.chapter_count must be 2")
    if int(job_summary.get("pending_voice_sample_count") or 0) != 0:
        issues.append("job_summary.pending_voice_sample_count must be 0")

    sanitized = dict(receipt.get("sanitized_receipt_summary") or {})
    if sanitized.get("status") != "audiobookshelf_imported":
        issues.append("sanitized_receipt_summary.status must be audiobookshelf_imported")
    if sanitized.get("player_scoped_reference_status") != "signed_reference_ready":
        issues.append("sanitized_receipt_summary.player_scoped_reference_status must be signed_reference_ready")
    if sanitized.get("public_share_status") != "public_share_ready":
        issues.append("sanitized_receipt_summary.public_share_status must be public_share_ready")
    if sanitized.get("public_share_whatsapp_delivery_status") != "sent":
        issues.append("sanitized_receipt_summary.public_share_whatsapp_delivery_status must be sent")
    if not bool(sanitized.get("m4b_output_ready")):
        issues.append("sanitized_receipt_summary.m4b_output_ready must be true")
    if not bool(sanitized.get("chapter_metadata_embedded")):
        issues.append("sanitized_receipt_summary.chapter_metadata_embedded must be true")
    if not bool(sanitized.get("public_share_whatsapp_message_id_present")):
        issues.append("sanitized_receipt_summary.public_share_whatsapp_message_id_present must be true")
    if not bool(sanitized.get("whatsapp_sender_bound")):
        issues.append("sanitized_receipt_summary.whatsapp_sender_bound must be true")
    if not bool(sanitized.get("whatsapp_session_bound")):
        issues.append("sanitized_receipt_summary.whatsapp_session_bound must be true")
    if not bool(sanitized.get("whatsapp_message_hash_present")):
        issues.append("sanitized_receipt_summary.whatsapp_message_hash_present must be true")
    if sanitized.get("whatsapp_voice_sample_delivery_status") != "sent":
        issues.append("sanitized_receipt_summary.whatsapp_voice_sample_delivery_status must be sent")

    player_probe = dict(receipt.get("player_probe_summary") or {})
    if player_probe.get("status") != "pass":
        issues.append("player_probe_summary.status must be pass")
    if player_probe.get("metadata_status") != "ready":
        issues.append("player_probe_summary.metadata_status must be ready")
    if not str(player_probe.get("content_type") or "").startswith("audio/"):
        issues.append("player_probe_summary.content_type must be audio/*")
    if not bool(player_probe.get("file_ready")):
        issues.append("player_probe_summary.file_ready must be true")
    if not str(player_probe.get("file_sha256") or "").strip():
        issues.append("player_probe_summary.file_sha256 must be present")
    if int(player_probe.get("audio_streams") or 0) < 1:
        issues.append("player_probe_summary.audio_streams must be >= 1")
    if float(player_probe.get("duration_seconds") or 0.0) <= 0:
        issues.append("player_probe_summary.duration_seconds must be > 0")
    if player_probe.get("raw_path_exposed") is not False:
        issues.append("player_probe_summary.raw_path_exposed must remain false")
    if player_probe.get("raw_token_exposed") is not False:
        issues.append("player_probe_summary.raw_token_exposed must remain false")

    player_http_probe = dict(receipt.get("player_http_probe_summary") or {})
    if player_http_probe.get("status") != "pass":
        issues.append("player_http_probe_summary.status must be pass")
    if int(player_http_probe.get("metadata_status_code") or 0) != 200:
        issues.append("player_http_probe_summary.metadata_status_code must be 200")
    if player_http_probe.get("metadata_status") != "ready":
        issues.append("player_http_probe_summary.metadata_status must be ready")
    if player_http_probe.get("metadata_cache_control") != "no-store":
        issues.append("player_http_probe_summary.metadata_cache_control must be no-store")
    if not bool(player_http_probe.get("metadata_download_url_present")):
        issues.append("player_http_probe_summary.metadata_download_url_present must be true")
    if bool(player_http_probe.get("metadata_vendor_token_exposed")):
        issues.append("player_http_probe_summary.metadata_vendor_token_exposed must remain false")
    if bool(player_http_probe.get("metadata_raw_library_path_exposed")):
        issues.append("player_http_probe_summary.metadata_raw_library_path_exposed must remain false")
    if int(player_http_probe.get("download_status_code") or 0) != 200:
        issues.append("player_http_probe_summary.download_status_code must be 200")
    if not str(player_http_probe.get("download_content_type") or "").startswith("audio/"):
        issues.append("player_http_probe_summary.download_content_type must be audio/*")
    if player_http_probe.get("download_cache_control") != "no-store":
        issues.append("player_http_probe_summary.download_cache_control must be no-store")
    if int(player_http_probe.get("download_bytes") or 0) <= 0:
        issues.append("player_http_probe_summary.download_bytes must be > 0")
    if player_http_probe.get("raw_path_exposed") is not False:
        issues.append("player_http_probe_summary.raw_path_exposed must remain false")
    if player_http_probe.get("raw_token_exposed") is not False:
        issues.append("player_http_probe_summary.raw_token_exposed must remain false")

    local_stage = dict(receipt.get("local_stage_receipt_summary") or {})
    intake_stage = dict(local_stage.get("intake") or {})
    delivery_stage = dict(local_stage.get("delivery") or {})
    if intake_stage.get("status") != "waiting_voice_choice":
        issues.append("local_stage_receipt_summary.intake.status must be waiting_voice_choice")
    if bool(intake_stage.get("live_delivery_claim_allowed")):
        issues.append("local_stage_receipt_summary.intake.live_delivery_claim_allowed must remain false")
    if intake_stage.get("next_action") != "choose_whatsapp_audiobook_voice_sample":
        issues.append("local_stage_receipt_summary.intake.next_action must be choose_whatsapp_audiobook_voice_sample")
    if dict(intake_stage.get("stage_counts") or {}) != {"waiting_voice_choice": 1}:
        issues.append("local_stage_receipt_summary.intake.stage_counts must be {waiting_voice_choice: 1}")
    if delivery_stage.get("status") != "blocked":
        issues.append("local_stage_receipt_summary.delivery.status must be blocked")
    if bool(delivery_stage.get("live_delivery_claim_allowed")):
        issues.append("local_stage_receipt_summary.delivery.live_delivery_claim_allowed must remain false")
    if delivery_stage.get("next_action") != "run_public_share_machine_playback_e2e_before_claiming_live_delivery":
        issues.append(
            "local_stage_receipt_summary.delivery.next_action must be run_public_share_machine_playback_e2e_before_claiming_live_delivery"
        )
    if dict(delivery_stage.get("stage_counts") or {}) != {"waiting_machine_playback_verification": 1}:
        issues.append(
            "local_stage_receipt_summary.delivery.stage_counts must be {waiting_machine_playback_verification: 1}"
        )

    privacy = dict(receipt.get("privacy") or {})
    expected_false = {
        "live_whatsapp_claim",
        "raw_epub_text_persisted",
        "raw_sender_ref_exposed",
        "raw_message_id_exposed",
        "callback_tokens_exposed",
        "public_share_token_exposed",
        "player_access_token_exposed",
        "audiobookshelf_raw_path_exposed",
        "provider_voice_ids_exposed",
        "provider_secret_exposed",
    }
    for key in expected_false:
        if privacy.get(key) is not False:
            issues.append(f"privacy.{key} must remain false")
    if privacy.get("local_temp_job_root_removed_after_run") is not True:
        issues.append("privacy.local_temp_job_root_removed_after_run must remain true")

    return issues


def main() -> int:
    import sys

    if any(flag in sys.argv[1:] for flag in ("--help", "-h")):
        print(
            "Usage:\n"
            "  python ea/scripts/verify_whatsapp_audiobook_local_intake_proof.py [options]\n\n"
            "Verify the WhatsApp audiobook local intake proof receipt."
        )
        return 0
    parser = argparse.ArgumentParser(description="Verify the WhatsApp audiobook local intake proof receipt.")
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    issues = verify(args.receipt)
    payload = {"status": "pass" if not issues else "blocked", "issues": issues}
    if args.pretty:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
