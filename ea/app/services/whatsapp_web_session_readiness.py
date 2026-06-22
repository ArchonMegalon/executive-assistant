from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from app.services import whatsapp_web_session_delivery


WEB_SESSION_CONNECTOR = whatsapp_web_session_delivery.WHATSAPP_WEB_SESSION_CONNECTOR


def _metadata(binding: Any | None) -> dict[str, object]:
    if binding is None:
        return {}
    return dict(getattr(binding, "auth_metadata_json", {}) or {})


def _scope_json(binding: Any | None) -> dict[str, object]:
    if binding is None:
        return {}
    return dict(getattr(binding, "scope_json", {}) or {})


def _metadata_value(metadata: dict[str, object], *keys: str) -> str:
    for key in keys:
        value = str(metadata.get(key) or "").strip()
        if value:
            return value
    return ""


def _resolve_binding(
    *,
    tool_runtime,
    principal_id: str,
    binding_id: str = "",
    binding: Any | None = None,
) -> Any | None:
    if binding is not None:
        return binding

    normalized_binding_id = str(binding_id or "").strip()
    if normalized_binding_id:
        if tool_runtime is None or not hasattr(tool_runtime, "get_connector_binding"):
            return None
        return tool_runtime.get_connector_binding(normalized_binding_id)

    normalized_principal = str(principal_id or "").strip()
    if not normalized_principal or tool_runtime is None or not hasattr(tool_runtime, "list_connector_bindings"):
        return None
    candidates = [
        row
        for row in tool_runtime.list_connector_bindings(normalized_principal, limit=200)
        if str(getattr(row, "connector_name", "") or "").strip() == WEB_SESSION_CONNECTOR
    ]
    candidates.sort(key=lambda row: str(getattr(row, "updated_at", "") or "").strip(), reverse=True)
    return next((row for row in candidates if str(getattr(row, "status", "") or "").strip().lower() == "enabled"), None)


def _scope_allows_whatsapp_send(scope_json: dict[str, object]) -> bool:
    values = scope_json.get("scopes") or ()
    if isinstance(values, str):
        candidates = {values.strip().lower()}
    elif isinstance(values, (list, tuple, set)):
        candidates = {str(value or "").strip().lower() for value in values}
    else:
        candidates = set()
    return bool(candidates.intersection({"whatsapp", "whatsapp.send", "whatsapp.post", "send.whatsapp"}))


def _status_url_template(metadata: dict[str, object]) -> str:
    configured = _metadata_value(
        metadata,
        "session_status_url_template",
        "status_url_template",
        "health_url_template",
    )
    if configured:
        return configured
    base_url = _metadata_value(metadata, "session_api_base_url", "api_base_url", "base_url").rstrip("/")
    if not base_url:
        return ""
    return f"{base_url}/sessions/{{session_ref}}/status"


def _format_url(template: str, *, session_ref: str, binding: Any) -> str:
    return template.format(
        session_ref=session_ref,
        binding_id=str(getattr(binding, "binding_id", "") or "").strip(),
        principal_id=str(getattr(binding, "principal_id", "") or "").strip(),
    )


def _probe_session_status_url(
    *,
    request_url: str,
    token: str = "",
    auth_header_name: str = "Authorization",
    auth_header_prefix: str = "Bearer ",
    timeout: float = 5.0,
) -> dict[str, object]:
    headers: dict[str, str] = {}
    if token:
        headers[str(auth_header_name or "Authorization")] = f"{auth_header_prefix}{token}".strip()
    request = urllib.request.Request(request_url, method="GET", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status_code = int(getattr(response, "status", 200) or 200)
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return {"ok": False, "reason": f"http_{int(getattr(exc, 'code', 500) or 500)}"}
    except Exception as exc:
        return {"ok": False, "reason": type(exc).__name__}
    if status_code >= 400:
        return {"ok": False, "reason": f"http_{status_code}"}
    try:
        parsed = json.loads(body or "{}")
    except Exception:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    ready = parsed.get("ready")
    state = str(parsed.get("status") or parsed.get("state") or "").strip().lower()
    if ready is False or state in {"logged_out", "disconnected", "qr_required", "not_ready", "error"}:
        return {"ok": False, "reason": state or "not_ready", "response": parsed}
    return {"ok": True, "reason": "ready", "response": parsed}


@dataclass(frozen=True)
class WhatsAppWebSessionReadiness:
    ready: bool
    reason: str
    binding_id: str = ""
    principal_id: str = ""
    connector_name: str = ""
    session_ref_present: bool = False
    session_store_ref_present: bool = False
    endpoint_present: bool = False
    token_present: bool = False
    status_url_present: bool = False
    service_routes: tuple[str, ...] = ()
    probe_reason: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "reason": self.reason,
            "binding_id": self.binding_id,
            "principal_id": self.principal_id,
            "connector_name": self.connector_name,
            "session_ref_present": self.session_ref_present,
            "session_store_ref_present": self.session_store_ref_present,
            "endpoint_present": self.endpoint_present,
            "token_present": self.token_present,
            "status_url_present": self.status_url_present,
            "service_routes": list(self.service_routes),
            "probe_reason": self.probe_reason,
        }


