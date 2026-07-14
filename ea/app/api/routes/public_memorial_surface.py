from __future__ import annotations

import mimetypes

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response

from app.api.routes.public_memorial_surface_support import (
    _asset_file,
    _ensure_memorial_guest_cookie,
    _load_memorial,
    _load_private_profile,
    _memorial_archive_publication_html_path,
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
from app.services.memorial_family_contributions import merge_public_family_contributions


router = APIRouter(tags=["public-memorial-surface"])


_PUBLIC_MEMORIAL_HTML_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
    "Permissions-Policy": "microphone=(self), camera=(), geolocation=(), interest-cohort=()",
    "X-Robots-Tag": "noindex, nofollow",
}

_PUBLIC_MEMORIAL_SUPPORT_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Robots-Tag": "noindex, nofollow",
}

_PUBLIC_MEMORIAL_STATIC_ASSET_HEADERS = {
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Robots-Tag": "noindex, nofollow",
}

_PUBLIC_MEMORIAL_ERROR_HEADERS = {
    "X-Robots-Tag": "noindex, nofollow",
}


def _public_surface_html_error_response(status_code: int, detail: str) -> HTMLResponse:
    del detail
    return HTMLResponse(
        (
            "<!doctype html><html lang=\"de\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            "<title>Erinnerungsseite gerade nicht erreichbar</title>"
            "<style>"
            ":root{color-scheme:light;--ink:#2d211a;--ink-soft:#67584c;--line:rgba(72,53,36,.16);--paper:rgba(255,251,246,.95);"
            "--shadow:0 28px 60px rgba(66,45,29,.12);--accent:#8c6949;}"
            "*{box-sizing:border-box;}body{margin:0;min-height:100vh;font-family:\"Avenir Next\",\"Segoe UI\",\"Helvetica Neue\",sans-serif;"
            "color:var(--ink);background:radial-gradient(circle at top, rgba(195,177,151,.28), transparent 38%),"
            "linear-gradient(180deg,#f5eee6 0%,#ebe1d4 48%,#f6f0e8 100%);display:flex;align-items:center;justify-content:center;padding:24px;}"
            "main{width:min(720px,100%);background:var(--paper);border:1px solid var(--line);border-radius:28px;padding:30px 28px;"
            "box-shadow:var(--shadow);}h1{margin:0 0 14px;font-family:\"Iowan Old Style\",\"Palatino Linotype\",Georgia,serif;"
            "font-size:clamp(2rem,5vw,3rem);line-height:1.04;}p{margin:0 0 12px;line-height:1.6;color:var(--ink-soft);}"
            ".kicker{display:inline-block;margin-bottom:14px;font-size:.82rem;letter-spacing:.12em;text-transform:uppercase;color:var(--accent);}"
            ".actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:20px}.actions a{display:inline-flex;align-items:center;min-height:44px;padding:10px 16px;"
            "border:1px solid var(--line);border-radius:999px;color:var(--ink);font-weight:700;text-underline-offset:3px;}"
            "</style></head><body><main><div class=\"kicker\">Erinnerungsseite</div>"
            "<h1>Diese Seite ist gerade nicht erreichbar.</h1>"
            "<p>Der Link kann vorübergehend nicht verfügbar sein. Private oder technische Details werden hier nicht angezeigt.</p>"
            "<p>Versuche es bitte noch einmal. Wenn die Seite weiter fehlt, frage die Person, von der du den Link erhalten hast.</p>"
            "<div class=\"actions\"><a href=\"\">Erneut versuchen</a><a href=\"/\">Zur Startseite</a></div>"
            "</main></body></html>"
        ),
        status_code=status_code,
        headers={**_PUBLIC_MEMORIAL_HTML_HEADERS, **_PUBLIC_MEMORIAL_ERROR_HEADERS},
    )


def _public_surface_error_response(status_code: int, detail: str) -> JSONResponse:
    return JSONResponse(
        {"detail": detail},
        status_code=status_code,
        headers={**_PUBLIC_MEMORIAL_SUPPORT_HEADERS, **_PUBLIC_MEMORIAL_ERROR_HEADERS},
    )


def _load_public_surface_memorial(slug: str) -> dict[str, object]:
    payload = _load_memorial(slug)
    return merge_public_family_contributions(slug=slug, memorial=payload)


