from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AUDIOBOOK_PIPELINE_PATH = ROOT / "ea" / "app" / "services" / "audiobook_epub_pipeline.py"
TELEGRAM_CHANNELS_PATH = ROOT / "ea" / "app" / "api" / "routes" / "channels.py"
WHATSAPP_INBOUND_ACTIONS_PATH = ROOT / "ea" / "app" / "services" / "whatsapp_inbound_actions.py"
AUDIOBOOK_TEST_PATH = ROOT / "tests" / "test_telegram_epub_audiobook_pipeline.py"
AUDIOBOOK_LIVE_DELIVERY_TEST_PATH = ROOT / "tests" / "test_telegram_audiobook_live_delivery_receipt.py"
WHATSAPP_AUDIOBOOK_LIVE_DELIVERY_TEST_PATH = ROOT / "tests" / "test_whatsapp_audiobook_live_delivery_receipt.py"
WHATSAPP_AUDIOBOOK_LOCAL_INTAKE_PROOF_TEST_PATH = ROOT / "tests" / "test_whatsapp_audiobook_local_intake_proof.py"
WHATSAPP_AUDIOBOOK_OPERATOR_PROOF_BUNDLE_TEST_PATH = ROOT / "tests" / "test_whatsapp_audiobook_operator_proof_bundle.py"
WHATSAPP_AUDIOBOOK_LIVE_VOICE_SELECTION_SHADOW_TEST_PATH = ROOT / "tests" / "test_whatsapp_audiobook_live_voice_selection_shadow.py"
WHATSAPP_AUDIOBOOK_PUBLIC_SHARE_PLAYBACK_TEST_PATH = ROOT / "tests" / "test_whatsapp_audiobook_public_share_playback.py"
WHATSAPP_WEB_ACTION_PROCESSOR_READINESS_TEST_PATH = ROOT / "tests" / "test_whatsapp_web_action_processor_readiness_materializer.py"
AUDIOBOOK_SKILL_PATH = ROOT / ".codex-design" / "ea" / "AUDIOBOOK_EPUB_TELEGRAM_SKILL.md"
LTD_MAP_PATH = ROOT / ".codex-design" / "ea" / "LTD_INTEGRATION_MAP.md"
AUDIOBOOK_LIVE_DELIVERY_SCRIPT_PATH = ROOT / "ea" / "scripts" / "materialize_telegram_audiobook_live_delivery_receipt.py"
WHATSAPP_AUDIOBOOK_LIVE_DELIVERY_SCRIPT_PATH = ROOT / "ea" / "scripts" / "materialize_whatsapp_audiobook_live_delivery_receipt.py"
WHATSAPP_AUDIOBOOK_LOCAL_INTAKE_PROOF_SCRIPT_PATH = ROOT / "ea" / "scripts" / "materialize_whatsapp_audiobook_local_intake_proof.py"
WHATSAPP_AUDIOBOOK_OPERATOR_PROOF_BUNDLE_SCRIPT_PATH = ROOT / "ea" / "scripts" / "materialize_whatsapp_audiobook_operator_proof_bundle.py"
WHATSAPP_AUDIOBOOK_LIVE_VOICE_SELECTION_SHADOW_SCRIPT_PATH = ROOT / "ea" / "scripts" / "materialize_whatsapp_audiobook_live_voice_selection_shadow.py"
WHATSAPP_AUDIOBOOK_PUBLIC_SHARE_PLAYBACK_SCRIPT_PATH = ROOT / "ea" / "scripts" / "verify_whatsapp_audiobook_public_share_playback.py"
WHATSAPP_WEB_ACTION_PROCESSOR_READINESS_SCRIPT_PATH = ROOT / "scripts" / "materialize_whatsapp_web_action_processor_readiness.py"
ENV_EXAMPLE_PATH = ROOT / ".env.example"
ENV_LOCAL_EXAMPLE_PATH = ROOT / ".env.local.example"
DOCKER_COMPOSE_PATH = ROOT / "docker-compose.yml"
DOCKER_COMPOSE_WHATSAPP_PATH = ROOT / "docker-compose.whatsapp-web-session.yml"

