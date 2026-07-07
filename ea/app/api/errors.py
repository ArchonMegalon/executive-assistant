from __future__ import annotations

import logging
import urllib.parse
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse, Response

from app.api.routes.property_surface_boundary import property_surface_boundary_response

try:
    from psycopg import InterfaceError as PsycopgInterfaceError
    from psycopg import OperationalError as PsycopgOperationalError
except Exception:  # pragma: no cover - psycopg is optional in some test modes
    PsycopgInterfaceError = None
    PsycopgOperationalError = None


_LOG = logging.getLogger(__name__)


def _correlation_id(request: Request) -> str:
    return str(getattr(request.state, "correlation_id", "") or uuid.uuid4())


def _error_payload(
    *,
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": str(code or "error"),
                "message": str(message or "request_failed"),
                "details": details,
                "correlation_id": _correlation_id(request),
            }
        },
    )


def _log_scope_denial(request: Request, *, code: str, status_code: int, detail: Any) -> None:
    normalized_code = str(code or "").strip()
    if normalized_code not in {"operator_scope_required", "principal_scope_mismatch"}:
        return
    context = getattr(request.state, "ea_request_context", None)
    _LOG.warning(
        "request_scope_denied correlation_id=%s code=%s status_code=%s method=%s path=%s principal_id=%s operator_id=%s operator_authorized=%s auth_source=%s user_agent=%s detail=%s",
        _correlation_id(request),
        normalized_code,
        int(status_code or 0),
        str(request.method or "").upper(),
        str(request.url.path or "").strip(),
        str(getattr(context, "principal_id", "") or "").strip(),
        str(getattr(context, "operator_id", "") or "").strip(),
        bool(getattr(context, "operator_authorized", False)),
        str(getattr(context, "auth_source", "") or "").strip(),
        str(request.headers.get("user-agent") or "").strip(),
        str(detail or "").strip(),
    )


def _code_from_http(status_code: int, detail: Any) -> str:
    if isinstance(detail, str) and detail.strip():
        return detail.strip()
    if status_code == 400:
        return "bad_request"
    if status_code == 401:
        return "unauthorized"
    if status_code == 403:
        return "forbidden"
    if status_code == 404:
        return "not_found"
    if status_code == 409:
        return "conflict"
    if status_code == 422:
        return "validation_error"
    return "request_failed"


def _browser_auth_redirect(request: Request, *, code: str) -> Response | None:
    if str(code or "").strip() != "auth_required":
        return None
    if not _browser_admin_document_request(request):
        return None
    boundary = property_surface_boundary_response(request)
    if boundary is not None:
        return boundary
    target = "/sign-in?" + urllib.parse.urlencode({"return_to": _request_relative_uri(request)})
    response = RedirectResponse(target, status_code=303)
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
    return response


def _request_relative_uri(request: Request) -> str:
    path = str(request.url.path or "").strip() or "/"
    query = str(request.url.query or "").strip()
    return f"{path}?{query}" if query else path


def _browser_admin_document_request(request: Request) -> bool:
    method = str(request.method or "").upper()
    if method not in {"GET", "HEAD"}:
        return False
    path = str(request.url.path or "").strip()
    if not path.startswith("/app") and not path.startswith("/admin"):
        return False
    if path.startswith("/app/api") or path.startswith("/admin/api"):
        return False
    accept = str(request.headers.get("accept") or "").lower()
    sec_fetch_dest = str(request.headers.get("sec-fetch-dest") or "").lower()
    return "text/html" in accept or sec_fetch_dest == "document"


def _browser_operator_scope_redirect(request: Request, *, code: str) -> Response | None:
    if str(code or "").strip() != "operator_scope_required":
        return None
    if not _browser_admin_document_request(request):
        return None
    boundary = property_surface_boundary_response(request)
    if boundary is not None:
        return boundary
    return_to = _request_relative_uri(request)
    context = getattr(request.state, "ea_request_context", None)
    authenticated = bool(getattr(context, "authenticated", False))
    principal_id = str(getattr(context, "principal_id", "") or "").strip()
    container = getattr(getattr(request.app, "state", None), "container", None)
    if authenticated and principal_id and container is not None:
        try:
            from app.api.routes.landing_shared_support import operator_bootstrap_needed

            if operator_bootstrap_needed(container, principal_id=principal_id):
                target = "/admin/bootstrap-operator?" + urllib.parse.urlencode({"return_to": return_to})
                response = RedirectResponse(target, status_code=303)
                response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
                return response
        except Exception:
            pass
    target = "/sign-in?" + urllib.parse.urlencode({"return_to": return_to})
    response = RedirectResponse(target, status_code=303)
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
    return response


def install_error_handlers(app: FastAPI) -> None:
    @app.middleware("http")
    async def correlation_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.correlation_id = request.headers.get("x-correlation-id") or str(uuid.uuid4())
        response = await call_next(request)
        response.headers["x-correlation-id"] = _correlation_id(request)
        return response

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):  # type: ignore[no-untyped-def]
        code = _code_from_http(exc.status_code, exc.detail)
        _log_scope_denial(request, code=code, status_code=exc.status_code, detail=exc.detail)
        redirect = _browser_auth_redirect(request, code=code)
        if redirect is None:
            redirect = _browser_operator_scope_redirect(request, code=code)
        if redirect is not None:
            return redirect
        message = str(exc.detail or code)
        return _error_payload(
            request=request,
            status_code=exc.status_code,
            code=code,
            message=message,
            details=exc.detail,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):  # type: ignore[no-untyped-def]
        return _error_payload(
            request=request,
            status_code=422,
            code="validation_error",
            message="request validation failed",
            details=exc.errors(),
        )

    @app.exception_handler(PermissionError)
    async def permission_exception_handler(request: Request, exc: PermissionError):  # type: ignore[no-untyped-def]
        detail = str(exc or "forbidden").strip() or "forbidden"
        return _error_payload(
            request=request,
            status_code=403,
            code=_code_from_http(403, detail),
            message=detail,
            details=detail,
        )

    async def _database_unavailable_handler(request: Request, exc: Exception):  # type: ignore[no-untyped-def]
        correlation_id = _correlation_id(request)
        _LOG.warning(
            "database_unavailable correlation_id=%s error_type=%s detail=%s",
            correlation_id,
            exc.__class__.__name__,
            str(exc or "").strip(),
        )
        response = _error_payload(
            request=request,
            status_code=503,
            code="database_unavailable",
            message="temporary service interruption",
            details="database_temporarily_unavailable",
        )
        response.headers["Retry-After"] = "5"
        return response

    if PsycopgOperationalError is not None:
        app.add_exception_handler(PsycopgOperationalError, _database_unavailable_handler)
    if PsycopgInterfaceError is not None:
        app.add_exception_handler(PsycopgInterfaceError, _database_unavailable_handler)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):  # type: ignore[no-untyped-def]
        return _error_payload(
            request=request,
            status_code=500,
            code="internal_error",
            message="internal server error",
            details=exc.__class__.__name__,
        )
