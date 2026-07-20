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
    title: str | None = None,
    author: str = "EA QA",
    source_kind: str = "epub",
    source_filename: str = "book.epub",
    source_sha256: str = "",
    source_url_sha256: str = "",
    telegram_chat_bound: bool = False,
    telegram_message_bound: bool = False,
    whatsapp_public_share_delivery_status: str = "",
    public_share_telegram_delivery_status: str = "",
    public_share_telegram_message_id_present: bool = False,
    status: str = "audiobookshelf_imported",
    playback_status: str = "accepted",
    playback_accepted: bool = True,
    render_voice_selection: dict[str, object] | None = None,
    telegram_voice_sample_delivery_status: str = "",
    telegram_voice_sample_delivery_expected_count: int = 0,
    telegram_voice_sample_delivery_sent_count: int = 0,
) -> dict[str, object]:
    return {
        "job_id": job_id,
        "status": status,
        "source": {
            "kind": source_kind,
            "source_filename": source_filename,
            "source_sha256": source_sha256,
            "source_url_sha256": source_url_sha256,
        },
        "metadata": {
            "title": title or f"Title for {job_id}",
            "author": author,
        },
        "assembly": {
            "output_file_ready": True,
            "chapter_metadata_embedded": True,
        },
        "telegram": {
            "chat_bound": telegram_chat_bound,
            "message_bound": telegram_message_bound,
            "voice_sample_delivery_status": telegram_voice_sample_delivery_status,
            "voice_sample_delivery_expected_count": telegram_voice_sample_delivery_expected_count,
            "voice_sample_delivery_sent_count": telegram_voice_sample_delivery_sent_count,
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
        "render": {
            "voice_selection": dict(render_voice_selection or {}),
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
    assert receipt["ignored_non_telegram_audiobook_candidate_count"] == 0
    assert receipt["selected_delivery"]["job_id_sha256"] == hashlib.sha256(
        b"explicit-telegram-kind"
    ).hexdigest()
    assert receipt["live_delivery_claim_allowed"] is False
    assert receipt["status"] == "blocked"
    assert "current_v5_narration_plan_missing" in receipt["failed_codes"]


def test_build_receipt_routes_sent_replacement_voice_sample_to_precise_operator_action(tmp_path: Path) -> None:
    module = _load_module()
    receipt = module.build_receipt(
        output_path=tmp_path / "telegram_live_delivery_replacement.json",
        job_receipts=[
            _job_receipt(
                job_id="replacement-voice",
                source_kind="telegram_epub",
                status="waiting_voice_selection",
                playback_status="not_recorded",
                playback_accepted=False,
                render_voice_selection={
                    "status": "waiting_user_choice",
                    "reason": "selected_voice_author_gender_mismatch",
                    "pending_candidate_keys": ["unmixr_dieter_7f88185d"],
                    "replacement_candidate_keys": ["unmixr_dieter_7f88185d"],
                    "pending_batch": [
                        {
                            "preset_key": "unmixr_dieter_7f88185d",
                            "label": "Dieter",
                            "voice_id_sha256": hashlib.sha256(b"voice-dieter").hexdigest(),
                        }
                    ],
                },
                telegram_voice_sample_delivery_status="sent",
                telegram_voice_sample_delivery_expected_count=1,
                telegram_voice_sample_delivery_sent_count=1,
            )
        ],
        generated_at="2026-06-30T00:00:00Z",
        observation_source="test",
    )

    assert receipt["status"] == "blocked"
    assert receipt["head_semantics"] == "source_state"
    assert receipt["source_git_head"]
    assert receipt["source_state_fingerprint"]
    assert receipt["next_action"] == "choose_sent_replacement_voice_sample"
    pending = receipt["pending_user_selected_voice_jobs"]
    assert pending[0]["replacement_candidate_labels"] == ["Dieter"]
    assert pending[0]["voice_sample_delivery_status"] == "sent"
    assert pending[0]["raw_voice_ids_exposed"] is False
    assert pending[0]["callback_tokens_exposed"] is False
    packet = receipt["operator_action_packet"]
    assert packet["user_action_required"] is True
    assert packet["operator_action"] == "choose_sent_replacement_voice_sample"
    assert packet["candidate_labels"] == ["Dieter"]
    assert packet["candidate_count"] == 1
    assert packet["sent_samples_cover_expected"] is True
    assert packet["raw_voice_ids_exposed"] is False
    assert packet["callback_tokens_exposed"] is False
    assert receipt["privacy"]["voice_labels_operator_safe"] is True
    assert receipt["privacy"]["raw_voice_ids_exposed"] is False


def test_build_receipt_blocks_user_choice_when_voice_samples_under_delivered(tmp_path: Path) -> None:
    module = _load_module()
    receipt = module.build_receipt(
        output_path=tmp_path / "telegram_live_delivery_under_delivered_voice_samples.json",
        job_receipts=[
            _job_receipt(
                job_id="under-delivered-voice-choice",
                source_kind="telegram_epub",
                status="waiting_voice_selection",
                playback_status="not_recorded",
                playback_accepted=False,
                render_voice_selection={
                    "status": "waiting_user_choice",
                    "pending_candidate_keys": [
                        "unmixr_seraphina_express_9827708d",
                        "unmixr_seraphina_e1f0fdaf",
                    ],
                    "pending_batch": [
                        {
                            "preset_key": "unmixr_seraphina_express_9827708d",
                            "label": "Seraphina (Express)",
                            "voice_id_sha256": hashlib.sha256(b"voice-seraphina-express").hexdigest(),
                        },
                        {
                            "preset_key": "unmixr_seraphina_e1f0fdaf",
                            "label": "Seraphina",
                            "voice_id_sha256": hashlib.sha256(b"voice-seraphina").hexdigest(),
                        },
                    ],
                },
                telegram_voice_sample_delivery_status="sent",
                telegram_voice_sample_delivery_expected_count=1,
                telegram_voice_sample_delivery_sent_count=1,
            )
        ],
        generated_at="2026-06-30T00:00:00Z",
        observation_source="test",
    )

    assert receipt["status"] == "blocked"
    assert "voice_sample_delivery_underfilled" in receipt["failed_codes"]
    assert receipt["next_action"] == "send_missing_telegram_audiobook_voice_samples_before_user_choice"
    packet = receipt["operator_action_packet"]
    assert packet["user_action_required"] is False
    assert packet["operator_action"] == "send_missing_telegram_audiobook_voice_samples_before_user_choice"
    assert packet["candidate_count"] == 2
    assert packet["voice_sample_delivery_sent_count"] == 1
    assert packet["voice_sample_delivery_expected_count"] == 1
    assert packet["voice_sample_delivery_required_count"] == 2
    assert packet["voice_sample_delivery_missing_count"] == 1
    assert packet["raw_voice_ids_exposed"] is False
    assert packet["callback_tokens_exposed"] is False


def test_build_receipt_blocks_replacement_choice_when_voice_samples_under_delivered(tmp_path: Path) -> None:
    module = _load_module()
    receipt = module.build_receipt(
        output_path=tmp_path / "telegram_live_delivery_under_delivered_replacement_samples.json",
        job_receipts=[
            _job_receipt(
                job_id="under-delivered-replacement-choice",
                source_kind="telegram_epub",
                status="waiting_voice_selection",
                playback_status="not_recorded",
                playback_accepted=False,
                render_voice_selection={
                    "status": "waiting_user_choice",
                    "reason": "voice_sample_generation_failed",
                    "replacement_candidate_keys": [
                        "unmixr_hans_33aa",
                        "unmixr_jurgen_44bb",
                    ],
                    "pending_batch": [
                        {
                            "preset_key": "unmixr_hans_33aa",
                            "label": "Hans",
                            "voice_id_sha256": hashlib.sha256(b"voice-hans").hexdigest(),
                        },
                        {
                            "preset_key": "unmixr_jurgen_44bb",
                            "label": "Jurgen",
                            "voice_id_sha256": hashlib.sha256(b"voice-jurgen").hexdigest(),
                        },
                    ],
                },
                telegram_voice_sample_delivery_status="sent",
                telegram_voice_sample_delivery_expected_count=1,
                telegram_voice_sample_delivery_sent_count=1,
            )
        ],
        generated_at="2026-06-30T00:00:00Z",
        observation_source="test",
    )

    assert receipt["status"] == "blocked"
    assert "voice_sample_delivery_underfilled" in receipt["failed_codes"]
    assert receipt["next_action"] == "send_missing_telegram_audiobook_voice_samples_before_user_choice"
    packet = receipt["operator_action_packet"]
    assert packet["user_action_required"] is False
    assert packet["candidate_count"] == 2
    assert packet["voice_sample_delivery_sent_count"] == 1
    assert packet["voice_sample_delivery_required_count"] == 2


def test_build_receipt_requires_refresh_for_author_gender_mismatched_sent_samples(tmp_path: Path) -> None:
    module = _load_module()
    receipt = module.build_receipt(
        output_path=tmp_path / "telegram_live_delivery_mismatched_voice_samples.json",
        job_receipts=[
            _job_receipt(
                job_id="replacement-voice-wrong-gender",
                source_kind="telegram_epub",
                author="Knuf, Andreas",
                status="waiting_voice_selection",
                playback_status="not_recorded",
                playback_accepted=False,
                render_voice_selection={
                    "status": "waiting_user_choice",
                    "reason": "selected_voice_author_gender_mismatch",
                    "book_profile": {"author_gender_signal": "male"},
                    "pending_candidate_keys": ["unmixr_seraphina_7f88185d"],
                    "replacement_candidate_keys": ["unmixr_seraphina_7f88185d"],
                    "pending_batch": [
                        {
                            "preset_key": "unmixr_seraphina_7f88185d",
                            "label": "Seraphina",
                            "tags": ["audiobook", "narration", "female"],
                            "voice_id_sha256": hashlib.sha256(b"voice-seraphina").hexdigest(),
                        }
                    ],
                },
                telegram_voice_sample_delivery_status="sent",
                telegram_voice_sample_delivery_expected_count=1,
                telegram_voice_sample_delivery_sent_count=1,
            )
        ],
        generated_at="2026-06-30T00:00:00Z",
        observation_source="test",
    )

    assert receipt["status"] == "blocked"
    assert "author_gender_mismatched_voice_samples_pending" in receipt["failed_codes"]
    assert receipt["next_action"] == "refresh_author_gender_matched_voice_samples_before_user_choice"
    packet = receipt["operator_action_packet"]
    assert packet["user_action_required"] is False
    assert packet["operator_action"] == "refresh_author_gender_matched_voice_samples_before_user_choice"
    assert packet["author_gender_signal"] == "male"
    assert packet["author_gender_mismatch_count"] == 1
    pending = receipt["pending_user_selected_voice_jobs"][0]
    assert pending["author_gender_mismatched_voice_samples_pending"] is True
    assert pending["author_gender_matched_candidates_only"] is False
    assert pending["replacement_candidate_labels"] == ["Seraphina"]
    assert pending["raw_voice_ids_exposed"] is False
    assert pending["callback_tokens_exposed"] is False


def test_build_receipt_suppresses_superseded_duplicate_voice_actions(tmp_path: Path) -> None:
    module = _load_module()
    source_sha = hashlib.sha256(b"same-telegram-epub").hexdigest()
    voice_selection = {
        "status": "waiting_user_choice",
        "reason": "selected_voice_author_gender_mismatch",
        "pending_candidate_keys": ["unmixr_dieter_7f88185d"],
        "replacement_candidate_keys": ["unmixr_dieter_7f88185d"],
        "pending_batch": [
            {
                "preset_key": "unmixr_dieter_7f88185d",
                "label": "Dieter",
                "voice_id_sha256": hashlib.sha256(b"voice-dieter").hexdigest(),
            }
        ],
    }

    receipt = module.build_receipt(
        output_path=tmp_path / "telegram_live_delivery_duplicate_suppression.json",
        job_receipts=[
            _job_receipt(
                job_id="replacement-voice-current",
                source_kind="telegram_epub",
                source_sha256=source_sha,
                status="waiting_voice_selection",
                playback_status="not_recorded",
                playback_accepted=False,
                render_voice_selection=voice_selection,
                telegram_voice_sample_delivery_status="sent",
                telegram_voice_sample_delivery_expected_count=1,
                telegram_voice_sample_delivery_sent_count=1,
            ),
            _job_receipt(
                job_id="replacement-voice-duplicate",
                source_kind="telegram_epub",
                source_sha256=source_sha,
                status="superseded_duplicate",
                playback_status="not_recorded",
                playback_accepted=False,
                render_voice_selection=voice_selection,
                telegram_voice_sample_delivery_status="sent",
                telegram_voice_sample_delivery_expected_count=1,
                telegram_voice_sample_delivery_sent_count=1,
            ),
        ],
        generated_at="2026-06-30T00:00:00Z",
        observation_source="test",
    )

    assert receipt["pending_user_selected_voice_job_count"] == 1
    assert receipt["next_action"] == "choose_sent_replacement_voice_sample"
    assert receipt["operator_action_packet"]["candidate_labels"] == ["Dieter"]
    duplicate_suppression = receipt["duplicate_suppression"]
    assert duplicate_suppression["action_required_only"] is True
    assert duplicate_suppression["only_current_jobs_can_require_user_action"] is True
    assert duplicate_suppression["superseded_duplicate_candidate_count"] == 1
    assert duplicate_suppression["suppressed_pending_voice_duplicate_count"] == 1
    assert duplicate_suppression["active_pending_voice_job_count"] == 1
    assert duplicate_suppression["duplicate_active_pending_source_key_count"] == 0
    assert duplicate_suppression["suppressed_voice_candidate_labels"] == ["Dieter"]
    assert duplicate_suppression["raw_voice_ids_exposed"] is False
    assert duplicate_suppression["callback_tokens_exposed"] is False
