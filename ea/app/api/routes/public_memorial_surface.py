from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response

from app.api.routes.public_memorial_surface_support import (
    _asset_file,
    _ensure_memorial_guest_cookie,
    _load_memorial,
    _load_private_profile,
    _memorial_archive_publication_html_path,
    _memorial_archive_publication_redirect_url,
    _memorial_html,
    _memorial_pwa_icon_file,
    _memorial_pwa_icon_svg,
    _memorial_pwa_manifest_payload,
    _memorial_pwa_service_worker,
    _prime_memorial_live_warmup_on_page_render,
    _public_memorial_archive_registry,
    _public_memorial_page_html,
    _public_memorial_payload,
    _safe_slug,
    request_hostname,
)
import mimetypes


router = APIRouter(tags=["public-memorial-surface"])


@router.get("/memorials/{slug}.json")
def public_memorial_manifest(slug: str) -> JSONResponse:
    return JSONResponse(_public_memorial_payload(_load_memorial(slug)))


@router.get("/memorials/{slug}/archive.json")
def public_memorial_archive_manifest(slug: str) -> JSONResponse:
    _load_memorial(slug)
    return JSONResponse(_public_memorial_archive_registry(slug))


@router.get("/memorials/{slug}/archive")
def public_memorial_archive_index(slug: str, request: Request) -> HTMLResponse:
    payload = _load_memorial(slug)
    private_profile = _load_private_profile(slug)
    _prime_memorial_live_warmup_on_page_render(slug)
    response = HTMLResponse(
        _memorial_html(
            payload,
            private_profile=private_profile,
            hostname=request_hostname(request),
        ),
        headers={"Cache-Control": "no-store, max-age=0"},
    )
    _ensure_memorial_guest_cookie(response, request, slug=slug)
    return response


@router.get("/memorials/{slug}/archive/{publication_slug}")
def public_memorial_archive_publication(slug: str, publication_slug: str) -> Response:
    _load_memorial(slug)
    html_path = _memorial_archive_publication_html_path(slug, publication_slug)
    if not html_path.is_file():
        redirect_url = _memorial_archive_publication_redirect_url(slug, publication_slug)
        if redirect_url:
            return RedirectResponse(url=redirect_url, status_code=307, headers={"Cache-Control": "no-store"})
        raise HTTPException(status_code=404, detail="memorial_archive_publication_not_found")
    return HTMLResponse(html_path.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


@router.get("/memorials/{slug}/app.webmanifest")
def public_memorial_pwa_manifest(slug: str, request: Request) -> JSONResponse:
    payload = _load_memorial(slug)
    prefer_install_surface = str(request.query_params.get("surface") or "").strip().lower() == "page"
    return JSONResponse(
        _memorial_pwa_manifest_payload(slug, payload, prefer_install_surface=prefer_install_surface),
        media_type="application/manifest+json",
    )


@router.get("/memorials/{slug}/service-worker.js")
def public_memorial_pwa_service_worker_route(slug: str) -> Response:
    payload = _load_memorial(slug)
    return Response(
        content=_memorial_pwa_service_worker(slug, payload),
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-store",
            "Service-Worker-Allowed": f"/memorials/{_safe_slug(slug)}",
        },
    )


@router.get("/memorials/{slug}/icon-{size}.png")
def public_memorial_pwa_png_icon(slug: str, size: int) -> FileResponse:
    if size not in {180, 192, 512}:
        raise HTTPException(status_code=404, detail="memorial_icon_not_found")
    payload = _load_memorial(slug)
    icon_path = _memorial_pwa_icon_file(slug, payload, size)
    if icon_path is None:
        raise HTTPException(status_code=404, detail="memorial_icon_not_found")
    return FileResponse(
        icon_path,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/memorials/{slug}/icon.svg")
def public_memorial_pwa_icon(slug: str) -> Response:
    payload = _load_memorial(slug)
    return Response(
        content=_memorial_pwa_icon_svg(payload),
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/memorials/files/{slug}/{asset_path:path}")
def public_memorial_file(slug: str, asset_path: str) -> FileResponse:
    path = _asset_file(slug, asset_path)
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(
        path,
        media_type=media_type,
        filename=path.name,
        headers={
            "Cache-Control": "public, max-age=3600, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/memorials/{slug}", response_class=HTMLResponse)
def public_memorial_page(slug: str, request: Request) -> HTMLResponse:
    payload = _load_memorial(slug)
    private_profile = _load_private_profile(slug)
    hostname = request_hostname(request)
    _prime_memorial_live_warmup_on_page_render(slug)
    response = HTMLResponse(
        _public_memorial_page_html(
            payload,
            private_profile=private_profile,
            hostname=hostname,
        ),
        headers={"Cache-Control": "no-store, max-age=0"},
    )
    _ensure_memorial_guest_cookie(response, request, slug=slug)
    return response


@router.head("/memorials/{slug}")
def public_memorial_head(slug: str, request: Request) -> HTMLResponse:
    payload = _load_memorial(slug)
    private_profile = _load_private_profile(slug)
    hostname = request_hostname(request)
    response = HTMLResponse(
        _public_memorial_page_html(
            payload,
            private_profile=private_profile,
            hostname=hostname,
        ),
        headers={"Cache-Control": "no-store, max-age=0"},
    )
    _ensure_memorial_guest_cookie(response, request, slug=slug)
    return response