AUDIOBOOK_QUALITY_ENV_NAMES = (
    "EA_AUDIOBOOK_EBOOK_CONVERT_BIN",
    "EA_AUDIOBOOK_KINDLE_CONVERT_TIMEOUT_SECONDS",
    "EA_AUDIOBOOK_PARAGRAPH_PAUSES_ENABLED",
    "EA_AUDIOBOOK_PARAGRAPH_PAUSE_SECONDS",
    "EA_AUDIOBOOK_PUBLICATION_STT_GATE_REQUIRED",
    "EA_AUDIOBOOK_PUBLICATION_STT_GATE_ENABLED",
    "EA_AUDIOBOOK_PUBLICATION_STT_COMMAND",
    "EA_AUDIOBOOK_PUBLICATION_STT_SAMPLE_SECONDS",
    "EA_AUDIOBOOK_PUBLICATION_STT_SAMPLE_COUNT",
    "EA_AUDIOBOOK_PUBLICATION_STT_MIN_BOOK_TOKEN_OVERLAP",
)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _has(text: str, *needles: str) -> bool:
    return all(needle in text for needle in needles)


def _function_body(text: str, name: str) -> str:
    marker = f"def {name}("
    start = text.find(marker)
    if start < 0:
        return ""
    next_def = text.find("\ndef ", start + len(marker))
    return text[start:] if next_def < 0 else text[start:next_def]


def _env_template_has_names(text: str) -> bool:
    return all(f"{name}=" in text for name in AUDIOBOOK_QUALITY_ENV_NAMES)


def _compose_has_names(text: str) -> bool:
    return all(f"{name}=${{{name}" in text for name in AUDIOBOOK_QUALITY_ENV_NAMES)


