from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Callable

try:
    from app.product import service as product_service
except Exception:  # pragma: no cover - import fallback for partial test environments
    product_service = SimpleNamespace(
        _pocket_audio_fallback_available=lambda: False,
        _pocket_retranscribe_from_audio_url=lambda **_kwargs: None,
    )

try:
    from app.services import photo_signal_analysis
except Exception:  # pragma: no cover - import fallback for partial test environments
    photo_signal_analysis = SimpleNamespace(
        analyze_photo_url=lambda **_kwargs: {"status": "unavailable", "summary": ""},
    )


@dataclass(frozen=True)
class TelegramLocalResolver:
    name: str
    resolve: Callable[[], str]


@dataclass(frozen=True)
class TelegramReplyMemoryState:
    active_object_map: dict[str, object] = field(default_factory=dict)
    intent_state: dict[str, object] = field(default_factory=dict)
    comparison_state: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class TelegramTurnContext:
    container: Any
    principal_id: str
    text: str
    payload: dict[str, object]
    bot_handle: str = ""
    preferred_onemin_labels: tuple[str, ...] = ()
    current_message_id: str = ""
    chat_id: str = ""
    normalized: str = ""
    lower: str = ""
    alpha_words: tuple[str, ...] = ()
    is_completion_cue: bool = False


@dataclass(frozen=True)
class TelegramTurnDecision:
    reply_text: str = ""
    schedule_async: bool = False
    async_text: str = ""
    async_message_id: str = ""
    async_payload: dict[str, object] | None = None
    suppress_async_ack: bool = False
    retry_budget: int = 1
    inline_buttons: list[list[tuple[str, str]]] | None = None


def _telegram_file_download_url(*, bot_token: str, file_id: str) -> str:
    token = urllib.parse.quote(str(bot_token or ""), safe="")
    file = urllib.parse.quote(str(file_id or ""), safe="")
    if not token or not file:
        raise RuntimeError("telegram_file_ref_missing")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/getFile?file_id={file}",
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not bool(payload.get("ok")):
        raise RuntimeError("telegram_getfile_failed")
    result = dict(payload.get("result") or {})
    file_path = str(result.get("file_path") or "").strip()
    if not file_path:
        raise RuntimeError("telegram_getfile_path_missing")
    return f"https://api.telegram.org/file/bot{token}/{file_path.lstrip('/')}"


def _hydrate_instructional_video_transcript(payload: dict[str, object]) -> dict[str, object]:
    resolved = dict(payload or {})
    if str(resolved.get("video_transcript_text") or "").strip():
        return resolved
    download_url = str(resolved.get("video_download_url") or "").strip()
    if not download_url:
        return resolved
    transcript = _transcribe_media_url(
        download_url=download_url,
        file_id=str(resolved.get("video_file_id") or "").strip(),
        message_id=str(resolved.get("video_message_id") or "").strip(),
        title="Telegram video audio",
    )
    if transcript["status"] == "ok":
        resolved["video_transcript_text"] = transcript["text"]
        resolved["video_transcription_status"] = "ok"
        resolved["transcript_metadata"] = transcript["metadata"]
    else:
        resolved["video_transcription_status"] = transcript["status"]
        if transcript["error_code"]:
            resolved["video_transcription_error_code"] = transcript["error_code"]
    return resolved


def build_turn_context(
    *,
    container: Any,
    principal_id: str,
    text: str,
    payload: dict[str, object] | None = None,
    bot_handle: str = "",
    preferred_onemin_labels: tuple[str, ...] = (),
    current_message_id: str = "",
    chat_id: str = "",
    completion_cue_predicate: Callable[[str], bool] | None = None,
) -> TelegramTurnContext:
    normalized = " ".join(str(text or "").split())
    lower = normalized.lower()
    alpha_words = tuple(re.findall(r"[a-zA-Z0-9_]+", lower))
    is_completion_cue = bool(completion_cue_predicate(normalized)) if completion_cue_predicate else False
    return TelegramTurnContext(
        container=container,
        principal_id=str(principal_id or ""),
        text=str(text or ""),
        payload=dict(payload or {}),
        bot_handle=str(bot_handle or ""),
        preferred_onemin_labels=tuple(preferred_onemin_labels or ()),
        current_message_id=str(current_message_id or ""),
        chat_id=str(chat_id or ""),
        normalized=normalized,
        lower=lower,
        alpha_words=alpha_words,
        is_completion_cue=is_completion_cue,
    )


