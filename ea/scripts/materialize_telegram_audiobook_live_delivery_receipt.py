from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hmac
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[2]
EA_ROOT = ROOT / "ea"
DEFAULT_OUTPUT = ROOT / ".codex-studio" / "published" / "telegram_audiobook_live_delivery.generated.json"
CONTRACT_NAME = "ea.telegram_audiobook_live_delivery_receipt.v2"
LEGACY_CONTRACT_NAME = "ea.telegram_audiobook_live_delivery_receipt.v1"
NARRATION_PLAN_CONTRACT_NAME = "ea.audiobook_narration_plan.v5"
HUMAN_LISTENED_CANARY_CONTRACT_NAME = "ea.audiobook_human_listened_canary_acceptance.v1"
PERCEPTUAL_ATTESTATION_CONTRACT_NAME = "ea.audiobook_perceptual_attestation.v1"
PERCEPTUAL_ATTESTATION_VERSION = 1
PERCEPTUAL_ATTESTATION_CHECKS = (
    "no_clipped_starts_or_ends",
    "no_abrupt_level_reset",
    "natural_paragraph_and_scene_timing",
    "distinct_dialogue_voice",
    "stable_speaker_identity",
    "correct_words",
    "useful_chapter_navigation",
)
LIVE_PROOF_MAX_AGE_SECONDS = 86_400
LIVE_PROOF_FUTURE_SKEW_SECONDS = 300
PUBLIC_LOAD_ERROR_CODES = frozenset(
    {
        "audiobook_pipeline_import_failed",
        "job_manifest_discovery_failed",
        "job_receipt_build_failed",
        "job_receipt_discovery_failed",
        "stored_job_receipt_load_failed",
        "stored_job_receipt_invalid_shape",
        "job_receipts_json_load_failed",
        "job_receipts_json_invalid_shape",
        "receipt_load_failed",
    }
)
HUMAN_LISTENED_CANARY_DIGEST_FIELDS = (
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
TELEGRAM_INTEGRATION_PATH = "/integrations/telegram"
TELEGRAM_INTEGRATION_LABEL = "Open Telegram"
CHANNEL_LOOP_PATH = "/app/channel-loop"
CHANNEL_LOOP_LABEL = "Open channel loop"
ACTION_METHOD = "get"
TELEGRAM_AUDIOBOOK_SOURCE_KINDS = {
    "audiobook_epub",
    "ebook",
    "epub",
    "kindle",
    "telegram_epub",
    "telegram_ebook",
}
TELEGRAM_AUDIOBOOK_SOURCE_SUFFIXES = {".azw", ".azw3", ".epub", ".mobi", ".prc"}
USER_SELECTED_VOICE_DELIVERY_BLOCKING_CODES = {
    "job_not_audiobookshelf_imported",
    "m4b_output_file_not_ready",
    "m4b_chapter_metadata_not_embedded",
    "audiobookshelf_import_not_imported",
    "audiobookshelf_target_file_not_ready",
    "machine_playback_e2e_not_verified",
}

TELEGRAM_ACTION_SURFACES = {
    "capture_real_user_playback_acceptance_or_close_operator_loop": (
        TELEGRAM_INTEGRATION_PATH,
        TELEGRAM_INTEGRATION_LABEL,
        ACTION_METHOD,
    ),
    "choose_one_telegram_audiobook_voice_sample": (
        TELEGRAM_INTEGRATION_PATH,
        TELEGRAM_INTEGRATION_LABEL,
        ACTION_METHOD,
    ),
    "choose_explicit_replacement_voice_or_restore_selected_provider": (
        TELEGRAM_INTEGRATION_PATH,
        TELEGRAM_INTEGRATION_LABEL,
        ACTION_METHOD,
    ),
    "choose_sent_replacement_voice_sample": (
        TELEGRAM_INTEGRATION_PATH,
        TELEGRAM_INTEGRATION_LABEL,
        ACTION_METHOD,
    ),
    "finish_user_selected_voice_audiobook_before_sending_public_share_link": (
        TELEGRAM_INTEGRATION_PATH,
        TELEGRAM_INTEGRATION_LABEL,
        ACTION_METHOD,
    ),
    "wait_for_scheduler_to_send_audiobookshelf_public_share_link_or_fix_telegram_delivery": (
        CHANNEL_LOOP_PATH,
        CHANNEL_LOOP_LABEL,
        ACTION_METHOD,
    ),
    "run_public_share_machine_playback_e2e_before_claiming_live_delivery": (
        CHANNEL_LOOP_PATH,
        CHANNEL_LOOP_LABEL,
        ACTION_METHOD,
    ),
    "resume_or_rebuild_telegram_audiobook_render_before_public_share_delivery": (
        CHANNEL_LOOP_PATH,
        CHANNEL_LOOP_LABEL,
        ACTION_METHOD,
    ),
    "wait_for_audiobookshelf_scan_then_rerun_share_followup": (
        CHANNEL_LOOP_PATH,
        CHANNEL_LOOP_LABEL,
        ACTION_METHOD,
    ),
    "inspect_failed_audiobook_delivery_candidates": (
        CHANNEL_LOOP_PATH,
        CHANNEL_LOOP_LABEL,
        ACTION_METHOD,
    ),
    "close_operator_loop": (
        CHANNEL_LOOP_PATH,
        CHANNEL_LOOP_LABEL,
        ACTION_METHOD,
    ),
    "refresh_author_gender_matched_voice_samples_before_user_choice": (
        CHANNEL_LOOP_PATH,
        CHANNEL_LOOP_LABEL,
        ACTION_METHOD,
    ),
    "send_missing_telegram_audiobook_voice_samples_before_user_choice": (
        CHANNEL_LOOP_PATH,
        CHANNEL_LOOP_LABEL,
        ACTION_METHOD,
    ),
}


if str(EA_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_ROOT))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.source_state_head import resolve_source_state_head
from scripts.source_state_head import resolve_source_worktree_fingerprint


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _logical_output_path(output_path: Path) -> str:
    """Return a portable artifact identity, never a machine-local path."""
    try:
        return output_path.resolve().relative_to(ROOT.resolve()).as_posix()
    except (OSError, ValueError):
        return output_path.name


def _sha256_text(value: object) -> str:
    text = str(value or "").strip()
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""


def _source_state_fields() -> dict[str, str]:
    return {
        "source_git_head": resolve_source_state_head(ROOT),
        "head_semantics": "source_state",
        "source_state_fingerprint": resolve_source_worktree_fingerprint(ROOT),
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
    }


def _is_sha256(value: object) -> bool:
    text = str(value or "").strip()
    return len(text) == 64 and all(ch in "0123456789abcdef" for ch in text.lower())


def _canary_receipt_hmac_key(channel: str) -> str:
    dedicated = str(
        os.getenv("EA_AUDIOBOOK_CANARY_RECEIPT_HMAC_KEY") or ""
    ).strip()
    if dedicated:
        return dedicated
    if channel == "telegram":
        return (
            str(os.getenv("EA_TELEGRAM_CALLBACK_SECRET") or "").strip()
            or str(os.getenv("EA_TELEGRAM_BOT_TOKEN") or "").strip()
        )
    if channel != "whatsapp":
        return ""
    configured = (
        str(os.getenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET") or "").strip()
        or str(os.getenv("EA_WHATSAPP_CALLBACK_SECRET") or "").strip()
        or str(os.getenv("EA_WHATSAPP_WEB_SESSION_API_TOKEN") or "").strip()
    )
    if configured:
        return configured
    for raw_path in (
        str(
            os.getenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET_FILE") or ""
        ).strip(),
        "/run/secrets/whatsapp_audiobook_callback_secret",
        "/config/whatsapp_audiobook_callback_secret",
        "/app/config/whatsapp_audiobook_callback_secret",
    ):
        if not raw_path:
            continue
        try:
            secret = Path(raw_path).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if secret:
            return secret
    return ""


def _as_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _receipt_nonnegative_int(value: object) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        raise ValueError("invalid_receipt_integer")
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise ValueError("invalid_receipt_integer")
    parsed = int(value)
    if parsed < 0:
        raise ValueError("invalid_receipt_integer")
    return parsed


def _receipt_nonnegative_float(value: object) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, bool):
        raise ValueError("invalid_receipt_number")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError("invalid_receipt_number")
    return parsed