def check_whatsapp_web_session_readiness(
    *,
    tool_runtime,
    principal_id: str,
    binding_id: str = "",
    binding: Any | None = None,
    probe_session: bool = False,
) -> WhatsAppWebSessionReadiness:
    resolved = _resolve_binding(
        tool_runtime=tool_runtime,
        principal_id=principal_id,
        binding_id=binding_id,
        binding=binding,
    )
    if resolved is None:
        return WhatsAppWebSessionReadiness(ready=False, reason="binding_not_found")

    resolved_binding_id = str(getattr(resolved, "binding_id", "") or "").strip()
    resolved_principal_id = str(getattr(resolved, "principal_id", "") or "").strip()
    connector_name = str(getattr(resolved, "connector_name", "") or "").strip()
    metadata = _metadata(resolved)
    scope_json = _scope_json(resolved)
    service_routes = tuple(
        str(value or "").strip()
        for value in dict(scope_json.get("service_routes") or {}).get("applies_to", ())
        if str(value or "").strip()
    )
    session_ref = _metadata_value(metadata, "session_ref", "session_id", "session_name")
    session_store_ref = _metadata_value(metadata, "session_store_ref", "session_store", "browser_profile_ref")
    endpoint_template = whatsapp_web_session_delivery._session_send_url_template(metadata)
    token = whatsapp_web_session_delivery._api_token(metadata)
    status_template = _status_url_template(metadata)

    base = {
        "binding_id": resolved_binding_id,
        "principal_id": resolved_principal_id,
        "connector_name": connector_name,
        "session_ref_present": bool(session_ref),
        "session_store_ref_present": bool(session_store_ref),
        "endpoint_present": bool(endpoint_template),
        "token_present": bool(token),
        "status_url_present": bool(status_template),
        "service_routes": service_routes,
    }

    if connector_name != WEB_SESSION_CONNECTOR:
        return WhatsAppWebSessionReadiness(ready=False, reason="connector_mismatch", **base)
    if str(getattr(resolved, "status", "") or "").strip().lower() != "enabled":
        return WhatsAppWebSessionReadiness(ready=False, reason="binding_disabled", **base)
    if str(principal_id or "").strip() and resolved_principal_id != str(principal_id or "").strip():
        return WhatsAppWebSessionReadiness(ready=False, reason="principal_scope_mismatch", **base)
    if not _scope_allows_whatsapp_send(scope_json):
        return WhatsAppWebSessionReadiness(ready=False, reason="scope_missing", **base)
    if not session_ref:
        return WhatsAppWebSessionReadiness(ready=False, reason="session_ref_missing", **base)
    if not session_store_ref:
        return WhatsAppWebSessionReadiness(ready=False, reason="session_store_ref_missing", **base)
    if not endpoint_template:
        return WhatsAppWebSessionReadiness(ready=False, reason="endpoint_missing", **base)

    if probe_session:
        if not status_template:
            return WhatsAppWebSessionReadiness(ready=False, reason="status_endpoint_missing", **base)
        probe = _probe_session_status_url(
            request_url=_format_url(status_template, session_ref=session_ref, binding=resolved),
            token=token,
            auth_header_name=whatsapp_web_session_delivery._auth_header_name(metadata),
            auth_header_prefix=whatsapp_web_session_delivery._auth_header_prefix(metadata),
        )
        if not bool(probe.get("ok")):
            return WhatsAppWebSessionReadiness(
                ready=False,
                reason="probe_failed",
                probe_reason=str(probe.get("reason") or "unknown"),
                **base,
            )
        return WhatsAppWebSessionReadiness(ready=True, reason="ready", probe_reason="ready", **base)

    return WhatsAppWebSessionReadiness(ready=True, reason="ready", **base)