def resolve_telegram_message_payload(*args, **kwargs) -> dict[str, object]:
    payload = dict(kwargs.get("payload") or {})
    bot_token = str(kwargs.get("bot_token") or "").strip()
    allow_video_transcription = bool(kwargs.get("allow_video_transcription", True))
    kind = str(payload.get("kind") or "").strip().lower()
    if kind not in {"voice", "audio", "video", "photo"}:
        return payload

    metadata = dict(payload.get("message_metadata") or {})
    file_id = str(metadata.get("file_id") or payload.get("file_id") or "").strip()
    message_id = str(payload.get("message_id") or metadata.get("message_id") or "").strip()
    duration = _safe_float(metadata.get("duration") or payload.get("duration") or 0)
    text = str(payload.get("text") or "").strip()

    if kind in {"voice", "audio"}:
        if _duration_over_limit(duration):
            payload["transcription_status"] = "skipped"
            payload["transcription_error_code"] = "duration_limit"
            return payload
        download_url = _resolve_download_url(bot_token=bot_token, file_id=file_id, metadata=metadata)
        if not download_url:
            payload["transcription_status"] = "failed"
            payload["transcription_error_code"] = "telegram_file_ref_missing"
            return payload
        metadata.pop("download_url", None)
        transcript = _transcribe_media_url(
            download_url=download_url,
            file_id=file_id,
            message_id=message_id,
            title="Telegram voice message",
        )
        payload["message_metadata"] = metadata
        payload["transcription_status"] = transcript["status"]
        if transcript["error_code"]:
            payload["transcription_error_code"] = transcript["error_code"]
        if transcript["status"] == "ok":
            payload["text"] = _truncate_transcript(transcript["text"])
            payload["transcript_metadata"] = transcript["metadata"]
        return payload

    if kind == "video":
        download_url = _resolve_download_url(bot_token=bot_token, file_id=file_id, metadata=metadata)
        if download_url:
            metadata["download_url"] = download_url
        payload["message_metadata"] = metadata
        if not allow_video_transcription:
            payload["transcription_status"] = "deferred"
            return payload
        if _duration_over_limit(duration):
            payload["transcription_status"] = "skipped"
            payload["transcription_error_code"] = "duration_limit"
            return payload
        if not download_url:
            payload["transcription_status"] = "failed"
            payload["transcription_error_code"] = "telegram_file_ref_missing"
            return payload
        transcript = _transcribe_media_url(
            download_url=download_url,
            file_id=file_id,
            message_id=message_id,
            title="Telegram video audio",
        )
        payload["transcription_status"] = transcript["status"]
        if transcript["error_code"]:
            payload["transcription_error_code"] = transcript["error_code"]
        if transcript["status"] == "ok":
            payload["video_transcript_text"] = transcript["text"]
            payload["transcript_metadata"] = transcript["metadata"]
        if text:
            payload["text"] = text
        return payload

    if kind == "photo":
        download_url = _resolve_download_url(bot_token=bot_token, file_id=file_id, metadata=metadata)
        if download_url:
            metadata["download_url"] = download_url
        payload["message_metadata"] = metadata
        if not download_url:
            payload["photo_analysis_status"] = "failed"
            payload["photo_analysis_error_code"] = "telegram_file_ref_missing"
            return payload
        try:
            analysis = dict(photo_signal_analysis.analyze_photo_url(photo_url=download_url))
        except Exception as exc:
            payload["photo_analysis_status"] = "failed"
            payload["photo_analysis_error_code"] = _error_code(exc)
            return payload
        status = str(analysis.get("status") or "analyzed").strip().lower() or "analyzed"
        payload["photo_analysis_status"] = status
        payload["photo_analysis"] = analysis
        summary = str(analysis.get("summary") or "").strip()
        if summary:
            payload["analysis_summary"] = summary
            payload["text"] = f"{text}\n\nPhoto analysis: {summary}".strip()
        return payload

    return payload


def run_local_resolvers(resolvers: list[TelegramLocalResolver] | tuple[TelegramLocalResolver, ...]) -> str:
    for resolver in resolvers:
        try:
            value = str(resolver.resolve() or "").strip()
        except Exception:
            value = ""
        if value:
            return value
    return ""


def _resolve_download_url(*, bot_token: str, file_id: str, metadata: dict[str, object]) -> str:
    existing = str(metadata.get("download_url") or "").strip()
    if existing:
        return existing
    if not bot_token or not file_id:
        return ""
    try:
        return _telegram_file_download_url(bot_token=bot_token, file_id=file_id)
    except Exception:
        return ""


def _transcribe_media_url(*, download_url: str, file_id: str, message_id: str, title: str) -> dict[str, object]:
    if not bool(product_service._pocket_audio_fallback_available()):
        return {"status": "unavailable", "text": "", "metadata": {}, "error_code": "pocket_audio_unavailable"}
    try:
        result = product_service._pocket_retranscribe_from_audio_url(
            recording_id=message_id or file_id or "telegram-media",
            title=title,
            language=str(os.getenv("EA_TELEGRAM_AUDIO_TRANSCRIBE_LANGUAGE") or "auto").strip() or "auto",
            audio_download_url=download_url,
        )
    except Exception as exc:
        return {"status": "failed", "text": "", "metadata": {}, "error_code": _error_code(exc)}
    payload = dict(result or {})
    text = str(payload.get("transcript_text") or "").strip()
    if not text:
        return {"status": "failed", "text": "", "metadata": {}, "error_code": "transcript_empty"}
    metadata = dict(payload.get("transcript_metadata") or {})
    if file_id:
        metadata["telegram_file_id"] = file_id
    if message_id:
        metadata["telegram_message_id"] = message_id
    return {"status": "ok", "text": text, "metadata": metadata, "error_code": ""}


def _max_audio_transcribe_seconds() -> float:
    try:
        return max(float(str(os.getenv("EA_TELEGRAM_MAX_AUDIO_TRANSCRIBE_SECONDS") or "300").strip() or "300"), 0)
    except Exception:
        return 300.0


def _duration_over_limit(duration: float) -> bool:
    return bool(duration and _max_audio_transcribe_seconds() and duration > _max_audio_transcribe_seconds())


def _max_transcript_chars() -> int:
    try:
        return max(int(str(os.getenv("EA_TELEGRAM_MAX_TRANSCRIPT_CHARS") or "4000").strip() or "4000"), 8)
    except Exception:
        return 4000


def _truncate_transcript(text: str) -> str:
    normalized = str(text or "").strip()
    limit = _max_transcript_chars()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: max(limit - 3, 0)].rstrip()}..."


def _safe_float(value: object) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _error_code(exc: Exception) -> str:
    raw = str(exc or "").strip()
    code = raw.split(":", 1)[0].strip().lower().replace(" ", "_")
    return code[:100] or exc.__class__.__name__.lower()
