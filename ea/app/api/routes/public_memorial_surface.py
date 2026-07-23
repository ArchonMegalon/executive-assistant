from __future__ import annotations

import mimetypes
import os
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)

from app.api.routes.memorial_memory_room import render_memorial_memory_room
from app.api.routes.public_memorial_surface_support import (
    _ALLOWED_PUBLIC_ASSET_SUFFIXES,
    _BLOCKED_PUBLIC_ASSET_NAMES,
    _apply_memorial_transport_security,
    _ensure_memorial_guest_cookie,
    _is_public_item,
    _list_of_dicts,
    _load_memorial,
    _load_private_profile,
    _memorial_bundle,
    _memorial_https_redirect,
    _memorial_transport_rejection,
    _memorial_voice_review_http_session_payload,
    _memorial_archive_publication_html_path,
    _memorial_pwa_icon_file,
    _memorial_pwa_icon_svg,
    _memorial_pwa_manifest_payload,
    _memorial_pwa_service_worker,
    _memorial_video_call_avatar,
    _public_memorial_archive_registry,
    _public_memorial_archive_registry_with_digest,
    _public_memorial_page_html,
    _public_memorial_payload,
    _payload_with_slug,
    _require_voice_consent,
    _safe_slug,
    _text,
    request_hostname,
)
from app.services.memorial_family_contributions import merge_public_family_contributions
from app.services.memorial_private_context import public_memorial_projection_source


router = APIRouter(tags=["public-memorial-surface"])


_PUBLIC_MEMORIAL_HTML_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "media-src 'self' blob:; connect-src 'self'; worker-src 'self'; "
        "manifest-src 'self'; font-src 'self'; object-src 'none'; "
        "frame-src 'none'; frame-ancestors 'none'; base-uri 'self'; "
        "form-action 'self'"
    ),
    "Permissions-Policy": "microphone=(self), camera=(), geolocation=(), interest-cohort=()",
    "X-Robots-Tag": "noindex, nofollow",
}

