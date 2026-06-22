#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "ea", ROOT):
    if path.exists() and str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.services import audiobook_access_approval, audiobook_epub_pipeline, proactive_telegram_binding, whatsapp_inbound_actions  # noqa: E402


DEFAULT_SESSION_API_BASE_URL = "http://127.0.0.1:8098"
DEFAULT_SESSION_REF = "default-wa-web"
DEFAULT_STATE_FILE = "/tmp/ea_whatsapp_web_session_actions.json"
DEFAULT_AUDIOBOOK_PRINCIPAL_ID = "principal-default"
DEFAULT_ACTION_REPLY_HEYY_AI_KEY = "empathetic_slow_typing_old_lady"
DEFAULT_ACTION_REPLY_HEYY_AI_NAME = "Herta (Heyy Lady)"
DEFAULT_TELEGRAM_SUMMARY_HEYY_AI_KEYS = DEFAULT_ACTION_REPLY_HEYY_AI_KEY
DEFAULT_TELEGRAM_SUMMARY_SCOPE_LABEL = "Herta"
DEFAULT_ACTION_REPLY_PRE_REPLY_DELAY_MIN_SECONDS = 60
DEFAULT_ACTION_REPLY_PRE_REPLY_DELAY_MAX_SECONDS = 900
DEFAULT_ACTION_REPLY_TYPING_DELAY_MS = 6500
DEFAULT_ACTION_REPLY_TYPING_DELAY_MS_PER_CHARACTER = 4000
DEFAULT_ACTION_REPLY_QUIET_HOURS_START_HOUR = 21
DEFAULT_ACTION_REPLY_QUIET_HOURS_END_HOUR = 6
DEFAULT_STALE_CALLBACK_REPLY_MAX_AGE_SECONDS = 900
DEFAULT_CONVERSATION_FALLBACK_NOOP_COOLDOWN_SECONDS = 60
DEFAULT_CONVERSATION_FALLBACK_NOOP_MAX_COOLDOWN_SECONDS = 300
DEFAULT_FREEFORM_EXECUTIVE_ASSISTANT_REPLY = "I got that. I am checking it now."


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int = 0, maximum: int = 100) -> int:
    raw = str(os.getenv(name) or "").strip()
    try:
        value = int(raw) if raw else int(default)
    except Exception:
        value = int(default)
    return max(min(value, maximum), minimum)


def _env_float(name: str, default: float, *, minimum: float = 0.0, maximum: float = 10_000.0) -> float:
    raw = str(os.getenv(name) or "").strip()
    try:
        value = float(raw) if raw else float(default)
    except Exception:
        value = float(default)
    return max(min(value, maximum), minimum)
SUPPORTED_CALLBACK_PREFIXES = ("ab|", "ap|", "am|")
SUPPORTED_BUTTON_KINDS = {"audiobook_voice", "audiobook_playback", "audiobook_voice_management"}
SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._()\\[\\] -]+")
AUDIOBOOK_STATUS_DONE_STATUSES = {"audiobookshelf_imported", "failed_m4b_merge"}


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _bounded_int(value: object, default: int, *, minimum: int = 0, maximum: int = 86_400) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(default)
    return max(int(minimum), min(int(parsed), int(maximum)))


def _sha(value: object, length: int = 24) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:length]


def _split_paths(value: object) -> list[Path]:
    raw = str(value or "").strip()
    if not raw:
        return []
    paths: list[Path] = []
    for item in re.split(r"[:;,]", raw):
        normalized = str(item or "").strip()
        if normalized:
            paths.append(Path(normalized).expanduser())
    return paths


def _audiobook_job_roots() -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()
    configured = [
        *_split_paths(os.getenv("EA_AUDIOBOOK_JOB_DISCOVERY_ROOTS")),
        *_split_paths(os.getenv("EA_WHATSAPP_AUDIOBOOK_JOBS_ROOTS")),
        *_split_paths(os.getenv("EA_WHATSAPP_AUDIOBOOK_JOBS_ROOT")),
        *_split_paths(os.getenv("EA_AUDIOBOOK_JOBS_ROOT")),
        *_split_paths(os.getenv("EA_AUDIOBOOK_JOBS_HOST_ROOT")),
    ]
    if not configured:
        try:
            configured.extend(audiobook_epub_pipeline.audiobook_job_discovery_roots())
        except Exception:
            pass
    for root in configured:
        try:
            normalized = str(root.resolve())
        except Exception:
            normalized = str(root)
        if normalized in seen:
            continue
        seen.add(normalized)
        try:
            is_dir = root.is_dir()
        except OSError:
            continue
        if is_dir:
            roots.append(root)
    return roots


def _iter_audiobook_job_manifests(*, newest_first: bool = False) -> list[Path]:
    manifests: list[Path] = []
    seen: set[str] = set()
    for root in _audiobook_job_roots():
        for manifest_path in root.glob("*/job.json"):
            key = str(manifest_path.resolve()) if manifest_path.exists() else str(manifest_path)
            if key in seen:
                continue
            seen.add(key)
            manifests.append(manifest_path)

    def _mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    return sorted(manifests, key=lambda path: (_mtime(path), str(path)), reverse=bool(newest_first))


def _parse_message_datetime(value: object) -> datetime | None:
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000.0
        try:
            return datetime.fromtimestamp(timestamp, tz=UTC)
        except Exception:
            return None
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        return _parse_message_datetime(int(raw))
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC)
    except Exception:
        return None


def _message_datetime(message: dict[str, Any]) -> datetime | None:
    for key in ("message_timestamp", "timestamp", "created_at", "received_at", "time", "date"):
        parsed = _parse_message_datetime(message.get(key))
        if parsed:
            return parsed
    return None


def _stale_callback_reply_max_age_seconds(args: argparse.Namespace) -> int:
    value = getattr(args, "stale_callback_reply_max_age_seconds", None)
    if value is None:
        value = _env(
            "EA_WHATSAPP_WEB_ACTION_STALE_CALLBACK_REPLY_MAX_AGE_SECONDS",
            str(DEFAULT_STALE_CALLBACK_REPLY_MAX_AGE_SECONDS),
        )
    return _bounded_int(value, DEFAULT_STALE_CALLBACK_REPLY_MAX_AGE_SECONDS, minimum=0, maximum=86_400 * 14)


def _suppress_stale_callback_reply(
    *,
    args: argparse.Namespace,
    message: dict[str, Any],
    status: str,
    stale_notice_keys: set[str],
    chat_ref: str,
    sender_digits: str,
    kind: str,
) -> tuple[bool, str]:
    if status not in {"stale", "ignored"}:
        return False, ""
    max_age_seconds = _stale_callback_reply_max_age_seconds(args)
    message_time = _message_datetime(message)
    if max_age_seconds > 0 and message_time:
        age_seconds = (datetime.now(UTC) - message_time).total_seconds()
        if age_seconds > max_age_seconds:
            return True, "callback_reply_too_old"
    notice_key = f"{chat_ref or sender_digits}:{kind}:{status}"
    if notice_key in stale_notice_keys:
        return True, "duplicate_stale_callback_notice"
    stale_notice_keys.add(notice_key)
    return False, ""


def _action_id(*, session_ref: str, message_id: str, callback_data: str) -> str:
    return _sha(f"{session_ref}:{message_id}:{callback_data}")


def _headers(*, token: str, auth_header_name: str, auth_header_prefix: str) -> dict[str, str]:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        headers[auth_header_name or "Authorization"] = f"{auth_header_prefix}{token}"
    return headers


def _binary_headers(*, token: str, auth_header_name: str, auth_header_prefix: str) -> dict[str, str]:
    headers = {"Accept": "*/*"}
    if token:
        headers[auth_header_name or "Authorization"] = f"{auth_header_prefix}{token}"
    return headers


def _request_json(
    *,
    method: str,
    url: str,
    token: str = "",
    auth_header_name: str = "Authorization",
    auth_header_prefix: str = "Bearer ",
    body: dict[str, object] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers=_headers(token=token, auth_header_name=auth_header_name, auth_header_prefix=auth_header_prefix),
        method=method.upper(),
    )
    try:
        with urllib.request.urlopen(request, timeout=max(float(timeout), 0.1)) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"http_{exc.code}:{details[:160]}") from exc
    return json.loads(raw or "{}")


def _request_bytes(
    *,
    method: str,
    url: str,
    token: str = "",
    auth_header_name: str = "Authorization",
    auth_header_prefix: str = "Bearer ",
    timeout: float = 30.0,
) -> bytes:
    request = urllib.request.Request(
        url,
        headers=_binary_headers(token=token, auth_header_name=auth_header_name, auth_header_prefix=auth_header_prefix),
        method=method.upper(),
    )
    try:
        with urllib.request.urlopen(request, timeout=max(float(timeout), 0.1)) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"http_{exc.code}:{details[:160]}") from exc


def _load_state(path: Path) -> dict[str, Any]:
    if not str(path):
        return {"version": 1, "actions": {}}
    if not path.exists():
        return {"version": 1, "actions": {}}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "actions": {}}
    if not isinstance(loaded, dict):
        return {"version": 1, "actions": {}}
    actions = loaded.get("actions")
    if not isinstance(actions, dict):
        loaded["actions"] = {}
    loaded["version"] = 1
    return loaded


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def _message_callback_data(message: dict[str, Any]) -> str:
    direct = str(
        message.get("selected_button_id")
        or message.get("selectedButtonId")
        or message.get("selected_button_callback")
        or message.get("button_callback_data")
        or message.get("callback_data")
        or ""
    ).strip()
    if direct:
        return direct
    return _fallback_callback_from_selected_button_label(message)


def _selected_button_label(message: dict[str, Any]) -> str:
    return str(
        message.get("selected_button_label")
        or message.get("selected_option_label")
        or message.get("poll_selected_option_label")
        or ""
    ).strip()


def _fallback_callback_expiry_for_message(_message: dict[str, Any]) -> int:
    # Local reconstruction for already-received WhatsApp votes. The callback is not exposed to a user.
    return 4102444800


def _fallback_callback_from_selected_button_label(message: dict[str, Any]) -> str:
    label = _selected_button_label(message)
    normalized_label = _normalize_voice_command_text(label)
    if not normalized_label:
        return ""
    chat_ref = _message_chat_ref(message)
    sender_digits = _message_sender_digits(message) or _whatsapp_sender_ref_for_chat_ref(chat_ref)
    if not sender_digits:
        return ""
    job = _latest_waiting_whatsapp_voice_selection_job(sender_digits=sender_digits, chat_ref=chat_ref)
    if not job:
        return ""
    voice_selection = dict(dict(job.get("provider") or {}).get("voice_selection") or {})
    pending_batch = [row for row in list(voice_selection.get("pending_batch") or []) if isinstance(row, dict)]
    for row in pending_batch:
        if not isinstance(row, dict):
            continue
        token = str(row.get("callback_token") or "").strip()
        if not token:
            continue
        use_label, dismiss_label = _voice_action_button_labels(row)
        if normalized_label == _normalize_voice_command_text(use_label):
            return whatsapp_inbound_actions.encode_whatsapp_audiobook_voice_callback(
                action="u",
                token=token,
                sender_ref=sender_digits,
                expires_at=_fallback_callback_expiry_for_message(message),
            )
        if normalized_label == _normalize_voice_command_text(dismiss_label):
            return whatsapp_inbound_actions.encode_whatsapp_audiobook_voice_callback(
                action="d",
                token=token,
                sender_ref=sender_digits,
                expires_at=_fallback_callback_expiry_for_message(message),
            )
    if len(pending_batch) == 1:
        token = str(dict(pending_batch[0]).get("callback_token") or "").strip()
        if not token:
            return ""
        generic_use_labels = {"use this", "use", "use this voice"}
        generic_dismiss_labels = {"dismiss", "dismiss this", "dismiss voice", "dismiss this voice"}
        if normalized_label in generic_use_labels:
            return whatsapp_inbound_actions.encode_whatsapp_audiobook_voice_callback(
                action="u",
                token=token,
                sender_ref=sender_digits,
                expires_at=_fallback_callback_expiry_for_message(message),
            )
        if normalized_label in generic_dismiss_labels:
            return whatsapp_inbound_actions.encode_whatsapp_audiobook_voice_callback(
                action="d",
                token=token,
                sender_ref=sender_digits,
                expires_at=_fallback_callback_expiry_for_message(message),
            )
    return ""


def _message_sender_digits(message: dict[str, Any]) -> str:
    return "".join(ch for ch in str(message.get("sender_digits") or "") if ch.isdigit())


def _message_chat_ref(message: dict[str, Any]) -> str:
    return str(message.get("chat_ref") or message.get("chatRef") or "").strip()


def _is_supported_callback(message: dict[str, Any]) -> bool:
    callback_data = _message_callback_data(message)
    kind = str(message.get("selected_button_kind") or "").strip()
    if kind in SUPPORTED_BUTTON_KINDS:
        return bool(callback_data)
    return callback_data.startswith(SUPPORTED_CALLBACK_PREFIXES)


def _callback_token(callback_data: str) -> str:
    parts = str(callback_data or "").strip().split("|")
    if len(parts) < 3 or parts[0] not in {"ab", "ap", "am"}:
        return ""
    return str(parts[2] or "").strip()


def _whatsapp_audiobook_management_token(job: dict[str, object]) -> str:
    job_id = str(job.get("job_id") or Path(str(dict(job.get("storage") or {}).get("job_dir") or "")).name).strip()
    metadata = dict(job.get("metadata") or {})
    source_sha = str(metadata.get("source_sha256") or "").strip()
    return _sha(f"whatsapp-audiobook-management:{job_id}:{source_sha}", 14) if job_id else ""


def _whatsapp_audiobook_job_by_management_token(*, token: str, chat_ref: str = "", sender_digits: str = "") -> dict[str, object]:
    normalized = str(token or "").strip()
    if not normalized:
        return {}
    normalized_chat_ref = str(chat_ref or "").strip()
    normalized_sender = "".join(ch for ch in str(sender_digits or "") if ch.isdigit())
    for manifest_path in _iter_audiobook_job_manifests(newest_first=True):
        job = _read_job_manifest(manifest_path)
        if not job:
            continue
        if _whatsapp_audiobook_management_token(job) != normalized:
            continue
        if normalized_chat_ref and _whatsapp_chat_ref(job) != normalized_chat_ref:
            continue
        if normalized_sender and _whatsapp_sender_ref_digits(job) != normalized_sender:
            continue
        return job
    return {}


def _whatsapp_sender_ref_for_callback(*, callback_data: str, chat_ref: str = "") -> str:
    token = _callback_token(callback_data)
    if not token:
        return ""
    normalized_chat_ref = str(chat_ref or "").strip()
    callback_kind = str(callback_data or "").strip().split("|", 1)[0]
    for manifest_path in _iter_audiobook_job_manifests(newest_first=True):
        job = _read_job_manifest(manifest_path)
        if not job:
            continue
        if normalized_chat_ref and _whatsapp_chat_ref(job) != normalized_chat_ref:
            continue
        if callback_kind == "ab":
            voice_selection = dict(dict(job.get("provider") or {}).get("voice_selection") or {})
            candidate_tokens = {
                str(row.get("callback_token") or "").strip()
                for row in list(voice_selection.get("pending_batch") or [])
                if isinstance(row, dict)
            }
            selected_token = str(voice_selection.get("selected_callback_token") or "").strip()
            token_seen = token in candidate_tokens or token == selected_token
            if not token_seen:
                try:
                    private_payload = json.loads((manifest_path.parent / "voice_audition" / "private.json").read_text(encoding="utf-8"))
                    token_seen = token in dict(private_payload.get("candidates") or {})
                except Exception:
                    token_seen = False
            if not token_seen:
                continue
        elif callback_kind == "ap":
            public_share = _public_share(job)
            callback = dict(public_share.get("playback_acceptance_callback") or {})
            if token != str(callback.get("token") or "").strip():
                continue
        elif callback_kind == "am":
            if token != _whatsapp_audiobook_management_token(job):
                continue
        else:
            continue
        sender_ref = _whatsapp_sender_ref_digits(job)
        if sender_ref:
            return sender_ref
    return ""


