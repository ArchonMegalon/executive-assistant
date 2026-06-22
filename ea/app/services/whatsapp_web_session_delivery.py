from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

WHATSAPP_WEB_SESSION_CONNECTOR = "whatsapp_web_session"
WHATSAPP_BUTTON_LABEL_MAX_CHARS = 48
WHATSAPP_BUTTON_CALLBACK_MAX_CHARS = 256
OLD_LADY_HEYY_AI_KEY = "empathetic_slow_typing_old_lady"


def _env_float(name: str, default: float) -> float:
    raw = str(os.getenv(name) or "").strip()
    try:
        return max(0.0, float(raw or str(default)))
    except Exception:
        return max(0.0, default)


def _env_int(name: str, default: int) -> int:
    raw = str(os.getenv(name) or "").strip()
    try:
        return max(1, int(raw or str(default)))
    except Exception:
        return max(1, default)


def _request_timeout_seconds() -> float:
    return _env_float("EA_WHATSAPP_WEB_SESSION_REQUEST_TIMEOUT_SECONDS", 15.0)


def _max_attempts() -> int:
    return _env_int("EA_WHATSAPP_WEB_SESSION_MAX_ATTEMPTS", 2)


def _retry_backoff_seconds() -> float:
    return _env_float("EA_WHATSAPP_WEB_SESSION_RETRY_BACKOFF_SECONDS", 1.0)


def _old_lady_request_timeout_seconds(text: str) -> float:
    max_pre_reply_seconds = _env_int("EA_WHATSAPP_WEB_HEYY_AI_PRE_REPLY_DELAY_MAX_SECONDS", 900)
    typing_ms_per_character = _env_int("EA_WHATSAPP_WEB_HEYY_AI_TYPING_DELAY_MS_PER_CHARACTER", 4000)
    margin_seconds = _env_float("EA_WHATSAPP_WEB_SESSION_LONG_REQUEST_MARGIN_SECONDS", 30.0)
    typing_seconds = (len(str(text or "")) * typing_ms_per_character) / 1000.0
    return max_pre_reply_seconds + typing_seconds + margin_seconds


def _request_timeout_for_message(*, text: str, heyy_ai_key: str) -> float:
    timeout = _request_timeout_seconds()
    if str(heyy_ai_key or "").strip() == OLD_LADY_HEYY_AI_KEY:
        return max(timeout, _old_lady_request_timeout_seconds(text))
    return timeout


def _normalize_recipient(recipient: str) -> str:
    normalized = str(recipient or "").strip()
    if not normalized:
        return ""
    if normalized.startswith("+"):
        normalized = normalized[1:]
    return "".join(ch for ch in normalized if ch.isdigit())


def _normalize_button_rows(buttons: Any) -> list[list[dict[str, str]]]:
    rows: list[list[dict[str, str]]] = []
    for raw_row in list(buttons or []):
        raw_items = raw_row if isinstance(raw_row, (list, tuple)) else [raw_row]
        row: list[dict[str, str]] = []
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
                if len(callback_data) > WHATSAPP_BUTTON_CALLBACK_MAX_CHARS:
                    raise RuntimeError("whatsapp_web_session_button_callback_too_long")
                row.append({"text": label[:WHATSAPP_BUTTON_LABEL_MAX_CHARS], "callback_data": callback_data})
        if row:
            rows.append(row[:3])
    return rows[:8]


def _metadata_value(metadata: dict[str, object], *keys: str) -> str:
    for key in keys:
        value = str(metadata.get(key) or "").strip()
        if value:
            return value
    return ""


def _env_value(*names: str) -> str:
    for name in names:
        value = str(os.getenv(name) or "").strip()
        if value:
            return value
    return ""


def _session_send_url_template(metadata: dict[str, object]) -> str:
    template = _metadata_value(
        metadata,
        "session_send_url_template",
        "send_url_template",
        "endpoint_template",
        "send_url",
    ) or _env_value("EA_WHATSAPP_WEB_SESSION_SEND_URL_TEMPLATE")
    if template:
        return template

    base_url = (
        _metadata_value(metadata, "session_api_base_url", "api_base_url", "base_url")
        or _env_value("EA_WHATSAPP_WEB_SESSION_API_BASE_URL")
    ).rstrip("/")
    if not base_url:
        return ""
    return f"{base_url}/sessions/{{session_ref}}/messages"


