from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import urllib.parse

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
import pytest
from starlette.requests import Request
from starlette.websockets import WebSocket

from app.api.routes import (
    public_memorial_runtime,
    public_memorial_surface,
    public_memorial_turn_support,
    public_memorials,
)
from scripts import issue_manfred_voice_review_link


_ORIGIN = "https://memorial.example"
_REVISION = "a" * 40
_IMAGE_ID = f"sha256:{'b' * 64}"
_VOICE_IDENTITY_SHA256 = "c" * 64
_SIGNING_SECRET = "voice-review-test-secret"


@pytest.fixture(autouse=True)
def _configured_voice_review(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", _ORIGIN)
    monkeypatch.setenv("EA_SOURCE_REVISION", _REVISION)
    monkeypatch.setenv("EA_DEPLOY_IMAGE_ID", _IMAGE_ID)
    monkeypatch.setenv(
        "EA_MEMORIAL_VOICE_IDENTITY_SHA256",
        _VOICE_IDENTITY_SHA256,
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_RATE_BACKEND", "memory")
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_review_signing_secret",
        lambda: _SIGNING_SECRET,
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_runtime_bindings",
        lambda: (
            {
                "expected_image_id": str(
                    public_memorials.os.getenv("EA_DEPLOY_IMAGE_ID") or ""
                ).strip(),
            },
            "",
        ),
    )
    state_dir = tmp_path / "state"
    state_dir.mkdir(mode=0o700)
    monkeypatch.setattr(
        public_memorials,
        "_memorial_state_dir",
        lambda: state_dir,
    )
    public_memorials._MEMORIAL_RUNTIME_READINESS_CACHE_STATE.clear()
    public_memorials._PUBLIC_MEMORIAL_RATE_MEMORY_EVENTS.clear()
    public_memorials._PUBLIC_MEMORIAL_RATE_BACKEND_CACHE = "memory"


def _request(
    path: str,
    *,
    cookie: str = "",
    method: str = "GET",
    query: bytes = b"",
    origin: str | None = None,
    extra_headers: list[tuple[bytes, bytes]] | None = None,
) -> Request:
    headers = [(b"host", b"memorial.example")]
    if origin is not None:
        headers.append((b"origin", origin.encode("ascii")))
    if cookie:
        headers.append((b"cookie", cookie.encode("ascii")))
    headers.extend(extra_headers or [])
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "https",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": query,
            "headers": headers,
            "client": ("127.0.0.1", 42100),
            "server": ("memorial.example", 443),
        }
    )


def _exchange_request(receive) -> Request:
    path = "/admin/memorials/manfred/voice-review"
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "headers": [
                (b"host", b"memorial.example"),
                (b"origin", _ORIGIN.encode("ascii")),
                (b"content-type", b"application/json"),
            ],
            "client": ("127.0.0.1", 42102),
            "server": ("memorial.example", 443),
        },
        receive,
    )


def _websocket(
    *,
    token: str = "",
    origin: str | None = _ORIGIN,
    host: str = "memorial.example",
    scheme: str = "wss",
    extra_headers: list[tuple[bytes, bytes]] | None = None,
    sent_messages: list[dict[str, object]] | None = None,
) -> WebSocket:
    async def _receive() -> dict[str, object]:
        return {"type": "websocket.disconnect"}

    async def _send(message: dict[str, object]) -> None:
        if sent_messages is not None:
            sent_messages.append(dict(message))

    headers = [(b"host", host.encode("ascii"))]
    if origin is not None:
        headers.append((b"origin", origin.encode("ascii")))
    if token:
        headers.append(
            (
                b"cookie",
                (
                    f"{public_memorials._MEMORIAL_VOICE_REVIEW_COOKIE}={token}"
                ).encode("ascii"),
            )
        )
    headers.extend(extra_headers or [])
    return WebSocket(
        {
            "type": "websocket",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "scheme": scheme,
            "path": "/memorials/manfred/realtime",
            "raw_path": b"/memorials/manfred/realtime",
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 42101),
            "server": ("memorial.example", 443),
            "subprotocols": [],
        },
        _receive,
        _send,
    )


