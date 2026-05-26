from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass

from app.domain.models import ConnectorBinding
from app.services.telegram_onboarding_service import TELEGRAM_IDENTITY_CONNECTOR
from app.services.tool_runtime import ToolRuntimeService

_TELEGRAM_MESSAGE_LIMIT = 4000


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
    candidates.sort(key=lambda item: str(item.updated_at or ""), reverse=True)
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
        payload = json.dumps({"chat_id": chat_id, "text": chunk}).encode("utf-8")
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
        if not bool(body.get("ok")):
            raise RuntimeError("telegram_send_failed")
        result = dict(body.get("result") or {})
        message_ids.append(str(result.get("message_id") or ""))
    return TelegramDeliveryReceipt(
        principal_id=str(principal_id or "").strip(),
        chat_id=chat_id,
        bot_key=bot_key,
        bot_handle=bot_handle,
        message_ids=tuple(value for value in message_ids if value),
    )
