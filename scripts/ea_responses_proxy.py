#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import stat
import sys
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ea"))

from app.api.dependencies import RequestContext  # noqa: E402
from app.api.routes.responses import _run_response  # noqa: E402
from app.api.routes.responses_read_routes import models_response_payload  # noqa: E402
from app.main import app  # noqa: E402
from app.services.responses_upstream import list_response_models  # noqa: E402
from fastapi.responses import JSONResponse, StreamingResponse  # noqa: E402


LOG = logging.getLogger("ea.responses_proxy")
CONTAINER = app.state.container
AUTH_TOKEN = str(CONTAINER.settings.auth.api_token or "").strip()
# This is an environment variable name, not a credential value.
_MEMORIAL_TOKEN_FILE_ENV = "EA_RESPONSES_MEMORIAL_CLIENT_TOKEN_FILE"  # nosec B105
_MEMORIAL_SCOPE = "memorial_no_retention"
_MEMORIAL_PRINCIPAL = "memorial-service"
_MEMORIAL_PROFILE = "groundwork"
_MEMORIAL_MODEL = "ea-onemin-coder"
_MEMORIAL_RETENTION_CONTRACT = "no_response_storage_no_debug_v1"
_MEMORIAL_REQUEST_FIELDS = frozenset({"model", "input", "max_output_tokens", "store"})
_MAX_REQUEST_BYTES = 256 * 1024
_MAX_MEMORIAL_INPUT_CHARS = 120_000


def _read_client_token_file(raw_path: str) -> str:
    configured = str(raw_path or "").strip()
    if not configured:
        return ""
    path = Path(configured)
    if not path.is_absolute():
        raise RuntimeError(f"{_MEMORIAL_TOKEN_FILE_ENV} must be an absolute path")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RuntimeError(f"{_MEMORIAL_TOKEN_FILE_ENV} is unreadable") from exc
    try:
        metadata = os.fstat(descriptor)
        mode = stat.S_IMODE(metadata.st_mode)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise RuntimeError(
                f"{_MEMORIAL_TOKEN_FILE_ENV} must reference one regular file"
            )
        if mode & 0o037:
            raise RuntimeError(
                f"{_MEMORIAL_TOKEN_FILE_ENV} must not be writable by group or accessible by others"
            )
        if metadata.st_uid not in {0, os.geteuid()}:
            allowed_groups = {os.getegid(), *os.getgroups()}
            if metadata.st_gid not in allowed_groups or not mode & stat.S_IRGRP:
                raise RuntimeError(
                    f"{_MEMORIAL_TOKEN_FILE_ENV} owner or group is not trusted"
                )
        raw = os.read(descriptor, 4097)
        if len(raw) > 4096:
            raise RuntimeError(f"{_MEMORIAL_TOKEN_FILE_ENV} is too large")
    finally:
        os.close(descriptor)
    try:
        token = raw.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise RuntimeError(
            f"{_MEMORIAL_TOKEN_FILE_ENV} must contain UTF-8 text"
        ) from exc
    if len(token) < 32 or any(character.isspace() for character in token):
        raise RuntimeError(f"{_MEMORIAL_TOKEN_FILE_ENV} contains an invalid token")
    return token


MEMORIAL_CLIENT_TOKEN = _read_client_token_file(
    os.environ.get(_MEMORIAL_TOKEN_FILE_ENV, "")
)
if (
    AUTH_TOKEN
    and MEMORIAL_CLIENT_TOKEN
    and hmac.compare_digest(AUTH_TOKEN, MEMORIAL_CLIENT_TOKEN)
):
    raise RuntimeError("Memorial client token must differ from the EA operator token")


@dataclass(frozen=True)
class _ProxyAuthContext:
    request_context: RequestContext
    scope: str


def _header_value(headers: Mapping[str, str] | Any, name: str) -> str:
    return str(headers.get(name) or headers.get(name.lower()) or "").strip()


def _authenticate_proxy_client(
    headers: Mapping[str, str] | Any,
    *,
    operator_token: str,
    memorial_token: str,
    default_principal_id: str,
) -> tuple[_ProxyAuthContext | None, str]:
    provided = _header_value(headers, "X-EA-API-Token") or _header_value(
        headers, "X-API-Token"
    )
    if memorial_token and hmac.compare_digest(provided, memorial_token):
        if (
            _header_value(headers, "X-EA-Principal-ID") != _MEMORIAL_PRINCIPAL
            or _header_value(headers, "X-EA-Codex-Profile").lower() != _MEMORIAL_PROFILE
            or _header_value(headers, "X-EA-Retention").lower() != "none"
        ):
            return None, "memorial_scope_invalid"
        if any(
            _header_value(headers, name)
            for name in (
                "X-EA-Onemin-Account-Alias",
                "X-EA-Onemin-Account-Env",
                "X-EA-Onemin-Account",
                "X-EA-Onemin-Preferred-Accounts",
            )
        ):
            return None, "memorial_scope_invalid"
        return (
            _ProxyAuthContext(
                request_context=RequestContext(
                    principal_id=_MEMORIAL_PRINCIPAL,
                    authenticated=True,
                    auth_source="memorial_client_token",
                ),
                scope=_MEMORIAL_SCOPE,
            ),
            "",
        )
    if operator_token and hmac.compare_digest(provided, operator_token):
        principal_id = _header_value(headers, "X-EA-Principal-ID")
        principal_id = (
            principal_id
            or str(default_principal_id or "").strip()
            or "principal-default"
        )
        return (
            _ProxyAuthContext(
                request_context=RequestContext(
                    principal_id=principal_id,
                    authenticated=True,
                    auth_source="api_token",
                ),
                scope="operator",
            ),
            "",
        )
    if operator_token or memorial_token:
        return None, "auth_required"
    principal_id = _header_value(headers, "X-EA-Principal-ID")
    principal_id = (
        principal_id or str(default_principal_id or "").strip() or "principal-default"
    )
    return (
        _ProxyAuthContext(
            request_context=RequestContext(
                principal_id=principal_id,
                authenticated=False,
                auth_source="anonymous",
            ),
            scope="anonymous",
        ),
        "",
    )


