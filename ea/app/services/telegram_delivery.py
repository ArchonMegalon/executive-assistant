from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import mimetypes
import os
import re
import subprocess
import tempfile
import time
import uuid
import urllib.parse
import urllib.request
from urllib.error import HTTPError, URLError
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from app.domain.models import ConnectorBinding
from app.services import google_oauth as google_oauth_service
from app.services.telegram_onboarding_service import TELEGRAM_IDENTITY_CONNECTOR

if TYPE_CHECKING:
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
_TELEGRAM_ERROR_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _telegram_max_attempts() -> int:
    return max(int(str(os.getenv("EA_TELEGRAM_DELIVERY_MAX_ATTEMPTS") or "3").strip() or "3"), 1)


def _telegram_retry_backoff_seconds() -> float:
    return max(float(str(os.getenv("EA_TELEGRAM_DELIVERY_RETRY_BACKOFF_SECONDS") or "1.5").strip() or "1.5"), 0.0)


def _telegram_upload_max_bytes() -> int:
    default_limit = 50 * 1024 * 1024
    return max(int(str(os.getenv("EA_TELEGRAM_UPLOAD_MAX_BYTES") or str(default_limit)).strip() or str(default_limit)), 1)


def _telegram_env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _telegram_csv_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = str(os.getenv(name) or "").strip()
    if not raw:
        return default
    values = [item.strip() for item in raw.replace(";", ",").split(",") if item.strip()]
    return tuple(values) or default


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
                raise RuntimeError(_telegram_api_error_code(method=method, body=body))
            result = body.get("result")
            return dict(result) if isinstance(result, dict) else {}
        except Exception as exc:
            last_error = exc
            error_code = _telegram_api_error_code_for_exception(method=method, exc=exc)
            if attempt >= _telegram_max_attempts() or not _telegram_error_retryable(error_code):
                raise RuntimeError(error_code) from exc
            if attempt >= _telegram_max_attempts():
                break
            time.sleep(_telegram_retry_backoff_seconds() * attempt)
    raise RuntimeError(_telegram_api_error_code_for_exception(method=method, exc=last_error)) from last_error


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
                raise RuntimeError(_telegram_api_error_code(method=method, body=body))
            return dict(body.get("result") or {})
        except Exception as exc:
            last_error = exc
            error_code = _telegram_api_error_code_for_exception(method=method, exc=exc)
            if attempt >= _telegram_max_attempts() or not _telegram_error_retryable(error_code):
                raise RuntimeError(error_code) from exc
            if attempt >= _telegram_max_attempts():
                break
            time.sleep(_telegram_retry_backoff_seconds() * attempt)
    raise RuntimeError(_telegram_api_error_code_for_exception(method=method, exc=last_error)) from last_error


def _telegram_api_error_code(method: str, *, body: object) -> str:
    prefix = f"telegram_{str(method or '').strip().lower() or 'request'}"
    if not isinstance(body, dict):
        return f"{prefix}_failed"
    raw_status = body.get("error_code")
    try:
        status_code = int(raw_status)
    except Exception:
        status_code = 0
    detail = _telegram_error_slug(body.get("description") or body.get("message") or body.get("error"))
    if status_code > 0:
        return f"{prefix}_http_{status_code}" + (f":{detail}" if detail else "")
    if detail:
        return f"{prefix}_api_error:{detail}"
    return f"{prefix}_failed"


def _telegram_api_error_code_for_exception(method: str, exc: Exception | None) -> str:
    prefix = f"telegram_{str(method or '').strip().lower() or 'request'}"
    if exc is None:
        return f"{prefix}_failed"
    if isinstance(exc, RuntimeError):
        existing = str(exc or "").strip()
        if existing:
            return existing
    if isinstance(exc, HTTPError):
        body = _telegram_http_error_body(exc)
        if body:
            return _telegram_api_error_code(method, body=body)
        detail = _telegram_error_slug(getattr(exc, "reason", "") or getattr(exc, "msg", "") or "")
        return f"{prefix}_http_{int(exc.code or 0)}" + (f":{detail}" if detail else "")
    if isinstance(exc, URLError):
        detail = _telegram_error_slug(getattr(exc, "reason", "") or str(exc))
        return f"{prefix}_url_error" + (f":{detail}" if detail else "")
    detail = _telegram_error_slug(str(exc))
    return f"{prefix}_failed" + (f":{detail}" if detail else "")


