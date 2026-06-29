from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
import hashlib


def _load_script(name: str) -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "ea" / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _job_receipt(
    *,
    job_id: str = "job-live-1",
    public_share_status: str = "public_share_ready",
    telegram_delivery_status: str = "sent",
    telegram_message_present: bool = True,
    playback_accepted: bool = False,
    status: str = "audiobookshelf_imported",
    render_status: str = "already_rendered",
    voice_selected_by_user: bool = False,
    replacement_choice_pending: bool = False,
    origin_edition_delivery: bool = False,
) -> dict[str, object]:
    voice_selection = (
        {
            "status": "selected_by_user",
            "last_action": {"status": "selected_by_user"},
            "selected": {
                "default": False,
                "label": "Davis (Express)",
                "voice_id_sha256": "u" * 64,
            },
        }
        if voice_selected_by_user
        else {
            "status": "waiting_user_choice" if replacement_choice_pending else "single_configured_voice",
            "reason": "selected_voice_provider_balance_blocked" if replacement_choice_pending else "",
            "replacement_candidate_keys": ["piper-local"] if replacement_choice_pending else [],
            "selected": {
                "default": True,
                "label": "Default German Voice",
                "voice_id_sha256": "v" * 64,
            },
        }
    )
    receipt = {
        "contract_name": "ea.telegram_epub_audiobook_job_receipt.v1",
        "status": status,
        "observed_at": "2026-06-19T21:00:00Z",
        "job_id": job_id,
        "metadata": {"title": "Test Book", "author": "A. Writer", "language": "en-US"},
        "source": {
            "kind": "epub",
            "priority_for_resume": False,
            "rights_basis": "user_supplied",
            "source_filename": "book.epub",
            "source_sha256": "s" * 64,
            "source_url_sha256": "",
        },
        "render": {
            "status": render_status,
            "chapter_index": 11 if status != "audiobookshelf_imported" else 0,
            "segment_index": 4 if status != "audiobookshelf_imported" else 0,
            "segment_count": 13 if status != "audiobookshelf_imported" else 0,
            "external_tts_blocker_code": "provider_balance_or_prebuilt_characters"
            if status != "audiobookshelf_imported"
            else "",
            "external_tts_blocker_retryable": status != "audiobookshelf_imported",
            "external_tts_blocker_reason_sha256": "r" * 64 if status != "audiobookshelf_imported" else "",
            "voice_selection": voice_selection,
        },
        "scheduler_resume": {
            "next_action": "unmixr_tts_no_audio_url:Insufficient API balance (prebuilt characters)"
            if status != "audiobookshelf_imported"
            else "done",
            "retry_after": "2026-06-20T15:07:55Z" if status != "audiobookshelf_imported" else "",
            "external_tts_blocker_retryable": status != "audiobookshelf_imported",
            "external_tts_blocker_code": "provider_balance_or_prebuilt_characters"
            if status != "audiobookshelf_imported"
            else "",
        },
        "assembly": {
            "status": "m4b_ready",
            "output_file_ready": True,
            "output_file_sha256": "a" * 64,
            "chapter_metadata_embedded": True,
        },
        "audiobookshelf_import": {
            "status": "imported",
            "target_file_ready": True,
            "target_file_sha256": "b" * 64,
            "target_storage_kind": "pcloud",
            "player_scoped_reference_status": "signed_reference_ready",
            "public_share_status": public_share_status,
            "public_share_url": "https://abs.example.com/share/ea-test-book",
            "public_share_slug_sha256": "c" * 64,
            "public_share_token_exposed": False,
            "public_share_raw_library_path_exposed": False,
            "public_share_telegram_followup_pending": False,
            "public_share_telegram_delivery_status": telegram_delivery_status,
            "public_share_telegram_notified_at": "2026-06-19T21:05:00Z",
            "public_share_telegram_message_id_present": telegram_message_present,
            "public_share_telegram_message_id_sha256": "d" * 64 if telegram_message_present else "",
            "public_share_telegram_callback_tokens_exposed": False,
            "public_share_telegram_audiobookshelf_token_exposed": False,
            "public_share_playback_e2e_status": "pass",
            "public_share_playback_e2e_browser": "chromium_playwright",
            "public_share_playback_e2e_checked_at": "2026-06-19T21:07:00Z",
            "public_share_playback_e2e_track_response_status": 206,
            "public_share_playback_e2e_track_content_type": "audio/mp4",
            "public_share_playback_e2e_duration_seconds": 3600.5,
            "public_share_playback_e2e_current_time_after_play_seconds": 4.25,
            "public_share_playback_e2e_media_error_present": False,
        },
        "storage": {
            "job_storage_kind": "pcloud",
            "audiobookshelf_storage_kind": "pcloud",
            "manifest_sha256": "e" * 64,
        },
        "telegram": {
            "chat_bound": True,
            "message_bound": True,
            "voice_sample_callback_tokens_exposed": False,
        },
        "playback_acceptance": {
            "contract_name": "ea.telegram_epub_audiobook_playback_acceptance.v1",
            "status": "accepted" if playback_accepted else "not_recorded",
            "accepted": playback_accepted,
            "source": "telegram" if playback_accepted else "",
            "recorded_at": "2026-06-19T21:15:00Z" if playback_accepted else "",
            "feedback_sha256": "f" * 64 if playback_accepted else "",
            "message_id_sha256": "g" * 64 if playback_accepted else "",
            "public_share_url_sha256": "h" * 64 if playback_accepted else "",
            "audiobookshelf_target_file_sha256": "b" * 64 if playback_accepted else "",
            "telegram_public_share_message_id_sha256": "d" * 64 if playback_accepted else "",
            "raw_feedback_exposed": False,
            "raw_message_id_exposed": False,
        },
        "privacy": {
            "raw_book_text_in_receipt": False,
            "telegram_chat_id_exposed": False,
            "telegram_message_id_exposed": False,
            "telegram_token_exposed": False,
            "provider_secret_exposed": False,
            "audiobookshelf_token_exposed": False,
            "audiobookshelf_raw_path_exposed": False,
            "private_job_path_exposed": False,
        },
    }
    if origin_edition_delivery:
        receipt["origin_edition_delivery"] = {
            "status": "sent",
            "project_id": "origin-live-gold",
            "origin_namespace": "origin.chummer.run/Varga/Mira/Kestrel",
            "telegram_delivery_status": "sent",
            "telegram_message_id_present": True,
            "links": {
                "read": "https://chummer.run/account/work/origin-dossiers/origin-live-gold/read",
                "listen": "https://chummer.run/account/work/origin-dossiers/origin-live-gold/listen",
                "watch": "https://chummer.run/account/work/origin-dossiers/origin-live-gold/video",
                "open_in_chummer": "https://chummer.run/account/work/origin-dossiers/origin-live-gold",
            },
        }
    return receipt


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def test_live_telegram_audiobook_delivery_receipt_passes_with_redacted_job_receipt(tmp_path: Path) -> None:
    module = _load_script("materialize_telegram_audiobook_live_delivery_receipt")

    receipt = module.build_receipt(
        output_path=tmp_path / "telegram_audiobook_live_delivery.generated.json",
        job_receipts=[_job_receipt()],
        generated_at="2026-06-19T21:10:00Z",
    )

    assert receipt["contract_name"] == "ea.telegram_audiobook_live_delivery_receipt.v1"
    assert receipt["status"] == "pass"
    assert receipt["live_delivery_claim_allowed"] is True
    assert receipt["machine_playback_e2e_verified"] is True
    assert receipt["real_user_playback_acceptance_verified"] is False
    assert receipt["goal_completion_claim_allowed"] is False
    selected = receipt["selected_delivery"]
    assert selected["public_share_url_present"] is True
    assert selected["public_share_host"] == "abs.example.com"
    assert selected["telegram_delivery_status"] == "sent"
    assert selected["telegram_delivery_message_id_present"] is True
    assert selected["machine_playback_e2e_verified"] is True
    assert selected["machine_playback_e2e_status"] == "pass"
    assert selected["machine_playback_e2e_track_response_status"] == 206
    assert selected["machine_playback_e2e_track_content_type"] == "audio/mp4"
    assert selected["machine_playback_e2e_current_time_after_play_seconds"] > 0
    assert selected["title_present"] is True
    assert selected["title_sha256"]
    serialized = json.dumps(receipt, sort_keys=True)
    assert "Test Book" not in serialized
    assert "A. Writer" not in serialized
    assert "https://abs.example.com/share/ea-test-book" not in serialized
    assert "/mnt/pcloud" not in serialized
    assert "secret-token" not in serialized
    assert receipt["privacy"]["machine_playback_e2e_url_redacted"] is True