def _iter_action_candidates(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        if str(message.get("direction") or "").strip() != "inbound":
            continue
        if bool(message.get("from_me")):
            continue
        if not bool(message.get("selected_button_id_present")) and not _message_callback_data(message):
            continue
        if not _is_supported_callback(message):
            continue
        if not _message_sender_digits(message) and not _message_chat_ref(message):
            continue
        candidates.append(message)
    return candidates


def _message_media_filename(message: dict[str, Any]) -> str:
    return str(message.get("media_filename") or message.get("filename") or "").strip()


def _message_media_mime_type(message: dict[str, Any]) -> str:
    return str(message.get("media_mime_type") or message.get("mimetype") or message.get("content_type") or "").strip()


def _message_caption(message: dict[str, Any]) -> str:
    return str(message.get("body_text") or message.get("caption") or "").strip()


def _is_audiobook_source_media_message(message: dict[str, Any]) -> bool:
    if str(message.get("direction") or "").strip() != "inbound":
        return False
    if bool(message.get("from_me")):
        return False
    if not _message_sender_digits(message):
        return False
    if not bool(message.get("media_present")):
        return False
    filename = _message_media_filename(message) or "whatsapp-book.epub"
    mime_type = _message_media_mime_type(message)
    return audiobook_epub_pipeline.is_audiobook_source_document(filename=filename, mime_type=mime_type)


def _iter_audiobook_source_candidates(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [message for message in messages if isinstance(message, dict) and _is_audiobook_source_media_message(message)]


def _is_epub_media_message(message: dict[str, Any]) -> bool:
    return _is_audiobook_source_media_message(message)


def _iter_epub_candidates(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _iter_audiobook_source_candidates(messages)


def _message_body_text(message: dict[str, Any]) -> str:
    return str(message.get("body_text") or message.get("text") or message.get("body") or "").strip()


def _message_has_summary_content(message: dict[str, Any]) -> bool:
    if _message_body_text(message):
        return True
    if bool(message.get("selected_button_id_present")) or _message_callback_data(message):
        return True
    if bool(message.get("media_present")):
        return True
    if _message_media_filename(message) or _message_media_mime_type(message):
        return True
    return False


def _message_timestamp(message: dict[str, Any]) -> str:
    return str(message.get("message_timestamp") or message.get("received_at") or message.get("timestamp") or "").strip()


def _message_summary_key(message: dict[str, Any]) -> str:
    message_id = str(message.get("id") or "").strip()
    if message_id:
        return _sha(message_id)
    material = {
        "chat_ref": _message_chat_ref(message),
        "sender_digits": _message_sender_digits(message),
        "timestamp": _message_timestamp(message),
        "body": _message_body_text(message),
    }
    return _sha(json.dumps(material, sort_keys=True))


def _csv_values(value: object) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _normalized_heyy_ai_keys(value: object) -> set[str]:
    return {item.lower() for item in _csv_values(value)}


def _message_heyy_ai_key(message: dict[str, Any]) -> str:
    return str(message.get("heyy_ai_key") or message.get("ai_key") or message.get("persona_key") or "").strip()


def _telegram_summary_allowed_heyy_ai_keys(args: argparse.Namespace) -> set[str]:
    configured = getattr(args, "telegram_summary_heyy_ai_keys", DEFAULT_TELEGRAM_SUMMARY_HEYY_AI_KEYS)
    return _normalized_heyy_ai_keys(configured) or _normalized_heyy_ai_keys(DEFAULT_TELEGRAM_SUMMARY_HEYY_AI_KEYS)


def _telegram_summary_scope_label(args: argparse.Namespace) -> str:
    return str(getattr(args, "telegram_summary_scope_label", "") or DEFAULT_TELEGRAM_SUMMARY_SCOPE_LABEL).strip()


def _iter_telegram_summary_candidates(
    messages: list[dict[str, Any]],
    *,
    allowed_heyy_ai_keys: set[str],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        heyy_ai_key = _message_heyy_ai_key(message).lower()
        if not heyy_ai_key or heyy_ai_key not in allowed_heyy_ai_keys:
            continue
        if str(message.get("direction") or "").strip() != "inbound":
            continue
        if bool(message.get("from_me")):
            continue
        if not _message_sender_digits(message) and not _message_chat_ref(message):
            continue
        if not _message_has_summary_content(message):
            continue
        candidates.append(message)
    return candidates


def _is_freeform_inbox_message(message: dict[str, Any]) -> bool:
    if str(message.get("direction") or "").strip() != "inbound":
        return False
    if bool(message.get("from_me")):
        return False
    if bool(message.get("selected_button_id_present")) or bool(_message_callback_data(message)):
        return False
    if _is_audiobook_source_media_message(message):
        return False
    if _is_empty_placeholder_message(message):
        return False
    if _is_audiobook_voice_text_message(message):
        return False
    if _is_audiobook_status_message(message):
        return False
    return _message_has_summary_content(message)


def _inbox_observability_summary(messages: list[dict[str, Any]]) -> dict[str, object]:
    inbound_messages = [
        message
        for message in messages
        if isinstance(message, dict)
        and str(message.get("direction") or "").strip() == "inbound"
        and not bool(message.get("from_me"))
    ]
    freeform_messages = [message for message in inbound_messages if _is_freeform_inbox_message(message)]
    freeform_by_heyy_ai_key: dict[str, int] = {}
    for message in freeform_messages:
        key = _message_heyy_ai_key(message).strip() or "unrouted"
        freeform_by_heyy_ai_key[key] = freeform_by_heyy_ai_key.get(key, 0) + 1
    return {
        "inbound_message_count": len(inbound_messages),
        "freeform_message_count": len(freeform_messages),
        "freeform_by_heyy_ai_key": freeform_by_heyy_ai_key,
    }


def _freeform_state(state: dict[str, Any]) -> dict[str, Any]:
    current = state.get("freeform")
    if isinstance(current, dict):
        return current
    state["freeform"] = {}
    return state["freeform"]


def _executive_assistant_freeform_enabled(args: argparse.Namespace) -> bool:
    value = getattr(args, "freeform_executive_assistant_enabled", None)
    if value is None:
        return _env_bool("EA_WHATSAPP_WEB_FREEFORM_EXECUTIVE_ASSISTANT_ENABLED", True)
    return bool(value)


def _executive_assistant_freeform_principal_id(args: argparse.Namespace) -> str:
    explicit = str(_env("EA_DEFAULT_PRINCIPAL_ID", "") or "").strip()
    if explicit:
        return explicit
    return str(getattr(args, "principal_id", "") or DEFAULT_AUDIOBOOK_PRINCIPAL_ID).strip()


def _executive_assistant_freeform_timeout_seconds() -> float:
    return _env_float(
        "EA_WHATSAPP_WEB_FREEFORM_EXECUTIVE_ASSISTANT_TIMEOUT_SECONDS",
        8.0,
        minimum=1.0,
        maximum=30.0,
    )


def _freeform_reply_args(args: argparse.Namespace, *, heyy_ai_key: str, heyy_ai_name: str) -> argparse.Namespace:
    reply_args = argparse.Namespace(**vars(args))
    reply_args.reply_heyy_ai_key = heyy_ai_key
    reply_args.reply_heyy_ai_name = heyy_ai_name
    reply_args.reply_use_sidecar_route_pacing = True
    reply_args.reply_pre_reply_delay_min_seconds = 0
    reply_args.reply_pre_reply_delay_max_seconds = 0
    reply_args.reply_quiet_hours_start_hour = 0
    reply_args.reply_quiet_hours_end_hour = 0
    reply_args.reply_typing_delay_ms = 0
    reply_args.reply_typing_delay_ms_per_character = 0
    reply_args.reply_typing_status_enabled = True
    return reply_args


def _executive_assistant_freeform_reply_text(
    *,
    args: argparse.Namespace,
    message: dict[str, Any],
) -> str:
    text = _message_body_text(message)
    if not text:
        return ""
    try:
        channels = importlib.import_module("app.api.routes.channels")
        container_module = importlib.import_module("app.container")
        container = container_module.build_container()
        principal_id = _executive_assistant_freeform_principal_id(args)
        general_reply = str(
            channels._telegram_general_reply_text(
                container=container,
                principal_id=principal_id,
                text=text,
            )
            or ""
        ).strip()
        if general_reply:
            return general_reply
        real_reply = str(
            channels._telegram_real_ea_reply_text(
                container=container,
                principal_id=principal_id,
                text=text,
                current_message_id=str(message.get("id") or "").strip(),
                timeout_seconds=_executive_assistant_freeform_timeout_seconds(),
            )
            or ""
        ).strip()
        if real_reply:
            return real_reply
    except Exception:
        pass
    return str(
        _env(
            "EA_WHATSAPP_WEB_FREEFORM_EXECUTIVE_ASSISTANT_FALLBACK_REPLY",
            DEFAULT_FREEFORM_EXECUTIVE_ASSISTANT_REPLY,
        )
        or DEFAULT_FREEFORM_EXECUTIVE_ASSISTANT_REPLY
    ).strip()


def _mask_sender_digits(value: object) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not digits:
        return "unbekannt"
    return f"...{digits[-4:]}" if len(digits) > 4 else f"...{digits}"


def _message_summary_sender_mask(message: dict[str, Any]) -> str:
    explicit = str(message.get("summary_sender_mask") or "").strip()
    if explicit:
        return explicit
    return _mask_sender_digits(_message_sender_digits(message) or _message_chat_ref(message))


def _message_summary_snippet(message: dict[str, Any], *, limit: int = 140) -> str:
    text = _message_body_text(message)
    if not text:
        return "Text nicht gespeichert"
    text = " ".join(text.split())
    if len(text) > limit:
        text = f"{text[: max(0, limit - 3)].rstrip()}..."
    return text


def _contact_summary_phrase(messages: list[dict[str, Any]]) -> str:
    senders: list[str] = []
    for message in messages:
        masked = _message_summary_sender_mask(message)
        if masked not in senders:
            senders.append(masked)
    if not senders:
        return "einem unbekannten Kontakt"
    if len(senders) == 1:
        return f"Kontakt {senders[0]}"
    if len(senders) == 2:
        return f"den Kontakten {senders[0]} und {senders[1]}"
    return f"{len(senders)} Kontakten"


def _telegram_summary_text(*, session_ref: str, messages: list[dict[str, Any]], scope_label: str = "") -> str:
    count = len(messages)
    word = "Nachricht" if count == 1 else "Nachrichten"
    contact_phrase = _contact_summary_phrase(messages)
    label = str(scope_label or "").strip()
    title = f"{label}-Zusammenfassung" if label else "WhatsApp-Zusammenfassung"
    chat_label = f"{label}-Chat" if label else "WhatsApp-Chat"
    snippets = [_message_summary_snippet(message) for message in messages]
    topic_text = "; ".join(f'"{snippet}"' for snippet in snippets[:5])
    latest = messages[-1] if messages else {}
    latest_timestamp = _message_timestamp(latest)
    latest_sender = _message_summary_sender_mask(latest)
    latest_when = f" um {latest_timestamp}" if latest_timestamp else ""
    latest_text = _message_summary_snippet(latest) if latest else "Text nicht gespeichert"
    verb = "ist" if count == 1 else "sind"
    return (
        f"{title} ({count} neue {word}): "
        f"Im {chat_label} {verb} {count} neue {word} von {contact_phrase} eingegangen. "
        f"Inhaltlich geht es zusammengefaßt um {topic_text}. "
        f"Zuletzt kam{latest_when} von {latest_sender}: \"{latest_text}\". "
        f"Session: {session_ref}."
    ).strip()


def _telegram_summary_chat_id(args: argparse.Namespace) -> str:
    explicit = str(getattr(args, "telegram_summary_chat_id", "") or "").strip()
    if explicit:
        return explicit
    try:
        return proactive_telegram_binding.resolve_proactive_telegram_chat_id(
            principal_id=str(getattr(args, "principal_id", "") or DEFAULT_AUDIOBOOK_PRINCIPAL_ID)
        )
    except Exception:
        return ""


def _send_telegram_message(*, bot_token: str, chat_id: str, text: str, timeout_seconds: float = 15.0) -> dict[str, object]:
    token = str(bot_token or "").strip()
    target = str(chat_id or "").strip()
    body_text = str(text or "").strip()
    if not token or not target or not body_text:
        return {"status": "skipped", "reason": "telegram_summary_not_configured"}
    payload = json.dumps({"chat_id": target, "text": body_text, "disable_web_page_preview": True}).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(float(timeout_seconds), 1.0)) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:160]
        return {"status": "failed", "reason": f"telegram_http_{exc.code}", "detail": detail}
    except Exception as exc:
        return {"status": "failed", "reason": type(exc).__name__}
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        parsed = {}
    result = dict(parsed.get("result") or {}) if isinstance(parsed, dict) else {}
    message_id = str(result.get("message_id") or "").strip()
    return {"status": "sent" if bool(parsed.get("ok")) else "failed", "message_id": message_id}


def _telegram_summary_state(state: dict[str, Any]) -> dict[str, Any]:
    summary = state.setdefault("telegram_summary", {})
    if not isinstance(summary, dict):
        summary = {}
        state["telegram_summary"] = summary
    seen = summary.get("seen_message_hashes")
    if not isinstance(seen, list):
        summary["seen_message_hashes"] = []
    pending = summary.get("pending_message_hashes")
    if not isinstance(pending, list):
        summary["pending_message_hashes"] = []
    records = summary.get("pending_message_records")
    if not isinstance(records, list):
        summary["pending_message_records"] = []
    return summary


def _telegram_summary_record(message_hash: str, message: dict[str, Any]) -> dict[str, str]:
    return {
        "message_hash": str(message_hash or "").strip(),
        "message_timestamp": _message_timestamp(message),
        "summary_text": _message_summary_snippet(message),
        "summary_sender_mask": _message_summary_sender_mask(message),
    }


def _message_from_telegram_summary_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "body_text": str(record.get("summary_text") or "").strip(),
        "message_timestamp": str(record.get("message_timestamp") or "").strip(),
        "summary_sender_mask": str(record.get("summary_sender_mask") or "").strip() or "unbekannt",
    }


def _telegram_summary_record_has_content(record: dict[str, Any]) -> bool:
    summary_text = str(record.get("summary_text") or "").strip()
    return bool(summary_text) and summary_text != "Text nicht gespeichert"


def _maybe_send_telegram_summary(
    *,
    args: argparse.Namespace,
    state: dict[str, Any],
    messages: list[dict[str, Any]],
    send_telegram_message: Callable[..., dict[str, object]] = _send_telegram_message,
) -> dict[str, object]:
    enabled = bool(getattr(args, "telegram_summary_enabled", False))
    every = max(1, min(int(getattr(args, "telegram_summary_every", 5) or 5), 100))
    if not enabled:
        return {"enabled": False, "status": "skipped", "reason": "disabled", "new_message_count": 0, "sent": 0}

    candidates = _iter_telegram_summary_candidates(
        messages,
        allowed_heyy_ai_keys=_telegram_summary_allowed_heyy_ai_keys(args),
    )
    summary = _telegram_summary_state(state)
    seen_hashes = [str(item) for item in list(summary.get("seen_message_hashes") or []) if str(item)]
    pending_hashes = [str(item) for item in list(summary.get("pending_message_hashes") or []) if str(item)]
    pending_records = [
        dict(item)
        for item in list(summary.get("pending_message_records") or [])
        if isinstance(item, dict) and str(item.get("message_hash") or "").strip()
    ]
    pending_records_by_hash = {str(item.get("message_hash") or "").strip(): item for item in pending_records}
    seen_set = set(seen_hashes)
    by_hash: dict[str, dict[str, Any]] = {}
    new_count = 0
    for message in candidates:
        message_hash = _message_summary_key(message)
        by_hash[message_hash] = message
        if message_hash in seen_set:
            continue
        seen_hashes.append(message_hash)
        pending_hashes.append(message_hash)
        pending_records_by_hash[message_hash] = _telegram_summary_record(message_hash, message)
        seen_set.add(message_hash)
        new_count += 1

    if pending_hashes:
        pending_hashes = [
            message_hash
            for message_hash in pending_hashes
            if message_hash in by_hash
            or (
                message_hash in pending_records_by_hash
                and _telegram_summary_record_has_content(pending_records_by_hash[message_hash])
            )
        ]
    pending_records = [pending_records_by_hash[message_hash] for message_hash in pending_hashes if message_hash in pending_records_by_hash]
    summary["seen_message_hashes"] = seen_hashes[-2000:]
    summary["pending_message_hashes"] = pending_hashes[-200:]
    summary["pending_message_records"] = pending_records[-200:]
    summary["total_seen_count"] = int(summary.get("total_seen_count") or 0) + new_count

    if bool(getattr(args, "dry_run", False)):
        return {
            "enabled": True,
            "status": "dry_run",
            "new_message_count": new_count,
            "pending_message_count": len(pending_hashes),
            "sent": 0,
        }
    if len(pending_hashes) < every:
        return {
            "enabled": True,
            "status": "waiting",
            "new_message_count": new_count,
            "pending_message_count": len(pending_hashes),
            "sent": 0,
        }

    batch_hashes = pending_hashes[:every]
    batch_messages = [
        by_hash[key]
        if key in by_hash
        else _message_from_telegram_summary_record(pending_records_by_hash[key])
        for key in batch_hashes
        if key in by_hash or key in pending_records_by_hash
    ]
    if len(batch_messages) < every:
        batch_messages = candidates[-every:]
    if len(batch_messages) < every:
        return {
            "enabled": True,
            "status": "waiting",
            "reason": "summary_messages_unavailable",
            "new_message_count": new_count,
            "pending_message_count": len(pending_hashes),
            "sent": 0,
        }

    bot_token = str(getattr(args, "telegram_summary_bot_token", "") or os.getenv("EA_TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = _telegram_summary_chat_id(args)
    if not bot_token or not chat_id:
        return {
            "enabled": True,
            "status": "skipped",
            "reason": "telegram_summary_not_configured",
            "new_message_count": new_count,
            "pending_message_count": len(pending_hashes),
            "sent": 0,
        }

    result = send_telegram_message(
        bot_token=bot_token,
        chat_id=chat_id,
        text=_telegram_summary_text(
            session_ref=str(getattr(args, "session_ref", "") or DEFAULT_SESSION_REF),
            messages=batch_messages,
            scope_label=_telegram_summary_scope_label(args),
        ),
        timeout_seconds=float(getattr(args, "telegram_summary_timeout_seconds", 15.0) or 15.0),
    )
    sent = 1 if str(result.get("status") or "").strip() == "sent" else 0
    if sent:
        pending_hashes = pending_hashes[every:]
        summary["pending_message_hashes"] = pending_hashes[-200:]
        summary["pending_message_records"] = [
            pending_records_by_hash[message_hash]
            for message_hash in pending_hashes[-200:]
            if message_hash in pending_records_by_hash
        ]
        summary["last_sent_at"] = _now_iso()
        summary["last_sent_message_count"] = every
        if str(result.get("message_id") or "").strip():
            summary["last_telegram_message_id_hash"] = _sha(result.get("message_id"))
    return {
        "enabled": True,
        "status": str(result.get("status") or "failed"),
        "reason": str(result.get("reason") or ""),
        "new_message_count": new_count,
        "pending_message_count": len(pending_hashes),
        "sent": sent,
    }


def _whatsapp_audiobook_status_intent(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().lower().split())
    if not normalized:
        return False
    sample_reference = any(
        marker in normalized
        for marker in (
            "voice sample",
            "voice samples",
            "3 samples",
            "three samples",
        )
    )
    audiobook_reference = any(
        marker in normalized
        for marker in (
            "audiobook",
            "audio book",
            "epub",
            "m4b",
        )
    )
    if not sample_reference and not audiobook_reference:
        return False
    return any(
        marker in normalized
        for marker in (
            "status",
            "ready",
            "configured",
            "preflight",
            "why",
            "voice sample",
            "voice samples",
            "3 samples",
            "three samples",
            "not get",
            "don't get",
            "dont get",
            "did not get",
            "didn't get",
            "resend",
            "send again",
        )
    )


def _whatsapp_voice_sample_resend_intent(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().lower().split())
    if not normalized:
        return False
    if not any(marker in normalized for marker in ("voice sample", "voice samples", "3 samples", "three samples")):
        return False
    return any(
        marker in normalized
        for marker in (
            "why",
            "not get",
            "don't get",
            "dont get",
            "did not get",
            "didn't get",
            "resend",
            "send again",
            "again",
        )
    )


def _normalize_voice_command_text(text: str) -> str:
    return re.sub(r"[^a-z0-9\u00c0-\u024f]+", " ", str(text or "").lower()).strip()


def _whatsapp_voice_text_action(text: str) -> str:
    normalized = " ".join(_normalize_voice_command_text(text).split())
    if not normalized:
        return ""
    dismiss_all_phrases = {
        "dismiss all",
        "dismiss all voices",
        "dismiss all voice samples",
        "dismiss all samples",
        "reject all",
        "reject all voices",
        "reject all voice samples",
        "next voices",
        "next voice samples",
        "new voices",
        "new voice samples",
    }
    if normalized in dismiss_all_phrases:
        return "dismiss_all"
    if normalized.startswith("dismiss all "):
        return "dismiss_all"
    if normalized.startswith("reject all "):
        return "dismiss_all"
    if normalized.startswith("next 3") or normalized.startswith("next three"):
        return "dismiss_all"
    if _whatsapp_voice_named_dismiss_choice(text):
        return "dismiss_named"
    if _whatsapp_voice_named_choice(text):
        return "use_named"
    return ""


def _whatsapp_voice_named_choice(text: str) -> str:
    normalized = " ".join(_normalize_voice_command_text(text).split())
    if not normalized:
        return ""
    prefixes = (
        "use voice",
        "use",
        "select voice",
        "select",
        "choose voice",
        "choose",
        "pick voice",
        "pick",
        "nimm stimme",
        "nimm",
        "verwende stimme",
        "verwende",
        "benutze stimme",
        "benutze",
        "waehle stimme",
        "waehle",
        "wähle stimme",
        "wähle",
    )
    for prefix in prefixes:
        prefix_normalized = " ".join(_normalize_voice_command_text(prefix).split())
        if normalized == prefix_normalized:
            return ""
        if normalized.startswith(f"{prefix_normalized} "):
            choice = normalized[len(prefix_normalized) :].strip()
            return choice[:80]
    return ""


def _whatsapp_voice_named_dismiss_choice(text: str) -> str:
    normalized = " ".join(_normalize_voice_command_text(text).split())
    if not normalized:
        return ""
    prefixes = (
        "dismiss voice",
        "dismiss",
        "reject voice",
        "reject",
        "skip voice",
        "skip",
        "weiter mit",
        "verwirf stimme",
        "verwirf",
    )
    for prefix in prefixes:
        prefix_normalized = " ".join(_normalize_voice_command_text(prefix).split())
        if normalized == prefix_normalized:
            return ""
        if normalized.startswith(f"{prefix_normalized} "):
            choice = normalized[len(prefix_normalized) :].strip()
            return choice[:80]
    return ""


def _pending_whatsapp_voice_label_choice(text: str, *, sender_digits: str = "", chat_ref: str = "") -> str:
    normalized = " ".join(_normalize_voice_command_text(text).split())
    if not normalized or len(normalized) > 80:
        return ""
    job = _latest_waiting_whatsapp_voice_selection_job(sender_digits=sender_digits, chat_ref=chat_ref)
    if not job:
        return ""
    voice_selection = dict(dict(job.get("provider") or {}).get("voice_selection") or {})
    pending_batch = [row for row in list(voice_selection.get("pending_batch") or []) if isinstance(row, dict)]
    if not pending_batch:
        return ""
    matches: list[tuple[int, str]] = []
    for row in pending_batch:
        label = str(row.get("label") or "").strip()
        if not label:
            continue
        score = _voice_choice_match_score(row, normalized)
        if score:
            matches.append((score, label))
    if not matches:
        return ""
    matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return matches[0][1]


def _is_audiobook_voice_text_message(message: dict[str, Any]) -> bool:
    if str(message.get("direction") or "").strip() != "inbound":
        return False
    if bool(message.get("from_me")):
        return False
    sender_digits = _message_sender_digits(message)
    chat_ref = _message_chat_ref(message)
    if not sender_digits and not chat_ref:
        return False
    if bool(message.get("media_present")):
        return False
    if bool(message.get("selected_button_id_present")) or _message_callback_data(message):
        return False
    text = _message_body_text(message)
    if _whatsapp_voice_text_action(text):
        return bool(
            _latest_waiting_whatsapp_voice_selection_job(
                sender_digits=sender_digits,
                chat_ref=chat_ref,
            )
        )
    return bool(
        _pending_whatsapp_voice_label_choice(
            text,
            sender_digits=sender_digits,
            chat_ref=chat_ref,
        )
    )


def _iter_audiobook_voice_text_candidates(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [message for message in messages if isinstance(message, dict) and _is_audiobook_voice_text_message(message)]


def _is_audiobook_status_message(message: dict[str, Any]) -> bool:
    if str(message.get("direction") or "").strip() != "inbound":
        return False
    if bool(message.get("from_me")):
        return False
    if not _message_sender_digits(message) and not _message_chat_ref(message):
        return False
    if bool(message.get("media_present")):
        return False
    if bool(message.get("selected_button_id_present")) or _message_callback_data(message):
        return False
    return _whatsapp_audiobook_status_intent(_message_body_text(message))


def _iter_audiobook_status_candidates(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [message for message in messages if isinstance(message, dict) and _is_audiobook_status_message(message)]


def _is_empty_placeholder_message(message: dict[str, Any]) -> bool:
    if str(message.get("direction") or "").strip() != "inbound":
        return False
    if bool(message.get("from_me")):
        return False
    if not _message_sender_digits(message) and not _message_chat_ref(message):
        return False
    if str(message.get("type") or "").strip() != "biz_content_placeholder":
        return False
    return not _message_has_summary_content(message)


def _iter_empty_placeholder_candidates(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [message for message in messages if isinstance(message, dict) and _is_empty_placeholder_message(message)]


def _actionable_candidate_counts(messages: list[dict[str, Any]]) -> dict[str, int]:
    audiobook_source_count = len(_iter_audiobook_source_candidates(messages))
    return {
        "button": len(_iter_action_candidates(messages)),
        "audiobook_source": audiobook_source_count,
        "epub": audiobook_source_count,
        "placeholder": len(_iter_empty_placeholder_candidates(messages)),
        "voice_text": len(_iter_audiobook_voice_text_candidates(messages)),
        "status": len(_iter_audiobook_status_candidates(messages)),
    }


def _flatten_conversation_messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for conversation in list(payload.get("conversations") or []):
        if not isinstance(conversation, dict):
            continue
        for message in list(conversation.get("messages") or []):
            if isinstance(message, dict):
                messages.append(message)
    return messages


def _merge_messages(primary: list[dict[str, Any]], fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for message in [*primary, *fallback]:
        if not isinstance(message, dict):
            continue
        message_id = str(message.get("id") or "").strip()
        key = message_id or f"anonymous:{len(merged)}"
        if key in seen:
            continue
        seen.add(key)
        merged.append(message)
    return merged


def _conversation_fallback_summary(
    *,
    attempted: bool = False,
    status: str = "skipped",
    reason: str = "",
    message_count: int = 0,
    candidate_counts: dict[str, int] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, object]:
    payload = payload if isinstance(payload, dict) else {}
    candidate_counts = candidate_counts if isinstance(candidate_counts, dict) else {}
    return {
        "attempted": attempted,
        "status": status,
        "reason": reason,
        "message_count": message_count,
        "button_candidate_count": int(candidate_counts.get("button") or 0),
        "audiobook_source_candidate_count": int(candidate_counts.get("audiobook_source") or candidate_counts.get("epub") or 0),
        "epub_candidate_count": int(candidate_counts.get("epub") or 0),
        "status_candidate_count": int(candidate_counts.get("status") or 0),
        "conversation_count": int(payload.get("conversation_count") or 0),
        "conversation_total": int(payload.get("conversation_total") or 0),
        "conversation_page_complete": bool(payload.get("conversation_page_complete")),
    }


def _conversation_fallback_noop_cooldown_seconds(args: argparse.Namespace) -> int:
    value = getattr(args, "conversation_fallback_noop_cooldown_seconds", None)
    if value is None:
        value = _env(
            "EA_WHATSAPP_WEB_ACTION_CONVERSATION_FALLBACK_NOOP_COOLDOWN_SECONDS",
            str(DEFAULT_CONVERSATION_FALLBACK_NOOP_COOLDOWN_SECONDS),
        )
    return _bounded_int(value, DEFAULT_CONVERSATION_FALLBACK_NOOP_COOLDOWN_SECONDS, minimum=0, maximum=3600)


def _conversation_fallback_noop_max_cooldown_seconds(args: argparse.Namespace) -> int:
    value = getattr(args, "conversation_fallback_noop_max_cooldown_seconds", None)
    if value is None:
        value = _env(
            "EA_WHATSAPP_WEB_ACTION_CONVERSATION_FALLBACK_NOOP_MAX_COOLDOWN_SECONDS",
            str(DEFAULT_CONVERSATION_FALLBACK_NOOP_MAX_COOLDOWN_SECONDS),
        )
    base = _conversation_fallback_noop_cooldown_seconds(args)
    return max(base, _bounded_int(value, DEFAULT_CONVERSATION_FALLBACK_NOOP_MAX_COOLDOWN_SECONDS, minimum=base, maximum=3600))


def _conversation_fallback_effective_noop_cooldown_seconds(
    *,
    args: argparse.Namespace,
    fallback_state: dict[str, Any],
) -> int:
    base = _conversation_fallback_noop_cooldown_seconds(args)
    if base <= 0:
        return 0
    max_cooldown = _conversation_fallback_noop_max_cooldown_seconds(args)
    consecutive_noop_count = _bounded_int(
        fallback_state.get("consecutive_noop_count"),
        1 if str(fallback_state.get("last_noop_at") or "").strip() else 0,
        minimum=0,
        maximum=16,
    )
    if consecutive_noop_count <= 1:
        return min(base, max_cooldown)
    multiplier = 2 ** min(consecutive_noop_count - 1, 6)
    return min(base * multiplier, max_cooldown)


def _conversation_fallback_cooldown_summary(
    *,
    args: argparse.Namespace,
    state: dict[str, Any],
) -> dict[str, object] | None:
    fallback_state = state.get("conversation_fallback")
    if not isinstance(fallback_state, dict):
        return None
    cooldown_seconds = _conversation_fallback_effective_noop_cooldown_seconds(
        args=args,
        fallback_state=fallback_state,
    )
    if cooldown_seconds <= 0:
        return None
    last_noop_at = _parse_message_datetime(fallback_state.get("last_noop_at"))
    if not last_noop_at:
        return None
    age_seconds = max(0, int((datetime.now(UTC) - last_noop_at).total_seconds()))
    if age_seconds >= cooldown_seconds:
        return None
    summary = _conversation_fallback_summary(
        attempted=False,
        status="cooldown",
        reason="recent_noop",
    )
    summary["cooldown_seconds"] = cooldown_seconds
    summary["cooldown_remaining_seconds"] = cooldown_seconds - age_seconds
    summary["last_noop_at"] = str(fallback_state.get("last_noop_at") or "").strip()
    summary["consecutive_noop_count"] = _bounded_int(fallback_state.get("consecutive_noop_count"), 1, minimum=1, maximum=16)
    return summary


def _should_bypass_conversation_fallback_cooldown(
    *,
    args: argparse.Namespace,
    state: dict[str, Any],
    messages_payload: dict[str, Any],
    messages: list[dict[str, Any]],
) -> bool:
    fallback_state = state.get("conversation_fallback")
    if not isinstance(fallback_state, dict):
        return False
    direct_inbox_count = _bounded_int(
        messages_payload.get("inbox_count"),
        len(messages),
        minimum=0,
        maximum=100_000,
    )
    take = max(1, min(int(getattr(args, "take", 100) or 100), 1000))
    previous_fallback_count = _bounded_int(
        fallback_state.get("last_message_count"),
        0,
        minimum=0,
        maximum=100_000,
    )
    if direct_inbox_count >= take:
        return False
    return previous_fallback_count > direct_inbox_count


def _record_conversation_fallback_run(
    *,
    args: argparse.Namespace,
    state: dict[str, Any],
    conversation_fallback: dict[str, object],
    processed: int,
    epub_processed: int,
    voice_text_processed: int,
    status_processed: int,
    reply_sent: int,
    share_link_sent: int,
    voice_sample_sent: int,
) -> None:
    if bool(getattr(args, "dry_run", False)):
        return
    fallback_state = state.get("conversation_fallback")
    if not isinstance(fallback_state, dict):
        fallback_state = {}
    attempted = bool(conversation_fallback.get("attempted"))
    if attempted:
        fallback_state["last_attempted_at"] = _now_iso()
        fallback_state["last_status"] = str(conversation_fallback.get("status") or "")
        fallback_state["last_message_count"] = int(conversation_fallback.get("message_count") or 0)
        fallback_state["last_meaningful_message_count"] = int(conversation_fallback.get("meaningful_message_count") or 0)
    did_work = any(
        int(value or 0) > 0
        for value in (
            processed,
            epub_processed,
            voice_text_processed,
            status_processed,
            reply_sent,
            share_link_sent,
            voice_sample_sent,
        )
    )
    meaningful_message_count = int(conversation_fallback.get("meaningful_message_count") or 0)
    if attempted and str(conversation_fallback.get("status") or "") == "pass" and not did_work and meaningful_message_count > 0:
        fallback_state["last_noop_at"] = _now_iso()
        fallback_state["consecutive_noop_count"] = _bounded_int(
            fallback_state.get("consecutive_noop_count"),
            0,
            minimum=0,
            maximum=16,
        ) + 1
    elif attempted and meaningful_message_count <= 0:
        fallback_state.pop("last_noop_at", None)
        fallback_state.pop("consecutive_noop_count", None)
    elif did_work:
        fallback_state.pop("last_noop_at", None)
        fallback_state.pop("consecutive_noop_count", None)
    state["conversation_fallback"] = fallback_state


def _load_conversation_fallback_messages(
    *,
    request_json: Callable[..., dict[str, Any]],
    args: argparse.Namespace,
    base_url: str,
    session_ref: str,
) -> tuple[list[dict[str, Any]], dict[str, object]]:
    take = max(1, min(int(getattr(args, "conversation_fallback_take", 25) or 25), 100))
    message_limit = max(1, min(int(getattr(args, "conversation_fallback_message_limit", 25) or 25), 100))
    timeout_ms = max(1000, min(int(getattr(args, "conversation_fallback_fetch_timeout_ms", 15000) or 15000), 120000))
    concurrency = max(1, min(int(getattr(args, "conversation_fallback_fetch_concurrency", 6) or 6), 20))
    url = (
        f"{base_url}/sessions/{urllib.parse.quote(session_ref)}/conversations"
        f"?take={take}&messages={message_limit}&fetch_timeout_ms={timeout_ms}&fetch_concurrency={concurrency}"
    )
    try:
        payload = request_json(
            method="GET",
            url=url,
            token=str(args.session_api_token or ""),
            auth_header_name=str(args.auth_header_name or "Authorization"),
            auth_header_prefix=str(args.auth_header_prefix if args.auth_header_prefix is not None else "Bearer "),
            timeout=float(args.timeout_seconds),
        )
    except Exception as exc:
        return [], _conversation_fallback_summary(attempted=True, status="failed", reason=type(exc).__name__)
    messages = _flatten_conversation_messages(payload)
    candidate_counts = _actionable_candidate_counts(messages)
    summary = _conversation_fallback_summary(
        attempted=True,
        status="pass",
        message_count=len(messages),
        candidate_counts=candidate_counts,
        payload=payload,
    )
    summary["meaningful_message_count"] = sum(
        1 for message in messages if isinstance(message, dict) and _message_has_summary_content(message)
    )
    return messages, summary


def _safe_filename(value: str, *, fallback: str = "whatsapp-book", suffix: str = "") -> str:
    normalized = " ".join(str(value or "").replace("/", " ").replace("\\", " ").split()).strip()
    normalized = SAFE_FILENAME_RE.sub("", normalized).strip(" .")
    if not normalized:
        normalized = fallback
    if len(normalized) > 96:
        normalized = normalized[:96].rstrip(" .")
    if suffix and not normalized.lower().endswith(suffix.lower()):
        normalized = f"{normalized}{suffix}"
    return normalized


def _job_dir_from_job(job: dict[str, object]) -> Path | None:
    raw = str(dict(job.get("storage") or {}).get("job_dir") or "").strip()
    return Path(raw) if raw else None


def _load_job_from_disk(job: dict[str, object]) -> dict[str, object]:
    job_dir = _job_dir_from_job(job)
    if job_dir is not None and (job_dir / "job.json").is_file():
        try:
            loaded = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                return loaded
        except Exception:
            return dict(job)
    return dict(job)


def _write_job_to_disk(job: dict[str, object]) -> dict[str, object]:
    job_dir = _job_dir_from_job(job)
    if job_dir is None:
        return job
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "job.json").write_text(json.dumps(job, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        audiobook_epub_pipeline._write_current_job_receipt_best_effort(job_dir)  # type: ignore[attr-defined]
    except Exception:
        pass
    return job


def _whatsapp_epub_reply_text(job: dict[str, object]) -> str:
    text = audiobook_epub_pipeline.telegram_epub_reply_text(job)
    text = text.replace("Telegram", "WhatsApp").replace("telegram", "WhatsApp")
    text = text.replace(
        "Choose 'Use this' under the one that fits; dismiss any sample to replace it.",
        "Tap Use under the voice that fits, or Dismiss to replace that sample. If WhatsApp hides the buttons, reply with the voice name or 'dismiss all'.",
    )
    text = text.replace(
        "Use the latest voice sample buttons.",
        "Use the latest voice sample buttons, or reply with the voice name or 'dismiss all'.",
    )
    return text


def _voice_sample_delivery_summary(sample_receipts: list[dict[str, object]]) -> dict[str, object]:
    receipts = [dict(item) for item in list(sample_receipts or []) if isinstance(item, dict)]
    sent_count = sum(1 for item in receipts if str(item.get("status") or "").strip().lower() == "sent")
    failed_count = sum(1 for item in receipts if str(item.get("status") or "").strip().lower() == "failed")
    skipped_count = sum(1 for item in receipts if str(item.get("status") or "").strip().lower() == "skipped")
    reasons: list[str] = []
    for item in receipts:
        reason = str(item.get("reason") or "").strip()
        if reason and reason not in reasons:
            reasons.append(reason)
    expected_count = len(receipts)
    status = (
        "sent"
        if expected_count and sent_count >= expected_count
        else "partial"
        if sent_count
        else "failed"
        if expected_count
        else "not_attempted"
    )
    return {
        "status": status,
        "expected_count": expected_count,
        "attempted_count": len(receipts),
        "sent_count": sent_count,
        "failed_count": failed_count,
        "skipped_count": skipped_count,
        "reason": reasons[0] if reasons else "",
        "reasons": reasons[:5],
        "token_sha256": [
            hashlib.sha256(str(item.get("token") or "").encode("utf-8")).hexdigest()
            for item in receipts
            if str(item.get("token") or "").strip()
        ],
        "updated_at": _now_iso(),
    }


def _record_whatsapp_voice_sample_delivery(
    *,
    job: dict[str, object],
    sample_receipts: list[dict[str, object]],
) -> dict[str, object]:
    current = _load_job_from_disk(job)
    whatsapp = dict(current.get("whatsapp") or {})
    whatsapp["voice_sample_delivery"] = _voice_sample_delivery_summary(sample_receipts)
    current["whatsapp"] = whatsapp
    current["updated_at"] = _now_iso()
    return _write_job_to_disk(current)


def _record_whatsapp_job_metadata(*, job: dict[str, object], metadata: dict[str, object]) -> dict[str, object]:
    current = _load_job_from_disk(job)
    whatsapp = dict(current.get("whatsapp") or {})
    whatsapp.update(metadata)
    current["whatsapp"] = whatsapp
    current["updated_at"] = _now_iso()
    return _write_job_to_disk(current)


def _reply_pacing_payload(args: argparse.Namespace) -> tuple[dict[str, object], float]:
    if bool(getattr(args, "reply_use_sidecar_route_pacing", False)):
        return {}, max(float(getattr(args, "timeout_seconds", 30.0) or 30.0), 0.1)
    min_seconds = _bounded_int(
        getattr(args, "reply_pre_reply_delay_min_seconds", DEFAULT_ACTION_REPLY_PRE_REPLY_DELAY_MIN_SECONDS),
        DEFAULT_ACTION_REPLY_PRE_REPLY_DELAY_MIN_SECONDS,
    )
    max_seconds = _bounded_int(
        getattr(args, "reply_pre_reply_delay_max_seconds", DEFAULT_ACTION_REPLY_PRE_REPLY_DELAY_MAX_SECONDS),
        DEFAULT_ACTION_REPLY_PRE_REPLY_DELAY_MAX_SECONDS,
    )
    if max_seconds < min_seconds:
        max_seconds = min_seconds
    typing_delay_ms = _bounded_int(
        getattr(args, "reply_typing_delay_ms", DEFAULT_ACTION_REPLY_TYPING_DELAY_MS),
        DEFAULT_ACTION_REPLY_TYPING_DELAY_MS,
        maximum=3_600_000,
    )
    typing_delay_ms_per_character = _bounded_int(
        getattr(args, "reply_typing_delay_ms_per_character", DEFAULT_ACTION_REPLY_TYPING_DELAY_MS_PER_CHARACTER),
        DEFAULT_ACTION_REPLY_TYPING_DELAY_MS_PER_CHARACTER,
        maximum=3_600_000,
    )
    payload = {
        "heyy_ai_key": str(
            getattr(args, "reply_heyy_ai_key", DEFAULT_ACTION_REPLY_HEYY_AI_KEY)
            or DEFAULT_ACTION_REPLY_HEYY_AI_KEY
        ).strip(),
        "heyy_ai_name": str(
            getattr(args, "reply_heyy_ai_name", DEFAULT_ACTION_REPLY_HEYY_AI_NAME)
            or DEFAULT_ACTION_REPLY_HEYY_AI_NAME
        ).strip(),
        "pre_reply_delay_max_seconds": max_seconds,
        "pre_reply_delay_min_seconds": min_seconds,
        "quiet_hours_end_hour": _bounded_int(
            getattr(args, "reply_quiet_hours_end_hour", DEFAULT_ACTION_REPLY_QUIET_HOURS_END_HOUR),
            DEFAULT_ACTION_REPLY_QUIET_HOURS_END_HOUR,
            maximum=23,
        ),
        "quiet_hours_start_hour": _bounded_int(
            getattr(args, "reply_quiet_hours_start_hour", DEFAULT_ACTION_REPLY_QUIET_HOURS_START_HOUR),
            DEFAULT_ACTION_REPLY_QUIET_HOURS_START_HOUR,
            maximum=23,
        ),
        "typing_delay_ms": typing_delay_ms,
        "typing_delay_ms_per_character": typing_delay_ms_per_character,
        "typing_status_enabled": bool(getattr(args, "reply_typing_status_enabled", True)),
    }
    pacing_timeout_seconds = max_seconds + (typing_delay_ms / 1000.0) + 15.0
    return payload, max(float(getattr(args, "timeout_seconds", 30.0) or 30.0), pacing_timeout_seconds)


def _send_reply(
    *,
    request_json: Callable[..., dict[str, Any]],
    args: argparse.Namespace,
    recipient_digits: str,
    text: str,
    buttons: list[list[tuple[str, str]]] | None = None,
    chat_ref: str = "",
) -> dict[str, Any]:
    base_url = str(args.session_api_base_url or DEFAULT_SESSION_API_BASE_URL).strip().rstrip("/")
    session_ref = str(args.session_ref or DEFAULT_SESSION_REF).strip()
    url = f"{base_url}/sessions/{urllib.parse.quote(session_ref)}/messages"
    pacing_payload, request_timeout = _reply_pacing_payload(args)
    payload = {
        "to": recipient_digits,
        "text": text,
        **pacing_payload,
    }
    if buttons:
        payload["buttons"] = buttons
    if str(chat_ref or "").strip():
        payload["chat_ref"] = str(chat_ref or "").strip()
    return request_json(
        method="POST",
        url=url,
        token=str(args.session_api_token or ""),
        auth_header_name=str(args.auth_header_name or "Authorization"),
        auth_header_prefix=str(args.auth_header_prefix if args.auth_header_prefix is not None else "Bearer "),
        body=payload,
        timeout=request_timeout,
    )


def _send_media(
    *,
    request_json: Callable[..., dict[str, Any]],
    args: argparse.Namespace,
    recipient_digits: str,
    media_path: Path,
    text: str = "",
    chat_ref: str = "",
) -> dict[str, Any]:
    base_url = str(args.session_api_base_url or DEFAULT_SESSION_API_BASE_URL).strip().rstrip("/")
    session_ref = str(args.session_ref or DEFAULT_SESSION_REF).strip()
    url = f"{base_url}/sessions/{urllib.parse.quote(session_ref)}/messages"
    mime_type = mimetypes.guess_type(media_path.name)[0] or "application/octet-stream"
    pacing_payload, request_timeout = _reply_pacing_payload(args)
    payload = {
        "to": recipient_digits,
        "text": str(text or "").strip(),
        "media_base64": base64.b64encode(media_path.read_bytes()).decode("ascii"),
        "media_filename": media_path.name,
        "media_mimetype": mime_type,
        **pacing_payload,
    }
    if str(chat_ref or "").strip():
        payload["chat_ref"] = str(chat_ref or "").strip()
    return request_json(
        method="POST",
        url=url,
        token=str(args.session_api_token or ""),
        auth_header_name=str(args.auth_header_name or "Authorization"),
        auth_header_prefix=str(args.auth_header_prefix if args.auth_header_prefix is not None else "Bearer "),
        body=payload,
        timeout=request_timeout,
    )


def _sample_caption(sample: dict[str, object]) -> str:
    caption = str(sample.get("label") or "Voice sample").strip()
    matched_tags = [str(item).strip() for item in list(sample.get("matched_tags") or []) if str(item).strip()]
    if matched_tags:
        caption = f"{caption} · {', '.join(matched_tags[:4])}"
    return caption


def _voice_action_button_labels(sample: dict[str, object]) -> tuple[str, str]:
    label = " ".join(str(sample.get("label") or "this voice").strip().split())
    if len(label) > 32:
        label = label[:32].rstrip()
    return f"Use {label}", f"Dismiss {label}"


def _language_prefix(value: object) -> str:
    normalized = str(value or "").strip().lower().replace("_", "-")
    return normalized.split("-", 1)[0] if normalized else ""


def _candidate_matches_language(candidate: dict[str, object], language: str) -> bool:
    target = _language_prefix(language)
    if not target:
        return False
    values = [candidate.get("language")]
    values.extend(list(candidate.get("supported_languages") or []))
    return any(_language_prefix(item) == target for item in values if str(item or "").strip())


def _book_language(job: dict[str, object]) -> str:
    metadata = dict(job.get("metadata") or {})
    if str(metadata.get("language") or "").strip():
        return str(metadata.get("language") or "").strip()
    voice_selection = dict(dict(job.get("provider") or {}).get("voice_selection") or {})
    profile = dict(voice_selection.get("book_profile") or {})
    return str(profile.get("language") or "").strip()


def _ffprobe_audio_stream(path: Path) -> dict[str, object]:
    ffprobe = shutil.which(str(os.environ.get("EA_FFPROBE_BIN") or "ffprobe").strip() or "ffprobe")
    if not ffprobe:
        raise RuntimeError("whatsapp_sample_ffprobe_missing")
    completed = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=_env_int("EA_WHATSAPP_SAMPLE_FFPROBE_TIMEOUT_SECONDS", 20, minimum=1, maximum=120),
    )
    if completed.returncode != 0:
        raise RuntimeError("whatsapp_sample_ffprobe_failed")
    try:
        payload = json.loads(completed.stdout or "{}")
    except Exception as exc:
        raise RuntimeError("whatsapp_sample_ffprobe_invalid_json") from exc
    streams = [dict(item) for item in list(payload.get("streams") or []) if isinstance(item, dict)]
    audio_stream = next((item for item in streams if str(item.get("codec_type") or "") == "audio"), None)
    if not audio_stream:
        raise RuntimeError("whatsapp_sample_audio_stream_missing")
    return {"stream": audio_stream, "format": dict(payload.get("format") or {})}


def _validate_whatsapp_voice_sample_media(path: Path) -> None:
    if not _env_bool("EA_WHATSAPP_VOICE_SAMPLE_TRANSCODE_QUALITY_GATE_ENABLED", True):
        return
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError("whatsapp_sample_media_missing")
    probed = _ffprobe_audio_stream(path)
    stream = dict(probed.get("stream") or {})
    fmt = dict(probed.get("format") or {})
    codec = str(stream.get("codec_name") or "").strip().lower()
    try:
        sample_rate = int(stream.get("sample_rate") or 0)
    except Exception:
        sample_rate = 0
    try:
        channels = int(stream.get("channels") or 0)
    except Exception:
        channels = 0
    try:
        duration = float(fmt.get("duration") or stream.get("duration") or 0.0)
    except Exception:
        duration = 0.0
    min_duration = _env_float("EA_WHATSAPP_VOICE_SAMPLE_MIN_DURATION_SECONDS", 0.08, minimum=0.01, maximum=60.0)
    max_duration = _env_float("EA_WHATSAPP_VOICE_SAMPLE_MAX_DURATION_SECONDS", 180.0, minimum=min_duration, maximum=3600.0)
    if codec != "mp3":
        raise RuntimeError("whatsapp_sample_media_codec_invalid")
    if sample_rate != 44100:
        raise RuntimeError("whatsapp_sample_media_sample_rate_invalid")
    if channels != 1:
        raise RuntimeError("whatsapp_sample_media_channel_count_invalid")
    if duration < min_duration:
        raise RuntimeError("whatsapp_sample_media_too_short")
    if duration > max_duration:
        raise RuntimeError("whatsapp_sample_media_too_long")


def _whatsapp_voice_sample_media_path(source: Path) -> Path:
    if source.suffix.lower() == ".mp3":
        _validate_whatsapp_voice_sample_media(source)
        return source
    ffmpeg = shutil.which(str(os.environ.get("EA_FFMPEG_BIN") or "ffmpeg").strip() or "ffmpeg")
    if not ffmpeg:
        raise RuntimeError("whatsapp_sample_transcode_ffmpeg_missing")
    target_dir = source.parent.parent / "whatsapp_media"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{source.stem}.mp3"
    try:
        if target.is_file() and target.stat().st_mtime >= source.stat().st_mtime:
            return target
    except OSError:
        pass
    completed = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "44100",
            "-b:a",
            "96k",
            str(target),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode != 0 or not target.is_file():
        raise RuntimeError("whatsapp_sample_transcode_failed")
    _validate_whatsapp_voice_sample_media(target)
    return target


def _send_whatsapp_voice_samples(
    *,
    request_json: Callable[..., dict[str, Any]],
    args: argparse.Namespace,
    recipient_digits: str,
    job: dict[str, object],
) -> list[dict[str, object]]:
    receipts: list[dict[str, object]] = []
    chat_ref = _whatsapp_chat_ref(job)
    for sample in audiobook_epub_pipeline.audiobook_voice_audition_sample_messages(job):
        token = str(sample.get("token") or "").strip()
        sample_path = Path(str(sample.get("audio_path") or ""))
        if not token or not sample_path.is_file():
            receipts.append({"token": token, "status": "failed", "reason": "sample_audio_missing"})
            continue
        quality_gate = audiobook_epub_pipeline.audiobook_voice_sample_audio_quality_gate(sample_path)
        if not bool(quality_gate.get("ok")):
            receipts.append(
                {
                    "token": token,
                    "status": "failed",
                    "reason": str(quality_gate.get("reason") or "voice_sample_audio_quality_failed"),
                    "audio_quality_status": str(quality_gate.get("status") or "").strip(),
                    "audio_quality_issues": list(dict(quality_gate.get("audio_quality") or {}).get("issues") or [])[:5],
                }
            )
            continue
        try:
            media_path = _whatsapp_voice_sample_media_path(sample_path)
        except Exception as exc:
            receipts.append({"token": token, "status": "failed", "reason": str(exc) or type(exc).__name__})
            continue
        use_callback = whatsapp_inbound_actions.encode_whatsapp_audiobook_voice_callback(
            action="u",
            token=token,
            sender_ref=recipient_digits,
        )
        dismiss_callback = whatsapp_inbound_actions.encode_whatsapp_audiobook_voice_callback(
            action="d",
            token=token,
            sender_ref=recipient_digits,
        )
        if not use_callback or not dismiss_callback:
            receipts.append({"token": token, "status": "failed", "reason": "callback_encoding_failed"})
            continue
        try:
            use_label, dismiss_label = _voice_action_button_labels(sample)
            media_result = _send_media(
                request_json=request_json,
                args=args,
                recipient_digits=recipient_digits,
                media_path=media_path,
                text=_sample_caption(sample),
                chat_ref=chat_ref,
            )
            button_result = _send_reply(
                request_json=request_json,
                args=args,
                recipient_digits=recipient_digits,
                text=f"Choose this voice sample. If the buttons do not work, reply 'use {str(sample.get('label') or 'this voice').strip()}' or 'dismiss all'.",
                buttons=[[(use_label, use_callback), (dismiss_label, dismiss_callback)]],
                chat_ref=chat_ref,
            )
        except Exception as exc:
            receipts.append({"token": token, "status": "failed", "reason": type(exc).__name__})
            continue
        sent = bool(media_result.get("ok", True)) and bool(button_result.get("ok", True))
        receipts.append(
            {
                "token": token,
                "status": "sent" if sent else "skipped",
                "reason": "" if sent else "whatsapp_voice_sample_send_skipped",
                "transport": "whatsapp_web_session",
                "media_message_id_sha256": _sha(media_result.get("message_id") or media_result.get("id") or ""),
                "button_message_id_sha256": _sha(button_result.get("message_id") or button_result.get("id") or ""),
                "button_count": int(button_result.get("button_count") or 0),
                "buttons_fallback": bool(button_result.get("buttons_fallback")),
                "control_kind": str(button_result.get("control_kind") or "").strip(),
            }
        )
    return receipts


def _send_whatsapp_voice_management_controls(
    *,
    request_json: Callable[..., dict[str, Any]],
    args: argparse.Namespace,
    recipient_digits: str,
    job: dict[str, object],
    text: str = "",
) -> dict[str, Any]:
    token = _whatsapp_audiobook_management_token(job)
    if not token:
        return {"ok": False, "reason": "management_token_missing"}
    restore_callback = whatsapp_inbound_actions.encode_whatsapp_audiobook_management_callback(
        action="r",
        token=token,
        sender_ref=recipient_digits,
    )
    next_callback = whatsapp_inbound_actions.encode_whatsapp_audiobook_management_callback(
        action="n",
        token=token,
        sender_ref=recipient_digits,
    )
    best_callback = whatsapp_inbound_actions.encode_whatsapp_audiobook_management_callback(
        action="b",
        token=token,
        sender_ref=recipient_digits,
    )
    buttons: list[tuple[str, str]] = []
    if restore_callback:
        language = _language_prefix(_book_language(job)).upper() or "book"
        buttons.append((f"Restore {language} voices", restore_callback))
    if next_callback:
        buttons.append(("Search more", next_callback))
    if best_callback:
        buttons.append(("Use best current", best_callback))
    if not buttons:
        return {"ok": False, "reason": "management_callback_encoding_failed"}
    voice_selection = dict(dict(job.get("provider") or {}).get("voice_selection") or {})
    reason = str(voice_selection.get("reason") or voice_selection.get("underfilled_reason") or "").strip()
    default_text = (
        "The current audiobook voice batch needs a decision."
        if not reason
        else "The current audiobook voice batch is outside the best language match. Choose how to continue."
    )
    return _send_reply(
        request_json=request_json,
        args=args,
        recipient_digits=recipient_digits,
        text=str(text or default_text).strip(),
        buttons=[buttons],
        chat_ref=_whatsapp_chat_ref(job),
    )


def _voice_selection_needs_management_controls(job: dict[str, object]) -> bool:
    voice_selection = dict(dict(job.get("provider") or {}).get("voice_selection") or {})
    reason = str(voice_selection.get("reason") or voice_selection.get("underfilled_reason") or "").strip()
    if bool(voice_selection.get("language_relaxed_after_dismissals")):
        return True
    if str(voice_selection.get("status") or "").strip() in {"exhausted", "blocked"}:
        return True
    return reason in {
        "voice_catalog_language_relaxed_after_dismissals",
        "voice_catalog_underfilled_after_dismissals",
        "voice_catalog_exhausted",
        "voice_sample_generation_failed_after_dismissal",
    }


def _maybe_send_whatsapp_voice_management_controls(
    *,
    request_json: Callable[..., dict[str, Any]],
    args: argparse.Namespace,
    recipient_digits: str,
    job: dict[str, object],
) -> dict[str, Any]:
    if not _voice_selection_needs_management_controls(job):
        return {"ok": False, "status": "not_needed"}
    return _send_whatsapp_voice_management_controls(
        request_json=request_json,
        args=args,
        recipient_digits=recipient_digits,
        job=job,
    )


def _extract_audiobook_voice_replacement_keys(job: dict[str, object]) -> set[str]:
    voice_selection = dict(dict(job.get("provider") or {}).get("voice_selection") or {})
    last_action = dict(voice_selection.get("last_action") or {})
    return {
        str(item or "").strip()
        for item in list(
            last_action.get("replacement_candidate_keys")
            or voice_selection.get("replacement_candidate_keys")
            or []
        )
        if str(item or "").strip()
    }


def _audiobook_voice_sample_subset(job: dict[str, object], candidate_keys: set[str]) -> dict[str, object]:
    if not candidate_keys:
        return dict(job)
    subset = dict(job)
    provider = dict(subset.get("provider") or {})
    voice_selection = dict(provider.get("voice_selection") or {})
    voice_selection["pending_batch"] = [
        row
        for row in list(voice_selection.get("pending_batch") or [])
        if isinstance(row, dict) and str(row.get("preset_key") or "").strip() in candidate_keys
    ]
    provider["voice_selection"] = voice_selection
    subset["provider"] = provider
    return subset


def _send_whatsapp_replacement_voice_samples(
    *,
    request_json: Callable[..., dict[str, Any]],
    args: argparse.Namespace,
    recipient_digits: str,
    job: dict[str, object],
) -> tuple[dict[str, object], int]:
    replacement_keys = _extract_audiobook_voice_replacement_keys(job)
    if not replacement_keys:
        return job, 0
    sample_job = _audiobook_voice_sample_subset(job, replacement_keys)
    sample_receipts = _send_whatsapp_voice_samples(
        request_json=request_json,
        args=args,
        recipient_digits=recipient_digits,
        job=sample_job,
    )
    if sample_receipts:
        job = audiobook_epub_pipeline.record_audiobook_voice_sample_delivery(
            job=job,
            sample_receipts=sample_receipts,
        )
        job = _record_whatsapp_voice_sample_delivery(job=job, sample_receipts=sample_receipts)
    sent_count = sum(1 for item in sample_receipts if str(dict(item).get("status") or "") == "sent")
    return job, sent_count


def _restore_language_matched_whatsapp_voice_samples(job: dict[str, object], *, limit: int = 3) -> tuple[dict[str, object], int]:
    current = _load_job_from_disk(job)
    job_dir = _job_dir_from_job(current)
    if job_dir is None:
        return current, 0
    private_path = job_dir / "voice_audition" / "private.json"
    try:
        private_payload = json.loads(private_path.read_text(encoding="utf-8"))
    except Exception:
        return current, 0
    private_candidates = dict(private_payload.get("candidates") or {})
    language = _book_language(current)
    if not language:
        return current, 0
    provider = dict(current.get("provider") or {})
    voice_selection = dict(provider.get("voice_selection") or {})
    rows: list[dict[str, object]] = []
    for candidate in private_candidates.values():
        if not isinstance(candidate, dict):
            continue
        public = dict(candidate.get("public") or {})
        if not public:
            continue
        preset_key = str(public.get("preset_key") or candidate.get("candidate_key") or "").strip()
        token = str(public.get("callback_token") or "").strip()
        sample_file = Path(str(public.get("sample_file") or "")).name
        if not preset_key or not token or not sample_file:
            continue
        if not _candidate_matches_language(public, language):
            continue
        if not (job_dir / "voice_audition" / "samples" / sample_file).is_file():
            continue
        rows.append(public)
    rows.sort(
        key=lambda row: (
            int(row.get("score") or 0),
            bool(row.get("author_gender_match")),
            str(row.get("label") or ""),
        ),
        reverse=True,
    )
    selected_rows = rows[: max(1, int(limit or 3))]
    if not selected_rows:
        return current, 0
    selected_keys = [
        str(row.get("preset_key") or "").strip()
        for row in selected_rows
        if str(row.get("preset_key") or "").strip()
    ]
    dismissed = {
        str(item or "").strip()
        for item in list(voice_selection.get("dismissed_candidate_keys") or [])
        if str(item or "").strip()
    }
    dismissed.difference_update(selected_keys)
    restored_selection = {
        **voice_selection,
        "contract_name": audiobook_epub_pipeline.VOICE_AUDITION_CONTRACT_NAME,
        "status": "waiting_user_choice",
        "reason": "language_matched_voice_restored",
        "language_relaxed_after_dismissals": False,
        "pending_candidate_keys": selected_keys,
        "replacement_candidate_keys": selected_keys,
        "pending_batch": selected_rows,
        "dismissed_candidate_keys": sorted(dismissed),
        "selected": {},
        "selected_candidate_key": "",
        "selected_callback_token": "",
        "raw_voice_ids_exposed": False,
        "sample_text_exposed": False,
        "last_action": {
            "action": "restore_language",
            "batch_advanced": True,
            "replacement_candidate_keys": selected_keys,
            "replacement_count": len(selected_keys),
            "remaining_in_batch": len(selected_rows),
            "status": "replacement_ready",
        },
    }
    provider["voice_selection"] = restored_selection
    current["provider"] = provider
    current["status"] = "waiting_voice_selection"
    current["next_action"] = "choose_audiobook_voice"
    current["render_result"] = {
        "status": "waiting_voice_selection",
        "reason": "language_matched_voice_restored",
        "voice_selection": restored_selection,
    }
    current["updated_at"] = _now_iso()
    return _write_job_to_disk(current), len(selected_rows)


def _use_best_current_whatsapp_voice_sample(job: dict[str, object]) -> dict[str, object]:
    current = _load_job_from_disk(job)
    voice_selection = dict(dict(current.get("provider") or {}).get("voice_selection") or {})
    rows = [row for row in list(voice_selection.get("pending_batch") or []) if isinstance(row, dict)]
    if not rows:
        raise RuntimeError("voice_batch_missing")
    rows.sort(key=lambda row: int(row.get("score") or 0), reverse=True)
    token = str(rows[0].get("callback_token") or "").strip()
    if not token:
        raise RuntimeError("voice_batch_token_missing")
    return audiobook_epub_pipeline.apply_audiobook_voice_audition_action(callback_token=token, action="use")


def _voice_choice_match_score(public: dict[str, object], requested: str) -> int:
    normalized_requested = " ".join(_normalize_voice_command_text(requested).split())
    if not normalized_requested:
        return 0
    values = [
        public.get("label"),
        public.get("preset_key"),
        public.get("candidate_key"),
    ]
    for value in values:
        normalized_value = " ".join(_normalize_voice_command_text(str(value or "")).split())
        if not normalized_value:
            continue
        if normalized_value == normalized_requested:
            return 100
        value_parts = set(normalized_value.split())
        request_parts = set(normalized_requested.split())
        if normalized_requested in value_parts:
            return 90
        if request_parts and request_parts.issubset(value_parts):
            return 80
        if normalized_requested in normalized_value:
            return 60
    return 0


def _use_named_whatsapp_voice_sample(job: dict[str, object], text: str) -> dict[str, object]:
    requested = _whatsapp_voice_named_choice(text) or text
    normalized_requested = " ".join(_normalize_voice_command_text(requested).split())
    if not normalized_requested:
        raise RuntimeError("voice_choice_missing")
    current = _load_job_from_disk(job)
    job_dir = _job_dir_from_job(current)
    if job_dir is None:
        raise RuntimeError("job_dir_missing")
    private_path = job_dir / "voice_audition" / "private.json"
    try:
        private_payload = json.loads(private_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError("voice_private_manifest_missing") from exc
    candidates = dict(private_payload.get("candidates") or {})
    matches: list[tuple[int, str, dict[str, object], dict[str, object]]] = []
    for token, candidate in candidates.items():
        if not isinstance(candidate, dict):
            continue
        public = dict(candidate.get("public") or {})
        if not public:
            continue
        if not audiobook_epub_pipeline._voice_candidate_allowed_for_audition(public):  # type: ignore[attr-defined]
            continue
        score = _voice_choice_match_score(public, normalized_requested)
        if score:
            matches.append((score, str(token), dict(candidate), public))
    if not matches:
        raise RuntimeError("voice_choice_not_found")
    matches.sort(key=lambda item: (item[0], int(item[3].get("score") or 0), str(item[3].get("label") or "")), reverse=True)
    _, token, candidate, public = matches[0]
    candidate_key = str(candidate.get("candidate_key") or public.get("preset_key") or "").strip()
    callback_token = str(public.get("callback_token") or token).strip()
    if not candidate_key or not callback_token:
        raise RuntimeError("voice_choice_token_missing")

    selected_public = dict(public)
    selected_public["voice_language_override_by_user"] = True
    selected_public["named_voice_choice"] = normalized_requested
    dismissed = {
        str(item or "").strip()
        for item in list(dict(dict(current.get("provider") or {}).get("voice_selection") or {}).get("dismissed_candidate_keys") or [])
        if str(item or "").strip()
    }
    dismissed.discard(candidate_key)
    provider = dict(current.get("provider") or {})
    voice_selection = dict(provider.get("voice_selection") or {})
    voice_selection.update(
        {
            "contract_name": audiobook_epub_pipeline.VOICE_AUDITION_CONTRACT_NAME,
            "status": "waiting_user_choice",
            "reason": "named_voice_choice_requested",
            "pending_candidate_keys": [candidate_key],
            "replacement_candidate_keys": [],
            "pending_batch": [selected_public],
            "dismissed_candidate_keys": sorted(dismissed),
            "selected": {},
            "selected_candidate_key": "",
            "selected_callback_token": "",
            "named_voice_choice": normalized_requested,
            "voice_language_override_by_user": True,
            "raw_voice_ids_exposed": False,
            "sample_text_exposed": False,
            "last_action": {
                "action": "use_named",
                "candidate_key": candidate_key,
                "status": "pending_candidate_activated",
            },
        }
    )
    provider["voice_selection"] = voice_selection
    current["provider"] = provider
    current["status"] = "waiting_voice_selection"
    current["next_action"] = "choose_audiobook_voice"
    current["updated_at"] = _now_iso()
    _write_job_to_disk(current)
    return audiobook_epub_pipeline.apply_audiobook_voice_audition_action(callback_token=callback_token, action="use")


def _dismiss_named_whatsapp_voice_sample(job: dict[str, object], text: str) -> dict[str, object]:
    requested = _whatsapp_voice_named_dismiss_choice(text) or text
    normalized_requested = " ".join(_normalize_voice_command_text(requested).split())
    if not normalized_requested:
        raise RuntimeError("voice_choice_missing")
    current = _load_job_from_disk(job)
    voice_selection = dict(dict(current.get("provider") or {}).get("voice_selection") or {})
    pending_batch = [row for row in list(voice_selection.get("pending_batch") or []) if isinstance(row, dict)]
    matches: list[tuple[int, str]] = []
    for row in pending_batch:
        token = str(row.get("callback_token") or "").strip()
        if not token:
            continue
        score = _voice_choice_match_score(row, normalized_requested)
        if score:
            matches.append((score, token))
    if not matches:
        raise RuntimeError("voice_choice_not_found")
    matches.sort(key=lambda item: item[0], reverse=True)
    return audiobook_epub_pipeline.apply_audiobook_voice_audition_action(
        callback_token=matches[0][1],
        action="dismiss",
    )


def _dismiss_all_pending_whatsapp_voice_samples(job: dict[str, object]) -> tuple[dict[str, object], int]:
    current = _load_job_from_disk(job)
    provider = dict(current.get("provider") or {})
    voice_selection = dict(provider.get("voice_selection") or {})
    pending_batch = [row for row in list(voice_selection.get("pending_batch") or []) if isinstance(row, dict)]
    pending_keys = [
        str(row.get("preset_key") or "").strip()
        for row in pending_batch
        if str(row.get("preset_key") or "").strip()
    ]
    if not pending_keys:
        return current, 0
    for row in pending_batch:
        try:
            audiobook_epub_pipeline.record_audiobook_voice_feedback(
                job=current,
                candidate=row,
                action="dismiss_all",
            )
        except Exception:
            pass
    dismissed = {
        str(item or "").strip()
        for item in list(voice_selection.get("dismissed_candidate_keys") or [])
        if str(item or "").strip()
    }
    dismissed.update(pending_keys)
    voice_selection["dismissed_candidate_keys"] = sorted(dismissed)
    voice_selection["pending_candidate_keys"] = []
    voice_selection["pending_batch"] = []
    voice_selection["replacement_candidate_keys"] = []
    voice_selection["last_action"] = {
        "action": "dismiss_all",
        "dismissed_count": len(pending_keys),
        "status": "refill_pending",
    }
    provider["voice_selection"] = voice_selection
    current["provider"] = provider
    current["status"] = "waiting_voice_selection"
    current["next_action"] = "choose_audiobook_voice"
    current["updated_at"] = _now_iso()
    current = _write_job_to_disk(current)
    job_dir = _job_dir_from_job(current)
    if job_dir is None:
        return current, len(pending_keys)
    refreshed = audiobook_epub_pipeline.prepare_audiobook_voice_audition(job_dir=job_dir, refill_pending=True)
    refreshed_provider = dict(refreshed.get("provider") or {})
    refreshed_selection = dict(refreshed_provider.get("voice_selection") or {})
    replacement_keys = [
        str(item or "").strip()
        for item in list(refreshed_selection.get("replacement_candidate_keys") or [])
        if str(item or "").strip()
    ]
    refreshed_selection["last_action"] = {
        "action": "dismiss_all",
        "dismissed_count": len(pending_keys),
        "batch_advanced": bool(replacement_keys),
        "replacement_candidate_keys": replacement_keys,
        "replacement_count": len(replacement_keys),
        "remaining_in_batch": len([row for row in list(refreshed_selection.get("pending_batch") or []) if isinstance(row, dict)]),
        "status": "replacement_ready"
        if replacement_keys
        else str(refreshed_selection.get("status") or "voice_catalog_exhausted"),
    }
    refreshed_provider["voice_selection"] = refreshed_selection
    refreshed["provider"] = refreshed_provider
    refreshed["updated_at"] = _now_iso()
    return _write_job_to_disk(refreshed), len(pending_keys)


def _voice_selection_status(job: dict[str, object]) -> str:
    return str(dict(dict(job.get("provider") or {}).get("voice_selection") or {}).get("status") or "").strip()


def _public_share(job: dict[str, object]) -> dict[str, object]:
    return dict(dict(job.get("audiobookshelf_import") or {}).get("public_share") or {})


def _public_share_url(job: dict[str, object]) -> str:
    share = _public_share(job)
    if str(share.get("status") or "").strip() != "public_share_ready":
        return ""
    return str(share.get("absolute_url") or "").strip()


def _public_share_reply_text(job: dict[str, object]) -> str:
    metadata = dict(job.get("metadata") or {})
    title = str(metadata.get("title") or metadata.get("source_filename") or "the audiobook").strip()
    url = _public_share_url(job)
    if url:
        return f"Audiobookshelf finished scanning {title}. Public share link: {url}."
    return _whatsapp_epub_reply_text(job)


def _playback_buttons(job: dict[str, object], recipient_digits: str) -> list[list[tuple[str, str]]]:
    share = _public_share(job)
    callback = dict(share.get("playback_acceptance_callback") or {})
    token = str(callback.get("token") or "").strip()
    if not token:
        return []
    accepted = whatsapp_inbound_actions.encode_whatsapp_audiobook_playback_callback(
        action="a",
        token=token,
        sender_ref=recipient_digits,
    )
    problem = whatsapp_inbound_actions.encode_whatsapp_audiobook_playback_callback(
        action="r",
        token=token,
        sender_ref=recipient_digits,
    )
    if not accepted or not problem:
        return []
    return [[("Playback works", accepted), ("Problem", problem)]]


def _read_job_manifest(manifest_path: Path) -> dict[str, object]:
    try:
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(loaded) if isinstance(loaded, dict) else {}


def _whatsapp_sender_ref_digits(job: dict[str, object]) -> str:
    whatsapp = dict(job.get("whatsapp") or {})
    return "".join(ch for ch in str(whatsapp.get("sender_ref") or "") if ch.isdigit())


def _whatsapp_chat_ref(job: dict[str, object]) -> str:
    whatsapp = dict(job.get("whatsapp") or {})
    return str(whatsapp.get("chat_ref") or "").strip()


def _latest_whatsapp_audiobook_job(
    *,
    sender_digits: str,
    predicate: Callable[[dict[str, object]], bool],
) -> dict[str, object]:
    normalized_sender = "".join(ch for ch in str(sender_digits or "") if ch.isdigit())
    if not normalized_sender:
        return {}
    candidates: list[tuple[float, str, dict[str, object]]] = []
    for manifest_path in _iter_audiobook_job_manifests():
        job = _read_job_manifest(manifest_path)
        if not job:
            continue
        if _whatsapp_sender_ref_digits(job) != normalized_sender:
            continue
        if not predicate(job):
            continue
        try:
            mtime = manifest_path.stat().st_mtime
        except OSError:
            mtime = 0.0
        candidates.append((mtime, manifest_path.parent.name, job))
    if not candidates:
        return {}
    candidates.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return dict(candidates[0][2])


def _latest_whatsapp_audiobook_job_for_chat_ref(
    *,
    chat_ref: str,
    predicate: Callable[[dict[str, object]], bool],
) -> dict[str, object]:
    normalized_chat_ref = str(chat_ref or "").strip()
    if not normalized_chat_ref:
        return {}
    candidates: list[tuple[float, str, dict[str, object]]] = []
    for manifest_path in _iter_audiobook_job_manifests():
        job = _read_job_manifest(manifest_path)
        if not job:
            continue
        if _whatsapp_chat_ref(job) != normalized_chat_ref:
            continue
        if not predicate(job):
            continue
        try:
            mtime = manifest_path.stat().st_mtime
        except OSError:
            mtime = 0.0
        candidates.append((mtime, manifest_path.parent.name, job))
    if not candidates:
        return {}
    candidates.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return dict(candidates[0][2])


def _latest_active_whatsapp_audiobook_job(sender_digits: str) -> dict[str, object]:
    return _latest_whatsapp_audiobook_job(
        sender_digits=sender_digits,
        predicate=lambda job: str(job.get("status") or "").strip() not in AUDIOBOOK_STATUS_DONE_STATUSES,
    )


def _latest_active_whatsapp_audiobook_job_for_chat_ref(chat_ref: str) -> dict[str, object]:
    return _latest_whatsapp_audiobook_job_for_chat_ref(
        chat_ref=chat_ref,
        predicate=lambda job: str(job.get("status") or "").strip() not in AUDIOBOOK_STATUS_DONE_STATUSES,
    )


def _waiting_whatsapp_voice_selection_job_predicate(job: dict[str, object]) -> bool:
    voice_selection = dict(dict(job.get("provider") or {}).get("voice_selection") or {})
    return (
        str(job.get("status") or "").strip() == "waiting_voice_selection"
        and str(voice_selection.get("status") or "").strip() == "waiting_user_choice"
    )


def _latest_waiting_whatsapp_voice_selection_job(*, sender_digits: str, chat_ref: str = "") -> dict[str, object]:
    normalized_sender = "".join(ch for ch in str(sender_digits or "") if ch.isdigit())
    job: dict[str, object] = {}
    if normalized_sender:
        job = _latest_whatsapp_audiobook_job(
            sender_digits=normalized_sender,
            predicate=_waiting_whatsapp_voice_selection_job_predicate,
        )
    if not job and str(chat_ref or "").strip():
        job = _latest_whatsapp_audiobook_job_for_chat_ref(
            chat_ref=str(chat_ref or "").strip(),
            predicate=_waiting_whatsapp_voice_selection_job_predicate,
        )
    return job


def _whatsapp_sender_ref_for_chat_ref(chat_ref: str) -> str:
    job = _latest_active_whatsapp_audiobook_job_for_chat_ref(chat_ref)
    if not job:
        job = _latest_whatsapp_audiobook_job_for_chat_ref(chat_ref=chat_ref, predicate=lambda _job: True)
    return _whatsapp_sender_ref_digits(job) if job else ""


def _whatsapp_voice_delivery(job: dict[str, object]) -> dict[str, object]:
    whatsapp = dict(job.get("whatsapp") or {})
    delivery = dict(whatsapp.get("voice_sample_delivery") or {})
    if delivery:
        return delivery
    return dict(dict(job.get("telegram") or {}).get("voice_sample_delivery") or {})


def _whatsapp_audiobook_check_label(check_key: str) -> str:
    labels = {
        "telegram_audiobook_enabled": "WhatsApp audiobook intake is disabled",
        "telegram_epub_enabled": "WhatsApp audiobook intake is disabled",
        "jobs_root_durable": "audiobook job storage is not durable-storage-backed",
        "jobs_root_writable": "audiobook job storage is not writable",
        "external_tts_enabled": "external audiobook TTS is disabled",
        "unmixr_auto_render_enabled": "audio generation is disabled",
        "voice_catalog_configured": "no audiobook voices are configured",
        "voice_catalog_audition_ready": "fewer than three audiobook voices are available",
        "unmixr_api_key_slot_present": "no owned audio generation account slot is configured",
        "player_access_signing_secret_present": "player-scoped playback signing is not configured",
        "player_access_base_url_present": "player-scoped playback base URL is not configured",
        "audiobookshelf_import_root_durable": "Audiobookshelf import storage is not durable-storage-backed",
        "audiobookshelf_import_root_writable": "Audiobookshelf import storage is not writable",
        "audiobookshelf_public_share_configured": "Audiobookshelf public-share API is not configured",
    }
    return labels.get(check_key, check_key.replace("_", " "))


def _whatsapp_active_audiobook_status_reply_text(*, sender_digits: str, chat_ref: str = "") -> str:
    job = _latest_active_whatsapp_audiobook_job(sender_digits) if sender_digits else {}
    if not job and str(chat_ref or "").strip():
        job = _latest_active_whatsapp_audiobook_job_for_chat_ref(chat_ref)
    if not job:
        return ""
    metadata = dict(job.get("metadata") or {})
    title = str(metadata.get("title") or metadata.get("source_filename") or "the audiobook").strip()
    voice_selection = dict(dict(job.get("provider") or {}).get("voice_selection") or {})
    reason = str(voice_selection.get("reason") or "").strip()
    if (
        str(job.get("status") or "").strip() == "waiting_voice_selection"
        and str(voice_selection.get("status") or "").strip() == "waiting_user_choice"
        and reason == "selected_voice_provider_balance_blocked"
    ):
        pending = [row for row in list(voice_selection.get("pending_batch") or []) if isinstance(row, dict)]
        label = str(dict(pending[0]).get("label") or "the replacement voice").strip() if pending else "the replacement voice"
        delivery = _whatsapp_voice_delivery(job)
        sent = str(delivery.get("status") or "").strip() == "sent" or int(delivery.get("sent_count") or 0) > 0
        selected_voice = str(dict(voice_selection.get("selected") or {}).get("label") or "").strip()
        selected_line = f" The originally selected voice is {selected_voice}." if selected_voice else ""
        sample_line = (
            f"I already sent the replacement sample for {label} with Use/Dismiss controls and text fallback replies like 'use {label}' or 'dismiss all'."
            if sent
            else f"The replacement sample for {label} is prepared but WhatsApp delivery is not confirmed."
        )
        return (
            f"Audiobook status for {title}: waiting for your explicit voice choice. "
            "The selected audiobook voice is blocked by credits/balance, so I stopped before publishing with a different voice."
            f"{selected_line} {sample_line}"
        )
    return _whatsapp_epub_reply_text(job)


def _whatsapp_audiobook_runtime_status_reply_text(text: str, *, sender_digits: str, chat_ref: str = "") -> str:
    if not _whatsapp_audiobook_status_intent(text):
        return ""
    active_job_reply = _whatsapp_active_audiobook_status_reply_text(sender_digits=sender_digits, chat_ref=chat_ref)
    if active_job_reply:
        return active_job_reply
    receipt = audiobook_epub_pipeline.audiobook_runtime_preflight()
    provider = dict(receipt.get("provider") or {})
    access = dict(receipt.get("access") or {})
    failed = [str(item) for item in list(receipt.get("failed_checks") or []) if str(item).strip()]
    warned = [str(item) for item in list(receipt.get("warned_checks") or []) if str(item).strip()]
    voice_count = int(provider.get("voice_catalog_count") or 0)
    min_voices = int(provider.get("voice_audition_min_candidates") or 3)
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
        if key in failed
    ]
    if voice_count < min_voices and "voice_catalog_audition_ready" not in sample_blockers:
        sample_blockers.append("voice_catalog_audition_ready")
    if int(provider.get("api_key_slot_count") or 0) <= 0 and "unmixr_api_key_slot_present" not in sample_blockers:
        sample_blockers.append("unmixr_api_key_slot_present")
    completion_blockers = [
        key
        for key in (
            "player_access_signing_secret_present",
            "player_access_base_url_present",
            "audiobookshelf_import_root_durable",
            "audiobookshelf_import_root_writable",
            "audiobookshelf_public_share_configured",
        )
        if key in failed or key in warned
    ]
    if sample_blockers:
        blocker_text = "; ".join(_whatsapp_audiobook_check_label(key) for key in sample_blockers[:5])
        return (
            "Audiobook voice samples are not live-ready yet. "
            f"Current blockers: {blocker_text}. "
            f"Voice catalog: {voice_count}/{min_voices}; audio generation account slots configured: {int(provider.get('api_key_slot_count') or 0)}. "
            "After those blockers clear, send the source ebook again and I should return three voice samples with Use/Dismiss controls and text fallback replies like 'use <voice>' or 'dismiss all'. "
            f"Completion blockers still tracked: {len(completion_blockers)}."
        )
    if completion_blockers:
        blocker_text = "; ".join(_whatsapp_audiobook_check_label(key) for key in completion_blockers[:4])
        return (
            "Audiobook voice samples are ready, but full delivery is not complete-ready yet. "
            f"Voice catalog: {voice_count}/{min_voices}. Remaining completion blockers: {blocker_text}."
        )
    public_share = "enabled" if access.get("audiobookshelf_public_share_enabled") else "disabled"
    return (
        "Audiobook intake and voice samples are ready. "
        f"Voice catalog: {voice_count}/{min_voices}; Audiobookshelf public share is {public_share}. "
        "Send an EPUB, AZW, AZW3, or MOBI file here in WhatsApp to get the three voice samples. "
        "If WhatsApp degrades, you can still reply with the voice name, 'dismiss <voice>', or 'dismiss all'."
    )


def _maybe_resend_whatsapp_voice_samples(
    *,
    request_json: Callable[..., dict[str, Any]],
    args: argparse.Namespace,
    recipient_digits: str,
    text: str,
    chat_ref: str = "",
) -> tuple[str, int]:
    if not _whatsapp_voice_sample_resend_intent(text):
        return "", 0
    job = _latest_active_whatsapp_audiobook_job(recipient_digits)
    if not job:
        return "", 0
    if str(chat_ref or "").strip() and not _whatsapp_chat_ref(job):
        job = _record_whatsapp_job_metadata(job=job, metadata={"chat_ref": str(chat_ref or "").strip()})
    voice_selection = dict(dict(job.get("provider") or {}).get("voice_selection") or {})
    if str(job.get("status") or "").strip() != "waiting_voice_selection":
        return "", 0
    if str(voice_selection.get("status") or "").strip() != "waiting_user_choice":
        return "", 0
    sample_receipts = _send_whatsapp_voice_samples(
        request_json=request_json,
        args=args,
        recipient_digits=recipient_digits,
        job=job,
    )
    if sample_receipts:
        job = audiobook_epub_pipeline.record_audiobook_voice_sample_delivery(job=job, sample_receipts=sample_receipts)
        _record_whatsapp_voice_sample_delivery(job=job, sample_receipts=sample_receipts)
    sent_count = sum(1 for item in sample_receipts if str(dict(item).get("status") or "").strip() == "sent")
    if sent_count:
        sample_word = "sample" if sent_count == 1 else "samples"
        return f"I resent {sent_count} audiobook voice {sample_word}.", sent_count
    if sample_receipts:
        return "I found the pending voice samples, but WhatsApp could not deliver the sample audio yet.", 0
    return "I found the pending audiobook voice choice, but no sample audio is available to resend yet.", 0


def _latest_whatsapp_audiobook_playback_buttons_for_sender(sender_digits: str) -> tuple[str, list[list[tuple[str, str]]]]:
    def _predicate(job: dict[str, object]) -> bool:
        public_share = _public_share(job)
        delivery = dict(public_share.get("whatsapp_delivery") or {})
        playback = dict(job.get("playback_acceptance") or {})
        return (
            str(public_share.get("status") or "").strip() == "public_share_ready"
            and str(delivery.get("status") or "").strip() == "sent"
            and str(playback.get("status") or "").strip() != "accepted"
        )

    job = _latest_whatsapp_audiobook_job(sender_digits=sender_digits, predicate=_predicate)
    if not job:
        return "", []
    updated_job = audiobook_epub_pipeline.ensure_audiobook_playback_acceptance_callback(job)
    buttons = _playback_buttons(updated_job, sender_digits)
    if not buttons:
        return "", []
    metadata = dict(updated_job.get("metadata") or {})
    title = str(metadata.get("title") or metadata.get("source_filename") or "the latest audiobook").strip()
    return title, buttons


def _record_whatsapp_public_share_delivery(
    *,
    job: dict[str, object],
    notification: dict[str, object],
) -> dict[str, object]:
    current = _load_job_from_disk(job)
    whatsapp = dict(current.get("whatsapp") or {})
    delivery = {
        "status": str(notification.get("status") or "").strip() or "unknown",
        "notified_at": _now_iso(),
        "message_id_sha256": _sha(notification.get("message_id") or notification.get("id") or ""),
        "reason": str(notification.get("reason") or "").strip(),
        "callback_tokens_exposed": False,
        "audiobookshelf_token_exposed": False,
    }
    whatsapp["public_share_delivery"] = delivery
    current["whatsapp"] = whatsapp

    import_result = dict(current.get("audiobookshelf_import") or {})
    share = dict(import_result.get("public_share") or {})
    share["whatsapp_delivery"] = delivery
    share["whatsapp_followup_pending"] = delivery["status"] != "sent"
    import_result["public_share"] = share
    current["audiobookshelf_import"] = import_result
    current["updated_at"] = _now_iso()
    return _write_job_to_disk(current)


def _send_public_share_if_ready(
    *,
    request_json: Callable[..., dict[str, Any]],
    args: argparse.Namespace,
    recipient_digits: str,
    job: dict[str, object],
) -> dict[str, object]:
    if not _public_share_url(job):
        return {"status": "skipped", "reason": "public_share_not_ready"}
    job = audiobook_epub_pipeline.ensure_audiobook_playback_acceptance_callback(job)
    chat_ref = _whatsapp_chat_ref(job)
    inline_buttons_enabled = bool(getattr(args, "public_share_inline_buttons_enabled", False))
    try:
        sent = _send_reply(
            request_json=request_json,
            args=args,
            recipient_digits=recipient_digits,
            text=_public_share_reply_text(job),
            buttons=_playback_buttons(job, recipient_digits) if inline_buttons_enabled else None,
            chat_ref=chat_ref,
        )
    except Exception as exc:
        notification = {"status": "failed", "reason": type(exc).__name__}
        _record_whatsapp_public_share_delivery(job=job, notification=notification)
        return notification
    notification = {
        "status": "sent" if bool(sent.get("ok", True)) else "failed",
        "message_id": sent.get("message_id") or sent.get("id") or "",
        "reason": "" if bool(sent.get("ok", True)) else str(sent.get("reason") or "whatsapp_send_failed"),
    }
    _record_whatsapp_public_share_delivery(job=job, notification=notification)
    return notification


def _continue_whatsapp_audiobook_after_voice_selection(job: dict[str, object]) -> dict[str, object]:
    current = _load_job_from_disk(job)
    if _public_share_url(current):
        return current
    status = str(current.get("status") or "").strip()
    if status not in {
        "voice_selected",
        "blocked_external_tts",
        "blocked_m4b_merge",
        "waiting_provider_throttle",
        "audiobookshelf_imported",
    }:
        return current
    job_dir = _job_dir_from_job(current)
    if job_dir is None:
        return current
    return audiobook_epub_pipeline.continue_job(job_dir)


def _download_whatsapp_epub(
    *,
    request_bytes: Callable[..., bytes],
    args: argparse.Namespace,
    message: dict[str, Any],
) -> Path:
    base_url = str(args.session_api_base_url or DEFAULT_SESSION_API_BASE_URL).strip().rstrip("/")
    session_ref = str(args.session_ref or DEFAULT_SESSION_REF).strip()
    message_id = str(message.get("id") or "").strip()
    url = f"{base_url}/sessions/{urllib.parse.quote(session_ref)}/messages/{urllib.parse.quote(message_id, safe='')}/media"
    payload = request_bytes(
        method="GET",
        url=url,
        token=str(args.session_api_token or ""),
        auth_header_name=str(args.auth_header_name or "Authorization"),
        auth_header_prefix=str(args.auth_header_prefix if args.auth_header_prefix is not None else "Bearer "),
        timeout=float(args.timeout_seconds),
    )
    if not payload:
        raise RuntimeError("whatsapp_epub_media_empty")
    root = audiobook_epub_pipeline.audiobook_jobs_root()
    staging_dir = root / "_incoming_whatsapp" / datetime.now(UTC).strftime("%Y%m%d")
    staging_dir.mkdir(parents=True, exist_ok=True)
    original_name = _message_media_filename(message)
    original_suffix = Path(str(original_name or "")).suffix
    source_name = _safe_filename(
        original_name,
        fallback="whatsapp-book",
        suffix=original_suffix if original_suffix else ".epub",
    )
    staging_path = staging_dir / f"{uuid.uuid4().hex[:12]}-{source_name}"
    staging_path.write_bytes(payload)
    return staging_path


def _whatsapp_approval_sender_ref(sender_digits: str) -> str:
    digits = "".join(ch for ch in str(sender_digits or "") if ch.isdigit())
    return f"whatsapp:{digits}" if digits else ""


def _approval_request_status(approval_id: str) -> str:
    record = audiobook_access_approval.load_request(approval_id)
    return str(record.get("status") or "").strip().lower() if record else "missing"


def _request_whatsapp_audiobook_approval(
    *,
    request_bytes: Callable[..., bytes],
    args: argparse.Namespace,
    message: dict[str, Any],
) -> tuple[dict[str, object], dict[str, object]]:
    sender_digits = _message_sender_digits(message)
    message_id = str(message.get("id") or "").strip()
    session_ref = str(args.session_ref or DEFAULT_SESSION_REF).strip()
    sender_ref = _whatsapp_approval_sender_ref(sender_digits)
    existing = audiobook_access_approval.find_request_for_source(
        channel="whatsapp",
        message_id=message_id,
        session_ref=session_ref,
        sender_ref=sender_ref,
    )
    if existing:
        delivery = dict(existing.get("approval_delivery") or {})
        return existing, {"status": str(delivery.get("status") or "already_requested").strip()}
    epub_path = _download_whatsapp_epub(request_bytes=request_bytes, args=args, message=message)
    record = audiobook_access_approval.create_pending_request(
        channel="whatsapp",
        principal_id=str(getattr(args, "principal_id", "") or DEFAULT_AUDIOBOOK_PRINCIPAL_ID).strip(),
        filename=_message_media_filename(message) or "whatsapp-book.epub",
        source_path=epub_path,
        phone_number=sender_digits,
        sender_ref=sender_ref,
        session_ref=session_ref,
        chat_ref=_message_chat_ref(message),
        message_id=message_id,
        file_size=epub_path.stat().st_size,
        mime_type=_message_media_mime_type(message),
        caption=_message_caption(message),
        requester_label=f"WhatsApp +{sender_digits}" if sender_digits else "WhatsApp requester",
    )
    delivery = audiobook_access_approval.send_telegram_approval_request(record=record)
    return record, delivery


def _process_epub_candidate(
    *,
    request_json: Callable[..., dict[str, Any]],
    request_bytes: Callable[..., bytes],
    args: argparse.Namespace,
    message: dict[str, Any],
    approved_request: dict[str, object] | None = None,
) -> tuple[dict[str, object], list[dict[str, object]], dict[str, object]]:
    sender_digits = _message_sender_digits(message)
    chat_ref = _message_chat_ref(message)
    message_id = str(message.get("id") or "").strip()
    filename = _message_media_filename(message) or "whatsapp-book.epub"
    approved = dict(approved_request or {})
    epub_path = audiobook_access_approval.source_path(approved) if approved else Path()
    if not epub_path.is_file():
        epub_path = _download_whatsapp_epub(request_bytes=request_bytes, args=args, message=message)
    principal_id = str(getattr(args, "principal_id", "") or DEFAULT_AUDIOBOOK_PRINCIPAL_ID).strip()
    job = audiobook_epub_pipeline.create_job_from_epub(
        epub_path=epub_path,
        original_filename=filename,
        principal_id=principal_id,
        chat_id="",
        message_id="",
        caption=_message_caption(message),
        source_url="",
    )
    metadata = {
        "sender_ref": sender_digits,
        "session_ref": str(args.session_ref or DEFAULT_SESSION_REF).strip(),
        "message_id_sha256": _sha(message_id),
        "source": "whatsapp_web_session",
        "source_filename": filename,
        "source_mime_type": _message_media_mime_type(message),
        "caption_sha256": _sha(_message_caption(message)),
        "delivery_status": "voice_samples_pending",
    }
    if chat_ref:
        metadata["chat_ref"] = chat_ref
    job = _record_whatsapp_job_metadata(job=job, metadata=metadata)
    sample_receipts = _send_whatsapp_voice_samples(
        request_json=request_json,
        args=args,
        recipient_digits=sender_digits,
        job=job,
    )
    sent_sample_count = sum(1 for item in sample_receipts if str(dict(item).get("status") or "").strip() == "sent")
    if sample_receipts:
        job = audiobook_epub_pipeline.record_audiobook_voice_sample_delivery(job=job, sample_receipts=sample_receipts)
    job = _record_whatsapp_voice_sample_delivery(job=job, sample_receipts=sample_receipts)
    try:
        _maybe_send_whatsapp_voice_management_controls(
            request_json=request_json,
            args=args,
            recipient_digits=sender_digits,
            job=job,
        )
    except Exception:
        pass
    reply = _send_reply(
        request_json=request_json,
        args=args,
        recipient_digits=sender_digits,
        text=_whatsapp_epub_reply_text(job),
        chat_ref=chat_ref,
    )
    job = _record_whatsapp_job_metadata(
        job=job,
        metadata={
            "delivery_status": "voice_samples_sent" if sent_sample_count else "voice_samples_blocked",
            "intake_reply_message_id_sha256": _sha(reply.get("message_id") or reply.get("id") or ""),
        },
    )
    return job, sample_receipts, reply


def _deliver_ready_whatsapp_share_links(
    *,
    request_json: Callable[..., dict[str, Any]],
    args: argparse.Namespace,
    limit: int | None = None,
) -> dict[str, object]:
    manifest_paths = _iter_audiobook_job_manifests()
    if not manifest_paths:
        return {"attempted": 0, "sent": 0, "errors": 0}
    attempted = 0
    sent = 0
    errors = 0
    max_jobs = max(1, int(limit or getattr(args, "audiobook_followup_limit", 3) or 3))
    for manifest_path in manifest_paths:
        if attempted >= max_jobs:
            break
        try:
            job = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            errors += 1
            continue
        if not isinstance(job, dict):
            continue
        whatsapp = dict(job.get("whatsapp") or {})
        recipient_digits = "".join(ch for ch in str(whatsapp.get("sender_ref") or "") if ch.isdigit())
        if not recipient_digits or not _public_share_url(job):
            continue
        delivery = dict(whatsapp.get("public_share_delivery") or {})
        share_delivery = dict(_public_share(job).get("whatsapp_delivery") or {})
        if str(delivery.get("status") or "").strip() == "sent":
            continue
        if str(share_delivery.get("status") or "").strip() == "sent":
            continue
        attempted += 1
        notification = _send_public_share_if_ready(
            request_json=request_json,
            args=args,
            recipient_digits=recipient_digits,
            job=job,
        )
        if str(notification.get("status") or "").strip() == "sent":
            sent += 1
        else:
            errors += 1
    return {"attempted": attempted, "sent": sent, "errors": errors}


def build_report(
    args: argparse.Namespace,
    *,
    request_json: Callable[..., dict[str, Any]] = _request_json,
    request_bytes: Callable[..., bytes] = _request_bytes,
    handle_callback: Callable[..., dict[str, object]] = whatsapp_inbound_actions.handle_whatsapp_inbound_callback,
    send_telegram_message: Callable[..., dict[str, object]] = _send_telegram_message,
) -> dict[str, object]:
    base_url = str(args.session_api_base_url or DEFAULT_SESSION_API_BASE_URL).strip().rstrip("/")
    session_ref = str(args.session_ref or DEFAULT_SESSION_REF).strip()
    state_path = Path(str(args.state_file or DEFAULT_STATE_FILE))
    state = _load_state(state_path)
    actions = state.setdefault("actions", {})
    if not isinstance(actions, dict):
        actions = {}
        state["actions"] = actions

    messages_url = (
        f"{base_url}/sessions/{urllib.parse.quote(session_ref)}/messages"
        f"?take={max(1, min(int(args.take), 1000))}"
    )
    payload = request_json(
        method="GET",
        url=messages_url,
        token=str(args.session_api_token or ""),
        auth_header_name=str(args.auth_header_name or "Authorization"),
        auth_header_prefix=str(args.auth_header_prefix if args.auth_header_prefix is not None else "Bearer "),
        timeout=float(args.timeout_seconds),
    )
    messages = [message for message in payload.get("messages") or [] if isinstance(message, dict)]
    telegram_summary_messages = list(messages)
    inbox_message_count = len(messages)
    inbox_observability = _inbox_observability_summary(messages)
    candidates = _iter_action_candidates(messages)
    audiobook_source_candidates = _iter_audiobook_source_candidates(messages)
    placeholder_candidates = _iter_empty_placeholder_candidates(messages)
    voice_text_candidates = _iter_audiobook_voice_text_candidates(messages)
    status_candidates = _iter_audiobook_status_candidates(messages)
    conversation_fallback = _conversation_fallback_summary()
    if (
        bool(getattr(args, "conversation_fallback_enabled", True))
        and not candidates
        and not audiobook_source_candidates
        and not placeholder_candidates
        and not voice_text_candidates
        and not status_candidates
    ):
        cooldown_summary = _conversation_fallback_cooldown_summary(args=args, state=state)
        if cooldown_summary is not None:
            if not _should_bypass_conversation_fallback_cooldown(
                args=args,
                state=state,
                messages_payload=payload,
                messages=messages,
            ):
                conversation_fallback = cooldown_summary
        if conversation_fallback.get("status") != "cooldown":
            fallback_messages, conversation_fallback = _load_conversation_fallback_messages(
                request_json=request_json,
                args=args,
                base_url=base_url,
                session_ref=session_ref,
            )
            if fallback_messages:
                messages = _merge_messages(messages, fallback_messages)
                candidates = _iter_action_candidates(messages)
                audiobook_source_candidates = _iter_audiobook_source_candidates(messages)
                placeholder_candidates = _iter_empty_placeholder_candidates(messages)
                voice_text_candidates = _iter_audiobook_voice_text_candidates(messages)
                status_candidates = _iter_audiobook_status_candidates(messages)

    processed = 0
    epub_processed = 0
    voice_text_processed = 0
    status_processed = 0
    freeform_reply_sent = 0
    skipped_processed = 0
    dry_run_candidates = 0
    reply_sent = 0
    voice_sample_sent = 0
    share_link_sent = 0
    errors = 0
    status_counts: dict[str, int] = {}
    stale_notice_keys: set[str] = set()
    now = _now_iso()
    telegram_summary = _maybe_send_telegram_summary(
        args=args,
        state=state,
        messages=telegram_summary_messages,
        send_telegram_message=send_telegram_message,
    )
    if str(telegram_summary.get("status") or "").strip() == "failed":
        errors += 1

    for message in audiobook_source_candidates:
        message_id = str(message.get("id") or "").strip()
        action_id = _action_id(session_ref=session_ref, message_id=message_id, callback_data="epub_media")
        existing_action = actions.get(action_id) if isinstance(actions.get(action_id), dict) else {}
        approved_request: dict[str, object] = {}
        retry_reason = ""
        retry_metadata: dict[str, object] = {}
        if action_id in actions:
            existing_status = str(dict(existing_action).get("status") or "").strip()
            retry_failed_without_reply = existing_status in {"failed", "started"} and not bool(dict(existing_action).get("reply_sent"))
            try:
                existing_sample_sent = int(dict(existing_action).get("sample_sent") or 0)
            except Exception:
                existing_sample_sent = 0
            try:
                zero_sample_retry_count = int(dict(existing_action).get("zero_sample_retry_count") or 0)
            except Exception:
                zero_sample_retry_count = 0
            retry_zero_samples = (
                _env_bool("EA_WHATSAPP_WEB_ACTION_RETRY_ZERO_SAMPLE_AUDIOBOOK", True)
                and existing_status in {"blocked_voice_samples", "applied"}
                and existing_sample_sent <= 0
                and zero_sample_retry_count < _env_int("EA_WHATSAPP_WEB_ACTION_ZERO_SAMPLE_RETRY_LIMIT", 1, minimum=0, maximum=10)
            )
            if retry_failed_without_reply or retry_zero_samples:
                retry_reason = str(dict(existing_action).get("reason") or existing_status or "").strip()
                if retry_zero_samples:
                    retry_reason = "zero_voice_samples"
                    retry_metadata["zero_sample_retry_count"] = zero_sample_retry_count + 1
                    retry_metadata["zero_sample_previous_status"] = existing_status
                existing_action["retry_started_at"] = now
                existing_action["retry_reason"] = retry_reason
                existing_action.update(retry_metadata)
                actions[action_id] = existing_action
                _save_state(state_path, state)
            elif existing_status != "pending_approval":
                skipped_processed += 1
                continue
            else:
                approval_id = str(dict(existing_action).get("approval_id") or "").strip()
                approval_status = _approval_request_status(approval_id)
                if approval_status == "approved":
                    approved_request = audiobook_access_approval.load_request(approval_id)
                elif approval_status == "denied":
                    sender_digits = _message_sender_digits(message)
                    chat_ref = _message_chat_ref(message)
                    try:
                        send_result = _send_reply(
                            request_json=request_json,
                            args=args,
                            recipient_digits=sender_digits,
                            text="That audiobook request was not approved.",
                            chat_ref=chat_ref,
                        )
                        existing_action["denial_reply_sent"] = bool(send_result.get("ok", True))
                        existing_action["denial_reply_message_hash"] = _sha(send_result.get("message_id") or send_result.get("id") or "")
                        if existing_action["denial_reply_sent"]:
                            reply_sent += 1
                    except Exception as exc:
                        errors += 1
                        existing_action["denial_reply_error"] = type(exc).__name__
                    existing_action["status"] = "denied"
                    actions[action_id] = existing_action
                    processed += 1
                    status_counts["denied"] = status_counts.get("denied", 0) + 1
                    _save_state(state_path, state)
                    continue
                else:
                    skipped_processed += 1
                    continue
        if bool(args.dry_run):
            dry_run_candidates += 1
            continue

        sender_digits = _message_sender_digits(message)
        sender_ref = _whatsapp_approval_sender_ref(sender_digits)
        if not approved_request and audiobook_access_approval.approval_required(
            phone_number=sender_digits,
            sender_ref=sender_ref,
            channel="whatsapp",
        ):
            actions[action_id] = {
                "approval_id": "",
                "approval_id_sha256": "",
                "callback_hash": _sha("epub_media"),
                "kind": "audiobook_epub",
                "message_hash": _sha(message_id),
                "processed_at": now,
                "reply_sent": False,
                "status": "pending_approval",
            }
            if retry_reason:
                actions[action_id]["retry_reason"] = retry_reason
                actions[action_id]["retry_started_at"] = now
            if retry_metadata:
                actions[action_id].update(retry_metadata)
            _save_state(state_path, state)
            try:
                approval_record, delivery = _request_whatsapp_audiobook_approval(
                    request_bytes=request_bytes,
                    args=args,
                    message=message,
                )
                approval_id = str(approval_record.get("approval_id") or "").strip()
                actions[action_id]["approval_id"] = approval_id
                actions[action_id]["approval_id_sha256"] = _sha(approval_id)
                actions[action_id]["approval_delivery_status"] = str(delivery.get("status") or "").strip()
                approval_sent = str(delivery.get("status") or "").strip() in {"sent", "already_requested"}
                reply = _send_reply(
                    request_json=request_json,
                    args=args,
                    recipient_digits=sender_digits,
                    text=(
                        "I need operator approval before creating an audiobook for this number. I sent the approval request in Telegram."
                        if approval_sent
                        else (
                            "I need operator approval before creating an audiobook for this number, "
                            "but the Telegram approval request could not be sent yet."
                        )
                    ),
                    chat_ref=_message_chat_ref(message),
                )
                actions[action_id]["reply_sent"] = bool(reply.get("ok", True))
                actions[action_id]["reply_message_hash"] = _sha(reply.get("message_id") or reply.get("id") or "")
                if actions[action_id]["reply_sent"]:
                    reply_sent += 1
            except Exception as exc:
                errors += 1
                actions[action_id]["status"] = "failed"
                actions[action_id]["reason"] = type(exc).__name__
                try:
                    send_result = _send_reply(
                        request_json=request_json,
                        args=args,
                        recipient_digits=sender_digits,
                        text="I could not request operator approval for that audiobook yet.",
                        chat_ref=_message_chat_ref(message),
                    )
                    actions[action_id]["reply_sent"] = bool(send_result.get("ok", True))
                    actions[action_id]["reply_message_hash"] = _sha(send_result.get("message_id") or send_result.get("id") or "")
                    if actions[action_id]["reply_sent"]:
                        reply_sent += 1
                except Exception as reply_exc:
                    actions[action_id]["reply_error"] = type(reply_exc).__name__
            processed += 1
            status_counts[str(actions[action_id].get("status") or "pending_approval")] = status_counts.get(str(actions[action_id].get("status") or "pending_approval"), 0) + 1
            _save_state(state_path, state)
            continue
        actions[action_id] = {
            "callback_hash": _sha("epub_media"),
            "kind": "audiobook_epub",
            "message_hash": _sha(message_id),
            "processed_at": now,
            "reply_sent": False,
            "status": "started",
        }
        if retry_reason:
            actions[action_id]["retry_reason"] = retry_reason
            actions[action_id]["retry_started_at"] = now
        if retry_metadata:
            actions[action_id].update(retry_metadata)
        _save_state(state_path, state)
        try:
            _job, sample_receipts, reply = _process_epub_candidate(
                request_json=request_json,
                request_bytes=request_bytes,
                args=args,
                message=message,
                approved_request=approved_request,
            )
            sent_samples = sum(1 for item in sample_receipts if str(dict(item).get("status") or "") == "sent")
            voice_sample_sent += sent_samples
            status = "applied" if sent_samples else "blocked_voice_samples"
            if sent_samples <= 0:
                errors += 1
            actions[action_id].update(
                {
                    "reply_sent": bool(reply.get("ok", True)),
                    "reply_message_hash": _sha(reply.get("message_id") or reply.get("id") or ""),
                    "sample_sent": sent_samples,
                    "status": status,
                }
            )
            if actions[action_id]["reply_sent"]:
                reply_sent += 1
        except Exception as exc:
            status = "failed"
            errors += 1
            actions[action_id].update({"reply_sent": False, "status": status, "reason": type(exc).__name__})
            try:
                chat_ref = _message_chat_ref(message)
                send_result = _send_reply(
                    request_json=request_json,
                    args=args,
                    recipient_digits=sender_digits,
                    text="I could not prepare that audiobook source yet.",
                    chat_ref=chat_ref,
                )
                actions[action_id]["reply_sent"] = bool(send_result.get("ok", True))
                actions[action_id]["reply_message_hash"] = _sha(send_result.get("message_id") or send_result.get("id") or "")
                if actions[action_id]["reply_sent"]:
                    reply_sent += 1
            except Exception as reply_exc:
                actions[action_id]["reply_error"] = type(reply_exc).__name__
            status_counts[status] = status_counts.get(status, 0) + 1
        processed += 1
        epub_processed += 1
        _save_state(state_path, state)

    for message in placeholder_candidates:
        message_id = str(message.get("id") or "").strip()
        action_id = _action_id(session_ref=session_ref, message_id=message_id, callback_data="placeholder_resend")
        if action_id in actions:
            skipped_processed += 1
            continue
        if bool(args.dry_run):
            dry_run_candidates += 1
            continue

        chat_ref = _message_chat_ref(message)
        sender_digits = _message_sender_digits(message) or _whatsapp_sender_ref_for_chat_ref(chat_ref)
        status = "placeholder_replied"
        actions[action_id] = {
            "callback_hash": _sha("placeholder_resend"),
            "kind": "placeholder_resend",
            "message_hash": _sha(message_id),
            "processed_at": now,
            "reply_sent": False,
            "status": status,
        }
        _save_state(state_path, state)
        processed += 1

        reply_text = (
            "WhatsApp Web only received an empty placeholder for that message, not the actual file. "
            "Please send the book again as a document attachment."
        )
        try:
            send_result = _send_reply(
                request_json=request_json,
                args=args,
                recipient_digits=sender_digits,
                text=reply_text,
                chat_ref=chat_ref,
            )
            actions[action_id]["reply_sent"] = bool(send_result.get("ok", True))
            actions[action_id]["reply_message_hash"] = _sha(send_result.get("message_id") or send_result.get("id") or "")
            if actions[action_id]["reply_sent"]:
                reply_sent += 1
        except Exception as exc:
            status = "failed"
            errors += 1
            actions[action_id].update({"reply_sent": False, "status": status, "reason": type(exc).__name__})
        status_counts[status] = status_counts.get(status, 0) + 1
        _save_state(state_path, state)

    for message in voice_text_candidates:
        message_id = str(message.get("id") or "").strip()
        text = _message_body_text(message)
        chat_ref = _message_chat_ref(message)
        sender_digits = _message_sender_digits(message) or _whatsapp_sender_ref_for_chat_ref(chat_ref)
        text_action = _whatsapp_voice_text_action(text)
        if not text_action and _pending_whatsapp_voice_label_choice(text, sender_digits=sender_digits, chat_ref=chat_ref):
            text_action = "use_named"
        action_id = _action_id(session_ref=session_ref, message_id=message_id, callback_data=f"audiobook_voice_text:{text_action}")
        if action_id in actions:
            skipped_processed += 1
            continue
        if bool(args.dry_run):
            dry_run_candidates += 1
            continue

        status = "applied"
        actions[action_id] = {
            "callback_hash": _sha(f"audiobook_voice_text:{text_action}"),
            "kind": "audiobook_voice_text",
            "message_hash": _sha(message_id),
            "processed_at": now,
            "reply_sent": False,
            "status": "started",
        }
        _save_state(state_path, state)
        processed += 1
        voice_text_processed += 1

        reply_text = ""
        try:
            if not sender_digits:
                status = "failed"
                reply_text = "I could not match that voice command to a WhatsApp audiobook job."
                errors += 1
            elif text_action == "dismiss_all":
                job = _latest_waiting_whatsapp_voice_selection_job(sender_digits=sender_digits, chat_ref=chat_ref)
                if not job:
                    status = "stale"
                    reply_text = "There is no pending audiobook voice batch to dismiss."
                else:
                    if chat_ref and not _whatsapp_chat_ref(job):
                        job = _record_whatsapp_job_metadata(job=job, metadata={"chat_ref": chat_ref})
                    job, dismissed_count = _dismiss_all_pending_whatsapp_voice_samples(job)
                    sample_receipts = _send_whatsapp_voice_samples(
                        request_json=request_json,
                        args=args,
                        recipient_digits=sender_digits,
                        job=job,
                    )
                    if sample_receipts:
                        job = audiobook_epub_pipeline.record_audiobook_voice_sample_delivery(
                            job=job,
                            sample_receipts=sample_receipts,
                        )
                        job = _record_whatsapp_voice_sample_delivery(job=job, sample_receipts=sample_receipts)
                    sent_count = sum(
                        1 for item in sample_receipts if str(dict(item).get("status") or "").strip() == "sent"
                    )
                    voice_sample_sent += sent_count
                    actions[action_id]["dismissed_voice_sample_count"] = dismissed_count
                    actions[action_id]["replacement_sample_sent"] = sent_count
                    if sent_count:
                        sample_word = "sample" if sent_count == 1 else "samples"
                        reply_text = f"Dismissed all {dismissed_count} current voices. I sent {sent_count} replacement audiobook voice {sample_word}."
                    elif dismissed_count:
                        reply_text = "Dismissed the current voices, but WhatsApp could not deliver the replacement sample audio yet."
                    else:
                        status = "stale"
                        reply_text = "There is no pending audiobook voice batch to dismiss."
            elif text_action == "use_named":
                job = _latest_waiting_whatsapp_voice_selection_job(sender_digits=sender_digits, chat_ref=chat_ref)
                if not job:
                    status = "stale"
                    reply_text = "There is no pending audiobook voice batch to choose from."
                else:
                    if chat_ref and not _whatsapp_chat_ref(job):
                        job = _record_whatsapp_job_metadata(job=job, metadata={"chat_ref": chat_ref})
                    job = _use_named_whatsapp_voice_sample(job, text)
                    selection = dict(dict(job.get("provider") or {}).get("voice_selection") or {})
                    selected = dict(selection.get("selected") or {})
                    label = str(selected.get("label") or _whatsapp_voice_named_choice(text) or "that voice").strip()
                    actions[action_id]["selected_voice_label_hash"] = _sha(label)
                    actions[action_id]["selected_candidate_key_hash"] = _sha(selection.get("selected_candidate_key") or "")
                    share_result = _send_public_share_if_ready(
                        request_json=request_json,
                        args=args,
                        recipient_digits=sender_digits,
                        job=job,
                    )
                    share_sent = str(share_result.get("status") or "") == "sent"
                    actions[action_id]["public_share_status"] = str(share_result.get("status") or "")
                    if share_sent:
                        reply_text = ""
                    elif str(job.get("status") or "").strip() == "failed":
                        status = "failed"
                        reply_text = _whatsapp_epub_reply_text(job)
                    else:
                        reply_text = f"Selected {label}. I am rendering the audiobook with that voice now."
            elif text_action == "dismiss_named":
                job = _latest_waiting_whatsapp_voice_selection_job(sender_digits=sender_digits, chat_ref=chat_ref)
                if not job:
                    status = "stale"
                    reply_text = "There is no pending audiobook voice batch to dismiss from."
                else:
                    if chat_ref and not _whatsapp_chat_ref(job):
                        job = _record_whatsapp_job_metadata(job=job, metadata={"chat_ref": chat_ref})
                    dismissed_label = (
                        _pending_whatsapp_voice_label_choice(
                            _whatsapp_voice_named_dismiss_choice(text) or text,
                            sender_digits=sender_digits,
                            chat_ref=chat_ref,
                        )
                        or _whatsapp_voice_named_dismiss_choice(text)
                        or "that voice"
                    )
                    if dismissed_label != "that voice":
                        dismissed_label = " ".join(part.capitalize() for part in dismissed_label.split())
                    job = _dismiss_named_whatsapp_voice_sample(job, text)
                    replacement_keys = _extract_audiobook_voice_replacement_keys(job)
                    if replacement_keys:
                        job, sent_count = _send_whatsapp_replacement_voice_samples(
                            request_json=request_json,
                            args=args,
                            recipient_digits=sender_digits,
                            job=job,
                        )
                        voice_sample_sent += sent_count
                        actions[action_id]["replacement_sample_sent"] = sent_count
                        if sent_count:
                            sample_word = "sample" if sent_count == 1 else "samples"
                            reply_text = f"Dismissed {dismissed_label}. I sent {sent_count} replacement audiobook voice {sample_word}."
                        else:
                            reply_text = f"Dismissed {dismissed_label}. The replacement audiobook voice is ready, but WhatsApp could not deliver the sample audio."
                    elif _voice_selection_status(job) == "exhausted":
                        reply_text = f"Dismissed {dismissed_label}. No more configured audiobook voice samples are available for this book."
            else:
                status = "ignored"
                reply_text = ""
        except Exception as exc:
            status = "failed"
            errors += 1
            reply_text = "I could not process that audiobook voice command yet."
            actions[action_id]["reason"] = type(exc).__name__

        status_counts[status] = status_counts.get(status, 0) + 1
        actions[action_id]["status"] = status
        if reply_text and sender_digits:
            try:
                send_result = _send_reply(
                    request_json=request_json,
                    args=args,
                    recipient_digits=sender_digits,
                    text=reply_text,
                    chat_ref=chat_ref,
                )
                actions[action_id]["reply_sent"] = bool(send_result.get("ok", True))
                actions[action_id]["reply_message_hash"] = _sha(send_result.get("message_id") or send_result.get("id") or "")
                if actions[action_id]["reply_sent"]:
                    reply_sent += 1
            except Exception as exc:
                errors += 1
                actions[action_id]["reply_error"] = type(exc).__name__
        _save_state(state_path, state)

    for message in candidates:
        callback_data = _message_callback_data(message)
        message_id = str(message.get("id") or "").strip()
        action_id = _action_id(session_ref=session_ref, message_id=message_id, callback_data=callback_data)
        existing_action = actions.get(action_id) if isinstance(actions.get(action_id), dict) else {}
        retry_failed_without_reply = (
            str(dict(existing_action).get("status") or "").strip() == "failed"
            and not bool(dict(existing_action).get("reply_sent"))
        )
        retry_ignored_missing_secret = (
            str(dict(existing_action).get("status") or "").strip() == "ignored"
            and str(dict(existing_action).get("reason") or "").strip() == "missing_secret"
            and not bool(dict(existing_action).get("reply_sent"))
        )
        if action_id in actions and not retry_failed_without_reply and not retry_ignored_missing_secret:
            skipped_processed += 1
            continue
        if bool(args.dry_run):
            dry_run_candidates += 1
            continue

        chat_ref = _message_chat_ref(message)
        sender_digits = _message_sender_digits(message) or _whatsapp_sender_ref_for_callback(
            callback_data=callback_data,
            chat_ref=chat_ref,
        )
        if not sender_digits:
            actions[action_id] = {
                "callback_hash": _sha(callback_data),
                "kind": str(message.get("selected_button_kind") or "").strip(),
                "message_hash": _sha(message_id),
                "processed_at": now,
                "reply_sent": False,
                "status": "failed",
                "reason": "sender_ref_unresolved",
            }
            status_counts["failed"] = status_counts.get("failed", 0) + 1
            errors += 1
            processed += 1
            _save_state(state_path, state)
            continue
        try:
            result = dict(
                handle_callback(
                    callback_data=callback_data,
                    sender_ref=sender_digits,
                    message_id=message_id,
                )
            )
        except Exception as exc:
            result = {"status": "failed", "reason": type(exc).__name__, "reply_text": "I could not process that WhatsApp action yet."}
            errors += 1

        status = str(result.get("status") or "unknown").strip() or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1
        result_kind = str(result.get("kind") or message.get("selected_button_kind") or "").strip()
        actions[action_id] = {
            "callback_hash": _sha(callback_data),
            "kind": result_kind,
            "message_hash": _sha(message_id),
            "processed_at": now,
            "reply_sent": False,
            "status": status,
        }
        reason = str(result.get("reason") or "").strip()
        if reason:
            actions[action_id]["reason"] = reason
        _save_state(state_path, state)
        processed += 1

        reply_text = str(result.get("reply_text") or "").strip()
        job = result.get("job") if isinstance(result.get("job"), dict) else {}
        if status == "applied" and str(result.get("kind") or "") == "audiobook_voice_management":
            management_token = str(result.get("token") or _callback_token(callback_data)).strip()
            action = str(result.get("action") or "").strip()
            job = _whatsapp_audiobook_job_by_management_token(
                token=management_token,
                chat_ref=chat_ref,
                sender_digits=sender_digits,
            )
            if not job:
                status = "stale"
                actions[action_id]["status"] = status
                reply_text = "That audiobook control is stale. Use the latest voice sample controls."
            else:
                metadata = {
                    "sender_ref": sender_digits,
                    "session_ref": session_ref,
                    "last_management_callback_message_id_sha256": _sha(message_id),
                    "source": "whatsapp_web_session",
                }
                if chat_ref:
                    metadata["chat_ref"] = chat_ref
                job = _record_whatsapp_job_metadata(job=job, metadata=metadata)
                if action == "restore_language":
                    job, restored_count = _restore_language_matched_whatsapp_voice_samples(job)
                    actions[action_id]["restored_voice_sample_count"] = restored_count
                    if restored_count:
                        sample_receipts = _send_whatsapp_voice_samples(
                            request_json=request_json,
                            args=args,
                            recipient_digits=sender_digits,
                            job=job,
                        )
                        if sample_receipts:
                            job = audiobook_epub_pipeline.record_audiobook_voice_sample_delivery(
                                job=job,
                                sample_receipts=sample_receipts,
                            )
                            job = _record_whatsapp_voice_sample_delivery(job=job, sample_receipts=sample_receipts)
                        sent_count = sum(
                            1 for item in sample_receipts if str(dict(item).get("status") or "").strip() == "sent"
                        )
                        voice_sample_sent += sent_count
                        actions[action_id]["replacement_sample_sent"] = sent_count
                        if sent_count:
                            sample_word = "sample" if sent_count == 1 else "samples"
                            reply_text = f"Restored the best language-matched voices and sent {sent_count} {sample_word}."
                        else:
                            reply_text = "Restored the best language-matched voices, but WhatsApp could not deliver the sample audio yet."
                    else:
                        reply_text = "I could not find any earlier language-matched voice samples to restore."
                elif action == "next_batch":
                    job, dismissed_count = _dismiss_all_pending_whatsapp_voice_samples(job)
                    sample_receipts = _send_whatsapp_voice_samples(
                        request_json=request_json,
                        args=args,
                        recipient_digits=sender_digits,
                        job=job,
                    )
                    if sample_receipts:
                        job = audiobook_epub_pipeline.record_audiobook_voice_sample_delivery(
                            job=job,
                            sample_receipts=sample_receipts,
                        )
                        job = _record_whatsapp_voice_sample_delivery(job=job, sample_receipts=sample_receipts)
                    sent_count = sum(
                        1 for item in sample_receipts if str(dict(item).get("status") or "").strip() == "sent"
                    )
                    voice_sample_sent += sent_count
                    actions[action_id]["dismissed_voice_sample_count"] = dismissed_count
                    actions[action_id]["replacement_sample_sent"] = sent_count
                    if sent_count:
                        sample_word = "sample" if sent_count == 1 else "samples"
                        reply_text = f"Dismissed the current batch and sent {sent_count} replacement {sample_word}."
                    elif dismissed_count:
                        reply_text = "Dismissed the current batch, but no replacement voice sample could be delivered yet."
                    else:
                        reply_text = "There is no pending audiobook voice batch to replace."
                    try:
                        _maybe_send_whatsapp_voice_management_controls(
                            request_json=request_json,
                            args=args,
                            recipient_digits=sender_digits,
                            job=job,
                        )
                    except Exception as exc:
                        actions[action_id]["management_controls_error"] = type(exc).__name__
                elif action == "use_best_current":
                    try:
                        job = _use_best_current_whatsapp_voice_sample(job)
                        job = _record_whatsapp_job_metadata(job=job, metadata=metadata)
                        notification = _send_public_share_if_ready(
                            request_json=request_json,
                            args=args,
                            recipient_digits=sender_digits,
                            job=job,
                        )
                        if str(notification.get("status") or "") == "sent":
                            actions[action_id]["public_share_sent"] = True
                            share_link_sent += 1
                            reply_text = ""
                        else:
                            reply_text = _whatsapp_epub_reply_text(job)
                    except Exception as exc:
                        actions[action_id]["reason"] = type(exc).__name__
                        reply_text = "I could not select the best current audiobook voice yet."
                else:
                    status = "ignored"
                    actions[action_id]["status"] = status
                    reply_text = "That audiobook control is not supported anymore. Use the latest controls."
        if status == "applied" and str(result.get("kind") or "") == "audiobook_voice" and isinstance(job, dict) and job:
            metadata = {
                "sender_ref": sender_digits,
                "session_ref": session_ref,
                "last_callback_message_id_sha256": _sha(message_id),
                "source": "whatsapp_web_session",
            }
            if chat_ref:
                metadata["chat_ref"] = chat_ref
            job = _record_whatsapp_job_metadata(
                job=job,
                metadata=metadata,
            )
            action = str(result.get("action") or "").strip()
            if action == "dismiss":
                replacement_keys = _extract_audiobook_voice_replacement_keys(job)
                if replacement_keys:
                    job, sent_count = _send_whatsapp_replacement_voice_samples(
                        request_json=request_json,
                        args=args,
                        recipient_digits=sender_digits,
                        job=job,
                    )
                    voice_sample_sent += sent_count
                    actions[action_id]["replacement_sample_sent"] = sent_count
                    if sent_count:
                        sample_word = "sample" if sent_count == 1 else "samples"
                        reply_text = f"Dismissed. I sent {sent_count} replacement audiobook voice {sample_word}."
                    else:
                        reply_text = "Dismissed. The replacement audiobook voice is ready, but WhatsApp could not deliver the sample audio."
                elif _voice_selection_status(job) == "exhausted":
                    reply_text = "Dismissed. No more configured audiobook voice samples are available for this book."
                try:
                    _maybe_send_whatsapp_voice_management_controls(
                        request_json=request_json,
                        args=args,
                        recipient_digits=sender_digits,
                        job=job,
                    )
                except Exception as exc:
                    actions[action_id]["management_controls_error"] = type(exc).__name__
            elif action == "use":
                voice_selection = dict(dict(job.get("provider") or {}).get("voice_selection") or {})
                if (
                    str(job.get("status") or "").strip() == "waiting_voice_selection"
                    and str(voice_selection.get("reason") or "").strip() == "selected_voice_provider_balance_blocked"
                    and _extract_audiobook_voice_replacement_keys(job)
                ):
                    job, sent_count = _send_whatsapp_replacement_voice_samples(
                        request_json=request_json,
                        args=args,
                        recipient_digits=sender_digits,
                        job=job,
                    )
                    voice_sample_sent += sent_count
                    actions[action_id]["replacement_sample_sent"] = sent_count
                    if sent_count:
                        sample_word = "sample" if sent_count == 1 else "samples"
                        reply_text = (
                            "The selected audiobook voice is blocked right now, so I stopped before publishing "
                            f"with a different voice. I sent {sent_count} replacement audiobook voice {sample_word}."
                        )
                    else:
                        reply_text = (
                            "The selected audiobook voice is blocked right now, so I stopped before publishing "
                            "with a different voice. The replacement voice is ready, but WhatsApp could not deliver "
                            "the sample audio."
                        )
                else:
                    notification = _send_public_share_if_ready(
                        request_json=request_json,
                        args=args,
                        recipient_digits=sender_digits,
                        job=job,
                    )
                    if str(notification.get("status") or "") != "sent":
                        try:
                            resumed_job = _continue_whatsapp_audiobook_after_voice_selection(job)
                            if resumed_job != job:
                                job = resumed_job
                                actions[action_id]["post_voice_selection_continue_status"] = str(job.get("status") or "").strip()
                                notification = _send_public_share_if_ready(
                                    request_json=request_json,
                                    args=args,
                                    recipient_digits=sender_digits,
                                    job=job,
                                )
                        except Exception as exc:
                            actions[action_id]["post_voice_selection_continue_error"] = type(exc).__name__
                    if str(notification.get("status") or "") == "sent":
                        actions[action_id]["public_share_sent"] = True
                        share_link_sent += 1
                        reply_text = ""
        suppress_reply, suppress_reason = _suppress_stale_callback_reply(
            args=args,
            message=message,
            status=status,
            stale_notice_keys=stale_notice_keys,
            chat_ref=chat_ref,
            sender_digits=sender_digits,
            kind=result_kind,
        )
        if suppress_reply and reply_text:
            actions[action_id]["reply_suppressed"] = True
            actions[action_id]["reply_suppressed_reason"] = suppress_reason
            reply_text = ""
        if reply_text and sender_digits:
            try:
                send_result = _send_reply(
                    request_json=request_json,
                    args=args,
                    recipient_digits=sender_digits,
                    text=reply_text,
                    chat_ref=chat_ref or _whatsapp_chat_ref(job),
                )
                actions[action_id]["reply_sent"] = bool(send_result.get("ok", True))
                actions[action_id]["reply_message_hash"] = _sha(send_result.get("message_id") or send_result.get("id") or "")
                if actions[action_id]["reply_sent"]:
                    reply_sent += 1
            except Exception as exc:
                errors += 1
                actions[action_id]["reply_error"] = type(exc).__name__
            _save_state(state_path, state)

    for message in status_candidates:
        message_id = str(message.get("id") or "").strip()
        action_id = _action_id(session_ref=session_ref, message_id=message_id, callback_data="audiobook_status")
        if action_id in actions:
            skipped_processed += 1
            continue
        if bool(args.dry_run):
            dry_run_candidates += 1
            continue

        chat_ref = _message_chat_ref(message)
        sender_digits = _message_sender_digits(message) or _whatsapp_sender_ref_for_chat_ref(chat_ref)
        text = _message_body_text(message)
        status = "status_replied"
        actions[action_id] = {
            "callback_hash": _sha("audiobook_status"),
            "kind": "audiobook_status",
            "message_hash": _sha(message_id),
            "processed_at": now,
            "reply_sent": False,
            "status": status,
        }
        _save_state(state_path, state)
        processed += 1
        status_processed += 1

        try:
            reply_text = _whatsapp_audiobook_runtime_status_reply_text(text, sender_digits=sender_digits, chat_ref=chat_ref)
            resend_line, resent_count = _maybe_resend_whatsapp_voice_samples(
                request_json=request_json,
                args=args,
                recipient_digits=sender_digits,
                text=text,
                chat_ref=chat_ref,
            )
            if resent_count:
                voice_sample_sent += resent_count
                actions[action_id]["resent_voice_sample_count"] = resent_count
            if resend_line:
                reply_text = f"{reply_text}\n\n{resend_line}".strip()
            title, playback_buttons = _latest_whatsapp_audiobook_playback_buttons_for_sender(sender_digits)
            if playback_buttons:
                reply_text = (
                    f"{reply_text}\n\n"
                    f"Latest Audiobookshelf delivery awaiting playback confirmation: {title}."
                ).strip()
                actions[action_id]["playback_buttons_sent"] = True
            send_result = _send_reply(
                request_json=request_json,
                args=args,
                recipient_digits=sender_digits,
                text=reply_text,
                buttons=playback_buttons or None,
                chat_ref=chat_ref,
            )
            actions[action_id]["reply_sent"] = bool(send_result.get("ok", True))
            actions[action_id]["reply_message_hash"] = _sha(send_result.get("message_id") or send_result.get("id") or "")
            if actions[action_id]["reply_sent"]:
                reply_sent += 1
        except Exception as exc:
            status = "failed"
            errors += 1
            actions[action_id].update({"reply_sent": False, "status": status, "reason": type(exc).__name__})
        status_counts[status] = status_counts.get(status, 0) + 1
        _save_state(state_path, state)

    freeform_state = _freeform_state(state)
    for message in messages:
        if not _is_freeform_inbox_message(message):
            continue
        if _message_heyy_ai_key(message).strip() != "executive_assistant":
            continue
        if not _executive_assistant_freeform_enabled(args):
            continue
        message_id = str(message.get("id") or "").strip()
        if not message_id:
            continue
        existing_freeform = freeform_state.get(message_id)
        if isinstance(existing_freeform, dict) and bool(existing_freeform.get("reply_sent")):
            continue
        sender_digits = _message_sender_digits(message) or _whatsapp_sender_ref_for_chat_ref(_message_chat_ref(message))
        if not sender_digits:
            freeform_state[message_id] = {
                "processed_at": now,
                "reply_sent": False,
                "status": "failed",
                "reason": "sender_ref_unresolved",
            }
            _save_state(state_path, state)
            continue
        chat_ref = _message_chat_ref(message)
        reply_text = _executive_assistant_freeform_reply_text(args=args, message=message)
        if not reply_text:
            freeform_state[message_id] = {
                "processed_at": now,
                "reply_sent": False,
                "status": "skipped",
                "reason": "reply_text_empty",
            }
            _save_state(state_path, state)
            continue
        try:
            send_result = _send_reply(
                request_json=request_json,
                args=_freeform_reply_args(
                    args,
                    heyy_ai_key="executive_assistant",
                    heyy_ai_name="Executive Assistant",
                ),
                recipient_digits=sender_digits,
                text=reply_text,
                chat_ref=chat_ref,
            )
            reply_sent_ok = bool(send_result.get("ok", True))
            freeform_state[message_id] = {
                "processed_at": now,
                "reply_message_hash": _sha(send_result.get("message_id") or send_result.get("id") or ""),
                "reply_sent": reply_sent_ok,
                "reply_text_hash": _sha(reply_text),
                "status": "replied" if reply_sent_ok else "failed",
            }
            if reply_sent_ok:
                reply_sent += 1
                freeform_reply_sent += 1
        except Exception as exc:
            errors += 1
            freeform_state[message_id] = {
                "processed_at": now,
                "reply_sent": False,
                "status": "failed",
                "reason": type(exc).__name__,
            }
        _save_state(state_path, state)

    resume_summary: dict[str, object] = {"ran": False}
    if bool(getattr(args, "audiobook_resume_due", False)):
        try:
            resume_summary = dict(
                audiobook_epub_pipeline.resume_due_audiobook_jobs(
                    notify_telegram=False,
                    limit=int(getattr(args, "audiobook_resume_due_limit", 1) or 1),
                )
            )
            errors += int(resume_summary.get("errors") or 0)
        except Exception as exc:
            errors += 1
            resume_summary = {"ran": False, "errors": 1, "reason": type(exc).__name__}

    followup_summary: dict[str, object] = {"attempted": 0, "sent": 0, "errors": 0}
    if bool(getattr(args, "audiobook_followup_enabled", False)):
        try:
            followup_summary = _deliver_ready_whatsapp_share_links(
                request_json=request_json,
                args=args,
                limit=int(getattr(args, "audiobook_followup_limit", 3) or 3),
            )
            share_link_sent += int(followup_summary.get("sent") or 0)
            reply_sent += int(followup_summary.get("sent") or 0)
            errors += int(followup_summary.get("errors") or 0)
        except Exception as exc:
            errors += 1
            followup_summary = {"attempted": 0, "sent": 0, "errors": 1, "reason": type(exc).__name__}

    status = "pass" if errors == 0 else "partial"
    if not bool(args.dry_run):
        _record_conversation_fallback_run(
            args=args,
            state=state,
            conversation_fallback=conversation_fallback,
            processed=processed,
            epub_processed=epub_processed,
            voice_text_processed=voice_text_processed,
            status_processed=status_processed,
            reply_sent=reply_sent,
            share_link_sent=share_link_sent,
            voice_sample_sent=voice_sample_sent,
        )
        state["session_ref"] = session_ref
        state["updated_at"] = _now_iso()
        state["last_run"] = {
            "candidate_count": len(candidates),
            "conversation_fallback_audiobook_source_candidate_count": int(
                conversation_fallback.get("audiobook_source_candidate_count")
                or conversation_fallback.get("epub_candidate_count")
                or 0
            ),
            "conversation_fallback_attempted": bool(conversation_fallback.get("attempted")),
            "conversation_fallback_epub_candidate_count": int(conversation_fallback.get("epub_candidate_count") or 0),
            "conversation_fallback_message_count": int(conversation_fallback.get("message_count") or 0),
            "conversation_fallback_status": str(conversation_fallback.get("status") or ""),
            "audiobook_source_candidate_count": len(audiobook_source_candidates),
            "epub_candidate_count": len(audiobook_source_candidates),
            "errors": errors,
            "freeform_inbox_by_heyy_ai_key": dict(inbox_observability.get("freeform_by_heyy_ai_key") or {}),
            "freeform_inbox_message_count": int(inbox_observability.get("freeform_message_count") or 0),
            "freeform_reply_sent": freeform_reply_sent,
            "inbox_message_count": inbox_message_count,
            "inbound_message_count": int(inbox_observability.get("inbound_message_count") or 0),
            "message_count": len(messages),
            "processed": processed,
            "reply_sent": reply_sent,
            "status": status,
            "status_candidate_count": len(status_candidates),
            "status_processed": status_processed,
            "telegram_summary": telegram_summary,
            "voice_text_candidate_count": len(voice_text_candidates),
            "voice_text_processed": voice_text_processed,
        }
        _save_state(state_path, state)

    return {
        "status": status,
        "session_ref": session_ref,
        "message_count": len(messages),
        "inbox_message_count": inbox_message_count,
        "inbound_message_count": int(inbox_observability.get("inbound_message_count") or 0),
        "freeform_inbox_message_count": int(inbox_observability.get("freeform_message_count") or 0),
        "freeform_inbox_by_heyy_ai_key": dict(inbox_observability.get("freeform_by_heyy_ai_key") or {}),
        "freeform_reply_sent": freeform_reply_sent,
        "conversation_fallback": conversation_fallback,
        "candidate_count": len(candidates),
        "audiobook_source_candidate_count": len(audiobook_source_candidates),
        "epub_candidate_count": len(audiobook_source_candidates),
        "voice_text_candidate_count": len(voice_text_candidates),
        "status_candidate_count": len(status_candidates),
        "processed": processed,
        "epub_processed": epub_processed,
        "voice_text_processed": voice_text_processed,
        "status_processed": status_processed,
        "skipped_processed": skipped_processed,
        "dry_run_candidates": dry_run_candidates,
        "reply_sent": reply_sent,
        "voice_sample_sent": voice_sample_sent,
        "share_link_sent": share_link_sent,
        "errors": errors,
        "telegram_summary": telegram_summary,
        "resume_summary": resume_summary,
        "followup_summary": followup_summary,
        "status_counts": status_counts,
        "state_file_present": bool(str(state_path)),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process WhatsApp Web audiobook source intake and selected button callbacks.")
    parser.add_argument("--session-api-base-url", default=_env("EA_WHATSAPP_WEB_SESSION_API_BASE_URL", DEFAULT_SESSION_API_BASE_URL))
    parser.add_argument("--session-ref", default=_env("EA_WHATSAPP_WEB_DEFAULT_SESSION_REF", DEFAULT_SESSION_REF))
    parser.add_argument("--session-api-token", default=_env("EA_WHATSAPP_WEB_SESSION_API_TOKEN"))
    parser.add_argument("--auth-header-name", default=_env("EA_WHATSAPP_WEB_SESSION_AUTH_HEADER_NAME", "Authorization"))
    parser.add_argument("--auth-header-prefix", default=os.environ.get("EA_WHATSAPP_WEB_SESSION_AUTH_HEADER_PREFIX", "Bearer "))
    parser.add_argument("--timeout-seconds", type=float, default=float(_env("EA_WHATSAPP_WEB_SESSION_REQUEST_TIMEOUT_SECONDS", "30") or "30"))
    parser.add_argument("--take", type=int, default=int(_env("EA_WHATSAPP_WEB_ACTION_MESSAGE_TAKE", "100") or "100"))
    parser.add_argument("--state-file", default=_env("EA_WHATSAPP_WEB_ACTION_STATE_FILE", DEFAULT_STATE_FILE))
    parser.add_argument(
        "--conversation-fallback-enabled",
        action=argparse.BooleanOptionalAction,
        default=_env("EA_WHATSAPP_WEB_ACTION_CONVERSATION_FALLBACK_ENABLED", "1").lower() in {"1", "true", "yes", "on"},
    )
    parser.add_argument(
        "--conversation-fallback-take",
        type=int,
        default=int(_env("EA_WHATSAPP_WEB_ACTION_CONVERSATION_FALLBACK_TAKE", "25") or "25"),
    )
    parser.add_argument(
        "--conversation-fallback-message-limit",
        type=int,
        default=int(_env("EA_WHATSAPP_WEB_ACTION_CONVERSATION_FALLBACK_MESSAGE_LIMIT", "25") or "25"),
    )
    parser.add_argument(
        "--conversation-fallback-fetch-timeout-ms",
        type=int,
        default=int(_env("EA_WHATSAPP_WEB_ACTION_CONVERSATION_FALLBACK_FETCH_TIMEOUT_MS", "15000") or "15000"),
    )
    parser.add_argument(
        "--conversation-fallback-fetch-concurrency",
        type=int,
        default=int(_env("EA_WHATSAPP_WEB_ACTION_CONVERSATION_FALLBACK_FETCH_CONCURRENCY", "6") or "6"),
    )
    parser.add_argument(
        "--conversation-fallback-noop-cooldown-seconds",
        type=int,
        default=int(
            _env(
                "EA_WHATSAPP_WEB_ACTION_CONVERSATION_FALLBACK_NOOP_COOLDOWN_SECONDS",
                str(DEFAULT_CONVERSATION_FALLBACK_NOOP_COOLDOWN_SECONDS),
            )
            or str(DEFAULT_CONVERSATION_FALLBACK_NOOP_COOLDOWN_SECONDS)
        ),
    )
    parser.add_argument(
        "--conversation-fallback-noop-max-cooldown-seconds",
        type=int,
        default=int(
            _env(
                "EA_WHATSAPP_WEB_ACTION_CONVERSATION_FALLBACK_NOOP_MAX_COOLDOWN_SECONDS",
                str(DEFAULT_CONVERSATION_FALLBACK_NOOP_MAX_COOLDOWN_SECONDS),
            )
            or str(DEFAULT_CONVERSATION_FALLBACK_NOOP_MAX_COOLDOWN_SECONDS)
        ),
    )
    parser.add_argument(
        "--telegram-summary-enabled",
        action=argparse.BooleanOptionalAction,
        default=_env("EA_WHATSAPP_WEB_TG_SUMMARY_ENABLED", "0").lower() in {"1", "true", "yes", "on"},
    )
    parser.add_argument(
        "--telegram-summary-every",
        type=int,
        default=int(_env("EA_WHATSAPP_WEB_TG_SUMMARY_EVERY", "5") or "5"),
    )
    parser.add_argument(
        "--telegram-summary-chat-id",
        default=_env("EA_WHATSAPP_WEB_TG_SUMMARY_CHAT_ID", _env("EA_TELEGRAM_DEFAULT_CHAT_ID")),
    )
    parser.add_argument(
        "--telegram-summary-bot-token",
        default=_env("EA_WHATSAPP_WEB_TG_SUMMARY_BOT_TOKEN", _env("EA_TELEGRAM_BOT_TOKEN", _env("TELEGRAM_BOT_TOKEN"))),
    )
    parser.add_argument(
        "--telegram-summary-timeout-seconds",
        type=float,
        default=float(_env("EA_WHATSAPP_WEB_TG_SUMMARY_TIMEOUT_SECONDS", "15") or "15"),
    )
    parser.add_argument(
        "--telegram-summary-heyy-ai-keys",
        default=_env("EA_WHATSAPP_WEB_TG_SUMMARY_HEYY_AI_KEYS", DEFAULT_TELEGRAM_SUMMARY_HEYY_AI_KEYS),
    )
    parser.add_argument(
        "--telegram-summary-scope-label",
        default=_env("EA_WHATSAPP_WEB_TG_SUMMARY_SCOPE_LABEL", DEFAULT_TELEGRAM_SUMMARY_SCOPE_LABEL),
    )
    parser.add_argument(
        "--reply-heyy-ai-key",
        default=_env("EA_WHATSAPP_WEB_ACTION_REPLY_HEYY_AI_KEY", DEFAULT_ACTION_REPLY_HEYY_AI_KEY),
    )
    parser.add_argument(
        "--reply-heyy-ai-name",
        default=_env("EA_WHATSAPP_WEB_ACTION_REPLY_HEYY_AI_NAME", DEFAULT_ACTION_REPLY_HEYY_AI_NAME),
    )
    parser.add_argument(
        "--reply-pre-reply-delay-min-seconds",
        type=int,
        default=int(
            _env(
                "EA_WHATSAPP_WEB_ACTION_REPLY_PRE_REPLY_DELAY_MIN_SECONDS",
                str(DEFAULT_ACTION_REPLY_PRE_REPLY_DELAY_MIN_SECONDS),
            )
            or str(DEFAULT_ACTION_REPLY_PRE_REPLY_DELAY_MIN_SECONDS)
        ),
    )
    parser.add_argument(
        "--reply-pre-reply-delay-max-seconds",
        type=int,
        default=int(
            _env(
                "EA_WHATSAPP_WEB_ACTION_REPLY_PRE_REPLY_DELAY_MAX_SECONDS",
                str(DEFAULT_ACTION_REPLY_PRE_REPLY_DELAY_MAX_SECONDS),
            )
            or str(DEFAULT_ACTION_REPLY_PRE_REPLY_DELAY_MAX_SECONDS)
        ),
    )
    parser.add_argument(
        "--reply-quiet-hours-start-hour",
        type=int,
        default=int(
            _env(
                "EA_WHATSAPP_WEB_ACTION_REPLY_QUIET_HOURS_START_HOUR",
                str(DEFAULT_ACTION_REPLY_QUIET_HOURS_START_HOUR),
            )
            or str(DEFAULT_ACTION_REPLY_QUIET_HOURS_START_HOUR)
        ),
    )
    parser.add_argument(
        "--reply-quiet-hours-end-hour",
        type=int,
        default=int(
            _env(
                "EA_WHATSAPP_WEB_ACTION_REPLY_QUIET_HOURS_END_HOUR",
                str(DEFAULT_ACTION_REPLY_QUIET_HOURS_END_HOUR),
            )
            or str(DEFAULT_ACTION_REPLY_QUIET_HOURS_END_HOUR)
        ),
    )
    parser.add_argument(
        "--reply-typing-delay-ms",
        type=int,
        default=int(
            _env("EA_WHATSAPP_WEB_ACTION_REPLY_TYPING_DELAY_MS", str(DEFAULT_ACTION_REPLY_TYPING_DELAY_MS))
            or str(DEFAULT_ACTION_REPLY_TYPING_DELAY_MS)
        ),
    )
    parser.add_argument(
        "--reply-typing-delay-ms-per-character",
        type=int,
        default=int(
            _env(
                "EA_WHATSAPP_WEB_ACTION_REPLY_TYPING_DELAY_MS_PER_CHARACTER",
                str(DEFAULT_ACTION_REPLY_TYPING_DELAY_MS_PER_CHARACTER),
            )
            or str(DEFAULT_ACTION_REPLY_TYPING_DELAY_MS_PER_CHARACTER)
        ),
    )
    parser.add_argument(
        "--reply-typing-status-enabled",
        action=argparse.BooleanOptionalAction,
        default=_env("EA_WHATSAPP_WEB_ACTION_REPLY_TYPING_STATUS_ENABLED", "1").lower() in {"1", "true", "yes", "on"},
    )
    parser.add_argument(
        "--reply-use-sidecar-route-pacing",
        action=argparse.BooleanOptionalAction,
        default=_env("EA_WHATSAPP_WEB_ACTION_REPLY_USE_SIDECAR_ROUTE_PACING", "0").lower() in {"1", "true", "yes", "on"},
    )
    parser.add_argument(
        "--principal-id",
        default=_env(
            "EA_WHATSAPP_WEB_DEFAULT_PRINCIPAL_ID",
            _env("EA_WHATSAPP_DEFAULT_PRINCIPAL_ID", DEFAULT_AUDIOBOOK_PRINCIPAL_ID),
        ),
    )
    parser.add_argument(
        "--audiobook-resume-due",
        action=argparse.BooleanOptionalAction,
        default=_env("EA_WHATSAPP_AUDIOBOOK_RESUME_DUE", "0").lower() in {"1", "true", "yes", "on"},
    )
    parser.add_argument(
        "--audiobook-resume-due-limit",
        type=int,
        default=int(_env("EA_WHATSAPP_AUDIOBOOK_RESUME_DUE_LIMIT", "1") or "1"),
    )
    parser.add_argument(
        "--audiobook-followup-enabled",
        action=argparse.BooleanOptionalAction,
        default=_env("EA_WHATSAPP_AUDIOBOOK_FOLLOWUP_ENABLED", "1").lower() in {"1", "true", "yes", "on"},
    )
    parser.add_argument(
        "--audiobook-followup-limit",
        type=int,
        default=int(_env("EA_WHATSAPP_AUDIOBOOK_FOLLOWUP_LIMIT", "3") or "3"),
    )
    parser.add_argument(
        "--public-share-inline-buttons-enabled",
        action=argparse.BooleanOptionalAction,
        default=_env("EA_WHATSAPP_PUBLIC_SHARE_INLINE_BUTTONS_ENABLED", "0").lower() in {"1", "true", "yes", "on"},
    )
    parser.add_argument(
        "--stale-callback-reply-max-age-seconds",
        type=int,
        default=int(
            _env(
                "EA_WHATSAPP_WEB_ACTION_STALE_CALLBACK_REPLY_MAX_AGE_SECONDS",
                str(DEFAULT_STALE_CALLBACK_REPLY_MAX_AGE_SECONDS),
            )
            or str(DEFAULT_STALE_CALLBACK_REPLY_MAX_AGE_SECONDS)
        ),
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    report = build_report(parse_args())
    print(json.dumps(report, sort_keys=True))
    return 0 if str(report.get("status") or "") == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
