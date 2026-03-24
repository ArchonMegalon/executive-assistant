from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from fastapi.params import Depends as DependsMarker

from app.container import AppContainer
from app.services.cloudflare_access import (
    CloudflareAccessIdentity,
    build_operator_id,
    build_operator_notes,
    resolve_access_identity,
)
from app.settings import RuntimeProfile, resolve_runtime_profile


def get_container(request: Request) -> AppContainer:
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise RuntimeError("application container is not initialized")
    return container


def _extract_token(request: Request) -> str:
    header = str(request.headers.get("authorization") or "").strip()
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return str(request.headers.get("x-api-token") or "").strip()


def _configured_api_token(container: AppContainer) -> str:
    return str(container.settings.auth.api_token or "").strip()


def _client_host(request: Request) -> str:
    client = getattr(request, "client", None)
    return str(getattr(client, "host", "") or "").strip()


def _is_loopback_host(host: str) -> bool:
    normalized = str(host or "").strip().lower()
    if not normalized:
        return False
    if normalized in {"localhost", "testclient"}:
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _loopback_no_auth_allowed(request: Request, container: AppContainer) -> bool:
    if not bool(getattr(container.settings.auth, "allow_loopback_no_auth", False)):
        return False
    return _is_loopback_host(_client_host(request))


def _provision_access_identity(container: AppContainer, identity: CloudflareAccessIdentity) -> None:
    operator_id = build_operator_id(identity)
    current = container.orchestrator.fetch_operator_profile(operator_id, principal_id=identity.principal_id)
    notes = build_operator_notes(identity)
    if (
        current is not None
        and current.display_name == identity.display_name
        and current.status == "active"
        and current.notes == notes
    ):
        return
    container.orchestrator.upsert_operator_profile(
        principal_id=identity.principal_id,
        operator_id=operator_id,
        display_name=identity.display_name,
        roles=("cloudflare_access",),
        trust_tier="standard",
        status="active",
        notes=notes,
    )


def get_cloudflare_access_identity(
    request: Request,
    container: AppContainer = Depends(get_container),
) -> CloudflareAccessIdentity | None:
    cached = getattr(request.state, "cloudflare_access_identity", None)
    if isinstance(cached, CloudflareAccessIdentity):
        return cached
    if cached is False:
        return None
    try:
        identity = resolve_access_identity(headers=request.headers, settings=container.settings.auth)
    except Exception as exc:
        setattr(request.state, "cloudflare_access_error", str(exc))
        raise HTTPException(status_code=401, detail="cloudflare_access_invalid") from exc
    if identity is None:
        setattr(request.state, "cloudflare_access_identity", False)
        return None
    _provision_access_identity(container, identity)
    setattr(request.state, "cloudflare_access_identity", identity)
    return identity


def _runtime_profile(container: AppContainer):
    profile = getattr(container, "runtime_profile", None)
    if profile is not None:
        return profile
    settings = container.settings
    if hasattr(settings, "storage"):
        return resolve_runtime_profile(settings)
    mode = str(getattr(getattr(settings, "runtime", None), "mode", "dev") or "dev").strip().lower() or "dev"
    api_token = str(getattr(getattr(settings, "auth", None), "api_token", "") or "").strip()
    auth_mode = "token" if mode == "prod" or api_token else "anonymous_dev"
    principal_source = "authenticated_header" if mode == "prod" else (
        "authenticated_header_or_default" if auth_mode == "token" else "caller_header_or_default"
    )
    return RuntimeProfile(
        mode=mode,
        storage_backend="postgres" if mode == "prod" else "memory",
        durability="durable" if mode == "prod" else "ephemeral",
        auth_mode=auth_mode,
        principal_source=principal_source,
        database_required=mode == "prod",
        database_configured=False,
        source_backend="memory",
    )


def _resolved_principal_id(
    request: Request,
    *,
    container: AppContainer,
    authenticated: bool,
    access_identity: CloudflareAccessIdentity | None = None,
) -> str:
    profile = _runtime_profile(container)
    if access_identity is not None:
        return access_identity.principal_id
    principal_id = str(request.headers.get("x-ea-principal-id") or "").strip()
    fallback_principal = str(container.settings.auth.default_principal_id or "").strip()
    if principal_id:
        if profile.caller_principal_header_requires_authentication and not authenticated:
            return ""
        if _loopback_no_auth_allowed(request, container):
            return principal_id
        if authenticated and not authenticated_principal_override_allowed():
            principal_id = ""
        else:
            return principal_id
    if fallback_principal and authenticated:
        return fallback_principal
    if profile.default_principal_fallback_allowed:
        return fallback_principal or "local-user"
    return ""


