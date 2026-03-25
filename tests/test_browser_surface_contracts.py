from __future__ import annotations

import os
import re

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


PUBLIC_ROUTES = (
    "/",
    "/product",
    "/integrations",
    "/security",
    "/pricing",
    "/docs",
    "/get-started",
    "/sign-in",
)

APP_ROUTES = (
    "/app/today",
    "/app/briefing",
    "/app/inbox",
    "/app/follow-ups",
    "/app/memory",
    "/app/contacts",
    "/app/channels",
    "/app/automations",
    "/app/activity",
    "/app/settings",
)


def _client(*, principal_id: str = "exec-browser-contract") -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ["EA_API_TOKEN"] = ""
    os.environ.pop("EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER", None)
    os.environ.pop("EA_OPERATOR_PRINCIPAL_IDS", None)
    from app.api.app import create_app

    client = TestClient(create_app())
    client.headers.update({"X-EA-Principal-ID": principal_id})
    return client


def _assert_no_drift(text: str) -> None:
    lower = text.lower()
    assert "chummer" not in lower
    assert "gm_creator_ops" not in lower
    assert "principal id" not in lower


def _internal_links(html: str) -> list[str]:
    refs = sorted(set(re.findall(r'href="([^"]+)"', html)))
    return [ref for ref in refs if ref.startswith("/") and not ref.startswith("//")]


def test_public_surface_routes_render_and_keep_product_language() -> None:
    client = _client()
    for path in PUBLIC_ROUTES:
        response = client.get(path)
        assert response.status_code == 200, path
        _assert_no_drift(response.text)

    landing = client.get("/")
    assert "Walk into the day with a ranked brief" in landing.text
    assert "Get started" in landing.text
    for href in _internal_links(landing.text):
        resolved = client.get(href, follow_redirects=False)
        assert resolved.status_code in {200, 303, 307}, href


def test_app_surface_routes_render_without_product_drift() -> None:
    client = _client(principal_id="exec-app-contract")
    for path in APP_ROUTES:
        response = client.get(path)
        assert response.status_code == 200, path
        _assert_no_drift(response.text)

    today = client.get("/app/today")
    assert "Today" in today.text
    assert "Next to clear" in today.text

    briefing = client.get("/app/briefing")
    assert "Briefing" in briefing.text
    assert "Context that shapes the day" in briefing.text

    inbox = client.get("/app/inbox")
    assert "Inbox" in inbox.text
    assert "Channel readiness" in inbox.text
