from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from app.services.public_branding import request_brand
from app.services.public_urls import propertyquarry_public_base_url

PROPERTY_APP_PREFIXES = (
    "/app/properties",
    "/app/shortlist",
    "/app/research",
    "/app/profile",
    "/app/alerts",
    "/app/billing",
)

PROPERTY_API_EXACT_PATHS = {
    "/app/api/signals/google/property-sync",
    "/app/api/signals/google/willhaben-sync",
    "/app/api/signals/willhaben/property-tour",
}

PROPERTY_API_PREFIXES = (
    "/app/api/signals/property",
    "/v1/onboarding/property-search",
)

PROPERTY_API_CONTAINS = (
    "/preference-profile/property-feedback",
)

PROPERTY_API_SUFFIXES = (
    "/preference-profile/learning-summary",
)


def _path_matches_prefix(path: str, prefixes: tuple[str, ...]) -> bool:
    normalized = str(path or "").strip() or "/"
    return any(
        normalized == prefix
        or normalized.startswith(f"{prefix}/")
        or normalized.startswith(prefix)
        for prefix in prefixes
    )


def is_property_app_surface_path(path: str) -> bool:
    return _path_matches_prefix(path, PROPERTY_APP_PREFIXES)


def is_property_api_surface_path(path: str) -> bool:
    normalized = str(path or "").strip()
    return (
        normalized in PROPERTY_API_EXACT_PATHS
        or _path_matches_prefix(normalized, PROPERTY_API_PREFIXES)
        or any(fragment in normalized for fragment in PROPERTY_API_CONTAINS)
        or any(normalized.endswith(suffix) for suffix in PROPERTY_API_SUFFIXES)
    )


def propertyquarry_url_for_path(path: str, query: str = "") -> str:
    normalized_path = "/" + str(path or "/").strip().lstrip("/")
    target = f"{propertyquarry_public_base_url()}{normalized_path}"
    normalized_query = str(query or "").strip()
    if normalized_query:
        target = f"{target}?{normalized_query}"
    return target


def property_surface_boundary_response(request: Request) -> Response | None:
    brand = request_brand(request)
    if str(brand.get("key") or "").strip().lower() == "propertyquarry":
        return None

    path = str(request.url.path or "")
    if is_property_app_surface_path(path):
        response = JSONResponse(
            {
                "detail": "property_search_not_available",
                "product_boundary": "propertyquarry",
            },
            status_code=404,
        )
        response.headers["X-EA-Product-Boundary"] = "propertyquarry"
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
        return response

    if is_property_api_surface_path(path):
        response = JSONResponse(
            {
                "detail": "property_surface_not_found",
                "product_boundary": "propertyquarry",
            },
            status_code=404,
        )
        response.headers["X-EA-Product-Boundary"] = "propertyquarry"
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
        return response

    return None


def install_property_surface_boundary(app: FastAPI) -> None:
    @app.middleware("http")
    async def property_surface_boundary_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        boundary = property_surface_boundary_response(request)
        if boundary is not None:
            return boundary
        return await call_next(request)
