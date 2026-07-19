from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[2]
EA_ROOT = ROOT / "ea"
DEFAULT_OUTPUT = ROOT / ".codex-studio" / "published" / "whatsapp_audiobook_live_delivery.generated.json"
DEFAULT_LOCAL_INTAKE_PROOF = ROOT / ".codex-studio" / "published" / "whatsapp_audiobook_local_intake_proof.generated.json"
DEFAULT_PUBLIC_SHARE_PLAYBACK = ROOT / ".codex-studio" / "published" / "whatsapp_audiobook_public_share_playback.generated.json"
DEFAULT_OPERATOR_PROOF_BUNDLE = ROOT / ".codex-studio" / "published" / "whatsapp_audiobook_operator_proof_bundle.generated.json"
DEFAULT_READINESS_RECEIPT = ROOT / ".codex-studio" / "published" / "whatsapp_web_action_processor_readiness.generated.json"
DEFAULT_RUNTIME_CONTAINER = "ea-api"
CONTRACT_NAME = "ea.whatsapp_audiobook_live_delivery_receipt.v2"
LEGACY_CONTRACT_NAME = "ea.whatsapp_audiobook_live_delivery_receipt.v1"


if str(EA_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_ROOT))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.audiobook_epub_pipeline import audiobook_runtime_preflight
from scripts.materialize_telegram_audiobook_live_delivery_receipt import HUMAN_LISTENED_CANARY_CONTRACT_NAME
from scripts.materialize_telegram_audiobook_live_delivery_receipt import LIVE_PROOF_MAX_AGE_SECONDS
from scripts.materialize_telegram_audiobook_live_delivery_receipt import NARRATION_PLAN_CONTRACT_NAME
from scripts.materialize_telegram_audiobook_live_delivery_receipt import _freshness_evidence
from scripts.materialize_telegram_audiobook_live_delivery_receipt import _human_listened_canary_evidence
from scripts.materialize_telegram_audiobook_live_delivery_receipt import _job_dir_identity
from scripts.materialize_telegram_audiobook_live_delivery_receipt import _parse_utc
from scripts.materialize_telegram_audiobook_live_delivery_receipt import _performance_evidence
from scripts.materialize_telegram_audiobook_live_delivery_receipt import _public_load_error_codes
from scripts.materialize_telegram_audiobook_live_delivery_receipt import _receipt_nonnegative_float
from scripts.materialize_telegram_audiobook_live_delivery_receipt import _receipt_nonnegative_int
from scripts.materialize_telegram_audiobook_live_delivery_receipt import _safe_mtime
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


def _is_sha256(value: object) -> bool:
    text = str(value or "").strip()
    return len(text) == 64 and all(ch in "0123456789abcdef" for ch in text.lower())


def _as_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _read_json(path: Path) -> dict[str, object]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _load_module(*, name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"{name}_missing")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _runtime_container_name() -> str:
    return str(os.environ.get("EA_RUNTIME_CONTAINER") or DEFAULT_RUNTIME_CONTAINER).strip()