def _parse_utc(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _freshness_evidence(value: object, *, reference: datetime) -> dict[str, object]:
    observed = _parse_utc(value)
    if observed is None:
        return {
            "timestamp_present": False,
            "fresh": False,
            "age_seconds": None,
            "max_age_seconds": LIVE_PROOF_MAX_AGE_SECONDS,
            "future_skew_seconds": None,
        }
    age_seconds = (reference - observed).total_seconds()
    return {
        "timestamp_present": True,
        "fresh": -LIVE_PROOF_FUTURE_SKEW_SECONDS <= age_seconds <= LIVE_PROOF_MAX_AGE_SECONDS,
        "age_seconds": round(max(age_seconds, 0.0), 3),
        "max_age_seconds": LIVE_PROOF_MAX_AGE_SECONDS,
        "future_skew_seconds": round(max(-age_seconds, 0.0), 3),
    }


def _expected_chapter_count(job: dict[str, object]) -> int:
    chapters = [row for row in _as_list(job.get("chapters")) if isinstance(row, dict)]
    if chapters:
        indexes = {
            _receipt_nonnegative_int(row.get("index") or row.get("chapter_index") or 0)
            for row in chapters
        }
        return len([index for index in indexes if index > 0])
    totals = _as_dict(job.get("totals"))
    return _receipt_nonnegative_int(
        totals.get("chapter_count") or totals.get("chapters") or 0
    )


def _canonical_acceptance_sha256(playback: dict[str, object]) -> str:
    binding = {key: playback.get(key) for key in HUMAN_LISTENED_CANARY_DIGEST_FIELDS}
    return hashlib.sha256(
        json.dumps(binding, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _canonical_perceptual_attestation_sha256(
    *,
    channel: str,
    checks: dict[str, object],
    all_checks_attested: bool,
) -> str:
    canonical = {
        "contract_name": PERCEPTUAL_ATTESTATION_CONTRACT_NAME,
        "version": PERCEPTUAL_ATTESTATION_VERSION,
        "channel": str(channel or "").strip().lower(),
        "checks": {
            key: checks.get(key) is True
            for key in PERCEPTUAL_ATTESTATION_CHECKS
        },
        "all_checks_attested": all_checks_attested is True,
    }
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _performance_evidence(job: dict[str, object]) -> tuple[dict[str, object], list[str]]:
    render = _as_dict(job.get("render"))
    plan = _as_dict(render.get("narration_plan"))
    cast = _as_dict(render.get("speaker_cast")) or _as_dict(plan.get("speaker_cast"))
    mastering = _as_dict(render.get("mastering"))
    quality = _as_dict(render.get("audio_quality"))
    publication = _as_dict(job.get("audio_publication_gate"))
    stt = _as_dict(publication.get("stt"))
    loudness = _as_dict(publication.get("loudness"))
    imported = _as_dict(job.get("audiobookshelf_import"))
    assembly = _as_dict(job.get("assembly"))
    source = _as_dict(job.get("source"))
    expected_chapters = _expected_chapter_count(job)
    issues: list[str] = []

    if expected_chapters <= 0:
        issues.append("expected_chapter_count_missing")
    if str(plan.get("contract_name") or "") != NARRATION_PLAN_CONTRACT_NAME:
        issues.append("current_v5_narration_plan_missing")
    if str(plan.get("status") or "") != "ready":
        issues.append("exact_narration_plan_not_ready")
    if str(plan.get("source_coverage") or "") != "complete" or plan.get("coverage_complete") is not True:
        issues.append("exact_narration_plan_coverage_incomplete")
    if plan.get("source_integrity_verified") is not True:
        issues.append("exact_narration_plan_source_integrity_unverified")
    for key, code in (
        ("plan_sha256", "narration_plan_sha256_missing"),
        ("source_aggregate_sha256", "narration_source_sha256_missing"),
        ("render_signature", "narration_render_signature_missing"),
    ):
        if not _is_sha256(plan.get(key)):
            issues.append(code)
    if _receipt_nonnegative_int(plan.get("chapter_count") or 0) != expected_chapters:
        issues.append("narration_plan_chapter_count_mismatch")

    dialogue_count = _receipt_nonnegative_int(
        plan.get("dialogue_span_count") or plan.get("dialogue_passage_count") or 0
    )
    cast_required = dialogue_count > 0
    cast_ready = (
        str(cast.get("status") or "") == "ready"
        and _is_sha256(cast.get("cast_map_sha256"))
        and cast.get("narrator_voice_excluded") is True
        and _receipt_nonnegative_int(cast.get("distinct_dialogue_voice_count") or 0) > 0
    )
    if cast_required and not cast_ready:
        issues.append("dialogue_cast_not_ready_or_distinct")

    expected_final_tracks = _receipt_nonnegative_int(
        mastering.get("expected_final_track_count") or 0
    )
    final_track_mode = str(mastering.get("final_track_mode") or "").strip()
    cinematic_timeline_sha256 = str(
        assembly.get("cinematic_timeline_sha256") or ""
    ).strip()
    cinematic = bool(cinematic_timeline_sha256)
    mastering_counts_match = (
        expected_final_tracks > 0
        and _receipt_nonnegative_int(mastering.get("final_track_ready_count") or 0)
        == expected_final_tracks
        and _receipt_nonnegative_int(
            mastering.get("signature_published_or_verified_count") or 0
        )
        == expected_final_tracks
    )
    if (
        str(mastering.get("status") or "") != "mastered"
        or not _is_sha256(mastering.get("contract_sha256"))
        or not _is_sha256(mastering.get("signature_set_sha256"))
        or mastering.get("segment_mastering") is not False
        or not mastering_counts_match
        or (
            cinematic
            and (
                final_track_mode != "cinematic_master"
                or expected_final_tracks != 1
            )
        )
        or (
            not cinematic
            and (
                final_track_mode != "chapter_masters"
                or expected_final_tracks != expected_chapters
            )
        )
    ):
        issues.append("final_mastering_or_signature_incomplete")
    final_quality = mastering.get("final_audio_quality")
    if isinstance(final_quality, list):
        final_quality_pass = (
            len(final_quality) == expected_final_tracks
            and all(isinstance(row, dict) and str(row.get("status") or "") == "pass" for row in final_quality)
        )
    elif isinstance(final_quality, dict):
        final_quality_pass = str(final_quality.get("status") or "") == "pass"
    else:
        final_quality_pass = False
    if str(quality.get("status") or "") != "pass" or not final_quality_pass:
        issues.append("final_audio_quality_not_pass")

    target_sha256 = str(imported.get("target_file_sha256") or "").strip().lower()
    publication_sha256 = str(publication.get("target_file_sha256") or "").strip().lower()
    publication_gate_sha256 = str(publication.get("gate_sha256") or "").strip().lower()
    if (
        str(publication.get("status") or "") != "pass"
        or str(publication.get("contract_name") or "")
        != "ea.audiobook_publication_audio_gate.v2"
        or bool(_as_list(publication.get("issues")))
        or _receipt_nonnegative_int(publication.get("chapters") or 0)
        != expected_chapters
        or not _is_sha256(target_sha256)
        or publication_sha256 != target_sha256
    ):
        issues.append("publication_gate_or_chapter_count_not_exact")
    expected_gate_bindings = {
        "source_sha256": str(source.get("source_sha256") or "").strip().lower(),
        "source_aggregate_sha256": str(plan.get("source_aggregate_sha256") or "").strip().lower(),
        "narration_plan_sha256": str(plan.get("plan_sha256") or "").strip().lower(),
        "render_signature_sha256": str(plan.get("render_signature") or "").strip().lower(),
        "mastering_signature_set_sha256": str(mastering.get("signature_set_sha256") or "").strip().lower(),
    }
    if cast_required:
        expected_gate_bindings["cast_map_sha256"] = str(
            cast.get("cast_map_sha256") or ""
        ).strip().lower()
    if (
        not _is_sha256(publication_gate_sha256)
        or any(
            not _is_sha256(expected)
            or str(publication.get(key) or "").strip().lower() != expected
            for key, expected in expected_gate_bindings.items()
        )
        or publication.get("chapter_count_matches") is not True
        or _receipt_nonnegative_int(publication.get("expected_chapter_count") or 0)
        != expected_chapters
        or _receipt_nonnegative_int(publication.get("actual_chapter_count") or 0)
        != expected_chapters
    ):
        issues.append("publication_gate_evidence_binding_mismatch")
    try:
        integrated_lufs = float(loudness.get("integrated_lufs"))
        true_peak_dbtp = float(loudness.get("true_peak_dbtp"))
        min_integrated_lufs = float(loudness.get("min_integrated_lufs"))
        max_integrated_lufs = float(loudness.get("max_integrated_lufs"))
        max_true_peak_dbtp = float(loudness.get("max_true_peak_dbtp"))
    except (TypeError, ValueError):
        issues.append("publication_full_file_loudness_missing")
    else:
        if (
            str(loudness.get("status") or "") != "checked"
            or str(loudness.get("analysis_scope") or "") != "full_file"
            or not all(
                math.isfinite(value)
                for value in (
                    integrated_lufs,
                    true_peak_dbtp,
                    min_integrated_lufs,
                    max_integrated_lufs,
                    max_true_peak_dbtp,
                )
            )
            or min_integrated_lufs > max_integrated_lufs
            or integrated_lufs < min_integrated_lufs
            or integrated_lufs > max_integrated_lufs
            or true_peak_dbtp > max_true_peak_dbtp
        ):
            issues.append("publication_full_file_loudness_out_of_bounds")
    if (
        str(stt.get("status") or "") != "pass"
        or stt.get("enabled") is not True
        or stt.get("required") is not True
        or _receipt_nonnegative_int(stt.get("sample_count") or 0) <= 0
        or _receipt_nonnegative_int(stt.get("passed_samples") or 0)
        != _receipt_nonnegative_int(stt.get("sample_count") or 0)
        or _receipt_nonnegative_int(stt.get("failed_samples") or 0) != 0
    ):
        issues.append("publication_stt_not_pass")
    if not _is_sha256(source.get("source_sha256")):
        issues.append("source_artifact_sha256_missing")
    if not _is_sha256(target_sha256) or (
        assembly.get("output_file_ready") is True
        and not _is_sha256(assembly.get("output_file_sha256"))
    ):
        issues.append("published_artifact_sha256_missing")
    if (
        assembly.get("chapter_count_matches") is not True
        or _receipt_nonnegative_int(assembly.get("expected_chapter_count") or 0)
        != expected_chapters
        or _receipt_nonnegative_int(assembly.get("actual_chapter_count") or 0)
        != expected_chapters
    ):
        issues.append("assembly_chapter_count_not_exact")
    if cinematic_timeline_sha256 and not _is_sha256(cinematic_timeline_sha256):
        issues.append("cinematic_timeline_sha256_invalid")

    return {
        "status": "pass" if not issues else "blocked",
        "all_required_proof_passed": not issues,
        "expected_chapter_count": expected_chapters,
        "publication_chapter_count": _receipt_nonnegative_int(
            publication.get("chapters") or 0
        ),
        "narration_plan": {
            "contract_name": str(plan.get("contract_name") or ""),
            "status": str(plan.get("status") or ""),
            "coverage_complete": plan.get("coverage_complete") is True,
            "source_integrity_verified": plan.get("source_integrity_verified") is True,
            "chapter_count": _receipt_nonnegative_int(plan.get("chapter_count") or 0),
            "plan_sha256": str(plan.get("plan_sha256") or ""),
            "source_aggregate_sha256": str(plan.get("source_aggregate_sha256") or ""),
            "render_signature": str(plan.get("render_signature") or ""),
        },
        "dialogue_cast": {
            "required": cast_required,
            "status": str(cast.get("status") or ("not_required" if not cast_required else "")),
            "ready_and_distinct": cast_ready if cast_required else True,
            "dialogue_span_count": dialogue_count,
            "distinct_dialogue_voice_count": _receipt_nonnegative_int(
                cast.get("distinct_dialogue_voice_count") or 0
            ),
            "narrator_voice_excluded": cast.get("narrator_voice_excluded") is True,
            "cast_map_sha256": str(cast.get("cast_map_sha256") or ""),
            "raw_voice_ids_exposed": False,
        },
        "mastering": {
            "status": str(mastering.get("status") or ""),
            "final_track_mode": final_track_mode,
            "contract_sha256": str(mastering.get("contract_sha256") or ""),
            "signature_set_sha256": str(mastering.get("signature_set_sha256") or ""),
            "expected_final_track_count": _receipt_nonnegative_int(
                mastering.get("expected_final_track_count") or 0
            ),
            "final_track_ready_count": _receipt_nonnegative_int(
                mastering.get("final_track_ready_count") or 0
            ),
            "signature_published_or_verified_count": _receipt_nonnegative_int(
                mastering.get("signature_published_or_verified_count") or 0
            ),
            "segment_mastering": mastering.get("segment_mastering"),
            "final_audio_quality_pass": final_quality_pass,
        },
        "publication_stt": {
            "status": str(stt.get("status") or ""),
            "required": stt.get("required") is True,
            "sample_count": _receipt_nonnegative_int(stt.get("sample_count") or 0),
            "passed_samples": _receipt_nonnegative_int(stt.get("passed_samples") or 0),
            "failed_samples": _receipt_nonnegative_int(stt.get("failed_samples") or 0),
        },
        "source_sha256": str(source.get("source_sha256") or ""),
        "artifact_sha256": target_sha256,
        "publication_gate_sha256": publication_gate_sha256,
        "cinematic_timeline_sha256": cinematic_timeline_sha256,
        "issues": issues,
    }, issues


def _public_performance_evidence_valid_strict(
    performance: dict[str, object],
) -> bool:
    expected = _receipt_nonnegative_int(
        performance.get("expected_chapter_count") or 0
    )
    narration = _as_dict(performance.get("narration_plan"))
    cast = _as_dict(performance.get("dialogue_cast"))
    mastering = _as_dict(performance.get("mastering"))
    stt = _as_dict(performance.get("publication_stt"))
    cast_valid = cast.get("required") is not True or (
        cast.get("ready_and_distinct") is True
        and str(cast.get("status") or "") == "ready"
        and _receipt_nonnegative_int(
            cast.get("distinct_dialogue_voice_count") or 0
        )
        > 0
        and cast.get("narrator_voice_excluded") is True
        and _is_sha256(cast.get("cast_map_sha256"))
    )
    return bool(
        performance.get("status") == "pass"
        and performance.get("all_required_proof_passed") is True
        and not _as_list(performance.get("issues"))
        and expected > 0
        and _receipt_nonnegative_int(
            performance.get("publication_chapter_count") or 0
        )
        == expected
        and narration.get("contract_name") == NARRATION_PLAN_CONTRACT_NAME
        and narration.get("status") == "ready"
        and narration.get("coverage_complete") is True
        and narration.get("source_integrity_verified") is True
        and _receipt_nonnegative_int(narration.get("chapter_count") or 0)
        == expected
        and all(
            _is_sha256(narration.get(key))
            for key in ("plan_sha256", "source_aggregate_sha256", "render_signature")
        )
        and cast_valid
        and mastering.get("status") == "mastered"
        and mastering.get("final_track_mode")
        in {"chapter_masters", "cinematic_master"}
        and _is_sha256(mastering.get("contract_sha256"))
        and _is_sha256(mastering.get("signature_set_sha256"))
        and _receipt_nonnegative_int(
            mastering.get("expected_final_track_count") or 0
        )
        > 0
        and _receipt_nonnegative_int(
            mastering.get("final_track_ready_count") or 0
        )
        == _receipt_nonnegative_int(
            mastering.get("expected_final_track_count") or 0
        )
        and _receipt_nonnegative_int(
            mastering.get("signature_published_or_verified_count") or 0
        )
        == _receipt_nonnegative_int(
            mastering.get("expected_final_track_count") or 0
        )
        and mastering.get("segment_mastering") is False
        and mastering.get("final_audio_quality_pass") is True
        and (
            (
                _is_sha256(performance.get("cinematic_timeline_sha256"))
                and mastering.get("final_track_mode") == "cinematic_master"
                and _receipt_nonnegative_int(
                    mastering.get("expected_final_track_count") or 0
                )
                == 1
            )
            or (
                not str(performance.get("cinematic_timeline_sha256") or "")
                and mastering.get("final_track_mode") == "chapter_masters"
                and _receipt_nonnegative_int(
                    mastering.get("expected_final_track_count") or 0
                )
                == expected
            )
        )
        and stt.get("status") == "pass"
        and stt.get("required") is True
        and _receipt_nonnegative_int(stt.get("sample_count") or 0) > 0
        and _receipt_nonnegative_int(stt.get("passed_samples") or 0)
        == _receipt_nonnegative_int(stt.get("sample_count") or 0)
        and _receipt_nonnegative_int(stt.get("failed_samples") or 0) == 0
        and _is_sha256(performance.get("source_sha256"))
        and _is_sha256(performance.get("artifact_sha256"))
        and _is_sha256(performance.get("publication_gate_sha256"))
        and (
            not str(performance.get("cinematic_timeline_sha256") or "")
            or _is_sha256(performance.get("cinematic_timeline_sha256"))
        )
    )


def _public_performance_evidence_valid(performance: dict[str, object]) -> bool:
    try:
        return _public_performance_evidence_valid_strict(performance)
    except (TypeError, ValueError, OverflowError):
        return False


def _human_listened_canary_evidence(
    job: dict[str, object],
    *,
    performance: dict[str, object],
    channel: str,
    reference: datetime,
) -> dict[str, object]:
    playback = _as_dict(job.get("playback_acceptance"))
    imported = _as_dict(job.get("audiobookshelf_import"))
    metadata = _as_dict(job.get("metadata"))
    channel_receipt = _as_dict(job.get(channel))
    narration = _as_dict(performance.get("narration_plan"))
    cast = _as_dict(performance.get("dialogue_cast"))
    perceptual_attestation = _as_dict(
        playback.get("perceptual_attestation")
    )
    perceptual_checks = _as_dict(perceptual_attestation.get("checks"))
    freshness = _freshness_evidence(playback.get("recorded_at"), reference=reference)
    expected_message_sha = str(imported.get(f"public_share_{channel}_message_id_sha256") or "").strip().lower()
    expected_url_sha = _sha256_text(imported.get("public_share_url"))
    normalized_language = str(metadata.get("language") or "").strip().lower().split("-", 1)[0]
    blocked_fields: list[str] = []
    if str(playback.get("contract_name") or "") != HUMAN_LISTENED_CANARY_CONTRACT_NAME:
        blocked_fields.append("current_canary_acceptance_contract")
    if (
        playback.get("accepted") is not True
        or playback.get("listened") is not True
        or str(playback.get("status") or "") != "listened_canary_accepted"
        or str(playback.get("canary_binding_status") or "") != "complete"
        or bool(_as_list(playback.get("binding_issues")))
    ):
        blocked_fields.append("human_listened_acceptance")
    if str(playback.get("channel") or playback.get("source") or "").strip().lower() != channel:
        blocked_fields.append("channel_binding")
    acceptance_source = str(playback.get("source") or "").strip().lower()
    if acceptance_source != f"{channel}_button":
        blocked_fields.append("callback_acceptance_source")
    expected_attestation_sha256 = _canonical_perceptual_attestation_sha256(
        channel=channel,
        checks=perceptual_checks,
        all_checks_attested=(
            perceptual_attestation.get("all_checks_attested") is True
        ),
    )
    perceptual_attestation_valid = bool(
        set(perceptual_attestation)
        == {
            "contract_name",
            "version",
            "checks",
            "all_checks_attested",
            "channel_feedback_bound",
            "attestation_sha256",
            "raw_values_exposed",
        }
        and perceptual_attestation.get("contract_name")
        == PERCEPTUAL_ATTESTATION_CONTRACT_NAME
        and isinstance(perceptual_attestation.get("version"), int)
        and not isinstance(perceptual_attestation.get("version"), bool)
        and perceptual_attestation.get("version")
        == PERCEPTUAL_ATTESTATION_VERSION
        and set(perceptual_checks) == set(PERCEPTUAL_ATTESTATION_CHECKS)
        and all(
            perceptual_checks.get(key) is True
            for key in PERCEPTUAL_ATTESTATION_CHECKS
        )
        and perceptual_attestation.get("all_checks_attested") is True
        and perceptual_attestation.get("channel_feedback_bound") is True
        and perceptual_attestation.get("raw_values_exposed") is False
        and str(perceptual_attestation.get("attestation_sha256") or "")
        .strip()
        .lower()
        == expected_attestation_sha256
    )
    if not perceptual_attestation_valid:
        blocked_fields.append("perceptual_attestation")
    if not _is_sha256(playback.get("message_id_sha256")):
        blocked_fields.append("callback_message_id_sha256")
    if not freshness.get("fresh"):
        blocked_fields.append("acceptance_freshness")
    expected_hashes = {
        "artifact_sha256": str(performance.get("artifact_sha256") or ""),
        "source_sha256": str(performance.get("source_sha256") or ""),
        "source_aggregate_sha256": str(narration.get("source_aggregate_sha256") or ""),
        "narration_plan_sha256": str(narration.get("plan_sha256") or ""),
        "render_signature_sha256": str(narration.get("render_signature") or ""),
        "cast_map_sha256": str(cast.get("cast_map_sha256") or ""),
        "mastering_signature_set_sha256": str(
            _as_dict(performance.get("mastering")).get("signature_set_sha256") or ""
        ),
        "publication_gate_sha256": str(
            performance.get("publication_gate_sha256") or ""
        ),
        "channel_public_share_message_id_sha256": expected_message_sha,
        "public_share_url_sha256": expected_url_sha,
        "listener_reference_sha256": str(
            channel_receipt.get("listener_reference_sha256") or ""
        ).strip().lower(),
    }
    cinematic_timeline_sha256 = str(
        performance.get("cinematic_timeline_sha256") or ""
    ).strip()
    if cinematic_timeline_sha256:
        expected_hashes["cinematic_timeline_sha256"] = cinematic_timeline_sha256
    elif str(playback.get("cinematic_timeline_sha256") or "").strip():
        blocked_fields.append("cinematic_timeline_sha256")
    for key, expected in expected_hashes.items():
        if not _is_sha256(expected) or str(playback.get(key) or "").strip().lower() != expected.lower():
            blocked_fields.append(key)
    for key in ("feedback_sha256",):
        if not _is_sha256(playback.get(key)):
            blocked_fields.append(key)
    if str(playback.get("language") or "").strip().lower().split("-", 1)[0] != normalized_language or normalized_language not in {"de", "en"}:
        blocked_fields.append("language")
    if _receipt_nonnegative_int(playback.get("dialogue_turn_count") or 0) < 2:
        blocked_fields.append("dialogue_turn_count")
    expected_chapters = _receipt_nonnegative_int(
        performance.get("expected_chapter_count") or 0
    )
    if (
        _receipt_nonnegative_int(playback.get("expected_chapter_count") or 0)
        != expected_chapters
        or _receipt_nonnegative_int(playback.get("actual_chapter_count") or 0)
        != expected_chapters
    ):
        blocked_fields.append("chapter_count_binding")
    for key in (
        "raw_feedback_exposed",
        "raw_message_id_exposed",
        "raw_listener_reference_exposed",
    ):
        if playback.get(key) is not False:
            blocked_fields.append(key)
    receipt_sha256 = str(playback.get("receipt_sha256") or "").strip().lower()
    if not _is_sha256(receipt_sha256) or receipt_sha256 != _canonical_acceptance_sha256(playback):
        blocked_fields.append("receipt_sha256")
    receipt_hmac_sha256 = str(
        playback.get("receipt_hmac_sha256") or ""
    ).strip().lower()
    hmac_key = _canary_receipt_hmac_key(channel)
    expected_hmac = (
        hmac.new(
            hmac_key.encode("utf-8"),
            receipt_sha256.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        if hmac_key and _is_sha256(receipt_sha256)
        else ""
    )
    receipt_hmac_valid = bool(
        _is_sha256(receipt_hmac_sha256)
        and expected_hmac
        and hmac.compare_digest(receipt_hmac_sha256, expected_hmac)
    )
    if not receipt_hmac_valid:
        blocked_fields.append("receipt_hmac_sha256")
    blocked_fields = list(dict.fromkeys(blocked_fields))
    legacy = (
        str(playback.get("status") or "").strip().lower()
        in {"accepted", "accepted_unqualified", "rejected"}
        and str(playback.get("contract_name") or "") != HUMAN_LISTENED_CANARY_CONTRACT_NAME
    )
    immutable_receipt = {
        key: playback.get(key)
        for key in HUMAN_LISTENED_CANARY_DIGEST_FIELDS
    }
    immutable_receipt["receipt_sha256"] = receipt_sha256
    return {
        "contract_name": str(playback.get("contract_name") or ""),
        "required_contract_name": HUMAN_LISTENED_CANARY_CONTRACT_NAME,
        "status": "accepted" if not blocked_fields else ("legacy_non_complete" if legacy else "blocked"),
        "claim_allowed": not blocked_fields and bool(performance.get("all_required_proof_passed")),
        "accepted": playback.get("accepted") is True,
        "listened": playback.get("listened") is True,
        "channel": channel,
        "recorded_at": str(playback.get("recorded_at") or ""),
        "freshness": freshness,
        "artifact_sha256": str(playback.get("artifact_sha256") or ""),
        "source_sha256": str(playback.get("source_sha256") or ""),
        "source_aggregate_sha256": str(playback.get("source_aggregate_sha256") or ""),
        "narration_plan_sha256": str(playback.get("narration_plan_sha256") or ""),
        "render_signature_sha256": str(playback.get("render_signature_sha256") or ""),
        "cast_map_sha256": str(playback.get("cast_map_sha256") or ""),
        "mastering_signature_set_sha256": str(playback.get("mastering_signature_set_sha256") or ""),
        "publication_gate_sha256": str(playback.get("publication_gate_sha256") or ""),
        "channel_public_share_message_id_sha256": str(playback.get("channel_public_share_message_id_sha256") or ""),
        "public_share_url_sha256": str(playback.get("public_share_url_sha256") or ""),
        "feedback_sha256": str(playback.get("feedback_sha256") or ""),
        "perceptual_attestation": {
            "contract_name": (
                PERCEPTUAL_ATTESTATION_CONTRACT_NAME
                if perceptual_attestation.get("contract_name")
                == PERCEPTUAL_ATTESTATION_CONTRACT_NAME
                else ""
            ),
            "version": (
                PERCEPTUAL_ATTESTATION_VERSION
                if perceptual_attestation.get("version")
                == PERCEPTUAL_ATTESTATION_VERSION
                and not isinstance(perceptual_attestation.get("version"), bool)
                else 0
            ),
            "checks": {
                key: perceptual_checks.get(key) is True
                for key in PERCEPTUAL_ATTESTATION_CHECKS
            },
            "all_checks_attested": (
                perceptual_attestation.get("all_checks_attested") is True
            ),
            "channel_feedback_bound": (
                perceptual_attestation.get("channel_feedback_bound") is True
            ),
            "attestation_sha256": (
                str(perceptual_attestation.get("attestation_sha256") or "")
                .strip()
                .lower()
                if _is_sha256(
                    perceptual_attestation.get("attestation_sha256")
                )
                else ""
            ),
            "raw_values_exposed": False,
        },
        "listener_reference_sha256": str(playback.get("listener_reference_sha256") or ""),
        "language": str(playback.get("language") or ""),
        "dialogue_turn_count": _receipt_nonnegative_int(
            playback.get("dialogue_turn_count") or 0
        ),
        "expected_chapter_count": _receipt_nonnegative_int(
            playback.get("expected_chapter_count") or 0
        ),
        "actual_chapter_count": _receipt_nonnegative_int(
            playback.get("actual_chapter_count") or 0
        ),
        "receipt_sha256": receipt_sha256,
        "receipt_digest_valid": "receipt_sha256" not in blocked_fields,
        "receipt_hmac_sha256": receipt_hmac_sha256,
        "receipt_hmac_valid": receipt_hmac_valid,
        "immutable_receipt": immutable_receipt,
        "blocked_fields": blocked_fields,
        "raw_feedback_exposed": False,
        "raw_message_id_exposed": False,
        "raw_voice_ids_exposed": False,
    }


def _public_share_ready(status: object) -> bool:
    return str(status or "").strip().lower() in {
        "public_share_ready",
        "ready",
        "created",
        "reused",
        "existing",
        "sent",
    }


def _machine_playback_verified(import_section: dict[str, object]) -> bool:
    status = str(import_section.get("public_share_playback_e2e_status") or "").strip().lower()
    response = _receipt_nonnegative_int(
        import_section.get("public_share_playback_e2e_track_response_status") or 0
    )
    content_type = str(import_section.get("public_share_playback_e2e_track_content_type") or "").strip().lower()
    current_time = _receipt_nonnegative_float(
        import_section.get("public_share_playback_e2e_current_time_after_play_seconds") or 0
    )
    duration = _receipt_nonnegative_float(
        import_section.get("public_share_playback_e2e_duration_seconds") or 0
    )
    media_error = bool(import_section.get("public_share_playback_e2e_media_error_present"))
    return (
        status == "pass"
        and response in {200, 206}
        and content_type.startswith("audio/")
        and current_time > 0
        and duration > 0
        and not media_error
    )


def _m4b_output_verified(
    *,
    assembly: dict[str, object],
    imported: dict[str, object],
    audio_publication_gate: dict[str, object],
) -> bool:
    if assembly.get("output_file_ready") is True:
        return True
    return (
        str(imported.get("status") or "").strip() == "imported"
        and imported.get("target_file_ready") is True
        and str(imported.get("target_file_sha256") or "").strip()
    )


def _chapter_metadata_verified(
    *,
    assembly: dict[str, object],
    audio_publication_gate: dict[str, object],
) -> bool:
    if assembly.get("chapter_metadata_embedded") is True:
        return True
    return _receipt_nonnegative_int(audio_publication_gate.get("chapters") or 0) > 0


def _voice_selection(job: dict[str, object]) -> dict[str, object]:
    render = _as_dict(job.get("render"))
    return _as_dict(render.get("voice_selection"))


def _voice_selected_by_user(job: dict[str, object]) -> bool:
    voice = _voice_selection(job)
    selected = _as_dict(voice.get("selected"))
    if selected.get("default") is False:
        return True
    return str(voice.get("status") or "").strip() == "selected_by_user"


def _replacement_choice_pending(job: dict[str, object]) -> bool:
    voice = _voice_selection(job)
    reason = str(voice.get("reason") or "").strip()
    if str(voice.get("status") or "").strip() == "waiting_user_choice" and reason:
        return True
    return bool(_as_list(voice.get("replacement_candidate_keys")) and reason)


def _voice_choice_pending(job: dict[str, object]) -> bool:
    voice = _voice_selection(job)
    return str(voice.get("status") or "").strip() == "waiting_user_choice"


def _voice_selected_default(job: dict[str, object]) -> bool:
    selected = _as_dict(_voice_selection(job).get("selected"))
    return selected.get("default") is not False


def _candidate(job: dict[str, object], *, reference: datetime) -> dict[str, object]:
    metadata = _as_dict(job.get("metadata"))
    source = _as_dict(job.get("source"))
    assembly = _as_dict(job.get("assembly"))
    imported = _as_dict(job.get("audiobookshelf_import"))
    telegram = _as_dict(job.get("telegram"))
    privacy = _as_dict(job.get("privacy"))
    playback = _as_dict(job.get("playback_acceptance"))
    origin_delivery = _as_dict(job.get("origin_edition_delivery"))
    audio_publication_gate = _as_dict(job.get("audio_publication_gate"))
    title = str(metadata.get("title") or "").strip()
    author = str(metadata.get("author") or "").strip()
    public_url = str(imported.get("public_share_url") or "").strip()
    parsed_host = urlparse(public_url).hostname or ""
    failed_codes: list[str] = []
    performance, performance_issues = _performance_evidence(job)
    job_freshness = _freshness_evidence(job.get("observed_at"), reference=reference)
    publication_freshness = _freshness_evidence(
        audio_publication_gate.get("checked_at"),
        reference=reference,
    )
    playback_freshness = _freshness_evidence(
        imported.get("public_share_playback_e2e_checked_at"),
        reference=reference,
    )
    canary = _human_listened_canary_evidence(
        job,
        performance=performance,
        channel="telegram",
        reference=reference,
    )

    if str(job.get("status") or "").strip() != "audiobookshelf_imported":
        failed_codes.append("job_not_audiobookshelf_imported")
    if not _m4b_output_verified(
        assembly=assembly,
        imported=imported,
        audio_publication_gate=audio_publication_gate,
    ):
        failed_codes.append("m4b_output_file_not_ready")
    if not _chapter_metadata_verified(
        assembly=assembly,
        audio_publication_gate=audio_publication_gate,
    ):
        failed_codes.append("m4b_chapter_metadata_not_embedded")
    if str(imported.get("status") or "").strip() != "imported":
        failed_codes.append("audiobookshelf_import_not_imported")
    if imported.get("target_file_ready") is not True:
        failed_codes.append("audiobookshelf_target_file_not_ready")
    player_reference_status = str(imported.get("player_scoped_reference_status") or "").strip()
    if player_reference_status != "signed_reference_ready" and not _machine_playback_verified(imported):
        failed_codes.append("player_scoped_reference_not_ready")
    if not _public_share_ready(imported.get("public_share_status")):
        failed_codes.append("audiobookshelf_public_share_not_ready")
    if not public_url:
        failed_codes.append("audiobookshelf_public_share_url_missing")
    if str(imported.get("public_share_telegram_delivery_status") or "").strip() != "sent":
        failed_codes.append("telegram_public_share_delivery_not_sent")
    if imported.get("public_share_telegram_message_id_present") is not True:
        failed_codes.append("telegram_public_share_message_id_missing")
    if not _machine_playback_verified(imported):
        failed_codes.append("machine_playback_e2e_not_verified")
    if not job_freshness.get("fresh"):
        failed_codes.append("live_job_receipt_stale_or_timestamp_invalid")
    if not publication_freshness.get("fresh"):
        failed_codes.append("audio_publication_gate_stale_or_timestamp_invalid")
    if not playback_freshness.get("fresh"):
        failed_codes.append("machine_playback_proof_stale_or_timestamp_invalid")
    failed_codes.extend(performance_issues)

    for key, issue in {
        "public_share_token_exposed": "audiobookshelf_public_share_token_exposed",
        "public_share_raw_library_path_exposed": "audiobookshelf_raw_library_path_exposed",
        "public_share_telegram_callback_tokens_exposed": "telegram_callback_token_exposed",
        "public_share_telegram_audiobookshelf_token_exposed": "telegram_audiobookshelf_token_exposed",
    }.items():
        if imported.get(key) is True:
            failed_codes.append(issue)
    for key, issue in {
        "telegram_chat_id_exposed": "telegram_chat_id_exposed",
        "telegram_message_id_exposed": "telegram_message_id_exposed",
        "telegram_token_exposed": "telegram_token_exposed",
        "provider_secret_exposed": "provider_secret_exposed",
        "audiobookshelf_token_exposed": "audiobookshelf_token_exposed",
        "audiobookshelf_raw_path_exposed": "audiobookshelf_raw_path_exposed",
        "private_job_path_exposed": "private_job_path_exposed",
    }.items():
        if privacy.get(key) is True:
            failed_codes.append(issue)

    return {
        "raw": job,
        "job_id_sha256": _sha256_text(job.get("job_id")),
        "status": str(job.get("status") or ""),
        "source_kind": str(source.get("kind") or ""),
        "title_present": bool(title),
        "title_sha256": _sha256_text(title),
        "author_present": bool(author),
        "author_sha256": _sha256_text(author),
        "public_share_status": str(imported.get("public_share_status") or ""),
        "public_share_url_present": bool(public_url),
        "public_share_host": parsed_host,
        "telegram_delivery_status": str(imported.get("public_share_telegram_delivery_status") or ""),
        "telegram_delivery_message_id_present": bool(imported.get("public_share_telegram_message_id_present")),
        "telegram_chat_bound": bool(telegram.get("chat_bound")),
        "telegram_message_bound": bool(telegram.get("message_bound")),
        "machine_playback_e2e_verified": _machine_playback_verified(imported),
        "machine_playback_e2e_status": str(imported.get("public_share_playback_e2e_status") or ""),
        "machine_playback_e2e_browser": str(imported.get("public_share_playback_e2e_browser") or ""),
        "machine_playback_e2e_track_response_status": _receipt_nonnegative_int(
            imported.get("public_share_playback_e2e_track_response_status") or 0
        ),
        "machine_playback_e2e_track_content_type": str(imported.get("public_share_playback_e2e_track_content_type") or ""),
        "machine_playback_e2e_duration_seconds": _receipt_nonnegative_float(
            imported.get("public_share_playback_e2e_duration_seconds") or 0
        ),
        "machine_playback_e2e_current_time_after_play_seconds": _receipt_nonnegative_float(
            imported.get("public_share_playback_e2e_current_time_after_play_seconds") or 0
        ),
        "machine_playback_e2e_media_error_present": bool(imported.get("public_share_playback_e2e_media_error_present")),
        "player_scoped_reference_status": player_reference_status,
        "player_scoped_reference_ready": player_reference_status == "signed_reference_ready",
        "playback_acceptance_verified": bool(canary.get("claim_allowed")),
        "playback_acceptance_status": str(playback.get("status") or ""),
        "playback_acceptance_source": str(playback.get("source") or ""),
        "playback_acceptance_feedback_sha256": str(playback.get("feedback_sha256") or ""),
        "proof_freshness": {
            "job_receipt": job_freshness,
            "audio_publication_gate": publication_freshness,
            "machine_playback": playback_freshness,
            "all_required_proof_fresh": bool(
                job_freshness.get("fresh")
                and publication_freshness.get("fresh")
                and playback_freshness.get("fresh")
            ),
        },
        "performance_evidence": performance,
        "human_listened_canary": canary,
        "canary_completion_claim_allowed": bool(canary.get("claim_allowed")),
        "origin_edition_link_bundle": _origin_edition_link_bundle(origin_delivery),
        "voice_selected_by_user": _voice_selected_by_user(job),
        "voice_selected_default": _voice_selected_default(job),
        "voice_choice_pending": _voice_choice_pending(job),
        "replacement_choice_pending": _replacement_choice_pending(job),
        "failed_codes": failed_codes,
    }


def _candidate_or_malformed(
    job: dict[str, object],
    *,
    reference: datetime,
) -> dict[str, object]:
    try:
        return _candidate(job, reference=reference)
    except (TypeError, ValueError, OverflowError):
        metadata = _as_dict(job.get("metadata"))
        source = _as_dict(job.get("source"))
        invalid_freshness = {
            "timestamp_present": False,
            "fresh": False,
            "age_seconds": None,
            "max_age_seconds": LIVE_PROOF_MAX_AGE_SECONDS,
            "future_skew_seconds": None,
        }
        return {
            "raw": job,
            "job_id_sha256": _sha256_text(job.get("job_id")),
            "status": "malformed_job_receipt",
            "source_kind": str(source.get("kind") or "").strip().lower(),
            "title_present": bool(str(metadata.get("title") or "").strip()),
            "title_sha256": _sha256_text(metadata.get("title")),
            "author_present": bool(str(metadata.get("author") or "").strip()),
            "author_sha256": _sha256_text(metadata.get("author")),
            "public_share_status": "",
            "public_share_url_present": False,
            "public_share_host": "",
            "telegram_delivery_status": "",
            "telegram_delivery_message_id_present": False,
            "telegram_chat_bound": False,
            "telegram_message_bound": False,
            "machine_playback_e2e_verified": False,
            "machine_playback_e2e_status": "",
            "machine_playback_e2e_browser": "",
            "machine_playback_e2e_track_response_status": 0,
            "machine_playback_e2e_track_content_type": "",
            "machine_playback_e2e_duration_seconds": 0.0,
            "machine_playback_e2e_current_time_after_play_seconds": 0.0,
            "machine_playback_e2e_media_error_present": False,
            "player_scoped_reference_status": "",
            "player_scoped_reference_ready": False,
            "playback_acceptance_verified": False,
            "playback_acceptance_status": "",
            "playback_acceptance_source": "",
            "playback_acceptance_feedback_sha256": "",
            "performance_evidence": {
                "status": "blocked",
                "all_required_proof_passed": False,
                "issues": ["malformed_job_receipt"],
            },
            "human_listened_canary": {
                "status": "blocked",
                "claim_allowed": False,
                "blocked_fields": ["malformed_job_receipt"],
            },
            "proof_freshness": {
                "job_receipt": dict(invalid_freshness),
                "audio_publication_gate": dict(invalid_freshness),
                "machine_playback": dict(invalid_freshness),
                "all_required_proof_fresh": False,
            },
            "origin_edition_link_bundle": {},
            "voice_selected_by_user": False,
            "voice_selected_default": False,
            "voice_choice_pending": False,
            "replacement_choice_pending": False,
            "canary_completion_claim_allowed": False,
            "failed_codes": ["malformed_job_receipt"],
        }


def _candidate_in_telegram_audiobook_scope(candidate: dict[str, object]) -> bool:
    source_kind = str(candidate.get("source_kind") or "").strip().lower()
    if source_kind not in TELEGRAM_AUDIOBOOK_SOURCE_KINDS:
        return False
    if source_kind in {"telegram_epub", "telegram_ebook"}:
        return True
    job = _as_dict(candidate.get("raw"))
    source = _as_dict(job.get("source"))
    telegram = _as_dict(job.get("telegram"))
    filename = str(source.get("source_filename") or "").strip().lower().split("?", 1)[0]
    if not any(filename.endswith(suffix) for suffix in TELEGRAM_AUDIOBOOK_SOURCE_SUFFIXES):
        return False
    return bool(
        telegram.get("chat_bound")
        or telegram.get("message_bound")
        or str(source.get("source_url_sha256") or "").strip()
    )


def _origin_edition_link_bundle(origin_delivery: dict[str, object]) -> dict[str, object]:
    if not origin_delivery:
        return {"status": "not_applicable"}
    links = _as_dict(origin_delivery.get("links"))
    read_url = str(links.get("read") or origin_delivery.get("read_url") or "").strip()
    listen_url = str(links.get("listen") or origin_delivery.get("listen_url") or "").strip()
    watch_url = str(links.get("watch") or origin_delivery.get("watch_url") or "").strip()
    open_url = str(
        links.get("open_in_chummer")
        or links.get("open")
        or origin_delivery.get("open_in_chummer_url")
        or origin_delivery.get("open_url")
        or ""
    ).strip()
    return {
        "status": str(origin_delivery.get("status") or "").strip(),
        "project_id": str(origin_delivery.get("project_id") or "").strip(),
        "origin_namespace_sha256": _sha256_text(origin_delivery.get("origin_namespace")),
        "telegram_delivery_status": str(origin_delivery.get("telegram_delivery_status") or "").strip(),
        "telegram_message_id_present": bool(origin_delivery.get("telegram_message_id_present")),
        "read_url_present": bool(read_url),
        "listen_url_present": bool(listen_url),
        "watch_url_present": bool(watch_url),
        "open_in_chummer_url_present": bool(open_url),
        "read_url_sha256": _sha256_text(read_url),
        "listen_url_sha256": _sha256_text(listen_url),
        "watch_url_sha256": _sha256_text(watch_url),
        "open_in_chummer_url_sha256": _sha256_text(open_url),
        "all_required_links_present": all((read_url, listen_url, watch_url, open_url)),
        "raw_urls_exposed": False,
    }


def _pending_user_selected_job(candidate: dict[str, object]) -> bool:
    if not candidate["failed_codes"]:
        return False
    if candidate.get("voice_choice_pending") or candidate.get("replacement_choice_pending"):
        return True
    if not candidate.get("voice_selected_by_user"):
        return False
    failed_codes = {str(code or "").strip() for code in list(candidate.get("failed_codes") or [])}
    return bool(failed_codes & USER_SELECTED_VOICE_DELIVERY_BLOCKING_CODES)


def _candidate_is_superseded(candidate: dict[str, object]) -> bool:
    return str(candidate.get("status") or "").strip() == "superseded_duplicate"


def _blocking_candidates(candidates: list[dict[str, object]]) -> list[dict[str, object]]:
    current = [candidate for candidate in candidates if not _candidate_is_superseded(candidate)]
    return current or candidates


def _candidate_source_key(candidate: dict[str, object]) -> str:
    job = _as_dict(candidate.get("raw"))
    source = _as_dict(job.get("source"))
    source_sha = str(source.get("source_sha256") or "").strip()
    if _is_sha256(source_sha):
        return f"source_sha256:{source_sha}"
    metadata = _as_dict(job.get("metadata"))
    title_sha = _sha256_text(metadata.get("title"))
    author_sha = _sha256_text(metadata.get("author"))
    if title_sha or author_sha:
        return f"title_author:{title_sha}:{author_sha}"
    return ""


def _pending_user_selected_job_still_blocks(
    candidate: dict[str, object],
    *,
    valid_user_selected_source_keys: set[str],
) -> bool:
    if not _pending_user_selected_job(candidate):
        return False
    if _candidate_is_superseded(candidate):
        return False
    source_key = _candidate_source_key(candidate)
    return not source_key or source_key not in valid_user_selected_source_keys


def _pending_summary(candidate: dict[str, object]) -> dict[str, object]:
    job = _as_dict(candidate.get("raw"))
    render = _as_dict(job.get("render"))
    scheduler = _as_dict(job.get("scheduler_resume"))
    telegram = _as_dict(job.get("telegram"))
    voice = _voice_selection(job)
    selected = _as_dict(voice.get("selected"))
    replacement_keys = _as_list(voice.get("replacement_candidate_keys"))
    voice_choice_keys = _as_list(voice.get("pending_candidate_keys")) or replacement_keys
    replacement_pending = bool(candidate.get("replacement_choice_pending"))
    pending_batch = [_as_dict(row) for row in _as_list(voice.get("pending_batch")) if isinstance(row, dict)]
    profile = _as_dict(voice.get("book_profile"))
    author_gender_signal = str(profile.get("author_gender_signal") or "").strip().lower()
    pending_labels = [
        str(row.get("label") or "").strip()
        for row in pending_batch
        if str(row.get("label") or "").strip()
    ]
    pending_genders = [_voice_candidate_gender(row) for row in pending_batch]
    author_gender_match_count = sum(
        1
        for gender in pending_genders
        if author_gender_signal in {"male", "female"} and gender == author_gender_signal
    )
    author_gender_mismatch_count = sum(
        1
        for gender in pending_genders
        if author_gender_signal in {"male", "female"} and gender in {"male", "female"} and gender != author_gender_signal
    )
    return {
        "job_id_sha256": candidate["job_id_sha256"],
        "status": str(job.get("status") or ""),
        "render_status": str(render.get("status") or ""),
        "render_chapter_index": int(render.get("chapter_index") or 0),
        "render_segment_index": int(render.get("segment_index") or 0),
        "render_segment_count": int(render.get("segment_count") or 0),
        "voice_selection_status": str(voice.get("status") or ""),
        "voice_selection_reason": str(voice.get("reason") or ""),
        "voice_selection_waiting": str(voice.get("status") or "") == "waiting_user_choice",
        "voice_choice_pending": bool(candidate.get("voice_choice_pending")),
        "source_key_sha256": _sha256_text(_candidate_source_key(candidate)),
        "voice_choice_candidate_count": len(voice_choice_keys),
        "voice_choice_candidate_labels": pending_labels[:3],
        "replacement_choice_pending": replacement_pending,
        "replacement_candidate_count": len(replacement_keys) if replacement_pending else 0,
        "replacement_candidate_labels": pending_labels[:3] if replacement_pending else [],
        "author_gender_signal": author_gender_signal if author_gender_signal in {"male", "female"} else "",
        "author_gender_match_count": author_gender_match_count,
        "author_gender_mismatch_count": author_gender_mismatch_count,
        "author_gender_matched_candidates_only": bool(
            author_gender_signal in {"male", "female"}
            and pending_batch
            and author_gender_match_count == len(pending_batch)
        ),
        "author_gender_mismatched_voice_samples_pending": bool(author_gender_mismatch_count > 0),
        "voice_sample_delivery_status": str(telegram.get("voice_sample_delivery_status") or "").strip(),
        "voice_sample_delivery_expected_count": int(telegram.get("voice_sample_delivery_expected_count") or 0),
        "voice_sample_delivery_sent_count": int(telegram.get("voice_sample_delivery_sent_count") or 0),
        "voice_sample_delivery_failed_count": int(telegram.get("voice_sample_delivery_failed_count") or 0),
        "selected_voice_id_sha256": str(selected.get("voice_id_sha256") or ""),
        "selected_label_sha256": _sha256_text(selected.get("label")),
        "raw_voice_ids_exposed": False,
        "callback_tokens_exposed": False,
        "external_tts_blocker_code": str(render.get("external_tts_blocker_code") or scheduler.get("external_tts_blocker_code") or ""),
        "external_tts_blocker_retryable": bool(
            render.get("external_tts_blocker_retryable") or scheduler.get("external_tts_blocker_retryable")
        ),
        "external_tts_blocker_reason_sha256": str(render.get("external_tts_blocker_reason_sha256") or ""),
        "scheduler_retry_after": str(scheduler.get("retry_after") or ""),
    }


def _voice_action_source_key(row: dict[str, object]) -> str:
    source_key = str(row.get("source_key_sha256") or "").strip()
    if source_key:
        return source_key
    return str(row.get("job_id_sha256") or "").strip()


def _duplicate_suppression_state(
    *,
    candidates: list[dict[str, object]],
    pending: list[dict[str, object]],
) -> dict[str, object]:
    superseded = [candidate for candidate in candidates if _candidate_is_superseded(candidate)]
    superseded_pending = [_pending_summary(candidate) for candidate in superseded if _pending_user_selected_job(candidate)]
    pending_source_keys = [_voice_action_source_key(row) for row in pending if _voice_action_source_key(row)]
    duplicate_pending_source_keys = _dedupe([key for key in pending_source_keys if pending_source_keys.count(key) > 1])
    suppressed_labels: list[str] = []
    for row in superseded_pending:
        suppressed_labels.extend(
            str(label).strip()
            for label in list(row.get("replacement_candidate_labels") or row.get("voice_choice_candidate_labels") or [])
            if str(label).strip()
        )
    return {
        "action_required_only": True,
        "only_current_jobs_can_require_user_action": True,
        "superseded_duplicate_candidate_count": len(superseded),
        "suppressed_pending_voice_duplicate_count": len(superseded_pending),
        "active_pending_voice_job_count": len(pending),
        "duplicate_active_pending_source_key_count": len(duplicate_pending_source_keys),
        "duplicate_active_pending_source_keys_sha256": [_sha256_text(key) for key in duplicate_pending_source_keys],
        "suppressed_voice_candidate_labels": _dedupe(suppressed_labels)[:3],
        "raw_voice_ids_exposed": False,
        "callback_tokens_exposed": False,
    }


def _candidate_public(candidate: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in candidate.items() if key != "raw"}


def _failed_candidate_public(candidate: dict[str, object]) -> dict[str, object]:
    return {
        "job_id_sha256": candidate["job_id_sha256"],
        "status": candidate["status"],
        "title_present": candidate["title_present"],
        "title_sha256": candidate["title_sha256"],
        "public_share_status": candidate["public_share_status"],
        "telegram_delivery_status": candidate["telegram_delivery_status"],
        "failed_codes": list(candidate["failed_codes"]),
    }


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _voice_candidate_gender(row: dict[str, object]) -> str:
    tags = row.get("tags")
    if isinstance(tags, str):
        values = [tags]
    elif isinstance(tags, list):
        values = tags
    else:
        values = []
    normalized = {str(item or "").strip().lower() for item in values}
    if "male" in normalized:
        return "male"
    if "female" in normalized:
        return "female"
    return ""


def _pending_voice_samples_sent(row: dict[str, object]) -> bool:
    expected = int(row.get("voice_sample_delivery_expected_count") or 0)
    sent = int(row.get("voice_sample_delivery_sent_count") or 0)
    status = str(row.get("voice_sample_delivery_status") or "").strip()
    candidate_count = int(row.get("voice_choice_candidate_count") or row.get("replacement_candidate_count") or 0)
    required = max(expected, candidate_count)
    return status == "sent" and required > 0 and sent >= required


def _pending_voice_samples_required(row: dict[str, object]) -> bool:
    expected = int(row.get("voice_sample_delivery_expected_count") or 0)
    candidate_count = int(row.get("voice_choice_candidate_count") or row.get("replacement_candidate_count") or 0)
    return max(expected, candidate_count) > 0


def _next_action(*, failed_codes: list[str], pending: list[dict[str, object]]) -> str:
    if any(row.get("author_gender_mismatched_voice_samples_pending") for row in pending):
        return "refresh_author_gender_matched_voice_samples_before_user_choice"
    if any(row.get("replacement_choice_pending") for row in pending):
        replacement_rows = [row for row in pending if row.get("replacement_choice_pending")]
        if any(_pending_voice_samples_required(row) for row in replacement_rows) and not all(
            _pending_voice_samples_sent(row) for row in replacement_rows if _pending_voice_samples_required(row)
        ):
            return "send_missing_telegram_audiobook_voice_samples_before_user_choice"
        if any(_pending_voice_samples_sent(row) for row in pending):
            return "choose_sent_replacement_voice_sample"
        return "choose_explicit_replacement_voice_or_restore_selected_provider"
    if any(row.get("voice_choice_pending") for row in pending):
        if not all(_pending_voice_samples_sent(row) for row in pending if row.get("voice_choice_pending")):
            return "send_missing_telegram_audiobook_voice_samples_before_user_choice"
        return "choose_one_telegram_audiobook_voice_sample"
    if (
        "job_not_audiobookshelf_imported" in failed_codes
        or "m4b_output_file_not_ready" in failed_codes
        or "m4b_chapter_metadata_not_embedded" in failed_codes
        or "audiobookshelf_import_not_imported" in failed_codes
        or "audiobookshelf_target_file_not_ready" in failed_codes
    ):
        return "resume_or_rebuild_telegram_audiobook_render_before_public_share_delivery"
    if pending:
        return "finish_user_selected_voice_audiobook_before_sending_public_share_link"
    if "audiobookshelf_public_share_not_ready" in failed_codes and "telegram_public_share_delivery_not_sent" not in failed_codes:
        return "wait_for_audiobookshelf_scan_then_rerun_share_followup"
    if "telegram_public_share_delivery_not_sent" in failed_codes or "telegram_public_share_message_id_missing" in failed_codes:
        return "wait_for_scheduler_to_send_audiobookshelf_public_share_link_or_fix_telegram_delivery"
    if "machine_playback_e2e_not_verified" in failed_codes:
        return "run_public_share_machine_playback_e2e_before_claiming_live_delivery"
    return "inspect_failed_audiobook_delivery_candidates"


def _next_action_surface(next_action: str) -> tuple[str, str, str]:
    return TELEGRAM_ACTION_SURFACES.get(
        str(next_action or "").strip(),
        (CHANNEL_LOOP_PATH, CHANNEL_LOOP_LABEL, ACTION_METHOD),
    )


def _operator_action_packet(
    *,
    next_action: str,
    pending: list[dict[str, object]],
    live_pass: bool,
    real_user_accepted: bool,
) -> dict[str, object]:
    if live_pass and real_user_accepted:
        return {
            "user_action_required": False,
            "reason": "telegram_audiobook_live_delivery_closed",
            "raw_voice_ids_exposed": False,
            "callback_tokens_exposed": False,
        }
    if not pending:
        return {
            "user_action_required": False,
            "reason": "no_user_voice_choice_required",
            "raw_voice_ids_exposed": False,
            "callback_tokens_exposed": False,
        }
    first = pending[0]
    if next_action == "refresh_author_gender_matched_voice_samples_before_user_choice":
        return {
            "user_action_required": False,
            "reason": "author_gender_mismatched_voice_samples_pending",
            "operator_action": next_action,
            "instruction": "Refresh the audiobook voice samples before asking the user to choose.",
            "author_gender_signal": str(first.get("author_gender_signal") or ""),
            "author_gender_match_count": int(first.get("author_gender_match_count") or 0),
            "author_gender_mismatch_count": int(first.get("author_gender_mismatch_count") or 0),
            "next_action_href": CHANNEL_LOOP_PATH,
            "next_action_label": CHANNEL_LOOP_LABEL,
            "next_action_method": ACTION_METHOD,
            "raw_voice_ids_exposed": False,
            "callback_tokens_exposed": False,
        }
    if next_action == "send_missing_telegram_audiobook_voice_samples_before_user_choice":
        candidate_count = int(first.get("replacement_candidate_count") or first.get("voice_choice_candidate_count") or 0)
        sent_count = int(first.get("voice_sample_delivery_sent_count") or 0)
        expected_count = int(first.get("voice_sample_delivery_expected_count") or 0)
        required_count = max(candidate_count, expected_count)
        return {
            "user_action_required": False,
            "reason": "voice_sample_delivery_underfilled",
            "operator_action": next_action,
            "instruction": "Send the missing Telegram audiobook voice samples before asking the user to choose.",
            "candidate_count": candidate_count,
            "voice_sample_delivery_status": str(first.get("voice_sample_delivery_status") or "").strip(),
            "voice_sample_delivery_sent_count": sent_count,
            "voice_sample_delivery_expected_count": expected_count,
            "voice_sample_delivery_required_count": required_count,
            "voice_sample_delivery_missing_count": max(required_count - sent_count, 0),
            "next_action_href": CHANNEL_LOOP_PATH,
            "next_action_label": CHANNEL_LOOP_LABEL,
            "next_action_method": ACTION_METHOD,
            "raw_voice_ids_exposed": False,
            "callback_tokens_exposed": False,
        }
    labels = [
        str(item).strip()
        for item in list(first.get("replacement_candidate_labels") or first.get("voice_choice_candidate_labels") or [])
        if str(item).strip()
    ]
    delivery_status = str(first.get("voice_sample_delivery_status") or "").strip()
    sent_count = int(first.get("voice_sample_delivery_sent_count") or 0)
    expected_count = int(first.get("voice_sample_delivery_expected_count") or 0)
    candidate_count = int(first.get("replacement_candidate_count") or first.get("voice_choice_candidate_count") or 0)
    if next_action == "choose_sent_replacement_voice_sample":
        instruction = "Choose one sent replacement voice sample in Telegram."
    elif next_action == "choose_explicit_replacement_voice_or_restore_selected_provider":
        instruction = "Choose a replacement voice or restore the selected provider voice before rendering."
    else:
        instruction = "Choose one Telegram audiobook voice sample."
    return {
        "user_action_required": True,
        "reason": str(first.get("voice_selection_reason") or next_action or "voice_choice_pending").strip(),
        "operator_action": next_action,
        "instruction": instruction,
        "candidate_count": candidate_count,
        "candidate_labels": labels[:3],
        "voice_sample_delivery_status": delivery_status,
        "voice_sample_delivery_sent_count": sent_count,
        "voice_sample_delivery_expected_count": expected_count,
        "voice_sample_delivery_required_count": max(expected_count, candidate_count),
        "sent_samples_cover_expected": bool(
            delivery_status == "sent" and max(expected_count, candidate_count) > 0 and sent_count >= max(expected_count, candidate_count)
        ),
        "next_action_href": TELEGRAM_INTEGRATION_PATH,
        "next_action_label": TELEGRAM_INTEGRATION_LABEL,
        "next_action_method": ACTION_METHOD,
        "raw_voice_ids_exposed": False,
        "callback_tokens_exposed": False,
    }


def build_receipt(
    *,
    output_path: Path = DEFAULT_OUTPUT,
    job_receipts: list[dict[str, object]] | None = None,
    generated_at: str | None = None,
    limit: int = 100,
    observation_source: str = "provided_job_receipts",
) -> dict[str, object]:
    generated_timestamp = generated_at or _now_iso()
    reference = _parse_utc(generated_timestamp) or datetime.now(UTC)
    jobs = list(job_receipts or [])[:limit]
    loaded_candidates = [
        _candidate_or_malformed(job, reference=reference)
        for job in jobs
        if isinstance(job, dict)
    ]
    candidates = [candidate for candidate in loaded_candidates if _candidate_in_telegram_audiobook_scope(candidate)]
    ignored_candidates = [candidate for candidate in loaded_candidates if candidate not in candidates]
    blocking_candidates = _blocking_candidates(candidates)
    valid_candidates = [candidate for candidate in candidates if not candidate["failed_codes"]]
    selected = valid_candidates[0] if valid_candidates else (
        min(blocking_candidates, key=lambda candidate: len(list(candidate.get("failed_codes") or []))) if blocking_candidates else {}
    )
    valid_user_selected_source_keys = {
        key
        for key in (_candidate_source_key(candidate) for candidate in valid_candidates if candidate.get("voice_selected_by_user"))
        if key
    }
    pending = [
        _pending_summary(candidate)
        for candidate in candidates
        if _pending_user_selected_job_still_blocks(
            candidate,
            valid_user_selected_source_keys=valid_user_selected_source_keys,
        )
    ]
    failed_codes = _dedupe([code for candidate in blocking_candidates for code in list(candidate.get("failed_codes") or [])])
    if any(row.get("voice_choice_pending") for row in pending):
        failed_codes.append("audiobook_voice_choice_pending")
    if pending:
        failed_codes.append("user_selected_voice_delivery_not_ready")
    if any(row.get("replacement_choice_pending") for row in pending):
        failed_codes.append("explicit_replacement_voice_choice_pending")
    if any(row.get("author_gender_mismatched_voice_samples_pending") for row in pending):
        failed_codes.append("author_gender_mismatched_voice_samples_pending")
    if any(_pending_voice_samples_required(row) and not _pending_voice_samples_sent(row) for row in pending):
        failed_codes.append("voice_sample_delivery_underfilled")
    failed_codes = _dedupe(failed_codes)
    live_pass = bool(valid_candidates) and not pending
    real_user_accepted = bool(selected.get("playback_acceptance_verified")) if selected else False
    machine_verified = bool(selected.get("machine_playback_e2e_verified")) if selected else any(
        bool(candidate.get("machine_playback_e2e_verified")) for candidate in candidates
    )
    selected_failed_codes = list(selected.get("failed_codes") or []) if selected else failed_codes
    if not valid_candidates and "valid_live_audiobook_delivery_missing" not in failed_codes:
        failed_codes.insert(0, "valid_live_audiobook_delivery_missing")
    next_action = (
        "close_operator_loop"
        if live_pass and real_user_accepted
        else (
            "capture_real_user_playback_acceptance_or_close_operator_loop"
            if live_pass
            else _next_action(failed_codes=selected_failed_codes, pending=pending)
        )
    )
    next_action_href, next_action_label, next_action_method = _next_action_surface(next_action)

    receipt = {
        "contract_name": CONTRACT_NAME,
        **_source_state_fields(),
        "generated_at": generated_timestamp,
        "generated_by": "ea/scripts/materialize_telegram_audiobook_live_delivery_receipt.py",
        "output_path": _logical_output_path(output_path),
        "observation_source": observation_source,
        "limit": limit,
        "source_filter": "telegram_epub_audiobook_sources",
        "claim": (
            "Telegram EPUB audiobook delivery has live proof only when a sanitized job receipt shows the M4B is ready, "
            "Audiobookshelf imported and public-shared it, and Telegram sent the public share link."
        ),
        "status": "pass" if live_pass else "blocked",
        "live_delivery_claim_allowed": live_pass,
        "proof_freshness": {
            "max_age_seconds": LIVE_PROOF_MAX_AGE_SECONDS,
            "fresh_live_job_receipt_present": bool(candidates),
            "fresh_live_job_receipt_passed": live_pass,
            "selected_job_receipt": _as_dict(_as_dict(selected.get("proof_freshness")).get("job_receipt"))
            if selected
            else {},
            "selected_audio_publication_gate": _as_dict(
                _as_dict(selected.get("proof_freshness")).get("audio_publication_gate")
            ) if selected else {},
            "selected_machine_playback": _as_dict(_as_dict(selected.get("proof_freshness")).get("machine_playback"))
            if selected
            else {},
        },
        "machine_playback_e2e_verified": machine_verified,
        "real_user_playback_acceptance_verified": real_user_accepted,
        "human_playback_acceptance_claim_allowed": bool(
            live_pass and selected.get("canary_completion_claim_allowed")
        ) if selected else False,
        "canary_completion_claim_allowed": bool(
            live_pass and selected.get("canary_completion_claim_allowed")
        ) if selected else False,
        "canary_completion_blocked_fields": list(
            _as_dict(selected.get("human_listened_canary")).get("blocked_fields") or []
        ) if selected else ["current_human_listened_canary_receipt"],
        "human_listened_canary_contract": HUMAN_LISTENED_CANARY_CONTRACT_NAME,
        "narration_plan_contract": NARRATION_PLAN_CONTRACT_NAME,
        "goal_completion_claim_allowed": False,
        "candidate_count": len(candidates),
        "ignored_non_telegram_audiobook_candidate_count": len(ignored_candidates),
        "ignored_non_telegram_audiobook_source_kinds": _dedupe(
            [str(candidate.get("source_kind") or "").strip() for candidate in ignored_candidates]
        ),
        "failed_candidate_count": len([candidate for candidate in candidates if candidate.get("failed_codes")]),
        "failed_codes": [] if live_pass else failed_codes,
        "blocking_reason": "" if live_pass else ", ".join(failed_codes),
        "next_action": next_action,
        "next_action_href": next_action_href,
        "next_action_label": next_action_label,
        "next_action_method": next_action_method,
        "operator_action_packet": _operator_action_packet(
            next_action=next_action,
            pending=pending,
            live_pass=live_pass,
            real_user_accepted=real_user_accepted,
        ),
        "duplicate_suppression": _duplicate_suppression_state(candidates=candidates, pending=pending),
        "selected_delivery": _candidate_public(selected) if selected else {},
        "failed_candidates": [_failed_candidate_public(candidate) for candidate in candidates if candidate.get("failed_codes")],
        "pending_user_selected_voice_job_count": len(pending),
        "pending_user_selected_voice_jobs": pending,
        "load_errors": [],
        "privacy": {
            "raw_job_receipts_persisted": False,
            "titles_redacted_to_sha256": True,
            "authors_redacted_to_sha256": True,
            "public_share_urls_redacted_to_host": True,
            "machine_playback_e2e_url_redacted": True,
            "playback_acceptance_feedback_hashed": real_user_accepted,
            "telegram_message_ids_hashed": True,
            "voice_labels_operator_safe": True,
            "raw_voice_ids_exposed": False,
            "provider_secret_exposed": False,
            "audiobookshelf_token_exposed": False,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def _public_load_error_codes(values: list[str] | tuple[str, ...]) -> list[str]:
    codes: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        code = normalized if normalized in PUBLIC_LOAD_ERROR_CODES else "receipt_load_failed"
        if code not in codes:
            codes.append(code)
    return codes


def _apply_load_errors(
    receipt: dict[str, object],
    errors: list[str] | tuple[str, ...],
) -> dict[str, object]:
    receipt["load_errors"] = _public_load_error_codes(errors)
    if not receipt["load_errors"]:
        return receipt
    receipt["status"] = "blocked"
    receipt["live_delivery_claim_allowed"] = False
    receipt["machine_playback_e2e_verified"] = False
    receipt["real_user_playback_acceptance_verified"] = False
    receipt["human_playback_acceptance_claim_allowed"] = False
    receipt["canary_completion_claim_allowed"] = False
    receipt["canary_completion_blocked_fields"] = ["job_receipt_load_errors"]
    receipt["goal_completion_claim_allowed"] = False
    proof_freshness = _as_dict(receipt.get("proof_freshness"))
    proof_freshness["fresh_live_job_receipt_passed"] = False
    receipt["proof_freshness"] = proof_freshness
    receipt["failed_codes"] = list(
        dict.fromkeys(
            [
                *_as_list(receipt.get("failed_codes")),
                "job_receipt_load_errors",
            ]
        )
    )
    receipt["blocking_reason"] = ", ".join(
        str(code) for code in _as_list(receipt.get("failed_codes"))
    )
    next_action = "inspect_failed_audiobook_delivery_candidates"
    next_href, next_label, next_method = _next_action_surface(next_action)
    receipt["next_action"] = next_action
    receipt["next_action_href"] = next_href
    receipt["next_action_label"] = next_label
    receipt["next_action_method"] = next_method
    receipt["operator_action_packet"] = _operator_action_packet(
        next_action=next_action,
        pending=[],
        live_pass=False,
        real_user_accepted=False,
    )
    return receipt


def _job_dir_identity(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _load_receipts_json(path: Path) -> tuple[list[dict[str, object]], list[str]]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return [], ["job_receipts_json_load_failed"]
    if isinstance(parsed, dict):
        if "receipts" in parsed:
            rows = parsed.get("receipts")
        elif "job_receipts" in parsed:
            rows = parsed.get("job_receipts")
        else:
            return [], ["job_receipts_json_invalid_shape"]
    elif isinstance(parsed, list):
        rows = parsed
    else:
        return [], ["job_receipts_json_invalid_shape"]
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        return [], ["job_receipts_json_invalid_shape"]
    receipts = [dict(row) for row in rows]
    return receipts, []


def _scan_job_receipts(limit: int) -> tuple[list[dict[str, object]], list[str]]:
    try:
        from app.services import audiobook_epub_pipeline
    except Exception:
        return [], ["audiobook_pipeline_import_failed"]
    receipts: list[dict[str, object]] = []
    errors: list[str] = []
    seen_job_dirs: set[Path] = set()
    try:
        job_paths = list(
            audiobook_epub_pipeline.iter_audiobook_job_manifests(
                newest_first=True
            )
        )[:limit]
    except Exception:
        return [], ["job_manifest_discovery_failed"]
    for job_path in job_paths:
        job_dir = job_path.parent
        seen_job_dirs.add(_job_dir_identity(job_dir))
        try:
            receipts.append(
                audiobook_epub_pipeline.build_audiobook_job_receipt(
                    job_dir=job_dir
                )
            )
        except Exception:
            errors.append("job_receipt_build_failed")
    remaining = max(0, limit - len(receipts))
    if remaining <= 0:
        return receipts, errors
    receipt_paths: list[Path] = []
    try:
        discovery_roots = tuple(
            audiobook_epub_pipeline.audiobook_job_discovery_roots()
        )
    except Exception:
        errors.append("job_receipt_discovery_failed")
        discovery_roots = ()
    for root in discovery_roots:
        try:
            receipt_paths.extend(root.glob("**/job_receipt.json"))
        except OSError:
            errors.append("job_receipt_discovery_failed")
    for receipt_path in sorted(receipt_paths, key=_safe_mtime, reverse=True):
        if len(receipts) >= limit:
            break
        if _job_dir_identity(receipt_path.parent) in seen_job_dirs:
            continue
        try:
            parsed = json.loads(receipt_path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                receipts.append(parsed)
            else:
                errors.append("stored_job_receipt_invalid_shape")
        except Exception:
            errors.append("stored_job_receipt_load_failed")
    return receipts, _public_load_error_codes(errors)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-receipts-json", type=Path)
    parser.add_argument("--output", "--out", dest="output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--require-pass", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    if args.job_receipts_json:
        receipts, errors = _load_receipts_json(args.job_receipts_json)
        source = "job_receipts_json"
    else:
        receipts, errors = _scan_job_receipts(args.limit)
        source = "job_discovery_roots"
    receipt = build_receipt(
        output_path=args.output,
        job_receipts=receipts,
        generated_at=args.generated_at or None,
        limit=args.limit,
        observation_source=source,
    )
    _apply_load_errors(receipt, errors)
    args.output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, indent=2 if args.pretty else None, sort_keys=True))
    if args.require_pass and receipt["status"] != "pass":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