def require_request_auth(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> None:
    if isinstance(access_identity, DependsMarker):
        access_identity = get_cloudflare_access_identity(request, container)
    profile = _runtime_profile(container)
    if access_identity is not None:
        return
    if _loopback_no_auth_allowed(request, container):
        return
    if profile.auth_mode not in {"token", "token_or_access", "access"}:
        return
    if profile.auth_mode == "access":
        raise HTTPException(status_code=401, detail="auth_required")
    expected = _configured_api_token(container)
    if not expected:
        raise HTTPException(status_code=401, detail="auth_required")
    provided = _extract_token(request)
    if provided == expected:
        return
    raise HTTPException(status_code=401, detail="auth_required")


@dataclass(frozen=True)
class RequestContext:
    principal_id: str
    authenticated: bool
    auth_source: str = "anonymous"
    access_email: str = ""
    operator_id: str = ""


def _operator_principal_allowlist() -> set[str]:
    values: set[str] = set()
    for env_name in ("EA_OPERATOR_PRINCIPAL_IDS", "EA_OPERATOR_PRINCIPALS"):
        raw = str(os.environ.get(env_name) or "").strip()
        if not raw:
            continue
        for item in raw.split(","):
            normalized = str(item or "").strip()
            if normalized:
                values.add(normalized)
    return values


def _operator_email_allowlist() -> set[str]:
    values: set[str] = set()
    for env_name in ("EA_OPERATOR_EMAILS", "EA_OPERATOR_ACCESS_EMAILS"):
        raw = str(os.environ.get(env_name) or "").strip()
        if not raw:
            continue
        for item in raw.split(","):
            normalized = str(item or "").strip().lower()
            if normalized:
                values.add(normalized)
    return values


def authenticated_principal_override_allowed() -> bool:
    for env_name in (
        "EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER",
        "EA_ALLOW_AUTHENTICATED_PRINCIPAL_HEADER",
        "EA_TRUST_API_TOKEN_PRINCIPAL_HEADER",
    ):
        if str(os.environ.get(env_name) or "").strip().lower() in {"1", "true", "yes", "on"}:
            return True
    return False


def browser_principal_override_allowed() -> bool:
    for env_name in (
        "EA_TRUST_BROWSER_PRINCIPAL_OVERRIDE",
        "EA_ALLOW_BROWSER_PRINCIPAL_OVERRIDE",
    ):
        if str(os.environ.get(env_name) or "").strip().lower() in {"1", "true", "yes", "on"}:
            return True
    return False


def is_operator_context(context: RequestContext) -> bool:
    principal_id = str(context.principal_id or "").strip()
    if not principal_id:
        return False
    if context.auth_source == "loopback_no_auth":
        return True
    if not bool(context.authenticated):
        return False
    if principal_id in _operator_principal_allowlist():
        return True
    access_email = str(context.access_email or "").strip().lower()
    if access_email and access_email in _operator_email_allowlist():
        return True
    if context.auth_source != "cloudflare_access":
        return False
    lowered = principal_id.lower()
    return lowered.startswith(("system", "operator", "admin", "automation", "scheduler", "cron", "daemon", "health"))


def get_request_context(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> RequestContext:
    if isinstance(access_identity, DependsMarker):
        access_identity = get_cloudflare_access_identity(request, container)
    profile = _runtime_profile(container)
    if access_identity is not None:
        principal_id = _resolved_principal_id(
            request,
            container=container,
            authenticated=True,
            access_identity=access_identity,
        )
        return RequestContext(
            principal_id=principal_id,
            authenticated=True,
            auth_source="cloudflare_access",
            access_email=access_identity.email,
            operator_id=build_operator_id(access_identity),
        )
    if _loopback_no_auth_allowed(request, container):
        principal_id = _resolved_principal_id(request, container=container, authenticated=True)
        if not principal_id:
            raise HTTPException(status_code=401, detail="principal_required")
        return RequestContext(
            principal_id=principal_id,
            authenticated=True,
            auth_source="loopback_no_auth",
        )
    authenticated = False
    if profile.auth_mode in {"token", "token_or_access"}:
        expected = _configured_api_token(container)
        if not expected:
            raise HTTPException(status_code=401, detail="auth_required")
        provided = _extract_token(request)
        if provided != expected:
            raise HTTPException(status_code=401, detail="auth_required")
        authenticated = True

    elif profile.auth_mode == "access":
        if not profile.default_principal_fallback_allowed:
            raise HTTPException(status_code=401, detail="auth_required")

    principal_id = _resolved_principal_id(request, container=container, authenticated=authenticated)
    if not principal_id:
        raise HTTPException(status_code=401, detail="principal_required")
    return RequestContext(
        principal_id=principal_id,
        authenticated=authenticated,
        auth_source="api_token" if authenticated else "anonymous",
    )


def require_operator_context(context: RequestContext = Depends(get_request_context)) -> None:
    if not is_operator_context(context):
        raise HTTPException(status_code=403, detail="operator_scope_required")


def resolve_principal_id(requested_principal_id: str | None, context: RequestContext) -> str:
    requested = str(requested_principal_id or "").strip()
    if requested and requested != context.principal_id:
        raise HTTPException(status_code=403, detail="principal_scope_mismatch")
    return context.principal_id