def test_live_telegram_audiobook_delivery_receipt_surfaces_playback_acceptance(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_telegram_audiobook_live_delivery_receipt")

    receipt = module.build_receipt(
        output_path=tmp_path / "accepted.generated.json",
        job_receipts=[_job_receipt(playback_accepted=True)],
        generated_at="2026-06-19T21:20:00Z",
    )

    assert receipt["status"] == "pass"
    assert receipt["live_delivery_claim_allowed"] is True
    assert receipt["machine_playback_e2e_verified"] is True
    assert receipt["real_user_playback_acceptance_verified"] is True
    assert receipt["goal_completion_claim_allowed"] is False
    selected = receipt["selected_delivery"]
    assert selected["playback_acceptance_verified"] is True
    assert selected["playback_acceptance_status"] == "accepted"
    assert selected["playback_acceptance_source"] == "telegram"
    assert selected["playback_acceptance_feedback_sha256"] == "f" * 64
    assert receipt["privacy"]["playback_acceptance_feedback_hashed"] is True


def test_live_telegram_audiobook_delivery_receipt_surfaces_origin_link_bundle_without_raw_urls(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_telegram_audiobook_live_delivery_receipt")

    receipt = module.build_receipt(
        output_path=tmp_path / "origin-links.generated.json",
        job_receipts=[_job_receipt(origin_edition_delivery=True)],
        generated_at="2026-06-19T21:20:00Z",
    )

    assert receipt["status"] == "pass"
    bundle = receipt["selected_delivery"]["origin_edition_link_bundle"]
    assert bundle["status"] == "sent"
    assert bundle["project_id"] == "origin-live-gold"
    assert bundle["telegram_delivery_status"] == "sent"
    assert bundle["telegram_message_id_present"] is True
    assert bundle["all_required_links_present"] is True
    assert bundle["raw_urls_exposed"] is False
    assert bundle["read_url_sha256"] == _sha256("https://chummer.run/account/work/origin-dossiers/origin-live-gold/read")
    assert bundle["listen_url_sha256"] == _sha256("https://chummer.run/account/work/origin-dossiers/origin-live-gold/listen")
    assert bundle["watch_url_sha256"] == _sha256("https://chummer.run/account/work/origin-dossiers/origin-live-gold/video")
    assert bundle["open_in_chummer_url_sha256"] == _sha256("https://chummer.run/account/work/origin-dossiers/origin-live-gold")
    serialized = json.dumps(receipt, sort_keys=True)
    assert "https://chummer.run/account/work/origin-dossiers/origin-live-gold/read" not in serialized
    assert "https://chummer.run/account/work/origin-dossiers/origin-live-gold/listen" not in serialized
    assert "https://chummer.run/account/work/origin-dossiers/origin-live-gold/video" not in serialized


def test_live_telegram_audiobook_delivery_receipt_blocks_default_voice_when_user_selected_job_pending(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_telegram_audiobook_live_delivery_receipt")

    receipt = module.build_receipt(
        output_path=tmp_path / "wrong-voice.generated.json",
        job_receipts=[
            _job_receipt(job_id="older-default-voice-job"),
            _job_receipt(
                job_id="newer-selected-voice-job",
                status="blocked_external_tts",
                render_status="blocked",
                public_share_status="",
                telegram_delivery_status="",
                telegram_message_present=False,
                voice_selected_by_user=True,
            ),
        ],
        generated_at="2026-06-20T08:00:00Z",
    )

    assert receipt["status"] == "blocked"
    assert receipt["live_delivery_claim_allowed"] is False
    assert "user_selected_voice_delivery_not_ready" in receipt["failed_codes"]
    assert receipt["next_action"] == "finish_user_selected_voice_audiobook_before_sending_public_share_link"
    assert receipt["pending_user_selected_voice_job_count"] == 1
    pending = receipt["pending_user_selected_voice_jobs"][0]
    assert pending["render_chapter_index"] == 11
    assert pending["render_segment_index"] == 4
    assert pending["render_segment_count"] == 13
    assert pending["external_tts_blocker_retryable"] is True
    assert pending["external_tts_blocker_code"] == "provider_balance_or_prebuilt_characters"
    assert pending["external_tts_blocker_reason_sha256"] == "r" * 64
    assert pending["scheduler_retry_after"] == "2026-06-20T15:07:55Z"
    selected = receipt["selected_delivery"]
    assert selected["voice_selected_by_user"] is False
    assert selected["voice_selected_default"] is True
    serialized = json.dumps(receipt, sort_keys=True)
    assert "Davis (Express)" not in serialized
    assert "Default German Voice" not in serialized
    assert "Insufficient API balance" not in serialized


def test_live_telegram_audiobook_delivery_receipt_ignores_duplicate_pending_after_user_selected_delivery(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_telegram_audiobook_live_delivery_receipt")

    receipt = module.build_receipt(
        output_path=tmp_path / "selected-delivery-duplicates.generated.json",
        job_receipts=[
            _job_receipt(job_id="selected-voice-delivered", voice_selected_by_user=True),
            _job_receipt(
                job_id="duplicate-audition",
                status="waiting_voice_selection",
                render_status="waiting_voice_selection",
                public_share_status="",
                telegram_delivery_status="",
                telegram_message_present=False,
                replacement_choice_pending=True,
            ),
        ],
        generated_at="2026-06-21T07:55:00Z",
    )

    assert receipt["status"] == "pass"
    assert receipt["live_delivery_claim_allowed"] is True
    assert receipt["pending_user_selected_voice_job_count"] == 0
    assert "user_selected_voice_delivery_not_ready" not in receipt["failed_codes"]
    assert "explicit_replacement_voice_choice_pending" not in receipt["failed_codes"]
    selected = receipt["selected_delivery"]
    assert selected["voice_selected_by_user"] is True
    assert selected["voice_selected_default"] is False


def test_live_telegram_audiobook_delivery_receipt_ignores_superseded_replacement_when_selected_needs_render(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_telegram_audiobook_live_delivery_receipt")
    selected = _job_receipt(job_id="selected-needs-render", voice_selected_by_user=True)
    selected["assembly"]["output_file_ready"] = False
    selected["audiobookshelf_import"]["target_file_ready"] = False
    selected["audiobookshelf_import"]["target_file_sha256"] = ""
    selected["audiobookshelf_import"]["public_share_playback_e2e_status"] = ""
    selected["audiobookshelf_import"]["public_share_playback_e2e_track_response_status"] = 0
    selected["audiobookshelf_import"]["public_share_playback_e2e_track_content_type"] = ""
    selected["audiobookshelf_import"]["public_share_playback_e2e_duration_seconds"] = 0
    selected["audiobookshelf_import"]["public_share_playback_e2e_current_time_after_play_seconds"] = 0
    superseded = _job_receipt(
        job_id="old-superseded-replacement",
        status="superseded_duplicate",
        render_status="waiting_voice_selection",
        public_share_status="",
        telegram_delivery_status="",
        telegram_message_present=False,
        replacement_choice_pending=True,
    )

    receipt = module.build_receipt(
        output_path=tmp_path / "selected-render-blocker.generated.json",
        job_receipts=[selected, superseded],
        generated_at="2026-06-21T08:05:00Z",
    )

    assert receipt["status"] == "blocked"
    assert receipt["live_delivery_claim_allowed"] is False
    assert receipt["pending_user_selected_voice_job_count"] == 1
    assert receipt["pending_user_selected_voice_jobs"][0]["replacement_choice_pending"] is False
    assert "explicit_replacement_voice_choice_pending" not in receipt["failed_codes"]
    assert "m4b_output_file_not_ready" in receipt["failed_codes"]
    assert "machine_playback_e2e_not_verified" in receipt["failed_codes"]
    assert receipt["next_action"] == "resume_or_rebuild_telegram_audiobook_render_before_public_share_delivery"


def test_live_telegram_audiobook_delivery_receipt_does_not_mark_delivery_only_gap_as_voice_pending(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_telegram_audiobook_live_delivery_receipt")

    receipt = module.build_receipt(
        output_path=tmp_path / "selected-delivery-only.generated.json",
        job_receipts=[
            _job_receipt(
                job_id="selected-needs-telegram-send",
                telegram_delivery_status="",
                telegram_message_present=False,
                voice_selected_by_user=True,
            )
        ],
        generated_at="2026-06-21T08:10:00Z",
    )

    assert receipt["status"] == "blocked"
    assert receipt["live_delivery_claim_allowed"] is False
    assert receipt["pending_user_selected_voice_job_count"] == 0
    assert "user_selected_voice_delivery_not_ready" not in receipt["failed_codes"]
    assert "m4b_output_file_not_ready" not in receipt["failed_codes"]
    assert "player_scoped_reference_not_ready" not in receipt["failed_codes"]
    assert "telegram_public_share_delivery_not_sent" in receipt["failed_codes"]
    assert receipt["next_action"] == "wait_for_scheduler_to_send_audiobookshelf_public_share_link_or_fix_telegram_delivery"


def test_live_telegram_audiobook_delivery_receipt_surfaces_initial_voice_choice(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_telegram_audiobook_live_delivery_receipt")
    pending = _job_receipt(
        job_id="initial-voice-choice",
        status="waiting_voice_selection",
        render_status="waiting_voice_selection",
        public_share_status="",
        telegram_delivery_status="",
        telegram_message_present=False,
        replacement_choice_pending=True,
    )
    pending["render"]["voice_selection"]["reason"] = ""

    receipt = module.build_receipt(
        output_path=tmp_path / "initial-voice-choice.generated.json",
        job_receipts=[pending],
        generated_at="2026-06-21T08:12:00Z",
    )

    assert receipt["status"] == "blocked"
    assert receipt["live_delivery_claim_allowed"] is False
    assert receipt["pending_user_selected_voice_job_count"] == 1
    assert receipt["pending_user_selected_voice_jobs"][0]["voice_choice_pending"] is True
    assert receipt["pending_user_selected_voice_jobs"][0]["voice_choice_candidate_count"] == 1
    assert receipt["pending_user_selected_voice_jobs"][0]["replacement_choice_pending"] is False
    assert "audiobook_voice_choice_pending" in receipt["failed_codes"]
    assert "explicit_replacement_voice_choice_pending" not in receipt["failed_codes"]
    assert receipt["next_action"] == "choose_one_telegram_audiobook_voice_sample"


def test_live_telegram_audiobook_delivery_receipt_surfaces_explicit_replacement_choice_pending(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_telegram_audiobook_live_delivery_receipt")

    receipt = module.build_receipt(
        output_path=tmp_path / "replacement-choice.generated.json",
        job_receipts=[
            _job_receipt(job_id="older-default-voice-job"),
            _job_receipt(
                job_id="replacement-choice-job",
                status="waiting_voice_selection",
                render_status="waiting_voice_selection",
                public_share_status="",
                telegram_delivery_status="",
                telegram_message_present=False,
                replacement_choice_pending=True,
            ),
        ],
        generated_at="2026-06-20T11:20:00Z",
    )

    assert receipt["status"] == "blocked"
    assert receipt["live_delivery_claim_allowed"] is False
    assert "user_selected_voice_delivery_not_ready" in receipt["failed_codes"]
    assert "explicit_replacement_voice_choice_pending" in receipt["failed_codes"]
    assert receipt["next_action"] == "choose_explicit_replacement_voice_or_restore_selected_provider"
    pending = receipt["pending_user_selected_voice_jobs"][0]
    assert pending["voice_selection_status"] == "waiting_user_choice"
    assert pending["voice_selection_reason"] == "selected_voice_provider_balance_blocked"
    assert pending["replacement_choice_pending"] is True
    assert pending["replacement_candidate_count"] == 1
    serialized = json.dumps(receipt, sort_keys=True)
    assert "Piper German Thorsten high" not in serialized
    assert "piper-local" not in serialized


def test_live_telegram_audiobook_delivery_receipt_surfaces_replacement_choice_without_prior_delivery(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_telegram_audiobook_live_delivery_receipt")

    receipt = module.build_receipt(
        output_path=tmp_path / "replacement-only.generated.json",
        job_receipts=[
            _job_receipt(
                job_id="replacement-choice-job",
                status="waiting_voice_selection",
                render_status="waiting_voice_selection",
                public_share_status="",
                telegram_delivery_status="",
                telegram_message_present=False,
                replacement_choice_pending=True,
            )
        ],
        generated_at="2026-06-20T11:25:00Z",
    )

    assert receipt["status"] == "blocked"
    assert receipt["live_delivery_claim_allowed"] is False
    assert "valid_live_audiobook_delivery_missing" in receipt["failed_codes"]
    assert "explicit_replacement_voice_choice_pending" in receipt["failed_codes"]
    assert receipt["next_action"] == "choose_explicit_replacement_voice_or_restore_selected_provider"
    assert receipt["pending_user_selected_voice_job_count"] == 1
    assert receipt["pending_user_selected_voice_jobs"][0]["replacement_choice_pending"] is True


def test_live_telegram_audiobook_delivery_receipt_blocks_missing_share_or_telegram_delivery(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_telegram_audiobook_live_delivery_receipt")

    receipt = module.build_receipt(
        output_path=tmp_path / "blocked.generated.json",
        job_receipts=[
            _job_receipt(public_share_status="waiting_for_audiobookshelf_scan"),
            _job_receipt(telegram_delivery_status="failed", telegram_message_present=False),
        ],
        generated_at="2026-06-19T21:10:00Z",
    )

    assert receipt["status"] == "blocked"
    assert receipt["live_delivery_claim_allowed"] is False
    assert "valid_live_audiobook_delivery_missing" in receipt["failed_codes"]
    assert "audiobookshelf_public_share_not_ready" in receipt["failed_codes"]
    assert "telegram_public_share_delivery_not_sent" in receipt["failed_codes"]
    assert "telegram_public_share_message_id_missing" in receipt["failed_codes"]
    assert receipt["next_action"] in {
        "wait_for_scheduler_to_send_audiobookshelf_public_share_link_or_fix_telegram_delivery",
        "wait_for_audiobookshelf_scan_then_rerun_share_followup",
        "inspect_failed_audiobook_delivery_candidates",
    }


def test_live_telegram_audiobook_delivery_receipt_ignores_origin_dossier_jobs(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_telegram_audiobook_live_delivery_receipt")
    origin = _job_receipt(job_id="origin-dossier-delivered")
    origin["source"]["kind"] = "origin_dossier_story"
    origin["source"]["source_filename"] = "Kestrel - Origin Story.txt"
    blocked_epub = _job_receipt(
        job_id="telegram-epub-needs-share",
        public_share_status="waiting_for_audiobookshelf_scan",
        telegram_delivery_status="",
        telegram_message_present=False,
    )

    receipt = module.build_receipt(
        output_path=tmp_path / "origin-filtered.generated.json",
        job_receipts=[origin, blocked_epub],
        generated_at="2026-06-29T19:45:00Z",
    )

    assert receipt["status"] == "blocked"
    assert receipt["live_delivery_claim_allowed"] is False
    assert receipt["candidate_count"] == 1
    assert receipt["ignored_non_telegram_audiobook_candidate_count"] == 1
    assert receipt["ignored_non_telegram_audiobook_source_kinds"] == ["origin_dossier_story"]
    assert receipt["selected_delivery"]["job_id_sha256"] == _sha256("telegram-epub-needs-share")
    assert receipt["selected_delivery"]["source_kind"] == "epub"
    assert "audiobookshelf_public_share_not_ready" in receipt["failed_codes"]


def test_scan_job_receipts_uses_pipeline_discovery_manifests(monkeypatch, tmp_path: Path) -> None:
    module = _load_script("materialize_telegram_audiobook_live_delivery_receipt")
    from app.services import audiobook_epub_pipeline as pipeline

    first = tmp_path / "first" / "job-a"
    second = tmp_path / "second" / "job-b"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    (first / "job.json").write_text("{}", encoding="utf-8")
    (second / "job.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        pipeline,
        "iter_audiobook_job_manifests",
        lambda *, newest_first=False: (second / "job.json", first / "job.json"),
    )
    monkeypatch.setattr(pipeline, "audiobook_job_discovery_roots", lambda: (tmp_path / "first", tmp_path / "second"))
    monkeypatch.setattr(pipeline, "build_audiobook_job_receipt", lambda *, job_dir: _job_receipt(job_id=job_dir.name))

    receipts, errors = module._scan_job_receipts(10)

    assert errors == []
    assert [receipt["job_id"] for receipt in receipts] == ["job-b", "job-a"]


def test_live_telegram_audiobook_delivery_receipt_cli_accepts_sanitized_job_receipts_json(
    tmp_path: Path,
) -> None:
    script = Path(__file__).resolve().parents[1] / "ea" / "scripts" / "materialize_telegram_audiobook_live_delivery_receipt.py"
    source = tmp_path / "job-receipts.json"
    output = tmp_path / "live.generated.json"
    source.write_text(json.dumps({"receipts": [_job_receipt()]}) + "\n", encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--job-receipts-json",
            str(source),
            "--output",
            str(output),
            "--require-pass",
        ],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr + proc.stdout
    summary = json.loads(proc.stdout)
    assert summary["status"] == "pass"
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["status"] == "pass"
