from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import os
import subprocess
import time
import uuid
import urllib.request
from urllib.error import HTTPError, URLError
from dataclasses import dataclass
from pathlib import Path

from app.domain.models import ConnectorBinding
from app.services.telegram_onboarding_service import TELEGRAM_IDENTITY_CONNECTOR
from app.services.tool_runtime import ToolRuntimeService

_TELEGRAM_MESSAGE_LIMIT = 4000
_TELEGRAM_CAPTION_LIMIT = 1024
_VIDEO_SUFFIXES = (".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv")
_AUDIO_SUFFIXES = (".mp3", ".m4a", ".wav", ".ogg", ".flac", ".aac", ".opus")
_DOCUMENT_SUFFIXES = (".pdf", ".txt", ".md", ".json", ".csv", ".rtf", ".doc", ".docx")
_TELEGRAM_REMOTE_MEDIA_TIMEOUT = 30
_TELEGRAM_FEEDBACK_KEY_ALIASES = {
    "like_property": "lp",
    "dislike_property": "dp",
}
_TELEGRAM_FEEDBACK_KEY_BY_ALIAS = {value: key for key, value in _TELEGRAM_FEEDBACK_KEY_ALIASES.items()}


def _telegram_max_attempts() -> int:
    return max(int(str(os.getenv("EA_TELEGRAM_DELIVERY_MAX_ATTEMPTS") or "3").strip() or "3"), 1)


def _telegram_retry_backoff_seconds() -> float:
    return max(float(str(os.getenv("EA_TELEGRAM_DELIVERY_RETRY_BACKOFF_SECONDS") or "1.5").strip() or "1.5"), 0.0)


def _telegram_upload_max_bytes() -> int:
    default_limit = 50 * 1024 * 1024
    return max(int(str(os.getenv("EA_TELEGRAM_UPLOAD_MAX_BYTES") or str(default_limit)).strip() or str(default_limit)), 1)


@dataclass(frozen=True)
class TelegramDeliveryReceipt:
    principal_id: str
    chat_id: str
    bot_key: str
    bot_handle: str
    message_ids: tuple[str, ...]


def _telegram_bot_registry() -> dict[str, dict[str, object]]:
    registry: dict[str, dict[str, object]] = {}
    raw_registry = str(os.getenv("EA_TELEGRAM_BOT_REGISTRY_JSON") or "").strip()
    if raw_registry:
        try:
            parsed = json.loads(raw_registry)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            for raw_key, raw_value in parsed.items():
                key = str(raw_key or "").strip()
                if not key or not isinstance(raw_value, dict):
                    continue
                token = str(raw_value.get("token") or "").strip()
                if not token:
                    continue
                registry[key] = {
                    "token": token,
                    "handle": str(raw_value.get("handle") or "").strip(),
                }
    default_token = str(os.getenv("EA_TELEGRAM_BOT_TOKEN") or "").strip()
    if default_token:
        registry.setdefault(
            "default",
            {
                "token": default_token,
                "handle": str(os.getenv("EA_TELEGRAM_BOT_HANDLE") or "").strip(),
            },
        )
    return registry


def _chunk_telegram_text(text: str) -> tuple[str, ...]:
    normalized = str(text or "").strip()
    if not normalized:
        return ()
    if len(normalized) <= _TELEGRAM_MESSAGE_LIMIT:
        return (normalized,)
    chunks: list[str] = []
    remaining = normalized
    while remaining:
        if len(remaining) <= _TELEGRAM_MESSAGE_LIMIT:
            chunks.append(remaining)
            break
        split_at = remaining.rfind("\n\n", 0, _TELEGRAM_MESSAGE_LIMIT)
        if split_at < 0:
            split_at = remaining.rfind("\n", 0, _TELEGRAM_MESSAGE_LIMIT)
        if split_at < 0:
            split_at = remaining.rfind(" ", 0, _TELEGRAM_MESSAGE_LIMIT)
        if split_at < 0:
            split_at = _TELEGRAM_MESSAGE_LIMIT
        chunk = remaining[:split_at].strip()
        if not chunk:
            chunk = remaining[:_TELEGRAM_MESSAGE_LIMIT].strip()
            split_at = _TELEGRAM_MESSAGE_LIMIT
        chunks.append(chunk)
        remaining = remaining[split_at:].strip()
    return tuple(chunk for chunk in chunks if chunk)


