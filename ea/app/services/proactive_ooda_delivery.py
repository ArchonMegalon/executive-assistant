from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from dataclasses import dataclass, replace
from typing import Any, Mapping

from app.services.proactive_ooda_telegram_approval import (
    prepare_proactive_ooda_telegram_approval,
    record_proactive_ooda_telegram_approval_delivery,
)
from app.services.proactive_ooda_telegram_policy import (
    approval_request_needs_telegram_user_action,
    telegram_ooda_text_is_internal_noise,
)
from app.services.proactive_telegram_binding import (
    proactive_telegram_ready,
    resolve_proactive_telegram_target,
)
from app.services.pushbullet_delivery import pushbullet_client_by_key, send_pushbullet_note
from app.services.telegram_delivery import (
    _telegram_bot_registry,
    _telegram_send_json,
    resolve_primary_telegram_binding,
    send_telegram_message_for_principal,
)
from app.services.whatsapp_delivery import resolve_whatsapp_delivery_config
from app.services.whatsapp_delivery_router import WEB_SESSION_CONNECTOR, send_whatsapp_delivery_text
from app.services.whatsapp_web_session_readiness import check_whatsapp_web_session_readiness


SUPPORTED_DELIVERY_CHANNELS = {"telegram", "whatsapp", "pushbullet"}
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
    route_error: str = ""
    recovery_hint: str = ""
    next_action: str = ""


