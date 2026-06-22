from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from app.domain.models import ConnectorBinding
try:
    from app.services.whatsapp_onboarding_service import (
        WHATSAPP_BUSINESS_CONNECTOR,
        WHATSAPP_EXPORT_CONNECTOR,
    )
except ModuleNotFoundError:
    WHATSAPP_BUSINESS_CONNECTOR = "whatsapp_business"
    WHATSAPP_EXPORT_CONNECTOR = "whatsapp_export"


_WHATSAPP_CONNECTOR_NAMES = {WHATSAPP_BUSINESS_CONNECTOR, WHATSAPP_EXPORT_CONNECTOR}


def _env_int(name: str, default: int) -> int:
    raw = str(os.getenv(name) or "").strip()
    try:
        return max(1, int(raw or str(default)))
    except Exception:
        return max(1, default)


def _env_float(name: str, default: float) -> float:
    raw = str(os.getenv(name) or "").strip()
    try:
        return max(0.0, float(raw or str(default)))
    except Exception:
        return max(0.0, default)


def _whatsapp_max_attempts() -> int:
    return _env_int("EA_WHATSAPP_SERVICE_MAX_ATTEMPTS", 3)


def _whatsapp_retry_backoff_seconds() -> float:
    return _env_float("EA_WHATSAPP_SERVICE_RETRY_BACKOFF_SECONDS", 1.2)


def _whatsapp_request_timeout_seconds() -> float:
    return _env_float("EA_WHATSAPP_REQUEST_TIMEOUT_SECONDS", 15.0)


def _whatsapp_endpoint_template() -> str:
    raw_template = str(
        os.getenv("EA_WHATSAPP_SEND_URL_TEMPLATE")
        or os.getenv("EA_HEYY_SEND_URL_TEMPLATE")
        or ""
    ).strip()
    if raw_template:
        return raw_template
    base = str(os.getenv("EA_WHATSAPP_GRAPH_API_BASE_URL") or os.getenv("EA_HEYY_GRAPH_API_BASE_URL") or "https://graph.facebook.com").strip().rstrip("/")
    version = str(os.getenv("EA_WHATSAPP_GRAPH_API_VERSION") or os.getenv("EA_HEYY_GRAPH_API_VERSION") or "v20.0").strip().strip("/")
    return f"{base}/{version}" + "/{phone_number_id}/messages"


def _whatsapp_auth_header_name() -> str:
    value = str(
        os.getenv("EA_WHATSAPP_AUTH_HEADER_NAME")
        or os.getenv("EA_HEYY_AUTH_HEADER_NAME")
        or "Authorization"
    ).strip()
    return value or "Authorization"


def _whatsapp_auth_header_prefix() -> str:
    return str(
        os.getenv("EA_WHATSAPP_AUTH_HEADER_PREFIX")
        or os.getenv("EA_HEYY_AUTH_HEADER_PREFIX")
        or "Bearer "
    )


def _parse_json_object(raw: str) -> dict[str, dict[str, object]]:
    try:
        payload = json.loads(raw or "{}")
    except Exception:
        return {}
    if isinstance(payload, dict):
        normalized: dict[str, dict[str, object]] = {}
        for key, value in payload.items():
            if not isinstance(key, str):
                continue
            if isinstance(value, dict):
                normalized[key.strip()] = {
                    str(vk).strip(): vv for vk, vv in value.items() if str(vk).strip()
                }
        return normalized
    return {}