def _auth_header_name(metadata: dict[str, object]) -> str:
    return (
        _metadata_value(metadata, "auth_header_name")
        or _env_value("EA_WHATSAPP_WEB_SESSION_AUTH_HEADER_NAME")
        or "Authorization"
    )


def _auth_header_prefix(metadata: dict[str, object]) -> str:
    value = _metadata_value(metadata, "auth_header_prefix")
    if value:
        return value
    env_value = os.getenv("EA_WHATSAPP_WEB_SESSION_AUTH_HEADER_PREFIX")
    return "Bearer " if env_value is None else str(env_value)


def _api_token(metadata: dict[str, object]) -> str:
    return _metadata_value(
        metadata,
        "session_api_token",
        "api_token",
        "access_token",
        "token",
    ) or _env_value("EA_WHATSAPP_WEB_SESSION_API_TOKEN")


def _request_url(template: str, *, session_ref: str, recipient: str, binding: Any) -> str:
    return template.format(
        session_ref=session_ref,
        recipient=recipient,
        binding_id=str(binding.binding_id or "").strip(),
        principal_id=str(binding.principal_id or "").strip(),
    )


@dataclass(frozen=True)
class WhatsAppWebSessionDeliveryReceipt:
    principal_id: str
    binding_id: str
    connector_name: str
    recipient: str
    session_ref: str
    message_ids: tuple[str, ...]
    request_url: str
    binding_status: str = "unknown"
    external_account_ref: str = ""


def _resolve_binding(
    *,
    tool_runtime,
    principal_id: str,
    binding_id: str = "",
    binding: Any | None = None,
) -> Any:
    normalized_principal = str(principal_id or "").strip()
    requested_binding_id = str(binding_id or "").strip()
    if binding is not None:
        candidate = binding
    elif requested_binding_id:
        if tool_runtime is None or not hasattr(tool_runtime, "get_connector_binding"):
            raise RuntimeError("whatsapp_web_session_binding_lookup_unavailable")
        candidate = tool_runtime.get_connector_binding(requested_binding_id)
        if candidate is None:
            raise RuntimeError(f"whatsapp_web_session_binding_not_found:{requested_binding_id}")
    else:
        if tool_runtime is None or not hasattr(tool_runtime, "list_connector_bindings"):
            raise RuntimeError("whatsapp_web_session_binding_required")
        candidates = [
            row
            for row in tool_runtime.list_connector_bindings(normalized_principal, limit=200)
            if str(getattr(row, "connector_name", "") or "").strip() == WHATSAPP_WEB_SESSION_CONNECTOR
        ]
        candidates.sort(key=lambda row: str(getattr(row, "updated_at", "") or "").strip(), reverse=True)
        candidate = next((row for row in candidates if str(getattr(row, "status", "") or "").strip().lower() == "enabled"), None)
        if candidate is None:
            raise RuntimeError("whatsapp_web_session_binding_required")

    if str(candidate.connector_name or "").strip() != WHATSAPP_WEB_SESSION_CONNECTOR:
        raise RuntimeError(f"whatsapp_web_session_connector_mismatch:{candidate.binding_id}")
    if str(candidate.status or "").strip().lower() != "enabled":
        raise RuntimeError(f"whatsapp_web_session_binding_disabled:{candidate.binding_id}")
    if normalized_principal and str(candidate.principal_id or "").strip() != normalized_principal:
        raise RuntimeError("principal_scope_mismatch")
    return candidate


def resolve_whatsapp_web_session_delivery_config(binding: Any) -> dict[str, str]:
    metadata = dict(binding.auth_metadata_json or {})
    session_ref = _metadata_value(metadata, "session_ref", "session_id", "session_name")
    if not session_ref:
        raise RuntimeError("whatsapp_web_session_ref_missing")

    endpoint_template = _session_send_url_template(metadata)
    if not endpoint_template:
        raise RuntimeError("whatsapp_web_session_endpoint_missing")

    return {
        "session_ref": session_ref,
        "endpoint_template": endpoint_template,
        "token": _api_token(metadata),
        "auth_header_name": _auth_header_name(metadata),
        "auth_header_prefix": _auth_header_prefix(metadata),
    }


