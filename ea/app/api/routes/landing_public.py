from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from app.api.routes import landing as shared

router = APIRouter(tags=["landing-public"])
archive_router = APIRouter(tags=["landing-archive"])


@router.get("/robots.txt", include_in_schema=False, response_class=PlainTextResponse)
def robots_txt() -> PlainTextResponse:
    return shared.robots_txt()


@router.get("/", response_class=HTMLResponse)
def landing(
    request: Request,
    container: shared.AppContainer = Depends(shared.get_container),
    access_identity: shared.CloudflareAccessIdentity | None = Depends(shared.get_cloudflare_access_identity),
) -> HTMLResponse:
    return shared.landing(request=request, container=container, access_identity=access_identity)


@archive_router.get("/{archive_slug}", response_class=HTMLResponse, include_in_schema=False)
def archive_publication_page(archive_slug: str, request: Request) -> HTMLResponse:
    return shared.archive_publication_page(archive_slug=archive_slug, request=request)


@router.get("/modes", response_class=HTMLResponse)
def project_modes_page(
    request: Request,
    container: shared.AppContainer = Depends(shared.get_container),
    access_identity: shared.CloudflareAccessIdentity | None = Depends(shared.get_cloudflare_access_identity),
    _: None = Depends(shared.require_operator_context),
) -> HTMLResponse:
    return shared.project_modes_page(request=request, container=container, access_identity=access_identity)


@router.get("/product", response_class=HTMLResponse)
def product_page(
    request: Request,
    container: shared.AppContainer = Depends(shared.get_container),
    access_identity: shared.CloudflareAccessIdentity | None = Depends(shared.get_cloudflare_access_identity),
) -> HTMLResponse:
    return shared.product_page(request=request, container=container, access_identity=access_identity)


@router.get("/integrations", response_class=HTMLResponse)
def integrations_page(
    request: Request,
    container: shared.AppContainer = Depends(shared.get_container),
    access_identity: shared.CloudflareAccessIdentity | None = Depends(shared.get_cloudflare_access_identity),
) -> HTMLResponse:
    return shared.integrations_page(request=request, container=container, access_identity=access_identity)


@router.get("/integrations/{channel_name}", response_class=HTMLResponse)
def integration_detail(
    channel_name: str,
    request: Request,
    container: shared.AppContainer = Depends(shared.get_container),
    access_identity: shared.CloudflareAccessIdentity | None = Depends(shared.get_cloudflare_access_identity),
) -> HTMLResponse:
    return shared.integration_detail(channel_name=channel_name, request=request, container=container, access_identity=access_identity)


@router.get("/security", response_class=HTMLResponse)
def security_page(
    request: Request,
    container: shared.AppContainer = Depends(shared.get_container),
    access_identity: shared.CloudflareAccessIdentity | None = Depends(shared.get_cloudflare_access_identity),
) -> HTMLResponse:
    return shared.security_page(request=request, container=container, access_identity=access_identity)


@router.get("/pricing", response_class=HTMLResponse)
def pricing_page(
    request: Request,
    container: shared.AppContainer = Depends(shared.get_container),
    access_identity: shared.CloudflareAccessIdentity | None = Depends(shared.get_cloudflare_access_identity),
) -> HTMLResponse:
    return shared.pricing_page(request=request, container=container, access_identity=access_identity)


@router.get("/docs", response_class=HTMLResponse)
def docs_page(
    request: Request,
    container: shared.AppContainer = Depends(shared.get_container),
    access_identity: shared.CloudflareAccessIdentity | None = Depends(shared.get_cloudflare_access_identity),
) -> HTMLResponse:
    return shared.docs_page(request=request, container=container, access_identity=access_identity)


@router.api_route("/sign-in", methods=["GET", "HEAD"], response_class=HTMLResponse, include_in_schema=False)
def sign_in_page(
    request: Request,
    container: shared.AppContainer = Depends(shared.get_container),
    access_identity: shared.CloudflareAccessIdentity | None = Depends(shared.get_cloudflare_access_identity),
) -> HTMLResponse:
    return shared.sign_in_page(request=request, container=container, access_identity=access_identity)


@router.post("/sign-in/email-link")
async def sign_in_email_link(
    request: Request,
    container: shared.AppContainer = Depends(shared.get_container),
) -> RedirectResponse:
    return await shared.sign_in_email_link(request=request, container=container)


@router.post("/sign-in/google")
async def sign_in_google(
    request: Request,
    container: shared.AppContainer = Depends(shared.get_container),
) -> RedirectResponse:
    return await shared.sign_in_google(request=request, container=container)


@router.get("/register", response_class=HTMLResponse)
def register_page(
    request: Request,
    container: shared.AppContainer = Depends(shared.get_container),
    access_identity: shared.CloudflareAccessIdentity | None = Depends(shared.get_cloudflare_access_identity),
) -> HTMLResponse:
    return shared.register_page(request=request, container=container, access_identity=access_identity)


@router.api_route("/workspace-invites/{token}", methods=["GET", "HEAD"], response_class=HTMLResponse, include_in_schema=False)
def workspace_invite_preview(
    token: str,
    request: Request,
    container: shared.AppContainer = Depends(shared.get_container),
) -> HTMLResponse:
    return shared.workspace_invite_preview(token=token, request=request, container=container)


@router.api_route("/workspace-access/{token}", methods=["GET", "HEAD"], response_model=None, include_in_schema=False)
def workspace_access_session(
    token: str,
    request: Request,
    container: shared.AppContainer = Depends(shared.get_container),
):
    return shared.workspace_access_session(token=token, request=request, container=container)


@router.api_route("/workspace-invites/{token}/accept", methods=["GET", "HEAD"], response_class=HTMLResponse, include_in_schema=False)
def workspace_invite_accept(
    token: str,
    request: Request,
    container: shared.AppContainer = Depends(shared.get_container),
    access_identity: shared.CloudflareAccessIdentity | None = Depends(shared.get_cloudflare_access_identity),
) -> HTMLResponse:
    return shared.workspace_invite_accept(token=token, request=request, container=container, access_identity=access_identity)


@router.get("/get-started", response_class=HTMLResponse)
def get_started(
    request: Request,
    container: shared.AppContainer = Depends(shared.get_container),
    access_identity: shared.CloudflareAccessIdentity | None = Depends(shared.get_cloudflare_access_identity),
) -> HTMLResponse:
    return shared.get_started(request=request, container=container, access_identity=access_identity)