def _session_token(*, now: int | None = None) -> str:
    bootstrap = public_memorials._issue_memorial_voice_review_bootstrap_token(
        now=now,
    )
    exchanged = public_memorials._exchange_memorial_voice_review_bootstrap_token(
        bootstrap,
        now=now,
    )
    assert exchanged is not None
    return exchanged[0]


def test_voice_review_tokens_fail_closed_for_forgery_expiry_and_pre_accept() -> None:
    issued_at = 1_800_000_000
    bootstrap = public_memorials._issue_memorial_voice_review_bootstrap_token(
        now=issued_at,
    )
    replacement = "A" if bootstrap[-1] != "A" else "B"
    forged = f"{bootstrap[:-1]}{replacement}"

    assert public_memorials._memorial_voice_review_token_payload(
        forged,
        expected_kind="bootstrap",
        required_scope="page",
        now=issued_at,
    ) is None
    assert public_memorials._memorial_voice_review_token_payload(
        bootstrap,
        expected_kind="bootstrap",
        required_scope="page",
        now=issued_at
        + public_memorials._MEMORIAL_VOICE_REVIEW_BOOTSTRAP_TTL_SECONDS
        + 1,
    ) is None
    assert public_memorials._memorial_voice_review_token_payload(
        bootstrap,
        expected_kind="session",
        required_scope="page",
        now=issued_at,
    ) is None


def test_voice_review_bootstraps_minted_same_second_are_unique() -> None:
    issued_at = 1_800_000_000
    first = public_memorials._issue_memorial_voice_review_bootstrap_token(
        now=issued_at,
    )
    second = public_memorials._issue_memorial_voice_review_bootstrap_token(
        now=issued_at,
    )

    assert first != second
    first_payload = public_memorials._memorial_voice_review_token_payload(
        first,
        expected_kind="bootstrap",
        required_scope="page",
        now=issued_at,
    )
    second_payload = public_memorials._memorial_voice_review_token_payload(
        second,
        expected_kind="bootstrap",
        required_scope="page",
        now=issued_at,
    )
    assert first_payload is not None
    assert second_payload is not None
    assert first_payload["jti"] != second_payload["jti"]


def test_voice_review_bootstrap_can_only_be_redeemed_once() -> None:
    issued_at = 1_800_000_000
    bootstrap = public_memorials._issue_memorial_voice_review_bootstrap_token(
        now=issued_at,
    )
    bootstrap_payload = (
        public_memorials._memorial_voice_review_token_payload(
            bootstrap,
            expected_kind="bootstrap",
            required_scope="page",
            now=issued_at,
        )
    )
    assert bootstrap_payload is not None

    assert (
        public_memorials._exchange_memorial_voice_review_bootstrap_token(
            bootstrap,
            now=issued_at,
        )
        is not None
    )
    assert (
        public_memorials._exchange_memorial_voice_review_bootstrap_token(
            bootstrap,
            now=issued_at,
        )
        is None
    )
    redemption_root = (
        public_memorials._memorial_state_dir()
        / "voice-review-redemptions"
    )
    markers = list(redemption_root.iterdir())
    assert stat.S_IMODE(redemption_root.stat().st_mode) == 0o700
    assert len(markers) == 1
    jti = str(bootstrap_payload["jti"])
    assert markers[0].name == (
        f"{hashlib.sha256(jti.encode('ascii')).hexdigest()}.redeemed"
    )
    assert stat.S_IMODE(markers[0].stat().st_mode) == 0o600
    assert markers[0].read_text(encoding="ascii") == (
        f"{bootstrap_payload['expires_at']}\n"
    )
    assert jti not in markers[0].name
    assert jti not in markers[0].read_text(encoding="ascii")
    assert bootstrap not in markers[0].read_text(encoding="ascii")