def _runtime_container_preflight() -> dict[str, object]:
    container = _runtime_container_name()
    if not container:
        return {}
    code = (
        "import json\n"
        "from app.services.audiobook_epub_pipeline import audiobook_runtime_preflight\n"
        "print(json.dumps(audiobook_runtime_preflight(), sort_keys=True))\n"
    )
    try:
        proc = subprocess.run(
            ["docker", "exec", container, "python3", "-c", code],
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
    except Exception:
        return {}
    if proc.returncode != 0:
        return {}
    try:
        payload = json.loads(str(proc.stdout or "").strip())
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


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


def _voice_selected_default(job: dict[str, object]) -> bool:
    selected = _as_dict(_voice_selection(job).get("selected"))
    return selected.get("default") is not False


def _voice_choice_pending(job: dict[str, object]) -> bool:
    voice = _voice_selection(job)
    return str(voice.get("status") or "").strip() == "waiting_user_choice"


def _replacement_choice_pending(job: dict[str, object]) -> bool:
    voice = _voice_selection(job)
    if not _as_list(voice.get("replacement_candidate_keys")):
        return False
    reason = str(voice.get("reason") or "").strip()
    strategy = str(voice.get("strategy") or "").strip()
    last_action = _as_dict(voice.get("last_action"))
    return (
        reason == "selected_voice_provider_balance_blocked"
        or strategy == "explicit_replacement_voice_after_provider_block"
        or str(last_action.get("action") or "").strip() in {"dismiss", "offer_replacement"}
        or str(last_action.get("status") or "").strip() == "replacement_ready"
    )


def _playback_acceptance_evidence(candidate: dict[str, object]) -> dict[str, object]:
    canary = _as_dict(candidate.get("human_listened_canary"))
    status = str(candidate.get("playback_acceptance_status") or "").strip().lower()
    source = str(candidate.get("playback_acceptance_source") or "").strip().lower()
    feedback_sha256 = str(candidate.get("playback_acceptance_feedback_sha256") or "").strip()
    whatsapp_sourced = source.startswith("whatsapp")
    accepted = bool(canary.get("claim_allowed"))
    rejected_claim_observed = status == "rejected" and whatsapp_sourced
    feedback_sha256_present = bool(feedback_sha256)
    feedback_sha256_valid = _is_sha256(feedback_sha256)
    operator_grade_rejected = rejected_claim_observed and feedback_sha256_valid
    if accepted:
        evidence_status = "accepted"
        next_action = "close_operator_loop"
        evidence_grade = "operator"
    elif operator_grade_rejected:
        evidence_status = "rejected"
        next_action = "review_audiobook_playback_problem"
        evidence_grade = "operator"
    elif rejected_claim_observed:
        evidence_status = "not_human_verified"
        next_action = "capture_hashed_audiobook_playback_problem_feedback"
        evidence_grade = "insufficient_feedback_hash"
    elif str(canary.get("status") or "") == "legacy_non_complete":
        evidence_status = "legacy_non_complete"
        next_action = "capture_real_user_playback_acceptance_or_close_operator_loop"
        evidence_grade = "legacy_non_complete"
    else:
        evidence_status = "not_human_verified"
        next_action = "capture_real_user_playback_acceptance_or_close_operator_loop"
        evidence_grade = "not_operator_evidence"
    return {
        "status": evidence_status,
        "accepted": accepted,
        "rejected": operator_grade_rejected,
        "rejected_claim_observed": rejected_claim_observed,
        "whatsapp_sourced": whatsapp_sourced,
        "source_present": bool(source),
        "feedback_sha256_present": feedback_sha256_present,
        "feedback_sha256_valid": feedback_sha256_valid,
        "feedback_sha256_required": rejected_claim_observed,
        "operator_grade": accepted or operator_grade_rejected,
        "evidence_grade": evidence_grade,
        "claim_allowed": accepted,
        "next_action": next_action,
        "canary_contract_name": str(canary.get("contract_name") or ""),
        "required_canary_contract_name": HUMAN_LISTENED_CANARY_CONTRACT_NAME,
        "canary_receipt_sha256": str(canary.get("receipt_sha256") or ""),
        "canary_receipt_digest_valid": bool(canary.get("receipt_digest_valid")),
        "canary_blocked_fields": list(canary.get("blocked_fields") or []),
        "artifact_sha256": str(canary.get("artifact_sha256") or ""),
        "narration_plan_sha256": str(canary.get("narration_plan_sha256") or ""),
        "render_signature_sha256": str(canary.get("render_signature_sha256") or ""),
        "cast_map_sha256": str(canary.get("cast_map_sha256") or ""),
        "recorded_at": str(canary.get("recorded_at") or ""),
        "freshness": _as_dict(canary.get("freshness")),
    }


def _is_whatsapp_job(job: dict[str, object]) -> bool:
    whatsapp = _as_dict(job.get("whatsapp"))
    source = str(whatsapp.get("source") or "").strip().lower()
    return (
        whatsapp.get("sender_bound") is True
        or whatsapp.get("session_bound") is True
        or whatsapp.get("message_hash_present") is True
        or bool(str(whatsapp.get("voice_sample_delivery_status") or "").strip())
        or source.startswith("whatsapp")
        or "whatsapp" in source
    )


def _runtime_session_ref(readiness_receipt: dict[str, object] | None) -> str:
    readiness = _as_dict(readiness_receipt)
    return str(
        readiness.get("effective_session_ref")
        or readiness.get("state_session_ref")
        or readiness.get("configured_session_ref")
        or ""
    ).strip()


def _job_matches_runtime_session(
    job: dict[str, object],
    *,
    readiness_receipt: dict[str, object] | None,
) -> bool:
    runtime_session_ref = _runtime_session_ref(readiness_receipt)
    if not runtime_session_ref:
        return True
    whatsapp = _as_dict(job.get("whatsapp"))
    job_session_ref = str(whatsapp.get("session_ref") or "").strip()
    if not job_session_ref:
        job_session_ref_sha256 = str(whatsapp.get("session_ref_sha256") or "").strip()
        if not job_session_ref_sha256:
            return True
        return job_session_ref_sha256 == _sha256_text(runtime_session_ref)
    return job_session_ref == runtime_session_ref


def _candidate(job: dict[str, object], *, reference: datetime) -> dict[str, object]:
    metadata = _as_dict(job.get("metadata"))
    source = _as_dict(job.get("source"))
    assembly = _as_dict(job.get("assembly"))
    imported = _as_dict(job.get("audiobookshelf_import"))
    whatsapp = _as_dict(job.get("whatsapp"))
    privacy = _as_dict(job.get("privacy"))
    playback = _as_dict(job.get("playback_acceptance"))
    render = _as_dict(job.get("render"))
    scheduler = _as_dict(job.get("scheduler_resume"))
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
        channel="whatsapp",
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
    if str(imported.get("public_share_whatsapp_delivery_status") or "").strip() != "sent":
        failed_codes.append("whatsapp_public_share_delivery_not_sent")
    if imported.get("public_share_whatsapp_message_id_present") is not True:
        failed_codes.append("whatsapp_public_share_message_id_missing")
    if whatsapp.get("sender_bound") is not True:
        failed_codes.append("whatsapp_sender_not_bound")
    if whatsapp.get("session_bound") is not True:
        failed_codes.append("whatsapp_session_not_bound")
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
        "public_share_whatsapp_callback_tokens_exposed": "whatsapp_callback_token_exposed",
        "public_share_whatsapp_audiobookshelf_token_exposed": "whatsapp_audiobookshelf_token_exposed",
    }.items():
        if imported.get(key) is True:
            failed_codes.append(issue)
    for key, issue in {
        "whatsapp_sender_ref_exposed": "whatsapp_sender_ref_exposed",
        "whatsapp_message_id_exposed": "whatsapp_message_id_exposed",
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
        "whatsapp_delivery_status": str(imported.get("public_share_whatsapp_delivery_status") or ""),
        "whatsapp_delivery_message_id_present": bool(imported.get("public_share_whatsapp_message_id_present")),
        "whatsapp_sender_bound": bool(whatsapp.get("sender_bound")),
        "whatsapp_session_bound": bool(whatsapp.get("session_bound")),
        "machine_playback_e2e_verified": _machine_playback_verified(imported),
        "machine_playback_e2e_status": str(imported.get("public_share_playback_e2e_status") or ""),
        "machine_playback_e2e_browser": str(imported.get("public_share_playback_e2e_browser") or ""),
        "machine_playback_e2e_reason": str(imported.get("public_share_playback_e2e_reason") or ""),
        "machine_playback_e2e_page_response_status": _receipt_nonnegative_int(
            imported.get("public_share_playback_e2e_page_response_status") or 0
        ),
        "machine_playback_e2e_track_response_status": _receipt_nonnegative_int(
            imported.get("public_share_playback_e2e_track_response_status") or 0
        ),
        "machine_playback_e2e_track_content_type": str(imported.get("public_share_playback_e2e_track_content_type") or ""),
        "machine_playback_e2e_track_response_resource_type": str(
            imported.get("public_share_playback_e2e_track_response_resource_type") or ""
        ),
        "machine_playback_e2e_duration_seconds": _receipt_nonnegative_float(
            imported.get("public_share_playback_e2e_duration_seconds") or 0
        ),
        "machine_playback_e2e_current_time_after_play_seconds": _receipt_nonnegative_float(
            imported.get("public_share_playback_e2e_current_time_after_play_seconds") or 0
        ),
        "machine_playback_e2e_media_error_present": bool(imported.get("public_share_playback_e2e_media_error_present")),
        "machine_playback_e2e_media_error_code": _receipt_nonnegative_int(
            imported.get("public_share_playback_e2e_media_error_code") or 0
        ),
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
        "voice_selected_by_user": _voice_selected_by_user(job),
        "voice_selected_default": _voice_selected_default(job),
        "voice_choice_pending": _voice_choice_pending(job),
        "replacement_choice_pending": _replacement_choice_pending(job),
        "provider_pacing_waiting": str(job.get("status") or "").strip() == "waiting_provider_throttle"
        or str(render.get("status") or "").strip() in {"provider_pacing_wait", "provider_throttled"},
        "provider_retry_after": str(render.get("provider_retry_after") or scheduler.get("retry_after") or ""),
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
            "whatsapp_delivery_status": "",
            "whatsapp_delivery_message_id_present": False,
            "whatsapp_sender_bound": False,
            "whatsapp_session_bound": False,
            "machine_playback_e2e_verified": False,
            "machine_playback_e2e_status": "",
            "machine_playback_e2e_browser": "",
            "machine_playback_e2e_reason": "",
            "machine_playback_e2e_page_response_status": 0,
            "machine_playback_e2e_track_response_status": 0,
            "machine_playback_e2e_track_content_type": "",
            "machine_playback_e2e_track_response_resource_type": "",
            "machine_playback_e2e_duration_seconds": 0.0,
            "machine_playback_e2e_current_time_after_play_seconds": 0.0,
            "machine_playback_e2e_media_error_present": False,
            "machine_playback_e2e_media_error_code": 0,
            "player_scoped_reference_status": "",
            "player_scoped_reference_ready": False,
            "playback_acceptance_verified": False,
            "playback_acceptance_status": "",
            "playback_acceptance_source": "",
            "playback_acceptance_feedback_sha256": "",
            "proof_freshness": {
                "job_receipt": dict(invalid_freshness),
                "audio_publication_gate": dict(invalid_freshness),
                "machine_playback": dict(invalid_freshness),
                "all_required_proof_fresh": False,
            },
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
            "canary_completion_claim_allowed": False,
            "voice_selected_by_user": False,
            "voice_selected_default": False,
            "voice_choice_pending": False,
            "replacement_choice_pending": False,
            "provider_pacing_waiting": False,
            "provider_retry_after": "",
            "failed_codes": ["malformed_job_receipt"],
        }


