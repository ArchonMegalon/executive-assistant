from __future__ import annotations

import json
import os
import subprocess
import uuid
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from app.domain.models import ConnectorBinding
from app.services.telegram_onboarding_service import TELEGRAM_IDENTITY_CONNECTOR
from app.services.tool_runtime import ToolRuntimeService

_TELEGRAM_MESSAGE_LIMIT = 4000
_TELEGRAM_CAPTION_LIMIT = 1024
_VIDEO_SUFFIXES = (".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv")


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


def _telegram_send_multipart(
    *,
    token: str,
    method: str,
    fields: dict[str, str],
    file_field: str,
    file_path: str,
    timeout: int = 120,
) -> dict[str, object]:
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
                "Content-Type: video/mp4\r\n\r\n"
            ).encode("utf-8"),
            Path(file_path).read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=b"".join(parts),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not bool(body.get("ok")):
        raise RuntimeError(f"telegram_{method.lower()}_failed")
    return dict(body.get("result") or {})


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


def resolve_primary_telegram_binding(tool_runtime: ToolRuntimeService, *, principal_id: str) -> ConnectorBinding | None:
    rows = tool_runtime.list_connector_bindings(str(principal_id or "").strip(), limit=200)
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
    def _sort_key(item: ConnectorBinding) -> tuple[int, int, str]:
        metadata = dict(item.auth_metadata_json or {})
        chat_ref = str(metadata.get("default_chat_ref") or item.external_account_ref or "").strip()
        numeric = 1 if chat_ref.isdigit() else 0
        plausible_numeric = 1 if numeric and int(chat_ref) > 1000 else 0
        return (plausible_numeric, numeric, str(item.updated_at or ""))

    candidates.sort(key=_sort_key, reverse=True)
    return candidates[0] if candidates else None


def send_telegram_message_for_principal(
    tool_runtime: ToolRuntimeService,
    *,
    principal_id: str,
    text: str,
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
        result = _telegram_send_json(
            token=token,
            method="sendMessage",
            payload={"chat_id": chat_id, "text": chunk},
        )
        message_ids.append(str(result.get("message_id") or ""))
    return TelegramDeliveryReceipt(
        principal_id=str(principal_id or "").strip(),
        chat_id=chat_id,
        bot_key=bot_key,
        bot_handle=bot_handle,
        message_ids=tuple(value for value in message_ids if value),
    )


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
        )
    else:
        if not has_audio:
            raise RuntimeError("telegram_video_audio_missing")
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