def _whatsapp_credential_registry() -> dict[str, dict[str, object]]:
    registry = _parse_json_object(
        str(os.getenv("EA_WHATSAPP_CREDENTIAL_REGISTRY_JSON") or os.getenv("EA_HEYY_CREDENTIAL_REGISTRY_JSON") or "")
    )
    legacy_token = str(
        os.getenv("EA_WHATSAPP_DEFAULT_AUTH_TOKEN")
        or os.getenv("EA_HEYY_AUTH_TOKEN")
        or os.getenv("EA_WHATSAPP_API_TOKEN")
        or ""
    ).strip()
    legacy_phone_id = str(
        os.getenv("EA_WHATSAPP_DEFAULT_PHONE_NUMBER_ID")
        or os.getenv("EA_HEYY_PHONE_NUMBER_ID")
        or ""
    ).strip()
    legacy_from_principal = str(
        os.getenv("EA_WHATSAPP_DEFAULT_PRINCIPAL_ID")
        or os.getenv("EA_HEYY_DEFAULT_PRINCIPAL_ID")
        or ""
    ).strip()
    if legacy_token or legacy_phone_id:
        registry.setdefault(
            legacy_from_principal or "default",
            {
                "token": legacy_token,
                "phone_number_id": legacy_phone_id,
                "endpoint_template": str(
                    os.getenv("EA_WHATSAPP_SEND_URL_TEMPLATE") or os.getenv("EA_HEYY_SEND_URL_TEMPLATE") or ""
                ).strip(),
                "auth_header_name": _whatsapp_auth_header_name(),
                "auth_header_prefix": _whatsapp_auth_header_prefix(),
            },
        )
    return registry


def _value_from_candidates(metadata: dict[str, object], candidates: tuple[str, ...]) -> str:
    for candidate in candidates:
        value = str(metadata.get(candidate) or "").strip()
        if value:
            return value
    return ""


def _extract_whatsapp_credentials_from_metadata(metadata: dict[str, object]) -> dict[str, str]:
    return {
        "token": _value_from_candidates(
            metadata,
            ("access_token", "token", "api_token", "api_key", "heyy_access_token", "bearer_token"),
        ),
        "phone_number_id": _value_from_candidates(
            metadata,
            ("phone_number_id", "whatsapp_phone_number_id", "phone_number", "recipient", "external_account_ref", "account_id"),
        ),
        "endpoint_template": _value_from_candidates(
            metadata,
            ("endpoint_template", "send_url_template"),
        ),
        "auth_header_name": _value_from_candidates(
            metadata,
            ("auth_header_name",),
        ),
        "auth_header_prefix": _value_from_candidates(
            metadata,
            ("auth_header_prefix",),
        ),
    }


def _coerce_binding_principal_id(candidates: tuple[str, ...]) -> tuple[str, ...]:
    normalized = [str(value or "").strip() for value in candidates]
    normalized.extend(
        [
            str(os.getenv("EA_DEFAULT_PRINCIPAL_ID") or "").strip(),
            str(os.getenv("EA_HEYY_DEFAULT_PRINCIPAL_ID") or "").strip(),
            str(os.getenv("EA_DEFAULT_PRINCIPAL") or "").strip(),
            "principal-default",
        ]
    )
    deduped: list[str] = []
    for value in normalized:
        if value and value not in deduped:
            deduped.append(value)
    return tuple(deduped)


def _normalize_recipient(recipient: str) -> str:
    normalized = str(recipient or "").strip()
    if not normalized:
        return ""
    if normalized.startswith("+"):
        normalized = normalized[1:]
    return "".join(ch for ch in normalized if ch.isdigit())


def _whatsapp_endpoint(phone_number_id: str, endpoint_template: str) -> str:
    template = str(endpoint_template or "").strip()
    if not template:
        template = _whatsapp_endpoint_template()
    return template.format(phone_number_id=phone_number_id)


@dataclass(frozen=True)
class WhatsAppDeliveryReceipt:
    principal_id: str
    binding_id: str
    connector_name: str
    recipient: str
    message_ids: tuple[str, ...]
    request_url: str
    binding_status: str = "unknown"
    external_account_ref: str = ""


def _read_binding_config(
    binding: ConnectorBinding,
    *,
    endpoint_template: str,
    auth_header_name: str,
    auth_header_prefix: str,
) -> dict[str, str]:
    metadata = dict(binding.auth_metadata_json or {})
    extracted = _extract_whatsapp_credentials_from_metadata(metadata)
    token = extracted.get("token", "")
    phone_number_id = extracted.get("phone_number_id", "")
    if not token:
        return {}
    return {
        "binding_id": str(binding.binding_id or "").strip(),
        "principal_id": str(binding.principal_id or "").strip(),
        "connector_name": str(binding.connector_name or "").strip(),
        "external_account_ref": str(binding.external_account_ref or "").strip(),
        "token": token,
        "phone_number_id": phone_number_id or str(binding.external_account_ref or "").strip(),
        "endpoint_template": extracted.get("endpoint_template", "") or endpoint_template,
        "auth_header_name": extracted.get("auth_header_name", "") or auth_header_name,
        "auth_header_prefix": extracted.get("auth_header_prefix", "") or auth_header_prefix,
        "status": str(binding.status or "").strip().lower(),
    }