@router.get("/memorials/{slug}.json")
def public_memorial_manifest(slug: str) -> JSONResponse:
    try:
        return JSONResponse(
            _public_memorial_payload(_load_public_surface_memorial(slug)),
            headers=dict(_PUBLIC_MEMORIAL_SUPPORT_HEADERS),
        )
    except HTTPException as exc:
        return _public_surface_error_response(exc.status_code, str(exc.detail))


@router.get("/memorials/{slug}/archive.json")
def public_memorial_archive_manifest(slug: str) -> JSONResponse:
    try:
        _load_memorial(slug)
        return JSONResponse(_public_memorial_archive_registry(slug), headers=dict(_PUBLIC_MEMORIAL_SUPPORT_HEADERS))
    except HTTPException as exc:
        return _public_surface_error_response(exc.status_code, str(exc.detail))


@router.get("/memorials/{slug}/archive")
def public_memorial_archive_index(slug: str, request: Request) -> HTMLResponse:
    try:
        payload = _load_public_surface_memorial(slug)
        private_profile = _load_private_profile(slug)
        _prime_memorial_live_warmup_on_page_render(slug)
        response = HTMLResponse(
            _memorial_html(
                payload,
                private_profile=private_profile,
                hostname=request_hostname(request),
            ),
            headers=dict(_PUBLIC_MEMORIAL_HTML_HEADERS),
        )
        _ensure_memorial_guest_cookie(response, request, slug=slug)
        return response
    except HTTPException as exc:
        return _public_surface_html_error_response(exc.status_code, str(exc.detail))


def _authorized_public_memorial_archive_publication(
    slug: str,
    publication_slug: str,
) -> dict[str, object] | None:
    registry = _public_memorial_archive_registry(slug)
    for raw_item in list(registry.get("fliplink_publications") or []):
        if not isinstance(raw_item, dict):
            continue
        try:
            registered_slug = _safe_slug(
                str(raw_item.get("slug") or raw_item.get("id") or "")
            )
        except HTTPException:
            continue
        if registered_slug != publication_slug:
            continue
        if (
            raw_item.get("approved") is not True
            or str(raw_item.get("audience") or "").strip().lower() != "public"
            or str(raw_item.get("sensitivity") or "").strip().upper() != "PUBLIC"
            or str(raw_item.get("review_status") or "").strip().lower()
            != "published"
            or not str(raw_item.get("url") or "").strip()
        ):
            continue
        return dict(raw_item)
    return None


@router.get("/memorials/{slug}/archive/{publication_slug}")
def public_memorial_archive_publication(slug: str, publication_slug: str) -> Response:
    try:
        _load_memorial(slug)
        safe_slug = _safe_slug(slug)
        safe_publication_slug = _safe_slug(publication_slug)
        publication = _authorized_public_memorial_archive_publication(
            safe_slug,
            safe_publication_slug,
        )
    except HTTPException as exc:
        return _public_surface_html_error_response(exc.status_code, str(exc.detail))
    if publication is None:
        return _public_surface_html_error_response(
            404,
            "memorial_archive_publication_not_found",
        )
    html_path = _memorial_archive_publication_html_path(
        safe_slug,
        safe_publication_slug,
    )
    if not html_path.is_file():
        redirect_url = str(publication.get("url") or "").strip()
        if redirect_url.startswith("https://"):
            return RedirectResponse(
                url=redirect_url,
                status_code=307,
                headers={
                    "Cache-Control": "no-store",
                    "Referrer-Policy": "no-referrer",
                    "X-Content-Type-Options": "nosniff",
                    "X-Robots-Tag": "noindex, nofollow",
                },
            )
        return _public_surface_html_error_response(404, "memorial_archive_publication_not_found")
    return HTMLResponse(html_path.read_text(encoding="utf-8"), headers=dict(_PUBLIC_MEMORIAL_HTML_HEADERS))