def _send_session_http_request(
    *,
    request_url: str,
    payload: dict[str, object],
    token: str,
    auth_header_name: str,
    auth_header_prefix: str,
    timeout: float,
) -> dict[str, object]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers[str(auth_header_name or "Authorization")] = f"{auth_header_prefix}{token}".strip()
    request = urllib.request.Request(
        request_url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    last_error: Exception | None = None
    for attempt in range(1, _max_attempts() + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status = int(getattr(response, "status", 200) or 200)
                if status >= 400:
                    raise RuntimeError(f"whatsapp_web_session_http_status_{status}")
                parsed = json.loads(response.read().decode("utf-8") or "{}")
                if not isinstance(parsed, dict):
                    raise RuntimeError("whatsapp_web_session_invalid_response")
                return parsed
        except Exception as exc:
            last_error = exc
            if isinstance(exc, urllib.error.HTTPError):
                status_code = int(getattr(exc, "code") or 500)
                if 400 <= status_code < 500 and status_code != 429:
                    raise RuntimeError("whatsapp_web_session_client_error") from exc
            if attempt >= _max_attempts():
                break
            time.sleep(_retry_backoff_seconds() * attempt)
    if isinstance(last_error, RuntimeError):
        raise last_error
    raise RuntimeError("whatsapp_web_session_send_failed") from last_error


def _extract_message_ids(response: dict[str, object]) -> tuple[str, ...]:
    ids: list[str] = []
    for key in ("messages", "message_ids", "data"):
        value = response.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    message_id = str(item.get("id") or item.get("message_id") or "").strip()
                    if message_id:
                        ids.append(message_id)
                elif isinstance(item, str):
                    ids.append(item.strip())
        elif isinstance(value, str):
            ids.append(value.strip())
    for key in ("message_id", "id"):
        value = str(response.get(key) or "").strip()
        if value:
            ids.append(value)
    return tuple(value for value in ids if value)


def send_whatsapp_web_session_text(
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
) -> WhatsAppWebSessionDeliveryReceipt:
    normalized_recipient = _normalize_recipient(recipient)
    if not normalized_recipient:
        raise RuntimeError("whatsapp_web_session_recipient_missing")
    if not str(text or "").strip():
        raise RuntimeError("whatsapp_web_session_text_missing")

    resolved_binding = _resolve_binding(
        tool_runtime=tool_runtime,
        principal_id=principal_id,
        binding_id=binding_id,
        binding=binding,
    )
    config = resolve_whatsapp_web_session_delivery_config(resolved_binding)
    session_ref = str(config.get("session_ref") or "").strip()
    request_url = _request_url(
        str(config.get("endpoint_template") or ""),
        session_ref=session_ref,
        recipient=normalized_recipient,
        binding=resolved_binding,
    )
    button_rows = _normalize_button_rows(buttons)
    payload: dict[str, object] = {
        "session_ref": session_ref,
        "to": normalized_recipient,
        "type": "text",
        "text": str(text),
        "metadata": {
            "binding_id": resolved_binding.binding_id,
            "connector_name": resolved_binding.connector_name,
            "principal_id": resolved_binding.principal_id,
            "transport": WHATSAPP_WEB_SESSION_CONNECTOR,
        },
    }
    if button_rows:
        payload["buttons"] = button_rows
        payload["metadata"]["button_count"] = sum(len(row) for row in button_rows)  # type: ignore[index]
        payload["metadata"]["button_surface"] = "whatsapp_web_session"
    normalized_ai_key = str(heyy_ai_key or "").strip()
    normalized_ai_name = str(heyy_ai_name or "").strip()
    if normalized_ai_key:
        payload["heyy_ai_key"] = normalized_ai_key
        payload["metadata"]["heyy_ai_key"] = normalized_ai_key  # type: ignore[index]
    if normalized_ai_name:
        payload["heyy_ai_name"] = normalized_ai_name
        payload["metadata"]["heyy_ai_name"] = normalized_ai_name  # type: ignore[index]
    response = _send_session_http_request(
        request_url=request_url,
        payload=payload,
        token=str(config.get("token") or ""),
        auth_header_name=str(config.get("auth_header_name") or "Authorization"),
        auth_header_prefix=str(config.get("auth_header_prefix") or "Bearer "),
        timeout=_request_timeout_for_message(text=str(text), heyy_ai_key=normalized_ai_key),
    )
    return WhatsAppWebSessionDeliveryReceipt(
        principal_id=str(resolved_binding.principal_id or ""),
        binding_id=str(resolved_binding.binding_id or ""),
        connector_name=str(resolved_binding.connector_name or ""),
        recipient=normalized_recipient,
        session_ref=session_ref,
        message_ids=_extract_message_ids(response),
        request_url=request_url,
        binding_status=str(resolved_binding.status or "unknown").strip(),
        external_account_ref=str(resolved_binding.external_account_ref or ""),
    )
