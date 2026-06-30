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
import urllib.parse
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[2]
EA_ROOT = ROOT / "ea"
DEFAULT_OUTPUT = ROOT / ".codex-studio" / "published" / "whatsapp_audiobook_operator_proof_bundle.generated.json"
CONTRACT_NAME = "ea.whatsapp_audiobook_operator_proof_bundle.v1"
LIVE_DELIVERY_CLAIM_SCOPES = {"none", "machine_playable_delivery_only", "machine_playable_delivery_and_human_accepted"}
HUMAN_PLAYBACK_ACCEPTANCE_STATUSES = {"accepted", "rejected", "not_human_verified"}
SUPPORTED_CALLBACK_PREFIXES = ("ab|", "ap|", "am|")
SUPPORTED_BUTTON_KINDS = {
    "audiobook_voice",
    "audiobook_playback",
    "audiobook_voice_management",
}


if str(EA_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_ROOT))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.source_state_head import resolve_source_state_head  # noqa: E402
from scripts.source_state_head import resolve_source_worktree_fingerprint  # noqa: E402


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _load_module(*, name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"{name}_missing")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _read_json(path: Path) -> dict[str, object]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _sha256_label(value: object) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:16]


def _path_kind(value: object) -> str:
    path = str(value or "").strip()
    if not path:
        return "missing"
    if path.startswith("/data/whatsapp-actions/"):
        return "whatsapp_actions_volume"
    if path.startswith("/tmp/"):
        return "host_tmp"
    repo_root = Path(__file__).resolve().parents[2]
    try:
        Path(path).resolve().relative_to(repo_root)
        return "repo_workspace"
    except Exception:
        pass
    if path.startswith("/"):
        return "absolute_path"
    return "relative_path"


def _host_kind(value: object) -> str:
    parsed = urllib.parse.urlparse(str(value or "").strip())
    host = (parsed.hostname or "").lower()
    if not host:
        return "missing"
    if host in {"127.0.0.1", "localhost", "::1"}:
        return "loopback"
    if host.endswith(".local") or "." not in host:
        return "internal_service"
    return "external_hostname"


def _auth_headers(args: argparse.Namespace) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    token = str(getattr(args, "session_api_token", "") or "").strip()
    if token:
        header_name = str(getattr(args, "auth_header_name", "") or "Authorization").strip() or "Authorization"
        header_prefix = str(getattr(args, "auth_header_prefix", "") if getattr(args, "auth_header_prefix", None) is not None else "Bearer ")
        headers[header_name] = f"{header_prefix}{token}"
    return headers


def _request_json(
    *,
    url: str,
    args: argparse.Namespace,
    timeout: float,
) -> tuple[int, dict[str, object]]:
    request = urllib.request.Request(url, headers=_auth_headers(args), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=max(float(timeout), 0.1)) as response:
            raw = response.read().decode("utf-8")
            parsed = json.loads(raw or "{}")
            return int(response.status), parsed if isinstance(parsed, dict) else {}
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read().decode("utf-8", errors="ignore")
            parsed = json.loads(raw or "{}")
        except Exception:
            parsed = {}
        return int(exc.code), parsed if isinstance(parsed, dict) else {}


def _is_epub_media(message: dict[str, object]) -> bool:
    filename = str(message.get("media_filename") or "").strip().lower()
    mimetype = str(message.get("media_mime_type") or "").strip().lower()
    return bool(message.get("media_present")) and (filename.endswith(".epub") or mimetype in {"application/epub+zip", "application/x-epub+zip"})


def _message_sender_or_chat_present(message: dict[str, object]) -> bool:
    sender_digits = "".join(ch for ch in str(message.get("sender_digits") or "") if ch.isdigit())
    chat_ref = str(message.get("chat_ref") or message.get("chatRef") or "").strip()
    return bool(sender_digits or chat_ref)


def _message_direct_callback_data(message: dict[str, object]) -> str:
    return str(
        message.get("selected_button_id")
        or message.get("selectedButtonId")
        or message.get("selected_button_callback")
        or message.get("button_callback_data")
        or message.get("callback_data")
        or ""
    ).strip()


def _message_selected_button_label(message: dict[str, object]) -> str:
    return str(
        message.get("selected_button_label")
        or message.get("selected_option_label")
        or message.get("poll_selected_option_label")
        or ""
    ).strip()


def _message_context_present(message: dict[str, object]) -> bool:
    for key in (
        "selected_button_message_id",
        "selected_button_parent_id",
        "selected_button_context_id",
        "button_message_id",
        "poll_message_id",
        "quoted_message_id",
        "context_message_id",
        "context_id",
        "parent_message_id",
        "reply_to_message_id",
    ):
        if str(message.get(key) or "").strip():
            return True
    return isinstance(message.get("context"), dict) and bool(message.get("context"))


def _is_inbound_user_message(message: dict[str, object]) -> bool:
    return str(message.get("direction") or "").strip() == "inbound" and not bool(message.get("from_me"))


def _button_action_observation(message: dict[str, object]) -> dict[str, bool]:
    if not _is_inbound_user_message(message) or not _message_sender_or_chat_present(message):
        return {
            "direct_callback": False,
            "selected_button_id_present": False,
            "label_fallback": False,
            "context_present": False,
            "poll_vote": False,
            "actionable": False,
        }
    direct_callback = _message_direct_callback_data(message)
    selected_button_id_present = bool(message.get("selected_button_id_present"))
    selected_kind = str(message.get("selected_button_kind") or "").strip()
    has_supported_kind = selected_kind in SUPPORTED_BUTTON_KINDS
    has_supported_direct_callback = (
        direct_callback.startswith(SUPPORTED_CALLBACK_PREFIXES)
        or (has_supported_kind and bool(direct_callback))
    )
    context_present = _message_context_present(message)
    poll_vote = str(message.get("type") or "").strip() == "poll_vote"
    label_fallback = bool(_message_selected_button_label(message)) and (
        poll_vote or context_present or has_supported_kind
    )
    selected_button_surface = selected_button_id_present and (
        has_supported_kind or bool(direct_callback)
    )
    return {
        "direct_callback": has_supported_direct_callback,
        "selected_button_id_present": selected_button_id_present,
        "label_fallback": label_fallback,
        "context_present": context_present,
        "poll_vote": poll_vote,
        "actionable": has_supported_direct_callback or selected_button_surface or label_fallback,
    }


