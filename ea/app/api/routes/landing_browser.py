from __future__ import annotations

import html
import hmac
import urllib.parse
from datetime import datetime, timezone

from fastapi import HTTPException, Request

from app.container import AppContainer
from app.services.cloudflare_access import CloudflareAccessIdentity
from app.services.public_request import trust_forwarded_host


def _expected_api_token(container: AppContainer) -> str:
    return str(container.settings.auth.api_token or "").strip()


def _default_principal_id(container: AppContainer) -> str:
    return str(container.settings.auth.default_principal_id or "").strip() or "local-user"


def _token_required(container: AppContainer) -> bool:
    mode = str(getattr(getattr(container.settings, "runtime", None), "mode", "dev") or "dev").strip().lower() or "dev"
    return mode == "prod" or bool(_expected_api_token(container))


def _form_value(form_data: dict[str, list[str]], key: str, default: str = "") -> str:
    values = form_data.get(key) or []
    return str(values[0] if values else default).strip()


def _form_values(form_data: dict[str, list[str]], key: str) -> tuple[str, ...]:
    return tuple(str(value).strip() for value in (form_data.get(key) or []) if str(value).strip())


def _normalize_browser_return_to(raw: str | None, *, default: str) -> str:
    value = str(raw or "").strip()
    if not value:
        return default
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme or parsed.netloc or value.startswith("//") or not value.startswith("/"):
        return default
    return value


def _first_forwarded_https_or_first_token(raw: str) -> str:
    tokens = [token.strip().lower() for token in str(raw or "").split(",") if token.strip()]
    if "https" in tokens:
        return "https"
    if "wss" in tokens:
        return "wss"
    return tokens[0] if tokens else ""


def _browser_request_uses_secure_scheme(request: Request) -> bool:
    forwarded_proto = str(request.headers.get("x-forwarded-proto") or "").strip().lower()
    if trust_forwarded_host() or "," in forwarded_proto:
        normalized = _first_forwarded_https_or_first_token(forwarded_proto)
        if normalized:
            return normalized in {"https", "wss"}
    return str(request.url.scheme or "").strip().lower() == "https"


def _workspace_session_cookie_kwargs(request: Request, *, expires_at: str = "") -> dict[str, object]:
    kwargs: dict[str, object] = {
        "httponly": True,
        "samesite": "lax",
        "path": "/",
        "secure": _browser_request_uses_secure_scheme(request),
    }
    normalized_expires_at = str(expires_at or "").strip()
    if not normalized_expires_at:
        return kwargs
    try:
        expires_dt = datetime.fromisoformat(normalized_expires_at)
    except ValueError:
        return kwargs
    if expires_dt.tzinfo is None:
        expires_dt = expires_dt.replace(tzinfo=timezone.utc)
    max_age = max(int((expires_dt - datetime.now(timezone.utc)).total_seconds()), 0)
    kwargs["expires"] = expires_dt
    kwargs["max_age"] = max_age
    return kwargs


def _shared_browser_fields(
    *,
    principal_id: str,
    access_identity: CloudflareAccessIdentity | None,
    container: AppContainer,
) -> str:
    token_field = ""
    if access_identity is None and _token_required(container):
        token_field = """
        <label for=\"api_token\">API token</label>
        <input id=\"api_token\" name=\"api_token\" type=\"password\" placeholder=\"required for browser setup on this host\">
        """
    if access_identity is not None:
        return f"""
        <input type=\"hidden\" name=\"principal_id\" value=\"{html.escape(principal_id)}\">
        {token_field}
        """
    return f"""
    {token_field}
    <p class=\"helper-note\">This browser can only finish setup for the default workspace on this deployment.</p>
    """


def _browser_form_context(
    *,
    form_data: dict[str, list[str]],
    container: AppContainer,
    access_identity: CloudflareAccessIdentity | None,
) -> str:
    expected = _expected_api_token(container)
    if access_identity is None and _token_required(container):
        api_token = _form_value(form_data, "api_token", "")
        if not expected or not hmac.compare_digest(api_token, expected):
            raise HTTPException(status_code=401, detail="auth_required")
    if access_identity is not None:
        requested = _form_value(form_data, "principal_id", access_identity.principal_id)
        if requested and requested != access_identity.principal_id:
            raise HTTPException(status_code=403, detail="principal_scope_mismatch")
        return access_identity.principal_id
    default_principal = _default_principal_id(container)
    requested = _form_value(form_data, "principal_id", "")
    if requested and requested != default_principal:
        raise HTTPException(status_code=403, detail="principal_override_not_allowed")
    return default_principal
