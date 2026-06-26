from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from dataclasses import dataclass
from typing import Any

from app.services.proactive_telegram_binding import proactive_telegram_ready, resolve_proactive_telegram_chat_id
from app.services.telegram_delivery import _telegram_bot_registry, resolve_primary_telegram_binding, send_telegram_message_for_principal
from app.services.whatsapp_delivery import resolve_whatsapp_delivery_config
from app.services.whatsapp_delivery_router import WEB_SESSION_CONNECTOR, send_whatsapp_delivery_text


SUPPORTED_DELIVERY_CHANNELS = {"telegram", "whatsapp"}
POLICY_SCOPE_ORDER = (
    "proactive_ooda",
    "proactive_notifications",
    "office_loop",
    "principal",
    "default",
)


@dataclass(frozen=True)
class ProactiveOodaDeliveryStatus:
    ready: bool
    selected_channel: str = ""
    selected_transport: str = ""
    selected_by: str = ""
    selected_reason: str = ""
    recipient_ref: str = ""
    recipient_ref_hash: str = ""
    binding_id: str = ""
    preference_id: str = ""
    policy_scope: str = ""
    available_channels: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    preference_count: int = 0
    policy_count: int = 0
    follow_up_hint_count: int = 0


@dataclass(frozen=True)
class ProactiveOodaDeliveryReceipt:
    channel: str
    delivery_transport: str
    selected_by: str
    selected_reason: str
    recipient_ref_hash: str
    message_ids: tuple[str, ...]
    binding_id: str = ""
    outbox_delivery_id: str = ""
    outbox_status: str = ""
    telegram_message_ids: tuple[str, ...] = ()


def resolve_proactive_ooda_delivery_status(
    *,
    principal_id: str,
    tool_runtime: Any | None = None,
    memory_runtime: Any | None = None,
    digest: Any | None = None,
) -> ProactiveOodaDeliveryStatus:
    high_priority = _digest_has_high_priority(digest)
    preferences = _active_delivery_preferences(memory_runtime, principal_id=principal_id)
    policies = _active_communication_policies(memory_runtime, principal_id=principal_id)
    follow_up_hints = _active_follow_up_hints(memory_runtime, principal_id=principal_id)
    policy_rank = _channel_priority_map(
        _ordered_policy_channels(policies),
    )
    hint_rank = _channel_priority_map(follow_up_hints)
    ready_channels: list[str] = []
    errors: list[str] = []
    preference_candidates: list[tuple[tuple[int, int, int], ProactiveOodaDeliveryStatus]] = []

    ordered_preferences = sorted(
        preferences,
        key=lambda row: (str(getattr(row, "updated_at", "") or ""), str(getattr(row, "created_at", "") or "")),
        reverse=True,
    )
    for index, preference in enumerate(ordered_preferences):
        channel = _canonical_channel(getattr(preference, "channel", ""))
        if channel not in SUPPORTED_DELIVERY_CHANNELS:
            continue
        cadence_allowed, cadence_reason = _cadence_allows_digest(
            str(getattr(preference, "cadence", "") or ""),
            high_priority=high_priority,
        )
        if not cadence_allowed:
            errors.append(f"delivery_preference_ineligible:{getattr(preference, 'preference_id', '')}:{cadence_reason}")
            continue
        route = _channel_route_status(
            channel=channel,
            principal_id=principal_id,
            recipient_ref=str(getattr(preference, "recipient_ref", "") or ""),
            tool_runtime=tool_runtime,
        )
        if route.ready:
            ready_channels.append(route.selected_channel)
            preference_candidates.append(
                (
                    (
                        policy_rank.get(channel, len(policy_rank) + 5),
                        hint_rank.get(channel, len(hint_rank) + 5),
                        index,
                    ),
                    ProactiveOodaDeliveryStatus(
                        ready=True,
                        selected_channel=route.selected_channel,
                        selected_transport=route.selected_transport,
                        selected_by="delivery_preference",
                        selected_reason=_preference_reason(preference, route=route),
                        recipient_ref=route.recipient_ref,
                        recipient_ref_hash=route.recipient_ref_hash,
                        binding_id=route.binding_id,
                        preference_id=str(getattr(preference, "preference_id", "") or ""),
                        available_channels=tuple(dict.fromkeys(ready_channels)),
                        errors=(),
                        preference_count=len(preferences),
                        policy_count=len(policies),
                        follow_up_hint_count=len(follow_up_hints),
                    ),
                )
            )
            continue
        errors.extend(route.errors)

    if preference_candidates:
        return min(preference_candidates, key=lambda item: item[0])[1]

    for scope, channel in _ordered_policy_channels_with_scope(policies):
        route = _channel_route_status(
            channel=channel,
            principal_id=principal_id,
            recipient_ref="",
            tool_runtime=tool_runtime,
        )
        if route.ready:
            ready_channels.append(route.selected_channel)
            return ProactiveOodaDeliveryStatus(
                ready=True,
                selected_channel=route.selected_channel,
                selected_transport=route.selected_transport,
                selected_by="communication_policy",
                selected_reason=f"{scope} policy prefers {route.selected_channel}",
                recipient_ref=route.recipient_ref,
                recipient_ref_hash=route.recipient_ref_hash,
                binding_id=route.binding_id,
                policy_scope=scope,
                available_channels=tuple(dict.fromkeys(ready_channels)),
                errors=tuple(dict.fromkeys(item for item in errors if item)),
                preference_count=len(preferences),
                policy_count=len(policies),
                follow_up_hint_count=len(follow_up_hints),
            )
        errors.extend(route.errors)

    telegram_fallback = _channel_route_status(
        channel="telegram",
        principal_id=principal_id,
        recipient_ref="",
        tool_runtime=tool_runtime,
    )
    if telegram_fallback.ready:
        ready_channels.append("telegram")
        return ProactiveOodaDeliveryStatus(
            ready=True,
            selected_channel=telegram_fallback.selected_channel,
            selected_transport=telegram_fallback.selected_transport,
            selected_by=telegram_fallback.selected_by or "default",
            selected_reason=telegram_fallback.selected_reason or "default Telegram fallback",
            recipient_ref=telegram_fallback.recipient_ref,
            recipient_ref_hash=telegram_fallback.recipient_ref_hash,
            binding_id=telegram_fallback.binding_id,
            available_channels=tuple(dict.fromkeys(ready_channels)),
            errors=tuple(dict.fromkeys(item for item in errors if item)),
            preference_count=len(preferences),
            policy_count=len(policies),
            follow_up_hint_count=len(follow_up_hints),
        )
    errors.extend(telegram_fallback.errors)

    return ProactiveOodaDeliveryStatus(
        ready=False,
        available_channels=tuple(dict.fromkeys(ready_channels)),
        errors=tuple(dict.fromkeys(item for item in errors if item)),
        preference_count=len(preferences),
        policy_count=len(policies),
        follow_up_hint_count=len(follow_up_hints),
    )


