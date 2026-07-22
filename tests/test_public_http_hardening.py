from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

from app.api.public_http import api_docs_enabled, install_public_http_hardening


def _policy_app(*, runtime_mode: str = "prod") -> FastAPI:
    app = FastAPI()

    @app.get("/privacy")
    def privacy(request: Request):  # type: ignore[no-untyped-def]
        return {
            "host": str(request.url.hostname or ""),
            "scheme": str(request.url.scheme or ""),
            "forwarded_host": str(request.headers.get("x-forwarded-host") or ""),
            "forwarded_for": str(request.headers.get("x-forwarded-for") or ""),
        }

    @app.get("/headers")
    def headers() -> HTMLResponse:
        return HTMLResponse("<h1>Safe</h1>")

    @app.get("/memorial")
    def memorial() -> HTMLResponse:
        response = HTMLResponse("<h1>Memorial</h1>")
        response.headers["Content-Security-Policy"] = "frame-ancestors 'none'; default-src 'self'"
        response.headers["Permissions-Policy"] = "microphone=(self), camera=()"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    install_public_http_hardening(
        app,
        settings=SimpleNamespace(runtime_mode=runtime_mode),
    )
    return app


@pytest.fixture
def public_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://myexternalbrain.com")
    monkeypatch.setenv("EA_ALLOWED_PUBLIC_HOSTS", "myexternalbrain.com")
    monkeypatch.setenv("EA_TRUST_PROXY_HEADERS", "1")
    monkeypatch.setenv("EA_TRUSTED_PROXY_CIDRS", "127.0.0.1/32")


