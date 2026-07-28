from __future__ import annotations

import importlib.util
import json
import hmac
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
import hashlib
import pytest


HUMAN_LISTENED_CANARY_CONTRACT_NAME = "ea.audiobook_human_listened_canary_acceptance.v1"
PERCEPTUAL_ATTESTATION_CONTRACT_NAME = "ea.audiobook_perceptual_attestation.v1"
PERCEPTUAL_ATTESTATION_CHECKS = (
    "no_clipped_starts_or_ends",
    "no_abrupt_level_reset",
    "natural_paragraph_and_scene_timing",
    "distinct_dialogue_voice",
    "stable_speaker_identity",
    "correct_words",
    "useful_chapter_navigation",
)
TEST_CANARY_HMAC_KEY = "test-canary-hmac-key"


@pytest.fixture(autouse=True)
def _canary_hmac_key(monkeypatch) -> None:
    monkeypatch.setenv("EA_AUDIOBOOK_CANARY_RECEIPT_HMAC_KEY", TEST_CANARY_HMAC_KEY)


def _acceptance_sha256(payload: dict[str, object]) -> str:
    binding = {
        key: payload.get(key)
        for key in (
            "contract_name",
            "status",
            "accepted",
            "listened",
            "canary_binding_status",
            "binding_issues",
            "channel",
            "source",
            "recorded_at",
            "artifact_sha256",
            "source_sha256",
            "source_aggregate_sha256",
            "narration_plan_sha256",
            "render_signature_sha256",
            "cast_map_sha256",
            "mastering_signature_set_sha256",
            "cinematic_timeline_sha256",
            "publication_gate_sha256",
            "channel_public_share_message_id_sha256",
            "public_share_url_sha256",
            "message_id_sha256",
            "feedback_sha256",
            "perceptual_attestation",
            "listener_reference_sha256",
            "language",
            "dialogue_turn_count",
            "expected_chapter_count",
            "actual_chapter_count",
            "raw_feedback_exposed",
            "raw_message_id_exposed",
            "raw_listener_reference_exposed",
        )
    }
    return hashlib.sha256(
        json.dumps(binding, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _perceptual_attestation(channel: str) -> dict[str, object]:
    checks = {key: True for key in PERCEPTUAL_ATTESTATION_CHECKS}
    canonical = {
        "contract_name": PERCEPTUAL_ATTESTATION_CONTRACT_NAME,
        "version": 1,
        "channel": channel,
        "checks": checks,
        "all_checks_attested": True,
    }
    return {
        "contract_name": PERCEPTUAL_ATTESTATION_CONTRACT_NAME,
        "version": 1,
        "checks": checks,
        "all_checks_attested": True,
        "channel_feedback_bound": True,
        "attestation_sha256": hashlib.sha256(
            json.dumps(
                canonical,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "raw_values_exposed": False,
    }


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
    voice_samples_sent: bool = True,
    origin_edition_delivery: bool = False,
) -> dict[str, object]:
    artifact_sha256 = "8" * 64
    source_sha256 = "1" * 64
    plan_sha256 = "2" * 64
    render_signature = "4" * 64
    cast_sha256 = "5" * 64
    message_sha256 = "9" * 64
    public_share_url = "https://abs.example.com/share/ea-test-book"
    voice_selection = (
        {
            "status": "selected_by_user",
            "last_action": {"status": "selected_by_user"},
            "selected": {
                "default": False,
                "label": "Davis (Express)",
                "voice_id_sha256": "d" * 64,
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
                "voice_id_sha256": "c" * 64,
            },
        }
    )
    playback_acceptance: dict[str, object] = {
        "status": "not_recorded",
        "accepted": False,
        "listened": False,
    }
    if playback_accepted:
        playback_acceptance = {
            "contract_name": HUMAN_LISTENED_CANARY_CONTRACT_NAME,
            "status": "listened_canary_accepted",
            "accepted": True,
            "listened": True,
            "canary_binding_status": "complete",
            "binding_issues": [],
            "channel": "telegram",
            "source": "telegram_button",
            "recorded_at": "2026-06-19T21:15:00Z",
            "artifact_sha256": artifact_sha256,
            "source_sha256": source_sha256,
            "source_aggregate_sha256": "3" * 64,
            "narration_plan_sha256": plan_sha256,
            "render_signature_sha256": render_signature,
            "cast_map_sha256": cast_sha256,
            "mastering_signature_set_sha256": "7" * 64,
            "cinematic_timeline_sha256": "",
            "publication_gate_sha256": "e" * 64,
            "channel_public_share_message_id_sha256": message_sha256,
            "public_share_url_sha256": _sha256(public_share_url),
            "message_id_sha256": "f" * 64,
            "feedback_sha256": "a" * 64,
            "perceptual_attestation": _perceptual_attestation("telegram"),
            "listener_reference_sha256": "b" * 64,
            "language": "en-US",
            "dialogue_turn_count": 2,
            "expected_chapter_count": 1,
            "actual_chapter_count": 1,
            "raw_feedback_exposed": False,
            "raw_message_id_exposed": False,
            "raw_listener_reference_exposed": False,
        }
        playback_acceptance["receipt_sha256"] = _acceptance_sha256(playback_acceptance)
        playback_acceptance["receipt_hmac_sha256"] = hmac.new(
            TEST_CANARY_HMAC_KEY.encode("utf-8"),
            str(playback_acceptance["receipt_sha256"]).encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
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
            "source_sha256": source_sha256,
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
            "narration_plan": {
                "contract_name": "ea.audiobook_narration_plan.v5",
                "status": "ready",
                "source_coverage": "complete",
                "coverage_complete": True,
                "source_integrity_verified": True,
                "chapter_count": 1,
                "dialogue_span_count": 2,
                "plan_sha256": plan_sha256,
                "source_aggregate_sha256": "3" * 64,
                "render_signature": render_signature,
            },
            "speaker_cast": {
                "status": "ready",
                "cast_map_sha256": cast_sha256,
                "distinct_dialogue_voice_count": 2,
                "narrator_voice_excluded": True,
                "raw_voice_ids_exposed": False,
            },
            "mastering": {
                "status": "mastered",
                "final_track_mode": "chapter_masters",
                "contract_sha256": "6" * 64,
                "signature_set_sha256": "7" * 64,
                "expected_final_track_count": 1,
                "final_track_ready_count": 1,
                "final_track_mastered_this_run_count": 1,
                "signature_published_or_verified_count": 1,
                "segment_mastering": False,
                "final_audio_quality": [{"chapter_index": 1, "status": "pass"}],
            },
            "audio_quality": {
                "status": "pass",
                "checked_files": 1,
                "passed_files": 1,
                "failed_files": 0,
            },
        },
        "totals": {"chapter_count": 1},
        "chapters": [{"index": 1}],
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
            "output_file_sha256": artifact_sha256,
            "chapter_metadata_embedded": True,
            "expected_chapter_count": 1,
            "actual_chapter_count": 1,
            "chapter_count_matches": True,
        },
        "audiobookshelf_import": {
            "status": "imported",
            "target_file_ready": True,
            "target_file_sha256": artifact_sha256,
            "target_storage_kind": "pcloud",
            "player_scoped_reference_status": "signed_reference_ready",
            "public_share_status": public_share_status,
            "public_share_url": public_share_url,
            "public_share_slug_sha256": "c" * 64,
            "public_share_token_exposed": False,
            "public_share_raw_library_path_exposed": False,
            "public_share_telegram_followup_pending": False,
            "public_share_telegram_delivery_status": telegram_delivery_status,
            "public_share_telegram_notified_at": "2026-06-19T21:05:00Z",
            "public_share_telegram_message_id_present": telegram_message_present,
            "public_share_telegram_message_id_sha256": message_sha256 if telegram_message_present else "",
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
        "audio_publication_gate": {
            "contract_name": "ea.audiobook_publication_audio_gate.v2",
            "status": "pass",
            "checked_at": "2026-06-19T21:08:00Z",
            "gate_sha256": "e" * 64,
            "issues": [],
            "chapters": 1,
            "target_file_sha256": artifact_sha256,
            "source_sha256": source_sha256,
            "source_aggregate_sha256": "3" * 64,
            "narration_plan_sha256": plan_sha256,
            "render_signature_sha256": render_signature,
            "cast_map_sha256": cast_sha256,
            "mastering_signature_set_sha256": "7" * 64,
            "expected_chapter_count": 1,
            "actual_chapter_count": 1,
            "chapter_count_matches": True,
            "cinematic_timeline_sha256": "",
            "loudness": {
                "status": "checked",
                "analysis_scope": "full_file",
                "integrated_lufs": -16.0,
                "true_peak_dbtp": -2.0,
                "min_integrated_lufs": -20.0,
                "max_integrated_lufs": -14.0,
                "max_true_peak_dbtp": -1.0,
            },
            "stt": {
                "status": "pass",
                "enabled": True,
                "required": True,
                "sample_count": 1,
                "passed_samples": 1,
                "failed_samples": 0,
            },
            "raw_paths_exposed": False,
        },
        "storage": {
            "job_storage_kind": "pcloud",
            "audiobookshelf_storage_kind": "pcloud",
            "manifest_sha256": "e" * 64,
        },
        "telegram": {
            "chat_bound": True,
            "listener_reference_sha256": "b" * 64,
            "message_bound": True,
            "voice_sample_delivery_status": (
                "sent" if replacement_choice_pending and voice_samples_sent else ""
            ),
            "voice_sample_delivery_expected_count": 1 if replacement_choice_pending else 0,
            "voice_sample_delivery_sent_count": (
                1 if replacement_choice_pending and voice_samples_sent else 0
            ),
            "voice_sample_delivery_failed_count": 0,
            "voice_sample_callback_tokens_exposed": False,
        },
        "playback_acceptance": playback_acceptance,
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


def test_live_telegram_audiobook_delivery_receipt_guides_empty_intake_to_telegram(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_telegram_audiobook_live_delivery_receipt")

    receipt = module.build_receipt(
        output_path=tmp_path / "empty.generated.json",
        job_receipts=[],
        generated_at="2026-06-19T21:10:00Z",
    )

    assert receipt["status"] == "blocked"
    assert receipt["candidate_count"] == 0
    assert receipt["failed_candidate_count"] == 0
    assert receipt["live_delivery_claim_allowed"] is False
    assert receipt["next_action"] == (
        "send_epub_over_telegram_to_create_live_delivery_receipt"
    )
    assert receipt["next_action_href"] == "/integrations/telegram"
    assert receipt["next_action_label"] == "Open Telegram"
    assert receipt["next_action_method"] == "get"


def test_live_telegram_audiobook_delivery_receipt_passes_with_redacted_job_receipt(tmp_path: Path) -> None:
    module = _load_script("materialize_telegram_audiobook_live_delivery_receipt")

    receipt = module.build_receipt(
        output_path=tmp_path / "telegram_audiobook_live_delivery.generated.json",
        job_receipts=[_job_receipt()],
        generated_at="2026-06-19T21:10:00Z",
    )

    assert receipt["contract_name"] == "ea.telegram_audiobook_live_delivery_receipt.v2"
    assert receipt["output_path"] == "telegram_audiobook_live_delivery.generated.json"
    assert not str(receipt["output_path"]).startswith("/")
    assert receipt["status"] == "pass"
    assert receipt["live_delivery_claim_allowed"] is True
    assert receipt["machine_playback_e2e_verified"] is True
    assert receipt["real_user_playback_acceptance_verified"] is False
    assert receipt["goal_completion_claim_allowed"] is False
    assert receipt["canary_completion_claim_allowed"] is False
    assert receipt["canary_completion_blocked_fields"]
    assert receipt["selected_delivery"]["performance_evidence"]["all_required_proof_passed"] is True
    assert receipt["next_action"] == "capture_real_user_playback_acceptance_or_close_operator_loop"
    assert receipt["next_action_href"] == "/integrations/telegram"
    assert receipt["next_action_label"] == "Open Telegram"
    assert receipt["next_action_method"] == "get"
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
    assert receipt["canary_completion_claim_allowed"] is True
    assert receipt["canary_completion_blocked_fields"] == []
    assert receipt["selected_delivery"]["human_listened_canary"]["receipt_digest_valid"] is True
    attestation = receipt["selected_delivery"]["human_listened_canary"][
        "perceptual_attestation"
    ]
    assert attestation["contract_name"] == PERCEPTUAL_ATTESTATION_CONTRACT_NAME
    assert attestation["version"] == 1
    assert attestation["all_checks_attested"] is True
    assert attestation["channel_feedback_bound"] is True
    assert all(attestation["checks"].values())
    assert attestation["raw_values_exposed"] is False
    assert receipt["goal_completion_claim_allowed"] is False
    assert receipt["next_action"] == "close_operator_loop"
    assert receipt["next_action_href"] == "/app/channel-loop"
    assert receipt["next_action_label"] == "Open channel loop"
    assert receipt["next_action_method"] == "get"
    selected = receipt["selected_delivery"]
    assert selected["playback_acceptance_verified"] is True
    assert selected["playback_acceptance_status"] == "listened_canary_accepted"
    assert selected["playback_acceptance_source"] == "telegram_button"
    assert selected["playback_acceptance_feedback_sha256"] == "a" * 64
    assert receipt["privacy"]["playback_acceptance_feedback_hashed"] is True


def test_telegram_load_error_forces_valid_accepted_delivery_to_nonclaiming_blocked_state(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_telegram_audiobook_live_delivery_receipt")
    receipt = module.build_receipt(
        output_path=tmp_path / "accepted-with-load-error.generated.json",
        job_receipts=[_job_receipt(playback_accepted=True)],
        generated_at="2026-06-19T21:20:00Z",
    )
    assert receipt["status"] == "pass"

    module._apply_load_errors(receipt, ["job_receipt_build_failed"])

    assert receipt["status"] == "blocked"
    assert receipt["live_delivery_claim_allowed"] is False
    assert receipt["machine_playback_e2e_verified"] is False
    assert receipt["real_user_playback_acceptance_verified"] is False
    assert receipt["human_playback_acceptance_claim_allowed"] is False
    assert receipt["canary_completion_claim_allowed"] is False
    assert receipt["goal_completion_claim_allowed"] is False
    assert receipt["proof_freshness"]["fresh_live_job_receipt_passed"] is False
    assert receipt["canary_completion_blocked_fields"] == ["job_receipt_load_errors"]
    assert receipt["failed_codes"] == ["job_receipt_load_errors"]
    assert receipt["next_action"] == "inspect_failed_audiobook_delivery_candidates"
    assert receipt["next_action"] != "close_operator_loop"


def test_live_telegram_receipt_rejects_signed_partial_perceptual_attestation(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_telegram_audiobook_live_delivery_receipt")
    job = _job_receipt(playback_accepted=True)
    playback = job["playback_acceptance"]
    attestation = playback["perceptual_attestation"]
    attestation["checks"]["correct_words"] = False
    canonical = {
        "contract_name": PERCEPTUAL_ATTESTATION_CONTRACT_NAME,
        "version": 1,
        "channel": "telegram",
        "checks": attestation["checks"],
        "all_checks_attested": True,
    }
    attestation["attestation_sha256"] = hashlib.sha256(
        json.dumps(
            canonical,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    playback["receipt_sha256"] = _acceptance_sha256(playback)
    playback["receipt_hmac_sha256"] = hmac.new(
        TEST_CANARY_HMAC_KEY.encode("utf-8"),
        playback["receipt_sha256"].encode("ascii"),
        hashlib.sha256,
    ).hexdigest()

    receipt = module.build_receipt(
        output_path=tmp_path / "partial-attestation.generated.json",
        job_receipts=[job],
        generated_at="2026-06-19T21:20:00Z",
    )

    human = receipt["selected_delivery"]["human_listened_canary"]
    assert human["receipt_digest_valid"] is True
    assert human["receipt_hmac_valid"] is True
    assert human["claim_allowed"] is False
    assert "perceptual_attestation" in human["blocked_fields"]
    assert receipt["canary_completion_claim_allowed"] is False


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
    assert receipt["next_action_href"] == "/integrations/telegram"
    assert receipt["next_action_label"] == "Open Telegram"
    assert receipt["next_action_method"] == "get"
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
        generated_at="2026-06-19T21:20:00Z",
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
    assert receipt["next_action_href"] == "/app/channel-loop"
    assert receipt["next_action_label"] == "Open channel loop"
    assert receipt["next_action_method"] == "get"


@pytest.mark.parametrize(
    (
        "voice_samples_sent",
        "expected_underfilled",
        "expected_next_action",
        "expected_href",
        "expected_label",
        "expected_user_action",
    ),
    [
        (
            False,
            True,
            "send_missing_telegram_audiobook_voice_samples_before_user_choice",
            "/app/channel-loop",
            "Open channel loop",
            False,
        ),
        (
            True,
            False,
            "choose_one_telegram_audiobook_voice_sample",
            "/integrations/telegram",
            "Open Telegram",
            True,
        ),
    ],
)
def test_live_telegram_audiobook_delivery_receipt_surfaces_initial_voice_choice(
    tmp_path: Path,
    voice_samples_sent: bool,
    expected_underfilled: bool,
    expected_next_action: str,
    expected_href: str,
    expected_label: str,
    expected_user_action: bool,
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
        voice_samples_sent=voice_samples_sent,
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
    assert (
        "voice_sample_delivery_underfilled" in receipt["failed_codes"]
    ) is expected_underfilled
    assert receipt["next_action"] == expected_next_action
    assert receipt["next_action_href"] == expected_href
    assert receipt["next_action_label"] == expected_label
    assert receipt["next_action_method"] == "get"
    packet = receipt["operator_action_packet"]
    assert packet["user_action_required"] is expected_user_action
    if expected_underfilled:
        assert packet["voice_sample_delivery_missing_count"] == 1
    else:
        assert packet["sent_samples_cover_expected"] is True


@pytest.mark.parametrize(
    (
        "voice_samples_sent",
        "expected_underfilled",
        "expected_next_action",
        "expected_user_action",
    ),
    [
        (
            False,
            True,
            "send_missing_telegram_audiobook_voice_samples_before_user_choice",
            False,
        ),
        (True, False, "choose_sent_replacement_voice_sample", True),
    ],
)
def test_live_telegram_audiobook_delivery_receipt_surfaces_explicit_replacement_choice_pending(
    tmp_path: Path,
    voice_samples_sent: bool,
    expected_underfilled: bool,
    expected_next_action: str,
    expected_user_action: bool,
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
                voice_samples_sent=voice_samples_sent,
            ),
        ],
        generated_at="2026-06-20T11:20:00Z",
    )

    assert receipt["status"] == "blocked"
    assert receipt["live_delivery_claim_allowed"] is False
    assert "user_selected_voice_delivery_not_ready" in receipt["failed_codes"]
    assert "explicit_replacement_voice_choice_pending" in receipt["failed_codes"]
    assert (
        "voice_sample_delivery_underfilled" in receipt["failed_codes"]
    ) is expected_underfilled
    assert receipt["next_action"] == expected_next_action
    packet = receipt["operator_action_packet"]
    assert packet["user_action_required"] is expected_user_action
    if expected_underfilled:
        assert packet["voice_sample_delivery_missing_count"] == 1
    else:
        assert packet["sent_samples_cover_expected"] is True
    pending = receipt["pending_user_selected_voice_jobs"][0]
    assert pending["voice_selection_status"] == "waiting_user_choice"
    assert pending["voice_selection_reason"] == "selected_voice_provider_balance_blocked"
    assert pending["replacement_choice_pending"] is True
    assert pending["replacement_candidate_count"] == 1
    serialized = json.dumps(receipt, sort_keys=True)
    assert "Piper German Thorsten high" not in serialized
    assert "piper-local" not in serialized


def test_live_telegram_audiobook_delivery_packet_targets_underfilled_row_after_sent_row(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_telegram_audiobook_live_delivery_receipt")
    sent = _job_receipt(
        job_id="sent-samples-first",
        status="waiting_voice_selection",
        render_status="waiting_voice_selection",
        public_share_status="",
        telegram_delivery_status="",
        telegram_message_present=False,
        replacement_choice_pending=True,
        voice_samples_sent=True,
    )
    underfilled = _job_receipt(
        job_id="underfilled-samples-second",
        status="waiting_voice_selection",
        render_status="waiting_voice_selection",
        public_share_status="",
        telegram_delivery_status="",
        telegram_message_present=False,
        replacement_choice_pending=True,
        voice_samples_sent=False,
    )
    underfilled["source"]["source_sha256"] = "a" * 64

    receipt = module.build_receipt(
        output_path=tmp_path / "mixed-sample-delivery.generated.json",
        job_receipts=[sent, underfilled],
        generated_at="2026-06-20T11:22:00Z",
    )

    assert receipt["next_action"] == (
        "send_missing_telegram_audiobook_voice_samples_before_user_choice"
    )
    packet = receipt["operator_action_packet"]
    assert packet["reason"] == "voice_sample_delivery_underfilled"
    assert packet["voice_sample_delivery_expected_count"] == 1
    assert packet["voice_sample_delivery_sent_count"] == 0
    assert packet["voice_sample_delivery_required_count"] == 1
    assert packet["voice_sample_delivery_missing_count"] == 1


def test_live_telegram_receipt_mixed_accepted_and_pending_normalizes_root_claims_and_verifies(
    tmp_path: Path,
) -> None:
    materializer = _load_script(
        "materialize_telegram_audiobook_live_delivery_receipt"
    )
    verifier = _load_script("verify_telegram_audiobook_live_delivery_receipt")
    accepted = _job_receipt(
        job_id="accepted-completed-delivery",
        playback_accepted=True,
    )
    pending = _job_receipt(
        job_id="distinct-pending-delivery",
        status="waiting_voice_selection",
        render_status="waiting_voice_selection",
        public_share_status="",
        telegram_delivery_status="",
        telegram_message_present=False,
        replacement_choice_pending=True,
        voice_samples_sent=False,
    )
    pending["source"]["source_sha256"] = "a" * 64
    receipt_path = tmp_path / "mixed-accepted-pending.generated.json"

    receipt = materializer.build_receipt(
        output_path=receipt_path,
        job_receipts=[accepted, pending],
        generated_at="2026-06-19T21:20:00Z",
    )

    assert receipt["status"] == "blocked"
    for field in (
        "live_delivery_claim_allowed",
        "machine_playback_e2e_verified",
        "real_user_playback_acceptance_verified",
        "human_playback_acceptance_claim_allowed",
        "canary_completion_claim_allowed",
        "goal_completion_claim_allowed",
    ):
        assert receipt[field] is False
    selected = receipt["selected_delivery"]
    assert selected["job_id_sha256"] == _sha256("accepted-completed-delivery")
    assert selected["projection_scope"] == "historical_non_claim_evidence"
    assert selected["current_claim_allowed"] is False
    assert selected["historical_human_acceptance_observed"] is True
    assert selected["playback_acceptance_verified"] is False
    assert selected["canary_completion_claim_allowed"] is False
    assert selected["human_listened_canary"]["claim_allowed"] is False
    assert selected["human_listened_canary"]["projection_scope"] == (
        "historical_non_claim_evidence"
    )
    assert verifier.verify(
        receipt_path,
        now=datetime(2026, 6, 19, 21, 25, tzinfo=UTC),
    ) == []


@pytest.mark.parametrize(
    (
        "voice_samples_sent",
        "expected_underfilled",
        "expected_next_action",
        "expected_href",
        "expected_label",
        "expected_user_action",
    ),
    [
        (
            False,
            True,
            "send_missing_telegram_audiobook_voice_samples_before_user_choice",
            "/app/channel-loop",
            "Open channel loop",
            False,
        ),
        (
            True,
            False,
            "choose_sent_replacement_voice_sample",
            "/integrations/telegram",
            "Open Telegram",
            True,
        ),
    ],
)
def test_live_telegram_audiobook_delivery_receipt_surfaces_replacement_choice_without_prior_delivery(
    tmp_path: Path,
    voice_samples_sent: bool,
    expected_underfilled: bool,
    expected_next_action: str,
    expected_href: str,
    expected_label: str,
    expected_user_action: bool,
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
                voice_samples_sent=voice_samples_sent,
            )
        ],
        generated_at="2026-06-20T11:25:00Z",
    )

    assert receipt["status"] == "blocked"
    assert receipt["live_delivery_claim_allowed"] is False
    assert "valid_live_audiobook_delivery_missing" in receipt["failed_codes"]
    assert "explicit_replacement_voice_choice_pending" in receipt["failed_codes"]
    assert (
        "voice_sample_delivery_underfilled" in receipt["failed_codes"]
    ) is expected_underfilled
    assert receipt["next_action"] == expected_next_action
    assert receipt["next_action_href"] == expected_href
    assert receipt["next_action_label"] == expected_label
    assert receipt["next_action_method"] == "get"
    packet = receipt["operator_action_packet"]
    assert packet["user_action_required"] is expected_user_action
    if expected_underfilled:
        assert packet["voice_sample_delivery_missing_count"] == 1
    else:
        assert packet["sent_samples_cover_expected"] is True
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


def test_scan_job_receipts_never_falls_back_to_stale_same_dir_after_build_error(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_telegram_audiobook_live_delivery_receipt")
    from app.services import audiobook_epub_pipeline as pipeline

    job_dir = tmp_path / "private-title-job"
    job_dir.mkdir()
    job_path = job_dir / "job.json"
    job_path.write_text("{}", encoding="utf-8")
    (job_dir / "job_receipt.json").write_text(
        json.dumps(_job_receipt(job_id="stale-should-not-load")),
        encoding="utf-8",
    )
    secret = "SUPER_SECRET_TELEGRAM_TOKEN"
    private_path = "/private/audiobooks/Hidden Title.epub"
    monkeypatch.setattr(
        pipeline,
        "iter_audiobook_job_manifests",
        lambda *, newest_first=False: (job_path,),
    )
    monkeypatch.setattr(
        pipeline,
        "audiobook_job_discovery_roots",
        lambda: (tmp_path,),
    )
    monkeypatch.setattr(
        pipeline,
        "build_audiobook_job_receipt",
        lambda *, job_dir: (_ for _ in ()).throw(
            RuntimeError(f"{secret} {private_path}")
        ),
    )

    receipts, errors = module._scan_job_receipts(10)

    assert receipts == []
    assert errors == ["job_receipt_build_failed"]
    serialized = json.dumps(errors)
    assert secret not in serialized
    assert private_path not in serialized
    assert "private-title-job" not in serialized


def test_telegram_live_receipt_verifier_rejects_load_errors_and_shape(
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_telegram_audiobook_live_delivery_receipt")
    verifier = _load_script("verify_telegram_audiobook_live_delivery_receipt")
    receipt_path = tmp_path / "load-errors.generated.json"
    materializer.build_receipt(
        output_path=receipt_path,
        job_receipts=[_job_receipt()],
        generated_at="2026-06-19T21:20:00Z",
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["load_errors"] = ["job_receipt_build_failed"]
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    issues = verifier.verify(
        receipt_path,
        now=datetime(2026, 6, 19, 21, 25, tzinfo=UTC),
    )
    assert "load_errors must be empty" in issues

    receipt["load_errors"] = "SECRET /private/Hidden.epub"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    issues = verifier.verify(
        receipt_path,
        now=datetime(2026, 6, 19, 21, 25, tzinfo=UTC),
    )
    assert "load_errors must be an array" in issues


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
            "--generated-at",
            "2026-06-19T21:20:00Z",
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


def test_live_telegram_receipt_rejects_legacy_plan_but_preserves_legacy_acceptance_as_non_complete(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_telegram_audiobook_live_delivery_receipt")
    job = _job_receipt(playback_accepted=True)
    job["render"]["narration_plan"]["contract_name"] = "ea.audiobook_narration_plan.v4"
    job["playback_acceptance"]["contract_name"] = "ea.telegram_epub_audiobook_playback_acceptance.v1"
    job["playback_acceptance"]["status"] = "accepted_unqualified"
    job["playback_acceptance"]["listened"] = False
    job["playback_acceptance"]["canary_binding_status"] = "incomplete"

    receipt = module.build_receipt(
        output_path=tmp_path / "legacy.generated.json",
        job_receipts=[job],
        generated_at="2026-06-19T21:20:00Z",
    )

    assert receipt["status"] == "blocked"
    assert "current_v5_narration_plan_missing" in receipt["failed_codes"]
    selected = receipt["selected_delivery"]
    assert selected["human_listened_canary"]["status"] == "legacy_non_complete"
    assert selected["canary_completion_claim_allowed"] is False
    assert receipt["goal_completion_claim_allowed"] is False


def test_live_telegram_receipt_keeps_tampered_human_acceptance_machine_only(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_telegram_audiobook_live_delivery_receipt")
    job = _job_receipt(playback_accepted=True)
    job["playback_acceptance"]["artifact_sha256"] = "0" * 64

    receipt = module.build_receipt(
        output_path=tmp_path / "tampered-acceptance.generated.json",
        job_receipts=[job],
        generated_at="2026-06-19T21:20:00Z",
    )

    assert receipt["status"] == "pass"
    assert receipt["live_delivery_claim_allowed"] is True
    assert receipt["real_user_playback_acceptance_verified"] is False
    assert receipt["canary_completion_claim_allowed"] is False
    assert "artifact_sha256" in receipt["canary_completion_blocked_fields"]
    assert "receipt_sha256" in receipt["canary_completion_blocked_fields"]
    assert receipt["next_action"] == "capture_real_user_playback_acceptance_or_close_operator_loop"


def test_live_telegram_receipt_blocks_stale_job_and_machine_playback_proof(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_telegram_audiobook_live_delivery_receipt")

    receipt = module.build_receipt(
        output_path=tmp_path / "stale.generated.json",
        job_receipts=[_job_receipt()],
        generated_at="2026-06-21T21:20:01Z",
    )

    assert receipt["status"] == "blocked"
    assert "live_job_receipt_stale_or_timestamp_invalid" in receipt["failed_codes"]
    assert "machine_playback_proof_stale_or_timestamp_invalid" in receipt["failed_codes"]
    assert receipt["proof_freshness"]["fresh_live_job_receipt_passed"] is False


def test_live_telegram_receipt_does_not_refresh_stale_publication_gate_with_new_observation(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_telegram_audiobook_live_delivery_receipt")
    job = _job_receipt()
    job["observed_at"] = "2026-06-19T21:19:00Z"
    job["audio_publication_gate"]["checked_at"] = "2026-06-17T21:19:00Z"

    receipt = module.build_receipt(
        output_path=tmp_path / "stale-gate-fresh-observation.generated.json",
        job_receipts=[job],
        generated_at="2026-06-19T21:20:00Z",
    )

    assert receipt["status"] == "blocked"
    assert "live_job_receipt_stale_or_timestamp_invalid" not in receipt["failed_codes"]
    assert "audio_publication_gate_stale_or_timestamp_invalid" in receipt["failed_codes"]
    gate_freshness = receipt["selected_delivery"]["proof_freshness"]["audio_publication_gate"]
    assert gate_freshness["fresh"] is False
    assert gate_freshness["age_seconds"] > gate_freshness["max_age_seconds"]


def test_telegram_live_receipt_verifier_enforces_real_receipt_max_age(
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_telegram_audiobook_live_delivery_receipt")
    verifier = _load_script("verify_telegram_audiobook_live_delivery_receipt")
    receipt_path = tmp_path / "freshness.generated.json"
    materializer.build_receipt(
        output_path=receipt_path,
        job_receipts=[_job_receipt(playback_accepted=True)],
        generated_at="2026-06-19T21:20:00Z",
    )

    assert verifier.verify(
        receipt_path,
        now=datetime(2026, 6, 19, 21, 25, tzinfo=UTC),
    ) == []
    issues = verifier.verify(
        receipt_path,
        now=datetime(2026, 6, 20, 21, 20, 1, tzinfo=UTC),
    )
    assert "live delivery receipt exceeds max-age freshness" in issues


def test_telegram_live_receipt_verifier_independently_rejects_attestation_tamper(
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_telegram_audiobook_live_delivery_receipt")
    verifier = _load_script("verify_telegram_audiobook_live_delivery_receipt")
    receipt_path = tmp_path / "attestation-tamper.generated.json"
    materializer.build_receipt(
        output_path=receipt_path,
        job_receipts=[_job_receipt(playback_accepted=True)],
        generated_at="2026-06-19T21:20:00Z",
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["selected_delivery"]["human_listened_canary"][
        "perceptual_attestation"
    ]["checks"]["correct_words"] = False
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    issues = verifier.verify(
        receipt_path,
        now=datetime(2026, 6, 19, 21, 25, tzinfo=UTC),
    )

    assert (
        "canary completion requires independently verified perceptual attestation"
        in issues
    )


def test_live_telegram_receipt_isolates_malformed_numeric_job_per_candidate(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_telegram_audiobook_live_delivery_receipt")
    malformed = _job_receipt(job_id="malformed-telegram-job")
    malformed["metadata"]["title"] = "PRIVATE MALFORMED TELEGRAM TITLE"
    malformed["audiobookshelf_import"][
        "public_share_playback_e2e_duration_seconds"
    ] = float("nan")

    receipt = module.build_receipt(
        output_path=tmp_path / "malformed-per-row.generated.json",
        job_receipts=[_job_receipt(job_id="valid-telegram-job"), malformed],
        generated_at="2026-06-19T21:20:00Z",
    )

    assert receipt["status"] == "pass"
    assert receipt["candidate_count"] == 2
    assert receipt["failed_candidate_count"] == 1
    assert receipt["selected_delivery"]["job_id_sha256"] == _sha256(
        "valid-telegram-job"
    )
    assert receipt["failed_candidates"] == [
        {
            "job_id_sha256": _sha256("malformed-telegram-job"),
            "status": "malformed_job_receipt",
            "title_present": True,
            "title_sha256": _sha256("PRIVATE MALFORMED TELEGRAM TITLE"),
            "public_share_status": "",
            "telegram_delivery_status": "",
            "failed_codes": ["malformed_job_receipt"],
        }
    ]
    serialized = json.dumps(receipt, allow_nan=False, sort_keys=True)
    assert "PRIVATE MALFORMED TELEGRAM TITLE" not in serialized


def test_live_telegram_receipt_isolates_malformed_pending_sample_count(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_telegram_audiobook_live_delivery_receipt")
    malformed = _job_receipt(
        job_id="malformed-pending-sample-count",
        status="waiting_voice_selection",
        render_status="waiting_voice_selection",
        public_share_status="",
        telegram_delivery_status="",
        telegram_message_present=False,
        replacement_choice_pending=True,
        voice_samples_sent=False,
    )
    malformed["telegram"]["voice_sample_delivery_expected_count"] = "not-an-int"

    receipt = module.build_receipt(
        output_path=tmp_path / "malformed-pending-sample.generated.json",
        job_receipts=[malformed],
        generated_at="2026-06-19T21:20:00Z",
    )

    assert receipt["status"] == "blocked"
    assert receipt["live_delivery_claim_allowed"] is False
    assert receipt["pending_user_selected_voice_job_count"] == 0
    assert "malformed_job_receipt" in receipt["failed_codes"]
    assert receipt["failed_candidates"][0]["status"] == "malformed_job_receipt"


def test_live_telegram_receipt_includes_approved_origin_dossier_story_delivery(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_telegram_audiobook_live_delivery_receipt")
    job = _job_receipt(job_id="origin-dossier-live-delivery")
    job["source"].update(
        {
            "kind": "origin_dossier_story",
            "rights_basis": "player_or_gm_approved_origin_story",
            "source_filename": "Kestrel - Origin Story.txt",
            "source_url_sha256": "",
        }
    )
    job["telegram"].update(
        {
            "chat_bound": False,
            "message_bound": False,
        }
    )

    receipt = module.build_receipt(
        output_path=tmp_path / "origin-dossier-live.generated.json",
        job_receipts=[job],
        generated_at="2026-06-19T21:20:00Z",
    )

    assert receipt["status"] == "pass"
    assert receipt["candidate_count"] == 1
    assert receipt["source_filter"] == "telegram_delivered_audiobook_sources"
    assert receipt["selected_delivery"]["source_kind"] == "origin_dossier_story"