def _pending_user_selected_job(candidate: dict[str, object]) -> bool:
    if not candidate["failed_codes"]:
        return False
    return bool(
        candidate.get("voice_selected_by_user")
        or candidate.get("voice_choice_pending")
        or candidate.get("replacement_choice_pending")
    )


def _candidate_is_superseded(candidate: dict[str, object]) -> bool:
    return str(candidate.get("status") or "").strip() == "superseded_duplicate"


def _selected_candidate_pool(candidates: list[dict[str, object]]) -> list[dict[str, object]]:
    current = [candidate for candidate in candidates if not _candidate_is_superseded(candidate)]
    return current or candidates


def _pending_job_is_playback_only(row: dict[str, object]) -> bool:
    return (
        str(row.get("status") or "").strip() == "audiobookshelf_imported"
        and str(row.get("voice_selection_status") or "").strip() == "selected_by_user"
        and not bool(row.get("voice_selection_waiting"))
        and not bool(row.get("replacement_choice_pending"))
        and not bool(row.get("external_tts_blocker_retryable"))
        and not str(row.get("scheduler_retry_after") or "").strip()
    )


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
        "replacement_choice_pending": bool(candidate.get("replacement_choice_pending")),
        "replacement_candidate_count": len(replacement_keys),
        "selected_voice_id_sha256": str(selected.get("voice_id_sha256") or ""),
        "selected_label_sha256": _sha256_text(selected.get("label")),
        "external_tts_blocker_code": str(render.get("external_tts_blocker_code") or scheduler.get("external_tts_blocker_code") or ""),
        "external_tts_blocker_retryable": bool(
            render.get("external_tts_blocker_retryable") or scheduler.get("external_tts_blocker_retryable")
        ),
        "external_tts_blocker_reason_sha256": str(render.get("external_tts_blocker_reason_sha256") or ""),
        "scheduler_retry_after": str(scheduler.get("retry_after") or render.get("provider_retry_after") or ""),
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
        "whatsapp_delivery_status": candidate["whatsapp_delivery_status"],
        "failed_codes": list(candidate["failed_codes"]),
    }