def send_proactive_ooda_notification(
    *,
    principal_id: str,
    text: str,
    tool_runtime: Any | None = None,
    channel_runtime: Any | None = None,
    memory_runtime: Any | None = None,
    digest: Any | None = None,
) -> ProactiveOodaDeliveryReceipt:
    route = resolve_proactive_ooda_delivery_status(
        principal_id=principal_id,
        tool_runtime=tool_runtime,
        memory_runtime=memory_runtime,
        digest=digest,
    )
    if not route.ready:
        detail = route.errors[0] if route.errors else "delivery_route_unavailable"
        raise RuntimeError(detail)

    outbox_row = None
    if channel_runtime is not None:
        try:
            outbox_row = channel_runtime.queue_delivery(
                route.selected_channel,
                route.recipient_ref or f"{route.selected_channel}:principal",
                text,
                metadata={
                    "principal_id": principal_id,
                    "proactive_ooda": True,
                    "selected_by": route.selected_by,
                    "selected_reason": route.selected_reason,
                    "delivery_transport": route.selected_transport,
                    "binding_id": route.binding_id,
                    "preference_id": route.preference_id,
                    "policy_scope": route.policy_scope,
                },
                principal_id=principal_id,
            )
        except Exception:
            outbox_row = None

    try:
        raw_receipt = _send_via_route(
            route=route,
            principal_id=principal_id,
            text=text,
            tool_runtime=tool_runtime,
        )
    except Exception as exc:
        if channel_runtime is not None and outbox_row is not None:
            try:
                channel_runtime.mark_delivery_failed(
                    outbox_row.delivery_id,
                    principal_id=principal_id,
                    error=str(exc)[:200] or exc.__class__.__name__,
                )
            except Exception:
                pass
        raise

    receipt = _normalize_delivery_receipt(raw_receipt, route=route, outbox_row=outbox_row)
    if channel_runtime is not None and outbox_row is not None:
        try:
            channel_runtime.mark_delivery_sent(
                outbox_row.delivery_id,
                principal_id=principal_id,
                receipt_json={
                    "channel": receipt.channel,
                    "delivery_transport": receipt.delivery_transport,
                    "selected_by": receipt.selected_by,
                    "message_ids": list(receipt.message_ids),
                    "telegram_message_ids": list(receipt.telegram_message_ids),
                    "recipient_ref_hash": receipt.recipient_ref_hash,
                },
            )
        except Exception:
            pass
    return receipt


