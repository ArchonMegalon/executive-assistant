from __future__ import annotations

import ast
import concurrent.futures
import hmac
import json
import os
import re
import time
import threading
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, Depends, Request
from fastapi import HTTPException
from pydantic import BaseModel, Field

from app.api.dependencies import RequestContext
from app.api.dependencies import get_container
from app.api.routes import responses as responses_route
from app.channels.telegram.adapter import TelegramObservationAdapter
from app.container import AppContainer
from app.product.service import build_product_service
from app.services.telegram_onboarding_service import TELEGRAM_IDENTITY_CONNECTOR, TELEGRAM_OFFICIAL_BOT_CONNECTOR

router = APIRouter(prefix="/v1/channels", tags=["channels"])
_telegram = TelegramObservationAdapter()
_SAFE_MATH_RE = re.compile(r"^[0-9\.\+\-\*\/\(\)\s=\?]+$")
_TELEGRAM_ASSISTANT_ACK = "Let me check that and get back to you here."
_TELEGRAM_ASYNC_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="telegram-ea")
_TELEGRAM_WEATHER_URL = "https://api.open-meteo.com/v1/forecast"


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
                    "bot_key": key,
                    "token": token,
                    "handle": str(raw_value.get("handle") or "").strip(),
                    "secret": str(raw_value.get("secret") or "").strip(),
                    "default_principal_id": str(raw_value.get("default_principal_id") or "").strip(),
                    "auto_bind_unknown_chat": bool(raw_value.get("auto_bind_unknown_chat")),
                    "preferred_onemin_labels": tuple(
                        str(item or "").strip()
                        for item in list(raw_value.get("preferred_onemin_labels") or [])
                        if str(item or "").strip()
                    ),
                }
    default_token = str(os.getenv("EA_TELEGRAM_BOT_TOKEN") or "").strip()
    if default_token:
        registry.setdefault(
            "default",
            {
                "bot_key": "default",
                "token": default_token,
                "handle": str(os.getenv("EA_TELEGRAM_BOT_HANDLE") or "").strip(),
                "secret": str(os.getenv("EA_TELEGRAM_INGEST_SECRET") or "").strip(),
                "default_principal_id": str(os.getenv("EA_TELEGRAM_DEFAULT_PRINCIPAL_ID") or "").strip(),
                "auto_bind_unknown_chat": _telegram_auto_bind_unknown_chat_enabled(),
                "preferred_onemin_labels": (),
            },
        )
    return registry


def _telegram_default_preferred_onemin_labels() -> tuple[str, ...]:
    raw = str(os.getenv("EA_TELEGRAM_RESPONSES_PREFERRED_ONEMIN_LABELS") or "").strip()
    if not raw:
        return ()
    labels: list[str] = []
    for item in raw.split(","):
        normalized = str(item or "").strip()
        if normalized and normalized not in labels:
            labels.append(normalized)
    return tuple(labels)


def _resolve_telegram_bot_config(*, bot_key: str = "", provided_secret: str = "", header_secret: str = "") -> dict[str, object]:
    registry = _telegram_bot_registry()
    normalized_key = str(bot_key or "").strip()
    if normalized_key:
        config = dict(registry.get(normalized_key) or {})
        if not config:
            raise HTTPException(status_code=404, detail="telegram_bot_not_found")
        return config
    if not registry:
        return {}
    for config in registry.values():
        secret = str(config.get("secret") or "").strip()
        if not secret:
            continue
        for candidate in (str(header_secret or "").strip(), str(provided_secret or "").strip()):
            if candidate and hmac.compare_digest(candidate, secret):
                return dict(config)
    return dict(registry.get("default") or next(iter(registry.values())))


def _require_telegram_ingest_secret(*, config: dict[str, object], provided: str, header_value: str) -> None:
    expected = str(config.get("secret") or os.getenv("EA_TELEGRAM_INGEST_SECRET") or "").strip()
    if not expected:
        return
    candidates = (str(header_value or "").strip(), str(provided or "").strip())
    for candidate in candidates:
        if candidate and hmac.compare_digest(candidate, expected):
            return
    raise HTTPException(status_code=403, detail="telegram_secret_invalid")


def _resolve_telegram_principal(container: AppContainer, chat_id: str, *, bot_key: str = "", bot_handle: str = "") -> str:
    normalized_chat_id = str(chat_id or "").strip()
    if not normalized_chat_id:
        return ""
    matches: list[str] = []
    for connector_name in (TELEGRAM_OFFICIAL_BOT_CONNECTOR, TELEGRAM_IDENTITY_CONNECTOR):
        for binding in container.tool_runtime.list_connector_bindings_for_connector(connector_name, limit=500):
            normalized_status = str(binding.status or "").strip().lower()
            if normalized_status in {"disabled", "inactive", "archived"}:
                continue
            metadata = dict(binding.auth_metadata_json or {})
            metadata_bot_key = str(metadata.get("bot_key") or "").strip()
            metadata_bot_handle = str(metadata.get("bot_handle") or "").strip()
            if bot_key and metadata_bot_key and metadata_bot_key != bot_key:
                continue
            if bot_handle and metadata_bot_handle and metadata_bot_handle != bot_handle:
                continue
            default_chat_ref = str(metadata.get("default_chat_ref") or "").strip()
            external_account_ref = str(binding.external_account_ref or "").strip()
            if normalized_chat_id in {default_chat_ref, external_account_ref}:
                matches.append(binding.principal_id)
    principals = sorted({principal_id for principal_id in matches if str(principal_id or "").strip()})
    if len(principals) == 1:
        return principals[0]
    if len(principals) > 1:
        raise HTTPException(status_code=409, detail="telegram_binding_ambiguous")
    return ""


