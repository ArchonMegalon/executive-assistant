from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.routes import landing as deps
from app.api.routes import landing_access_support as support

router = APIRouter(tags=["landing-access"])


@router.api_route("/sign-in", methods=["GET", "HEAD"], response_class=HTMLResponse, include_in_schema=False)
def sign_in_page(
    request: Request,
    container: deps.AppContainer = Depends(deps.get_container),
    access_identity: deps.CloudflareAccessIdentity | None = Depends(deps.get_cloudflare_access_identity),
) -> HTMLResponse:
    return support.sign_in_page(request=request, container=container, access_identity=access_identity)


@router.post("/sign-in/email-link")
async def sign_in_email_link(
    request: Request,
    container: deps.AppContainer = Depends(deps.get_container),
) -> RedirectResponse:
    return await support.sign_in_email_link(request=request, container=container)


@router.post("/sign-in/google")
async def sign_in_google(
    request: Request,
    container: deps.AppContainer = Depends(deps.get_container),
) -> RedirectResponse:
    return await support.sign_in_google(request=request, container=container)


@router.get("/register", response_class=HTMLResponse)
def register_page(
    request: Request,
    container: deps.AppContainer = Depends(deps.get_container),
    access_identity: deps.CloudflareAccessIdentity | None = Depends(deps.get_cloudflare_access_identity),
) -> HTMLResponse:
    return support.register_page(request=request, container=container, access_identity=access_identity)


@router.api_route("/workspace-invites/{token}", methods=["GET", "HEAD"], response_class=HTMLResponse, include_in_schema=False)
def workspace_invite_preview(
    token: str,
    request: Request,
    container: deps.AppContainer = Depends(deps.get_container),
) -> HTMLResponse:
    return support.workspace_invite_preview(token=token, request=request, container=container)


@router.api_route("/workspace-access/{token}", methods=["GET", "HEAD"], response_model=None, include_in_schema=False)
def workspace_access_session(
    token: str,
    request: Request,
    container: deps.AppContainer = Depends(deps.get_container),
):
    return support.workspace_access_session(token=token, request=request, container=container)


@router.api_route("/workspace-invites/{token}/accept", methods=["GET", "HEAD"], response_class=HTMLResponse, include_in_schema=False)
def workspace_invite_accept(
    token: str,
    request: Request,
    container: deps.AppContainer = Depends(deps.get_container),
    access_identity: deps.CloudflareAccessIdentity | None = Depends(deps.get_cloudflare_access_identity),
) -> HTMLResponse:
    return support.workspace_invite_accept(token=token, request=request, container=container, access_identity=access_identity)


@router.get("/get-started", response_class=HTMLResponse)
def get_started(
    request: Request,
    container: deps.AppContainer = Depends(deps.get_container),
    access_identity: deps.CloudflareAccessIdentity | None = Depends(deps.get_cloudflare_access_identity),
) -> HTMLResponse:
    return support.get_started(request=request, container=container, access_identity=access_identity)
