from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from app.services.public_clickrank import clickrank_head_snippet, clickrank_site_id_for_hostname, request_hostname


_MYEXTERNALBRAIN_SITE_ID = "33ff8f39-6213-4903-99d7-81048b5b3e1f"


def _client(*, principal_id: str = "exec-clickrank-contract", clickrank_enabled: bool = True) -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ["EA_API_TOKEN"] = ""
    if clickrank_enabled:
        os.environ["EA_ENABLE_CLICKRANK"] = "1"
        os.environ["CLICKRANK_AI_MYEXTERNALBRAIN_SITE_ID"] = _MYEXTERNALBRAIN_SITE_ID
    else:
        os.environ.pop("EA_ENABLE_CLICKRANK", None)
        os.environ.pop("CLICKRANK_AI_MYEXTERNALBRAIN_SITE_ID", None)
    os.environ.pop("EA_ENABLE_PUBLIC_SIDE_SURFACES", None)
    os.environ.pop("EA_ENABLE_PUBLIC_RESULTS", None)
    os.environ.pop("EA_ENABLE_PUBLIC_TOURS", None)
    os.environ.pop("EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER", None)
    os.environ.pop("EA_OPERATOR_PRINCIPAL_IDS", None)
    from app.api.app import create_app

    client = TestClient(create_app())
    client.headers.update({"X-EA-Principal-ID": principal_id})
    return client


def test_request_hostname_prefers_forwarded_host_over_host_and_url_host() -> None:
    request = SimpleNamespace(
        headers={
            "x-forwarded-host": "myexternalbrain.com",
            "host": "internal-ea-host:443",
        },
        url=SimpleNamespace(hostname="internal-ea-host"),
    )

    assert request_hostname(request) == "myexternalbrain.com"


def test_request_hostname_uses_public_base_host_for_proxied_opaque_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://myexternalbrain.com")
    request = SimpleNamespace(
        headers={
            "host": "opaque-origin.internal",
            "x-forwarded-for": "198.51.100.42",
        },
        url=SimpleNamespace(hostname="opaque-origin.internal"),
    )

    assert request_hostname(request) == "myexternalbrain.com"


def test_clickrank_site_id_for_hostname_uses_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_ENABLE_CLICKRANK", "1")
    monkeypatch.setenv("CLICKRANK_AI_MYEXTERNALBRAIN_SITE_ID", "configured-site-id")
    monkeypatch.delenv("EA_PUBLIC_APP_BASE_URL", raising=False)

    assert clickrank_site_id_for_hostname("myexternalbrain.com") == "configured-site-id"


def test_clickrank_site_id_for_hostname_falls_back_to_public_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EA_ENABLE_CLICKRANK", "1")
    monkeypatch.setenv("CLICKRANK_AI_MYEXTERNALBRAIN_SITE_ID", _MYEXTERNALBRAIN_SITE_ID)
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://myexternalbrain.com")

    assert clickrank_site_id_for_hostname("internal-ea-host") == _MYEXTERNALBRAIN_SITE_ID


def test_clickrank_site_id_for_hostname_does_not_fallback_for_unknown_public_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EA_ENABLE_CLICKRANK", "1")
    monkeypatch.setenv("CLICKRANK_AI_MYEXTERNALBRAIN_SITE_ID", _MYEXTERNALBRAIN_SITE_ID)
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://myexternalbrain.com")

    assert clickrank_site_id_for_hostname("example.com") == ""


def test_clickrank_head_snippet_returns_empty_for_unknown_host_without_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EA_ENABLE_CLICKRANK", "1")
    monkeypatch.delenv("CLICKRANK_AI_MYEXTERNALBRAIN_SITE_ID", raising=False)
    monkeypatch.delenv("EA_PUBLIC_APP_BASE_URL", raising=False)

    assert clickrank_head_snippet("example.com") == ""


def test_public_landing_includes_clickrank_snippet_for_myexternalbrain_host() -> None:
    client = _client()

    response = client.get("/", headers={"host": "myexternalbrain.com"})

    assert response.status_code == 200
    assert f"https://js.clickrank.ai/seo/{_MYEXTERNALBRAIN_SITE_ID}/script?" in response.text


def test_public_landing_includes_clickrank_snippet_for_www_myexternalbrain_host() -> None:
    client = _client()

    response = client.get("/", headers={"host": "www.myexternalbrain.com"})

    assert response.status_code == 200
    assert f"https://js.clickrank.ai/seo/{_MYEXTERNALBRAIN_SITE_ID}/script?" in response.text


def test_public_landing_omits_clickrank_snippet_for_localhost() -> None:
    client = _client()

    response = client.get("/", headers={"host": "localhost"})

    assert response.status_code == 200
    assert "clickrank.ai" not in response.text


def test_public_landing_omits_clickrank_snippet_for_unknown_public_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EA_ENABLE_CLICKRANK", "1")
    monkeypatch.setenv("CLICKRANK_AI_MYEXTERNALBRAIN_SITE_ID", _MYEXTERNALBRAIN_SITE_ID)
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://myexternalbrain.com")
    client = _client()

    response = client.get("/", headers={"host": "example.com"})

    assert response.status_code == 200
    assert "clickrank.ai" not in response.text


def test_public_landing_omits_clickrank_snippet_when_not_explicitly_enabled() -> None:
    client = _client(clickrank_enabled=False, principal_id="exec-clickrank-disabled")

    response = client.get("/", headers={"host": "myexternalbrain.com"})

    assert response.status_code == 200
    assert "clickrank.ai" not in response.text