def _read_registry_config(
    *,
    principal_id: str,
    endpoint_template: str,
    auth_header_name: str,
    auth_header_prefix: str,
) -> dict[str, str]:
    registry = _whatsapp_credential_registry()
    for candidate in _coerce_binding_principal_id((str(principal_id or "").strip(),)):
        value = dict(registry.get(candidate) or {})
        if not value:
            continue
        token = str(value.get("token") or "").strip()
        if not token:
            continue
        return {
            "binding_id": "",
            "principal_id": candidate,
            "connector_name": "",
            "external_account_ref": str(value.get("external_account_ref") or "").strip(),
            "token": token,
            "phone_number_id": str(value.get("phone_number_id") or value.get("phone_number") or "").strip(),
            "endpoint_template": str(value.get("endpoint_template") or endpoint_template).strip(),
            "auth_header_name": str(value.get("auth_header_name") or auth_header_name).strip() or auth_header_name,
            "auth_header_prefix": str(value.get("auth_header_prefix") or auth_header_prefix).strip() or auth_header_prefix,
            "status": "enabled",
        }
    return {}


def resolve_whatsapp_delivery_config(
    *,
    tool_runtime,
    principal_id: str,
    binding_id: str = "",
    binding: ConnectorBinding | None = None,
) -> dict[str, str]:
    normalized_principal_id = str(principal_id or "").strip()
    if binding is None and tool_runtime is None:
        resolved = _read_registry_config(
            principal_id=normalized_principal_id,
            endpoint_template=_whatsapp_endpoint_template(),
            auth_header_name=_whatsapp_auth_header_name(),
            auth_header_prefix=_whatsapp_auth_header_prefix(),
        )
        if resolved:
            return resolved
        raise RuntimeError("whatsapp_delivery_config_missing")
    endpoint_template = _whatsapp_endpoint_template()
    auth_header_name = _whatsapp_auth_header_name()
    auth_header_prefix = _whatsapp_auth_header_prefix()
    if binding is not None:
        cfg = _read_binding_config(
            binding,
            endpoint_template=endpoint_template,
            auth_header_name=auth_header_name,
            auth_header_prefix=auth_header_prefix,
        )
        if cfg:
            return cfg
    elif normalized_principal_id and binding_id:
        candidate = tool_runtime.get_connector_binding(binding_id)
        if candidate is not None and str(candidate.principal_id or "").strip() == normalized_principal_id:
            cfg = _read_binding_config(
                candidate,
                endpoint_template=endpoint_template,
                auth_header_name=auth_header_name,
                auth_header_prefix=auth_header_prefix,
            )
            if cfg:
                return cfg
    elif tool_runtime is not None and normalized_principal_id:
        candidates: list[ConnectorBinding] = []
        for row in tool_runtime.list_connector_bindings(normalized_principal_id, limit=200):
            if str(row.connector_name or "").strip() not in _WHATSAPP_CONNECTOR_NAMES:
                continue
            candidates.append(row)
        status_rank = {"enabled": 2, "imported": 1, "ready": 1, "planned": 0}
        candidates.sort(
            key=lambda item: (
                status_rank.get(str(item.status or "").strip().lower(), 0),
                str(item.updated_at or "").strip(),
            ),
            reverse=True,
        )
        for candidate in candidates:
            cfg = _read_binding_config(
                candidate,
                endpoint_template=endpoint_template,
                auth_header_name=auth_header_name,
                auth_header_prefix=auth_header_prefix,
            )
            if cfg:
                return cfg
    resolved = _read_registry_config(
        principal_id=normalized_principal_id,
        endpoint_template=endpoint_template,
        auth_header_name=auth_header_name,
        auth_header_prefix=auth_header_prefix,
    )
    if resolved:
        return resolved
    raise RuntimeError("whatsapp_delivery_config_missing")


