from __future__ import annotations

import functools
import inspect
import json
import logging
import re
from typing import Any

LOG = logging.getLogger(__name__)

SAFE_SIMPLIFIED_COPY = "Delivered in simplified mode today. Visual formatting is temporarily unavailable."
SAFE_PLACEHOLDER_COPY = "Preparing your briefing in safe mode..."

FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("json_block", re.compile(r"(?s)^\s*[\[{].*[\]}]\s*$")),
    ("traceback", re.compile(r"(?m)^Traceback \(most recent call last\):")),
    ("exception", re.compile(r"(?m)^\s*[A-Za-z_][A-Za-z0-9_]*(Error|Exception):\s")),
    ("provider_trace", re.compile(r"(?i)\b(openai|anthropic|gemini|claude|gpt-4|gpt-5|mistral|xai|perplexity)\b.*\b(error|trace|payload|response|exception)\b")),
    ("template_id", re.compile(r"(?i)\btemplate[_ -]?id\b")),
    ("internal_identifier", re.compile(r"(?i)\b(ooda|delivery_sessions|repair_jobs|repair_attempts|sanitizer_audits|circuit_breakers|mum brain|llm gateway|account[_ -]?id|component[_ -]?name)\b")),
    ("secret_like", re.compile(r"\b(sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z\-_]{20,}|xox[baprs]-[A-Za-z0-9-]{10,})\b")),
)


def _normalize(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (dict, list, tuple)):
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        except Exception:
            return str(value).strip()
    return str(value).strip()


def detect_forbidden_pattern(value: Any) -> str | None:
    text = _normalize(value)
    if not text:
        return None
    for name, pattern in FORBIDDEN_PATTERNS:
        if pattern.search(text):
            return name
    return None


def sanitize_telegram_text(value: Any, *, placeholder: bool = False) -> str:
    text = _normalize(value)
    if not text:
        return text
    if detect_forbidden_pattern(text):
        return SAFE_PLACEHOLDER_COPY if placeholder else SAFE_SIMPLIFIED_COPY
    return text


def _sanitize_args(args: tuple[Any, ...], kwargs: dict[str, Any], key: str, *, placeholder: bool) -> tuple[tuple[Any, ...], dict[str, Any]]:
    if key in kwargs:
        kwargs = dict(kwargs)
        kwargs[key] = sanitize_telegram_text(kwargs.get(key), placeholder=placeholder)
        return args, kwargs

    # Common bound-method layout: (self, chat_id, text, ...)
    if key == 'text' and len(args) >= 3:
        tmp = list(args)
        tmp[2] = sanitize_telegram_text(tmp[2], placeholder=placeholder)
        return tuple(tmp), kwargs

    # Common caption layout: (self, chat_id, photo, caption, ...)
    if key == 'caption' and len(args) >= 4:
        tmp = list(args)
        tmp[3] = sanitize_telegram_text(tmp[3], placeholder=placeholder)
        return tuple(tmp), kwargs

    return args, kwargs


def _wrap_method(fn, key: str, *, placeholder: bool = False):
    if getattr(fn, '_ea_safe_wrapped', False):
        return fn

    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def async_wrapper(*args, **kwargs):
            a, k = _sanitize_args(args, kwargs, key, placeholder=placeholder)
            return await fn(*a, **k)
        async_wrapper._ea_safe_wrapped = True  # type: ignore[attr-defined]
        return async_wrapper

    @functools.wraps(fn)
    def sync_wrapper(*args, **kwargs):
        a, k = _sanitize_args(args, kwargs, key, placeholder=placeholder)
        return fn(*a, **k)
    sync_wrapper._ea_safe_wrapped = True  # type: ignore[attr-defined]
    return sync_wrapper


def install_telegram_safety() -> list[str]:
    patched: list[str] = []

    try:
        from telegram import Bot, Message  # type: ignore

        for name, key in (
            ('send_message', 'text'),
            ('edit_message_text', 'text'),
            ('send_photo', 'caption'),
            ('send_document', 'caption'),
        ):
            if hasattr(Bot, name):
                setattr(Bot, name, _wrap_method(getattr(Bot, name), key))
        if hasattr(Message, 'reply_text'):
            Message.reply_text = _wrap_method(Message.reply_text, 'text')
        patched.append('python-telegram-bot')
    except Exception:
        pass

    try:
        from aiogram import Bot as AioBot  # type: ignore

        for name, key in (
            ('send_message', 'text'),
            ('edit_message_text', 'text'),
            ('send_photo', 'caption'),
            ('send_document', 'caption'),
        ):
            if hasattr(AioBot, name):
                setattr(AioBot, name, _wrap_method(getattr(AioBot, name), key))
        patched.append('aiogram')
    except Exception:
        pass

    if patched:
        LOG.info('EA Telegram safety installed for: %s', ', '.join(patched))
    else:
        LOG.info('EA Telegram safety bootstrap loaded; no supported Telegram SDK detected for monkeypatching')
    return patched