def _send_via_route(
    *,
    route: ProactiveOodaDeliveryStatus,
    principal_id: str,
    text: str,
    tool_runtime: Any | None,
) -> object:
    if route.selected_channel == "whatsapp":
        return send_whatsapp_delivery_text(
            tool_runtime=tool_runtime,
            principal_id=principal_id,
            recipient=route.recipient_ref,
            text=text,
            binding_id=route.binding_id,
        )
    if tool_runtime is not None and route.selected_by != "env_telegram_fallback":
        return send_telegram_message_for_principal(
            tool_runtime,
            principal_id=principal_id,
            text=text,
        )
    return _send_telegram_message_from_env(principal_id=principal_id, text=text)


def _channel_route_status(
    *,
    channel: str,
    principal_id: str,
    recipient_ref: str,
    tool_runtime: Any | None,
) -> ProactiveOodaDeliveryStatus:
    normalized = _canonical_channel(channel)
    if normalized == "telegram":
        return _telegram_route_status(principal_id=principal_id, tool_runtime=tool_runtime)
    if normalized == "whatsapp":
        return _whatsapp_route_status(
            principal_id=principal_id,
            recipient_ref=recipient_ref,
            tool_runtime=tool_runtime,
        )
    return ProactiveOodaDeliveryStatus(
        ready=False,
        errors=(f"delivery_channel_unsupported:{normalized or 'unknown'}",),
    )


def _telegram_route_status(*, principal_id: str, tool_runtime: Any | None) -> ProactiveOodaDeliveryStatus:
    if tool_runtime is not None:
        try:
            binding = resolve_primary_telegram_binding(tool_runtime, principal_id=principal_id)
        except Exception:
            binding = None
        if binding is not None:
            metadata = dict(getattr(binding, "auth_metadata_json", {}) or {})
            bot_key = str(metadata.get("bot_key") or "default").strip() or "default"
            token = str(dict(_telegram_bot_registry().get(bot_key) or {}).get("token") or "").strip()
            if token:
                return ProactiveOodaDeliveryStatus(
                    ready=True,
                    selected_channel="telegram",
                    selected_transport="telegram",
                    selected_by="tool_runtime_binding",
                    selected_reason="enabled Telegram binding available",
                    recipient_ref_hash=_hash_text(str(metadata.get("default_chat_ref") or getattr(binding, "external_account_ref", "") or "")),
                    binding_id=str(getattr(binding, "binding_id", "") or ""),
                    available_channels=("telegram",),
                )
    if proactive_telegram_ready(principal_id=principal_id):
        return ProactiveOodaDeliveryStatus(
            ready=True,
            selected_channel="telegram",
            selected_transport="telegram",
            selected_by="env_telegram_fallback",
            selected_reason="Telegram bot token and proactive chat id available",
            recipient_ref_hash=_hash_text(resolve_proactive_telegram_chat_id(principal_id=principal_id)),
            available_channels=("telegram",),
        )
    return ProactiveOodaDeliveryStatus(
        ready=False,
        errors=("telegram_notification_not_configured",),
    )