def _telegram_caption(text: str) -> str:
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized:
        return ""
    if len(normalized) <= _TELEGRAM_CAPTION_LIMIT:
        return normalized
    return f"{normalized[: _TELEGRAM_CAPTION_LIMIT - 3].rstrip()}..."


def _telegram_send_json(*, token: str, method: str, payload: dict[str, object], timeout: int = 30) -> dict[str, object]:
    last_error: Exception | None = None
    for attempt in range(1, _telegram_max_attempts() + 1):
        try:
            request = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/{method}",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
            if not bool(body.get("ok")):
                raise RuntimeError(f"telegram_{method.lower()}_failed")
            return dict(body.get("result") or {})
        except Exception as exc:
            last_error = exc
            if attempt >= _telegram_max_attempts():
                break
            time.sleep(_telegram_retry_backoff_seconds() * attempt)
    raise RuntimeError(f"telegram_{method.lower()}_failed") from last_error


def _telegram_send_multipart(
    *,
    token: str,
    method: str,
    fields: dict[str, str],
    file_field: str,
    file_path: str,
    content_type: str = "application/octet-stream",
    timeout: int = 120,
) -> dict[str, object]:
    file_size = Path(file_path).stat().st_size
    if file_size > _telegram_upload_max_bytes():
        raise RuntimeError("telegram_upload_too_large")
    boundary = f"----ea-telegram-{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for key, value in fields.items():
        parts.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )
    upload_name = Path(file_path).name
    parts.extend(
        [
            f"--{boundary}\r\n".encode("utf-8"),
            (
                f'Content-Disposition: form-data; name="{file_field}"; filename="{upload_name}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8"),
            Path(file_path).read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    request_body = b"".join(parts)
    last_error: Exception | None = None
    for attempt in range(1, _telegram_max_attempts() + 1):
        try:
            request = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/{method}",
                data=request_body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
            if not bool(body.get("ok")):
                raise RuntimeError(f"telegram_{method.lower()}_failed")
            return dict(body.get("result") or {})
        except Exception as exc:
            last_error = exc
            if attempt >= _telegram_max_attempts():
                break
            time.sleep(_telegram_retry_backoff_seconds() * attempt)
    raise RuntimeError(f"telegram_{method.lower()}_failed") from last_error


def _telegram_video_has_audio(video_ref: str) -> bool:
    normalized = str(video_ref or "").strip()
    if not normalized:
        return False
    ffprobe_bin = str(os.getenv("EA_FFPROBE_BIN") or "ffprobe").strip() or "ffprobe"
    timeout_seconds = max(int(str(os.getenv("EA_TELEGRAM_VIDEO_PROBE_TIMEOUT_SECONDS") or "30").strip() or "30"), 1)
    try:
        completed = subprocess.run(
            [
                ffprobe_bin,
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "json",
                normalized,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except Exception:
        return False
    if completed.returncode != 0:
        return False
    try:
        payload = json.loads(str(completed.stdout or "{}"))
    except json.JSONDecodeError:
        return False
    streams = payload.get("streams") or []
    if not isinstance(streams, list):
        return False
    return any(str(dict(stream).get("codec_type") or "").strip().lower() == "audio" for stream in streams if isinstance(stream, dict))


def _extract_video_ref(*, output_json: dict[str, object]) -> str:
    for key in ("asset_url", "download_url", "video_url"):
        value = str(output_json.get(key) or "").strip()
        if value and value.lower().split("?", 1)[0].endswith(_VIDEO_SUFFIXES):
            return value
    structured = dict(output_json.get("structured_output_json") or {})
    for key in ("asset_url", "download_url", "video_url"):
        value = str(structured.get(key) or "").strip()
        if value and value.lower().split("?", 1)[0].endswith(_VIDEO_SUFFIXES):
            return value
    for value in list(output_json.get("asset_urls") or []) + list(structured.get("asset_urls") or []):
        normalized = str(value or "").strip()
        if normalized and normalized.lower().split("?", 1)[0].endswith(_VIDEO_SUFFIXES):
            return normalized
    return ""


def _extract_audio_ref(*, output_json: dict[str, object]) -> str:
    for key in ("asset_url", "download_url", "audio_url"):
        value = str(output_json.get(key) or "").strip()
        if value and value.lower().split("?", 1)[0].endswith(_AUDIO_SUFFIXES):
            return value
    structured = dict(output_json.get("structured_output_json") or {})
    for key in ("asset_url", "download_url", "audio_url"):
        value = str(structured.get(key) or "").strip()
        if value and value.lower().split("?", 1)[0].endswith(_AUDIO_SUFFIXES):
            return value
    for value in list(output_json.get("asset_urls") or []) + list(structured.get("asset_urls") or []):
        normalized = str(value or "").strip()
        if normalized and normalized.lower().split("?", 1)[0].endswith(_AUDIO_SUFFIXES):
            return normalized
    return ""


def _extract_document_ref(*, output_json: dict[str, object]) -> str:
    for key in ("asset_url", "download_url", "document_url"):
        value = str(output_json.get(key) or "").strip()
        if value and value.lower().split("?", 1)[0].endswith(_DOCUMENT_SUFFIXES):
            return value
    structured = dict(output_json.get("structured_output_json") or {})
    for key in ("asset_url", "download_url", "document_url"):
        value = str(structured.get(key) or "").strip()
        if value and value.lower().split("?", 1)[0].endswith(_DOCUMENT_SUFFIXES):
            return value
    for value in list(output_json.get("asset_urls") or []) + list(structured.get("asset_urls") or []):
        normalized = str(value or "").strip()
        if normalized and normalized.lower().split("?", 1)[0].endswith(_DOCUMENT_SUFFIXES):
            return normalized
    return ""


def _guess_content_type(file_ref: str, *, fallback: str = "application/octet-stream") -> str:
    normalized = str(file_ref or "").strip()
    guessed, _ = mimetypes.guess_type(normalized)
    return str(guessed or fallback).strip() or fallback


def _telegram_remote_ref_reachable(file_ref: str) -> bool:
    normalized = str(file_ref or "").strip()
    if not normalized.lower().startswith(("http://", "https://")):
        return False
    request = urllib.request.Request(normalized, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=_TELEGRAM_REMOTE_MEDIA_TIMEOUT) as response:
            return int(getattr(response, "status", 200) or 200) < 400
    except HTTPError as exc:
        status_code = int(getattr(exc, "code", 500) or 500)
        if status_code == 405:
            try:
                fallback_request = urllib.request.Request(normalized, method="GET")
                with urllib.request.urlopen(fallback_request, timeout=_TELEGRAM_REMOTE_MEDIA_TIMEOUT) as response:
                    return int(getattr(response, "status", 200) or 200) < 400
            except Exception:
                return False
        return status_code < 400
    except (URLError, ValueError):
        return False


def _telegram_binding_principal_candidates(principal_id: str) -> tuple[str, ...]:
    ordered: list[str] = []
    for candidate in (
        str(principal_id or "").strip(),
        str(os.getenv("EA_TELEGRAM_DEFAULT_PRINCIPAL_ID") or "").strip(),
        str(os.getenv("EA_DEFAULT_PRINCIPAL_ID") or "").strip(),
        "local-user",
    ):
        if candidate and candidate not in ordered:
            ordered.append(candidate)
    return tuple(ordered)


def resolve_primary_telegram_binding(tool_runtime: ToolRuntimeService, *, principal_id: str) -> ConnectorBinding | None:
    def _sort_key(item: ConnectorBinding) -> tuple[int, int, str]:
        metadata = dict(item.auth_metadata_json or {})
        chat_ref = str(metadata.get("default_chat_ref") or item.external_account_ref or "").strip()
        numeric = 1 if chat_ref.isdigit() else 0
        plausible_numeric = 1 if numeric and int(chat_ref) > 1000 else 0
        return (plausible_numeric, numeric, str(item.updated_at or ""))

    for binding_principal_id in _telegram_binding_principal_candidates(principal_id):
        rows = tool_runtime.list_connector_bindings(binding_principal_id, limit=200)
        candidates: list[ConnectorBinding] = []
        for row in rows:
            if str(row.connector_name or "").strip() != TELEGRAM_IDENTITY_CONNECTOR:
                continue
            if str(row.status or "").strip().lower() != "enabled":
                continue
            metadata = dict(row.auth_metadata_json or {})
            chat_ref = str(metadata.get("default_chat_ref") or row.external_account_ref or "").strip()
            if not chat_ref:
                continue
            candidates.append(row)
        candidates.sort(key=_sort_key, reverse=True)
        if candidates:
            return candidates[0]
    return None


def send_telegram_chat_action_for_principal(
    tool_runtime: ToolRuntimeService,
    *,
    principal_id: str,
    action: str = "typing",
) -> TelegramDeliveryReceipt:
    binding = resolve_primary_telegram_binding(tool_runtime, principal_id=principal_id)
    if binding is None:
        raise RuntimeError("telegram_binding_not_found")
    metadata = dict(binding.auth_metadata_json or {})
    bot_key = str(metadata.get("bot_key") or "default").strip() or "default"
    bot_handle = str(metadata.get("bot_handle") or "").strip()
    chat_id = str(metadata.get("default_chat_ref") or binding.external_account_ref or "").strip()
    if not chat_id:
        raise RuntimeError("telegram_chat_ref_missing")
    config = dict(_telegram_bot_registry().get(bot_key) or {})
    token = str(config.get("token") or "").strip()
    if not token:
        raise RuntimeError("telegram_bot_token_missing")
    if not bot_handle:
        bot_handle = str(config.get("handle") or "").strip()
    normalized_action = str(action or "typing").strip().lower() or "typing"
    allowed_actions = {
        "typing",
        "upload_photo",
        "record_video",
        "upload_video",
        "record_voice",
        "upload_voice",
        "upload_document",
        "choose_sticker",
        "find_location",
        "record_video_note",
        "upload_video_note",
    }
    if normalized_action not in allowed_actions:
        raise RuntimeError("telegram_chat_action_invalid")
    _telegram_send_json(
        token=token,
        method="sendChatAction",
        payload={"chat_id": chat_id, "action": normalized_action},
    )
    return TelegramDeliveryReceipt(
        principal_id=str(principal_id or "").strip(),
        chat_id=chat_id,
        bot_key=bot_key,
        bot_handle=bot_handle,
        message_ids=(),
    )


def send_telegram_message_for_principal(
    tool_runtime: ToolRuntimeService,
    *,
    principal_id: str,
    text: str,
    inline_buttons: list[list[tuple[str, str]]] | None = None,
    url_buttons: list[list[tuple[str, str]]] | None = None,
) -> TelegramDeliveryReceipt:
    binding = resolve_primary_telegram_binding(tool_runtime, principal_id=principal_id)
    if binding is None:
        raise RuntimeError("telegram_binding_not_found")
    metadata = dict(binding.auth_metadata_json or {})
    bot_key = str(metadata.get("bot_key") or "default").strip() or "default"
    bot_handle = str(metadata.get("bot_handle") or "").strip()
    chat_id = str(metadata.get("default_chat_ref") or binding.external_account_ref or "").strip()
    if not chat_id:
        raise RuntimeError("telegram_chat_ref_missing")
    config = dict(_telegram_bot_registry().get(bot_key) or {})
    token = str(config.get("token") or "").strip()
    if not token:
        raise RuntimeError("telegram_bot_token_missing")
    if not bot_handle:
        bot_handle = str(config.get("handle") or "").strip()
    message_ids: list[str] = []
    for chunk in _chunk_telegram_text(text):
        payload: dict[str, object] = {"chat_id": chat_id, "text": chunk}
        keyboard_rows: list[list[dict[str, str]]] = []
        for row in list(inline_buttons or []):
            buttons = [
                {"text": str(label or "").strip(), "callback_data": str(callback_data or "").strip()}
                for label, callback_data in row
                if str(label or "").strip() and str(callback_data or "").strip()
            ]
            if buttons:
                keyboard_rows.append(buttons)
        for row in list(url_buttons or []):
            buttons = [
                {"text": str(label or "").strip(), "url": str(url or "").strip()}
                for label, url in row
                if str(label or "").strip() and str(url or "").strip()
            ]
            if buttons:
                keyboard_rows.append(buttons)
        if keyboard_rows:
            payload["reply_markup"] = {"inline_keyboard": keyboard_rows}
        result = _telegram_send_json(
            token=token,
            method="sendMessage",
            payload=payload,
        )
        message_ids.append(str(result.get("message_id") or ""))
    return TelegramDeliveryReceipt(
        principal_id=str(principal_id or "").strip(),
        chat_id=chat_id,
        bot_key=bot_key,
        bot_handle=bot_handle,
        message_ids=tuple(value for value in message_ids if value),
    )


def send_telegram_photo_for_principal(
    tool_runtime: ToolRuntimeService,
    *,
    principal_id: str,
    photo_ref: str,
    caption: str = "",
    inline_buttons: list[list[tuple[str, str]]] | None = None,
    url_buttons: list[list[tuple[str, str]]] | None = None,
) -> TelegramDeliveryReceipt:
    binding = resolve_primary_telegram_binding(tool_runtime, principal_id=principal_id)
    if binding is None:
        raise RuntimeError("telegram_binding_not_found")
    metadata = dict(binding.auth_metadata_json or {})
    bot_key = str(metadata.get("bot_key") or "default").strip() or "default"
    bot_handle = str(metadata.get("bot_handle") or "").strip()
    chat_id = str(metadata.get("default_chat_ref") or binding.external_account_ref or "").strip()
    if not chat_id:
        raise RuntimeError("telegram_chat_ref_missing")
    config = dict(_telegram_bot_registry().get(bot_key) or {})
    token = str(config.get("token") or "").strip()
    if not token:
        raise RuntimeError("telegram_bot_token_missing")
    if not bot_handle:
        bot_handle = str(config.get("handle") or "").strip()
    normalized_photo_ref = str(photo_ref or "").strip()
    if not normalized_photo_ref:
        raise RuntimeError("telegram_photo_ref_missing")
    keyboard_rows: list[list[dict[str, str]]] = []
    for row in list(inline_buttons or []):
        buttons = [
            {"text": str(label or "").strip(), "callback_data": str(callback_data or "").strip()}
            for label, callback_data in row
            if str(label or "").strip() and str(callback_data or "").strip()
        ]
        if buttons:
            keyboard_rows.append(buttons)
    for row in list(url_buttons or []):
        buttons = [
            {"text": str(label or "").strip(), "url": str(url or "").strip()}
            for label, url in row
            if str(label or "").strip() and str(url or "").strip()
        ]
        if buttons:
            keyboard_rows.append(buttons)
    reply_markup = {"inline_keyboard": keyboard_rows} if keyboard_rows else None
    if Path(normalized_photo_ref).is_file():
        fields = {"chat_id": chat_id, "caption": _telegram_caption(caption)}
        if reply_markup:
            fields["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
        result = _telegram_send_multipart(
            token=token,
            method="sendPhoto",
            fields=fields,
            file_field="photo",
            file_path=normalized_photo_ref,
            content_type=_guess_content_type(normalized_photo_ref, fallback="image/jpeg"),
        )
    else:
        if not _telegram_remote_ref_reachable(normalized_photo_ref):
            raise RuntimeError("telegram_photo_unreachable")
        payload: dict[str, object] = {
            "chat_id": chat_id,
            "photo": normalized_photo_ref,
            "caption": _telegram_caption(caption),
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        result = _telegram_send_json(
            token=token,
            method="sendPhoto",
            payload=payload,
        )
    return TelegramDeliveryReceipt(
        principal_id=str(principal_id or "").strip(),
        chat_id=chat_id,
        bot_key=bot_key,
        bot_handle=bot_handle,
        message_ids=tuple(value for value in (str(result.get("message_id") or ""),) if value),
    )


def _telegram_feedback_secret(*, bot_token: str) -> str:
    return str(os.getenv("EA_TELEGRAM_FEEDBACK_SECRET") or "").strip() or str(bot_token or "").strip()


def _telegram_feedback_signature(
    *,
    secret: str,
    notification_key: str,
    feedback_key: str,
    chat_id: str,
    expires_at: int,
) -> str:
    payload = "|".join(
        (
            str(notification_key or "").strip(),
            str(feedback_key or "").strip(),
            str(chat_id or "").strip(),
            str(int(expires_at)),
        )
    )
    return hmac.new(
        str(secret or "").encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:12]


def build_telegram_feedback_callback_data_for_principal(
    tool_runtime: ToolRuntimeService,
    *,
    principal_id: str,
    notification_key: str,
    feedback_key: str,
    expires_at: int,
) -> str:
    binding = resolve_primary_telegram_binding(tool_runtime, principal_id=principal_id)
    if binding is None:
        return ""
    metadata = dict(binding.auth_metadata_json or {})
    bot_key = str(metadata.get("bot_key") or "default").strip() or "default"
    chat_id = str(metadata.get("default_chat_ref") or binding.external_account_ref or "").strip()
    config = dict(_telegram_bot_registry().get(bot_key) or {})
    token = str(config.get("token") or "").strip()
    secret = _telegram_feedback_secret(bot_token=token)
    if not secret or not chat_id:
        return ""
    encoded_feedback_key = str(_TELEGRAM_FEEDBACK_KEY_ALIASES.get(str(feedback_key or "").strip(), str(feedback_key or "").strip())).strip()
    signature = _telegram_feedback_signature(
        secret=secret,
        notification_key=notification_key,
        feedback_key=encoded_feedback_key,
        chat_id=chat_id,
        expires_at=int(expires_at),
    )
    return f"fb|{str(notification_key or '').strip()}|{encoded_feedback_key}|{chat_id}|{int(expires_at)}|{signature}"


def decode_telegram_feedback_callback_data(
    *,
    bot_token: str,
    callback_data: str,
    chat_id: str,
) -> dict[str, object]:
    normalized = str(callback_data or "").strip()
    parts = normalized.split("|")
    if len(parts) != 6 or parts[0] != "fb":
        return {"ok": False, "reason": "invalid_format"}
    _, notification_key, encoded_feedback_key, encoded_chat_id, expires_at_raw, signature = parts
    if str(encoded_chat_id or "").strip() != str(chat_id or "").strip():
        return {"ok": False, "reason": "chat_mismatch"}
    try:
        expires_at = int(str(expires_at_raw or "").strip())
    except Exception:
        return {"ok": False, "reason": "invalid_expiry"}
    if expires_at < int(time.time()):
        return {"ok": False, "reason": "expired"}
    secret = _telegram_feedback_secret(bot_token=bot_token)
    if not secret:
        return {"ok": False, "reason": "missing_secret"}
    expected_signature = _telegram_feedback_signature(
        secret=secret,
        notification_key=notification_key,
        feedback_key=encoded_feedback_key,
        chat_id=str(chat_id or "").strip(),
        expires_at=expires_at,
    )
    if not hmac.compare_digest(str(signature or "").strip(), expected_signature):
        return {"ok": False, "reason": "invalid_signature"}
    feedback_key = str(_TELEGRAM_FEEDBACK_KEY_BY_ALIAS.get(str(encoded_feedback_key or "").strip(), str(encoded_feedback_key or "").strip())).strip()
    return {
        "ok": True,
        "notification_key": str(notification_key or "").strip(),
        "feedback_key": str(feedback_key or "").strip(),
        "chat_id": str(chat_id or "").strip(),
        "expires_at": expires_at,
    }


def send_telegram_video_for_principal(
    tool_runtime: ToolRuntimeService,
    *,
    principal_id: str,
    video_ref: str,
    audio_probe_ref: str = "",
    caption: str = "",
) -> TelegramDeliveryReceipt:
    binding = resolve_primary_telegram_binding(tool_runtime, principal_id=principal_id)
    if binding is None:
        raise RuntimeError("telegram_binding_not_found")
    metadata = dict(binding.auth_metadata_json or {})
    bot_key = str(metadata.get("bot_key") or "default").strip() or "default"
    bot_handle = str(metadata.get("bot_handle") or "").strip()
    chat_id = str(metadata.get("default_chat_ref") or binding.external_account_ref or "").strip()
    if not chat_id:
        raise RuntimeError("telegram_chat_ref_missing")
    config = dict(_telegram_bot_registry().get(bot_key) or {})
    token = str(config.get("token") or "").strip()
    if not token:
        raise RuntimeError("telegram_bot_token_missing")
    if not bot_handle:
        bot_handle = str(config.get("handle") or "").strip()
    normalized_video_ref = str(video_ref or "").strip()
    if not normalized_video_ref:
        raise RuntimeError("telegram_video_ref_missing")
    normalized_probe_ref = str(audio_probe_ref or normalized_video_ref).strip()
    has_audio = _telegram_video_has_audio(normalized_probe_ref)
    if Path(normalized_video_ref).is_file():
        method = "sendVideo" if has_audio else "sendDocument"
        file_field = "video" if has_audio else "document"
        result = _telegram_send_multipart(
            token=token,
            method=method,
            fields={
                "chat_id": chat_id,
                "caption": _telegram_caption(caption),
                **({"supports_streaming": "true"} if has_audio else {}),
            },
            file_field=file_field,
            file_path=normalized_video_ref,
            content_type=_guess_content_type(normalized_video_ref, fallback="video/mp4"),
        )
    else:
        if not has_audio:
            raise RuntimeError("telegram_video_audio_missing")
        if not _telegram_remote_ref_reachable(normalized_video_ref):
            raise RuntimeError("telegram_video_unreachable")
        result = _telegram_send_json(
            token=token,
            method="sendVideo",
            payload={
                "chat_id": chat_id,
                "video": normalized_video_ref,
                "caption": _telegram_caption(caption),
                "supports_streaming": True,
            },
        )
    return TelegramDeliveryReceipt(
        principal_id=str(principal_id or "").strip(),
        chat_id=chat_id,
        bot_key=bot_key,
        bot_handle=bot_handle,
        message_ids=tuple(value for value in (str(result.get("message_id") or ""),) if value),
    )


def send_telegram_audio_for_principal(
    tool_runtime: ToolRuntimeService,
    *,
    principal_id: str,
    audio_ref: str,
    caption: str = "",
) -> TelegramDeliveryReceipt:
    binding = resolve_primary_telegram_binding(tool_runtime, principal_id=principal_id)
    if binding is None:
        raise RuntimeError("telegram_binding_not_found")
    metadata = dict(binding.auth_metadata_json or {})
    bot_key = str(metadata.get("bot_key") or "default").strip() or "default"
    bot_handle = str(metadata.get("bot_handle") or "").strip()
    chat_id = str(metadata.get("default_chat_ref") or binding.external_account_ref or "").strip()
    if not chat_id:
        raise RuntimeError("telegram_chat_ref_missing")
    config = dict(_telegram_bot_registry().get(bot_key) or {})
    token = str(config.get("token") or "").strip()
    if not token:
        raise RuntimeError("telegram_bot_token_missing")
    if not bot_handle:
        bot_handle = str(config.get("handle") or "").strip()
    normalized_audio_ref = str(audio_ref or "").strip()
    if not normalized_audio_ref:
        raise RuntimeError("telegram_audio_ref_missing")
    if Path(normalized_audio_ref).is_file():
        result = _telegram_send_multipart(
            token=token,
            method="sendAudio",
            fields={"chat_id": chat_id, "caption": _telegram_caption(caption)},
            file_field="audio",
            file_path=normalized_audio_ref,
            content_type=_guess_content_type(normalized_audio_ref, fallback="audio/mpeg"),
        )
    else:
        if not _telegram_remote_ref_reachable(normalized_audio_ref):
            raise RuntimeError("telegram_audio_unreachable")
        result = _telegram_send_json(
            token=token,
            method="sendAudio",
            payload={"chat_id": chat_id, "audio": normalized_audio_ref, "caption": _telegram_caption(caption)},
        )
    return TelegramDeliveryReceipt(
        principal_id=str(principal_id or "").strip(),
        chat_id=chat_id,
        bot_key=bot_key,
        bot_handle=bot_handle,
        message_ids=tuple(value for value in (str(result.get("message_id") or ""),) if value),
    )


def send_telegram_document_for_principal(
    tool_runtime: ToolRuntimeService,
    *,
    principal_id: str,
    document_ref: str,
    caption: str = "",
) -> TelegramDeliveryReceipt:
    binding = resolve_primary_telegram_binding(tool_runtime, principal_id=principal_id)
    if binding is None:
        raise RuntimeError("telegram_binding_not_found")
    metadata = dict(binding.auth_metadata_json or {})
    bot_key = str(metadata.get("bot_key") or "default").strip() or "default"
    bot_handle = str(metadata.get("bot_handle") or "").strip()
    chat_id = str(metadata.get("default_chat_ref") or binding.external_account_ref or "").strip()
    if not chat_id:
        raise RuntimeError("telegram_chat_ref_missing")
    config = dict(_telegram_bot_registry().get(bot_key) or {})
    token = str(config.get("token") or "").strip()
    if not token:
        raise RuntimeError("telegram_bot_token_missing")
    if not bot_handle:
        bot_handle = str(config.get("handle") or "").strip()
    normalized_document_ref = str(document_ref or "").strip()
    if not normalized_document_ref:
        raise RuntimeError("telegram_document_ref_missing")
    if Path(normalized_document_ref).is_file():
        result = _telegram_send_multipart(
            token=token,
            method="sendDocument",
            fields={"chat_id": chat_id, "caption": _telegram_caption(caption)},
            file_field="document",
            file_path=normalized_document_ref,
            content_type=_guess_content_type(normalized_document_ref),
        )
    else:
        if not _telegram_remote_ref_reachable(normalized_document_ref):
            raise RuntimeError("telegram_document_unreachable")
        result = _telegram_send_json(
            token=token,
            method="sendDocument",
            payload={"chat_id": chat_id, "document": normalized_document_ref, "caption": _telegram_caption(caption)},
        )
    return TelegramDeliveryReceipt(
        principal_id=str(principal_id or "").strip(),
        chat_id=chat_id,
        bot_key=bot_key,
        bot_handle=bot_handle,
        message_ids=tuple(value for value in (str(result.get("message_id") or ""),) if value),
    )