def _telegram_default_principal_id() -> str:
    return str(os.getenv("EA_TELEGRAM_DEFAULT_PRINCIPAL_ID") or "").strip()


def _telegram_bot_handle() -> str:
    return str(os.getenv("EA_TELEGRAM_BOT_HANDLE") or "").strip()


def _telegram_auto_bind_unknown_chat_enabled() -> bool:
    normalized = str(os.getenv("EA_TELEGRAM_AUTO_BIND_UNKNOWN_CHAT") or "").strip().lower()
    return normalized in {"1", "true", "yes", "on"}


def _auto_bind_telegram_chat(container: AppContainer, chat_id: str, *, config: dict[str, object]) -> str:
    normalized_chat_id = str(chat_id or "").strip()
    principal_id = str(config.get("default_principal_id") or _telegram_default_principal_id() or "").strip()
    auto_bind = config.get("auto_bind_unknown_chat")
    if auto_bind is None:
        auto_bind_enabled = _telegram_auto_bind_unknown_chat_enabled()
    else:
        auto_bind_enabled = bool(auto_bind)
    if not normalized_chat_id or not principal_id or not auto_bind_enabled:
        return ""
    connector = container.tool_runtime.upsert_connector_binding(
        principal_id=principal_id,
        connector_name=TELEGRAM_IDENTITY_CONNECTOR,
        external_account_ref=normalized_chat_id,
        scope_json={"assistant_surfaces": ["dm"]},
        auth_metadata_json={
            "identity_mode": "bot_webhook",
            "history_mode": "future_only",
            "default_chat_ref": normalized_chat_id,
            "status": "enabled",
            "bot_handle": str(config.get("handle") or _telegram_bot_handle() or "").strip(),
            "bot_key": str(config.get("bot_key") or "").strip(),
            "auto_bound": True,
        },
        status="enabled",
    )
    return str(connector.principal_id or "").strip()