@dataclass(frozen=True)
class ProactiveOodaDeliveryRecovery:
    route_error: str = ""
    recovery_hint: str = ""
    next_action: str = ""


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
    route_error: str = ""
    recovery_hint: str = ""
    next_action: str = ""
    approval_surface: Mapping[str, Any] | None = None


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
        return _with_delivery_recovery(min(preference_candidates, key=lambda item: item[0])[1])

    for scope, channel in _ordered_policy_channels_with_scope(policies):
        route = _channel_route_status(
            channel=channel,
            principal_id=principal_id,
            recipient_ref="",
            tool_runtime=tool_runtime,
        )
        if route.ready:
            ready_channels.append(route.selected_channel)
            return _with_delivery_recovery(
                ProactiveOodaDeliveryStatus(
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
        return _with_delivery_recovery(
            ProactiveOodaDeliveryStatus(
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
        )
    errors.extend(telegram_fallback.errors)

    return _with_delivery_recovery(
        ProactiveOodaDeliveryStatus(
        ready=False,
        available_channels=tuple(dict.fromkeys(ready_channels)),
        errors=tuple(dict.fromkeys(item for item in errors if item)),
        preference_count=len(preferences),
        policy_count=len(policies),
        follow_up_hint_count=len(follow_up_hints),
    )
    )


def send_proactive_ooda_notification(
    *,
    principal_id: str,
    text: str,
    tool_runtime: Any | None = None,
    channel_runtime: Any | None = None,
    memory_runtime: Any | None = None,
    digest: Any | None = None,
    approval_request: Mapping[str, Any] | None = None,
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
    if _telegram_delivery_should_suppress_non_actionable(
        route=route,
        text=text,
        approval_request=approval_request,
    ):
        return ProactiveOodaDeliveryReceipt(
            channel=route.selected_channel,
            delivery_transport=route.selected_transport or route.selected_channel,
            selected_by=route.selected_by,
            selected_reason=route.selected_reason,
            recipient_ref_hash=route.recipient_ref_hash,
            message_ids=(),
            binding_id=route.binding_id,
            route_error="telegram_notification_suppressed_non_actionable",
            recovery_hint="Telegram action-required-only policy suppressed an internal proactive OODA status packet.",
            next_action="review_proactive_ooda_runtime_in_dashboard",
            approval_surface={
                "present": False,
                "channel": "telegram",
                "status": "suppressed_non_actionable",
                "reason": "telegram_action_required_only",
            },
        )

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
            approval_request=approval_request,
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
                    "route_error": receipt.route_error,
                    "recovery_hint": receipt.recovery_hint,
                    "next_action": receipt.next_action,
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
    approval_request: Mapping[str, Any] | None,
) -> object:
    if route.selected_channel == "whatsapp":
        return send_whatsapp_delivery_text(
            tool_runtime=tool_runtime,
            principal_id=principal_id,
            recipient=route.recipient_ref,
            text=text,
            binding_id=route.binding_id,
        )
    if route.selected_channel == "pushbullet":
        title, body = _pushbullet_title_body(text)
        return send_pushbullet_note(
            client_key=route.recipient_ref,
            title=title,
            body=body,
        )
    return _send_telegram_via_route(
        route=route,
        principal_id=principal_id,
        text=text,
        tool_runtime=tool_runtime,
        approval_request=approval_request,
    )


def _telegram_delivery_should_suppress_non_actionable(
    *,
    route: ProactiveOodaDeliveryStatus,
    text: str,
    approval_request: Mapping[str, Any] | None,
) -> bool:
    if route.selected_channel != "telegram":
        return False
    request = dict(approval_request or {})
    action_required_only = _telegram_action_required_only_mode()
    if not request:
        return action_required_only and telegram_ooda_text_is_internal_noise(text)
    if approval_request_needs_telegram_user_action(request):
        return False
    if action_required_only:
        return True
    return telegram_ooda_text_is_internal_noise(
        text,
        request.get("approval_prompt"),
        request.get("approved_execution_mode"),
        request.get("approved_action"),
        request.get("stage_kind"),
        request.get("stage"),
        request.get("decision"),
        request.get("action"),
    )


def _telegram_action_required_only_mode() -> bool:
    raw = str(os.getenv("EA_TELEGRAM_ACTION_REQUIRED_ONLY", "1") or "1").strip().lower()
    return raw in {"1", "true", "yes", "on"}


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
    if normalized == "pushbullet":
        return _pushbullet_route_status(recipient_ref=recipient_ref)
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
    proactive_target = resolve_proactive_telegram_target(principal_id=principal_id)
    proactive_chat_id = str(proactive_target.get("chat_id") or "").strip()
    proactive_bot_key = str(proactive_target.get("bot_key") or "default").strip() or "default"
    proactive_token = str(dict(_telegram_bot_registry().get(proactive_bot_key) or {}).get("token") or "").strip()
    if proactive_chat_id and proactive_token and proactive_telegram_ready(principal_id=principal_id):
        return ProactiveOodaDeliveryStatus(
            ready=True,
            selected_channel="telegram",
            selected_transport="telegram",
            selected_by="env_telegram_fallback",
            selected_reason="Telegram bot token and proactive chat id available",
            recipient_ref_hash=_hash_text(proactive_chat_id),
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
    readiness_error = ""
    staged_error = ""
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
            readiness = check_whatsapp_web_session_readiness(
                tool_runtime=tool_runtime,
                principal_id=principal_id,
                binding=binding,
                probe_session=True,
            )
            if readiness.ready:
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
            readiness_error = _whatsapp_readiness_error(readiness)
        else:
            readiness_error = ""
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
    try:
        config = resolve_whatsapp_delivery_config(
            tool_runtime=tool_runtime,
            principal_id=principal_id,
        )
    except Exception as exc:
        errors = [item for item in (readiness_error, staged_error) if item]
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


def _pushbullet_route_status(*, recipient_ref: str) -> ProactiveOodaDeliveryStatus:
    client_ref = _normalize_pushbullet_client_ref(recipient_ref)
    if not client_ref:
        client_ref = _normalize_pushbullet_client_ref(os.getenv("EA_PUSHBULLET_DEFAULT_CLIENT", ""))
    if not client_ref:
        return ProactiveOodaDeliveryStatus(
            ready=False,
            errors=("pushbullet_client_ref_missing",),
        )
    client = pushbullet_client_by_key(client_ref)
    if client is None:
        return ProactiveOodaDeliveryStatus(
            ready=False,
            errors=(f"pushbullet_client_missing:{client_ref}",),
        )
    if not client.token_present:
        return ProactiveOodaDeliveryStatus(
            ready=False,
            errors=(f"pushbullet_token_missing:{client.client_key}",),
        )
    return ProactiveOodaDeliveryStatus(
        ready=True,
        selected_channel="pushbullet",
        selected_transport="pushbullet",
        selected_by="env_pushbullet_client",
        selected_reason="configured Pushbullet client available",
        recipient_ref=client.client_key,
        recipient_ref_hash=client.email_sha256 or _hash_text(client.client_key),
        available_channels=("pushbullet",),
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
    elif hasattr(raw_receipt, "push_id_hash"):
        push_id_hash = str(getattr(raw_receipt, "push_id_hash", "") or "").strip()
        message_ids = (push_id_hash,) if push_id_hash else ()
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
        route_error=route.route_error,
        recovery_hint=route.recovery_hint,
        next_action=route.next_action,
        approval_surface=_extract_approval_surface(raw_receipt),
    )


def _send_telegram_via_route(
    *,
    route: ProactiveOodaDeliveryStatus,
    principal_id: str,
    text: str,
    tool_runtime: Any | None,
    approval_request: Mapping[str, Any] | None,
) -> dict[str, object]:
    receipts: list[object] = []
    prompt = _proactive_ooda_approval_prompt(
        route=route,
        principal_id=principal_id,
        tool_runtime=tool_runtime,
        approval_request=approval_request,
    )
    prompt_text = str(prompt.get("prompt_text") or "").strip()
    inline_buttons = list(prompt.get("inline_buttons") or [])
    url_buttons = list(prompt.get("url_buttons") or [])
    approval_surface = dict(prompt.get("approval_surface") or {})
    record_path = str(prompt.get("record_path") or "").strip()
    if prompt_text and (inline_buttons or url_buttons):
        try:
            prompt_receipt = _send_telegram_message_for_route(
                route=route,
                principal_id=principal_id,
                text=prompt_text,
                tool_runtime=tool_runtime,
                inline_buttons=inline_buttons,
                url_buttons=url_buttons,
            )
            prompt_message_ids = _receipt_message_ids(prompt_receipt)
            if record_path:
                record_proactive_ooda_telegram_approval_delivery(
                    record_path=record_path,
                    message_ids=prompt_message_ids,
                    status="pending",
                )
            if approval_surface:
                approval_surface["message_ids"] = prompt_message_ids
                approval_surface["message_count"] = len(prompt_message_ids)
            receipts.append(prompt_receipt)
        except Exception:
            if record_path:
                try:
                    record_proactive_ooda_telegram_approval_delivery(
                        record_path=record_path,
                        message_ids=(),
                        status="delivery_failed",
                        delivery_error_code="telegram_approval_prompt_delivery_failed",
                    )
                except Exception:
                    pass
            if approval_surface:
                approval_surface["status"] = "delivery_failed"
                approval_surface["message_ids"] = ()
                approval_surface["message_count"] = 0
                approval_surface["delivery_error_code"] = "telegram_approval_prompt_delivery_failed"
            raise RuntimeError("telegram_approval_prompt_delivery_failed")
    elif _approval_request_requires_telegram_action(approval_request):
        raise RuntimeError("proactive_ooda_action_surface_unavailable")
    else:
        receipts.append(_send_telegram_message_for_route(route=route, principal_id=principal_id, text=text, tool_runtime=tool_runtime))
    message_ids: list[str] = []
    for receipt in receipts:
        message_ids.extend(_receipt_message_ids(receipt))
    return {"message_ids": tuple(message_ids), "approval_surface": approval_surface}


def _approval_request_requires_telegram_action(approval_request: Mapping[str, Any] | None) -> bool:
    return approval_request_needs_telegram_user_action(approval_request)


def _send_telegram_message_for_route(
    *,
    route: ProactiveOodaDeliveryStatus,
    principal_id: str,
    text: str,
    tool_runtime: Any | None,
    inline_buttons: list[list[tuple[str, str]]] | None = None,
    url_buttons: list[list[tuple[str, str]]] | None = None,
) -> object:
    if tool_runtime is not None and route.selected_by != "env_telegram_fallback":
        if inline_buttons or url_buttons:
            return send_telegram_message_for_principal(
                tool_runtime,
                principal_id=principal_id,
                text=text,
                inline_buttons=inline_buttons,
                url_buttons=url_buttons,
            )
        return send_telegram_message_for_principal(
            tool_runtime,
            principal_id=principal_id,
            text=text,
        )
    return _send_telegram_message_from_env(
        principal_id=principal_id,
        text=text,
        inline_buttons=inline_buttons,
        url_buttons=url_buttons,
    )


def _send_telegram_message_from_env(
    *,
    principal_id: str,
    text: str,
    inline_buttons: list[list[tuple[str, str]]] | None = None,
    url_buttons: list[list[tuple[str, str]]] | None = None,
) -> dict[str, object]:
    target = resolve_proactive_telegram_target(principal_id=principal_id)
    chat_id = str(target.get("chat_id") or "").strip()
    bot_key = str(target.get("bot_key") or "default").strip() or "default"
    token = str(dict(_telegram_bot_registry().get(bot_key) or {}).get("token") or "").strip()
    if not token or not chat_id:
        raise RuntimeError("telegram_notification_not_configured")
    payload: dict[str, object] = {"chat_id": chat_id, "text": text}
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
    return _telegram_send_json(
        token=token,
        method="sendMessage",
        payload=payload,
    )


def _receipt_message_ids(receipt: object) -> tuple[str, ...]:
    if hasattr(receipt, "message_ids"):
        return tuple(str(item or "").strip() for item in getattr(receipt, "message_ids", ()) if str(item or "").strip())
    if isinstance(receipt, dict):
        raw_ids = receipt.get("message_ids")
        if isinstance(raw_ids, (list, tuple)):
            return tuple(str(item or "").strip() for item in raw_ids if str(item or "").strip())
        message_id = str(receipt.get("message_id") or "").strip()
        return (message_id,) if message_id else ()
    return ()


def _extract_approval_surface(raw_receipt: object) -> dict[str, Any]:
    if hasattr(raw_receipt, "approval_surface"):
        value = getattr(raw_receipt, "approval_surface")
        return dict(value) if isinstance(value, Mapping) else {}
    if isinstance(raw_receipt, dict):
        value = raw_receipt.get("approval_surface")
        return dict(value) if isinstance(value, Mapping) else {}
    return {}


def _proactive_ooda_approval_prompt(
    *,
    route: ProactiveOodaDeliveryStatus,
    principal_id: str,
    tool_runtime: Any | None,
    approval_request: Mapping[str, Any] | None,
) -> dict[str, Any]:
    request = dict(approval_request or {})
    packet_ref = str(request.get("packet_ref") or "").strip()
    staged_artifact_ref = str(request.get("staged_artifact_ref") or "").strip()
    if route.selected_channel != "telegram" or not packet_ref or not staged_artifact_ref:
        return {"prompt_text": "", "inline_buttons": [], "url_buttons": [], "approval_surface": {}, "record_path": ""}
    if not approval_request_needs_telegram_user_action(request):
        return {"prompt_text": "", "inline_buttons": [], "url_buttons": [], "approval_surface": {}, "record_path": ""}
    chat_id, bot_token = _telegram_route_identity(route=route, principal_id=principal_id, tool_runtime=tool_runtime)
    if not chat_id or not bot_token:
        return {"prompt_text": "", "inline_buttons": [], "url_buttons": [], "approval_surface": {}, "record_path": ""}
    prepared = prepare_proactive_ooda_telegram_approval(
        principal_id=principal_id,
        packet_ref=packet_ref,
        staged_artifact_ref=staged_artifact_ref,
        approval_prompt=str(request.get("approval_prompt") or "").strip(),
        staged_action_url=str(request.get("staged_action_url") or "").strip(),
        approved_execution_mode=str(request.get("approved_execution_mode") or "").strip(),
        approved_action=str(request.get("approved_action") or "").strip(),
        chat_id=chat_id,
        bot_token=bot_token,
        state_path=os.getenv("EA_PROACTIVE_OODA_STATE_PATH", "state/proactive_ooda_notified.json"),
        receipt_path=os.getenv("EA_PROACTIVE_OODA_RECEIPT_PATH", ""),
    )
    inline_buttons = list(prepared.get("inline_buttons") or [])
    url_buttons = list(prepared.get("url_buttons") or [])
    if not inline_buttons and not url_buttons:
        return {"prompt_text": "", "inline_buttons": [], "url_buttons": [], "approval_surface": {}, "record_path": ""}
    prompt_text = str(request.get("approval_prompt") or "").strip()
    if not prompt_text:
        prompt_text = "Record your proactive OODA decision for this staged packet. No purchase, booking, or send will happen without explicit approval."
    approval_surface = {
        "present": True,
        "channel": "telegram",
        "status": str(prepared.get("status") or "pending").strip() or "pending",
        "callback_token_sha256": str(prepared.get("callback_token_sha256") or "").strip(),
        "expires_at": str(prepared.get("expires_at") or "").strip(),
        "packet_ref_sha256": str(prepared.get("packet_ref_sha256") or "").strip(),
        "staged_artifact_sha256": str(prepared.get("staged_artifact_ref_sha256") or "").strip(),
        "approval_prompt_sha256": str(prepared.get("approval_prompt_sha256") or "").strip(),
        "staged_action_url_sha256": str(prepared.get("staged_action_url_sha256") or "").strip(),
        "inline_button_count": sum(len(row) for row in inline_buttons),
        "url_button_count": sum(len(row) for row in url_buttons),
        "message_ids": (),
        "message_count": 0,
        "delivery_error_code": "",
        "privacy": {
            "raw_callback_token_stored": False,
            "raw_packet_ref_stored": False,
            "raw_staged_artifact_ref_stored": False,
            "raw_approval_prompt_stored": False,
            "raw_staged_action_url_stored": False,
        },
    }
    return {
        "prompt_text": prompt_text,
        "inline_buttons": inline_buttons,
        "url_buttons": url_buttons,
        "approval_surface": approval_surface,
        "record_path": str(prepared.get("record_path") or ""),
    }


def _telegram_route_identity(
    *,
    route: ProactiveOodaDeliveryStatus,
    principal_id: str,
    tool_runtime: Any | None,
) -> tuple[str, str]:
    if tool_runtime is not None and route.selected_by != "env_telegram_fallback":
        try:
            binding = resolve_primary_telegram_binding(tool_runtime, principal_id=principal_id)
        except Exception:
            binding = None
        if binding is not None:
            metadata = dict(getattr(binding, "auth_metadata_json", {}) or {})
            bot_key = str(metadata.get("bot_key") or "default").strip() or "default"
            token = str(dict(_telegram_bot_registry().get(bot_key) or {}).get("token") or "").strip()
            chat_id = str(metadata.get("default_chat_ref") or getattr(binding, "external_account_ref", "") or "").strip()
            if chat_id and token:
                return chat_id, token
    target = resolve_proactive_telegram_target(principal_id=principal_id)
    chat_id = str(target.get("chat_id") or "").strip()
    bot_key = str(target.get("bot_key") or "default").strip() or "default"
    token = str(dict(_telegram_bot_registry().get(bot_key) or {}).get("token") or "").strip()
    return chat_id, token


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
    if normalized in {"pb", "pushbullet", "pushbullet_note", "pushbullet_link"}:
        return "pushbullet"
    return ""


def _normalize_recipient(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith("+"):
        raw = raw[1:]
    digits = "".join(ch for ch in raw if ch.isdigit())
    return digits or str(value or "").strip()


def _normalize_pushbullet_client_ref(value: object) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return "".join(ch for ch in normalized if ch.isalnum() or ch == "_").strip("_")


def _pushbullet_title_body(text: str) -> tuple[str, str]:
    normalized = str(text or "").strip()
    if not normalized:
        return "EA OODA", ""
    first_line = next((line.strip() for line in normalized.splitlines() if line.strip()), "")
    title = first_line[:120].rstrip() or "EA OODA"
    return title, normalized


def _hash_text(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def proactive_ooda_delivery_recovery(
    error_codes: str | tuple[str, ...] | list[str],
    *,
    ready: bool | None = None,
) -> ProactiveOodaDeliveryRecovery:
    errors = _normalized_delivery_errors(error_codes)
    actionable = next((item for item in errors if not item.startswith("delivery_preference_ineligible:")), "")
    if not actionable:
        if ready is False:
            actionable = errors[0] if errors else "delivery_route_unavailable"
        else:
            return ProactiveOodaDeliveryRecovery()
    return _guidance_for_delivery_error(actionable)


def _with_delivery_recovery(status: ProactiveOodaDeliveryStatus) -> ProactiveOodaDeliveryStatus:
    recovery = proactive_ooda_delivery_recovery(status.errors, ready=status.ready)
    return replace(
        status,
        route_error=status.route_error or recovery.route_error,
        recovery_hint=status.recovery_hint or recovery.recovery_hint,
        next_action=status.next_action or recovery.next_action,
    )


def _normalized_delivery_errors(error_codes: str | tuple[str, ...] | list[str]) -> tuple[str, ...]:
    if isinstance(error_codes, str):
        items = (error_codes,)
    else:
        items = tuple(error_codes or ())
    return tuple(dict.fromkeys(str(item or "").strip() for item in items if str(item or "").strip()))


def _guidance_for_delivery_error(error_code: str) -> ProactiveOodaDeliveryRecovery:
    normalized = str(error_code or "").strip()
    if not normalized:
        return ProactiveOodaDeliveryRecovery()
    if normalized == "whatsapp_recipient_missing":
        return ProactiveOodaDeliveryRecovery(
            route_error=normalized,
            recovery_hint="Add a WhatsApp recipient ref or phone number on the active delivery preference before routing there.",
            next_action="set_whatsapp_recipient_ref",
        )
    if normalized.startswith("whatsapp_web_session_binding_disabled:"):
        return ProactiveOodaDeliveryRecovery(
            route_error=normalized,
            recovery_hint="Enable the staged WhatsApp Web binding or replace it with an enabled session binding before preferring WhatsApp.",
            next_action="enable_whatsapp_web_binding",
        )
    if normalized == "whatsapp_delivery_config_missing":
        return ProactiveOodaDeliveryRecovery(
            route_error=normalized,
            recovery_hint="Seed or enable a WhatsApp delivery binding with send credentials before preferring WhatsApp.",
            next_action="configure_whatsapp_delivery_binding",
        )
    if normalized.startswith("whatsapp_web_session_not_ready:qr_required"):
        return ProactiveOodaDeliveryRecovery(
            route_error=normalized,
            recovery_hint="Scan the WhatsApp Web QR code and re-activate the session before preferring WhatsApp again.",
            next_action="scan_whatsapp_web_qr",
        )
    if normalized.startswith("whatsapp_web_session_not_ready:"):
        return ProactiveOodaDeliveryRecovery(
            route_error=normalized,
            recovery_hint="Restore or re-authenticate the WhatsApp Web session and confirm it reports ready before preferring WhatsApp.",
            next_action="restore_whatsapp_web_session",
        )
    if normalized == "telegram_notification_not_configured":
        return ProactiveOodaDeliveryRecovery(
            route_error=normalized,
            recovery_hint="Link Telegram delivery or set the proactive Telegram chat so Telegram can be used as the fallback route.",
            next_action="configure_telegram_proactive_delivery",
        )
    if normalized == "pushbullet_client_ref_missing":
        return ProactiveOodaDeliveryRecovery(
            route_error=normalized,
            recovery_hint="Set a Pushbullet client key on the delivery preference recipient_ref or configure EA_PUSHBULLET_DEFAULT_CLIENT before preferring Pushbullet.",
            next_action="set_pushbullet_client_ref",
        )
    if normalized.startswith("pushbullet_client_missing:"):
        return ProactiveOodaDeliveryRecovery(
            route_error=normalized,
            recovery_hint="Create the named Pushbullet client env slot before preferring Pushbullet for proactive delivery.",
            next_action="configure_pushbullet_client",
        )
    if normalized.startswith("pushbullet_token_missing:"):
        return ProactiveOodaDeliveryRecovery(
            route_error=normalized,
            recovery_hint="Create a Pushbullet account access token, store it in the configured token env var, and rerun Pushbullet readiness before preferring that client.",
            next_action="create_pushbullet_access_token",
        )
    if normalized.startswith("pushbullet_http_401") or normalized.startswith("pushbullet_http_403"):
        return ProactiveOodaDeliveryRecovery(
            route_error=normalized,
            recovery_hint="Rotate the Pushbullet access token and verify it belongs to the intended account before retrying delivery.",
            next_action="rotate_pushbullet_access_token",
        )
    if normalized.startswith("pushbullet_"):
        return ProactiveOodaDeliveryRecovery(
            route_error=normalized,
            recovery_hint="Inspect Pushbullet client readiness and provider response before retrying proactive delivery.",
            next_action="inspect_pushbullet_delivery",
        )
    if normalized.startswith("telegram_sendmessage_http_401"):
        return ProactiveOodaDeliveryRecovery(
            route_error=normalized,
            recovery_hint="Refresh the Telegram bot token and confirm the configured bot registry entry still matches the intended bot before retrying.",
            next_action="rotate_telegram_bot_token",
        )
    if normalized.startswith("telegram_sendmessage_http_429"):
        return ProactiveOodaDeliveryRecovery(
            route_error=normalized,
            recovery_hint="Telegram rate-limited the proactive send. Wait for the limit to clear, then retry the delivery.",
            next_action="wait_for_telegram_rate_limit_reset",
        )
    if normalized.startswith("telegram_sendmessage_http_400") or normalized.startswith("telegram_sendmessage_http_403"):
        return ProactiveOodaDeliveryRecovery(
            route_error=normalized,
            recovery_hint="Open the Telegram chat with the configured bot, press Start if needed, and confirm the proactive chat binding still points at the intended chat before retrying.",
            next_action="repair_telegram_proactive_delivery",
        )
    if normalized.startswith("telegram_sendmessage_"):
        return ProactiveOodaDeliveryRecovery(
            route_error=normalized,
            recovery_hint="Inspect the Telegram delivery binding, bot registry, and target chat before retrying proactive delivery.",
            next_action="inspect_telegram_proactive_delivery",
        )
    if normalized.startswith("delivery_channel_unsupported:"):
        return ProactiveOodaDeliveryRecovery(
            route_error=normalized,
            recovery_hint="Use telegram, whatsapp, or pushbullet for proactive delivery preferences and policies.",
            next_action="use_supported_delivery_channel",
        )
    if normalized == "delivery_route_unavailable":
        return ProactiveOodaDeliveryRecovery(
            route_error=normalized,
            recovery_hint="Inspect channel bindings, recipients, and fallback delivery config before retrying proactive delivery.",
            next_action="inspect_proactive_delivery_route",
        )
    return ProactiveOodaDeliveryRecovery(
        route_error=normalized,
        recovery_hint="Inspect the proactive delivery route configuration and provider readiness before retrying.",
        next_action="inspect_proactive_delivery_route",
    )


def _whatsapp_readiness_error(readiness: Any) -> str:
    probe_reason = str(getattr(readiness, "probe_reason", "") or "").strip()
    reason = str(getattr(readiness, "reason", "") or "").strip()
    if probe_reason:
        return f"whatsapp_web_session_not_ready:{probe_reason}"
    if reason:
        return f"whatsapp_web_session_not_ready:{reason}"
    return "whatsapp_web_session_not_ready:unknown"