def _live_pass_next_action(candidate: dict[str, object]) -> str:
    return str(_playback_acceptance_evidence(candidate).get("next_action") or "")


def _candidate_stage(candidate: dict[str, object]) -> str:
    failed = set(str(code) for code in list(candidate.get("failed_codes") or []))
    if not failed:
        return "delivered_playable"
    if candidate.get("replacement_choice_pending"):
        return "waiting_replacement_voice_choice"
    if candidate.get("voice_choice_pending"):
        return "waiting_voice_choice"
    if candidate.get("provider_pacing_waiting"):
        return "waiting_provider_pacing"
    if "job_not_audiobookshelf_imported" in failed:
        return "render_or_import_pending"
    if "audiobookshelf_public_share_not_ready" in failed or "audiobookshelf_public_share_url_missing" in failed:
        return "waiting_audiobookshelf_public_share"
    if "whatsapp_public_share_delivery_not_sent" in failed or "whatsapp_public_share_message_id_missing" in failed:
        return "waiting_whatsapp_public_share_delivery"
    if "machine_playback_e2e_not_verified" in failed:
        return "waiting_machine_playback_verification"
    if "whatsapp_sender_not_bound" in failed or "whatsapp_session_not_bound" in failed:
        return "waiting_whatsapp_binding"
    return "failed_needs_inspection"


def _stage_summary(candidates: list[dict[str, object]]) -> dict[str, object]:
    counts: dict[str, int] = {}
    latest_by_stage: dict[str, dict[str, object]] = {}
    for candidate in candidates:
        stage = _candidate_stage(candidate)
        counts[stage] = counts.get(stage, 0) + 1
        latest_by_stage.setdefault(
            stage,
            {
                "job_id_sha256": candidate.get("job_id_sha256") or "",
                "status": candidate.get("status") or "",
                "title_sha256": candidate.get("title_sha256") or "",
                "public_share_status": candidate.get("public_share_status") or "",
                "whatsapp_delivery_status": candidate.get("whatsapp_delivery_status") or "",
                "failed_codes": list(candidate.get("failed_codes") or [])[:6],
            },
        )
    return {
        "counts": counts,
        "latest_by_stage": latest_by_stage,
    }