def _telegram_send_message(*, bot_token: str, chat_id: str, text: str) -> dict[str, object]:
    normalized_token = str(bot_token or "").strip()
    normalized_chat_id = str(chat_id or "").strip()
    normalized_text = str(text or "").strip()
    if not normalized_token or not normalized_chat_id or not normalized_text:
        return {}
    payload = json.dumps({"chat_id": normalized_chat_id, "text": normalized_text}).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{normalized_token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        timeout_seconds = max(float(str(os.getenv("EA_TELEGRAM_SEND_TIMEOUT_SECONDS") or "10").strip() or "10"), 1.0)
    except Exception:
        timeout_seconds = 10.0
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def _safe_math_answer(text: str) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    candidate = normalized.replace("?", "").replace("=", "").strip()
    if not candidate or not _SAFE_MATH_RE.fullmatch(normalized):
        return ""

    def _eval_node(node):  # type: ignore[no-untyped-def]
        if isinstance(node, ast.Expression):
            return _eval_node(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = _eval_node(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            left = _eval_node(node.left)
            right = _eval_node(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            return left / right
        raise ValueError("unsupported_math_expression")

    try:
        parsed = ast.parse(candidate, mode="eval")
        value = _eval_node(parsed)
    except Exception:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f"{candidate} = {value}"


def _recent_telegram_texts(container: AppContainer, *, principal_id: str, limit: int = 12) -> list[str]:
    rows = container.channel_runtime.list_recent_observations(limit=limit, principal_id=principal_id)
    texts: list[str] = []
    for row in rows:
        if str(row.channel or "").strip() != "telegram":
            continue
        payload = dict(row.payload or {})
        text = str(payload.get("text") or "").strip()
        if text:
            texts.append(text)
    return texts


def _recent_telegram_reply_texts(container: AppContainer, *, principal_id: str, limit: int = 12) -> list[str]:
    rows = container.channel_runtime.list_recent_observations(limit=limit, principal_id=principal_id)
    texts: list[str] = []
    for row in rows:
        if str(row.channel or "").strip() != "telegram":
            continue
        if str(row.event_type or "").strip() != "telegram.reply_sent":
            continue
        payload = dict(row.payload or {})
        text = str(payload.get("reply_text") or "").strip()
        if text:
            texts.append(text)
    return texts


def _telegram_reply_marker_dedupe_key(dedupe_key: str) -> str:
    normalized = str(dedupe_key or "").strip()
    return f"{normalized}:reply_sent" if normalized else ""


def _telegram_async_marker_dedupe_key(dedupe_key: str) -> str:
    normalized = str(dedupe_key or "").strip()
    return f"{normalized}:assistant_async_started" if normalized else ""


def _telegram_reply_already_sent(container: AppContainer, *, principal_id: str, dedupe_key: str) -> bool:
    marker = _telegram_reply_marker_dedupe_key(dedupe_key)
    if not marker:
        return False
    return container.channel_runtime.find_observation_by_dedupe(marker, principal_id=principal_id) is not None


def _record_telegram_reply_sent(
    container: AppContainer,
    *,
    principal_id: str,
    chat_id: str,
    dedupe_key: str,
    reply_text: str,
    message_id: str,
) -> None:
    marker = _telegram_reply_marker_dedupe_key(dedupe_key)
    if not marker:
        return
    container.channel_runtime.ingest_observation(
        principal_id=principal_id,
        channel="telegram",
        event_type="telegram.reply_sent",
        payload={
            "chat_id": chat_id,
            "reply_text": reply_text,
            "message_id": message_id,
            "dedupe_key": dedupe_key,
        },
        source_id=f"telegram:{chat_id}" if chat_id else "telegram",
        external_id=str(message_id or "").strip(),
        dedupe_key=marker,
    )


def _telegram_async_already_started(container: AppContainer, *, principal_id: str, dedupe_key: str) -> bool:
    marker = _telegram_async_marker_dedupe_key(dedupe_key)
    if not marker:
        return False
    return container.channel_runtime.find_observation_by_dedupe(marker, principal_id=principal_id) is not None


def _telegram_similar_async_prompt_pending(
    container: AppContainer,
    *,
    principal_id: str,
    chat_id: str,
    text: str,
    window_seconds: int = 120,
) -> bool:
    normalized_text = " ".join(str(text or "").strip().lower().split())
    if not normalized_text:
        return False
    cutoff = datetime.now(ZoneInfo("UTC")).timestamp() - max(int(window_seconds), 1)
    for row in container.channel_runtime.list_recent_observations(limit=80, principal_id=principal_id):
        if str(row.channel or "").strip() != "telegram":
            continue
        if str(row.event_type or "").strip() != "telegram.reply_async_started":
            continue
        payload = dict(row.payload or {})
        if str(payload.get("chat_id") or "").strip() != str(chat_id or "").strip():
            continue
        prompt_text = " ".join(str(payload.get("prompt_text") or "").strip().lower().split())
        if prompt_text != normalized_text:
            continue
        created_at = _parse_isoish_datetime(getattr(row, "created_at", "") or "")
        if created_at is None:
            continue
        if created_at.timestamp() >= cutoff:
            return True
    return False


def _record_telegram_async_started(
    container: AppContainer,
    *,
    principal_id: str,
    chat_id: str,
    dedupe_key: str,
    prompt_text: str,
) -> None:
    marker = _telegram_async_marker_dedupe_key(dedupe_key)
    if not marker:
        return
    container.channel_runtime.ingest_observation(
        principal_id=principal_id,
        channel="telegram",
        event_type="telegram.reply_async_started",
        payload={
            "chat_id": chat_id,
            "prompt_text": prompt_text,
            "dedupe_key": dedupe_key,
        },
        source_id=f"telegram:{chat_id}" if chat_id else "telegram",
        external_id=str(dedupe_key or "").strip(),
        dedupe_key=marker,
    )


def _telegram_general_reply_text(*, container: AppContainer, principal_id: str, text: str) -> str:
    normalized = str(text or "").strip()
    lower = normalized.lower()
    alpha = "".join(ch for ch in lower if ch.isalpha() or ch.isspace()).strip()
    if alpha in {"again", "repeat", "say that again", "repeat that", "once more"}:
        for previous_reply in _recent_telegram_reply_texts(container, principal_id=principal_id):
            previous_normalized = str(previous_reply or "").strip()
            if not previous_normalized:
                continue
            previous_lower = previous_normalized.lower()
            if previous_lower in {
                "let me check that and get back to you here.",
                "i am still working on that last message.",
            }:
                continue
            if previous_lower.startswith("i got it. i saved this in tibor's assistant flow"):
                continue
            return previous_normalized
        return "I do not have a useful previous answer to repeat yet."
    if lower in {"really", "really?"}:
        for previous in _recent_telegram_texts(container, principal_id=principal_id):
            previous_normalized = str(previous or "").strip()
            if previous_normalized.lower() in {"really", "really?"}:
                continue
            math_answer = _safe_math_answer(previous_normalized)
            if math_answer:
                return f"Yes. {math_answer}"
            if "http://" in previous_normalized or "https://" in previous_normalized:
                return "Yes. I captured the link and kept it in Tibor's assistant inbox."
            break
        return "Yes. I captured your message and kept it in Tibor's assistant flow."
    if ("today" in lower and "day" in lower) or alpha in {"day", "today", "what day", "weekday"}:
        now = datetime.now(ZoneInfo("Europe/Vienna"))
        return f"Today is {now.strftime('%A, %d %B %Y')} in Vienna."
    if ("today" in lower and "date" in lower) or alpha in {"date", "today date", "what date"}:
        now = datetime.now(ZoneInfo("Europe/Vienna"))
        return f"Today's date is {now.strftime('%A, %d %B %Y')} in Vienna."
    if ("time" in lower and "what" in lower) or alpha in {"time", "current time", "what time"}:
        now = datetime.now(ZoneInfo("Europe/Vienna"))
        return f"It is {now.strftime('%H:%M')} in Vienna."
    weather_reply = _telegram_weather_reply_text(text=normalized)
    if weather_reply:
        return weather_reply
    if normalized:
        return (
            "I got it. I saved this in Tibor's assistant flow and can act on links, property alerts, and follow-up requests here."
        )
    return ""


def _telegram_weather_code_label(code: int) -> str:
    mapping = {
        0: "clear",
        1: "mostly clear",
        2: "partly cloudy",
        3: "overcast",
        45: "foggy",
        48: "foggy",
        51: "light drizzle",
        53: "drizzle",
        55: "heavy drizzle",
        61: "light rain",
        63: "rain",
        65: "heavy rain",
        71: "light snow",
        73: "snow",
        75: "heavy snow",
        80: "rain showers",
        81: "rain showers",
        82: "heavy rain showers",
        95: "thunderstorms",
    }
    return mapping.get(int(code), "mixed conditions")


def _telegram_weather_reply_text(*, text: str) -> str:
    normalized = str(text or "").strip()
    lower = normalized.lower()
    if "weather" not in lower:
        return ""
    target_index = 1 if "tomorrow" in lower else 0 if "today" in lower else None
    if target_index is None:
        return ""
    try:
        query = urllib.parse.urlencode(
            {
                "latitude": "48.2082",
                "longitude": "16.3738",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": "Europe/Vienna",
                "forecast_days": "2",
            }
        )
        request = urllib.request.Request(f"{_TELEGRAM_WEATHER_URL}?{query}", headers={"User-Agent": "EA-Telegram/1.0"})
        with urllib.request.urlopen(request, timeout=6) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return "I could not fetch the Vienna forecast right now."
    daily = dict(payload.get("daily") or {}) if isinstance(payload, dict) else {}
    dates = list(daily.get("time") or [])
    codes = list(daily.get("weather_code") or [])
    highs = list(daily.get("temperature_2m_max") or [])
    lows = list(daily.get("temperature_2m_min") or [])
    precipitation = list(daily.get("precipitation_probability_max") or [])
    if target_index >= len(dates):
        return "I could not read the forecast for that day."
    label = "Tomorrow" if target_index == 1 else "Today"
    code = int(codes[target_index]) if target_index < len(codes) else 0
    high = highs[target_index] if target_index < len(highs) else None
    low = lows[target_index] if target_index < len(lows) else None
    rain = precipitation[target_index] if target_index < len(precipitation) else None
    parts = [f"{label} in Vienna looks {_telegram_weather_code_label(code)}"]
    if high is not None and low is not None:
        parts.append(f"with about {int(round(low))} to {int(round(high))}°C")
    if rain is not None:
        parts.append(f"and up to {int(round(rain))}% precipitation probability")
    return " ".join(parts) + "."


def _telegram_local_assistant_reply_text(
    container: AppContainer,
    *,
    principal_id: str,
    text: str,
) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    lower = normalized.lower()
    alpha = "".join(ch for ch in lower if ch.isalpha() or ch.isspace()).strip()
    if alpha in {"hi", "hello", "hey", "test", "testing"}:
        return "I am here."
    if any(
        phrase in lower
        for phrase in (
            "what can you do",
            "what can u do",
            "can you answer everything",
            "can u answer everything",
            "what do you do",
        )
    ):
        return (
            "I can answer from your grounded EA state here: schedule, recent inbox and office signals, property alerts, Pocket-derived context, "
            "and quick summaries. General open-ended chat is still limited when the live model lane is unavailable."
        )
    def _is_low_signal_summary(value: object) -> bool:
        summary = str(value or "").strip().lower()
        if not summary:
            return True
        low_signal_markers = (
            "signal from ",
            "signal sync completed",
            "workspace signal sync completed",
            "google workspace signal sync completed",
            "sync completed",
            "google sync completed",
            "office signal ingested",
        )
        return any(marker in summary for marker in low_signal_markers)
    def _is_actionable_focus_summary(value: object) -> bool:
        summary = str(value or "").strip().lower()
        if not summary or _is_low_signal_summary(summary):
            return False
        actionable_markers = (
            "approve",
            "review",
            "reply",
            "follow up",
            "follow-up",
            "send",
            "book",
            "call",
            "prepare",
            "shortlist",
            "property",
            "apartment",
            "tour",
        )
        return any(marker in summary for marker in actionable_markers)
    def _compact_focus_text(value: object, *, limit: int = 120) -> str:
        text_value = " ".join(str(value or "").strip().split())
        if not text_value:
            return ""
        if text_value.lower().startswith("review apartment alert:"):
            suffix = text_value.split(":", 1)[1].strip()
            suffix = suffix.strip("\"")
            text_value = f"Apartment alert: {suffix}" if suffix else "Apartment alert"
        if text_value.lower().startswith("apartment alert:"):
            prefix, _, suffix = text_value.partition(":")
            cleaned_suffix = suffix.strip().replace('"', "").replace("“", "").replace("”", "")
            listing_match = re.match(r"^(?P<label>.+?) hat (?P<count>\d+) neue Anzeige(?:n)? für dich gefunden\.?$", cleaned_suffix, re.IGNORECASE)
            if listing_match:
                label = " ".join(str(listing_match.group("label") or "").split()).strip(" ,;:")
                count = int(str(listing_match.group("count") or "0") or "0")
                noun = "listing" if count == 1 else "listings"
                cleaned_suffix = f"{label} ({count} new {noun})"
            text_value = f"{prefix}: {cleaned_suffix}".strip()
        if text_value.lower().startswith("reply to ") and " | " in text_value:
            _, _, remainder = text_value.partition(" | ")
            if remainder.strip():
                text_value = remainder.strip()
        if text_value.lower().startswith("re:"):
            text_value = text_value[3:].strip()
        lowered = text_value.lower()
        noisy_markers = (
            "stage 1 commitment candidate.",
            "prepare a reply draft for approval before send.",
            "no additional ltd lane is recommended",
            "office signal ingested.",
            "recent mail from",
            " hi ",
        )
        for marker in noisy_markers:
            idx = lowered.find(marker)
            if idx >= 0:
                text_value = text_value[:idx].strip()
                lowered = text_value.lower()
        greeting_idx = lowered.find(". hi ")
        if greeting_idx >= 0:
            text_value = text_value[: greeting_idx + 1].strip()
        if ". " in text_value:
            first_sentence = text_value.split(". ", 1)[0].strip()
            if 0 < len(first_sentence) <= limit:
                text_value = first_sentence.rstrip(".") + "."
        while ".." in text_value:
            text_value = text_value.replace("..", ".")
        if len(text_value) <= limit:
            return text_value
        clipped = text_value[: limit - 1].rstrip()
        if " " in clipped:
            clipped = clipped.rsplit(" ", 1)[0]
        return clipped.rstrip(" ,;:.") + "..."
    if any(
        phrase in lower
        for phrase in (
            "focus on tomorrow",
            "what should i focus on tomorrow",
            "what should i focus on",
            "what should i do tomorrow",
            "what is tomorrow like",
        )
    ):
        now_vienna = datetime.now(ZoneInfo("Europe/Vienna"))
        tomorrow_date = now_vienna.date() + timedelta(days=1)
        upcoming = _telegram_upcoming_calendar_events(container, principal_id=principal_id, limit=6)
        tomorrow_events = [
            event
            for event in upcoming
            if event["start_at"].astimezone(ZoneInfo("Europe/Vienna")).date() == tomorrow_date
        ]
        parts: list[str] = []
        if tomorrow_events:
            first = tomorrow_events[0]
            start_text = first["start_at"].astimezone(ZoneInfo("Europe/Vienna")).strftime("%H:%M")
            parts.append(f"Tomorrow, focus first on {first['title']} at {start_text}.")
            if str(first.get("location") or "").strip():
                parts.append(f"Location: {str(first.get('location') or '').strip()}.")
        product_service = build_product_service(container)
        events = list(product_service.list_office_events(principal_id=principal_id, limit=20))
        recent_summaries = [
            str(row.get("summary") or "").strip()
            for row in events
            if str(row.get("channel") or "").strip() in {"gmail", "product", "pocket"}
            and str(row.get("summary") or "").strip()
            and _is_actionable_focus_summary(row.get("summary"))
        ][:2]
        queue_items = []
        try:
            queue_items = list(product_service.list_queue(principal_id=principal_id, limit=3))
        except Exception:
            queue_items = []
        if recent_summaries:
            compact_summaries = [_compact_focus_text(item, limit=90) for item in recent_summaries]
            compact_summaries = [item for item in compact_summaries if item]
            if compact_summaries:
                joined = " | ".join(compact_summaries[:2]).rstrip(". ")
                parts.append("Recent follow-up context: " + joined + ".")
        if queue_items:
            first = queue_items[0]
            first_title = _compact_focus_text(getattr(first, "title", ""), limit=90)
            first_summary = _compact_focus_text(getattr(first, "summary", ""), limit=80)
            if first_title:
                sentence = f"Top priority looks like {first_title}."
                if first_summary and first_summary.lower() not in {"operator · pending", "unassigned · normal · pending"}:
                    sentence += f" {first_summary}"
                parts.append(sentence)
            if len(queue_items) > 1:
                next_titles = [
                    _compact_focus_text(getattr(item, "title", ""), limit=80)
                    for item in queue_items[1:]
                    if _compact_focus_text(getattr(item, "title", ""), limit=80)
                ]
                if next_titles:
                    parts.append("After that: " + " | ".join(next_titles[:2]) + ".")
        if parts:
            return " ".join(parts)
        return "I do not see a concrete appointment for tomorrow yet. Focus on clearing the most important inbox and property follow-ups first."
    if any(phrase in lower for phrase in ("summarize", "summary", "recap", "catch me up")):
        upcoming = _telegram_upcoming_calendar_events(container, principal_id=principal_id, limit=2)
        product_service = build_product_service(container)
        events = list(product_service.list_office_events(principal_id=principal_id, limit=12))
        recent_signals = [
            row
            for row in events
            if str(row.get("channel") or "").strip() in {"gmail", "calendar", "pocket", "product"}
            and not _is_low_signal_summary(row.get("summary"))
        ][:4]
        parts: list[str] = []
        if upcoming:
            first = upcoming[0]
            starts = first["start_at"].astimezone(ZoneInfo("Europe/Vienna")).strftime("%A at %H:%M")
            parts.append(f"Next up: {first['title']} on {starts}.")
        if recent_signals:
            summaries = [str(row.get("summary") or "").strip() for row in recent_signals if str(row.get("summary") or "").strip()]
            if summaries:
                parts.append("Recent activity: " + " | ".join(summaries[:3]))
        if parts:
            return " ".join(parts)
        return "I do not have enough recent EA state to summarize anything useful right now."
    if any(phrase in lower for phrase in ("email", "emails", "inbox", "mail")):
        product_service = build_product_service(container)
        events = list(product_service.list_office_events(principal_id=principal_id, limit=20))
        gmail_events = [row for row in events if str(row.get("channel") or "").strip() == "gmail"][:3]
        if gmail_events:
            summaries = [str(row.get("summary") or "").strip() for row in gmail_events if str(row.get("summary") or "").strip()]
            if summaries:
                return "Recent email signals: " + " | ".join(summaries)
        return "I do not see a recent Gmail signal I can summarize right now."
    return ""


def _parse_isoish_datetime(value: object) -> datetime | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        parsed = datetime.fromisoformat(normalized)
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=ZoneInfo("UTC"))
    return parsed


def _telegram_upcoming_calendar_events(
    container: AppContainer,
    *,
    principal_id: str,
    limit: int = 4,
) -> list[dict[str, object]]:
    product_service = build_product_service(container)
    rows = list(
        product_service.list_office_events(
            principal_id=principal_id,
            limit=max(limit * 8, 20),
            event_type="office_signal_calendar_note",
        )
    )
    upcoming: list[dict[str, object]] = []
    now = datetime.now(ZoneInfo("UTC"))
    for row in rows:
        payload = dict(row.get("payload") or {})
        start_at = (
            str(payload.get("start_at") or "").strip()
            or str(payload.get("due_at") or "").strip()
            or str(row.get("created_at") or "").strip()
        )
        parsed_start = _parse_isoish_datetime(start_at)
        if parsed_start is None:
            continue
        if parsed_start.astimezone(ZoneInfo("UTC")) < now:
            continue
        title = str(payload.get("title") or row.get("summary") or "").strip() or "Upcoming meeting"
        attendees = [str(item or "").strip() for item in list(payload.get("attendees") or []) if str(item or "").strip()]
        location = str(payload.get("location") or "").strip()
        upcoming.append(
            {
                "title": title,
                "start_at": parsed_start,
                "location": location,
                "attendees": attendees[:4],
                "summary": str(row.get("summary") or "").strip(),
            }
        )
    upcoming.sort(key=lambda item: item["start_at"])
    return upcoming[:limit]


def _telegram_direct_calendar_reply_text(*, container: AppContainer, principal_id: str, text: str) -> str:
    normalized = str(text or "").strip()
    lower = normalized.lower()
    if not normalized:
        return ""
    schedule_markers = (
        "next appointment",
        "next meeting",
        "next calendar",
        "my calendar",
        "my schedule",
        "next event",
        "what's next",
        "whats next",
        "what is next",
        "appointment",
    )
    if not any(marker in lower for marker in schedule_markers):
        return ""
    events = _telegram_upcoming_calendar_events(container, principal_id=principal_id, limit=3)
    if not events:
        return "I do not see an upcoming calendar appointment in EA right now."
    first = events[0]
    starts = first["start_at"].astimezone(ZoneInfo("Europe/Vienna")).strftime("%A at %H:%M")
    prefix = "Yes. " if any(marker in lower for marker in ("can u", "can you")) else ""
    detail_parts = [f"{prefix}Your next appointment is {first['title']} on {starts}."]
    location = str(first.get("location") or "").strip()
    if location:
        detail_parts.append(f"Location: {location}.")
    attendees = [str(item or "").strip() for item in list(first.get("attendees") or []) if str(item or "").strip()]
    if attendees:
        detail_parts.append(f"With {', '.join(attendees[:3])}.")
    return " ".join(detail_parts)


def _telegram_recent_conversation_messages(
    container: AppContainer,
    *,
    principal_id: str,
    current_message_id: str = "",
    limit: int = 8,
) -> list[dict[str, object]]:
    rows = list(container.channel_runtime.list_recent_observations(limit=60, principal_id=principal_id))
    rows.sort(key=lambda row: (str(row.created_at or ""), str(row.observation_id or "")))
    messages: list[dict[str, object]] = []
    current_external_id = str(current_message_id or "").strip()
    for row in rows:
        if str(row.channel or "").strip() != "telegram":
            continue
        payload = dict(row.payload or {})
        event_type = str(row.event_type or "").strip().lower()
        if event_type == "telegram.message":
            if current_external_id and str(row.external_id or "").strip() == current_external_id:
                continue
            text = str(payload.get("text") or "").strip()
            if text:
                messages.append({"role": "user", "content": [{"type": "input_text", "text": text}]})
        elif event_type == "telegram.reply_sent":
            reply_text = str(payload.get("reply_text") or "").strip()
            if reply_text:
                messages.append({"role": "assistant", "content": [{"type": "output_text", "text": reply_text}]})
    return messages[-limit:]


def _telegram_office_grounding_text(container: AppContainer, *, principal_id: str) -> str:
    product_service = build_product_service(container)
    events = list(product_service.list_office_events(principal_id=principal_id, limit=12))
    upcoming_calendar = _telegram_upcoming_calendar_events(container, principal_id=principal_id, limit=4)
    lines = [
        "Surface: Telegram chat with the principal.",
        "Use this grounding for personal schedule, inbox, property, and assistant-state questions.",
    ]
    if upcoming_calendar:
        lines.append("Upcoming calendar events:")
        for event in upcoming_calendar:
            start_text = event["start_at"].astimezone(ZoneInfo("Europe/Vienna")).strftime("%Y-%m-%d %H:%M")
            detail = f"- {start_text}: {event['title']}"
            if str(event.get("location") or "").strip():
                detail += f" @ {str(event.get('location') or '').strip()}"
            attendees = [str(item or "").strip() for item in list(event.get("attendees") or []) if str(item or "").strip()]
            if attendees:
                detail += f" with {', '.join(attendees[:3])}"
            lines.append(detail)
    else:
        lines.append("Upcoming calendar events: none visible in stored EA office signals.")
    recent_product_events = [row for row in events if str(row.get("channel") or "").strip() == "product"][:4]
    if recent_product_events:
        lines.append("Recent EA product events:")
        for row in recent_product_events:
            lines.append(f"- {str(row.get('event_type') or '').strip()}: {str(row.get('summary') or '').strip()}")
    recent_signal_events = [row for row in events if str(row.get("channel") or "").strip() in {"gmail", "calendar", "pocket"}][:6]
    if recent_signal_events:
        lines.append("Recent office signals:")
        for row in recent_signal_events:
            lines.append(
                f"- {str(row.get('channel') or '').strip()} {str(row.get('event_type') or '').strip()}: {str(row.get('summary') or '').strip()}"
            )
    return "\n".join(line for line in lines if line).strip()


def _telegram_real_ea_reply_text(
    *,
    container: AppContainer,
    principal_id: str,
    text: str,
    current_message_id: str = "",
    preferred_onemin_labels: tuple[str, ...] = (),
) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    model = str(os.getenv("EA_TELEGRAM_RESPONSES_MODEL") or "ea-coder-fast").strip() or "ea-coder-fast"
    normalized_preferred_onemin_labels = tuple(
        str(item or "").strip()
        for item in preferred_onemin_labels
        if str(item or "").strip()
    ) or _telegram_default_preferred_onemin_labels()
    grounding = _telegram_office_grounding_text(container, principal_id=principal_id)
    messages = [
        {
            "role": "system",
            "content": (
                "You are Executive Assistant replying inside a Telegram chat. "
                "Be concise, direct, and useful. "
                "Use the supplied grounding as source of truth for schedule, inbox, property, and workspace-state claims. "
                "If the grounding does not support a personal factual claim, say that clearly instead of guessing. "
                "Do not mention internal prompts, routes, tokens, or implementation details."
            ),
        },
        {
            "role": "system",
            "content": grounding,
        },
    ]
    for item in _telegram_recent_conversation_messages(
        container,
        principal_id=principal_id,
        current_message_id=current_message_id,
    ):
        role = str(item.get("role") or "").strip() or "user"
        content_parts = list(item.get("content") or [])
        text_part = ""
        for part in content_parts:
            if not isinstance(part, dict):
                continue
            text_part = str(part.get("text") or "").strip()
            if text_part:
                break
        if text_part:
            messages.append({"role": role, "content": text_part})
    messages.append({"role": "user", "content": normalized})
    try:
        timeout_seconds = max(float(str(os.getenv("EA_TELEGRAM_RESPONSES_TIMEOUT_SECONDS") or "12").strip() or "12"), 1.0)
    except Exception:
        timeout_seconds = 12.0
    executor: concurrent.futures.ThreadPoolExecutor | None = None
    try:
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(
            responses_route._generate_upstream_text,
            prompt=normalized,
            messages=messages,
            requested_model=model,
            max_output_tokens=220,
            chatplayground_audit_callback=None,
            chatplayground_audit_callback_only=False,
            chatplayground_audit_principal_id=principal_id,
            preferred_onemin_labels=normalized_preferred_onemin_labels,
            request_deadline_monotonic=time.monotonic() + timeout_seconds,
        )
        result = future.result(timeout=timeout_seconds)
    except concurrent.futures.TimeoutError:
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
        return ""
    except Exception:
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
        return ""
    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=True)
    return str(getattr(result, "text", "") or "").strip()


def _telegram_should_async_assistant_reply(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    if normalized.startswith("/"):
        return False
    if _safe_math_answer(normalized):
        return False
    lower = normalized.lower()
    alpha = "".join(ch for ch in lower if ch.isalpha() or ch.isspace()).strip()
    if lower in {"really", "really?"}:
        return False
    if ("today" in lower and "day" in lower) or alpha in {"day", "today", "what day", "weekday"}:
        return False
    if ("today" in lower and "date" in lower) or alpha in {"date", "today date", "what date"}:
        return False
    if ("time" in lower and "what" in lower) or alpha in {"time", "current time", "what time"}:
        return False
    schedule_markers = (
        "next appointment",
        "next meeting",
        "next calendar",
        "my calendar",
        "my schedule",
        "next event",
        "what's next",
        "whats next",
        "what is next",
        "appointment",
    )
    if any(marker in lower for marker in schedule_markers):
        return False
    if "http://" in normalized or "https://" in normalized:
        return False
    return True


def _telegram_async_assistant_reply_worker(
    *,
    container: AppContainer,
    principal_id: str,
    bot_config: dict[str, object],
    chat_id: str,
    text: str,
    current_message_id: str,
) -> None:
    reply_text = _telegram_real_ea_reply_text(
        container=container,
        principal_id=principal_id,
        text=text,
        current_message_id=current_message_id,
        preferred_onemin_labels=tuple(
            str(item or "").strip()
            for item in list(bot_config.get("preferred_onemin_labels") or ())
            if str(item or "").strip()
        ),
    ).strip()
    if not reply_text:
        reply_text = _telegram_local_assistant_reply_text(
            container,
            principal_id=principal_id,
            text=text,
        ).strip()
    if not reply_text:
        reply_text = "I could not complete that yet. Ask me again in a moment, or ask me about schedule, property alerts, or links first."
    try:
        _telegram_send_message(
            bot_token=str(bot_config.get("token") or "").strip(),
            chat_id=chat_id,
            text=reply_text,
        )
    except Exception:
        return
    container.channel_runtime.ingest_observation(
        principal_id=principal_id,
        channel="telegram",
        event_type="telegram.reply_async_sent",
        payload={
            "chat_id": chat_id,
            "reply_text": reply_text,
        },
        source_id=f"telegram:{chat_id}" if chat_id else "telegram",
        external_id=str(current_message_id or "").strip(),
        dedupe_key=f"{str(current_message_id or '').strip()}:assistant_async_sent" if str(current_message_id or '').strip() else "",
    )


def _telegram_schedule_async_assistant_reply(
    *,
    container: AppContainer,
    principal_id: str,
    bot_config: dict[str, object],
    chat_id: str,
    dedupe_key: str,
    text: str,
    current_message_id: str,
) -> None:
    if not chat_id or not dedupe_key:
        return
    if _telegram_async_already_started(container, principal_id=principal_id, dedupe_key=dedupe_key):
        return
    _record_telegram_async_started(
        container,
        principal_id=principal_id,
        chat_id=chat_id,
        dedupe_key=dedupe_key,
        prompt_text=text,
    )
    _TELEGRAM_ASYNC_EXECUTOR.submit(
        _telegram_async_assistant_reply_worker,
        container=container,
        principal_id=principal_id,
        bot_config=dict(bot_config),
        chat_id=chat_id,
        text=text,
        current_message_id=current_message_id,
    )


def _telegram_command_reply_text(
    *,
    container: AppContainer,
    principal_id: str,
    text: str,
    bot_handle: str,
    current_message_id: str = "",
    chat_id: str = "",
) -> tuple[str, bool]:
    normalized = str(text or "").strip()
    command = normalized.split()[0].split("@", 1)[0].lower() if normalized else ""
    handle = str(bot_handle or "").strip() or "this bot"
    if command == "/start":
        return (
            f"{handle} is connected to Executive Assistant.\n\n"
            "You can send messages, links, property alerts, and follow-up requests here. "
            "EA will capture this chat for Tibor and use it as a live assistant inbox."
        ), False
    if command == "/help":
        return (
            "Available commands:\n"
            "/start - connect this chat to Executive Assistant\n"
            "/help - show this help text\n"
            "/status - check bot and routing status\n\n"
            "You can also send property links, notes, or requests in plain text."
        ), False
    if command == "/status":
        return (
            "EA is online.\n"
            "Telegram ingest is active.\n"
            "Property email sync is active.\n"
            "Pocket sync is active.\n"
            "Teable preference review sync is active."
        ), False
    math_reply = _safe_math_answer(normalized)
    if math_reply:
        return math_reply, False
    if "http://" in normalized or "https://" in normalized:
        return (
            "Link received. EA captured it and will route it into Tibor's assistant workspace for review."
        ), False
    if normalized:
        general_reply = _telegram_general_reply_text(container=container, principal_id=principal_id, text=normalized)
        if general_reply and not general_reply.startswith("I got it. I saved this in Tibor's assistant flow"):
            return general_reply, False
        calendar_reply = _telegram_direct_calendar_reply_text(
            container=container,
            principal_id=principal_id,
            text=normalized,
        )
        if calendar_reply:
            return calendar_reply, False
        local_assistant_reply = _telegram_local_assistant_reply_text(
            container,
            principal_id=principal_id,
            text=normalized,
        )
        if local_assistant_reply:
            return local_assistant_reply, False
        if _telegram_should_async_assistant_reply(normalized):
            if _telegram_similar_async_prompt_pending(
                container,
                principal_id=principal_id,
                chat_id=chat_id,
                text=normalized,
            ):
                return "", False
            return "", True
        return general_reply, False
    return "", False


class TelegramIngestOut(BaseModel):
    observation_id: str
    principal_id: str
    channel: str
    event_type: str
    created_at: str
    reply_sent: bool = False
    reply_text: str = ""


@router.post("/telegram/ingest/{bot_key}")
@router.post("/telegram/ingest")
def ingest_telegram(
    request: Request,
    body: dict[str, object] = Body(default_factory=dict),
    bot_key: str = "",
    container: AppContainer = Depends(get_container),
) -> TelegramIngestOut:
    payload = dict(body or {})
    update = dict(payload.get("update") or {}) if isinstance(payload.get("update"), dict) else payload
    header_secret = str(request.headers.get("x-telegram-bot-api-secret-token") or "")
    provided_secret = str(update.get("secret_token") or "")
    bot_config = _resolve_telegram_bot_config(bot_key=bot_key, provided_secret=provided_secret, header_secret=header_secret)
    _require_telegram_ingest_secret(
        config=bot_config,
        provided=provided_secret,
        header_value=header_secret,
    )
    fields = _telegram.to_observation_fields(update)
    chat_id = str(fields.get("chat_id") or "").strip()
    dedupe_key = str(fields.get("dedupe_key") or "")
    principal_id = _resolve_telegram_principal(
        container,
        chat_id,
        bot_key=str(bot_config.get("bot_key") or "").strip(),
        bot_handle=str(bot_config.get("handle") or "").strip(),
    )
    if not principal_id:
        principal_id = _auto_bind_telegram_chat(container, chat_id, config=bot_config)
    if not principal_id:
        raise HTTPException(status_code=404, detail="telegram_binding_not_found")
    existing_event = (
        container.channel_runtime.find_observation_by_dedupe(dedupe_key, principal_id=principal_id) if dedupe_key else None
    )
    event = existing_event or container.channel_runtime.ingest_observation(
        principal_id=principal_id,
        channel=_telegram.channel,
        event_type=str(fields.get("event_type") or "telegram.update"),
        payload=dict(fields.get("payload") or {}),
        source_id=str(fields.get("source_id") or ""),
        external_id=str(fields.get("external_id") or ""),
        dedupe_key=dedupe_key,
    )
    reply_text, schedule_async = _telegram_command_reply_text(
        container=container,
        principal_id=principal_id,
        text=str(dict(fields.get("payload") or {}).get("text") or ""),
        bot_handle=str(bot_config.get("handle") or "").strip(),
        current_message_id=str(dict(fields.get("payload") or {}).get("message_id") or ""),
        chat_id=chat_id,
    )
    reply_sent = False
    if reply_text and chat_id and not _telegram_reply_already_sent(container, principal_id=principal_id, dedupe_key=dedupe_key):
        try:
            receipt = _telegram_send_message(
                bot_token=str(bot_config.get("token") or "").strip(),
                chat_id=chat_id,
                text=reply_text,
            )
            reply_sent = bool(receipt.get("ok"))
            if reply_sent:
                result = dict(receipt.get("result") or {})
                _record_telegram_reply_sent(
                    container,
                    principal_id=principal_id,
                    chat_id=chat_id,
                    dedupe_key=dedupe_key,
                    reply_text=reply_text,
                    message_id=str(result.get("message_id") or "").strip(),
                )
        except Exception:
            reply_sent = False
    if schedule_async and chat_id:
        _telegram_schedule_async_assistant_reply(
            container=container,
            principal_id=principal_id,
            bot_config=bot_config,
            chat_id=chat_id,
            dedupe_key=dedupe_key,
            text=str(dict(fields.get("payload") or {}).get("text") or ""),
            current_message_id=str(dict(fields.get("payload") or {}).get("message_id") or ""),
        )
    return TelegramIngestOut(
        observation_id=event.observation_id,
        principal_id=event.principal_id,
        channel=event.channel,
        event_type=event.event_type,
        created_at=event.created_at,
        reply_sent=reply_sent,
        reply_text=reply_text,
    )
