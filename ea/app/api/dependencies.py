from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

from app.container import AppContainer
from app.settings import is_prod_mode


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


def _is_prod_mode(container: AppContainer) -> bool:
    return is_prod_mode(container.settings.runtime.mode)


def _resolved_principal_id(request: Request, *, container: AppContainer) -> str:
    principal_id = str(request.headers.get("x-ea-principal-id") or "").strip()
    if principal_id:
        return principal_id
    if _is_prod_mode(container):
        return ""
    return str(container.settings.auth.default_principal_id or "").strip() or "local-user"


def require_request_auth(
    request: Request,
    container: AppContainer = Depends(get_container),
) -> None:
    if _is_prod_mode(container) and not _configured_api_token(container):
        raise HTTPException(status_code=401, detail="auth_required")
    expected = _configured_api_token(container)
    if not expected:
        return
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
    if _is_prod_mode(container) and not _configured_api_token(container):
        raise HTTPException(status_code=401, detail="auth_required")
    authenticated = False
    expected = _configured_api_token(container)
    if expected:
        provided = _extract_token(request)
        if provided != expected:
            raise HTTPException(status_code=401, detail="auth_required")
        authenticated = True
    elif _is_prod_mode(container):
        raise HTTPException(status_code=401, detail="principal_required")

    principal_id = _resolved_principal_id(request, container=container)
    if not principal_id and _is_prod_mode(container):
        raise HTTPException(status_code=401, detail="principal_required")
    if not principal_id:
        raise HTTPException(status_code=401, detail="principal_required")
    return RequestContext(principal_id=principal_id, authenticated=authenticated)


def resolve_principal_id(requested_principal_id: str | None, context: RequestContext) -> str:
    requested = str(requested_principal_id or "").strip()
    if requested and requested != context.principal_id:
        raise HTTPException(status_code=403, detail="principal_scope_mismatch")
    return context.principal_id