def _historical_evidence(
    payloads: dict[str, dict[str, object]] | None,
) -> dict[str, object]:
    receipts = payloads or {}
    local = _as_dict(receipts.get("local_intake"))
    playback = _as_dict(receipts.get("public_share_playback"))
    bundle = _as_dict(receipts.get("operator_bundle"))
    bundle_checks = _as_dict(bundle.get("checks"))
    bundle_voice_shadow = _as_dict(bundle.get("live_voice_selection_shadow"))
    bundle_text_fallback = _as_dict(bundle_voice_shadow.get("text_fallback"))
    playback_results = [row for row in _as_list(playback.get("results")) if isinstance(row, dict)]
    playback_passes = [
        row
        for row in playback_results
        if bool(row.get("passed")) and str(row.get("status") or "").strip() == "pass"
    ]
    bundle_live = _as_dict(bundle.get("live_delivery"))
    local_checks = _as_dict(local.get("checks"))
    local_processor = _as_dict(local.get("processor_report"))
    local_voice_selection = _as_dict(local_processor.get("voice_selection"))
    local_job_summary = _as_dict(local.get("job_summary"))
    local_path_proven = (
        str(local.get("status") or "").strip() == "pass"
        and bool(local_checks.get("whatsapp_public_share_sent"))
        and bool(local_checks.get("whatsapp_sender_bound"))
        and bool(local_checks.get("whatsapp_session_bound"))
        and int(local_voice_selection.get("share_link_sent") or 0) >= 1
        and str(local_job_summary.get("status") or "").strip() == "audiobookshelf_imported"
    )
    playback_path_proven = (
        str(playback.get("status") or "").strip() == "pass"
        and int(playback.get("passed") or 0) >= 1
        and bool(playback_passes)
    )
    bundle_live_path_proven = (
        str(bundle.get("status") or "").strip() == "pass"
        and str(bundle_live.get("status") or "").strip() == "pass"
        and bool(bundle_live.get("live_delivery_claim_allowed"))
    )
    present = bool(local or playback or bundle)
    historical_live_path_proven = bool((local_path_proven and playback_path_proven) or bundle_live_path_proven)
    public_share_hosts = _dedupe(
        [
            str(row.get("public_share_host") or "").strip()
            for row in playback_passes
            if str(row.get("public_share_host") or "").strip()
        ]
    )
    return {
        "present": present,
        "historical_live_path_proven": historical_live_path_proven,
        "requires_fresh_live_job_receipt": present,
        "local_intake": {
            "receipt_present": bool(local),
            "status": str(local.get("status") or ""),
            "generated_at": str(local.get("generated_at") or ""),
            "share_link_sent": int(local_voice_selection.get("share_link_sent") or 0),
            "voice_sample_sent": int(_as_dict(local_processor.get("intake")).get("voice_sample_sent") or 0),
            "local_path_proven": local_path_proven,
        },
        "public_share_playback": {
            "receipt_present": bool(playback),
            "status": str(playback.get("status") or ""),
            "generated_at": str(playback.get("generated_at") or ""),
            "passed": int(playback.get("passed") or 0),
            "attempted": int(playback.get("attempted") or 0),
            "passed_result_count": len(playback_passes),
            "public_share_hosts": public_share_hosts,
            "playback_path_proven": playback_path_proven,
        },
        "operator_bundle": {
            "receipt_present": bool(bundle),
            "status": str(bundle.get("status") or ""),
            "generated_at": str(bundle.get("generated_at") or ""),
            "recommended_action": str(bundle.get("recommended_action") or ""),
            "live_delivery_status": str(bundle_live.get("status") or ""),
            "live_delivery_claim_allowed": bool(bundle_live.get("live_delivery_claim_allowed")),
            "voice_selection_text_fallback_ready": bool(
                bundle_checks.get("live_voice_selection_text_fallback_ready_or_not_required")
                or bundle_text_fallback.get("bare_voice_choice_resolved")
            ),
            "live_path_proven": bundle_live_path_proven,
        },
    }


def _voice_selection_text_fallback_ready(historical: dict[str, object]) -> bool:
    operator_bundle = _as_dict(historical.get("operator_bundle"))
    return bool(operator_bundle.get("voice_selection_text_fallback_ready"))


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _next_action(
    *,
    failed_codes: list[str],
    pending: list[dict[str, object]],
    stage_counts: dict[str, int] | None = None,
    historical_evidence: dict[str, object] | None = None,
) -> str:
    stages = dict(stage_counts or {})
    historical = _as_dict(historical_evidence)
    if "whatsapp_audiobook_job_missing" in failed_codes:
        if bool(historical.get("present")):
            return "send_epub_over_whatsapp_to_refresh_live_delivery_receipt"
        return "send_epub_over_whatsapp_to_start_audiobook_flow"
    if any(row.get("replacement_choice_pending") for row in pending):
        return "choose_explicit_replacement_voice_or_restore_selected_provider"
    if any(row.get("voice_selection_waiting") for row in pending):
        return "choose_whatsapp_audiobook_voice_sample"
    if stages.get("waiting_provider_pacing"):
        return "wait_until_provider_retry_after_then_resume_whatsapp_audiobook_render"
    if stages.get("waiting_machine_playback_verification") and (
        not pending or all(_pending_job_is_playback_only(row) for row in pending)
    ):
        return "run_public_share_machine_playback_e2e_before_claiming_live_delivery"
    if pending:
        return "finish_user_selected_voice_audiobook_before_sending_whatsapp_public_share_link"
    if stages.get("render_or_import_pending"):
        return "resume_or_finish_whatsapp_audiobook_render_before_public_share_delivery"
    if stages.get("waiting_audiobookshelf_public_share"):
        return "wait_for_audiobookshelf_scan_then_rerun_whatsapp_share_followup"
    if stages.get("waiting_whatsapp_public_share_delivery"):
        return "run_whatsapp_action_processor_audiobook_followup_to_send_public_share_link"
    if stages.get("waiting_machine_playback_verification"):
        return "run_public_share_machine_playback_e2e_before_claiming_live_delivery"
    if "audiobookshelf_public_share_not_ready" in failed_codes and "whatsapp_public_share_delivery_not_sent" not in failed_codes:
        return "wait_for_audiobookshelf_scan_then_rerun_whatsapp_share_followup"
    if "whatsapp_public_share_delivery_not_sent" in failed_codes or "whatsapp_public_share_message_id_missing" in failed_codes:
        return "wait_for_whatsapp_action_processor_to_send_audiobookshelf_public_share_link"
    if "whatsapp_sender_not_bound" in failed_codes or "whatsapp_session_not_bound" in failed_codes:
        return "bind_whatsapp_sender_session_then_retry_public_share_delivery"
    return "inspect_failed_whatsapp_audiobook_delivery_candidates"


