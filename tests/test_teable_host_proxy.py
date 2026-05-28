from __future__ import annotations

import http.client
import importlib.util
import io
import json
import socket
import threading
import types
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
_MODULE_PATH = ROOT / "scripts" / "teable_host_proxy.py"
_SPEC = importlib.util.spec_from_file_location("teable_host_proxy", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
teable_host_proxy = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(teable_host_proxy)


def _run_server(server) -> threading.Thread:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_teable_host_proxy_healthz_returns_ok() -> None:
    port = _free_port()
    with teable_host_proxy._ThreadingServer(("127.0.0.1", port), teable_host_proxy._ProxyHandler) as server:
        server.target_base = "https://app.teable.ai"
        thread = _run_server(server)
        try:
            response = urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=10)
            payload = json.loads(response.read().decode("utf-8"))
            assert response.status == 200
            assert payload["status"] == "ok"
            assert payload["target_base"] == "https://app.teable.ai"
        finally:
            server.shutdown()
            thread.join(timeout=5)


def test_teable_host_proxy_rejects_non_api_paths() -> None:
    port = _free_port()
    with teable_host_proxy._ThreadingServer(("127.0.0.1", port), teable_host_proxy._ProxyHandler) as server:
        server.target_base = "https://app.teable.ai"
        thread = _run_server(server)
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/forbidden", timeout=10) as _:
                raise AssertionError("expected 404")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
            assert json.loads(exc.read().decode("utf-8"))["error"] == "path_not_allowed"
        finally:
            server.shutdown()
            thread.join(timeout=5)


def test_teable_host_proxy_forwards_api_requests_with_browser_headers(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _FakeResponse:
        status = 200
        headers = {"Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return b'{"ok":true}'

    def _fake_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    request = types.SimpleNamespace(
        path="/api/auth/user",
        headers=http.client.HTTPMessage(),
        rfile=io.BytesIO(b""),
        wfile=io.BytesIO(),
        command="GET",
        server=types.SimpleNamespace(target_base="https://app.teable.ai"),
    )
    request.headers.add_header("Authorization", "Bearer teable-token")

    responses: list[int] = []
    sent_headers: list[tuple[str, str]] = []

    request.send_response = responses.append
    request.send_header = lambda name, value: sent_headers.append((name, value))
    request.end_headers = lambda: None

    teable_host_proxy._ProxyHandler._forward(request)  # type: ignore[arg-type]

    assert responses == [200]
    assert captured["url"] == "https://app.teable.ai/api/auth/user"
    headers = {str(key).lower(): value for key, value in dict(captured["headers"]).items()}
    assert headers["authorization"] == "Bearer teable-token"
    assert headers["origin"] == "https://app.teable.ai"
    assert headers["referer"] == "https://app.teable.ai/"
    assert "mozilla/5.0" in str(headers["user-agent"]).lower()
    assert ("Content-Type", "application/json") in sent_headers
    assert request.wfile.getvalue() == b'{"ok":true}'