def test_voice_review_tokens_bind_runtime_image_and_voice_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issued_at = 1_800_000_000
    bootstrap = public_memorials._issue_memorial_voice_review_bootstrap_token(
        now=issued_at,
    )
    exchanged = (
        public_memorials._exchange_memorial_voice_review_bootstrap_token(
            bootstrap,
            now=issued_at,
        )
    )
    assert exchanged is not None
    session = exchanged[0]

    monkeypatch.setenv("EA_DEPLOY_IMAGE_ID", f"sha256:{'e' * 64}")
    assert public_memorials._memorial_voice_review_token_payload(
        bootstrap,
        expected_kind="bootstrap",
        required_scope="page",
        now=issued_at,
    ) is None
    assert public_memorials._memorial_voice_review_token_payload(
        session,
        expected_kind="session",
        required_scope="realtime",
        now=issued_at,
    ) is None

    monkeypatch.setenv("EA_DEPLOY_IMAGE_ID", _IMAGE_ID)
    monkeypatch.setenv("EA_MEMORIAL_VOICE_IDENTITY_SHA256", "f" * 64)
    assert public_memorials._memorial_voice_review_token_payload(
        bootstrap,
        expected_kind="bootstrap",
        required_scope="page",
        now=issued_at,
    ) is None
    assert public_memorials._memorial_voice_review_token_payload(
        session,
        expected_kind="session",
        required_scope="realtime",
        now=issued_at,
    ) is None


def test_voice_review_tokens_bind_revision_origin_and_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issued_at = 1_800_000_000
    bootstrap = public_memorials._issue_memorial_voice_review_bootstrap_token(
        now=issued_at,
    )

    monkeypatch.setenv("EA_SOURCE_REVISION", "b" * 40)
    assert public_memorials._memorial_voice_review_token_payload(
        bootstrap,
        expected_kind="bootstrap",
        required_scope="page",
        now=issued_at,
    ) is None
    monkeypatch.setenv("EA_SOURCE_REVISION", _REVISION)
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://other.example")
    assert public_memorials._memorial_voice_review_token_payload(
        bootstrap,
        expected_kind="bootstrap",
        required_scope="page",
        now=issued_at,
    ) is None

    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", _ORIGIN)
    page_only = public_memorials._sign_memorial_voice_review_claims(
        {
            "contract_name": public_memorials._MEMORIAL_VOICE_REVIEW_CONTRACT,
            "purpose": public_memorials._MEMORIAL_VOICE_REVIEW_PURPOSE,
            "kind": "session",
            "slug": "manfred",
            "jti": "d" * (
                public_memorials._MEMORIAL_VOICE_REVIEW_JTI_BYTES * 2
            ),
            "source_revision": _REVISION,
            "public_origin": _ORIGIN,
            "image_id": _IMAGE_ID,
            "voice_identity_sha256": _VOICE_IDENTITY_SHA256,
            "issued_at": issued_at,
            "accepted_at": issued_at,
            "expires_at": issued_at + 600,
            "scopes": ["page"],
        }
    )
    assert public_memorials._memorial_voice_review_token_payload(
        page_only,
        expected_kind="session",
        required_scope="page",
        now=issued_at,
    ) is not None
    assert public_memorials._memorial_voice_review_token_payload(
        page_only,
        expected_kind="session",
        required_scope="readiness",
        now=issued_at,
    ) is None


def test_fragment_exchange_sets_only_short_lived_strict_http_only_cookie() -> None:
    app = FastAPI()
    app.include_router(public_memorial_surface.router)
    client = TestClient(app, base_url=_ORIGIN)
    bootstrap = public_memorials._issue_memorial_voice_review_bootstrap_token()

    page = client.get("/admin/memorials/manfred/voice-review")
    assert page.status_code == 200
    assert "#token=" not in page.text
    assert "window.location.hash" in page.text
    assert client.get(
        f"/admin/memorials/manfred/voice-review?token={bootstrap}"
    ).status_code == 400

    response = client.post(
        "/admin/memorials/manfred/voice-review",
        headers={"Origin": _ORIGIN},
        json={"token": bootstrap},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "accepted",
        "redirect": "/memorials/manfred",
    }
    set_cookie = response.headers["set-cookie"]
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "SameSite=strict" in set_cookie
    assert "Path=/memorials/manfred" in set_cookie
    assert public_memorials._MEMORIAL_VOICE_REVIEW_COOKIE in set_cookie
    assert bootstrap not in set_cookie
    session = response.cookies.get(public_memorials._MEMORIAL_VOICE_REVIEW_COOKIE)
    assert session
    assert public_memorials._memorial_voice_review_token_payload(
        session,
        expected_kind="session",
        required_scope="realtime",
    ) is not None