def test_trusted_proxy_slash_redirect_is_relative_and_https_safe(public_proxy_env: None) -> None:
    client = TestClient(
        _policy_app(),
        base_url="http://origin.myexternalbrain.com",
        client=("127.0.0.1", 50000),
    )

    response = client.get(
        "/privacy/",
        headers={
            "x-forwarded-host": "myexternalbrain.com",
            "x-forwarded-proto": "https",
        },
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"] == "/privacy"
    assert response.headers["strict-transport-security"] == "max-age=31536000"
    assert "origin.myexternalbrain.com" not in response.headers["location"]


def test_trusted_proxy_can_canonicalize_opaque_origin_without_forwarded_host(public_proxy_env: None) -> None:
    client = TestClient(
        _policy_app(),
        base_url="http://origin.myexternalbrain.com",
        client=("127.0.0.1", 50000),
    )

    response = client.get("/privacy", headers={"x-forwarded-proto": "https"})

    assert response.status_code == 200
    assert response.json()["host"] == "myexternalbrain.com"
    assert response.json()["scheme"] == "https"


def test_trusted_proxy_canonicalizes_exact_configured_forwarded_origin_alias(
    public_proxy_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "EA_TRUSTED_PUBLIC_ORIGIN_ALIASES",
        "origin.myexternalbrain.com",
    )
    client = TestClient(
        _policy_app(),
        base_url="http://origin.myexternalbrain.com",
        client=("127.0.0.1", 50000),
    )

    response = client.get(
        "/privacy",
        headers={
            "x-forwarded-host": "origin.myexternalbrain.com",
            "x-forwarded-proto": "https",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "host": "myexternalbrain.com",
        "scheme": "https",
        "forwarded_host": "myexternalbrain.com",
        "forwarded_for": "",
    }


def test_untrusted_raw_origin_alias_remains_rejected(
    public_proxy_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "EA_TRUSTED_PUBLIC_ORIGIN_ALIASES",
        "origin.myexternalbrain.com",
    )
    client = TestClient(
        _policy_app(),
        base_url="https://origin.myexternalbrain.com",
        client=("203.0.113.10", 50000),
    )

    response = client.get("/privacy")

    assert response.status_code == 421
    assert response.json()["error"]["code"] == "host_not_allowed"


@pytest.mark.parametrize("port", (0, 8443))
def test_trusted_origin_alias_rejects_noncanonical_port(
    public_proxy_env: None,
    monkeypatch: pytest.MonkeyPatch,
    port: int,
) -> None:
    monkeypatch.setenv(
        "EA_TRUSTED_PUBLIC_ORIGIN_ALIASES",
        "origin.myexternalbrain.com",
    )
    client = TestClient(
        _policy_app(),
        base_url="http://origin.myexternalbrain.com",
        client=("127.0.0.1", 50000),
    )

    response = client.get(
        "/privacy",
        headers={
            "x-forwarded-host": f"origin.myexternalbrain.com:{port}",
            "x-forwarded-proto": "https",
        },
    )

    assert response.status_code == 421
    assert response.json()["error"]["code"] == "forwarded_host_not_allowed"


def test_trusted_origin_alias_rejects_raw_and_forwarded_host_mismatch(
    public_proxy_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "EA_TRUSTED_PUBLIC_ORIGIN_ALIASES",
        "origin.myexternalbrain.com",
    )
    client = TestClient(
        _policy_app(),
        base_url="http://attacker.invalid",
        client=("127.0.0.1", 50000),
    )

    response = client.get(
        "/privacy",
        headers={
            "x-forwarded-host": "origin.myexternalbrain.com",
            "x-forwarded-proto": "https",
        },
    )

    assert response.status_code == 421
    assert response.json()["error"]["code"] == "forwarded_host_not_allowed"


def test_trusted_property_host_is_not_rewritten_as_ea_origin_alias(
    public_proxy_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "EA_TRUSTED_PUBLIC_ORIGIN_ALIASES",
        "origin.myexternalbrain.com",
    )
    monkeypatch.setenv("PROPERTYQUARRY_PUBLIC_BASE_URL", "https://propertyquarry.com")
    monkeypatch.setenv("PROPERTYQUARRY_PUBLIC_HOSTS", "propertyquarry.com")
    client = TestClient(
        _policy_app(),
        base_url="http://propertyquarry.com",
        client=("127.0.0.1", 50000),
    )

    response = client.get(
        "/privacy",
        headers={
            "x-forwarded-host": "propertyquarry.com",
            "x-forwarded-proto": "https",
        },
    )

    assert response.status_code == 200
    assert response.json()["host"] == "propertyquarry.com"
    assert response.json()["forwarded_host"] == "propertyquarry.com"


def test_untrusted_proxy_metadata_is_removed_before_routing(public_proxy_env: None) -> None:
    client = TestClient(
        _policy_app(),
        base_url="https://myexternalbrain.com",
        client=("203.0.113.10", 50000),
    )

    response = client.get(
        "/privacy",
        headers={
            "x-forwarded-for": "127.0.0.1",
            "x-forwarded-host": "attacker.invalid",
            "x-forwarded-proto": "http",
            "forwarded": "host=attacker.invalid;proto=http",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "host": "myexternalbrain.com",
        "scheme": "https",
        "forwarded_host": "",
        "forwarded_for": "",
    }


@pytest.mark.parametrize(
    "headers",
    (
        {"x-forwarded-host": "myexternalbrain.com,attacker.invalid", "x-forwarded-proto": "https"},
        {"x-forwarded-host": "myexternalbrain.com", "x-forwarded-proto": "https,http"},
        {"forwarded": "host=myexternalbrain.com;proto=https,host=attacker.invalid;proto=http"},
        {
            "forwarded": "host=myexternalbrain.com;proto=https",
            "x-forwarded-host": "attacker.invalid",
            "x-forwarded-proto": "https",
        },
    ),
)
def test_trusted_proxy_rejects_ambiguous_or_conflicting_metadata(
    public_proxy_env: None,
    headers: dict[str, str],
) -> None:
    client = TestClient(
        _policy_app(),
        base_url="http://origin.myexternalbrain.com",
        client=("127.0.0.1", 50000),
    )

    response = client.get("/privacy", headers=headers)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "proxy_header_invalid"
    assert "attacker.invalid" not in response.text


def test_trusted_proxy_rejects_unapproved_forwarded_host(public_proxy_env: None) -> None:
    client = TestClient(
        _policy_app(),
        base_url="http://origin.myexternalbrain.com",
        client=("127.0.0.1", 50000),
    )

    response = client.get(
        "/privacy",
        headers={"x-forwarded-host": "attacker.invalid", "x-forwarded-proto": "https"},
    )

    assert response.status_code == 421
    assert response.json()["error"]["code"] == "forwarded_host_not_allowed"
    assert "attacker.invalid" not in response.text


def test_trusted_forwarded_origin_alias_requires_explicit_configuration(
    public_proxy_env: None,
) -> None:
    client = TestClient(
        _policy_app(),
        base_url="http://origin.myexternalbrain.com",
        client=("127.0.0.1", 50000),
    )

    response = client.get(
        "/privacy",
        headers={
            "x-forwarded-host": "origin.myexternalbrain.com",
            "x-forwarded-proto": "https",
        },
    )

    assert response.status_code == 421
    assert response.json()["error"]["code"] == "forwarded_host_not_allowed"


def test_production_rejects_unapproved_raw_host(public_proxy_env: None) -> None:
    client = TestClient(
        _policy_app(),
        base_url="https://attacker.invalid",
        client=("203.0.113.10", 50000),
    )

    response = client.get("/privacy")

    assert response.status_code == 421
    assert response.json()["error"]["code"] == "host_not_allowed"
    assert "attacker.invalid" not in response.text


def test_untrusted_forwarded_host_cannot_bypass_raw_host_policy(public_proxy_env: None) -> None:
    client = TestClient(
        _policy_app(),
        base_url="https://attacker.invalid",
        client=("203.0.113.10", 50000),
    )

    response = client.get(
        "/privacy",
        headers={
            "x-forwarded-for": "127.0.0.1",
            "x-forwarded-host": "myexternalbrain.com",
            "x-forwarded-proto": "https",
        },
    )

    assert response.status_code == 421
    assert response.json()["error"]["code"] == "host_not_allowed"


def test_duplicate_host_headers_are_rejected(public_proxy_env: None) -> None:
    client = TestClient(
        _policy_app(),
        base_url="https://myexternalbrain.com",
        client=("203.0.113.10", 50000),
    )

    response = client.get(
        "/privacy",
        headers=[("host", "myexternalbrain.com"), ("host", "attacker.invalid")],
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "host_header_invalid"


def test_production_redirects_allowed_plain_http_to_configured_https(public_proxy_env: None) -> None:
    client = TestClient(
        _policy_app(),
        base_url="http://myexternalbrain.com",
        client=("203.0.113.10", 50000),
    )

    response = client.get("/privacy?source=audit", follow_redirects=False)

    assert response.status_code == 308
    assert response.headers["location"] == "https://myexternalbrain.com/privacy?source=audit"


def test_public_security_headers_are_present_and_route_specific_headers_win(public_proxy_env: None) -> None:
    client = TestClient(
        _policy_app(),
        base_url="https://myexternalbrain.com",
        client=("203.0.113.10", 50000),
    )

    generic = client.get("/headers")
    memorial = client.get("/memorial")

    assert generic.status_code == 200
    assert generic.headers["content-security-policy"] == "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    assert generic.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=(), interest-cohort=()"
    assert generic.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert generic.headers["x-content-type-options"] == "nosniff"
    assert generic.headers["x-frame-options"] == "DENY"
    assert generic.headers["strict-transport-security"] == "max-age=31536000"
    assert memorial.headers["content-security-policy"] == "frame-ancestors 'none'; default-src 'self'"
    assert memorial.headers["permissions-policy"] == "microphone=(self), camera=()"
    assert memorial.headers["referrer-policy"] == "no-referrer"


def test_api_docs_default_off_in_production_and_explicitly_configurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EA_ENABLE_API_DOCS", raising=False)
    assert api_docs_enabled(runtime_mode="prod") is False
    assert api_docs_enabled(runtime_mode="dev") is True

    monkeypatch.setenv("EA_ENABLE_API_DOCS", "1")
    assert api_docs_enabled(runtime_mode="prod") is True

    monkeypatch.setenv("EA_ENABLE_API_DOCS", "0")
    assert api_docs_enabled(runtime_mode="dev") is False


def test_explicit_docs_disable_removes_openapi_and_interactive_docs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EA_STORAGE_BACKEND", "memory")
    monkeypatch.setenv("EA_API_TOKEN", "")
    monkeypatch.setenv("EA_ENABLE_API_DOCS", "0")
    monkeypatch.setenv("EA_RUNTIME_MODE", "dev")
    from app.api.app import create_app

    client = TestClient(create_app(), base_url="https://testserver")

    assert client.get("/openapi.json").status_code == 404
    assert client.get("/api/docs").status_code == 404
    assert client.get("/api/redoc").status_code == 404
    assert client.get("/docs/oauth2-redirect").status_code == 404

    public_docs = client.get("/docs")
    assert public_docs.status_code == 200
    assert public_docs.headers["strict-transport-security"] == "max-age=31536000"
    slash_redirect = client.get("/docs/", follow_redirects=False)
    assert slash_redirect.status_code == 307
    assert slash_redirect.headers["location"] == "/docs"
