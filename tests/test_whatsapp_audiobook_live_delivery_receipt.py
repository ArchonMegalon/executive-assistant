from __future__ import annotations

import importlib.util
import hashlib
import json
import hmac
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
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


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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
    job_id: str = "job-wa-live-1",
    public_share_status: str = "public_share_ready",
    whatsapp_delivery_status: str = "sent",
    whatsapp_message_present: bool = True,
    playback_accepted: bool = False,
    playback_source: str = "whatsapp_button",
    status: str = "audiobookshelf_imported",
    render_status: str = "already_rendered",
    voice_selected_by_user: bool = False,
    voice_choice_pending: bool = False,
    replacement_choice_pending: bool = False,
    whatsapp_sender_bound: bool = True,
    whatsapp_session_bound: bool = True,
    assembly_output_ready: bool = True,
    chapter_metadata_embedded: bool = True,
    player_scoped_reference_status: str = "signed_reference_ready",
    publication_gate_chapters: int = 0,
) -> dict[str, object]:
    expected_chapters = publication_gate_chapters or 1
    artifact_sha256 = "8" * 64
    source_sha256 = "1" * 64
    plan_sha256 = "2" * 64
    render_signature = "4" * 64
    cast_sha256 = "5" * 64
    message_sha256 = "9" * 64
    public_share_url = "https://abs.example.com/share/wa-test-book"
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
            "status": "waiting_user_choice" if replacement_choice_pending or voice_choice_pending else "single_configured_voice",
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
            "channel": "whatsapp",
            "source": playback_source,
            "recorded_at": "2026-06-21T08:20:00Z",
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
            "perceptual_attestation": _perceptual_attestation("whatsapp"),
            "listener_reference_sha256": "b" * 64,
            "language": "en-US",
            "dialogue_turn_count": 2,
            "expected_chapter_count": expected_chapters,
            "actual_chapter_count": expected_chapters,
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
    return {
        "contract_name": "ea.telegram_epub_audiobook_job_receipt.v1",
        "status": status,
        "observed_at": "2026-06-21T08:10:00Z",
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
                "chapter_count": expected_chapters,
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
                "expected_final_track_count": expected_chapters,
                "final_track_ready_count": expected_chapters,
                "final_track_mastered_this_run_count": expected_chapters,
                "signature_published_or_verified_count": expected_chapters,
                "segment_mastering": False,
                "final_audio_quality": [
                    {"chapter_index": index, "status": "pass"}
                    for index in range(1, expected_chapters + 1)
                ],
            },
            "audio_quality": {
                "status": "pass",
                "checked_files": expected_chapters,
                "passed_files": expected_chapters,
                "failed_files": 0,
            },
        },
        "totals": {"chapter_count": expected_chapters},
        "chapters": [{"index": index} for index in range(1, expected_chapters + 1)],
        "scheduler_resume": {
            "next_action": "unmixr_tts_no_audio_url:Insufficient API balance (prebuilt characters)"
            if status != "audiobookshelf_imported"
            else "done",
            "retry_after": "2026-06-21T15:07:55Z" if status != "audiobookshelf_imported" else "",
            "external_tts_blocker_retryable": status != "audiobookshelf_imported",
            "external_tts_blocker_code": "provider_balance_or_prebuilt_characters"
            if status != "audiobookshelf_imported"
            else "",
        },
        "assembly": {
            "status": "m4b_ready",
            "output_file_ready": assembly_output_ready,
            "output_file_sha256": artifact_sha256 if assembly_output_ready else "",
            "chapter_metadata_embedded": chapter_metadata_embedded,
            "expected_chapter_count": expected_chapters,
            "actual_chapter_count": expected_chapters,
            "chapter_count_matches": True,
        },
        "audiobookshelf_import": {
            "status": "imported",
            "target_file_ready": True,
            "target_file_sha256": artifact_sha256,
            "target_storage_kind": "pcloud",
            "player_scoped_reference_status": player_scoped_reference_status,
            "public_share_status": public_share_status,
            "public_share_url": public_share_url,
            "public_share_slug_sha256": "c" * 64,
            "public_share_token_exposed": False,
            "public_share_raw_library_path_exposed": False,
            "public_share_whatsapp_followup_pending": False,
            "public_share_whatsapp_delivery_status": whatsapp_delivery_status,
            "public_share_whatsapp_notified_at": "2026-06-21T08:15:00Z",
            "public_share_whatsapp_message_id_present": whatsapp_message_present,
            "public_share_whatsapp_message_id_sha256": message_sha256 if whatsapp_message_present else "",
            "public_share_whatsapp_callback_tokens_exposed": False,
            "public_share_whatsapp_audiobookshelf_token_exposed": False,
            "public_share_playback_e2e_status": "pass",
            "public_share_playback_e2e_browser": "chromium_playwright",
            "public_share_playback_e2e_checked_at": "2026-06-21T08:17:00Z",
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
        "audio_publication_gate": {
            "contract_name": "ea.audiobook_publication_audio_gate.v2",
            "status": "pass",
            "checked_at": "2026-06-21T08:18:00Z",
            "gate_sha256": "e" * 64,
            "issues": [],
            "chapters": expected_chapters,
            "target_file_sha256": artifact_sha256,
            "source_sha256": source_sha256,
            "source_aggregate_sha256": "3" * 64,
            "narration_plan_sha256": plan_sha256,
            "render_signature_sha256": render_signature,
            "cast_map_sha256": cast_sha256,
            "mastering_signature_set_sha256": "7" * 64,
            "expected_chapter_count": expected_chapters,
            "actual_chapter_count": expected_chapters,
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
        "telegram": {
            "chat_bound": False,
            "message_bound": False,
            "voice_sample_callback_tokens_exposed": False,
        },
        "whatsapp": {
            "sender_bound": whatsapp_sender_bound,
            "listener_reference_sha256": "b" * 64,
            "session_bound": whatsapp_session_bound,
            "source": "whatsapp_web_session",
            "message_hash_present": True,
            "voice_sample_delivery_status": "sent",
            "voice_sample_delivery_expected_count": 3,
            "voice_sample_delivery_attempted_count": 3,
            "voice_sample_delivery_sent_count": 3,
            "voice_sample_callback_tokens_exposed": False,
        },
        "playback_acceptance": playback_acceptance,
        "privacy": {
            "raw_book_text_in_receipt": False,
            "telegram_chat_id_exposed": False,
            "telegram_message_id_exposed": False,
            "telegram_token_exposed": False,
            "whatsapp_sender_ref_exposed": False,
            "whatsapp_message_id_exposed": False,
            "provider_secret_exposed": False,
            "audiobookshelf_token_exposed": False,
            "audiobookshelf_raw_path_exposed": False,
            "private_job_path_exposed": False,
        },
    }


def _runtime_preflight_ready() -> dict[str, object]:
    return {
        "contract_name": "ea.telegram_epub_audiobook_runtime_preflight.v1",
        "status": "pass",
        "provider": {
            "api_key_slot_count": 2,
            "voice_catalog_count": 8,
            "voice_audition_min_candidates": 3,
            "unmixr_auto_render_enabled": True,
        },
        "checks": [
            {"key": "telegram_audiobook_enabled", "status": "pass"},
            {"key": "jobs_root_durable", "status": "pass"},
            {"key": "jobs_root_writable", "status": "pass"},
            {"key": "external_tts_enabled", "status": "pass"},
            {"key": "unmixr_auto_render_enabled", "status": "pass"},
            {"key": "voice_catalog_configured", "status": "pass"},
        ],
    }


def _runtime_preflight_blocked() -> dict[str, object]:
    return {
        "contract_name": "ea.telegram_epub_audiobook_runtime_preflight.v1",
        "status": "fail",
        "provider": {
            "api_key_slot_count": 0,
            "voice_catalog_count": 0,
            "voice_audition_min_candidates": 3,
            "unmixr_auto_render_enabled": False,
        },
        "checks": [
            {"key": "telegram_audiobook_enabled", "status": "pass"},
            {"key": "jobs_root_durable", "status": "pass"},
            {"key": "jobs_root_writable", "status": "pass"},
            {"key": "external_tts_enabled", "status": "pass"},
            {"key": "unmixr_auto_render_enabled", "status": "fail"},
            {"key": "voice_catalog_configured", "status": "fail"},
        ],
    }


def test_live_whatsapp_audiobook_delivery_receipt_passes_with_sanitized_job_receipt(tmp_path: Path) -> None:
    module = _load_script("materialize_whatsapp_audiobook_live_delivery_receipt")

    receipt = module.build_receipt(
        output_path=tmp_path / "whatsapp_audiobook_live_delivery.generated.json",
        job_receipts=[_job_receipt()],
        generated_at="2026-06-21T08:20:00Z",
    )

    assert receipt["contract_name"] == "ea.whatsapp_audiobook_live_delivery_receipt.v2"
    assert receipt["output_path"] == "whatsapp_audiobook_live_delivery.generated.json"
    assert not str(receipt["output_path"]).startswith("/")
    assert receipt["status"] == "pass"
    assert receipt["live_delivery_claim_allowed"] is True
    assert receipt["fresh_live_job_receipt_proven"] is True
    assert receipt["historical_or_shadow_proof_only"] is False
    assert receipt["proof_freshness"]["fresh_live_job_receipt_passed"] is True
    assert receipt["live_delivery_claim_scope"] == "machine_playable_delivery_only"
    assert receipt["machine_playback_e2e_verified"] is True
    assert receipt["real_user_playback_acceptance_verified"] is False
    assert receipt["human_playback_acceptance_claim_allowed"] is False
    assert receipt["human_playback_acceptance_evidence"]["status"] == "not_human_verified"
    assert receipt["canary_completion_claim_allowed"] is False
    assert receipt["canary_completion_blocked_fields"]
    assert receipt["selected_delivery"]["performance_evidence"]["all_required_proof_passed"] is True
    assert receipt["proof_semantics"]["machine_playable_delivery_does_not_imply_human_acceptance"] is True
    assert receipt["next_action"] == "capture_real_user_playback_acceptance_or_close_operator_loop"
    selected = receipt["selected_delivery"]
    assert selected["public_share_url_present"] is True
    assert selected["public_share_host"] == "abs.example.com"
    assert selected["whatsapp_delivery_status"] == "sent"
    assert selected["whatsapp_delivery_message_id_present"] is True
    assert selected["whatsapp_sender_bound"] is True
    assert selected["whatsapp_session_bound"] is True
    assert selected["machine_playback_e2e_track_response_status"] == 206
    assert selected["machine_playback_e2e_track_content_type"] == "audio/mp4"
    serialized = json.dumps(receipt, sort_keys=True)
    assert "Test Book" not in serialized
    assert "A. Writer" not in serialized
    assert "https://abs.example.com/share/wa-test-book" not in serialized
    assert "4368120864006" not in serialized
    assert "wamid" not in serialized
    assert receipt["privacy"]["whatsapp_message_ids_hashed"] is True
    assert receipt["privacy"]["playback_acceptance_feedback_hashed"] is False


def test_live_whatsapp_audiobook_delivery_receipt_accepts_cleaned_import_target_proof(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_whatsapp_audiobook_live_delivery_receipt")

    receipt = module.build_receipt(
        output_path=tmp_path / "cleaned-import.generated.json",
        job_receipts=[
            _job_receipt(
                assembly_output_ready=False,
                chapter_metadata_embedded=False,
                player_scoped_reference_status="blocked",
                publication_gate_chapters=12,
            )
        ],
        generated_at="2026-06-21T08:26:00Z",
    )

    assert receipt["status"] == "pass"
    assert receipt["live_delivery_claim_allowed"] is True
    selected = receipt["selected_delivery"]
    assert selected["player_scoped_reference_ready"] is False
    assert selected["machine_playback_e2e_verified"] is True
    assert "m4b_output_file_not_ready" not in receipt["failed_codes"]
    assert "player_scoped_reference_not_ready" not in receipt["failed_codes"]


def test_live_whatsapp_audiobook_delivery_receipt_surfaces_whatsapp_playback_acceptance(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_whatsapp_audiobook_live_delivery_receipt")

    receipt = module.build_receipt(
        output_path=tmp_path / "accepted.generated.json",
        job_receipts=[_job_receipt(playback_accepted=True)],
        generated_at="2026-06-21T08:25:00Z",
    )

    assert receipt["status"] == "pass"
    assert receipt["real_user_playback_acceptance_verified"] is True
    assert receipt["human_playback_acceptance_claim_allowed"] is True
    assert receipt["canary_completion_claim_allowed"] is True
    assert receipt["canary_completion_blocked_fields"] == []
    assert receipt["live_delivery_claim_scope"] == "machine_playable_delivery_and_human_accepted"
    assert receipt["human_playback_acceptance_evidence"]["status"] == "accepted"
    assert receipt["next_action"] == "close_operator_loop"
    selected = receipt["selected_delivery"]
    assert selected["playback_acceptance_verified"] is True
    assert selected["human_listened_canary"]["receipt_digest_valid"] is True
    attestation = selected["human_listened_canary"]["perceptual_attestation"]
    assert attestation["contract_name"] == PERCEPTUAL_ATTESTATION_CONTRACT_NAME
    assert attestation["version"] == 1
    assert attestation["all_checks_attested"] is True
    assert attestation["channel_feedback_bound"] is True
    assert all(attestation["checks"].values())
    assert attestation["raw_values_exposed"] is False
    assert selected["playback_acceptance_source"] == "whatsapp_button"
    assert receipt["privacy"]["playback_acceptance_feedback_hashed"] is True


def test_whatsapp_load_error_forces_valid_accepted_delivery_to_nonclaiming_blocked_state(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_whatsapp_audiobook_live_delivery_receipt")
    receipt = module.build_receipt(
        output_path=tmp_path / "accepted-with-load-error.generated.json",
        job_receipts=[_job_receipt(playback_accepted=True)],
        generated_at="2026-06-21T08:25:00Z",
    )
    assert receipt["status"] == "pass"

    module._apply_load_errors(receipt, ["job_receipt_build_failed"])

    assert receipt["status"] == "blocked"
    assert receipt["live_delivery_claim_allowed"] is False
    assert receipt["live_delivery_claim_scope"] == "none"
    assert receipt["fresh_live_job_receipt_proven"] is False
    assert receipt["machine_playback_e2e_verified"] is False
    assert receipt["real_user_playback_acceptance_verified"] is False
    assert receipt["human_playback_acceptance_claim_allowed"] is False
    assert receipt["human_playback_acceptance_evidence"]["claim_allowed"] is False
    assert receipt["human_playback_acceptance_evidence"]["status"] == "not_human_verified"
    assert receipt["canary_completion_claim_allowed"] is False
    assert receipt["goal_completion_claim_allowed"] is False
    assert receipt["proof_freshness"]["fresh_live_job_receipt_passed"] is False
    assert receipt["proof_semantics"]["live_delivery_claim_scope"] == "none"
    assert receipt["canary_completion_blocked_fields"] == ["job_receipt_load_errors"]
    assert receipt["failed_codes"] == ["job_receipt_load_errors"]
    assert receipt["next_action"] == "inspect_failed_whatsapp_audiobook_delivery_candidates"
    assert receipt["next_action"] != "close_operator_loop"


def test_live_whatsapp_receipt_rejects_signed_partial_perceptual_attestation(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_whatsapp_audiobook_live_delivery_receipt")
    job = _job_receipt(playback_accepted=True)
    playback = job["playback_acceptance"]
    attestation = playback["perceptual_attestation"]
    attestation["checks"]["stable_speaker_identity"] = False
    canonical = {
        "contract_name": PERCEPTUAL_ATTESTATION_CONTRACT_NAME,
        "version": 1,
        "channel": "whatsapp",
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
        generated_at="2026-06-21T08:25:00Z",
    )

    human = receipt["selected_delivery"]["human_listened_canary"]
    assert human["receipt_digest_valid"] is True
    assert human["receipt_hmac_valid"] is True
    assert human["claim_allowed"] is False
    assert "perceptual_attestation" in human["blocked_fields"]
    assert receipt["canary_completion_claim_allowed"] is False


def test_live_whatsapp_audiobook_delivery_receipt_routes_rejected_playback_to_review_action(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_whatsapp_audiobook_live_delivery_receipt")
    rejected = _job_receipt(playback_accepted=False)
    rejected["playback_acceptance"] = {
        "contract_name": "ea.telegram_epub_audiobook_playback_acceptance.v1",
        "status": "rejected",
        "accepted": False,
        "source": "whatsapp_button_recovered",
        "recorded_at": "2026-06-21T08:20:00Z",
        "feedback_sha256": "f" * 64,
        "message_id_sha256": "g" * 64,
        "public_share_url_sha256": "h" * 64,
        "audiobookshelf_target_file_sha256": "b" * 64,
        "telegram_public_share_message_id_sha256": "",
        "whatsapp_public_share_message_id_sha256": "d" * 64,
        "raw_feedback_exposed": False,
        "raw_message_id_exposed": False,
    }

    receipt = module.build_receipt(
        output_path=tmp_path / "rejected.generated.json",
        job_receipts=[rejected],
        generated_at="2026-06-21T08:25:00Z",
    )

    assert receipt["status"] == "pass"
    assert receipt["real_user_playback_acceptance_verified"] is False
    assert receipt["human_playback_acceptance_claim_allowed"] is False
    assert receipt["live_delivery_claim_scope"] == "machine_playable_delivery_only"
    assert receipt["human_playback_acceptance_evidence"]["status"] == "rejected"
    assert receipt["human_playback_acceptance_evidence"]["rejected"] is True
    assert receipt["human_playback_acceptance_evidence"]["feedback_sha256_present"] is True
    assert receipt["machine_playback_e2e_verified"] is True
    assert receipt["next_action"] == "review_audiobook_playback_problem"
    assert receipt["privacy"]["playback_acceptance_feedback_hashed"] is True


def test_live_whatsapp_audiobook_delivery_receipt_requires_hashed_feedback_for_rejected_playback(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_whatsapp_audiobook_live_delivery_receipt")
    rejected = _job_receipt(playback_accepted=False)
    rejected["playback_acceptance"] = {
        "contract_name": "ea.telegram_epub_audiobook_playback_acceptance.v1",
        "status": "rejected",
        "accepted": False,
        "source": "whatsapp_button_recovered",
        "recorded_at": "2026-06-21T08:20:00Z",
        "feedback_sha256": "",
        "message_id_sha256": "g" * 64,
        "public_share_url_sha256": "h" * 64,
        "audiobookshelf_target_file_sha256": "b" * 64,
        "telegram_public_share_message_id_sha256": "",
        "whatsapp_public_share_message_id_sha256": "d" * 64,
        "raw_feedback_exposed": False,
        "raw_message_id_exposed": False,
    }

    receipt = module.build_receipt(
        output_path=tmp_path / "rejected-unhashed.generated.json",
        job_receipts=[rejected],
        generated_at="2026-06-21T08:25:00Z",
    )

    evidence = receipt["human_playback_acceptance_evidence"]
    assert receipt["status"] == "pass"
    assert receipt["live_delivery_claim_scope"] == "machine_playable_delivery_only"
    assert receipt["human_playback_acceptance_claim_allowed"] is False
    assert evidence["status"] == "not_human_verified"
    assert evidence["rejected"] is False
    assert evidence["rejected_claim_observed"] is True
    assert evidence["feedback_sha256_present"] is False
    assert evidence["feedback_sha256_valid"] is False
    assert evidence["feedback_sha256_required"] is True
    assert evidence["operator_grade"] is False
    assert evidence["evidence_grade"] == "insufficient_feedback_hash"
    assert receipt["next_action"] == "capture_hashed_audiobook_playback_problem_feedback"
    assert receipt["privacy"]["playback_acceptance_feedback_hashed"] is False


def test_live_whatsapp_audiobook_delivery_receipt_blocks_missing_whatsapp_delivery(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_whatsapp_audiobook_live_delivery_receipt")

    receipt = module.build_receipt(
        output_path=tmp_path / "missing-wa.generated.json",
        job_receipts=[_job_receipt(whatsapp_delivery_status="", whatsapp_message_present=False)],
        generated_at="2026-06-21T08:30:00Z",
    )

    assert receipt["status"] == "blocked"
    assert receipt["live_delivery_claim_allowed"] is False
    assert receipt["live_delivery_claim_scope"] == "none"
    assert "whatsapp_public_share_delivery_not_sent" in receipt["failed_codes"]
    assert "whatsapp_public_share_message_id_missing" in receipt["failed_codes"]
    assert receipt["stage_summary"]["counts"]["waiting_whatsapp_public_share_delivery"] == 1
    assert receipt["next_action"] == "run_whatsapp_action_processor_audiobook_followup_to_send_public_share_link"


def test_live_whatsapp_audiobook_delivery_receipt_routes_current_playback_failure_to_playback_repair(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_whatsapp_audiobook_live_delivery_receipt")
    current = _job_receipt(voice_selected_by_user=True, player_scoped_reference_status="blocked")
    current["audiobookshelf_import"]["public_share_playback_e2e_status"] = "failed"
    current["audiobookshelf_import"]["public_share_playback_e2e_track_response_status"] = 500
    current["audiobookshelf_import"]["public_share_playback_e2e_track_content_type"] = "text/html"
    current["audiobookshelf_import"]["public_share_playback_e2e_duration_seconds"] = 0
    current["audiobookshelf_import"]["public_share_playback_e2e_current_time_after_play_seconds"] = 0
    current["audiobookshelf_import"]["public_share_playback_e2e_media_error_present"] = True
    superseded = _job_receipt(job_id="older-superseded", voice_selected_by_user=True)
    superseded["status"] = "superseded_duplicate"

    receipt = module.build_receipt(
        output_path=tmp_path / "playback-failed.generated.json",
        job_receipts=[current, superseded],
        generated_at="2026-06-21T08:31:00Z",
    )

    assert receipt["status"] == "blocked"
    assert receipt["live_delivery_claim_allowed"] is False
    assert receipt["selected_delivery"]["status"] == "audiobookshelf_imported"
    assert receipt["selected_delivery"]["machine_playback_e2e_track_response_status"] == 500
    assert receipt["stage_summary"]["counts"]["waiting_machine_playback_verification"] == 1
    assert receipt["next_action"] == "run_public_share_machine_playback_e2e_before_claiming_live_delivery"
    assert receipt["pending_user_selected_voice_job_count"] == 1
    assert receipt["pending_user_selected_voice_jobs"][0]["status"] == "audiobookshelf_imported"


def test_live_whatsapp_audiobook_delivery_receipt_waits_for_provider_pacing(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_whatsapp_audiobook_live_delivery_receipt")

    receipt = module.build_receipt(
        output_path=tmp_path / "provider-pacing.generated.json",
        job_receipts=[
            _job_receipt(
                status="waiting_provider_throttle",
                render_status="provider_pacing_wait",
                voice_selected_by_user=True,
            )
        ],
        generated_at="2026-06-21T08:32:00Z",
    )

    assert receipt["status"] == "waiting_provider_throttle"
    assert receipt["live_delivery_claim_allowed"] is False
    assert receipt["stage_summary"]["counts"]["waiting_provider_pacing"] == 1
    assert receipt["next_action"] == "wait_until_provider_retry_after_then_resume_whatsapp_audiobook_render"
    assert receipt["pending_user_selected_voice_jobs"][0]["scheduler_retry_after"] == "2026-06-21T15:07:55Z"


def test_live_whatsapp_audiobook_delivery_receipt_ignores_non_whatsapp_jobs(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_whatsapp_audiobook_live_delivery_receipt")
    telegram_only = _job_receipt(
        job_id="telegram-only-pending",
        status="waiting_voice_selection",
        render_status="waiting_voice_selection",
        public_share_status="",
        whatsapp_delivery_status="",
        whatsapp_message_present=False,
        replacement_choice_pending=True,
        whatsapp_sender_bound=False,
        whatsapp_session_bound=False,
    )
    telegram_only["whatsapp"] = {}

    receipt = module.build_receipt(
        output_path=tmp_path / "no-wa-job.generated.json",
        job_receipts=[telegram_only],
        generated_at="2026-06-21T08:32:00Z",
    )

    assert receipt["status"] == "blocked"
    assert receipt["observed_job_count"] == 1
    assert receipt["non_whatsapp_job_count"] == 1
    assert receipt["candidate_count"] == 0
    assert receipt["pending_user_selected_voice_job_count"] == 0
    assert receipt["stage_summary"]["counts"] == {}
    assert "whatsapp_audiobook_job_missing" in receipt["failed_codes"]
    assert "explicit_replacement_voice_choice_pending" not in receipt["failed_codes"]
    assert receipt["next_action"] == "send_epub_over_whatsapp_to_start_audiobook_flow"


def test_live_whatsapp_audiobook_delivery_receipt_ignores_jobs_from_non_runtime_session(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_whatsapp_audiobook_live_delivery_receipt")
    mismatched = _job_receipt(
        job_id="proof-fixture-session",
        status="waiting_voice_selection",
        render_status="waiting_voice_selection",
        public_share_status="",
        whatsapp_delivery_status="",
        whatsapp_message_present=False,
        replacement_choice_pending=True,
    )
    mismatched["whatsapp"]["session_ref"] = "session-1"
    matched = _job_receipt(job_id="live-session-pass")
    matched["whatsapp"]["session_ref"] = "tibor-wa-web"

    receipt = module.build_receipt(
        output_path=tmp_path / "runtime-session-filter.generated.json",
        job_receipts=[mismatched, matched],
        readiness_receipt={"effective_session_ref": "tibor-wa-web"},
        generated_at="2026-06-21T08:25:00Z",
    )

    assert receipt["status"] == "pass"
    assert receipt["candidate_count"] == 1
    assert receipt["observed_job_count"] == 2
    assert receipt["pending_user_selected_voice_job_count"] == 0
    assert receipt["selected_delivery"]["job_id_sha256"] == module._sha256_text("live-session-pass")


def test_live_whatsapp_audiobook_delivery_receipt_uses_historical_evidence_to_request_refresh(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_whatsapp_audiobook_live_delivery_receipt")

    receipt = module.build_receipt(
        output_path=tmp_path / "historical-refresh.generated.json",
        job_receipts=[],
        historical_receipts={
            "local_intake": {
                "status": "pass",
                "generated_at": "2026-06-21T19:00:00Z",
                "checks": {
                    "whatsapp_public_share_sent": True,
                    "whatsapp_sender_bound": True,
                    "whatsapp_session_bound": True,
                },
                "processor_report": {
                    "intake": {"voice_sample_sent": 3},
                    "voice_selection": {"share_link_sent": 1},
                },
                "job_summary": {"status": "audiobookshelf_imported"},
            },
            "public_share_playback": {
                "status": "pass",
                "generated_at": "2026-06-21T19:05:00Z",
                "attempted": 1,
                "passed": 1,
                "results": [
                    {
                        "passed": True,
                        "status": "pass",
                        "public_share_host": "audiobookshelf.girschele.com",
                    }
                ],
            },
            "operator_bundle": {
                "status": "pass",
                "generated_at": "2026-06-21T19:10:00Z",
                "recommended_action": "capture_real_user_playback_acceptance_or_close_operator_loop",
                "live_delivery": {
                    "status": "pass",
                    "live_delivery_claim_allowed": True,
                },
            },
        },
        generated_at="2026-06-22T08:32:00Z",
    )

    assert receipt["status"] == "blocked"
    assert receipt["candidate_count"] == 0
    assert "whatsapp_audiobook_job_missing" in receipt["failed_codes"]
    assert "fresh_live_whatsapp_job_receipt_missing" in receipt["failed_codes"]
    assert receipt["next_action"] == "send_epub_over_whatsapp_to_refresh_live_delivery_receipt"
    historical = receipt["historical_evidence"]
    assert historical["present"] is True
    assert historical["historical_live_path_proven"] is True
    assert historical["local_intake"]["local_path_proven"] is True
    assert historical["public_share_playback"]["playback_path_proven"] is True
    assert historical["public_share_playback"]["public_share_hosts"] == ["audiobookshelf.girschele.com"]
    assert historical["operator_bundle"]["live_path_proven"] is True


def test_live_whatsapp_audiobook_delivery_receipt_waits_for_fresh_epub_when_runtime_is_ready(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_whatsapp_audiobook_live_delivery_receipt")
    module._runtime_container_preflight = lambda: {}
    module.audiobook_runtime_preflight = lambda: _runtime_preflight_ready()

    receipt = module.build_receipt(
        output_path=tmp_path / "historical-waiting.generated.json",
        job_receipts=[],
        historical_receipts={
            "local_intake": {
                "status": "pass",
                "generated_at": "2026-06-21T19:00:00Z",
                "checks": {
                    "whatsapp_public_share_sent": True,
                    "whatsapp_sender_bound": True,
                    "whatsapp_session_bound": True,
                },
                "processor_report": {
                    "intake": {"voice_sample_sent": 3},
                    "voice_selection": {"share_link_sent": 1},
                },
                "job_summary": {"status": "audiobookshelf_imported"},
            },
            "public_share_playback": {
                "status": "pass",
                "generated_at": "2026-06-21T19:05:00Z",
                "attempted": 1,
                "passed": 1,
                "results": [
                    {
                        "passed": True,
                        "status": "pass",
                        "public_share_host": "audiobookshelf.girschele.com",
                    }
                ],
            },
        },
        readiness_receipt={
            "contract_name": "ea.whatsapp_web_action_processor_readiness.v1",
            "status": "ready",
            "ready": True,
            "reason": "ready",
            "sidecar_ready": True,
            "state_fresh": True,
            "effective_session_ref": "tibor-wa-web",
        },
        generated_at="2026-06-22T08:33:00Z",
    )

    assert receipt["status"] == "waiting_for_live_epub"
    assert receipt["candidate_count"] == 0
    assert receipt["fresh_live_job_receipt_proven"] is False
    assert receipt["historical_or_shadow_proof_only"] is True
    assert receipt["proof_freshness"]["historical_live_path_proven"] is True
    assert receipt["runtime_readiness"]["receipt_present"] is True
    assert receipt["runtime_readiness"]["ready"] is True
    assert receipt["runtime_readiness"]["effective_session_ref_present"] is True
    assert "whatsapp_audiobook_job_missing" in receipt["failed_codes"]
    assert "fresh_live_whatsapp_job_receipt_missing" in receipt["failed_codes"]
    assert receipt["next_action"] == "send_epub_over_whatsapp_to_refresh_live_delivery_receipt"


def test_live_whatsapp_audiobook_delivery_receipt_blocks_refresh_when_audiobook_runtime_is_not_ready(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_whatsapp_audiobook_live_delivery_receipt")
    module._runtime_container_preflight = lambda: {}
    module.audiobook_runtime_preflight = lambda: _runtime_preflight_blocked()

    receipt = module.build_receipt(
        output_path=tmp_path / "historical-blocked-runtime.generated.json",
        job_receipts=[],
        historical_receipts={
            "local_intake": {
                "status": "pass",
                "generated_at": "2026-06-21T19:00:00Z",
                "checks": {
                    "whatsapp_public_share_sent": True,
                    "whatsapp_sender_bound": True,
                    "whatsapp_session_bound": True,
                },
                "processor_report": {
                    "intake": {"voice_sample_sent": 3},
                    "voice_selection": {"share_link_sent": 1},
                },
                "job_summary": {"status": "audiobookshelf_imported"},
            },
            "public_share_playback": {
                "status": "pass",
                "generated_at": "2026-06-21T19:05:00Z",
                "attempted": 1,
                "passed": 1,
                "results": [
                    {
                        "passed": True,
                        "status": "pass",
                        "public_share_host": "audiobookshelf.girschele.com",
                    }
                ],
            },
        },
        readiness_receipt={
            "contract_name": "ea.whatsapp_web_action_processor_readiness.v1",
            "status": "ready",
            "ready": True,
            "reason": "ready",
            "sidecar_ready": True,
            "state_fresh": True,
            "effective_session_ref": "tibor-wa-web",
        },
        generated_at="2026-06-22T08:33:00Z",
    )

    assert receipt["status"] == "blocked"
    assert "audiobook_runtime_not_ready" in receipt["failed_codes"]
    assert receipt["audiobook_runtime"]["ready_for_live_intake"] is False
    assert receipt["audiobook_runtime"]["sample_blockers"] == [
        "unmixr_auto_render_enabled",
        "voice_catalog_configured",
        "voice_catalog_audition_ready",
        "unmixr_api_key_slot_present",
    ]


def test_live_whatsapp_audiobook_delivery_receipt_prefers_runtime_container_preflight(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_whatsapp_audiobook_live_delivery_receipt")
    module._runtime_container_preflight = lambda: _runtime_preflight_ready()
    module.audiobook_runtime_preflight = lambda: _runtime_preflight_blocked()

    receipt = module.build_receipt(
        output_path=tmp_path / "historical-container-runtime.generated.json",
        job_receipts=[],
        historical_receipts={
            "local_intake": {
                "status": "pass",
                "generated_at": "2026-06-21T19:00:00Z",
                "checks": {
                    "whatsapp_public_share_sent": True,
                    "whatsapp_sender_bound": True,
                    "whatsapp_session_bound": True,
                },
                "processor_report": {
                    "intake": {"voice_sample_sent": 3},
                    "voice_selection": {"share_link_sent": 1},
                },
                "job_summary": {"status": "audiobookshelf_imported"},
            },
            "public_share_playback": {
                "status": "pass",
                "generated_at": "2026-06-21T19:05:00Z",
                "attempted": 1,
                "passed": 1,
                "results": [
                    {
                        "passed": True,
                        "status": "pass",
                        "public_share_host": "audiobookshelf.girschele.com",
                    }
                ],
            },
        },
        readiness_receipt={
            "contract_name": "ea.whatsapp_web_action_processor_readiness.v1",
            "status": "ready",
            "ready": True,
            "reason": "ready",
            "sidecar_ready": True,
            "state_fresh": True,
            "effective_session_ref": "tibor-wa-web",
        },
        generated_at="2026-06-22T08:33:00Z",
    )

    assert receipt["status"] == "waiting_for_live_epub"
    assert receipt["audiobook_runtime"]["ready_for_live_intake"] is True
    assert receipt["audiobook_runtime"]["sample_blockers"] == []


def test_live_whatsapp_audiobook_delivery_receipt_distinguishes_existing_whatsapp_render_job(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_whatsapp_audiobook_live_delivery_receipt")

    receipt = module.build_receipt(
        output_path=tmp_path / "render-pending.generated.json",
        job_receipts=[
            _job_receipt(
                job_id="whatsapp-render-pending",
                status="rendering_audio",
                render_status="rendering_audio",
                public_share_status="",
                whatsapp_delivery_status="",
                whatsapp_message_present=False,
            )
        ],
        generated_at="2026-06-21T08:34:00Z",
    )

    assert receipt["status"] == "blocked"
    assert receipt["candidate_count"] == 1
    assert "whatsapp_audiobook_job_missing" not in receipt["failed_codes"]
    assert receipt["stage_summary"]["counts"]["render_or_import_pending"] == 1
    stage = receipt["stage_summary"]["latest_by_stage"]["render_or_import_pending"]
    assert stage["job_id_sha256"]
    assert "job_not_audiobookshelf_imported" in stage["failed_codes"]
    assert receipt["next_action"] == "resume_or_finish_whatsapp_audiobook_render_before_public_share_delivery"


def test_live_whatsapp_audiobook_delivery_receipt_surfaces_initial_voice_choice_pending(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_whatsapp_audiobook_live_delivery_receipt")

    receipt = module.build_receipt(
        output_path=tmp_path / "voice-choice-pending.generated.json",
        job_receipts=[
            _job_receipt(
                job_id="whatsapp-voice-choice-pending",
                status="waiting_voice_selection",
                render_status="provider_pacing_wait",
                public_share_status="",
                whatsapp_delivery_status="",
                whatsapp_message_present=False,
                voice_choice_pending=True,
            )
        ],
        generated_at="2026-06-21T08:34:30Z",
        historical_receipts={
            "operator_bundle": {
                "checks": {"live_voice_selection_text_fallback_ready_or_not_required": True},
                "live_voice_selection_shadow": {
                    "text_fallback": {
                        "bare_voice_choice_resolved": True,
                    }
                },
            }
        },
    )

    assert receipt["status"] == "waiting_voice_choice"
    assert receipt["candidate_count"] == 1
    assert receipt["stage_summary"]["counts"]["waiting_voice_choice"] == 1
    assert receipt["pending_user_selected_voice_job_count"] == 1
    assert receipt["pending_user_selected_voice_jobs"][0]["replacement_choice_pending"] is False
    assert receipt["pending_user_selected_voice_jobs"][0]["voice_selection_text_fallback_ready"] is True
    assert receipt["voice_selection_text_fallback_ready"] is True
    assert receipt["historical_evidence"]["operator_bundle"]["voice_selection_text_fallback_ready"] is True
    assert "explicit_replacement_voice_choice_pending" not in receipt["failed_codes"]
    assert receipt["next_action"] == "choose_whatsapp_audiobook_voice_sample"


def test_live_whatsapp_audiobook_delivery_receipt_blocks_default_voice_when_user_selected_job_pending(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_whatsapp_audiobook_live_delivery_receipt")

    receipt = module.build_receipt(
        output_path=tmp_path / "wrong-voice.generated.json",
        job_receipts=[
            _job_receipt(job_id="older-default-voice-job"),
            _job_receipt(
                job_id="newer-selected-voice-job",
                status="blocked_external_tts",
                render_status="blocked",
                public_share_status="",
                whatsapp_delivery_status="",
                whatsapp_message_present=False,
                voice_selected_by_user=True,
            ),
        ],
        generated_at="2026-06-21T08:35:00Z",
    )

    assert receipt["status"] == "blocked"
    assert receipt["live_delivery_claim_allowed"] is False
    assert "user_selected_voice_delivery_not_ready" in receipt["failed_codes"]
    assert receipt["next_action"] == "finish_user_selected_voice_audiobook_before_sending_whatsapp_public_share_link"
    assert receipt["pending_user_selected_voice_job_count"] == 1
    pending = receipt["pending_user_selected_voice_jobs"][0]
    assert pending["external_tts_blocker_code"] == "provider_balance_or_prebuilt_characters"
    selected = receipt["selected_delivery"]
    assert selected["voice_selected_by_user"] is False
    assert selected["voice_selected_default"] is True
    serialized = json.dumps(receipt, sort_keys=True)
    assert "Davis (Express)" not in serialized
    assert "Default German Voice" not in serialized
    assert "Insufficient API balance" not in serialized


def test_live_whatsapp_audiobook_delivery_receipt_ignores_duplicate_pending_after_user_selected_delivery(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_whatsapp_audiobook_live_delivery_receipt")

    receipt = module.build_receipt(
        output_path=tmp_path / "selected-delivery-duplicates.generated.json",
        job_receipts=[
            _job_receipt(job_id="selected-voice-delivered", voice_selected_by_user=True),
            _job_receipt(
                job_id="duplicate-audition",
                status="waiting_voice_selection",
                render_status="waiting_voice_selection",
                public_share_status="",
                whatsapp_delivery_status="",
                whatsapp_message_present=False,
                replacement_choice_pending=True,
            ),
        ],
        generated_at="2026-06-21T08:40:00Z",
    )

    assert receipt["status"] == "pass"
    assert receipt["live_delivery_claim_allowed"] is True
    assert receipt["pending_user_selected_voice_job_count"] == 0
    assert "user_selected_voice_delivery_not_ready" not in receipt["failed_codes"]
    selected = receipt["selected_delivery"]
    assert selected["voice_selected_by_user"] is True
    assert selected["voice_selected_default"] is False


def test_live_whatsapp_audiobook_delivery_receipt_cli_accepts_sanitized_job_receipts_json(
    tmp_path: Path,
) -> None:
    payload = {"job_receipts": [_job_receipt()]}
    input_path = tmp_path / "receipts.json"
    output_path = tmp_path / "receipt.generated.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "ea" / "scripts" / "materialize_whatsapp_audiobook_live_delivery_receipt.py"),
            "--job-receipts-json",
            str(input_path),
                "--output",
                str(output_path),
                "--generated-at",
                "2026-06-21T08:25:00Z",
                "--require-pass",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    receipt = json.loads(output_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "pass"
    assert receipt["observation_source"] == "job_receipts_json"


def test_live_whatsapp_audiobook_delivery_receipt_resolves_runtime_readiness_when_receipt_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script("materialize_whatsapp_audiobook_live_delivery_receipt")
    module.audiobook_runtime_preflight = lambda: _runtime_preflight_ready()
    module._runtime_container_preflight = lambda: {}
    readiness_path = tmp_path / "missing-readiness.generated.json"
    monkeypatch.setattr(module, "DEFAULT_READINESS_RECEIPT", readiness_path)

    class ReadinessMaterializer:
        @staticmethod
        def build_whatsapp_web_action_processor_readiness(*, output_path, generated_at=None, args=None, request_json=None, run=None):
            payload = {
                "contract_name": "ea.whatsapp_web_action_processor_readiness.v1",
                "status": "ready",
                "ready": True,
                "reason": "ready",
                "sidecar_ready": True,
                "state_fresh": True,
                "effective_session_ref": "tibor-wa-web",
            }
            Path(output_path).write_text(json.dumps(payload), encoding="utf-8")
            return payload

    monkeypatch.setattr(module, "_load_module", lambda **_: ReadinessMaterializer)

    receipt = module.build_receipt(
        output_path=tmp_path / "historical-waiting.generated.json",
        job_receipts=[],
        historical_receipts={
            "local_intake": {
                "status": "pass",
                "checks": {
                    "whatsapp_public_share_sent": True,
                    "whatsapp_sender_bound": True,
                    "whatsapp_session_bound": True,
                },
                "processor_report": {
                    "intake": {"voice_sample_sent": 3},
                    "voice_selection": {"share_link_sent": 1},
                },
                "job_summary": {"status": "audiobookshelf_imported"},
            },
            "public_share_playback": {
                "status": "pass",
                "attempted": 1,
                "passed": 1,
                "results": [
                    {
                        "passed": True,
                        "status": "pass",
                        "public_share_host": "audiobookshelf.girschele.com",
                    }
                ],
            },
        },
        readiness_receipt=module._resolve_runtime_readiness_receipt(),
        generated_at="2026-06-22T08:45:00Z",
    )

    assert receipt["status"] == "waiting_for_live_epub"
    assert receipt["runtime_readiness"]["receipt_present"] is True
    assert receipt["runtime_readiness"]["ready"] is True
    assert readiness_path.exists()


def test_whatsapp_audiobook_live_delivery_verifier_rejects_stale_source_state(
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_whatsapp_audiobook_live_delivery_receipt")
    verifier = _load_script("verify_whatsapp_audiobook_live_delivery_receipt")
    receipt_path = tmp_path / "stale-source.generated.json"
    materializer.build_receipt(
        output_path=receipt_path,
        job_receipts=[_job_receipt()],
        generated_at="2026-06-21T08:20:00Z",
    )

    verification_now = datetime(2026, 6, 21, 8, 25, tzinfo=UTC)
    assert verifier.verify(receipt_path, now=verification_now) == []

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["source_git_head"] = "0" * 40
    receipt["source_state_fingerprint"] = "0" * 64
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    issues = verifier.verify(receipt_path, now=verification_now)
    assert "source_git_head stale" in issues
    assert "source_state_fingerprint stale" in issues


def test_live_whatsapp_receipt_requires_explicit_mastering_signature_evidence(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_whatsapp_audiobook_live_delivery_receipt")
    job = _job_receipt()
    job["render"]["mastering"].pop("signature_set_sha256")

    receipt = module.build_receipt(
        output_path=tmp_path / "missing-mastering-signature.generated.json",
        job_receipts=[job],
        generated_at="2026-06-21T08:20:00Z",
    )

    assert receipt["status"] == "blocked"
    assert "final_mastering_or_signature_incomplete" in receipt["failed_codes"]
    assert receipt["selected_delivery"]["performance_evidence"]["all_required_proof_passed"] is False


def test_live_whatsapp_receipt_requires_exact_chapter_count_and_publication_stt_pass(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_whatsapp_audiobook_live_delivery_receipt")
    job = _job_receipt()
    job["audio_publication_gate"]["chapters"] = 2
    job["audio_publication_gate"]["stt"].update(
        {"status": "fail", "passed_samples": 0, "failed_samples": 1}
    )

    receipt = module.build_receipt(
        output_path=tmp_path / "chapter-stt-mismatch.generated.json",
        job_receipts=[job],
        generated_at="2026-06-21T08:20:00Z",
    )

    assert receipt["status"] == "blocked"
    assert "publication_gate_or_chapter_count_not_exact" in receipt["failed_codes"]
    assert "publication_stt_not_pass" in receipt["failed_codes"]


def test_live_whatsapp_receipt_accepts_one_signed_cinematic_master_for_multiple_chapters(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_whatsapp_audiobook_live_delivery_receipt")
    job = _job_receipt(publication_gate_chapters=3)
    job["render"]["mastering"].update(
        {
            "final_track_mode": "cinematic_master",
            "expected_final_track_count": 1,
            "final_track_ready_count": 1,
            "final_track_mastered_this_run_count": 1,
            "signature_published_or_verified_count": 1,
            "final_audio_quality": [{"chapter_index": 0, "status": "pass"}],
        }
    )
    job["assembly"]["cinematic_timeline_sha256"] = "a" * 64

    receipt = module.build_receipt(
        output_path=tmp_path / "cinematic-master.generated.json",
        job_receipts=[job],
        generated_at="2026-06-21T08:20:00Z",
    )

    assert receipt["status"] == "pass"
    performance = receipt["selected_delivery"]["performance_evidence"]
    assert performance["expected_chapter_count"] == 3
    assert performance["mastering"]["expected_final_track_count"] == 1
    assert performance["cinematic_timeline_sha256"] == "a" * 64


def test_live_whatsapp_receipt_preserves_legacy_human_acceptance_as_non_complete(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_whatsapp_audiobook_live_delivery_receipt")
    job = _job_receipt(playback_accepted=True)
    job["playback_acceptance"]["contract_name"] = "ea.telegram_epub_audiobook_playback_acceptance.v1"
    job["playback_acceptance"]["status"] = "accepted_unqualified"
    job["playback_acceptance"]["listened"] = False
    job["playback_acceptance"]["canary_binding_status"] = "incomplete"

    receipt = module.build_receipt(
        output_path=tmp_path / "legacy-human.generated.json",
        job_receipts=[job],
        generated_at="2026-06-21T08:25:00Z",
    )

    assert receipt["status"] == "pass"
    assert receipt["live_delivery_claim_scope"] == "machine_playable_delivery_only"
    assert receipt["real_user_playback_acceptance_verified"] is False
    assert receipt["human_playback_acceptance_evidence"]["status"] == "legacy_non_complete"
    assert receipt["canary_completion_claim_allowed"] is False
    assert receipt["goal_completion_claim_allowed"] is False


def test_whatsapp_live_receipt_verifier_rejects_forged_machine_only_canary_completion(
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_whatsapp_audiobook_live_delivery_receipt")
    verifier = _load_script("verify_whatsapp_audiobook_live_delivery_receipt")
    receipt_path = tmp_path / "forged-canary.generated.json"
    materializer.build_receipt(
        output_path=receipt_path,
        job_receipts=[_job_receipt()],
        generated_at="2026-06-21T08:20:00Z",
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["canary_completion_claim_allowed"] = True
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    issues = verifier.verify(
        receipt_path,
        now=datetime(2026, 6, 21, 8, 25, tzinfo=UTC),
    )
    assert "canary completion requires verified human playback acceptance" in issues
    assert "canary completion requires the immutable human-listened contract" in issues


def test_whatsapp_live_receipt_verifier_independently_rejects_attestation_tamper(
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_whatsapp_audiobook_live_delivery_receipt")
    verifier = _load_script("verify_whatsapp_audiobook_live_delivery_receipt")
    receipt_path = tmp_path / "attestation-tamper.generated.json"
    materializer.build_receipt(
        output_path=receipt_path,
        job_receipts=[_job_receipt(playback_accepted=True)],
        generated_at="2026-06-21T08:25:00Z",
    )
    assert verifier.verify(
        receipt_path,
        now=datetime(2026, 6, 21, 8, 30, tzinfo=UTC),
    ) == []
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["selected_delivery"]["human_listened_canary"][
        "perceptual_attestation"
    ]["checks"]["stable_speaker_identity"] = False
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    issues = verifier.verify(
        receipt_path,
        now=datetime(2026, 6, 21, 8, 30, tzinfo=UTC),
    )

    assert (
        "canary completion requires independently verified perceptual attestation"
        in issues
    )


def test_live_whatsapp_receipt_isolates_malformed_numeric_job_per_candidate(
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_whatsapp_audiobook_live_delivery_receipt")
    malformed = _job_receipt(job_id="malformed-whatsapp-job")
    malformed["metadata"]["title"] = "PRIVATE MALFORMED WHATSAPP TITLE"
    malformed["audiobookshelf_import"][
        "public_share_playback_e2e_duration_seconds"
    ] = float("nan")

    receipt = module.build_receipt(
        output_path=tmp_path / "malformed-per-row.generated.json",
        job_receipts=[_job_receipt(job_id="valid-whatsapp-job"), malformed],
        generated_at="2026-06-21T08:20:00Z",
    )

    assert receipt["status"] == "pass"
    assert receipt["candidate_count"] == 2
    assert receipt["failed_candidate_count"] == 1
    assert receipt["selected_delivery"]["job_id_sha256"] == _sha256(
        "valid-whatsapp-job"
    )
    assert receipt["failed_candidates"] == [
        {
            "job_id_sha256": _sha256("malformed-whatsapp-job"),
            "status": "malformed_job_receipt",
            "title_present": True,
            "title_sha256": _sha256("PRIVATE MALFORMED WHATSAPP TITLE"),
            "public_share_status": "",
            "whatsapp_delivery_status": "",
            "failed_codes": ["malformed_job_receipt"],
        }
    ]
    serialized = json.dumps(receipt, allow_nan=False, sort_keys=True)
    assert "PRIVATE MALFORMED WHATSAPP TITLE" not in serialized


def test_whatsapp_scan_never_falls_back_to_stale_same_dir_after_build_error(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_script("materialize_whatsapp_audiobook_live_delivery_receipt")
    from app.services import audiobook_epub_pipeline as pipeline

    job_dir = tmp_path / "private-whatsapp-job"
    job_dir.mkdir()
    (job_dir / "job.json").write_text("{}", encoding="utf-8")
    (job_dir / "job_receipt.json").write_text(
        json.dumps(_job_receipt(job_id="stale-should-not-load")),
        encoding="utf-8",
    )
    secret = "SUPER_SECRET_WHATSAPP_TOKEN"
    private_path = "/private/audiobooks/Hidden WhatsApp.epub"
    monkeypatch.setattr(pipeline, "audiobook_jobs_root", lambda: tmp_path)
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
    assert "private-whatsapp-job" not in serialized


def test_whatsapp_live_receipt_verifier_rejects_load_errors_and_shape(
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_whatsapp_audiobook_live_delivery_receipt")
    verifier = _load_script("verify_whatsapp_audiobook_live_delivery_receipt")
    receipt_path = tmp_path / "load-errors.generated.json"
    materializer.build_receipt(
        output_path=receipt_path,
        job_receipts=[_job_receipt()],
        generated_at="2026-06-21T08:20:00Z",
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["load_errors"] = ["job_receipt_build_failed"]
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    issues = verifier.verify(
        receipt_path,
        now=datetime(2026, 6, 21, 8, 25, tzinfo=UTC),
    )
    assert "load_errors must be empty" in issues

    receipt["load_errors"] = "SECRET /private/Hidden.epub"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    issues = verifier.verify(
        receipt_path,
        now=datetime(2026, 6, 21, 8, 25, tzinfo=UTC),
    )
    assert "load_errors must be an array" in issues
