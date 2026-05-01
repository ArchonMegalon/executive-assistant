#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

sys.path.insert(0, "/docker/EA/ea")

from app.api.dependencies import RequestContext  # noqa: E402
from app.api.routes.responses import _run_response  # noqa: E402
from app.main import app  # noqa: E402
from app.services.responses_upstream import list_response_models  # noqa: E402
from fastapi.responses import JSONResponse, StreamingResponse  # noqa: E402


LOG = logging.getLogger("ea.responses_proxy")
CONTAINER = app.state.container
AUTH_TOKEN = str(CONTAINER.settings.auth.api_token or "").strip()


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

    def _auth_context(self) -> RequestContext | None:
        provided = str(self.headers.get("x-ea-api-token") or self.headers.get("x-api-token") or "").strip()
        if AUTH_TOKEN and provided != AUTH_TOKEN:
            self._send_json(
                401,
                {"error": {"code": "auth_required", "message": "auth_required"}},
            )
            return None
        principal_id = str(self.headers.get("X-EA-Principal-ID") or "").strip()
        if not principal_id:
            principal_id = str(CONTAINER.settings.auth.default_principal_id or "").strip() or "local-user"
        return RequestContext(
            principal_id=principal_id,
            authenticated=bool(AUTH_TOKEN),
            auth_source="api_token" if AUTH_TOKEN else "anonymous",
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
            self._send_json(200, {"object": "list", "data": list_response_models()})
            return
        self._send_json(404, {"error": {"code": "not_found", "message": "not_found"}})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/v1/responses":
            self._send_json(404, {"error": {"code": "not_found", "message": "not_found"}})
            return
        context = self._auth_context()
        if context is None:
            return
        payload = self._read_payload()
        if payload is None:
            return
        profile = _normalize_profile(
            str(self.headers.get("X-EA-Codex-Profile") or self.headers.get("X-CodexEA-Profile") or "")
        )
        try:
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
    host = str(os.environ.get("EA_RESPONSES_PROXY_HOST") or "0.0.0.0").strip() or "0.0.0.0"
    port = int(str(os.environ.get("EA_RESPONSES_PROXY_PORT") or "8091").strip() or "8091")
    server = ThreadingHTTPServer((host, port), ResponsesProxyHandler)
    server.daemon_threads = True
    LOG.info("responses proxy listening host=%s port=%s", host, port)
    server.serve_forever()


if __name__ == "__main__":
    main()