def _whatsapp_route_status(
    *,
    principal_id: str,
    recipient_ref: str,
    tool_runtime: Any | None,
) -> ProactiveOodaDeliveryStatus:
    normalized_recipient = _normalize_recipient(recipient_ref)
    if not normalized_recipient:
        return ProactiveOodaDeliveryStatus(
            ready=False,
            errors=("whatsapp_recipient_missing",),
        )
    if tool_runtime is not None and hasattr(tool_runtime, "list_connector_bindings"):
        candidates = list(tool_runtime.list_connector_bindings(principal_id, limit=200) or [])
        enabled_web = [
            row
            for row in candidates
            if str(getattr(row, "connector_name", "") or "").strip() == WEB_SESSION_CONNECTOR
            and str(getattr(row, "status", "") or "").strip().lower() == "enabled"
        ]
        enabled_web.sort(key=lambda row: str(getattr(row, "updated_at", "") or ""), reverse=True)
        if enabled_web:
            binding = enabled_web[0]
            return ProactiveOodaDeliveryStatus(
                ready=True,
                selected_channel="whatsapp",
                selected_transport=WEB_SESSION_CONNECTOR,
                selected_by="tool_runtime_binding",
                selected_reason="enabled WhatsApp Web session binding available",
                recipient_ref=normalized_recipient,
                recipient_ref_hash=_hash_text(normalized_recipient),
                binding_id=str(getattr(binding, "binding_id", "") or ""),
                available_channels=("whatsapp",),
            )
        staged_web = next(
            (
                row
                for row in candidates
                if str(getattr(row, "connector_name", "") or "").strip() == WEB_SESSION_CONNECTOR
            ),
            None,
        )
        if staged_web is not None and str(getattr(staged_web, "status", "") or "").strip().lower() != "enabled":
            staged_error = f"whatsapp_web_session_binding_disabled:{getattr(staged_web, 'binding_id', '')}"
        else:
            staged_error = ""
    else:
        staged_error = ""
    try:
        config = resolve_whatsapp_delivery_config(
            tool_runtime=tool_runtime,
            principal_id=principal_id,
        )
    except Exception as exc:
        errors = [staged_error] if staged_error else []
        errors.append(str(exc) or exc.__class__.__name__)
        return ProactiveOodaDeliveryStatus(
            ready=False,
            errors=tuple(item for item in errors if item),
        )
    return ProactiveOodaDeliveryStatus(
        ready=True,
        selected_channel="whatsapp",
        selected_transport=str(config.get("connector_name") or "whatsapp").strip() or "whatsapp",
        selected_by="delivery_config",
        selected_reason="WhatsApp delivery credentials available",
        recipient_ref=normalized_recipient,
        recipient_ref_hash=_hash_text(normalized_recipient),
        binding_id=str(config.get("binding_id") or "").strip(),
        available_channels=("whatsapp",),
    )


def _normalize_delivery_receipt(
    raw_receipt: object,
    *,
    route: ProactiveOodaDeliveryStatus,
    outbox_row: Any | None,
) -> ProactiveOodaDeliveryReceipt:
    if raw_receipt is None:
        message_ids: tuple[str, ...] = ()
    elif hasattr(raw_receipt, "message_ids"):
        message_ids = tuple(
            str(item or "").strip()
            for item in getattr(raw_receipt, "message_ids", ())
            if str(item or "").strip()
        )
    elif isinstance(raw_receipt, dict):
        if isinstance(raw_receipt.get("message_ids"), (list, tuple)):
            message_ids = tuple(str(item or "").strip() for item in raw_receipt.get("message_ids") or () if str(item or "").strip())
        else:
            raw_message_id = str(raw_receipt.get("message_id") or raw_receipt.get("id") or "").strip()
            message_ids = (raw_message_id,) if raw_message_id else ()
    else:
        message_ids = ()
    telegram_message_ids = message_ids if route.selected_channel == "telegram" else ()
    return ProactiveOodaDeliveryReceipt(
        channel=route.selected_channel,
        delivery_transport=route.selected_transport or route.selected_channel,
        selected_by=route.selected_by,
        selected_reason=route.selected_reason,
        recipient_ref_hash=route.recipient_ref_hash,
        message_ids=message_ids,
        binding_id=route.binding_id,
        outbox_delivery_id=str(getattr(outbox_row, "delivery_id", "") or ""),
        outbox_status=str(getattr(outbox_row, "status", "") or ""),
        telegram_message_ids=telegram_message_ids,
    )