def _runtime_readiness_summary(readiness_receipt: dict[str, object] | None) -> dict[str, object]:
    readiness = _as_dict(readiness_receipt)
    return {
        "receipt_present": bool(readiness),
        "ready": bool(readiness.get("ready")),
        "status": str(readiness.get("status") or ""),
        "reason": str(readiness.get("reason") or ""),
        "sidecar_ready": bool(readiness.get("sidecar_ready")),
        "state_fresh": bool(readiness.get("state_fresh")),
        "effective_session_ref_present": bool(str(readiness.get("effective_session_ref") or "").strip()),
    }


def _resolve_runtime_readiness_receipt() -> dict[str, object]:
    published = _read_json(DEFAULT_READINESS_RECEIPT)
    if published:
        return published
    try:
        module = _load_module(
            name="materialize_whatsapp_web_action_processor_readiness_for_live_delivery",
            path=ROOT / "scripts" / "materialize_whatsapp_web_action_processor_readiness.py",
        )
    except Exception:
        return {}
    try:
        return dict(
            module.build_whatsapp_web_action_processor_readiness(
                output_path=DEFAULT_READINESS_RECEIPT,
            )
        )
    except Exception:
        return {}


def _audiobook_runtime_readiness_summary() -> dict[str, object]:
    try:
        receipt = _runtime_container_preflight() or dict(audiobook_runtime_preflight())
    except Exception as exc:
        return {
            "receipt_present": False,
            "ready_for_live_intake": False,
            "status": "error",
            "reason": f"audiobook_runtime_preflight_failed:{type(exc).__name__}",
            "sample_blockers": ["audiobook_runtime_preflight_failed"],
            "voice_catalog_count": 0,
            "api_key_slot_count": 0,
            "unmixr_auto_render_enabled": False,
        }
    checks = {
        str(item.get("key") or "").strip(): str(item.get("status") or "").strip()
        for item in list(receipt.get("checks") or [])
        if isinstance(item, dict) and str(item.get("key") or "").strip()
    }
    sample_blockers = [
        key
        for key in (
            "telegram_audiobook_enabled",
            "jobs_root_durable",
            "jobs_root_writable",
            "external_tts_enabled",
            "unmixr_auto_render_enabled",
            "voice_catalog_configured",
        )
        if checks.get(key) == "fail"
    ]
    provider = _as_dict(receipt.get("provider"))
    voice_catalog_count = int(provider.get("voice_catalog_count") or 0)
    min_candidates = int(provider.get("voice_audition_min_candidates") or 3)
    if voice_catalog_count < min_candidates:
        sample_blockers.append("voice_catalog_audition_ready")
    if int(provider.get("api_key_slot_count") or 0) <= 0:
        sample_blockers.append("unmixr_api_key_slot_present")
    sample_blockers = _dedupe(sample_blockers)
    return {
        "receipt_present": True,
        "ready_for_live_intake": not sample_blockers,
        "status": str(receipt.get("status") or "").strip(),
        "reason": "" if not sample_blockers else ", ".join(sample_blockers),
        "sample_blockers": sample_blockers,
        "voice_catalog_count": voice_catalog_count,
        "api_key_slot_count": int(provider.get("api_key_slot_count") or 0),
        "unmixr_auto_render_enabled": bool(provider.get("unmixr_auto_render_enabled")),
    }


