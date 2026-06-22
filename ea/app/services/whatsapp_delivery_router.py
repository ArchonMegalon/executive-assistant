from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from app.services import whatsapp_web_session_delivery


WEB_SESSION_CONNECTOR = whatsapp_web_session_delivery.WHATSAPP_WEB_SESSION_CONNECTOR


@dataclass(frozen=True)
class RoutedWhatsAppDeliveryReceipt:
    principal_id: str
    binding_id: str
    connector_name: str
    recipient: str
    message_ids: tuple[str, ...]
    request_url: str
    binding_status: str
    external_account_ref: str
    delivery_transport: str


def _resolve_binding(
    *,
    tool_runtime,
    principal_id: str = "",
    binding_id: str = "",
    binding: Any | None = None,
) -> Any | None:
    if binding is not None:
        return binding
    normalized_binding_id = str(binding_id or "").strip()
    default_web_binding_id = str(os.getenv("EA_WHATSAPP_WEB_DEFAULT_BINDING_ID") or "").strip()
    if normalized_binding_id or default_web_binding_id:
        if tool_runtime is None or not hasattr(tool_runtime, "get_connector_binding"):
            return None
        candidate = tool_runtime.get_connector_binding(normalized_binding_id or default_web_binding_id)
        if candidate is not None:
            return candidate

    normalized_principal_id = str(principal_id or "").strip()
    if not normalized_principal_id or tool_runtime is None or not hasattr(tool_runtime, "list_connector_bindings"):
        return None
    candidates = [
        row
        for row in tool_runtime.list_connector_bindings(normalized_principal_id, limit=200)
        if str(getattr(row, "connector_name", "") or "").strip() == WEB_SESSION_CONNECTOR
    ]
    candidates.sort(key=lambda row: str(getattr(row, "updated_at", "") or "").strip(), reverse=True)
    candidates.sort(key=lambda row: 0 if str(getattr(row, "status", "") or "").strip().lower() == "enabled" else 1)
    return candidates[0] if candidates else None


def _connector_name(binding: Any | None) -> str:
    return str(getattr(binding, "connector_name", "") or "").strip()


def _transport_for_connector(connector_name: str) -> str:
    normalized = str(connector_name or "").strip()
    if normalized == WEB_SESSION_CONNECTOR:
        return WEB_SESSION_CONNECTOR
    return normalized or "whatsapp"


def _button_fallback_lines(buttons: Any) -> tuple[str, ...]:
    lines: list[str] = []
    index = 1
    for raw_row in list(buttons or []):
        raw_items = raw_row if isinstance(raw_row, (list, tuple)) else [raw_row]
        for raw_item in list(raw_items or []):
            if isinstance(raw_item, dict):
                label = str(
                    raw_item.get("text")
                    or raw_item.get("label")
                    or raw_item.get("title")
                    or raw_item.get("body")
                    or ""
                ).strip()
                callback_data = str(
                    raw_item.get("callback_data")
                    or raw_item.get("callback")
                    or raw_item.get("id")
                    or raw_item.get("button_id")
                    or raw_item.get("value")
                    or ""
                ).strip()
            elif isinstance(raw_item, (list, tuple)) and len(raw_item) >= 2:
                label = str(raw_item[0] or "").strip()
                callback_data = str(raw_item[1] or "").strip()
            else:
                continue
            if label and callback_data:
                lines.append(f"{index}. {label} [{callback_data}]")
                index += 1
    return tuple(lines)


def _text_with_button_fallback(text: str, buttons: Any) -> str:
    lines = _button_fallback_lines(buttons)
    if not lines:
        return str(text or "")
    return f"{str(text or '').rstrip()}\n\nChoices:\n" + "\n".join(lines)


def _legacy_whatsapp_delivery_module():
    try:
        from app.services import whatsapp_delivery
    except Exception as exc:  # pragma: no cover - exercised when local dirty checkout is missing legacy module
        raise RuntimeError("whatsapp_legacy_delivery_unavailable") from exc
    return whatsapp_delivery


def _send_legacy_whatsapp_text(
    *,
    tool_runtime,
    principal_id: str,
    recipient: str,
    text: str,
    binding_id: str = "",
    binding: Any | None = None,
    buttons: Any | None = None,
) -> Any:
    return _legacy_whatsapp_delivery_module().send_whatsapp_text(
        tool_runtime=tool_runtime,
        principal_id=principal_id,
        recipient=recipient,
        text=_text_with_button_fallback(text, buttons),
        binding_id=binding_id,
        binding=binding,
    )


def _routed_receipt(receipt: Any, *, delivery_transport: str) -> RoutedWhatsAppDeliveryReceipt:
    return RoutedWhatsAppDeliveryReceipt(
        principal_id=str(getattr(receipt, "principal_id", "") or ""),
        binding_id=str(getattr(receipt, "binding_id", "") or ""),
        connector_name=str(getattr(receipt, "connector_name", "") or ""),
        recipient=str(getattr(receipt, "recipient", "") or ""),
        message_ids=tuple(str(value or "").strip() for value in getattr(receipt, "message_ids", ()) if str(value or "").strip()),
        request_url=str(getattr(receipt, "request_url", "") or ""),
        binding_status=str(getattr(receipt, "binding_status", "unknown") or "unknown"),
        external_account_ref=str(getattr(receipt, "external_account_ref", "") or ""),
        delivery_transport=delivery_transport,
    )


def send_whatsapp_delivery_text(
    *,
    tool_runtime,
    principal_id: str,
    recipient: str,
    text: str,
    binding_id: str = "",
    binding: Any | None = None,
    buttons: Any | None = None,
    heyy_ai_key: str = "",
    heyy_ai_name: str = "",
) -> RoutedWhatsAppDeliveryReceipt:
    resolved_binding = _resolve_binding(
        tool_runtime=tool_runtime,
        principal_id=principal_id,
        binding_id=binding_id,
        binding=binding,
    )
    connector_name = _connector_name(resolved_binding)
    if connector_name == WEB_SESSION_CONNECTOR:
        receipt = whatsapp_web_session_delivery.send_whatsapp_web_session_text(
            tool_runtime=tool_runtime,
            principal_id=principal_id,
            recipient=recipient,
            text=text,
            binding_id=binding_id,
            binding=resolved_binding,
            buttons=buttons,
            heyy_ai_key=heyy_ai_key,
            heyy_ai_name=heyy_ai_name,
        )
        return _routed_receipt(receipt, delivery_transport=WEB_SESSION_CONNECTOR)

    receipt = _send_legacy_whatsapp_text(
        tool_runtime=tool_runtime,
        principal_id=principal_id,
        recipient=recipient,
        text=text,
        binding_id=binding_id,
        binding=resolved_binding,
        buttons=buttons,
    )
    return _routed_receipt(receipt, delivery_transport=_transport_for_connector(connector_name or getattr(receipt, "connector_name", "")))