@router.get("/memorials/{slug}/app.webmanifest")
def public_memorial_pwa_manifest(slug: str, request: Request) -> JSONResponse:
    try:
        payload = _load_memorial(slug)
        prefer_install_surface = str(request.query_params.get("surface") or "").strip().lower() == "page"
        return JSONResponse(
            _memorial_pwa_manifest_payload(slug, payload, prefer_install_surface=prefer_install_surface),
            media_type="application/manifest+json",
            headers=dict(_PUBLIC_MEMORIAL_SUPPORT_HEADERS),
        )
    except HTTPException as exc:
        return _public_surface_error_response(exc.status_code, str(exc.detail))


@router.get("/memorials/{slug}/service-worker.js")
def public_memorial_pwa_service_worker_route(slug: str) -> Response:
    try:
        payload = _load_memorial(slug)
        return Response(
            content=_memorial_pwa_service_worker(slug, payload),
            media_type="application/javascript",
            headers={
                **_PUBLIC_MEMORIAL_SUPPORT_HEADERS,
                "Service-Worker-Allowed": f"/memorials/{_safe_slug(slug)}",
            },
        )
    except HTTPException as exc:
        return _public_surface_error_response(exc.status_code, str(exc.detail))


@router.get("/memorials/{slug}/icon-{size}.png")
def public_memorial_pwa_png_icon(slug: str, size: int) -> FileResponse:
    if size not in {180, 192, 512}:
        return _public_surface_error_response(404, "memorial_icon_not_found")
    try:
        payload = _load_memorial(slug)
    except HTTPException as exc:
        return _public_surface_error_response(exc.status_code, str(exc.detail))
    icon_path = _memorial_pwa_icon_file(slug, payload, size)
    if icon_path is None:
        return _public_surface_error_response(404, "memorial_icon_not_found")
    return FileResponse(
        icon_path,
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=3600",
            **_PUBLIC_MEMORIAL_STATIC_ASSET_HEADERS,
        },
    )


@router.get("/memorials/{slug}/icon.svg")
def public_memorial_pwa_icon(slug: str) -> Response:
    try:
        payload = _load_memorial(slug)
        return Response(
            content=_memorial_pwa_icon_svg(payload),
            media_type="image/svg+xml",
            headers={
                "Cache-Control": "public, max-age=3600",
                **_PUBLIC_MEMORIAL_STATIC_ASSET_HEADERS,
            },
        )
    except HTTPException as exc:
        return _public_surface_error_response(exc.status_code, str(exc.detail))


@router.get("/memorials/files/{slug}/{asset_path:path}")
def public_memorial_file(slug: str, asset_path: str) -> FileResponse:
    try:
        path = _asset_file(slug, asset_path)
    except HTTPException as exc:
        return _public_surface_error_response(exc.status_code, str(exc.detail))
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(
        path,
        media_type=media_type,
        filename=path.name,
        headers={
            "Cache-Control": "public, max-age=3600, immutable",
            **_PUBLIC_MEMORIAL_STATIC_ASSET_HEADERS,
        },
    )


@router.get("/memorials/{slug}", response_class=HTMLResponse)
def public_memorial_page(slug: str, request: Request) -> HTMLResponse:
    try:
        payload = _load_public_surface_memorial(slug)
        private_profile = _load_private_profile(slug)
        hostname = request_hostname(request)
        _prime_memorial_live_warmup_on_page_render(slug)
        response = HTMLResponse(
            _public_memorial_page_html(
                payload,
                private_profile=private_profile,
                hostname=hostname,
            ),
            headers=dict(_PUBLIC_MEMORIAL_HTML_HEADERS),
        )
        _ensure_memorial_guest_cookie(response, request, slug=slug)
        return response
    except HTTPException as exc:
        return _public_surface_html_error_response(exc.status_code, str(exc.detail))


@router.head("/memorials/{slug}")
def public_memorial_head(slug: str, request: Request) -> HTMLResponse:
    try:
        payload = _load_public_surface_memorial(slug)
        private_profile = _load_private_profile(slug)
        hostname = request_hostname(request)
        response = HTMLResponse(
            _public_memorial_page_html(
                payload,
                private_profile=private_profile,
                hostname=hostname,
            ),
            headers=dict(_PUBLIC_MEMORIAL_HTML_HEADERS),
        )
        _ensure_memorial_guest_cookie(response, request, slug=slug)
        return response
    except HTTPException as exc:
        return _public_surface_html_error_response(exc.status_code, str(exc.detail))