def verify_audiobook_epub_quality_contract() -> dict[str, object]:
    pipeline = _read(AUDIOBOOK_PIPELINE_PATH)
    channels = _read(TELEGRAM_CHANNELS_PATH)
    whatsapp_inbound_actions = _read(WHATSAPP_INBOUND_ACTIONS_PATH)
    whatsapp_voice_sender = _function_body(channels, "_whatsapp_send_audiobook_voice_samples")
    tests = _read(AUDIOBOOK_TEST_PATH)
    live_tests = _read(AUDIOBOOK_LIVE_DELIVERY_TEST_PATH)
    whatsapp_live_tests = _read(WHATSAPP_AUDIOBOOK_LIVE_DELIVERY_TEST_PATH)
    whatsapp_local_proof_tests = _read(WHATSAPP_AUDIOBOOK_LOCAL_INTAKE_PROOF_TEST_PATH)
    whatsapp_bundle_tests = _read(WHATSAPP_AUDIOBOOK_OPERATOR_PROOF_BUNDLE_TEST_PATH)
    whatsapp_voice_selection_shadow_tests = _read(WHATSAPP_AUDIOBOOK_LIVE_VOICE_SELECTION_SHADOW_TEST_PATH)
    whatsapp_public_share_playback_tests = _read(WHATSAPP_AUDIOBOOK_PUBLIC_SHARE_PLAYBACK_TEST_PATH)
    whatsapp_readiness_tests = _read(WHATSAPP_WEB_ACTION_PROCESSOR_READINESS_TEST_PATH)
    skill = _read(AUDIOBOOK_SKILL_PATH)
    ltd = _read(LTD_MAP_PATH)
    live_script = _read(AUDIOBOOK_LIVE_DELIVERY_SCRIPT_PATH)
    whatsapp_live_script = _read(WHATSAPP_AUDIOBOOK_LIVE_DELIVERY_SCRIPT_PATH)
    whatsapp_local_proof_script = _read(WHATSAPP_AUDIOBOOK_LOCAL_INTAKE_PROOF_SCRIPT_PATH)
    whatsapp_bundle_script = _read(WHATSAPP_AUDIOBOOK_OPERATOR_PROOF_BUNDLE_SCRIPT_PATH)
    whatsapp_voice_selection_shadow_script = _read(WHATSAPP_AUDIOBOOK_LIVE_VOICE_SELECTION_SHADOW_SCRIPT_PATH)
    whatsapp_public_share_playback_script = _read(WHATSAPP_AUDIOBOOK_PUBLIC_SHARE_PLAYBACK_SCRIPT_PATH)
    whatsapp_readiness_script = _read(WHATSAPP_WEB_ACTION_PROCESSOR_READINESS_SCRIPT_PATH)
    env_example = _read(ENV_EXAMPLE_PATH)
    env_local_example = _read(ENV_LOCAL_EXAMPLE_PATH)
    docker_compose = _read(DOCKER_COMPOSE_PATH)
    docker_compose_whatsapp = _read(DOCKER_COMPOSE_WHATSAPP_PATH)

    checks = {
        "voice_audition_runtime_present": _has(
            pipeline,
            "prepare_audiobook_voice_audition",
            "audiobook_voice_audition_sample_messages",
            "choose_audiobook_voice",
        ),
        "telegram_inline_voice_controls_present": _has(
            channels,
            "_telegram_send_audiobook_voice_samples",
            "Use this",
            "Dismiss",
        ),
        "telegram_dismiss_immediate_replacement_present": _has(
            channels,
            "replacement audiobook voice",
            "action == \"dismiss\"",
            "_telegram_audiobook_voice_sample_subset",
        ),
        "author_gender_voice_signal_present": _has(
            pipeline,
            "_infer_author_gender",
            "author_gender_signal",
            "author_gender_match",
            "explicit_approved_metadata",
            "not_available_without_explicit_approved_metadata",
        )
        and "test_voice_selection_does_not_infer_author_gender_from_name" in tests
        and "test_voice_audition_does_not_infer_author_gender_from_name" in tests,
        "telegram_voice_sample_status_diagnostic_present": _has(
            pipeline,
            "voice_sample_delivery",
            "record_audiobook_voice_sample_delivery",
        )
        and "test_voice_sample_delivery_summary_prevents_false_sent_reply" in tests,
        "alice_blocklist_default_present": "EA_AUDIOBOOK_VOICE_BLOCKLIST" in pipeline
        and "alice" in pipeline.lower()
        and "Alice is deprioritized" in skill,
        "quiet_tail_quality_gates_present": _has(
            pipeline,
            "quiet_tail",
            "EA_AUDIOBOOK_AUDIO_QUIET_TAIL_RMS_THRESHOLD",
            "tail_volume_probe_failed",
        )
        and "test_audio_publication_gate_blocks_quiet_tail" in tests,
        "publication_stt_required_by_default_present": _has(
            pipeline,
            "def _audiobook_publication_stt_required()",
            'EA_AUDIOBOOK_PUBLICATION_STT_GATE_REQUIRED", True',
            "stt_transcript_not_book_text",
            "_build_audiobook_publication_stt_gate",
        )
        and "test_audio_publication_gate_requires_stt_by_default" in tests
        and "test_audio_publication_gate_blocks_stt_text_that_is_not_from_book" in tests,
        "paragraph_pause_rendering_present": _has(
            pipeline,
            "EA_AUDIOBOOK_PARAGRAPH_PAUSES_ENABLED",
            "EA_AUDIOBOOK_PARAGRAPH_PAUSE_SECONDS",
            "_write_silence_wav",
            "_chapter_text_segment_rows",
            "paragraph_pause_count",
            "paragraph-pause.wav",
        )
        and "test_unmixr_render_inserts_silence_between_paragraphs" in tests,
        "audiobook_quality_env_surface_present": (
            _env_template_has_names(env_example)
            and _env_template_has_names(env_local_example)
            and _compose_has_names(docker_compose)
            and _compose_has_names(docker_compose_whatsapp)
        ),
        "kindle_source_formats_present": (
            _has(
                pipeline,
                "_KINDLE_SOURCE_EXTENSIONS",
                ".azw3",
                ".mobi",
                "EA_AUDIOBOOK_EBOOK_CONVERT_BIN",
                "EA_AUDIOBOOK_KINDLE_CONVERT_TIMEOUT_SECONDS",
                "_convert_kindle_source_to_epub",
                "operator_supplied_kindle_file",
            )
            and "test_azw3_document_is_accepted_as_audiobook_source" in tests
            and "test_create_job_from_azw3_converts_to_epub_before_extraction" in tests
            and "test_kindle_source_formats_complete_audiobook_pipeline_without_external_tts" in tests
            and "test_telegram_azw3_turn_decision_routes_as_audiobook_source" in tests
        ),
        "voice_feedback_learning_present": (
            _has(
                pipeline,
                "VOICE_FEEDBACK_CONTRACT_NAME",
                "_audiobook_voice_feedback_adjustment",
                "record_audiobook_voice_feedback",
                "record_audiobook_completed_voice_feedback",
                "voice_feedback_total_adjustment",
                "selected_count * 8 - dismissed_count * 5",
                "same_book_voice_adjustment",
                "completed_audiobook_ready",
            )
            and "test_voice_selection_learns_from_selected_and_dismissed_feedback" in tests
            and "test_voice_selection_reuses_completed_same_book_voice" in tests
            and "assert selected[\"voice_feedback_adjustment\"] > 0" in tests
            and "assert dismissed[\"voice_feedback_adjustment\"] < 0" in tests
            and "assert selected[\"same_book_voice_reuse\"] is True" in tests
        ),
        "m4b_chapters_and_cover_present": _has(
            pipeline,
            "_write_ffmetadata_file",
            "cover_embedded",
            "_m4b_cover_image_path",
            "generated-audiobook-cover.jpg",
        )
        and "chaptered-M4B fallback" in ltd,
        "m4b_structure_probe_present": (
            (ROOT / "ea" / "scripts" / "materialize_audiobook_m4b_structure_probe.py").is_file()
            and (ROOT / "ea" / "scripts" / "verify_audiobook_m4b_structure_probe.py").is_file()
        ),
        "delayed_audiobookshelf_share_followup_present": _has(
            pipeline,
            "resume_due_audiobook_jobs",
            "_audiobook_public_share_followup_pending",
            "_refresh_audiobookshelf_public_share_for_job",
        ),
        "live_telegram_audiobook_delivery_receipt_present": _has(
            live_tests + live_script,
            "ea.telegram_audiobook_live_delivery_receipt.v1",
            "live_delivery_claim_allowed",
        ),
        "live_whatsapp_audiobook_delivery_receipt_present": _has(
            whatsapp_live_tests + whatsapp_live_script,
            "ea.whatsapp_audiobook_live_delivery_receipt.v1",
            "live_delivery_claim_allowed",
            "whatsapp_audiobook_job_missing",
            "stage_summary",
            "waiting_voice_choice",
            "render_or_import_pending",
            "waiting_provider_throttle",
            "waiting_provider_pacing",
        ),
        "local_whatsapp_audiobook_intake_proof_present": _has(
            whatsapp_local_proof_tests + whatsapp_local_proof_script,
            "ea.whatsapp_audiobook_local_epub_intake_proof.v1",
            "three_voice_samples_sent",
            "voice_choice_callback_processed",
            "audiobookshelf_imported",
            "player_scoped_reference_ready",
            "player_scoped_reference_resolves",
            "player_scoped_audio_probe_passed",
            "player_http_metadata_ready",
            "player_http_audio_download_works",
            "player_probe_summary",
            "player_http_probe_summary",
            "whatsapp_public_share_sent",
            "public_share_whatsapp_delivery_status",
            "waiting_machine_playback_verification",
            "choose_whatsapp_audiobook_voice_sample",
            "raw_sender_ref_exposed",
        ),
        "whatsapp_voice_callbacks_are_native": (
            _has(
                whatsapp_voice_sender,
                "whatsapp_inbound_actions.encode_whatsapp_audiobook_voice_callback",
                "sender_ref=recipient",
                "Use this",
                "Dismiss",
            )
            and "_telegram_encode_audiobook_voice_callback" not in whatsapp_voice_sender
            and "_whatsapp_audiobook_callback_config" not in channels
            and _has(
                whatsapp_inbound_actions,
                "def encode_whatsapp_audiobook_voice_callback",
                "EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET",
                "EA_WHATSAPP_CALLBACK_SECRET",
                "EA_WHATSAPP_WEB_SESSION_API_TOKEN",
            )
            and "EA_TELEGRAM_CALLBACK_SECRET" not in whatsapp_inbound_actions
        ),
        "whatsapp_audiobook_operator_proof_bundle_present": _has(
            whatsapp_bundle_tests + whatsapp_bundle_script,
            "ea.whatsapp_audiobook_operator_proof_bundle.v1",
            "waiting_for_live_epub",
            "historical_public_share_playback_proven",
            "live_public_share_playback_verified_or_not_required",
            "public_share_playback",
            "local_epub_intake_proof_passed",
            "local_proof_selects_voice_and_sends_share",
            "local_proof_player_probe_passed",
            "local_proof_player_http_route_passed",
            "delivery_stage_counts",
            "player_probe",
            "player_http_probe",
            "runtime_alignment",
            "execution_runtime",
            "container_stdout_json_present",
            "live_processor_runtime_alignment_evaluated",
            "live_sidecar_inbox",
            "live_sidecar_inbox_accessible",
            "epub_media_candidate_count",
            "conversation_fallback",
            "conversation_fallback_enabled",
            "conversation_fallback_epub_candidate_count",
            "raw_text_exposed",
            "raw_sender_exposed",
            "raw_message_ids_exposed",
            "state_file_match",
            "secret_values_exposed",
            "live_action_processor_ready",
            "live_action_processor_ran",
            "live_processor",
            "fix_whatsapp_action_processor_run",
        ),
        "whatsapp_live_voice_selection_shadow_present": _has(
            whatsapp_voice_selection_shadow_tests + whatsapp_voice_selection_shadow_script,
            "ea.whatsapp_audiobook_live_voice_selection_shadow.v1",
            "shadow_text_fallback_ready",
            "dismiss_named_action",
            "dismiss_all_action",
            "fallback_prompt_mentions_text_commands",
        ),
        "whatsapp_public_share_playback_proof_present": _has(
            whatsapp_public_share_playback_tests + whatsapp_public_share_playback_script,
            "ea.whatsapp_audiobook_public_share_playback_e2e.v1",
            "record_playback_e2e",
            "current_time_after_play_seconds",
            "raw_url_exposed",
        ),
        "whatsapp_web_action_processor_readiness_present": _has(
            whatsapp_readiness_tests + whatsapp_readiness_script,
            "ea.whatsapp_web_action_processor_readiness.v1",
            "runtime_ready_claim_allowed",
            "live_delivery_claim_allowed",
            "send_epub_over_whatsapp_to_start_or_refresh_live_audiobook_flow",
            "restore_whatsapp_web_session_sidecar_readiness",
            "seed_whatsapp_callback_secret_and_rerun_readiness",
        ),
        "focused_tests_cover_m4b_structure_probe": _has(
            tests,
            "test_existing_chapter_wavs_merge_with_ffmpeg_fallback_and_import",
            "cover_embedded",
            "cover_streams",
        ),
    }
    issue_by_check = {
        "voice_audition_runtime_present": "voice_audition_runtime_present_missing",
        "telegram_inline_voice_controls_present": "telegram_inline_voice_controls_present_missing",
        "telegram_dismiss_immediate_replacement_present": "telegram_dismiss_immediate_replacement_present_missing",
        "author_gender_voice_signal_present": "author_gender_voice_signal_present_missing",
        "telegram_voice_sample_status_diagnostic_present": "telegram_voice_sample_status_diagnostic_present_missing",
        "alice_blocklist_default_present": "alice_blocklist_default_present_missing",
        "quiet_tail_quality_gates_present": "quiet_tail_quality_gates_present_missing",
        "publication_stt_required_by_default_present": "publication_stt_required_by_default_present_missing",
        "paragraph_pause_rendering_present": "paragraph_pause_rendering_present_missing",
        "audiobook_quality_env_surface_present": "audiobook_quality_env_surface_present_missing",
        "kindle_source_formats_present": "kindle_source_formats_present_missing",
        "voice_feedback_learning_present": "voice_feedback_learning_present_missing",
        "m4b_chapters_and_cover_present": "m4b_chapters_and_cover_present_missing",
        "m4b_structure_probe_present": "m4b_structure_probe_present_missing",
        "delayed_audiobookshelf_share_followup_present": "delayed_audiobookshelf_share_followup_present_missing",
        "live_telegram_audiobook_delivery_receipt_present": "live_telegram_audiobook_delivery_receipt_present_missing",
        "live_whatsapp_audiobook_delivery_receipt_present": "live_whatsapp_audiobook_delivery_receipt_present_missing",
        "local_whatsapp_audiobook_intake_proof_present": "local_whatsapp_audiobook_intake_proof_present_missing",
        "whatsapp_voice_callbacks_are_native": "whatsapp_voice_callbacks_are_native_missing",
        "whatsapp_audiobook_operator_proof_bundle_present": "whatsapp_audiobook_operator_proof_bundle_present_missing",
        "whatsapp_live_voice_selection_shadow_present": "whatsapp_live_voice_selection_shadow_present_missing",
        "whatsapp_public_share_playback_proof_present": "whatsapp_public_share_playback_proof_present_missing",
        "whatsapp_web_action_processor_readiness_present": "whatsapp_web_action_processor_readiness_present_missing",
        "focused_tests_cover_m4b_structure_probe": "focused_tests_cover_audio_and_m4b_missing",
    }
    issues = [issue for key, issue in issue_by_check.items() if not checks[key]]
    return {
        "contract_name": "ea.telegram_epub_audiobook_quality_contract.v1",
        "status": "fail" if issues else "pass",
        "issues": issues,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    result = verify_audiobook_epub_quality_contract()
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
