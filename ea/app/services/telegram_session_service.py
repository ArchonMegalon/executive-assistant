from __future__ import annotations

import dataclasses
import json
import os
import urllib.error
import urllib.request

from app.product import service as product_service


@dataclasses.dataclass(frozen=True)
class TelegramTurnDecision:
    reply_text: str = ""
    schedule_async: bool = False


@dataclasses.dataclass(frozen=True)
class TelegramReplyMemoryState:
    active_object_map: dict[str, str]
    intent_state: dict[str, object]
    comparison_state: dict[str, str]


@dataclasses.dataclass(frozen=True)
class TelegramTurnContext:
    container: object
    principal_id: str
    text: str
    payload: dict[str, object]
    bot_handle: str
    preferred_onemin_labels: tuple[str, ...]
    current_message_id: str
    chat_id: str
    normalized: str
    lower: str
    alpha_words: tuple[str, ...]
    is_completion_cue: bool


@dataclasses.dataclass(frozen=True)
class TelegramLocalResolver:
    name: str
    resolve: object


def build_turn_context(
    *,
    container: object,
    principal_id: str,
    text: str,
    payload: dict[str, object] | None,
    bot_handle: str,
    preferred_onemin_labels: tuple[str, ...],
    current_message_id: str,
    chat_id: str,
    completion_cue_predicate,
) -> TelegramTurnContext:
    normalized = str(text or "").strip()
    lower = normalized.lower()
    alpha_words = tuple(part for part in "".join(ch for ch in lower if ch.isalpha() or ch.isspace()).split() if part)
    return TelegramTurnContext(
        container=container,
        principal_id=principal_id,
        text=text,
        payload=dict(payload or {}),
        bot_handle=bot_handle,
        preferred_onemin_labels=preferred_onemin_labels,
        current_message_id=current_message_id,
        chat_id=chat_id,
        normalized=normalized,
        lower=lower,
        alpha_words=alpha_words,
        is_completion_cue=bool(completion_cue_predicate(normalized)),
    )


def run_local_resolvers(resolvers: list[TelegramLocalResolver]) -> str:
    for resolver in resolvers:
        reply = str(resolver.resolve() or "").strip()
        if reply:
            return reply
    return ""


def _telegram_file_download_url(*, bot_token: str, file_id: str) -> str:
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{str(bot_token or '').strip()}/getFile?file_id={str(file_id or '').strip()}",
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"telegram_getfile_http_{exc.code}:{detail[:200]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"telegram_getfile_unreachable:{exc.reason}") from exc
    if not isinstance(payload, dict) or not bool(payload.get("ok")):
        raise RuntimeError("telegram_getfile_failed")
    result = dict(payload.get("result") or {}) if isinstance(payload.get("result"), dict) else {}
    file_path = str(result.get("file_path") or "").strip()
    if not file_path:
        raise RuntimeError("telegram_getfile_missing_path")
    return f"https://api.telegram.org/file/bot{str(bot_token or '').strip()}/{file_path}"


def _telegram_max_audio_duration_seconds() -> int:
    raw = str(os.getenv("EA_TELEGRAM_MAX_AUDIO_TRANSCRIBE_SECONDS") or "300").strip()
    try:
        return max(int(float(raw or "300")), 1)
    except Exception:
        return 300


def _telegram_max_transcript_chars() -> int:
    raw = str(os.getenv("EA_TELEGRAM_MAX_TRANSCRIPT_CHARS") or "4000").strip()
    try:
        return max(int(float(raw or "4000")), 32)
    except Exception:
        return 4000


def resolve_telegram_message_payload(*, payload: dict[str, object], bot_token: str) -> dict[str, object]:
    resolved = dict(payload or {})
    kind = str(resolved.get("kind") or "").strip().lower()
    metadata = dict(resolved.get("message_metadata") or {})
    if kind not in {"voice", "audio"}:
        return resolved
    file_id = str(metadata.get("file_id") or "").strip()
    try:
        duration_seconds = int(float(str(metadata.get("duration") or "0").strip() or "0"))
    except Exception:
        duration_seconds = 0
    if duration_seconds and duration_seconds > _telegram_max_audio_duration_seconds():
        resolved["transcription_status"] = "skipped"
        resolved["transcription_error_code"] = "duration_limit"
        return resolved
    if not file_id or not str(bot_token or "").strip() or not product_service._pocket_audio_fallback_available():
        return resolved
    try:
        audio_url = _telegram_file_download_url(bot_token=bot_token, file_id=file_id)
        transcription = product_service._pocket_retranscribe_from_audio_url(
            recording_id=str(resolved.get("message_id") or file_id or "telegram-audio").strip(),
            title="Telegram voice message" if kind == "voice" else "Telegram audio message",
            language="de",
            audio_download_url=audio_url,
        )
    except Exception as exc:
        raw_error = str(exc or "").strip()
        error_code = raw_error.split(":", 1)[0].strip().lower().replace(" ", "_") or "transcription_failed"
        resolved["transcription_status"] = "failed"
        resolved["transcription_error_code"] = error_code[:80]
        return resolved
    transcript_text = str(dict(transcription or {}).get("transcript_text") or "").strip()
    if not transcript_text:
        resolved["transcription_status"] = "empty"
        return resolved
    max_chars = _telegram_max_transcript_chars()
    if len(transcript_text) > max_chars:
        transcript_text = transcript_text[:max_chars].rstrip()
        if " " in transcript_text:
            transcript_text = transcript_text.rsplit(" ", 1)[0].rstrip()
        transcript_text = transcript_text.rstrip(" ,;:.") + "..."
    transcript_metadata = dict(dict(transcription or {}).get("transcript_metadata") or {})
    transcript_metadata["telegram_file_id"] = file_id
    resolved["text"] = transcript_text
    resolved["transcription_status"] = "ok"
    resolved["transcript_metadata"] = transcript_metadata
    return resolved
