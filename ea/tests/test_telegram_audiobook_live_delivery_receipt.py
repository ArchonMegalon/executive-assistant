from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "materialize_telegram_audiobook_live_delivery_receipt.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("materialize_telegram_audiobook_live_delivery_receipt", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _job_receipt(
    *,
    job_id: str,
    source_kind: str = "epub",
    source_filename: str = "book.epub",
    source_url_sha256: str = "",
    telegram_chat_bound: bool = False,
    telegram_message_bound: bool = False,
    whatsapp_public_share_delivery_status: str = "",
    public_share_telegram_delivery_status: str = "",
    public_share_telegram_message_id_present: bool = False,
    status: str = "audiobookshelf_imported",
    playback_status: str = "accepted",
    playback_accepted: bool = True,
) -> dict[str, object]:
    return {
        "job_id": job_id,
        "status": status,
        "source": {
            "kind": source_kind,
            "source_filename": source_filename,
            "source_url_sha256": source_url_sha256,
        },
        "metadata": {
            "title": f"Title for {job_id}",
            "author": "EA QA",
        },
        "assembly": {
            "output_file_ready": True,
            "chapter_metadata_embedded": True,
        },
        "telegram": {
            "chat_bound": telegram_chat_bound,
            "message_bound": telegram_message_bound,
        },
        "whatsapp": {
            "public_share_delivery": {
                "status": whatsapp_public_share_delivery_status,
            }
        }
        if whatsapp_public_share_delivery_status
        else {},
        "audiobookshelf_import": {
            "status": "imported",
            "target_file_ready": True,
            "target_file_sha256": "target-sha",
            "player_scoped_reference_status": "signed_reference_ready",
            "public_share_status": "public_share_ready",
            "public_share_url": "https://audiobookshelf.girschele.com/audiobookshelf/share/test",
            "public_share_telegram_delivery_status": public_share_telegram_delivery_status,
            "public_share_telegram_message_id_present": public_share_telegram_message_id_present,
            "public_share_playback_e2e_status": "pass",
            "public_share_playback_e2e_track_response_status": 206,
            "public_share_playback_e2e_track_content_type": "audio/mp4",
            "public_share_playback_e2e_current_time_after_play_seconds": 2.1,
            "public_share_playback_e2e_duration_seconds": 30.0,
            "public_share_playback_e2e_media_error_present": False,
        },
        "playback_acceptance": {
            "status": playback_status,
            "accepted": playback_accepted,
        },
        "privacy": {
            "telegram_chat_id_exposed": False,
            "telegram_message_id_exposed": False,
            "telegram_token_exposed": False,
            "provider_secret_exposed": False,
            "audiobookshelf_token_exposed": False,
            "audiobookshelf_raw_path_exposed": False,
            "private_job_path_exposed": False,
        },
        "origin_edition_delivery": {},
        "audio_publication_gate": {"chapters": 1},
    }


def test_build_receipt_excludes_whatsapp_ingress_epub_jobs_from_telegram_scope(tmp_path: Path) -> None:
    module = _load_module()
    telegram_job = _job_receipt(
        job_id="telegram-job",
        source_kind="epub",
        source_url_sha256="telegram-source-url",
        telegram_chat_bound=True,
        telegram_message_bound=True,
        status="blocked_external_tts",
        playback_status="not_recorded",
        playback_accepted=False,
    )
    whatsapp_job = _job_receipt(
        job_id="whatsapp-job",
        source_kind="epub",
        whatsapp_public_share_delivery_status="sent",
        playback_status="rejected",
        playback_accepted=False,
    )

    receipt = module.build_receipt(
        output_path=tmp_path / "telegram_live_delivery.json",
        job_receipts=[whatsapp_job, telegram_job],
        generated_at="2026-06-30T00:00:00Z",
        observation_source="test",
    )

    assert receipt["candidate_count"] == 1
    assert receipt["selected_delivery"]["job_id_sha256"] == hashlib.sha256(b"telegram-job").hexdigest()
    assert receipt["ignored_non_telegram_audiobook_candidate_count"] == 1


def test_build_receipt_keeps_explicit_telegram_source_kind_in_scope_without_bound_chat(tmp_path: Path) -> None:
    module = _load_module()
    receipt = module.build_receipt(
        output_path=tmp_path / "telegram_live_delivery_explicit.json",
        job_receipts=[
            _job_receipt(
                job_id="explicit-telegram-kind",
                source_kind="telegram_epub",
                public_share_telegram_delivery_status="sent",
                public_share_telegram_message_id_present=True,
            )
        ],
        generated_at="2026-06-30T00:00:00Z",
        observation_source="test",
    )

    assert receipt["candidate_count"] == 1
    assert receipt["live_delivery_claim_allowed"] is True
    assert receipt["status"] == "pass"