def test_exchange_rejects_cross_origin_and_invalid_bootstrap() -> None:
    app = FastAPI()
    app.include_router(public_memorial_surface.router)
    client = TestClient(app, base_url=_ORIGIN)
    bootstrap = public_memorials._issue_memorial_voice_review_bootstrap_token()

    assert client.post(
        "/admin/memorials/manfred/voice-review",
        headers={"Origin": "https://other.example"},
        json={"token": bootstrap},
    ).status_code == 403
    assert client.post(
        "/admin/memorials/manfred/voice-review",
        headers={"Origin": _ORIGIN},
        json={"token": f"{bootstrap}x"},
    ).status_code == 403


def test_voice_review_routes_are_registered_on_split_public_surface() -> None:
    methods = {
        method
        for route in public_memorial_surface.router.routes
        if getattr(route, "path", "")
        == "/admin/memorials/manfred/voice-review"
        for method in (getattr(route, "methods", set()) or set())
    }

    assert methods == {"GET", "POST"}


def test_voice_review_issuer_resolves_source_and_flattened_image_layouts(
    tmp_path: Path,
) -> None:
    source_layout = tmp_path / "source"
    (source_layout / "ea" / "app").mkdir(parents=True)
    flattened_layout = tmp_path / "image"
    (flattened_layout / "app").mkdir(parents=True)

    assert issue_manfred_voice_review_link._app_import_root(source_layout) == (
        source_layout / "ea"
    )
    assert issue_manfred_voice_review_link._app_import_root(
        flattened_layout
    ) == flattened_layout

    script_path = (
        flattened_layout
        / "scripts"
        / Path(issue_manfred_voice_review_link.__file__).name
    )
    script_path.parent.mkdir(parents=True)
    shutil.copy2(issue_manfred_voice_review_link.__file__, script_path)
    for package_dir in (
        flattened_layout / "app",
        flattened_layout / "app" / "api",
        flattened_layout / "app" / "api" / "routes",
    ):
        package_dir.mkdir(parents=True, exist_ok=True)
        (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (
        flattened_layout
        / "app"
        / "api"
        / "routes"
        / "public_memorials.py"
    ).write_text(
        "_MEMORIAL_VOICE_REVIEW_BOOTSTRAP_TTL_SECONDS = 1800\n",
        encoding="utf-8",
    )
    unrelated_cwd = tmp_path / "elsewhere"
    unrelated_cwd.mkdir()
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)

    result = subprocess.run(
        [sys.executable, str(script_path), "--help"],
        cwd=unrelated_cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "ModuleNotFoundError" not in result.stderr


@pytest.mark.parametrize(
    ("path", "method", "shared_name"),
    [
        (
            "/memorials/manfred/warmup-status",
            "POST",
            "public_memorial_warmup_status",
        ),
        (
            "/memorials/manfred/readiness",
            "GET",
            "public_memorial_readiness",
        ),
    ],
)
def test_split_runtime_forwards_review_request_context(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    method: str,
    shared_name: str,
) -> None:
    captured: dict[str, object] = {}

    def _shared_handler(*, slug: str, request: Request) -> JSONResponse:
        captured.update(
            {
                "slug": slug,
                "method": request.method,
                "origin": request.headers.get("origin"),
                "cookie": request.headers.get("cookie"),
            }
        )
        return JSONResponse({"status": "pass"})

    monkeypatch.setattr(public_memorials, shared_name, _shared_handler)
    app = FastAPI()
    app.include_router(public_memorial_runtime.router)
    client = TestClient(app, base_url=_ORIGIN)
    response = client.request(
        method,
        path,
        headers={
            "Origin": _ORIGIN,
            "Cookie": "ea_manfred_voice_review=test-session",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "pass"}
    assert captured == {
        "slug": "manfred",
        "method": method,
        "origin": _ORIGIN,
        "cookie": "ea_manfred_voice_review=test-session",
    }


def test_exchange_rejects_oversized_stream_before_token_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunks = [
        {
            "type": "http.request",
            "body": b"x" * 2048,
            "more_body": True,
        },
        {
            "type": "http.request",
            "body": b"x" * 2048,
            "more_body": False,
        },
    ]
    received = 0

    async def _receive() -> dict[str, object]:
        nonlocal received
        received += 1
        return chunks.pop(0)

    monkeypatch.setattr(
        public_memorials,
        "_enforce_public_memorial_rate_limit",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        public_memorials,
        "_exchange_memorial_voice_review_bootstrap_token",
        lambda *_args, **_kwargs: pytest.fail(
            "oversized body reached token verification"
        ),
    )

    response = asyncio.run(
        public_memorials.manfred_memorial_voice_review_exchange(
            _exchange_request(_receive)
        )
    )

    assert response.status_code == 413
    assert json.loads(response.body) == {
        "detail": "memorial_voice_review_exchange_too_large"
    }
    assert received == 2


def test_exchange_rate_limit_runs_before_body_or_token_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _receive() -> dict[str, object]:
        pytest.fail("rate-limited exchange read the request body")

    def _rate_limit(bucket: str, **_kwargs: object) -> None:
        assert bucket == "voice_review_exchange"
        raise HTTPException(status_code=429, detail="memorial_rate_limited")

    monkeypatch.setattr(
        public_memorials,
        "_enforce_public_memorial_rate_limit",
        _rate_limit,
    )
    monkeypatch.setattr(
        public_memorials,
        "_exchange_memorial_voice_review_bootstrap_token",
        lambda *_args, **_kwargs: pytest.fail(
            "rate-limited exchange reached token verification"
        ),
    )

    response = asyncio.run(
        public_memorials.manfred_memorial_voice_review_exchange(
            _exchange_request(_receive)
        )
    )

    assert response.status_code == 429
    payload = json.loads(response.body)
    assert payload["detail"] == "memorial_rate_limited"
    assert payload["error"]["code"] == "memorial_rate_limited"


def test_cookie_authenticated_page_is_preview_but_anonymous_page_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "slug": "manfred",
        "person_name": "Manfred",
        "title": "Erinnerungen an Manfred",
    }
    consent_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        public_memorial_surface,
        "_load_public_surface_memorial",
        lambda _slug: dict(payload),
    )
    monkeypatch.setattr(
        public_memorial_surface,
        "_load_private_profile",
        lambda _slug: {},
    )
    monkeypatch.setattr(
        public_memorial_surface,
        "_ensure_memorial_guest_cookie",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        public_memorial_surface,
        "_require_voice_consent",
        lambda _payload, _action, **kwargs: consent_calls.append(dict(kwargs)),
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_release_enforced",
        lambda: True,
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_release_decision",
        lambda _slug: {"allowed": False},
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_pwa_icon_url",
        lambda *_args: "/memorials/manfred/icon-180.png",
    )

    anonymous = public_memorial_surface.public_memorial_page(
        "manfred",
        _request("/memorials/manfred"),
    )
    anonymous_html = anonymous.body.decode("utf-8")
    assert anonymous.status_code == 200
    assert 'data-operator-voice-preview="allowed"' not in anonymous_html
    assert "Frage schreiben" in anonymous_html
    assert consent_calls == []

    session = _session_token()
    preview = public_memorial_surface.public_memorial_page(
        "manfred",
        _request(
            "/memorials/manfred",
            cookie=(
                f"{public_memorials._MEMORIAL_VOICE_REVIEW_COOKIE}={session}"
            ),
        ),
    )
    preview_html = preview.body.decode("utf-8")
    assert preview.status_code == 200
    assert 'data-operator-voice-preview="allowed"' in preview_html
    assert "Gespräch beginnen" in preview_html
    assert "Gemini Live verbunden" not in preview_html
    assert "Gemini Live Audio" not in preview_html
    assert "function applyRealtimeReadyMode(payload)" in preview_html
    assert "Sprachdialog verbunden" in preview_html
    assert "Live-Audio verbunden" in preview_html
    assert consent_calls == [{"operator_preview_allowed": True}]