def _memorial_payload_error(payload: dict[str, Any]) -> str:
    if set(payload) != _MEMORIAL_REQUEST_FIELDS:
        return "memorial_payload_fields_invalid"
    if payload.get("model") != _MEMORIAL_MODEL:
        return "memorial_model_invalid"
    input_text = payload.get("input")
    if (
        not isinstance(input_text, str)
        or not input_text.strip()
        or len(input_text) > _MAX_MEMORIAL_INPUT_CHARS
    ):
        return "memorial_input_invalid"
    max_output_tokens = payload.get("max_output_tokens")
    if (
        isinstance(max_output_tokens, bool)
        or not isinstance(max_output_tokens, int)
        or not 1 <= max_output_tokens <= 900
    ):
        return "memorial_output_limit_invalid"
    if payload.get("store") is not False:
        return "memorial_retention_invalid"
    return ""


def _memorial_response(response: JSONResponse | StreamingResponse) -> JSONResponse:
    if (
        not isinstance(response, JSONResponse)
        or getattr(response, "body", None) is None
    ):
        return JSONResponse(
            {
                "error": {
                    "code": "memorial_provider_contract_failed",
                    "message": "provider contract failed",
                }
            },
            status_code=502,
        )
    try:
        payload = json.loads(bytes(response.body).decode("utf-8"))
        metadata = payload["metadata"]
        if (
            int(getattr(response, "status_code", 200) or 200) != 200
            or payload["status"] != "completed"
            or payload["model"] != _MEMORIAL_MODEL
            or not isinstance(metadata, dict)
            or metadata.get("upstream_provider") != "onemin"
            or not str(metadata.get("upstream_model") or "").strip()
        ):
            raise ValueError("provider_contract_mismatch")
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return JSONResponse(
            {
                "error": {
                    "code": "memorial_provider_contract_failed",
                    "message": "provider contract failed",
                }
            },
            status_code=502,
        )
    sanitized = dict(payload)
    sanitized["input"] = []
    sanitized["instructions"] = None
    sanitized["reasoning"] = None
    sanitized["metadata"] = {
        "upstream_provider": "onemin",
        "upstream_model": str(metadata["upstream_model"]),
        "ea_retention": "none",
        "ea_retention_contract": _MEMORIAL_RETENTION_CONTRACT,
    }
    return JSONResponse(sanitized, status_code=200)


def _normalize_profile(raw: str) -> str:
    value = str(raw or "").strip().lower()
    if value == "jury":
        value = "audit"
    if value == "review-light":
        value = "review_light"
    if value not in {
        "core",
        "core_batch",
        "core_rescue",
        "easy",
        "repair",
        "groundwork",
        "review_light",
        "survival",
        "audit",
    }:
        return ""
    return value


def _preferred_onemin_labels(
    headers: BaseHTTPRequestHandler.headers.__class__,
) -> tuple[str, ...]:
    labels: list[str] = []
    for header_name in (
        "X-EA-Onemin-Account-Alias",
        "X-EA-Onemin-Account-Env",
        "X-EA-Onemin-Account",
        "X-EA-Onemin-Preferred-Accounts",
    ):
        raw = str(headers.get(header_name) or "").strip()
        if not raw:
            continue
        for part in raw.replace(";", ",").split(","):
            label = str(part or "").strip()
            if label and label not in labels:
                labels.append(label)
    return tuple(labels)


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


class ResponsesProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        LOG.info("%s - %s", self.address_string(), fmt % args)

    def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = _json_bytes(payload)
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self._write_payload(body)

    def _write_payload(self, payload: bytes) -> bool:
        try:
            self.wfile.write(payload)
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError):
            LOG.info("responses proxy client disconnected before payload flush")
            return False

    def _auth_context(self) -> _ProxyAuthContext | None:
        auth_context, error_code = _authenticate_proxy_client(
            self.headers,
            operator_token=AUTH_TOKEN,
            memorial_token=MEMORIAL_CLIENT_TOKEN,
            default_principal_id=str(
                CONTAINER.settings.auth.default_principal_id or ""
            ),
        )
        if auth_context is None:
            status_code = 403 if error_code == "memorial_scope_invalid" else 401
            self._send_json(
                status_code,
                {"error": {"code": error_code, "message": error_code}},
            )
            return None
        return auth_context

    def _read_payload(self) -> dict[str, Any] | None:
        try:
            content_length = int(
                str(self.headers.get("Content-Length") or "0").strip() or "0"
            )
        except ValueError:
            self._send_json(
                400,
                {"error": {"code": "bad_request", "message": "invalid_content_length"}},
            )
            return None
        if content_length < 0 or content_length > _MAX_REQUEST_BYTES:
            self._send_json(
                413,
                {
                    "error": {
                        "code": "request_too_large",
                        "message": "request_too_large",
                    }
                },
            )
            return None
        raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._send_json(
                400,
                {"error": {"code": "bad_request", "message": "invalid_json"}},
            )
            return None
        if not isinstance(payload, dict):
            self._send_json(
                400,
                {"error": {"code": "bad_request", "message": "invalid_payload"}},
            )
            return None
        return payload

    def _write_starlette_response(
        self, response: JSONResponse | StreamingResponse
    ) -> None:
        self.send_response(int(getattr(response, "status_code", 200) or 200))
        for key, value in response.headers.items():
            lowered = str(key).strip().lower()
            if lowered == "content-length" and isinstance(response, StreamingResponse):
                continue
            self.send_header(key, value)
        self.send_header("Connection", "close")
        body = getattr(response, "body", None)
        if body is not None:
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body is not None:
            self._write_payload(body)
            return

        async def _stream() -> None:
            async for chunk in response.body_iterator:
                payload = (
                    chunk.encode("utf-8") if isinstance(chunk, str) else bytes(chunk)
                )
                if not self._write_payload(payload):
                    break

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_stream())
        finally:
            loop.close()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path in {"/health/live", "/health/ready"}:
            self._send_json(200, {"status": "ready", "reason": "responses_proxy_ready"})
            return
        if parsed.path == "/v1/models":
            self._send_json(
                200, models_response_payload(list_response_models=list_response_models)
            )
            return
        self._send_json(404, {"error": {"code": "not_found", "message": "not_found"}})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/v1/responses":
            self._send_json(
                404, {"error": {"code": "not_found", "message": "not_found"}}
            )
            return
        auth_context = self._auth_context()
        if auth_context is None:
            return
        payload = self._read_payload()
        if payload is None:
            return
        if auth_context.scope == _MEMORIAL_SCOPE:
            content_type = (
                _header_value(self.headers, "Content-Type")
                .split(";", 1)[0]
                .strip()
                .lower()
            )
            if content_type != "application/json":
                self._send_json(
                    400,
                    {
                        "error": {
                            "code": "memorial_content_type_invalid",
                            "message": "memorial_content_type_invalid",
                        }
                    },
                )
                return
            payload_error = _memorial_payload_error(payload)
            if payload_error:
                self._send_json(
                    400,
                    {"error": {"code": payload_error, "message": payload_error}},
                )
                return
        profile = _normalize_profile(
            str(
                self.headers.get("X-EA-Codex-Profile")
                or self.headers.get("X-CodexEA-Profile")
                or ""
            )
        )
        try:
            response = _run_response(
                payload,
                context=auth_context.request_context,
                container=CONTAINER,
                codex_profile=_MEMORIAL_PROFILE
                if auth_context.scope == _MEMORIAL_SCOPE
                else (profile or None),
                preferred_onemin_labels=(
                    ()
                    if auth_context.scope == _MEMORIAL_SCOPE
                    else _preferred_onemin_labels(self.headers)
                ),
                lock_requested_model=auth_context.scope == _MEMORIAL_SCOPE,
                allow_debug_capture=auth_context.scope != _MEMORIAL_SCOPE,
            )
        except Exception as exc:
            LOG.exception("responses proxy request failed")
            self._send_json(
                500,
                {
                    "error": {
                        "code": "internal_error",
                        "message": "internal server error",
                        "details": exc.__class__.__name__,
                    }
                },
            )
            return
        if auth_context.scope == _MEMORIAL_SCOPE:
            response = _memorial_response(response)
        self._write_starlette_response(response)


def main() -> None:
    logging.basicConfig(
        level=getattr(
            logging,
            str(os.environ.get("EA_RESPONSES_PROXY_LOG_LEVEL") or "INFO")
            .strip()
            .upper(),
            logging.INFO,
        ),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    host = (
        str(os.environ.get("EA_RESPONSES_PROXY_HOST") or "127.0.0.1").strip()
        or "127.0.0.1"
    )
    port = int(
        str(os.environ.get("EA_RESPONSES_PROXY_PORT") or "8091").strip() or "8091"
    )
    server = ThreadingHTTPServer((host, port), ResponsesProxyHandler)
    server.daemon_threads = True
    LOG.info("responses proxy listening host=%s port=%s", host, port)
    server.serve_forever()


if __name__ == "__main__":
    main()