def build_receipt(
    *,
    output_path: Path = DEFAULT_OUTPUT,
    job_receipts: list[dict[str, object]] | None = None,
    generated_at: str | None = None,
    limit: int = 100,
    observation_source: str = "provided_job_receipts",
    historical_receipts: dict[str, dict[str, object]] | None = None,
    readiness_receipt: dict[str, object] | None = None,
) -> dict[str, object]:
    generated_timestamp = generated_at or _now_iso()
    reference = _parse_utc(generated_timestamp) or datetime.now(UTC)
    observed_jobs = [job for job in list(job_receipts or [])[:limit] if isinstance(job, dict)]
    jobs = [
        job
        for job in observed_jobs
        if _is_whatsapp_job(job) and _job_matches_runtime_session(job, readiness_receipt=readiness_receipt)
    ]
    candidates = [_candidate_or_malformed(job, reference=reference) for job in jobs]
    selected_pool = _selected_candidate_pool(candidates)
    valid_candidates = [candidate for candidate in selected_pool if not candidate["failed_codes"]]
    selected = valid_candidates[0] if valid_candidates else (
        min(selected_pool, key=lambda candidate: len(list(candidate.get("failed_codes") or []))) if selected_pool else {}
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
    failed_codes = _dedupe([code for candidate in candidates for code in list(candidate.get("failed_codes") or [])])
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
    human_acceptance_evidence = _playback_acceptance_evidence(selected) if selected else {
        "status": "not_human_verified",
        "accepted": False,
        "rejected": False,
        "rejected_claim_observed": False,
        "whatsapp_sourced": False,
        "source_present": False,
        "feedback_sha256_present": False,
        "feedback_sha256_valid": False,
        "feedback_sha256_required": False,
        "operator_grade": False,
        "evidence_grade": "not_operator_evidence",
        "claim_allowed": False,
        "next_action": "capture_real_user_playback_acceptance_or_close_operator_loop",
    }
    claim_scope = (
        "machine_playable_delivery_and_human_accepted"
        if live_pass and bool(human_acceptance_evidence.get("claim_allowed"))
        else ("machine_playable_delivery_only" if live_pass else "none")
    )
    playback_acceptance_feedback_hashed = bool(human_acceptance_evidence.get("feedback_sha256_valid"))
    if not candidates:
        failed_codes.insert(0, "whatsapp_audiobook_job_missing")
    if not valid_candidates and "valid_live_audiobook_delivery_missing" not in failed_codes:
        failed_codes.insert(0, "valid_live_audiobook_delivery_missing")
    stage_summary = _stage_summary(candidates)
    stage_counts = dict(stage_summary.get("counts") or {})
    historical = _historical_evidence(historical_receipts)
    runtime_readiness = _runtime_readiness_summary(readiness_receipt)
    audiobook_runtime = _audiobook_runtime_readiness_summary()
    voice_selection_text_fallback_ready = _voice_selection_text_fallback_ready(historical)
    if not candidates and bool(historical.get("present")):
        failed_codes.append("fresh_live_whatsapp_job_receipt_missing")
    if not live_pass and not bool(audiobook_runtime.get("ready_for_live_intake")):
        failed_codes.append("audiobook_runtime_not_ready")
    failed_codes = _dedupe(failed_codes)
    waiting_voice_choice = bool(
        stage_counts.get("waiting_voice_choice") or stage_counts.get("waiting_replacement_voice_choice")
    ) and not live_pass
    waiting_provider_pacing = bool(stage_counts.get("waiting_provider_pacing")) and not live_pass
    waiting_for_live_epub = (
        not live_pass
        and not candidates
        and bool(historical.get("historical_live_path_proven"))
        and bool(runtime_readiness.get("ready"))
        and bool(audiobook_runtime.get("ready_for_live_intake"))
    )
    receipt_status = "pass" if live_pass else (
        "waiting_voice_choice"
        if waiting_voice_choice
        else (
            "waiting_provider_throttle"
            if waiting_provider_pacing
            else ("waiting_for_live_epub" if waiting_for_live_epub else "blocked")
        )
    )

    receipt = {
        "contract_name": CONTRACT_NAME,
        "generated_at": generated_timestamp,
        "generated_by": "ea/scripts/materialize_whatsapp_audiobook_live_delivery_receipt.py",
        "source_git_head": resolve_source_state_head(ROOT),
        "head_semantics": "source_state",
        "source_state_fingerprint": resolve_source_worktree_fingerprint(ROOT),
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
        "output_path": _logical_output_path(output_path),
        "observation_source": observation_source,
        "limit": limit,
        "claim": (
            "WhatsApp EPUB audiobook delivery has live proof only when a sanitized job receipt shows the M4B is ready, "
            "Audiobookshelf imported and public-shared it, WhatsApp sent the public share link, and machine playback works. "
            "Human playback acceptance is a separate claim and is not implied by machine-playable delivery."
        ),
        "status": receipt_status,
        "live_delivery_claim_allowed": live_pass,
        "live_delivery_claim_scope": claim_scope,
        "fresh_live_job_receipt_proven": live_pass,
        "historical_or_shadow_proof_only": (not bool(candidates)) and bool(historical.get("present")),
        "proof_freshness": {
            "fresh_live_job_receipt_present": bool(candidates),
            "fresh_live_job_receipt_passed": live_pass,
            "max_age_seconds": LIVE_PROOF_MAX_AGE_SECONDS,
            "selected_job_receipt": _as_dict(_as_dict(selected.get("proof_freshness")).get("job_receipt"))
            if selected
            else {},
            "selected_audio_publication_gate": _as_dict(
                _as_dict(selected.get("proof_freshness")).get("audio_publication_gate")
            ) if selected else {},
            "selected_machine_playback": _as_dict(_as_dict(selected.get("proof_freshness")).get("machine_playback"))
            if selected
            else {},
            "historical_evidence_present": bool(historical.get("present")),
            "historical_live_path_proven": bool(historical.get("historical_live_path_proven")),
            "shadow_voice_selection_only": False,
        },
        "machine_playback_e2e_verified": machine_verified,
        "real_user_playback_acceptance_verified": real_user_accepted,
        "human_playback_acceptance_claim_allowed": bool(human_acceptance_evidence.get("claim_allowed")),
        "human_playback_acceptance_evidence": human_acceptance_evidence,
        "canary_completion_claim_allowed": bool(
            live_pass and selected.get("canary_completion_claim_allowed")
        ) if selected else False,
        "canary_completion_blocked_fields": list(
            _as_dict(selected.get("human_listened_canary")).get("blocked_fields") or []
        ) if selected else ["current_human_listened_canary_receipt"],
        "human_listened_canary_contract": HUMAN_LISTENED_CANARY_CONTRACT_NAME,
        "narration_plan_contract": NARRATION_PLAN_CONTRACT_NAME,
        "proof_semantics": {
            "machine_playable_delivery_evidence": "fresh_job_receipt_and_machine_playback_e2e" if live_pass else "not_proven",
            "human_acceptance_evidence": str(human_acceptance_evidence.get("status") or "not_human_verified"),
            "live_delivery_claim_scope": claim_scope,
            "machine_playable_delivery_does_not_imply_human_acceptance": True,
        },
        "goal_completion_claim_allowed": False,
        "observed_job_count": len(observed_jobs),
        "non_whatsapp_job_count": len(observed_jobs) - len(jobs),
        "candidate_count": len(candidates),
        "failed_candidate_count": len([candidate for candidate in candidates if candidate.get("failed_codes")]),
        "stage_summary": stage_summary,
        "failed_codes": [] if live_pass else failed_codes,
        "blocking_reason": "" if live_pass else ", ".join(failed_codes),
        "next_action": _live_pass_next_action(selected)
        if live_pass and selected
        else (
            "capture_real_user_playback_acceptance_or_close_operator_loop"
            if live_pass
            else _next_action(
            failed_codes=failed_codes,
            pending=pending,
            stage_counts=stage_counts,
            historical_evidence=historical,
            )
        ),
        "selected_delivery": _candidate_public(selected) if selected else {},
        "failed_candidates": [_failed_candidate_public(candidate) for candidate in candidates if candidate.get("failed_codes")],
        "pending_user_selected_voice_job_count": len(pending),
        "pending_user_selected_voice_jobs": [
            {
                **row,
                "voice_selection_text_fallback_ready": voice_selection_text_fallback_ready
                if (row.get("voice_selection_waiting") or row.get("replacement_choice_pending"))
                else False,
            }
            for row in pending
        ],
        "voice_selection_text_fallback_ready": voice_selection_text_fallback_ready if waiting_voice_choice else False,
        "historical_evidence": historical,
        "runtime_readiness": runtime_readiness,
        "audiobook_runtime": audiobook_runtime,
        "load_errors": [],
        "privacy": {
            "raw_job_receipts_persisted": False,
            "titles_redacted_to_sha256": True,
            "authors_redacted_to_sha256": True,
            "public_share_urls_redacted_to_host": True,
            "machine_playback_e2e_url_redacted": True,
            "playback_acceptance_feedback_hashed": playback_acceptance_feedback_hashed,
            "whatsapp_message_ids_hashed": True,
            "whatsapp_sender_refs_hashed": True,
            "voice_labels_hashed": True,
            "provider_secret_exposed": False,
            "audiobookshelf_token_exposed": False,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def _apply_load_errors(
    receipt: dict[str, object],
    errors: list[str] | tuple[str, ...],
) -> dict[str, object]:
    receipt["load_errors"] = _public_load_error_codes(errors)
    if not receipt["load_errors"]:
        return receipt
    receipt["status"] = "blocked"
    receipt["live_delivery_claim_allowed"] = False
    receipt["live_delivery_claim_scope"] = "none"
    receipt["fresh_live_job_receipt_proven"] = False
    receipt["machine_playback_e2e_verified"] = False
    receipt["real_user_playback_acceptance_verified"] = False
    receipt["human_playback_acceptance_claim_allowed"] = False
    receipt["canary_completion_claim_allowed"] = False
    receipt["canary_completion_blocked_fields"] = ["job_receipt_load_errors"]
    receipt["goal_completion_claim_allowed"] = False
    proof_freshness = _as_dict(receipt.get("proof_freshness"))
    proof_freshness["fresh_live_job_receipt_passed"] = False
    receipt["proof_freshness"] = proof_freshness
    human_evidence = _as_dict(receipt.get("human_playback_acceptance_evidence"))
    human_evidence.update(
        {
            "status": "not_human_verified",
            "accepted": False,
            "rejected": False,
            "rejected_claim_observed": False,
            "operator_grade": False,
            "claim_allowed": False,
        }
    )
    receipt["human_playback_acceptance_evidence"] = human_evidence
    proof_semantics = _as_dict(receipt.get("proof_semantics"))
    proof_semantics.update(
        {
            "machine_playable_delivery_evidence": "not_proven",
            "human_acceptance_evidence": "not_human_verified",
            "live_delivery_claim_scope": "none",
        }
    )
    receipt["proof_semantics"] = proof_semantics
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
    receipt["next_action"] = "inspect_failed_whatsapp_audiobook_delivery_candidates"
    return receipt


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
    try:
        root = audiobook_epub_pipeline.audiobook_jobs_root()
        job_paths = sorted(
            root.glob("**/job.json"),
            key=_safe_mtime,
            reverse=True,
        )[:limit]
    except Exception:
        return [], ["job_manifest_discovery_failed"]
    receipts: list[dict[str, object]] = []
    errors: list[str] = []
    seen_job_dirs: set[Path] = set()
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
    try:
        receipt_paths = sorted(
            root.glob("**/job_receipt.json"),
            key=_safe_mtime,
            reverse=True,
        )
    except Exception:
        errors.append("job_receipt_discovery_failed")
        receipt_paths = []
    for receipt_path in receipt_paths:
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
        source = "jobs_root"
    historical_receipts = {
        "local_intake": _read_json(DEFAULT_LOCAL_INTAKE_PROOF),
        "public_share_playback": _read_json(DEFAULT_PUBLIC_SHARE_PLAYBACK),
        "operator_bundle": _read_json(DEFAULT_OPERATOR_PROOF_BUNDLE),
    }
    readiness_receipt = _resolve_runtime_readiness_receipt()
    receipt = build_receipt(
        output_path=args.output,
        job_receipts=receipts,
        generated_at=args.generated_at or None,
        limit=args.limit,
        observation_source=source,
        historical_receipts=historical_receipts,
        readiness_receipt=readiness_receipt,
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
