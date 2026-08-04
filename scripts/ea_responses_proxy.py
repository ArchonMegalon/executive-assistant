#!/usr/bin/env python3
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hmac
import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ea"))

from app.api.dependencies import RequestContext  # noqa: E402
from app.api.routes.responses import _no_retention_response_scope, _run_response  # noqa: E402
from app.api.routes.responses_read_routes import models_response_payload  # noqa: E402
from app.main import app  # noqa: E402
from app.services.responses_upstream import list_response_models  # noqa: E402
from fastapi.responses import JSONResponse, StreamingResponse  # noqa: E402


LOG = logging.getLogger("ea.responses_proxy")
CONTAINER = app.state.container
AUTH_TOKEN = str(CONTAINER.settings.auth.api_token or "").strip()


@dataclass(frozen=True)
class _NoRetentionClient:
    principal_id: str
    token: str


def _load_no_retention_clients(path_value: str | None = None) -> tuple[_NoRetentionClient, ...]:
    path_text = str(
        path_value
        if path_value is not None
        else os.environ.get("EA_RESPONSES_NO_RETENTION_CLIENTS_FILE") or ""
    ).strip()
    if not path_text:
        return ()
    try:
        payload = json.loads(Path(path_text).read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError("invalid no-retention client configuration") from exc
    rows = payload.get("clients") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("no-retention client configuration has no clients")
    clients: list[_NoRetentionClient] = []
    principals: set[str] = set()
    tokens: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("invalid no-retention client entry")
        principal_id = str(row.get("principal_id") or "").strip()
        token = str(row.get("token") or "").strip()
        if not principal_id or len(token) < 32:
            raise RuntimeError("invalid no-retention client credentials")
        if principal_id in principals or token in tokens or (AUTH_TOKEN and hmac.compare_digest(token, AUTH_TOKEN)):
            raise RuntimeError("duplicate no-retention client credentials")
        principals.add(principal_id)
        tokens.add(token)
        clients.append(_NoRetentionClient(principal_id=principal_id, token=token))
    return tuple(clients)


NO_RETENTION_CLIENTS = _load_no_retention_clients()


def _normalize_profile(raw: str) -> str:
    value = str(raw or "").strip().lower()
    if value == "jury":
        value = "audit"
    if value == "review-light":
        value = "review_light"
    if value not in {"core", "core_batch", "core_rescue", "easy", "repair", "groundwork", "review_light", "survival", "audit"}:
        return ""
    return value


def _preferred_onemin_labels(headers: BaseHTTPRequestHandler.headers.__class__) -> tuple[str, ...]:
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


def _no_retention_client(provided_token: str) -> _NoRetentionClient | None:
    if not provided_token:
        return None
    for client in NO_RETENTION_CLIENTS:
        if hmac.compare_digest(provided_token, client.token):
            return client
    return None


def _no_retention_response(response: JSONResponse | StreamingResponse) -> JSONResponse:
    if isinstance(response, StreamingResponse) or getattr(response, "body", None) is None:
        return JSONResponse(
            status_code=502,
            content={"error": {"code": "invalid_manager_response", "message": "invalid manager response"}},
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )
    try:
        payload = json.loads(bytes(response.body).decode("utf-8"))
    except Exception:
        payload = None
    if not isinstance(payload, dict):
        return JSONResponse(
            status_code=502,
            content={"error": {"code": "invalid_manager_response", "message": "invalid manager response"}},
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )
    if int(getattr(response, "status_code", 200) or 200) >= 400:
        return JSONResponse(
            status_code=int(getattr(response, "status_code", 500) or 500),
            content=payload,
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict) or str(metadata.get("upstream_provider") or "").strip().lower() != "onemin":
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "required_provider_unavailable",
                    "message": "required provider unavailable",
                }
            },
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )
    metadata["ea_retention"] = "none"
    metadata["ea_retention_contract"] = "no_response_storage_no_debug_v1"
    payload["metadata"] = metadata
    return JSONResponse(
        status_code=int(getattr(response, "status_code", 200) or 200),
        content=payload,
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


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

    def _auth_context(self) -> tuple[RequestContext, bool] | None:
        provided = str(self.headers.get("x-ea-api-token") or self.headers.get("x-api-token") or "").strip()
        no_retention_client = _no_retention_client(provided)
        if no_retention_client is not None:
            return (
                RequestContext(
                    principal_id=no_retention_client.principal_id,
                    authenticated=True,
                    auth_source="api_token",
                ),
                True,
            )
        if AUTH_TOKEN and not hmac.compare_digest(provided, AUTH_TOKEN):
            self._send_json(
                401,
                {"error": {"code": "auth_required", "message": "auth_required"}},
            )
            return None
        if not AUTH_TOKEN and NO_RETENTION_CLIENTS and provided:
            self._send_json(
                401,
                {"error": {"code": "auth_required", "message": "auth_required"}},
            )
            return None
        principal_id = str(self.headers.get("X-EA-Principal-ID") or "").strip()
        if not principal_id:
            principal_id = str(CONTAINER.settings.auth.default_principal_id or "").strip() or "principal-default"
        return (
            RequestContext(
                principal_id=principal_id,
                authenticated=bool(AUTH_TOKEN),
                auth_source="api_token" if AUTH_TOKEN else "anonymous",
            ),
            False,
        )

    def _read_payload(self) -> dict[str, Any] | None:
        content_length = int(str(self.headers.get("Content-Length") or "0").strip() or "0")
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

    def _write_starlette_response(self, response: JSONResponse | StreamingResponse) -> None:
        self.send_response(int(getattr(response, "status_code", 200) or 200))
        for key, value in response.headers.items():
            lowered = str(key).strip().lower()
            if lowered == "content-length":
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
                payload = chunk.encode("utf-8") if isinstance(chunk, str) else bytes(chunk)
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
            self._send_json(200, models_response_payload(list_response_models=list_response_models))
            return
        self._send_json(404, {"error": {"code": "not_found", "message": "not_found"}})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/v1/responses":
            self._send_json(404, {"error": {"code": "not_found", "message": "not_found"}})
            return
        auth = self._auth_context()
        if auth is None:
            return
        context, no_retention_client = auth
        payload = self._read_payload()
        if payload is None:
            return
        retention_mode = str(self.headers.get("X-EA-Retention") or "").strip().lower()
        if retention_mode not in {"", "none"}:
            self._send_json(
                400,
                {"error": {"code": "invalid_retention_mode", "message": "invalid retention mode"}},
            )
            return
        if no_retention_client and retention_mode != "none":
            self._send_json(
                403,
                {"error": {"code": "retention_contract_required", "message": "retention contract required"}},
            )
            return
        if retention_mode == "none" and not no_retention_client:
            self._send_json(
                403,
                {"error": {"code": "retention_scope_required", "message": "retention scope required"}},
            )
            return
        if no_retention_client:
            if payload.get("stream") is True or payload.get("background") is True or payload.get("previous_response_id"):
                self._send_json(
                    400,
                    {"error": {"code": "unsupported_no_retention_request", "message": "unsupported request"}},
                )
                return
            payload["store"] = False
            payload["stream"] = False
            payload.pop("background", None)
            payload["tools"] = []
            payload["tool_choice"] = "none"
        profile = _normalize_profile(
            str(self.headers.get("X-EA-Codex-Profile") or self.headers.get("X-CodexEA-Profile") or "")
        )
        try:
            if no_retention_client:
                with _no_retention_response_scope():
                    response = _run_response(
                        payload,
                        context=context,
                        container=CONTAINER,
                        codex_profile=profile or "groundwork",
                        preferred_onemin_labels=(),
                    )
                response = _no_retention_response(response)
            else:
                response = _run_response(
                    payload,
                    context=context,
                    container=CONTAINER,
                    codex_profile=profile or None,
                    preferred_onemin_labels=_preferred_onemin_labels(self.headers),
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
        self._write_starlette_response(response)


def main() -> None:
    logging.basicConfig(
        level=getattr(logging, str(os.environ.get("EA_RESPONSES_PROXY_LOG_LEVEL") or "INFO").strip().upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    host = str(os.environ.get("EA_RESPONSES_PROXY_HOST") or "127.0.0.1").strip() or "127.0.0.1"
    port = int(str(os.environ.get("EA_RESPONSES_PROXY_PORT") or "8091").strip() or "8091")
    server = ThreadingHTTPServer((host, port), ResponsesProxyHandler)
    server.daemon_threads = True
    LOG.info("responses proxy listening host=%s port=%s", host, port)
    server.serve_forever()


if __name__ == "__main__":
    main()