def _telegram_http_error_body(exc: HTTPError) -> dict[str, object]:
    try:
        raw = exc.read()
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _telegram_error_slug(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return ""
    for prefix in ("bad request:", "forbidden:", "unauthorized:", "too many requests:"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :].strip()
    slug = _TELEGRAM_ERROR_SLUG_RE.sub("_", normalized).strip("_")
    return slug[:96]


def _telegram_error_retryable(error_code: str) -> bool:
    normalized = str(error_code or "").strip().lower()
    if not normalized:
        return True
    if "_http_429" in normalized:
        return True
    for status in ("400", "401", "403", "404"):
        if f"_http_{status}" in normalized:
            return False
    return True


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


def telegram_video_delivery_audio_policy() -> dict[str, object]:
    fallback_tts_enabled = _telegram_env_bool("EA_TELEGRAM_VIDEO_FALLBACK_TTS_ENABLED", True)
    fallback_tts_providers = list(
        _telegram_csv_env(
            "EA_TELEGRAM_VIDEO_FALLBACK_TTS_PROVIDERS",
            ("piper_fast",),
        )
    )
    return {
        "local_video_final_audio_probe_required": True,
        "remote_video_audio_probe_required": True,
        "fallback_audio_text_preferred_before_silence": True,
        "silent_track_is_last_resort": True,
        "fallback_tts_enabled_default": fallback_tts_enabled,
        "fallback_tts_providers": fallback_tts_providers,
    }


def _telegram_video_redacted_path(raw_url: str) -> str:
    parsed = urllib.parse.urlparse(str(raw_url or "").strip())
    path = str(parsed.path or "").strip()
    if not path:
        return ""
    if "/bot" in path:
        prefix, suffix = path.split("/bot", 1)
        tokenless_suffix = suffix.split("/", 1)[1] if "/" in suffix else ""
        if tokenless_suffix:
            return f"{prefix}/bot<redacted>/{tokenless_suffix}".replace("//", "/")
        return f"{prefix}/bot<redacted>".replace("//", "/")
    return path


def telegram_video_source_receipt_context(payload: dict[str, object]) -> dict[str, object]:
    source_video = dict(payload.get("source_video") or {}) if isinstance(payload.get("source_video"), dict) else {}
    raw_url = str(
        source_video.get("source_url")
        or payload.get("video_download_url")
        or payload.get("source_video_url")
        or ""
    ).strip()
    parsed = urllib.parse.urlparse(raw_url) if raw_url else None
    frame_paths = payload.get("source_video_reference_frame_paths")
    if isinstance(frame_paths, (list, tuple)):
        frame_count = len([item for item in frame_paths if str(item or "").strip()])
    else:
        frame_count = int(source_video.get("source_video_reference_frame_count") or 0)
    board_present = bool(
        str(payload.get("source_video_reference_board_path") or "").strip()
        or bool(source_video.get("source_video_reference_board_present"))
    )
    duration_seconds = payload.get("video_duration_seconds")
    if duration_seconds in {None, ""}:
        duration_seconds = source_video.get("source_video_duration_seconds")
    context = {
        "has_source_video": bool(raw_url),
        "source_url_raw_stored": False,
        "source_url_sha256": hashlib.sha256(raw_url.encode("utf-8")).hexdigest() if raw_url else "",
        "source_host": str(parsed.netloc or "").strip().lower() if parsed else "",
        "source_path_redacted": _telegram_video_redacted_path(raw_url),
        "source_video_duration_seconds": duration_seconds if duration_seconds not in {None, ""} else 0,
        "source_video_reference_board_present": board_present,
        "source_video_reference_frame_count": max(frame_count, 0),
    }
    for key, value in source_video.items():
        if key not in context and key not in {"source_url"}:
            context[key] = value
    return context


def _extract_video_ref(*, output_json: dict[str, object]) -> str:
    for key in ("asset_url", "download_url", "video_url", "asset_path"):
        value = str(output_json.get(key) or "").strip()
        if value and value.lower().split("?", 1)[0].endswith(_VIDEO_SUFFIXES):
            return value
    structured = dict(output_json.get("structured_output_json") or {})
    for key in ("asset_url", "download_url", "video_url", "asset_path", "browser_video_path"):
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


def _telegram_video_render_fallback_audio_path(*, source_path: Path, text: str, language: str) -> Path:
    normalized_text = " ".join(str(text or "").split()).strip()
    if not normalized_text:
        raise RuntimeError("telegram_video_fallback_audio_text_missing")
    raise RuntimeError("telegram_video_fallback_audio_tts_disabled_by_policy")


def _telegram_video_with_attached_audio(source_path: str | Path, rendered_audio_path: str | Path) -> tuple[str, Path]:
    ffmpeg_bin = str(os.getenv("EA_FFMPEG_BIN") or "ffmpeg").strip() or "ffmpeg"
    source = Path(source_path).expanduser().resolve()
    audio = Path(rendered_audio_path).expanduser().resolve()
    fd, raw_path = tempfile.mkstemp(prefix="ea-telegram-video-with-audio-", suffix=".mp4")
    os.close(fd)
    output_path = Path(raw_path)
    completed = subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-i",
            str(source),
            "-i",
            str(audio),
            "-filter_complex",
            "[1:a]apad[a]",
            "-map",
            "0:v:0",
            "-map",
            "[a]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            "-movflags",
            "+faststart",
            str(output_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=max(int(str(os.getenv("EA_TELEGRAM_VIDEO_NORMALIZE_TIMEOUT_SECONDS") or "180").strip() or "180"), 30),
    )
    if completed.returncode != 0 or not output_path.exists():
        with contextlib.suppress(FileNotFoundError):
            output_path.unlink()
        raise RuntimeError("telegram_video_add_audio_failed")
    return str(output_path), output_path


def _telegram_video_with_silent_audio(source_path: str | Path) -> tuple[str, Path]:
    ffmpeg_bin = str(os.getenv("EA_FFMPEG_BIN") or "ffmpeg").strip() or "ffmpeg"
    source = Path(source_path).expanduser().resolve()
    fd, raw_path = tempfile.mkstemp(prefix="ea-telegram-video-silent-audio-", suffix=".mp4")
    os.close(fd)
    output_path = Path(raw_path)
    completed = subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-i",
            str(source),
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            "-movflags",
            "+faststart",
            str(output_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=max(int(str(os.getenv("EA_TELEGRAM_VIDEO_NORMALIZE_TIMEOUT_SECONDS") or "180").strip() or "180"), 30),
    )
    if completed.returncode != 0 or not output_path.exists():
        with contextlib.suppress(FileNotFoundError):
            output_path.unlink()
        raise RuntimeError("telegram_video_add_audio_failed")
    return str(output_path), output_path


def _telegram_video_with_fallback_audio(
    source_path: str,
    audio_ref: str = "",
    fallback_audio_text: str = "",
    fallback_audio_language: str = "",
) -> tuple[str, Path]:
    normalized_source_path = Path(str(source_path or "").strip()).expanduser()
    if not normalized_source_path.is_file():
        raise RuntimeError("telegram_video_source_path_missing")
    normalized_audio_ref = Path(str(audio_ref or "").strip()).expanduser() if str(audio_ref or "").strip() else None
    if normalized_audio_ref is not None and normalized_audio_ref.is_file() and _telegram_video_has_audio(str(normalized_audio_ref)):
        return _telegram_video_with_attached_audio(normalized_source_path, normalized_audio_ref)
    rendered_audio_path: Path | None = None
    if str(fallback_audio_text or "").strip() and telegram_video_delivery_audio_policy().get("fallback_tts_enabled_default") is True:
        try:
            rendered_audio_path = _telegram_video_render_fallback_audio_path(
                source_path=normalized_source_path,
                text=str(fallback_audio_text or "").strip(),
                language=str(fallback_audio_language or "en").strip() or "en",
            )
            return _telegram_video_with_attached_audio(normalized_source_path, rendered_audio_path)
        finally:
            if rendered_audio_path is not None:
                with contextlib.suppress(FileNotFoundError):
                    rendered_audio_path.unlink()
    return _telegram_video_with_silent_audio(normalized_source_path)


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
    return google_oauth_service._principal_alias_candidates(
        container=None,
        principal_ids=(
            str(principal_id or "").strip(),
            str(os.getenv("EA_TELEGRAM_DEFAULT_PRINCIPAL_ID") or "").strip(),
            str(os.getenv("EA_DEFAULT_PRINCIPAL_ID") or "").strip(),
        ),
        include_local_user=True,
    )


def resolve_primary_telegram_binding(tool_runtime: "ToolRuntimeService", *, principal_id: str) -> ConnectorBinding | None:
    from app.services import proactive_telegram_binding

    def _sort_key(item: tuple[int, ConnectorBinding]) -> tuple[int, int, int, str]:
        candidate_index, binding = item
        metadata = dict(binding.auth_metadata_json or {})
        chat_ref = str(metadata.get("default_chat_ref") or binding.external_account_ref or "").strip()
        numeric = 1 if chat_ref.isdigit() else 0
        plausible_numeric = 1 if numeric and int(chat_ref) > 1000 else 0
        return (plausible_numeric, numeric, -candidate_index, str(binding.updated_at or ""))

    ranked_candidates: list[tuple[int, ConnectorBinding]] = []
    for candidate_index, binding_principal_id in enumerate(_telegram_binding_principal_candidates(principal_id)):
        rows = tool_runtime.list_connector_bindings(binding_principal_id, limit=200)
        for row in rows:
            if str(row.connector_name or "").strip() != TELEGRAM_IDENTITY_CONNECTOR:
                continue
            if str(row.status or "").strip().lower() != "enabled":
                continue
            metadata = dict(row.auth_metadata_json or {})
            chat_ref = str(metadata.get("default_chat_ref") or row.external_account_ref or "").strip()
            if not chat_ref:
                continue
            ranked_candidates.append((candidate_index, row))
    ranked_candidates.sort(key=_sort_key, reverse=True)
    if len(ranked_candidates) > 1:
        for _candidate_index, row in ranked_candidates:
            metadata = dict(row.auth_metadata_json or {})
            chat_ref = str(metadata.get("default_chat_ref") or row.external_account_ref or "").strip()
            bot_key = str(metadata.get("bot_key") or "default").strip() or "default"
            token = str(dict(_telegram_bot_registry().get(bot_key) or {}).get("token") or "").strip()
            if token and proactive_telegram_binding._telegram_chat_reachable(chat_id=chat_ref, token=token):
                return row
    if ranked_candidates:
        return ranked_candidates[0][1]
    return None


def send_telegram_chat_action_for_principal(
    tool_runtime: "ToolRuntimeService",
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
    tool_runtime: "ToolRuntimeService",
    *,
    principal_id: str,
    text: str,
    inline_buttons: list[list[tuple[str, str]]] | None = None,
    url_buttons: list[list[tuple[str, str]]] | None = None,
    disable_web_page_preview: bool = False,
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
        if disable_web_page_preview:
            payload["disable_web_page_preview"] = True
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
    tool_runtime: "ToolRuntimeService",
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
    tool_runtime: "ToolRuntimeService",
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


def record_telegram_video_delivery_receipt(
    channel_runtime,
    *,
    principal_id: str,
    chat_id: str,
    source_message_id: str,
    provider: str,
    status: str,
    source_payload: dict[str, object],
    message_ids: list[object] | tuple[object, ...] | None = None,
    error: str = "",
    sidecar: dict[str, object] | None = None,
) -> dict[str, object]:
    payload = {
        "receipt_type": "telegram_video_delivery",
        "chat_id": str(chat_id or "").strip(),
        "source_message_id": str(source_message_id or "").strip(),
        "provider": str(provider or "").strip(),
        "status": str(status or "").strip(),
        "delivery_kind": "video",
        "telegram_method": "sendVideo",
        "message_ids": [str(item or "").strip() for item in list(message_ids or []) if str(item or "").strip()],
        "error": str(error or "").strip(),
        "source_video": telegram_video_source_receipt_context(dict(source_payload or {})),
    }
    if sidecar:
        payload["sidecar"] = dict(sidecar)
    dedupe_key = ":".join(
        item
        for item in (
            "telegram_video_delivery",
            str(chat_id or "").strip(),
            str(source_message_id or "").strip(),
            str(provider or "").strip(),
            str(status or "").strip(),
            ",".join(payload["message_ids"]),
        )
        if item
    )
    if hasattr(channel_runtime, "ingest_observation"):
        channel_runtime.ingest_observation(
            principal_id=str(principal_id or "").strip(),
            channel="telegram",
            event_type="telegram.video_delivery_receipt",
            payload=payload,
            source_id=f"telegram:{str(chat_id or '').strip()}" if str(chat_id or "").strip() else "telegram",
            external_id=str(source_message_id or "").strip(),
            dedupe_key=dedupe_key,
        )
    return payload


def send_telegram_video_for_principal(
    tool_runtime: "ToolRuntimeService",
    *,
    principal_id: str,
    video_ref: str,
    audio_probe_ref: str = "",
    fallback_audio_text: str = "",
    fallback_audio_language: str = "",
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
    normalized_probe_ref = str(audio_probe_ref or "").strip()
    original_video_path = Path(normalized_video_ref).resolve() if Path(normalized_video_ref).is_file() else None
    effective_video_ref = normalized_video_ref
    temporary_video_path: Path | None = None
    video_has_audio = _telegram_video_has_audio(normalized_video_ref)
    probe_has_audio = _telegram_video_has_audio(normalized_probe_ref) if normalized_probe_ref else False
    if not video_has_audio:
        try:
            effective_video_ref, temporary_video_path = _telegram_video_with_fallback_audio(
                normalized_video_ref,
                audio_ref=normalized_probe_ref if probe_has_audio else "",
                fallback_audio_text=str(fallback_audio_text or "").strip(),
                fallback_audio_language=str(fallback_audio_language or "").strip(),
            )
        except Exception as exc:
            raise RuntimeError("telegram_video_audio_missing") from exc
        if not _telegram_video_has_audio(str(effective_video_ref or "").strip()):
            if temporary_video_path is not None and temporary_video_path.exists():
                with contextlib.suppress(FileNotFoundError):
                    temporary_video_path.unlink()
            raise RuntimeError("telegram_video_audio_missing")
    try:
        if Path(effective_video_ref).is_file():
            result = _telegram_send_multipart(
                token=token,
                method="sendVideo",
                fields={
                    "chat_id": chat_id,
                    "caption": _telegram_caption(caption),
                    "supports_streaming": "true",
                },
                file_field="video",
                file_path=effective_video_ref,
                content_type=_guess_content_type(effective_video_ref, fallback="video/mp4"),
            )
        else:
            if not _telegram_remote_ref_reachable(effective_video_ref):
                raise RuntimeError("telegram_video_unreachable")
            result = _telegram_send_json(
                token=token,
                method="sendVideo",
                payload={
                    "chat_id": chat_id,
                    "video": effective_video_ref,
                    "caption": _telegram_caption(caption),
                    "supports_streaming": True,
                },
            )
    finally:
        if temporary_video_path is not None and temporary_video_path.exists():
            if original_video_path is None or temporary_video_path.resolve() != original_video_path:
                with contextlib.suppress(FileNotFoundError):
                    temporary_video_path.unlink()
    return TelegramDeliveryReceipt(
        principal_id=str(principal_id or "").strip(),
        chat_id=chat_id,
        bot_key=bot_key,
        bot_handle=bot_handle,
        message_ids=tuple(value for value in (str(result.get("message_id") or ""),) if value),
    )


def send_telegram_audio_for_principal(
    tool_runtime: "ToolRuntimeService",
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
    tool_runtime: "ToolRuntimeService",
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
