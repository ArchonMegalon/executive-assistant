from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


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

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):  # type: ignore[no-untyped-def]
        return _error_payload(
            request=request,
            status_code=500,
            code="internal_error",
            message="internal server error",
            details=exc.__class__.__name__,
        )
