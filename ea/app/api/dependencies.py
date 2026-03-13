from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

from app.container import AppContainer
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


def _resolved_principal_id(request: Request, *, container: AppContainer, authenticated: bool) -> str:
    profile = _runtime_profile(container)
    principal_id = str(request.headers.get("x-ea-principal-id") or "").strip()
    fallback_principal = str(container.settings.auth.default_principal_id or "").strip()
    if principal_id:
        if profile.caller_principal_header_requires_authentication and not authenticated:
            return ""
        return principal_id
    if profile.default_principal_fallback_allowed:
        return fallback_principal or "local-user"
    return ""


def require_request_auth(
    request: Request,
    container: AppContainer = Depends(get_container),
) -> None:
    profile = _runtime_profile(container)
    if profile.auth_mode != "token":
        return
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


def get_request_context(
    request: Request,
    container: AppContainer = Depends(get_container),
) -> RequestContext:
    profile = _runtime_profile(container)
    authenticated = False
    if profile.auth_mode == "token":
        expected = _configured_api_token(container)
        if not expected:
            raise HTTPException(status_code=401, detail="auth_required")
        provided = _extract_token(request)
        if provided != expected:
            raise HTTPException(status_code=401, detail="auth_required")
        authenticated = True

    principal_id = _resolved_principal_id(request, container=container, authenticated=authenticated)
    if not principal_id:
        raise HTTPException(status_code=401, detail="principal_required")
    return RequestContext(principal_id=principal_id, authenticated=authenticated)


def resolve_principal_id(requested_principal_id: str | None, context: RequestContext) -> str:
    requested = str(requested_principal_id or "").strip()
    if requested and requested != context.principal_id:
        raise HTTPException(status_code=403, detail="principal_scope_mismatch")
    return context.principal_id