_PUBLIC_MEMORIAL_MEMORY_ROOM_HEADERS = {
    **_PUBLIC_MEMORIAL_HTML_HEADERS,
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
        "img-src 'none'; media-src 'none'; connect-src 'none'; worker-src 'none'; "
        "manifest-src 'none'; font-src 'none'; object-src 'none'; frame-src 'none'; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    ),
    "Permissions-Policy": (
        "microphone=(), camera=(), geolocation=(), interest-cohort=()"
    ),
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

_PUBLIC_MEMORIAL_ARCHIVE_PUBLISHED_SLUGS_ENV = (
    "EA_PUBLIC_MEMORIAL_ARCHIVE_PUBLISHED_SLUGS"
)
_PUBLIC_MEMORIAL_ARCHIVE_GATE_SCHEMA = "ea.memorial_archive_gate.v1"
_PUBLIC_MEMORIAL_ARCHIVE_GATE_STATE = "intentionally_unpublished"


def _public_surface_html_error_response(status_code: int, detail: str) -> HTMLResponse:
    del detail
    return HTMLResponse(
        (
            '<!doctype html><html lang="de"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            "<title>Erinnerungsseite gerade nicht erreichbar</title>"
            "<style>"
            ":root{color-scheme:light;--ink:#2d211a;--ink-soft:#67584c;--line:rgba(72,53,36,.16);--paper:rgba(255,251,246,.95);"
            "--shadow:0 28px 60px rgba(66,45,29,.12);--accent:#8c6949;}"
            '*{box-sizing:border-box;}body{margin:0;min-height:100vh;font-family:"Avenir Next","Segoe UI","Helvetica Neue",sans-serif;'
            "color:var(--ink);background:radial-gradient(circle at top, rgba(195,177,151,.28), transparent 38%),"
            "linear-gradient(180deg,#f5eee6 0%,#ebe1d4 48%,#f6f0e8 100%);display:flex;align-items:center;justify-content:center;padding:24px;}"
            "main{width:min(720px,100%);background:var(--paper);border:1px solid var(--line);border-radius:28px;padding:30px 28px;"
            'box-shadow:var(--shadow);}h1{margin:0 0 14px;font-family:"Iowan Old Style","Palatino Linotype",Georgia,serif;'
            "font-size:clamp(2rem,5vw,3rem);line-height:1.04;}p{margin:0 0 12px;line-height:1.6;color:var(--ink-soft);}"
            ".kicker{display:inline-block;margin-bottom:14px;font-size:.82rem;letter-spacing:.12em;text-transform:uppercase;color:var(--accent);}"
            ".actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:20px}.actions a{display:inline-flex;align-items:center;min-height:44px;padding:10px 16px;"
            "border:1px solid var(--line);border-radius:999px;color:var(--ink);font-weight:700;text-underline-offset:3px;}"
            '</style></head><body><main><div class="kicker">Erinnerungsseite</div>'
            "<h1>Diese Seite ist gerade nicht erreichbar.</h1>"
            "<p>Der Link kann vorübergehend nicht verfügbar sein. Private oder technische Details werden hier nicht angezeigt.</p>"
            "<p>Versuche es bitte noch einmal. Wenn die Seite weiter fehlt, frage die Person, von der du den Link erhalten hast.</p>"
            '<div class="actions"><a href="">Erneut versuchen</a><a href="/">Zur Startseite</a></div>'
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
    merged_payload = _load_memorial(slug)
    public_payload = public_memorial_projection_source(merged_payload)
    return merge_public_family_contributions(slug=slug, memorial=public_payload)


def _public_memorial_archive_is_published(slug: str) -> bool:
    safe_slug = _safe_slug(slug)
    published_slugs: set[str] = set()
    for raw_slug in os.getenv(
        _PUBLIC_MEMORIAL_ARCHIVE_PUBLISHED_SLUGS_ENV, ""
    ).split(","):
        candidate = raw_slug.strip()
        if not candidate:
            continue
        try:
            published_slugs.add(_safe_slug(candidate))
        except HTTPException:
            continue
    return safe_slug in published_slugs


def _require_public_memorial_archive_publication(slug: str) -> str:
    """Fail closed unless this memorial archive was explicitly published."""

    safe_slug = _safe_slug(slug)
    if not _public_memorial_archive_is_published(safe_slug):
        raise HTTPException(status_code=404, detail="memorial_not_found")
    return safe_slug


def _public_memorial_archive_unpublished_response(slug: str) -> JSONResponse:
    """Declare a verified unpublished gate without exposing archive content."""

    safe_slug = _safe_slug(slug)
    _load_public_surface_memorial(safe_slug)
    registry, registry_sha256 = _public_memorial_archive_registry_with_digest(
        safe_slug
    )
    if (
        not registry_sha256
        or str(registry.get("slug") or "").strip() != safe_slug
        or not list(registry.get("archive_sections") or [])
        or not list(registry.get("fliplink_publications") or [])
    ):
        raise HTTPException(status_code=404, detail="memorial_not_found")
    return JSONResponse(
        {
            "detail": "memorial_not_found",
            "archive_gate": {
                "schema": _PUBLIC_MEMORIAL_ARCHIVE_GATE_SCHEMA,
                "state": _PUBLIC_MEMORIAL_ARCHIVE_GATE_STATE,
                "slug": safe_slug,
                "registry_sha256": registry_sha256,
            },
        },
        status_code=404,
        headers={
            **_PUBLIC_MEMORIAL_SUPPORT_HEADERS,
            **_PUBLIC_MEMORIAL_ERROR_HEADERS,
        },
    )


def _public_memorial_asset_file(slug: str, asset_path: str) -> Path:
    """Resolve an asset only from the pre-private-overlay public projection."""

    bundle_dir = _memorial_bundle(slug)
    payload = _load_public_surface_memorial(slug)
    candidate = (bundle_dir / str(asset_path or "")).resolve()
    resolved_bundle = bundle_dir.resolve()
    if candidate != resolved_bundle and resolved_bundle not in candidate.parents:
        raise HTTPException(status_code=404, detail="memorial_file_not_found")
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="memorial_file_not_found")
    if (
        candidate.name.lower() in _BLOCKED_PUBLIC_ASSET_NAMES
        or candidate.suffix.lower() not in _ALLOWED_PUBLIC_ASSET_SUFFIXES
    ):
        raise HTTPException(status_code=404, detail="memorial_file_not_found")

    allowed_relpaths: set[str] = set()
    for clip in _list_of_dicts(payload.get("audio_clips")):
        if not _is_public_item(clip):
            continue
        relpath = _text(clip.get("asset_relpath"), "")
        if relpath:
            allowed_relpaths.add(PurePosixPath(relpath).as_posix().lstrip("/"))
    for document in _list_of_dicts(payload.get("public_documents")):
        if not _is_public_item(document):
            continue
        relpath = _text(document.get("asset_relpath"), "")
        if relpath:
            allowed_relpaths.add(PurePosixPath(relpath).as_posix().lstrip("/"))
    avatar = _memorial_video_call_avatar(payload, slug)
    for key in ("asset_relpath", "poster_relpath"):
        relpath = _text(avatar.get(key), "")
        if relpath:
            allowed_relpaths.add(PurePosixPath(relpath).as_posix().lstrip("/"))

    relative_path = candidate.relative_to(resolved_bundle).as_posix().lstrip("/")
    if relative_path not in allowed_relpaths:
        raise HTTPException(status_code=404, detail="memorial_file_not_found")
    return candidate


@router.get("/memorials/{slug}.json")
def public_memorial_manifest(slug: str) -> JSONResponse:
    try:
        payload = _public_memorial_payload(_load_public_surface_memorial(slug))
        if not _public_memorial_archive_is_published(slug):
            payload["archive_sections"] = []
            payload["fliplink_publications"] = []
        return JSONResponse(
            payload,
            headers=dict(_PUBLIC_MEMORIAL_SUPPORT_HEADERS),
        )
    except HTTPException as exc:
        return _public_surface_error_response(exc.status_code, str(exc.detail))


@router.get("/memorials/{slug}/archive.json")
def public_memorial_archive_manifest(slug: str) -> JSONResponse:
    try:
        safe_slug = _safe_slug(slug)
        if not _public_memorial_archive_is_published(safe_slug):
            return _public_memorial_archive_unpublished_response(safe_slug)
        _load_memorial(safe_slug)
        return JSONResponse(
            _public_memorial_archive_registry(safe_slug),
            headers=dict(_PUBLIC_MEMORIAL_SUPPORT_HEADERS),
        )
    except HTTPException as exc:
        return _public_surface_error_response(exc.status_code, str(exc.detail))


@router.get("/memorials/{slug}/archive")
def public_memorial_archive_index(slug: str, request: Request) -> Response:
    rejection = _memorial_transport_rejection(request)
    if rejection is not None:
        return rejection
    redirect = _memorial_https_redirect(request)
    if redirect is not None:
        return redirect
    try:
        _require_public_memorial_archive_publication(slug)
        payload = _load_public_surface_memorial(slug)
        response = HTMLResponse(
            _public_memorial_page_html(
                payload,
                hostname=request_hostname(request),
            ),
            headers=dict(_PUBLIC_MEMORIAL_HTML_HEADERS),
        )
        _ensure_memorial_guest_cookie(response, request, slug=slug)
        return _apply_memorial_transport_security(response, request)
    except HTTPException as exc:
        response = _public_surface_html_error_response(exc.status_code, str(exc.detail))
        return _apply_memorial_transport_security(response, request)


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
            or str(raw_item.get("review_status") or "").strip().lower() != "published"
            or not str(raw_item.get("url") or "").strip()
        ):
            continue
        return dict(raw_item)
    return None


@router.get("/memorials/{slug}/archive/{publication_slug}")
def public_memorial_archive_publication(
    slug: str, publication_slug: str, request: Request
) -> Response:
    rejection = _memorial_transport_rejection(request)
    if rejection is not None:
        return rejection
    redirect = _memorial_https_redirect(request)
    if redirect is not None:
        return redirect
    try:
        _require_public_memorial_archive_publication(slug)
        _load_memorial(slug)
        safe_slug = _safe_slug(slug)
        safe_publication_slug = _safe_slug(publication_slug)
        publication = _authorized_public_memorial_archive_publication(
            safe_slug,
            safe_publication_slug,
        )
    except HTTPException as exc:
        response = _public_surface_html_error_response(
            exc.status_code,
            str(exc.detail),
        )
        return _apply_memorial_transport_security(response, request)

    if publication is None:
        response = _public_surface_html_error_response(
            404,
            "memorial_archive_publication_not_found",
        )
        return _apply_memorial_transport_security(response, request)

    html_path = _memorial_archive_publication_html_path(
        safe_slug,
        safe_publication_slug,
    )
    if not html_path.is_file():
        redirect_url = str(publication.get("url") or "").strip()
        if redirect_url.startswith("https://"):
            response = RedirectResponse(
                url=redirect_url,
                status_code=307,
                headers={
                    "Cache-Control": "no-store",
                    "Referrer-Policy": "no-referrer",
                    "X-Content-Type-Options": "nosniff",
                    "X-Robots-Tag": "noindex, nofollow",
                },
            )
            return _apply_memorial_transport_security(response, request)
        response = _public_surface_html_error_response(
            404,
            "memorial_archive_publication_not_found",
        )
        return _apply_memorial_transport_security(response, request)

    response = HTMLResponse(
        html_path.read_text(encoding="utf-8"),
        headers=dict(_PUBLIC_MEMORIAL_HTML_HEADERS),
    )
    return _apply_memorial_transport_security(response, request)


def _public_memorial_memory_room_response(
    slug: str,
    request: Request,
    *,
    head_only: bool,
) -> Response:
    rejection = _memorial_transport_rejection(request)
    if rejection is not None:
        return rejection
    redirect = _memorial_https_redirect(request)
    if redirect is not None:
        return redirect
    try:
        safe_slug = _safe_slug(slug)
        payload = _public_memorial_payload(_load_public_surface_memorial(safe_slug))
        content = render_memorial_memory_room(payload, slug=safe_slug)
        response: Response
        if head_only:
            response = Response(
                content=b"",
                media_type="text/html",
                headers=dict(_PUBLIC_MEMORIAL_MEMORY_ROOM_HEADERS),
            )
        else:
            response = HTMLResponse(
                content,
                headers=dict(_PUBLIC_MEMORIAL_MEMORY_ROOM_HEADERS),
            )
        return _apply_memorial_transport_security(response, request)
    except HTTPException as exc:
        response = _public_surface_html_error_response(exc.status_code, str(exc.detail))
        return _apply_memorial_transport_security(response, request)


@router.get("/memorials/{slug}/memory-room", response_class=HTMLResponse)
def public_memorial_memory_room(slug: str, request: Request) -> Response:
    return _public_memorial_memory_room_response(slug, request, head_only=False)


@router.head("/memorials/{slug}/memory-room")
def public_memorial_memory_room_head(slug: str, request: Request) -> Response:
    return _public_memorial_memory_room_response(slug, request, head_only=True)


@router.get("/memorials/{slug}/app.webmanifest")
def public_memorial_pwa_manifest(slug: str, request: Request) -> JSONResponse:
    try:
        payload = _load_public_surface_memorial(slug)
        prefer_install_surface = (
            str(request.query_params.get("surface") or "").strip().lower() == "page"
        )
        return JSONResponse(
            _memorial_pwa_manifest_payload(
                slug, payload, prefer_install_surface=prefer_install_surface
            ),
            media_type="application/manifest+json",
            headers=dict(_PUBLIC_MEMORIAL_SUPPORT_HEADERS),
        )
    except HTTPException as exc:
        return _public_surface_error_response(exc.status_code, str(exc.detail))


@router.get("/memorials/{slug}/service-worker.js")
def public_memorial_pwa_service_worker_route(slug: str) -> Response:
    try:
        payload = _load_public_surface_memorial(slug)
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
        payload = _load_public_surface_memorial(slug)
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
        payload = _load_public_surface_memorial(slug)
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
        path = _public_memorial_asset_file(slug, asset_path)
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


@router.api_route(
    "/memorial/manfred",
    methods=["GET", "HEAD"],
    include_in_schema=False,
)
def manfred_memorial_singular_alias(request: Request) -> Response:
    rejection = _memorial_transport_rejection(request)
    if rejection is not None:
        return rejection
    target = "/memorials/manfred"
    if request.url.query:
        target = f"{target}?{request.url.query}"
    if any(ord(character) < 32 or ord(character) == 127 for character in target):
        raise HTTPException(status_code=400, detail="memorial_alias_url_invalid")
    return RedirectResponse(
        url=target,
        status_code=308,
        headers=dict(_PUBLIC_MEMORIAL_SUPPORT_HEADERS),
    )


@router.get("/memorials/{slug}", response_class=HTMLResponse)
def public_memorial_page(slug: str, request: Request) -> Response:
    rejection = _memorial_transport_rejection(request)
    if rejection is not None:
        return rejection
    redirect = _memorial_https_redirect(request)
    if redirect is not None:
        return redirect
    try:
        payload = _load_public_surface_memorial(slug)
        private_profile = _load_private_profile(slug)
        hostname = request_hostname(request)
        operator_preview_allowed = (
            _memorial_voice_review_http_session_payload(
                request,
                slug=slug,
                required_scope="page",
                allow_originless_navigation=True,
            )
            is not None
        )
        if operator_preview_allowed:
            _require_voice_consent(
                _payload_with_slug(slug, payload),
                "realtime",
                operator_preview_allowed=True,
            )
        response = HTMLResponse(
            _public_memorial_page_html(
                payload,
                private_profile=private_profile,
                hostname=hostname,
                operator_preview_allowed=operator_preview_allowed,
            ),
            headers=dict(_PUBLIC_MEMORIAL_HTML_HEADERS),
        )
        _ensure_memorial_guest_cookie(response, request, slug=slug)
        return _apply_memorial_transport_security(response, request)
    except HTTPException as exc:
        response = _public_surface_html_error_response(exc.status_code, str(exc.detail))
        return _apply_memorial_transport_security(response, request)


@router.head("/memorials/{slug}")
def public_memorial_head(slug: str, request: Request) -> Response:
    rejection = _memorial_transport_rejection(request)
    if rejection is not None:
        return rejection
    redirect = _memorial_https_redirect(request)
    if redirect is not None:
        return redirect
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
        return _apply_memorial_transport_security(response, request)
    except HTTPException as exc:
        response = _public_surface_html_error_response(exc.status_code, str(exc.detail))
        return _apply_memorial_transport_security(response, request)