def _send_whatsapp_http_request(
    *,
    request_url: str,
    payload: dict[str, object],
    token: str,
    auth_header_name: str,
    auth_header_prefix: str,
    timeout: float,
) -> dict[str, object]:
    request = urllib.request.Request(
        request_url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            str(auth_header_name): f"{auth_header_prefix}{token}".strip(),
        },
    )
    last_error: Exception | None = None
    for attempt in range(1, _whatsapp_max_attempts() + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if int(getattr(response, "status", 200) or 200) >= 400:
                    raise RuntimeError(f"whatsapp_http_status_{int(getattr(response, 'status', 400))}")
                body = response.read().decode("utf-8")
                parsed = json.loads(body or "{}")
                if not isinstance(parsed, dict):
                    raise RuntimeError("whatsapp_send_invalid_response")
                return parsed
        except Exception as exc:
            last_error = exc
            if attempt >= _whatsapp_max_attempts():
                break
            if isinstance(exc, urllib.error.HTTPError):
                status_code = int(getattr(exc, "code") or 500)
                if 400 <= status_code < 500 and status_code != 429:
                    raise RuntimeError("whatsapp_client_error") from exc
            time.sleep(_whatsapp_retry_backoff_seconds() * attempt)
    if isinstance(last_error, RuntimeError):
        raise last_error
    raise RuntimeError("whatsapp_send_failed") from last_error


def _extract_message_ids(response: dict[str, object]) -> tuple[str, ...]:
    ids: list[str] = []
    for key in ("messages", "data", "message_ids"):
        value = response.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    message_id = str(item.get("id") or "").strip()
                    if message_id:
                        ids.append(message_id)
                elif isinstance(item, str):
                    ids.append(str(item).strip())
        elif isinstance(value, str):
            normalized = str(value).strip()
            if normalized:
                ids.append(normalized)
    if not ids:
        nested = response.get("message") or response.get("id")
        if isinstance(nested, str):
            normalized = str(nested).strip()
            if normalized:
                ids.append(normalized)
    return tuple(value for value in ids if value)


def send_whatsapp_text(
    *,
    tool_runtime,
    principal_id: str,
    recipient: str,
    text: str,
    binding_id: str = "",
    binding: ConnectorBinding | None = None,
) -> WhatsAppDeliveryReceipt:
    normalized_recipient = _normalize_recipient(recipient)
    if not normalized_recipient:
        raise RuntimeError("whatsapp_recipient_missing")
    if not str(text or "").strip():
        raise RuntimeError("whatsapp_text_missing")
    config = resolve_whatsapp_delivery_config(
        tool_runtime=tool_runtime,
        principal_id=principal_id,
        binding_id=str(binding_id or "").strip(),
        binding=binding,
    )
    if not config:
        raise RuntimeError("whatsapp_delivery_config_missing")
    phone_number_id = str(config.get("phone_number_id") or "").strip()
    token = str(config.get("token") or "").strip()
    if not token:
        raise RuntimeError("whatsapp_access_token_missing")
    if not phone_number_id:
        raise RuntimeError("whatsapp_phone_id_missing")
    request_url = _whatsapp_endpoint(phone_number_id, str(config.get("endpoint_template") or ""))
    response = _send_whatsapp_http_request(
        request_url=request_url,
        payload={
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": normalized_recipient,
            "type": "text",
            "text": {"body": str(text)},
        },
        token=token,
        auth_header_name=str(config.get("auth_header_name") or "Authorization"),
        auth_header_prefix=str(config.get("auth_header_prefix") or "Bearer "),
        timeout=_whatsapp_request_timeout_seconds(),
    )
    return WhatsAppDeliveryReceipt(
        principal_id=str(config.get("principal_id") or principal_id),
        binding_id=str(config.get("binding_id") or ""),
        connector_name=str(config.get("connector_name") or ""),
        recipient=normalized_recipient,
        message_ids=_extract_message_ids(response),
        request_url=request_url,
        binding_status=str(config.get("status") or "unknown").strip(),
        external_account_ref=str(config.get("external_account_ref") or ""),
    )