def test_preview_readiness_bypasses_and_does_not_replace_public_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        public_memorials,
        "_public_memorial_surface_probe",
        lambda _slug: {"slug": "manfred", "person_name": "Manfred"},
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_release_enforced",
        lambda: True,
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_release_decision",
        lambda _slug: {
            "allowed": False,
            "status": "blocked",
            "reason": "operator_acceptance_pending",
            "receipt_status": "pending",
        },
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_live_warmup_snapshot",
        lambda _slug: {
            "warm": True,
            "errors": [],
            "voice_required": False,
            "voice_prewarm_stale": False,
            "voice_inflight": False,
            "voice_ready": True,
            "voice_errors": [],
            "ttl_remaining_seconds": 300.0,
            "voice_ttl_remaining_seconds": 0.0,
        },
    )
    monkeypatch.setattr(
        public_memorials,
        "_load_memorial",
        lambda _slug: {"slug": "manfred"},
    )
    monkeypatch.setattr(
        public_memorials,
        "_load_voice_config",
        lambda _slug: {"voice_profile_ready": True},
    )
    monkeypatch.setattr(
        public_memorials,
        "_public_voice_profile_summary",
        lambda _slug: {"voice_profile_ready": True},
    )
    monkeypatch.setattr(
        public_memorials,
        "_tts_plugin_options",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        public_memorials,
        "_resolve_server_tts_plugin",
        lambda **_kwargs: ("unmixr_clone", {"tts_plugin_enabled": True}),
    )
    monkeypatch.setattr(
        public_memorials,
        "_resolve_memorial_voice_chat_model",
        lambda *_args, **_kwargs: "grounded-model",
    )
    monkeypatch.setattr(
        public_memorials,
        "_load_public_memorial_profile",
        lambda _slug: {},
    )
    monkeypatch.setattr(
        public_memorials,
        "_gemini_live_available",
        lambda: False,
    )
    monkeypatch.setattr(
        public_memorials,
        "_collect_memorial_write_tokens",
        lambda _payload: [],
    )

    anonymous = public_memorials._memorial_runtime_readiness("manfred")
    assert anonymous["status"] == "blocked_release"
    assert anonymous["ready"] is False
    cached_before = copy.deepcopy(
        public_memorials._MEMORIAL_RUNTIME_READINESS_CACHE_STATE
    )

    preview = public_memorials._memorial_runtime_readiness(
        "manfred",
        operator_preview_allowed=True,
    )

    assert preview["status"] == "degraded_realtime"
    assert preview["ready"] is True
    assert preview["release"]["allowed"] is False
    assert preview["release"]["operator_preview"] is True
    assert (
        public_memorials._MEMORIAL_RUNTIME_READINESS_CACHE_STATE
        == cached_before
    )
    assert public_memorials._memorial_runtime_readiness("manfred") == anonymous


