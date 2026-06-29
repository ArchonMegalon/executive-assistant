from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[2]
EA_ROOT = ROOT / "ea"
DEFAULT_OUTPUT = ROOT / ".codex-studio" / "published" / "telegram_audiobook_live_delivery.generated.json"
CONTRACT_NAME = "ea.telegram_audiobook_live_delivery_receipt.v1"
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
}


if str(EA_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_ROOT))


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256_text(value: object) -> str:
    text = str(value or "").strip()
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""


def _is_sha256(value: object) -> bool:
    text = str(value or "").strip()
    return len(text) == 64 and all(ch in "0123456789abcdef" for ch in text.lower())


def _as_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


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
    response = int(import_section.get("public_share_playback_e2e_track_response_status") or 0)
    content_type = str(import_section.get("public_share_playback_e2e_track_content_type") or "").strip().lower()
    current_time = float(import_section.get("public_share_playback_e2e_current_time_after_play_seconds") or 0)
    duration = float(import_section.get("public_share_playback_e2e_duration_seconds") or 0)
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
    return int(audio_publication_gate.get("chapters") or 0) > 0


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


def _candidate(job: dict[str, object]) -> dict[str, object]:
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
        "machine_playback_e2e_track_response_status": int(imported.get("public_share_playback_e2e_track_response_status") or 0),
        "machine_playback_e2e_track_content_type": str(imported.get("public_share_playback_e2e_track_content_type") or ""),
        "machine_playback_e2e_duration_seconds": float(imported.get("public_share_playback_e2e_duration_seconds") or 0),
        "machine_playback_e2e_current_time_after_play_seconds": float(
            imported.get("public_share_playback_e2e_current_time_after_play_seconds") or 0
        ),
        "machine_playback_e2e_media_error_present": bool(imported.get("public_share_playback_e2e_media_error_present")),
        "player_scoped_reference_status": player_reference_status,
        "player_scoped_reference_ready": player_reference_status == "signed_reference_ready",
        "playback_acceptance_verified": bool(playback.get("accepted")) and str(playback.get("status") or "") == "accepted",
        "playback_acceptance_status": str(playback.get("status") or ""),
        "playback_acceptance_source": str(playback.get("source") or ""),
        "playback_acceptance_feedback_sha256": str(playback.get("feedback_sha256") or ""),
        "origin_edition_link_bundle": _origin_edition_link_bundle(origin_delivery),
        "voice_selected_by_user": _voice_selected_by_user(job),
        "voice_selected_default": _voice_selected_default(job),
        "voice_choice_pending": _voice_choice_pending(job),
        "replacement_choice_pending": _replacement_choice_pending(job),
        "failed_codes": failed_codes,
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
    voice = _voice_selection(job)
    selected = _as_dict(voice.get("selected"))
    replacement_keys = _as_list(voice.get("replacement_candidate_keys"))
    voice_choice_keys = _as_list(voice.get("pending_candidate_keys")) or replacement_keys
    replacement_pending = bool(candidate.get("replacement_choice_pending"))
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
        "voice_choice_candidate_count": len(voice_choice_keys),
        "replacement_choice_pending": replacement_pending,
        "replacement_candidate_count": len(replacement_keys) if replacement_pending else 0,
        "selected_voice_id_sha256": str(selected.get("voice_id_sha256") or ""),
        "selected_label_sha256": _sha256_text(selected.get("label")),
        "external_tts_blocker_code": str(render.get("external_tts_blocker_code") or scheduler.get("external_tts_blocker_code") or ""),
        "external_tts_blocker_retryable": bool(
            render.get("external_tts_blocker_retryable") or scheduler.get("external_tts_blocker_retryable")
        ),
        "external_tts_blocker_reason_sha256": str(render.get("external_tts_blocker_reason_sha256") or ""),
        "scheduler_retry_after": str(scheduler.get("retry_after") or ""),
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


def _next_action(*, failed_codes: list[str], pending: list[dict[str, object]]) -> str:
    if any(row.get("replacement_choice_pending") for row in pending):
        return "choose_explicit_replacement_voice_or_restore_selected_provider"
    if any(row.get("voice_choice_pending") for row in pending):
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


def build_receipt(
    *,
    output_path: Path = DEFAULT_OUTPUT,
    job_receipts: list[dict[str, object]] | None = None,
    generated_at: str | None = None,
    limit: int = 100,
    observation_source: str = "provided_job_receipts",
) -> dict[str, object]:
    jobs = list(job_receipts or [])[:limit]
    loaded_candidates = [_candidate(job) for job in jobs if isinstance(job, dict)]
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
        "generated_at": generated_at or _now_iso(),
        "generated_by": "ea/scripts/materialize_telegram_audiobook_live_delivery_receipt.py",
        "output_path": output_path.as_posix(),
        "observation_source": observation_source,
        "limit": limit,
        "source_filter": "telegram_epub_audiobook_sources",
        "claim": (
            "Telegram EPUB audiobook delivery has live proof only when a sanitized job receipt shows the M4B is ready, "
            "Audiobookshelf imported and public-shared it, and Telegram sent the public share link."
        ),
        "status": "pass" if live_pass else "blocked",
        "live_delivery_claim_allowed": live_pass,
        "machine_playback_e2e_verified": machine_verified,
        "real_user_playback_acceptance_verified": real_user_accepted,
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
            "voice_labels_hashed": True,
            "provider_secret_exposed": False,
            "audiobookshelf_token_exposed": False,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def _load_receipts_json(path: Path) -> tuple[list[dict[str, object]], list[str]]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [], [f"{path.as_posix()}:{exc}"]
    if isinstance(parsed, dict):
        rows = parsed.get("receipts") or parsed.get("job_receipts") or []
    else:
        rows = parsed
    receipts = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    return receipts, []


def _scan_job_receipts(limit: int) -> tuple[list[dict[str, object]], list[str]]:
    try:
        from app.services import audiobook_epub_pipeline
    except Exception as exc:
        return [], [f"audiobook_pipeline_import_failed:{exc}"]
    receipts: list[dict[str, object]] = []
    errors: list[str] = []
    seen_job_dirs: set[Path] = set()
    job_paths = list(audiobook_epub_pipeline.iter_audiobook_job_manifests(newest_first=True))[:limit]
    for job_path in job_paths:
        try:
            receipts.append(audiobook_epub_pipeline.build_audiobook_job_receipt(job_dir=job_path.parent))
            seen_job_dirs.add(job_path.parent.resolve())
        except Exception as exc:
            errors.append(f"{job_path.name}:{exc}")
    remaining = max(0, limit - len(receipts))
    if remaining <= 0:
        return receipts, errors
    receipt_paths: list[Path] = []
    for root in audiobook_epub_pipeline.audiobook_job_discovery_roots():
        try:
            receipt_paths.extend(root.glob("**/job_receipt.json"))
        except OSError as exc:
            errors.append(f"{root.as_posix()}:{type(exc).__name__}")
    for receipt_path in sorted(receipt_paths, key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True):
        if len(receipts) >= limit:
            break
        try:
            if receipt_path.parent.resolve() in seen_job_dirs:
                continue
        except Exception:
            pass
        try:
            parsed = json.loads(receipt_path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                receipts.append(parsed)
        except Exception as exc:
            errors.append(f"{receipt_path.name}:{exc}")
    return receipts, errors


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
    if errors:
        receipt["load_errors"] = errors
        args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2 if args.pretty else None, sort_keys=True))
    if args.require_pass and receipt["status"] != "pass":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
