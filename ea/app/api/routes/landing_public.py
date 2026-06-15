from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, PlainTextResponse

from app.api.routes import landing as deps
from app.api.routes import landing_public_pages_support as support

router = APIRouter(tags=["landing-public"])
archive_router = APIRouter(tags=["landing-archive"])


@router.get("/robots.txt", include_in_schema=False, response_class=PlainTextResponse)
def robots_txt(request: Request) -> PlainTextResponse:
    return deps.robots_txt(request)


@router.get("/", response_class=HTMLResponse)
def landing(
    request: Request,
    container: deps.AppContainer = Depends(deps.get_container),
    access_identity: deps.CloudflareAccessIdentity | None = Depends(deps.get_cloudflare_access_identity),
) -> HTMLResponse:
    return support.landing(request=request, container=container, access_identity=access_identity)


@archive_router.get("/{archive_slug}", response_class=HTMLResponse, include_in_schema=False)
def archive_publication_page(archive_slug: str, request: Request) -> HTMLResponse:
    return support.archive_publication_page(archive_slug=archive_slug, request=request)


@router.get("/modes", response_class=HTMLResponse)
def project_modes_page(
    request: Request,
    container: deps.AppContainer = Depends(deps.get_container),
    access_identity: deps.CloudflareAccessIdentity | None = Depends(deps.get_cloudflare_access_identity),
    _: None = Depends(deps.require_operator_context),
) -> HTMLResponse:
    return support.project_modes_page(request=request, container=container, access_identity=access_identity)


@router.get("/product", response_class=HTMLResponse)
def product_page(
    request: Request,
    container: deps.AppContainer = Depends(deps.get_container),
    access_identity: deps.CloudflareAccessIdentity | None = Depends(deps.get_cloudflare_access_identity),
) -> HTMLResponse:
    return support.product_page(request=request, container=container, access_identity=access_identity)


@router.get("/integrations", response_class=HTMLResponse)
def integrations_page(
    request: Request,
    container: deps.AppContainer = Depends(deps.get_container),
    access_identity: deps.CloudflareAccessIdentity | None = Depends(deps.get_cloudflare_access_identity),
) -> HTMLResponse:
    return support.integrations_page(request=request, container=container, access_identity=access_identity)


@router.get("/integrations/{channel_name}", response_class=HTMLResponse)
def integration_detail(
    channel_name: str,
    request: Request,
    container: deps.AppContainer = Depends(deps.get_container),
    access_identity: deps.CloudflareAccessIdentity | None = Depends(deps.get_cloudflare_access_identity),
) -> HTMLResponse:
    return support.integration_detail(channel_name=channel_name, request=request, container=container, access_identity=access_identity)


@router.get("/security", response_class=HTMLResponse)
def security_page(
    request: Request,
    container: deps.AppContainer = Depends(deps.get_container),
    access_identity: deps.CloudflareAccessIdentity | None = Depends(deps.get_cloudflare_access_identity),
) -> HTMLResponse:
    return support.security_page(request=request, container=container, access_identity=access_identity)


@router.get("/pricing", response_class=HTMLResponse)
def pricing_page(
    request: Request,
    container: deps.AppContainer = Depends(deps.get_container),
    access_identity: deps.CloudflareAccessIdentity | None = Depends(deps.get_cloudflare_access_identity),
) -> HTMLResponse:
    return support.pricing_page(request=request, container=container, access_identity=access_identity)


@router.get("/docs", response_class=HTMLResponse)
def docs_page(
    request: Request,
    container: deps.AppContainer = Depends(deps.get_container),
    access_identity: deps.CloudflareAccessIdentity | None = Depends(deps.get_cloudflare_access_identity),
) -> HTMLResponse:
    return support.docs_page(request=request, container=container, access_identity=access_identity)
