from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

from app.container import AppContainer


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


def require_request_auth(
    request: Request,
    container: AppContainer = Depends(get_container),
) -> None:
    expected = str(container.settings.auth.api_token or "").strip()
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
    expected = str(container.settings.auth.api_token or "").strip()
    authenticated = False
    if expected:
        provided = _extract_token(request)
        if provided != expected:
            raise HTTPException(status_code=401, detail="auth_required")
        authenticated = True
    principal_id = str(request.headers.get("x-ea-principal-id") or "").strip()
    if not principal_id and container.settings.runtime.mode == "prod":
        raise HTTPException(status_code=401, detail="principal_required")
    if not principal_id:
        principal_id = str(container.settings.auth.default_principal_id or "").strip() or "local-user"
    return RequestContext(principal_id=principal_id, authenticated=authenticated)


def resolve_principal_id(requested_principal_id: str | None, context: RequestContext) -> str:
    requested = str(requested_principal_id or "").strip()
    if requested and requested != context.principal_id:
        raise HTTPException(status_code=403, detail="principal_scope_mismatch")
    return context.principal_id