def _send_telegram_message_from_env(*, principal_id: str, text: str) -> dict[str, object]:
    token = str(os.getenv("EA_TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = resolve_proactive_telegram_chat_id(principal_id=principal_id)
    if not token or not chat_id:
        raise RuntimeError("telegram_notification_not_configured")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not bool(payload.get("ok")):
        raise RuntimeError("telegram_sendmessage_failed")
    return dict(payload.get("result") or {})


def _active_delivery_preferences(memory_runtime: Any | None, *, principal_id: str) -> list[Any]:
    if memory_runtime is None or not hasattr(memory_runtime, "list_delivery_preferences"):
        return []
    try:
        return list(memory_runtime.list_delivery_preferences(principal_id=principal_id, status="active", limit=100) or [])
    except Exception:
        return []


def _active_communication_policies(memory_runtime: Any | None, *, principal_id: str) -> list[Any]:
    if memory_runtime is None or not hasattr(memory_runtime, "list_communication_policies"):
        return []
    try:
        return list(memory_runtime.list_communication_policies(principal_id=principal_id, status="active", limit=100) or [])
    except Exception:
        return []


def _active_follow_up_hints(memory_runtime: Any | None, *, principal_id: str) -> tuple[str, ...]:
    if memory_runtime is None or not hasattr(memory_runtime, "list_follow_ups"):
        return ()
    try:
        rows = list(memory_runtime.list_follow_ups(principal_id=principal_id, status="open", limit=100) or [])
    except Exception:
        return ()
    ordered: list[str] = []
    rows.sort(key=lambda row: (str(getattr(row, "due_at", "") or ""), str(getattr(row, "updated_at", "") or "")))
    for row in rows:
        channel = _canonical_channel(getattr(row, "channel_hint", ""))
        if channel and channel not in ordered:
            ordered.append(channel)
    return tuple(ordered)


def _ordered_policy_channels(policies: list[Any]) -> tuple[str, ...]:
    ordered = [channel for _scope, channel in _ordered_policy_channels_with_scope(policies)]
    return tuple(dict.fromkeys(channel for channel in ordered if channel))


def _ordered_policy_channels_with_scope(policies: list[Any]) -> tuple[tuple[str, str], ...]:
    def _scope_rank(policy: Any) -> tuple[int, str]:
        scope = str(getattr(policy, "scope", "") or "").strip().lower()
        try:
            rank = POLICY_SCOPE_ORDER.index(scope)
        except ValueError:
            rank = len(POLICY_SCOPE_ORDER) + 1
        return rank, scope

    ordered: list[tuple[str, str]] = []
    for policy in sorted(policies, key=_scope_rank):
        channel = _canonical_channel(getattr(policy, "preferred_channel", ""))
        scope = str(getattr(policy, "scope", "") or "").strip().lower()
        if channel and (scope, channel) not in ordered:
            ordered.append((scope or "default", channel))
    return tuple(ordered)


def _cadence_allows_digest(cadence: str, *, high_priority: bool) -> tuple[bool, str]:
    normalized = str(cadence or "normal").strip().lower()
    if normalized in {"", "normal", "default", "always"}:
        return True, ""
    if normalized in {"urgent_only", "high_priority_only", "critical_only"}:
        return high_priority, "high_priority_required"
    if normalized in {"disabled", "muted", "never", "off"}:
        return False, "disabled"
    return True, ""


def _digest_has_high_priority(digest: Any | None) -> bool:
    items = tuple(getattr(digest, "items", ()) or ()) if digest is not None else ()
    return any(str(getattr(item, "priority", "") or "").strip().lower() == "high" for item in items)


def _preference_reason(preference: Any, *, route: ProactiveOodaDeliveryStatus) -> str:
    cadence = str(getattr(preference, "cadence", "normal") or "normal").strip().lower()
    if cadence and cadence not in {"normal", "default", "always"}:
        return f"{route.selected_channel} preference selected ({cadence})"
    return f"{route.selected_channel} preference selected"


def _channel_priority_map(channels: tuple[str, ...]) -> dict[str, int]:
    return {channel: index for index, channel in enumerate(channels)}


def _canonical_channel(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"tg", "telegram", "telegram_bot", "telegram_identity"}:
        return "telegram"
    if normalized in {
        "wa",
        "whatsapp",
        "whatsapp_web_session",
        "whatsapp_business",
        "whatsapp_export",
    }:
        return "whatsapp"
    return ""


def _normalize_recipient(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith("+"):
        raw = raw[1:]
    digits = "".join(ch for ch in raw if ch.isdigit())
    return digits or str(value or "").strip()


def _hash_text(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