def _sidecar_inbox_observation(readiness_args: argparse.Namespace) -> dict[str, object]:
    base_url = str(getattr(readiness_args, "session_api_base_url", "") or "").strip().rstrip("/")
    session_ref = str(getattr(readiness_args, "session_ref", "") or "").strip()
    if not base_url or not session_ref:
        return {
            "attempted": False,
            "status": "missing_runtime_coordinates",
            "messages_accessible": False,
            "raw_text_exposed": False,
            "raw_sender_exposed": False,
            "raw_message_ids_exposed": False,
            "raw_media_url_exposed": False,
        }
    timeout = float(getattr(readiness_args, "timeout_seconds", 15.0) or 15.0)
    try:
        status_code, payload = _request_json(
            url=f"{base_url}/sessions/{urllib.parse.quote(session_ref)}/messages?take=100",
            args=readiness_args,
            timeout=timeout,
        )
    except Exception as exc:
        return {
            "attempted": True,
            "status": "failed",
            "reason": type(exc).__name__,
            "messages_accessible": False,
            "session_api_host_kind": _host_kind(base_url),
            "raw_text_exposed": False,
            "raw_sender_exposed": False,
            "raw_message_ids_exposed": False,
            "raw_media_url_exposed": False,
        }

    messages = [item for item in list(payload.get("messages") or []) if isinstance(item, dict)]
    inbound_messages = [item for item in messages if str(item.get("direction") or "").strip() == "inbound"]
    media_messages = [item for item in messages if bool(item.get("media_present"))]
    epub_messages = [item for item in media_messages if _is_epub_media(item)]
    button_observations = [_button_action_observation(item) for item in messages]
    selected_button_messages = [row for row in button_observations if row["selected_button_id_present"]]
    direct_callback_messages = [row for row in button_observations if row["direct_callback"]]
    label_fallback_messages = [row for row in button_observations if row["label_fallback"]]
    context_fallback_messages = [row for row in button_observations if row["label_fallback"] and row["context_present"]]
    poll_vote_messages = [row for row in button_observations if row["poll_vote"]]
    actionable_button_messages = [row for row in button_observations if row["actionable"]]
    latest_timestamps = [
        str(item.get("message_timestamp") or item.get("received_at") or "").strip()
        for item in messages
        if str(item.get("message_timestamp") or item.get("received_at") or "").strip()
    ]
    return {
        "attempted": True,
        "status": "pass" if status_code == 200 and bool(payload.get("ok", True)) else "blocked",
        "status_code": status_code,
        "session_api_host_kind": _host_kind(base_url),
        "session_ready": bool(payload.get("ready")),
        "session_status": str(payload.get("status") or ""),
        "messages_accessible": status_code == 200 and isinstance(payload.get("messages"), list),
        "inbox_count": int(payload.get("inbox_count") or len(messages)),
        "message_count": len(messages),
        "inbound_message_count": len(inbound_messages),
        "media_message_count": len(media_messages),
        "epub_media_candidate_count": len(epub_messages),
        "selected_button_candidate_count": len(selected_button_messages),
        "direct_button_callback_candidate_count": len(direct_callback_messages),
        "selected_button_label_fallback_candidate_count": len(label_fallback_messages),
        "selected_button_context_fallback_candidate_count": len(context_fallback_messages),
        "poll_vote_candidate_count": len(poll_vote_messages),
        "actionable_button_candidate_count": len(actionable_button_messages),
        "latest_message_timestamp_present": bool(latest_timestamps),
        "raw_text_exposed": False,
        "raw_sender_exposed": False,
        "raw_message_ids_exposed": False,
        "raw_media_url_exposed": False,
    }


def _runtime_alignment(readiness_args: argparse.Namespace, processor_args: argparse.Namespace | None) -> dict[str, object]:
    def _host_kind_compatible(readiness_kind: str, processor_kind: str) -> bool:
        if readiness_kind == processor_kind:
            return True
        return {readiness_kind, processor_kind} <= {"loopback", "internal_service"}

    if processor_args is None:
        return {
            "evaluated": False,
            "state_file_match": False,
            "session_ref_match": False,
            "session_api_host_kind_match": False,
            "session_api_host_kind_exact_match": False,
            "secret_values_exposed": False,
        }
    readiness_state_file = str(getattr(readiness_args, "state_file", "") or "").strip()
    processor_state_file = str(getattr(processor_args, "state_file", "") or "").strip()
    readiness_session_ref = str(getattr(readiness_args, "session_ref", "") or "").strip()
    processor_session_ref = str(getattr(processor_args, "session_ref", "") or "").strip()
    readiness_api_base_url = str(getattr(readiness_args, "session_api_base_url", "") or "").strip()
    processor_api_base_url = str(getattr(processor_args, "session_api_base_url", "") or "").strip()
    readiness_host_kind = _host_kind(readiness_api_base_url)
    processor_host_kind = _host_kind(processor_api_base_url)
    exact_match = processor_host_kind == readiness_host_kind
    return {
        "evaluated": True,
        "state_file_match": processor_state_file == readiness_state_file,
        "state_file_kinds_match": _path_kind(processor_state_file) == _path_kind(readiness_state_file),
        "processor_state_file_kind": _path_kind(processor_state_file),
        "readiness_state_file_kind": _path_kind(readiness_state_file),
        "processor_state_file_sha256": _sha256_label(processor_state_file),
        "readiness_state_file_sha256": _sha256_label(readiness_state_file),
        "session_ref_match": processor_session_ref == readiness_session_ref,
        "processor_session_ref_sha256": _sha256_label(processor_session_ref),
        "readiness_session_ref_sha256": _sha256_label(readiness_session_ref),
        "session_api_host_kind_match": _host_kind_compatible(readiness_host_kind, processor_host_kind),
        "session_api_host_kind_exact_match": exact_match,
        "processor_session_api_host_kind": processor_host_kind,
        "readiness_session_api_host_kind": readiness_host_kind,
        "secret_values_exposed": False,
    }


def _readiness_args(readiness_module):
    return argparse.Namespace(
        api_container="ea-api",
        auth_header_name=readiness_module._env("EA_WHATSAPP_WEB_SESSION_AUTH_HEADER_NAME", "Authorization"),
        auth_header_prefix=readiness_module._env("EA_WHATSAPP_WEB_SESSION_AUTH_HEADER_PREFIX", "Bearer "),
        check_containers=True,
        compose_file=readiness_module._env("EA_WHATSAPP_WEB_ACTION_COMPOSE_FILE", str(readiness_module.DEFAULT_COMPOSE_FILE)),
        env_file=readiness_module._env("EA_WHATSAPP_WEB_ACTION_ENV_FILE", str(readiness_module.DEFAULT_ENV_FILE)),
        probe_sidecar=True,
        processor_container="ea-whatsapp-web-action-processor",
        session_api_base_url=readiness_module._env(
            "EA_WHATSAPP_WEB_SESSION_API_BASE_URL",
            readiness_module.DEFAULT_SESSION_API_BASE_URL,
        ),
        session_api_token=readiness_module._env("EA_WHATSAPP_WEB_SESSION_API_TOKEN"),
        session_ref=readiness_module._env("EA_WHATSAPP_WEB_DEFAULT_SESSION_REF", readiness_module.DEFAULT_SESSION_REF),
        state_file=readiness_module._env("EA_WHATSAPP_WEB_ACTION_STATE_FILE", readiness_module.DEFAULT_ACTION_STATE_FILE),
        state_stale_seconds=600,
        timeout_seconds=15.0,
    )


def _int_env(name: str, default: int) -> int:
    try:
        return int(str(os.environ.get(name) or default).strip())
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(str(os.environ.get(name) or default).strip())
    except ValueError:
        return default