def test_preview_still_enforces_approved_non_revoked_voice_consent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _revoked(*_args: object, **_kwargs: object) -> None:
        raise HTTPException(status_code=409, detail="voice_consent_revoked")

    monkeypatch.setattr(
        public_memorials,
        "_support_require_voice_consent",
        _revoked,
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_release_enforced",
        lambda: True,
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_release_decision",
        lambda _slug: (_ for _ in ()).throw(
            AssertionError("preview must not consult final release")
        ),
    )

    with pytest.raises(HTTPException, match="voice_consent_revoked"):
        public_memorials._require_voice_consent(
            {"slug": "manfred"},
            "realtime",
            operator_preview_allowed=True,
        )


def test_preview_cookie_allows_http_voice_fallback_with_guards_and_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    voice_id = "manfred-review-voice"
    base_config = {
        "voice_profile_ready": True,
        "tts_plugin": public_memorials.MANFRED_TTS_PROVIDER,
        "tts_mode": public_memorials.MANFRED_TTS_PROVIDER,
        "tts_plugin_voice_id": voice_id,
        "tts_base_voice_variant": public_memorials.MANFRED_TTS_MODEL,
    }
    selected_option = {
        "tts_plugin": public_memorials.MANFRED_TTS_PROVIDER,
        "tts_plugin_enabled": True,
        "tts_plugin_voice_id": voice_id,
    }
    consent_actions: list[str] = []
    rate_buckets: list[str] = []
    guarded_routes: list[str] = []

    monkeypatch.setenv("UNMIXR_VOICE_ID", voice_id)
    monkeypatch.setattr(
        public_memorials,
        "_load_memorial",
        lambda _slug: {"slug": "manfred"},
    )
    monkeypatch.setattr(
        public_memorials,
        "_support_require_voice_consent",
        lambda _payload, action, **_kwargs: consent_actions.append(action),
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_release_enforced",
        lambda: True,
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_release_decision",
        lambda _slug: pytest.fail(
            "valid preview consulted the final release receipt"
        ),
    )
    monkeypatch.setattr(
        public_memorials,
        "_load_voice_config",
        lambda _slug: dict(base_config),
    )
    monkeypatch.setattr(
        public_memorials,
        "_tts_plugin_options",
        lambda **_kwargs: [dict(selected_option)],
    )
    monkeypatch.setattr(
        public_memorials,
        "_resolve_server_tts_plugin",
        lambda **_kwargs: (
            public_memorials.MANFRED_TTS_PROVIDER,
            dict(selected_option),
        ),
    )
    monkeypatch.setattr(
        public_memorials,
        "_enforce_public_memorial_rate_limit",
        lambda bucket, **_kwargs: rate_buckets.append(bucket),
    )
    monkeypatch.setattr(
        public_memorials,
        "_register_memorial_known_audio_transcript",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        public_memorials,
        "_personal_memory_public_status",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(
        public_memorials,
        "_prefer_fast_tts_for_conversation_turn",
        lambda _slug: (False, ""),
    )
    monkeypatch.setattr(
        public_memorial_turn_support,
        "runtime_from_shared",
        lambda _shared: object(),
    )

    def _guarded_render(**kwargs: object) -> tuple[bytes, str]:
        public_memorials._require_manfred_release_tts_lane(
            slug=str(kwargs["slug"]),
            merged_config=dict(kwargs["merged_config"]),
            selected_plugin=str(kwargs["selected_plugin"]),
            selected_option=dict(kwargs["selected_option"]),
            voice_ref=voice_id,
        )
        guarded_routes.append("speech_synthesize")
        return b"RIFF-review-audio", "audio/wav"

    class _Turn:
        def as_public_payload(self) -> dict[str, object]:
            return {
                "answer": "Ich bin da.",
                "audio_base64": "",
                "audio_content_type": "audio/wav",
                "sources": [],
            }

    def _guarded_turn(**_kwargs: object) -> _Turn:
        public_memorials._require_manfred_release_tts_lane(
            slug="manfred",
            merged_config=dict(base_config),
            selected_plugin=public_memorials.MANFRED_TTS_PROVIDER,
            selected_option=dict(selected_option),
            voice_ref=voice_id,
        )
        guarded_routes.append("conversation_turn")
        return _Turn()

    monkeypatch.setattr(
        public_memorials,
        "_render_memorial_tts_audio",
        _guarded_render,
    )
    monkeypatch.setattr(
        public_memorial_turn_support,
        "build_public_memorial_turn",
        _guarded_turn,
    )

    app = FastAPI()
    app.include_router(public_memorials.router)
    client = TestClient(app, base_url=_ORIGIN)
    session = _session_token()
    cookie = (
        f"{public_memorials._MEMORIAL_VOICE_REVIEW_COOKIE}={session}"
    )

    synthesized = client.post(
        "/memorials/manfred/speech-synthesize",
        headers={"Cookie": cookie, "Origin": _ORIGIN},
        json={"text": "Ich bin da."},
    )
    conversation = client.post(
        "/memorials/manfred/conversation-turn",
        headers={
            "Cookie": cookie,
            "Content-Type": "audio/wav",
            "Origin": _ORIGIN,
        },
        content=b"RIFF-review-input",
    )

    assert synthesized.status_code == 200
    assert conversation.status_code == 200
    assert set(consent_actions) == {"synthesize", "conversation_turn"}
    assert rate_buckets == ["speech_synthesize", "conversation_turn"]
    assert guarded_routes == ["speech_synthesize", "conversation_turn"]


@pytest.mark.parametrize(
    "preview_request",
    [
        pytest.param(
            _request("/memorials/manfred/readiness"),
            id="missing-origin",
        ),
        pytest.param(
            _request(
                "/memorials/manfred/readiness",
                origin="https://sibling.memorial.example",
            ),
            id="sibling-origin",
        ),
        pytest.param(
            _request(
                "/memorials/manfred/readiness",
                origin=_ORIGIN,
                extra_headers=[(b"origin", _ORIGIN.encode("ascii"))],
            ),
            id="duplicate-origin",
        ),
    ],
)
def test_preview_cookie_http_authorization_rejects_untrusted_origin_metadata(
    preview_request: Request,
) -> None:
    session = _session_token()
    preview_request.scope["headers"].append(
        (
            b"cookie",
            (
                f"{public_memorials._MEMORIAL_VOICE_REVIEW_COOKIE}={session}"
            ).encode("ascii"),
        )
    )

    with pytest.raises(HTTPException) as exc_info:
        public_memorials._memorial_voice_review_http_session_payload(
            preview_request,
            slug="manfred",
            required_scope="readiness",
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "memorial_voice_review_origin_rejected"


def test_preview_cookie_http_authorization_accepts_only_exact_origin() -> None:
    session = _session_token()
    payload = public_memorials._memorial_voice_review_http_session_payload(
        _request(
            "/memorials/manfred/readiness",
            cookie=(
                f"{public_memorials._MEMORIAL_VOICE_REVIEW_COOKIE}={session}"
            ),
            origin=_ORIGIN,
        ),
        slug="manfred",
        required_scope="readiness",
    )

    assert payload is not None
    assert payload["public_origin"] == _ORIGIN


def test_websocket_review_cookie_requires_wss_exact_host_and_origin() -> None:
    session = _session_token()

    assert public_memorials._memorial_voice_review_websocket_session_payload(
        _websocket(token=session),
        slug="manfred",
        required_scope="realtime",
    ) is not None
    assert public_memorials._memorial_voice_review_websocket_session_payload(
        _websocket(token=session, origin="https://other.example"),
        slug="manfred",
        required_scope="realtime",
    ) is None
    assert public_memorials._memorial_voice_review_websocket_session_payload(
        _websocket(token=session, host="other.example"),
        slug="manfred",
        required_scope="realtime",
    ) is None
    assert public_memorials._memorial_voice_review_websocket_session_payload(
        _websocket(token=session, scheme="ws"),
        slug="manfred",
        required_scope="realtime",
    ) is None


@pytest.mark.parametrize(
    "websocket",
    [
        _websocket(origin=None),
        _websocket(origin="https://hostile.example"),
        _websocket(
            extra_headers=[(b"origin", _ORIGIN.encode("ascii"))],
        ),
        _websocket(
            extra_headers=[(b"host", b"memorial.example")],
        ),
        _websocket(
            extra_headers=[(b"x-forwarded-host", b"hostile.example")],
        ),
        _websocket(
            extra_headers=[(b"x-forwarded-proto", b"http")],
        ),
    ],
)
def test_released_anonymous_websocket_transport_rejects_hostile_metadata(
    websocket: WebSocket,
) -> None:
    assert (
        public_memorials._memorial_realtime_websocket_transport_allowed(
            websocket
        )
        is False
    )


def test_realtime_route_applies_transport_gate_before_release_or_consent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[dict[str, object]] = []
    websocket = _websocket(
        origin=None,
        sent_messages=sent,
    )
    monkeypatch.setattr(
        public_memorials,
        "_load_memorial",
        lambda _slug: pytest.fail(
            "hostile socket reached memorial/release processing"
        ),
    )

    asyncio.run(
        public_memorials.public_memorial_realtime("manfred", websocket)
    )

    assert sent == [
        {
            "type": "websocket.close",
            "code": 1008,
            "reason": "",
        }
    ]


def test_minted_link_keeps_credential_in_fragment_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts import issue_manfred_voice_review_link

    assert issue_manfred_voice_review_link.main(
        ["--ttl-seconds", "60"]
    ) == 0
    output = capsys.readouterr().out.strip()
    assert output.startswith(
        f"{_ORIGIN}/admin/memorials/manfred/voice-review#token="
    )
    assert "?" not in output
    token = urllib.parse.unquote(output.split("#token=", 1)[1])
    payload = public_memorials._memorial_voice_review_token_payload(
        token,
        expected_kind="bootstrap",
        required_scope="page",
    )
    assert payload is not None
    assert int(payload["expires_at"]) - int(payload["issued_at"]) == 60
