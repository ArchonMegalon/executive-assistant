from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Callable


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
    return f"https://api.telegram.org/file/bot{token}/{file}"


def _hydrate_instructional_video_transcript(payload: dict[str, object]) -> dict[str, object]:
    return dict(payload or {})


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
    payload = kwargs.get("payload")
    return dict(payload or {})


def run_local_resolvers(resolvers: list[TelegramLocalResolver] | tuple[TelegramLocalResolver, ...]) -> str:
    for resolver in resolvers:
        try:
            value = str(resolver.resolve() or "").strip()
        except Exception:
            value = ""
        if value:
            return value
    return ""