def _bool_env(name: str, default: bool) -> bool:
    value = str(os.environ.get(name) or "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def _module_attr(module, name: str, default):
    return getattr(module, name, default)


def _live_delivery_claim_scope(live_receipt: dict[str, object], live_status: str) -> str:
    scope = str(live_receipt.get("live_delivery_claim_scope") or "").strip()
    if scope in LIVE_DELIVERY_CLAIM_SCOPES:
        return scope
    if live_status != "pass":
        return "none"
    return ""


def _human_playback_acceptance_evidence(live_receipt: dict[str, object], live_status: str) -> dict[str, object]:
    evidence = dict(live_receipt.get("human_playback_acceptance_evidence") or {})
    status = str(evidence.get("status") or "").strip()
    if status in HUMAN_PLAYBACK_ACCEPTANCE_STATUSES:
        rejected_claim_observed = bool(evidence.get("rejected_claim_observed")) or status == "rejected"
        feedback_sha256_valid = bool(evidence.get("feedback_sha256_valid"))
        if status == "rejected" and not feedback_sha256_valid:
            return {
                "status": "not_human_verified",
                "accepted": False,
                "rejected": False,
                "rejected_claim_observed": rejected_claim_observed,
                "whatsapp_sourced": bool(evidence.get("whatsapp_sourced")),
                "source_present": bool(evidence.get("source_present")),
                "feedback_sha256_present": bool(evidence.get("feedback_sha256_present")),
                "feedback_sha256_valid": False,
                "feedback_sha256_required": True,
                "operator_grade": False,
                "evidence_grade": "insufficient_feedback_hash",
                "claim_allowed": False,
                "next_action": "capture_hashed_audiobook_playback_problem_feedback",
            }
        return {
            "status": status,
            "accepted": bool(evidence.get("accepted")),
            "rejected": True if status == "rejected" else bool(evidence.get("rejected")),
            "rejected_claim_observed": rejected_claim_observed,
            "whatsapp_sourced": bool(evidence.get("whatsapp_sourced")),
            "source_present": bool(evidence.get("source_present")),
            "feedback_sha256_present": bool(evidence.get("feedback_sha256_present")),
            "feedback_sha256_valid": feedback_sha256_valid,
            "feedback_sha256_required": True if status == "rejected" else bool(evidence.get("feedback_sha256_required")),
            "operator_grade": True if status == "rejected" else bool(evidence.get("operator_grade")),
            "evidence_grade": "operator" if status == "rejected" else str(evidence.get("evidence_grade") or ""),
            "claim_allowed": bool(evidence.get("claim_allowed")),
            "next_action": str(evidence.get("next_action") or ""),
        }
    if live_status != "pass":
        return {
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
    return evidence


def _proof_semantics(
    *,
    live_receipt: dict[str, object],
    live_status: str,
    live_delivery_claim_scope: str,
    human_playback_acceptance_status: str,
) -> dict[str, object]:
    semantics = dict(live_receipt.get("proof_semantics") or {})
    return {
        "machine_playable_delivery_evidence": str(
            semantics.get("machine_playable_delivery_evidence")
            or ("fresh_job_receipt_and_machine_playback_e2e" if live_status == "pass" else "not_proven")
        ),
        "human_acceptance_evidence": human_playback_acceptance_status or "not_human_verified",
        "live_delivery_claim_scope": live_delivery_claim_scope or "none",
        "machine_playable_delivery_does_not_imply_human_acceptance": bool(
            semantics.get("machine_playable_delivery_does_not_imply_human_acceptance", True)
        ),
    }


def _goal_completion_claim_allowed(live_receipt: dict[str, object], live_status: str) -> bool:
    value = live_receipt.get("goal_completion_claim_allowed")
    if isinstance(value, bool):
        return value
    if live_status != "pass" and live_receipt.get("live_delivery_claim_allowed") is False:
        return False
    return bool(value)


def _processor_args(processor_module, readiness_args: argparse.Namespace | None = None):
    resolved_session_api_base_url = str(getattr(readiness_args, "session_api_base_url", "") or "").strip()
    resolved_session_ref = str(getattr(readiness_args, "session_ref", "") or "").strip()
    resolved_state_file = str(getattr(readiness_args, "state_file", "") or "").strip()
    return argparse.Namespace(
        audiobook_followup_enabled=_bool_env("EA_WHATSAPP_AUDIOBOOK_FOLLOWUP_ENABLED", True),
        audiobook_followup_limit=_int_env("EA_WHATSAPP_AUDIOBOOK_FOLLOWUP_LIMIT", 3),
        audiobook_resume_due=_bool_env("EA_WHATSAPP_AUDIOBOOK_RESUME_DUE", False),
        audiobook_resume_due_limit=_int_env("EA_WHATSAPP_AUDIOBOOK_RESUME_DUE_LIMIT", 1),
        auth_header_name=processor_module._env("EA_WHATSAPP_WEB_SESSION_AUTH_HEADER_NAME", "Authorization"),
        auth_header_prefix=os.environ.get("EA_WHATSAPP_WEB_SESSION_AUTH_HEADER_PREFIX", "Bearer "),
        dry_run=False,
        conversation_fallback_enabled=_bool_env("EA_WHATSAPP_WEB_ACTION_CONVERSATION_FALLBACK_ENABLED", True),
        conversation_fallback_take=_int_env("EA_WHATSAPP_WEB_ACTION_CONVERSATION_FALLBACK_TAKE", 25),
        conversation_fallback_message_limit=_int_env("EA_WHATSAPP_WEB_ACTION_CONVERSATION_FALLBACK_MESSAGE_LIMIT", 25),
        conversation_fallback_fetch_timeout_ms=_int_env("EA_WHATSAPP_WEB_ACTION_CONVERSATION_FALLBACK_FETCH_TIMEOUT_MS", 15000),
        conversation_fallback_fetch_concurrency=_int_env("EA_WHATSAPP_WEB_ACTION_CONVERSATION_FALLBACK_FETCH_CONCURRENCY", 6),
        principal_id=processor_module._env(
            "EA_WHATSAPP_WEB_DEFAULT_PRINCIPAL_ID",
            processor_module._env("EA_WHATSAPP_DEFAULT_PRINCIPAL_ID", processor_module.DEFAULT_AUDIOBOOK_PRINCIPAL_ID),
        ),
        reply_heyy_ai_key=processor_module._env(
            "EA_WHATSAPP_WEB_ACTION_REPLY_HEYY_AI_KEY",
            _module_attr(processor_module, "DEFAULT_ACTION_REPLY_HEYY_AI_KEY", "empathetic_slow_typing_old_lady"),
        ),
        reply_heyy_ai_name=processor_module._env(
            "EA_WHATSAPP_WEB_ACTION_REPLY_HEYY_AI_NAME",
            _module_attr(processor_module, "DEFAULT_ACTION_REPLY_HEYY_AI_NAME", "Herta (Heyy Lady)"),
        ),
        reply_pre_reply_delay_min_seconds=_int_env(
            "EA_WHATSAPP_WEB_ACTION_REPLY_PRE_REPLY_DELAY_MIN_SECONDS",
            _module_attr(processor_module, "DEFAULT_ACTION_REPLY_PRE_REPLY_DELAY_MIN_SECONDS", 60),
        ),
        reply_pre_reply_delay_max_seconds=_int_env(
            "EA_WHATSAPP_WEB_ACTION_REPLY_PRE_REPLY_DELAY_MAX_SECONDS",
            _module_attr(processor_module, "DEFAULT_ACTION_REPLY_PRE_REPLY_DELAY_MAX_SECONDS", 900),
        ),
        reply_quiet_hours_start_hour=_int_env(
            "EA_WHATSAPP_WEB_ACTION_REPLY_QUIET_HOURS_START_HOUR",
            _module_attr(processor_module, "DEFAULT_ACTION_REPLY_QUIET_HOURS_START_HOUR", 21),
        ),
        reply_quiet_hours_end_hour=_int_env(
            "EA_WHATSAPP_WEB_ACTION_REPLY_QUIET_HOURS_END_HOUR",
            _module_attr(processor_module, "DEFAULT_ACTION_REPLY_QUIET_HOURS_END_HOUR", 6),
        ),
        reply_typing_delay_ms=_int_env(
            "EA_WHATSAPP_WEB_ACTION_REPLY_TYPING_DELAY_MS",
            _module_attr(processor_module, "DEFAULT_ACTION_REPLY_TYPING_DELAY_MS", 6500),
        ),
        reply_typing_delay_ms_per_character=_int_env(
            "EA_WHATSAPP_WEB_ACTION_REPLY_TYPING_DELAY_MS_PER_CHARACTER",
            _module_attr(processor_module, "DEFAULT_ACTION_REPLY_TYPING_DELAY_MS_PER_CHARACTER", 4000),
        ),
        reply_typing_status_enabled=_bool_env("EA_WHATSAPP_WEB_ACTION_REPLY_TYPING_STATUS_ENABLED", True),
        session_api_base_url=processor_module._env(
            "EA_WHATSAPP_WEB_SESSION_API_BASE_URL",
            resolved_session_api_base_url or processor_module.DEFAULT_SESSION_API_BASE_URL,
        ),
        session_api_token=processor_module._env("EA_WHATSAPP_WEB_SESSION_API_TOKEN"),
        session_ref=processor_module._env(
            "EA_WHATSAPP_WEB_DEFAULT_SESSION_REF",
            resolved_session_ref or processor_module.DEFAULT_SESSION_REF,
        ),
        state_file=processor_module._env(
            "EA_WHATSAPP_WEB_ACTION_STATE_FILE",
            resolved_state_file or processor_module.DEFAULT_STATE_FILE,
        ),
        take=_int_env("EA_WHATSAPP_WEB_ACTION_MESSAGE_TAKE", 100),
        timeout_seconds=_float_env("EA_WHATSAPP_WEB_SESSION_REQUEST_TIMEOUT_SECONDS", 30.0),
    )


def _container_processor_args(readiness_args: argparse.Namespace) -> argparse.Namespace:
    return argparse.Namespace(
        session_api_base_url="http://ea-whatsapp-web-session:8098",
        session_ref=str(getattr(readiness_args, "session_ref", "") or ""),
        state_file=str(getattr(readiness_args, "state_file", "") or ""),
    )


def _processor_container_timeout_seconds() -> float:
    raw = os.environ.get("EA_WHATSAPP_WEB_ACTION_PROCESSOR_CONTAINER_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return 20.0
    try:
        return max(float(raw), 1.0)
    except ValueError:
        return 20.0


def _parse_json_stdout(stdout: str) -> dict[str, object]:
    for line in reversed(str(stdout or "").splitlines()):
        candidate = line.strip()
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def _resolve_processor_container(readiness_args: argparse.Namespace) -> str:
    configured = str(getattr(readiness_args, "processor_container", "") or "ea-whatsapp-web-action-processor").strip()
    service_name = "ea-whatsapp-web-action-processor"
    compose_file = Path(str(getattr(readiness_args, "compose_file", "") or ROOT / "docker-compose.whatsapp-web-session.yml"))
    compose_path = compose_file.resolve().as_posix() if compose_file.exists() else compose_file.as_posix()
    try:
        completed = subprocess.run(
            [
                "docker",
                "ps",
                "--filter",
                f"label=com.docker.compose.service={service_name}",
                "--format",
                '{{.Names}}\t{{.Status}}\t{{.Label "com.docker.compose.project.config_files"}}',
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return configured
    if completed.returncode != 0:
        return configured
    candidates: list[tuple[int, str]] = []
    for line in completed.stdout.splitlines():
        parts = line.split("\t")
        if not parts or not parts[0].strip():
            continue
        name = parts[0].strip()
        status = parts[1].strip().lower() if len(parts) > 1 else ""
        config_files = parts[2].strip() if len(parts) > 2 else ""
        score = 0
        if "(healthy)" in status:
            score += 100
        elif "up" in status and "(unhealthy)" not in status:
            score += 50
        if compose_path and compose_path in config_files.split(","):
            score += 20
        if configured and name == configured:
            score += 1
        candidates.append((score, name))
    if not candidates:
        return configured
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][1]


def _run_processor_in_container(readiness_args: argparse.Namespace) -> tuple[dict[str, object], dict[str, object]]:
    configured_container_name = str(
        getattr(readiness_args, "processor_container", "") or "ea-whatsapp-web-action-processor"
    ).strip()
    container_name = _resolve_processor_container(readiness_args)
    meta: dict[str, object] = {
        "attempted": True,
        "configured_container_name_sha256": _sha256_label(configured_container_name),
        "container_name_sha256": _sha256_label(container_name),
        "container_resolved": container_name != configured_container_name,
        "stdout_json_present": False,
        "return_code": -1,
        "timed_out": False,
        "timeout_seconds": _processor_container_timeout_seconds(),
    }
    try:
        completed = subprocess.run(
            [
                "docker",
                "exec",
                container_name,
                "python",
                "/app/scripts/process_whatsapp_web_session_actions.py",
                "--no-conversation-fallback-enabled",
                "--no-telegram-summary-enabled",
                "--no-audiobook-resume-due",
                "--no-audiobook-followup-enabled",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=float(meta["timeout_seconds"]),
        )
    except subprocess.TimeoutExpired:
        meta["timed_out"] = True
        return {"status": "failed", "errors": 1, "reason": "processor_container_timeout"}, meta
    except Exception as exc:
        return {"status": "failed", "errors": 1, "reason": type(exc).__name__}, meta

    report = _parse_json_stdout(completed.stdout)
    meta = {
        **meta,
        "stdout_json_present": bool(report),
        "return_code": int(completed.returncode),
    }
    if not report:
        return {"status": "failed", "errors": 1, "reason": "processor_container_json_missing"}, meta
    if completed.returncode != 0 and str(report.get("status") or "") == "pass":
        report = {**report, "status": "failed", "errors": 1, "reason": "processor_container_nonzero_exit"}
    return report, meta


def _processor_summary(report: dict[str, object] | None, *, ran: bool) -> dict[str, object]:
    report = report if isinstance(report, dict) else {}
    conversation_fallback = dict(report.get("conversation_fallback") or {})
    return {
        "ran": ran,
        "status": str(report.get("status") or ""),
        "message_count": int(report.get("message_count") or 0),
        "inbox_message_count": int(report.get("inbox_message_count") or 0),
        "candidate_count": int(report.get("candidate_count") or 0),
        "epub_candidate_count": int(report.get("epub_candidate_count") or 0),
        "epub_processed": int(report.get("epub_processed") or 0),
        "voice_text_candidate_count": int(report.get("voice_text_candidate_count") or 0),
        "voice_text_processed": int(report.get("voice_text_processed") or 0),
        "status_candidate_count": int(report.get("status_candidate_count") or 0),
        "status_processed": int(report.get("status_processed") or 0),
        "processed": int(report.get("processed") or 0),
        "skipped_processed": int(report.get("skipped_processed") or 0),
        "reply_sent": int(report.get("reply_sent") or 0),
        "voice_sample_sent": int(report.get("voice_sample_sent") or 0),
        "share_link_sent": int(report.get("share_link_sent") or 0),
        "errors": int(report.get("errors") or 0),
        "conversation_fallback_attempted": bool(conversation_fallback.get("attempted")),
        "conversation_fallback_epub_candidate_count": int(conversation_fallback.get("epub_candidate_count") or 0),
        "conversation_fallback": {
            "attempted": bool(conversation_fallback.get("attempted")),
            "status": str(conversation_fallback.get("status") or ""),
            "message_count": int(conversation_fallback.get("message_count") or 0),
            "button_candidate_count": int(conversation_fallback.get("button_candidate_count") or 0),
            "epub_candidate_count": int(conversation_fallback.get("epub_candidate_count") or 0),
            "status_candidate_count": int(conversation_fallback.get("status_candidate_count") or 0),
            "conversation_count": int(conversation_fallback.get("conversation_count") or 0),
            "conversation_total": int(conversation_fallback.get("conversation_total") or 0),
            "conversation_page_complete": bool(conversation_fallback.get("conversation_page_complete")),
        },
        "followup": {
            "attempted": int(dict(report.get("followup_summary") or {}).get("attempted") or 0),
            "sent": int(dict(report.get("followup_summary") or {}).get("sent") or 0),
            "errors": int(dict(report.get("followup_summary") or {}).get("errors") or 0),
        },
        "resume": {
            "ran": bool(dict(report.get("resume_summary") or {}).get("ran")),
            "errors": int(dict(report.get("resume_summary") or {}).get("errors") or 0),
        },
    }


def _local_stage_section(local_proof: dict[str, object], key: str) -> dict[str, object]:
    summary = local_proof.get("local_stage_receipt_summary")
    if not isinstance(summary, dict):
        return {}
    nested = summary.get(key)
    if isinstance(nested, dict):
        return nested
    return summary if key == "intake" else {}


def _local_processor_section(local_proof: dict[str, object], key: str) -> dict[str, object]:
    report = local_proof.get("processor_report")
    if not isinstance(report, dict):
        return {}
    nested = report.get(key)
    if isinstance(nested, dict):
        return nested
    return report if key == "intake" else {}


def materialize_whatsapp_audiobook_operator_proof_bundle(
    *,
    output_path: Path = DEFAULT_OUTPUT,
    run_live_readiness: bool = True,
    run_live_processor: bool = True,
) -> dict[str, object]:
    generated_at = _now_iso()
    local_proof_module = _load_module(
        name="materialize_whatsapp_audiobook_local_intake_proof_for_bundle",
        path=Path(__file__).with_name("materialize_whatsapp_audiobook_local_intake_proof.py"),
    )
    live_receipt_module = _load_module(
        name="materialize_whatsapp_audiobook_live_delivery_receipt_for_bundle",
        path=Path(__file__).with_name("materialize_whatsapp_audiobook_live_delivery_receipt.py"),
    )
    voice_selection_shadow_module = _load_module(
        name="materialize_whatsapp_audiobook_live_voice_selection_shadow_for_bundle",
        path=Path(__file__).with_name("materialize_whatsapp_audiobook_live_voice_selection_shadow.py"),
    )
    readiness_module = _load_module(
        name="check_whatsapp_web_action_processor_readiness_for_bundle",
        path=ROOT / "scripts" / "check_whatsapp_web_action_processor_readiness.py",
    )
    readiness_materializer_module = _load_module(
        name="materialize_whatsapp_web_action_processor_readiness_for_bundle",
        path=ROOT / "scripts" / "materialize_whatsapp_web_action_processor_readiness.py",
    )
    local_proof = local_proof_module.materialize_whatsapp_audiobook_local_intake_proof()
    readiness_args = _readiness_args(readiness_module)
    live_processor_report: dict[str, object] = {"status": "skipped"}
    processor_args: argparse.Namespace | None = None
    processor_runtime = "skipped"
    processor_container_meta: dict[str, object] = {"attempted": False, "stdout_json_present": False, "return_code": 0}
    if run_live_processor:
        container_report, processor_container_meta = _run_processor_in_container(readiness_args)
        if bool(processor_container_meta.get("stdout_json_present")):
            live_processor_report = container_report
            processor_args = _container_processor_args(readiness_args)
            processor_runtime = "container"
        else:
            processor_module = _load_module(
                name="process_whatsapp_web_session_actions_for_bundle",
                path=ROOT / "scripts" / "process_whatsapp_web_session_actions.py",
            )
            processor_args = _processor_args(processor_module, readiness_args)
            processor_runtime = "host_fallback"
            try:
                live_processor_report = dict(processor_module.build_report(processor_args))
            except Exception as exc:
                live_processor_report = {"status": "failed", "errors": 1, "reason": type(exc).__name__}
    live_processor = {
        **_processor_summary(live_processor_report, ran=run_live_processor),
        "execution_runtime": processor_runtime,
        "container_attempted": bool(processor_container_meta.get("attempted")),
        "container_stdout_json_present": bool(processor_container_meta.get("stdout_json_present")),
        "container_return_code": int(processor_container_meta.get("return_code") or 0),
        "container_resolved": bool(processor_container_meta.get("container_resolved")),
        "container_timed_out": bool(processor_container_meta.get("timed_out")),
        "container_timeout_seconds": float(processor_container_meta.get("timeout_seconds") or 0),
    }
    live_historical_receipts = {
        "local_intake": local_proof,
        "public_share_playback": _read_json(
            ROOT / ".codex-studio" / "published" / "whatsapp_audiobook_public_share_playback.generated.json"
        ),
        "operator_bundle": _read_json(
            ROOT / ".codex-studio" / "published" / "whatsapp_audiobook_operator_proof_bundle.generated.json"
        ),
    }
    if run_live_readiness:
        if hasattr(readiness_materializer_module, "build_whatsapp_web_action_processor_readiness"):
            readiness = readiness_materializer_module.build_whatsapp_web_action_processor_readiness(
                output_path=ROOT / ".codex-studio" / "published" / "whatsapp_web_action_processor_readiness.generated.json",
                generated_at=generated_at,
                args=readiness_args,
            )
        else:
            readiness = readiness_module.build_report(readiness_args)
    else:
        readiness = _read_json(ROOT / ".codex-studio" / "published" / "whatsapp_web_action_processor_readiness.generated.json")
    live_receipt = live_receipt_module.build_receipt(
        output_path=ROOT / ".codex-studio" / "published" / "whatsapp_audiobook_live_delivery.generated.json",
        job_receipts=live_receipt_module._scan_job_receipts(100)[0],
        generated_at=generated_at,
        observation_source="jobs_root",
        historical_receipts=live_historical_receipts,
        readiness_receipt=readiness,
    )
    try:
        voice_selection_shadow = voice_selection_shadow_module.build_receipt(
            output_path=ROOT
            / ".codex-studio"
            / "published"
            / "whatsapp_audiobook_live_voice_selection_shadow.generated.json",
            generated_at=generated_at,
        )
    except Exception as exc:
        voice_selection_shadow = {"status": "failed", "reason": type(exc).__name__}
    effective_session_ref = str(readiness.get("effective_session_ref") or "").strip()
    if effective_session_ref:
        readiness_args.session_ref = effective_session_ref
        if processor_args is not None:
            processor_args.session_ref = effective_session_ref
    runtime_alignment = _runtime_alignment(readiness_args, processor_args)
    sidecar_inbox = _sidecar_inbox_observation(readiness_args)

    local_status = str(local_proof.get("status") or "")
    live_status = str(live_receipt.get("status") or "")
    readiness_ready = bool(readiness.get("ready"))
    live_candidate_count = int(live_receipt.get("candidate_count") or 0)
    live_historical = dict(live_receipt.get("historical_evidence") or {})
    live_historical_present = bool(live_historical.get("present"))
    live_historical_path_proven = bool(live_historical.get("historical_live_path_proven"))
    local_intake_stage = _local_stage_section(local_proof, "intake")
    local_delivery_stage = _local_stage_section(local_proof, "delivery")
    local_intake_processor = _local_processor_section(local_proof, "intake")
    local_selection_processor = _local_processor_section(local_proof, "voice_selection")
    local_player_probe = dict(local_proof.get("player_probe_summary") or {})
    local_player_http_probe = dict(local_proof.get("player_http_probe_summary") or {})
    public_share_playback = dict(live_historical_receipts.get("public_share_playback") or {})
    local_next_action = str(local_intake_stage.get("next_action") or "")
    live_next_action = str(live_receipt.get("next_action") or "")
    live_delivery_claim_scope = _live_delivery_claim_scope(live_receipt, live_status)
    human_playback_acceptance_evidence = _human_playback_acceptance_evidence(live_receipt, live_status)
    human_playback_acceptance_status = str(human_playback_acceptance_evidence.get("status") or "").strip()
    normalized_live_next_action = (
        str(human_playback_acceptance_evidence.get("next_action") or "").strip()
        if live_status == "pass"
        else live_next_action
    ) or live_next_action
    rejected_playback_feedback_hashed_or_not_operator_grade = (
        human_playback_acceptance_status != "rejected"
        or bool(human_playback_acceptance_evidence.get("feedback_sha256_valid"))
    )
    proof_semantics = _proof_semantics(
        live_receipt=live_receipt,
        live_status=live_status,
        live_delivery_claim_scope=live_delivery_claim_scope,
        human_playback_acceptance_status=human_playback_acceptance_status,
    )
    goal_completion_claim_allowed = _goal_completion_claim_allowed(live_receipt, live_status)
    voice_selection_shadow_status = str(voice_selection_shadow.get("status") or "").strip()
    live_voice_selection_shadow_required = live_status == "waiting_voice_choice"
    historical_public_share_playback_proven = (
        str(public_share_playback.get("status") or "").strip() == "pass"
        and int(public_share_playback.get("passed") or 0) >= 1
    )
    live_public_share_playback_verified = bool(live_receipt.get("machine_playback_e2e_verified"))
    processor_callback_candidates = int(live_processor.get("candidate_count") or 0)
    processor_processed = int(live_processor.get("processed") or 0)
    processor_skipped_processed = int(live_processor.get("skipped_processed") or 0)
    processor_voice_text_candidates = int(live_processor.get("voice_text_candidate_count") or 0)
    processor_voice_text_processed = int(live_processor.get("voice_text_processed") or 0)
    sidecar_button_callback_candidates = int(sidecar_inbox.get("actionable_button_candidate_count") or 0)
    effective_button_callback_candidates = max(processor_callback_candidates, sidecar_button_callback_candidates)
    live_processor["sidecar_actionable_button_candidate_count"] = sidecar_button_callback_candidates
    live_processor["effective_button_callback_candidate_count"] = effective_button_callback_candidates
    processor_button_callbacks_drained = effective_button_callback_candidates <= processor_processed + processor_skipped_processed
    processor_voice_text_drained = processor_voice_text_candidates <= processor_voice_text_processed
    checks = {
        "local_epub_intake_proof_passed": local_status == "pass",
        "local_proof_waits_for_voice_choice": local_next_action == "choose_whatsapp_audiobook_voice_sample",
        "local_proof_selects_voice_and_sends_share": int(local_selection_processor.get("share_link_sent") or 0) >= 1,
        "local_proof_player_probe_passed": str(local_player_probe.get("status") or "") == "pass",
        "local_proof_player_http_route_passed": str(local_player_http_probe.get("status") or "") == "pass",
        "historical_public_share_playback_proven": historical_public_share_playback_proven,
        "live_action_processor_ready": readiness_ready,
        "live_action_processor_ran": run_live_processor,
        "live_action_processor_no_runtime_errors": int(live_processor.get("errors") or 0) == 0,
        "live_processor_button_callbacks_drained": processor_button_callbacks_drained,
        "live_sidecar_button_callbacks_visible_to_processor_semantics": (
            sidecar_button_callback_candidates <= processor_callback_candidates
            or effective_button_callback_candidates <= processor_processed + processor_skipped_processed
        ),
        "live_processor_voice_text_drained": processor_voice_text_drained,
        "live_processor_runtime_alignment_evaluated": bool(runtime_alignment.get("evaluated")),
        "live_sidecar_inbox_accessible": bool(sidecar_inbox.get("messages_accessible")),
        "live_receipt_materialized": live_status
        in {"pass", "blocked", "waiting_for_live_epub", "waiting_provider_throttle", "waiting_voice_choice"},
        "live_receipt_has_explicit_next_action": bool(normalized_live_next_action),
        "live_public_share_playback_verified_or_not_required": live_public_share_playback_verified if live_status == "pass" else True,
        "live_delivery_semantics_from_live_receipt_or_explicit_nonpass_default": (
            bool(live_receipt.get("proof_semantics"))
            and bool(live_receipt.get("human_playback_acceptance_evidence"))
            if live_status == "pass"
            else True
        ),
        "live_delivery_claim_scope_explicit": live_delivery_claim_scope
        in LIVE_DELIVERY_CLAIM_SCOPES,
        "human_playback_acceptance_status_explicit": human_playback_acceptance_status
        in HUMAN_PLAYBACK_ACCEPTANCE_STATUSES,
        "rejected_playback_feedback_hashed_or_not_operator_grade": rejected_playback_feedback_hashed_or_not_operator_grade,
        "machine_delivery_does_not_imply_human_acceptance": bool(
            proof_semantics.get("machine_playable_delivery_does_not_imply_human_acceptance")
        ),
        "live_goal_completion_claim_disallowed": goal_completion_claim_allowed is False,
        "live_voice_selection_text_fallback_ready_or_not_required": (
            bool(dict(voice_selection_shadow.get("checks") or {}).get("shadow_text_fallback_ready"))
            if live_voice_selection_shadow_required
            else voice_selection_shadow_status in {"pass", "waiting"}
        ),
        "live_voice_selection_shadow_passed_or_not_required": (
            voice_selection_shadow_status == "pass" if live_voice_selection_shadow_required else voice_selection_shadow_status in {"pass", "waiting"}
        ),
    }
    waiting_core_checks = {
        "local_epub_intake_proof_passed",
        "live_action_processor_ready",
        "live_action_processor_ran",
        "live_action_processor_no_runtime_errors",
        "live_processor_button_callbacks_drained",
        "live_processor_voice_text_drained",
        "live_processor_runtime_alignment_evaluated",
        "live_sidecar_inbox_accessible",
        "live_receipt_materialized",
        "live_receipt_has_explicit_next_action",
        "live_delivery_semantics_from_live_receipt_or_explicit_nonpass_default",
        "live_delivery_claim_scope_explicit",
        "human_playback_acceptance_status_explicit",
        "rejected_playback_feedback_hashed_or_not_operator_grade",
        "machine_delivery_does_not_imply_human_acceptance",
        "live_goal_completion_claim_disallowed",
        "live_voice_selection_text_fallback_ready_or_not_required",
        "live_voice_selection_shadow_passed_or_not_required",
    }
    warnings = []
    if bool(runtime_alignment.get("evaluated")) and not bool(runtime_alignment.get("state_file_match")):
        warnings.append("live_processor_state_file_mismatch")
    if bool(runtime_alignment.get("evaluated")) and not bool(runtime_alignment.get("session_ref_match")):
        warnings.append("live_processor_session_ref_mismatch")
    if bool(processor_container_meta.get("timed_out")):
        warnings.append("live_processor_container_timeout")
    if int(sidecar_inbox.get("epub_media_candidate_count") or 0) > 0 and int(live_processor.get("epub_processed") or 0) <= 0:
        warnings.append("live_epub_media_visible_but_not_processed")
    if not processor_button_callbacks_drained:
        warnings.append("live_button_callbacks_visible_but_not_processed")
    if sidecar_button_callback_candidates > processor_callback_candidates:
        warnings.append("live_sidecar_button_callbacks_exceed_processor_candidates")
    if not processor_voice_text_drained:
        warnings.append("live_voice_text_choices_visible_but_not_processed")
    if live_status == "pass" and not bool(checks.get("live_delivery_semantics_from_live_receipt_or_explicit_nonpass_default")):
        warnings.append("live_delivery_semantics_missing_from_pass_receipt")
    live_waiting_for_epub = live_candidate_count == 0 and "whatsapp_audiobook_job_missing" in list(live_receipt.get("failed_codes") or [])
    if live_status == "pass" and not bool(checks.get("live_delivery_semantics_from_live_receipt_or_explicit_nonpass_default")):
        status = "blocked"
        recommended_action = "refresh_live_delivery_receipt_with_explicit_playback_acceptance_semantics"
    elif not processor_button_callbacks_drained or not processor_voice_text_drained:
        status = "blocked"
        recommended_action = "run_whatsapp_action_processor_until_voice_choices_are_drained"
    elif live_status == "pass":
        status = "pass"
        recommended_action = normalized_live_next_action or "capture_real_user_playback_acceptance_or_close_operator_loop"
    elif live_status == "waiting_voice_choice":
        if voice_selection_shadow_status == "pass":
            status = "waiting_voice_choice"
            recommended_action = normalized_live_next_action or "choose_whatsapp_audiobook_voice_sample"
        else:
            status = "blocked"
            recommended_action = "fix_whatsapp_voice_selection_shadow_proof"
    elif live_status == "waiting_provider_throttle":
        status = "waiting_provider_throttle"
        recommended_action = normalized_live_next_action or "wait_until_provider_retry_after_then_resume_whatsapp_audiobook_render"
    elif run_live_processor and int(live_processor.get("errors") or 0) > 0:
        status = "blocked"
        recommended_action = "fix_whatsapp_action_processor_run"
    elif not bool(sidecar_inbox.get("messages_accessible")):
        status = "blocked"
        recommended_action = "fix_whatsapp_sidecar_inbox_access"
    elif (
        all(bool(checks.get(key)) for key in waiting_core_checks)
        and live_waiting_for_epub
        and live_historical_path_proven
    ):
        status = "waiting_for_live_epub"
        recommended_action = (
            "send_epub_over_whatsapp_to_refresh_live_audiobook_flow"
            if live_historical_present
            else "send_epub_over_whatsapp_to_start_live_audiobook_flow"
        )
    elif not readiness_ready:
        status = "blocked"
        recommended_action = "fix_whatsapp_action_processor_readiness"
    elif local_status != "pass":
        status = "blocked"
        recommended_action = "fix_local_whatsapp_epub_intake_path"
    else:
        status = "blocked"
        recommended_action = normalized_live_next_action or "inspect_whatsapp_audiobook_operator_bundle"
    bundle_live_delivery_status = "waiting_for_live_epub" if status == "waiting_for_live_epub" else live_status

    bundle = {
        "contract_name": CONTRACT_NAME,
        "generated_at": generated_at,
        "generated_by": "ea/scripts/materialize_whatsapp_audiobook_operator_proof_bundle.py",
        "source_git_head": resolve_source_state_head(ROOT),
        "head_semantics": "source_state",
        "source_state_fingerprint": resolve_source_worktree_fingerprint(ROOT),
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
        "status": status,
        "recommended_action": recommended_action,
        "claim": (
            "This bundle combines local WhatsApp EPUB intake proof, live WhatsApp action processor readiness, "
            "and the live WhatsApp audiobook delivery receipt. It separates implementation proof from live delivery proof."
        ),
        "checks": checks,
        "warnings": warnings,
        "proof_semantics": {
            "machine_playable_delivery_evidence": str(proof_semantics.get("machine_playable_delivery_evidence") or ""),
            "human_acceptance_evidence": str(
                proof_semantics.get("human_acceptance_evidence") or human_playback_acceptance_status
            ),
            "live_delivery_claim_scope": live_delivery_claim_scope,
            "machine_playable_delivery_does_not_imply_human_acceptance": bool(
                proof_semantics.get("machine_playable_delivery_does_not_imply_human_acceptance")
            ),
        },
        "runtime_alignment": runtime_alignment,
        "local_intake": {
            "status": local_status,
            "voice_sample_sent": int(local_intake_processor.get("voice_sample_sent") or 0),
            "next_action": local_next_action,
            "delivery_stage_next_action": str(local_delivery_stage.get("next_action") or ""),
            "delivery_stage_counts": dict(local_delivery_stage.get("stage_counts") or {}),
            "voice_selection_processed": int(local_selection_processor.get("processed") or 0),
            "share_link_sent": int(local_selection_processor.get("share_link_sent") or 0),
            "player_probe": {
                "status": str(local_player_probe.get("status") or ""),
                "metadata_status": str(local_player_probe.get("metadata_status") or ""),
                "content_type": str(local_player_probe.get("content_type") or ""),
                "audio_streams": int(local_player_probe.get("audio_streams") or 0),
                "duration_seconds": float(local_player_probe.get("duration_seconds") or 0.0),
            },
            "player_http_probe": {
                "status": str(local_player_http_probe.get("status") or ""),
                "metadata_status_code": int(local_player_http_probe.get("metadata_status_code") or 0),
                "download_status_code": int(local_player_http_probe.get("download_status_code") or 0),
                "download_content_type": str(local_player_http_probe.get("download_content_type") or ""),
                "download_bytes": int(local_player_http_probe.get("download_bytes") or 0),
            },
            "receipt_path": str(local_proof.get("receipt_path") or ""),
        },
        "live_readiness": {
            "status": str(readiness.get("status") or ""),
            "ready": readiness_ready,
            "reason": str(readiness.get("reason") or ""),
            "reasons": list(readiness.get("reasons") or []),
            "action_processor_enabled": bool(readiness.get("action_processor_enabled")),
            "sidecar_ready": bool(readiness.get("sidecar_ready")),
            "state_fresh": bool(readiness.get("state_fresh")),
        },
        "live_sidecar_inbox": sidecar_inbox,
        "live_processor": live_processor,
        "live_delivery": {
            "status": bundle_live_delivery_status,
            "candidate_count": live_candidate_count,
            "observed_job_count": int(live_receipt.get("observed_job_count") or 0),
            "non_whatsapp_job_count": int(live_receipt.get("non_whatsapp_job_count") or 0),
            "failed_codes": list(live_receipt.get("failed_codes") or []),
            "next_action": normalized_live_next_action,
            "stage_counts": dict(dict(live_receipt.get("stage_summary") or {}).get("counts") or {}),
            "live_delivery_claim_allowed": bool(live_receipt.get("live_delivery_claim_allowed")),
            "live_delivery_claim_scope": live_delivery_claim_scope,
            "machine_playback_e2e_verified": bool(live_receipt.get("machine_playback_e2e_verified")),
            "fresh_live_job_receipt_proven": bool(live_receipt.get("fresh_live_job_receipt_proven")),
            "historical_or_shadow_proof_only": bool(live_receipt.get("historical_or_shadow_proof_only")),
            "proof_freshness": dict(live_receipt.get("proof_freshness") or {}),
            "real_user_playback_acceptance_verified": bool(live_receipt.get("real_user_playback_acceptance_verified")),
            "human_playback_acceptance_claim_allowed": bool(
                live_receipt.get("human_playback_acceptance_claim_allowed")
            ),
            "human_playback_acceptance_evidence": human_playback_acceptance_evidence,
            "proof_semantics": proof_semantics,
            "goal_completion_claim_allowed": goal_completion_claim_allowed,
            "historical_evidence_present": live_historical_present,
            "historical_live_path_proven": live_historical_path_proven,
        },
        "public_share_playback": {
            "status": str(public_share_playback.get("status") or ""),
            "attempted": int(public_share_playback.get("attempted") or 0),
            "passed": int(public_share_playback.get("passed") or 0),
            "failed": int(public_share_playback.get("failed") or 0),
            "historical_playback_path_proven": historical_public_share_playback_proven,
        },
        "live_voice_selection_shadow": {
            "status": voice_selection_shadow_status,
            "reason": str(voice_selection_shadow.get("reason") or ""),
            "candidate": {
                "status": str(dict(voice_selection_shadow.get("candidate") or {}).get("status") or ""),
                "next_action": str(dict(voice_selection_shadow.get("candidate") or {}).get("next_action") or ""),
                "pending_voice_count": int(dict(voice_selection_shadow.get("candidate") or {}).get("pending_voice_count") or 0),
                "voice_sample_delivery_status": str(
                    dict(voice_selection_shadow.get("candidate") or {}).get("voice_sample_delivery_status") or ""
                ),
            },
            "shadow": {
                "status": str(dict(voice_selection_shadow.get("shadow") or {}).get("status") or ""),
                "callback_status": str(dict(voice_selection_shadow.get("shadow") or {}).get("callback_status") or ""),
                "shadow_status": str(dict(voice_selection_shadow.get("shadow") or {}).get("shadow_status") or ""),
                "shadow_next_action": str(dict(voice_selection_shadow.get("shadow") or {}).get("shadow_next_action") or ""),
                "pending_voice_count_after": int(
                    dict(voice_selection_shadow.get("shadow") or {}).get("pending_voice_count_after") or 0
                ),
                "selected_label_present": bool(dict(voice_selection_shadow.get("shadow") or {}).get("selected_label_present")),
            },
            "text_fallback": {
                "status": str(dict(voice_selection_shadow.get("text_fallback") or {}).get("status") or ""),
                "use_named_action": str(dict(voice_selection_shadow.get("text_fallback") or {}).get("use_named_action") or ""),
                "dismiss_named_action": str(dict(voice_selection_shadow.get("text_fallback") or {}).get("dismiss_named_action") or ""),
                "dismiss_all_action": str(dict(voice_selection_shadow.get("text_fallback") or {}).get("dismiss_all_action") or ""),
                "bare_voice_choice_resolved": bool(
                    dict(voice_selection_shadow.get("text_fallback") or {}).get("bare_voice_choice_resolved")
                ),
                "fallback_prompt_mentions_text_commands": bool(
                    dict(voice_selection_shadow.get("text_fallback") or {}).get("fallback_prompt_mentions_text_commands")
                ),
            },
            "checks": dict(voice_selection_shadow.get("checks") or {}),
            "live_job_unchanged": bool(dict(voice_selection_shadow.get("live_mutation") or {}).get("unchanged")),
        },
        "privacy": {
            "raw_whatsapp_sender_exposed": False,
            "raw_whatsapp_message_id_exposed": False,
            "raw_callback_tokens_exposed": False,
            "raw_provider_secret_exposed": False,
            "raw_book_text_exposed": False,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {**bundle, "receipt_path": output_path.as_posix()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--no-live-readiness", action="store_true")
    parser.add_argument("--no-live-processor", action="store_true")
    parser.add_argument("--require-ready-or-waiting", action="store_true")
    args = parser.parse_args()
    result = materialize_whatsapp_audiobook_operator_proof_bundle(
        output_path=args.output,
        run_live_readiness=not args.no_live_readiness,
        run_live_processor=not args.no_live_processor,
    )
    print(json.dumps(result, sort_keys=True))
    allowed_waiting = {"pass", "waiting_for_live_epub", "waiting_provider_throttle", "waiting_voice_choice"}
    allowed_statuses = {*allowed_waiting, "blocked"}
    if args.require_ready_or_waiting and result["status"] not in allowed_waiting:
        return 2
    return 0 if result["status"] in allowed_statuses else 1


if __name__ == "__main__":
    raise SystemExit(main())
