from __future__ import annotations

import os
import re

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


PUBLIC_ROUTES = (
    "/",
    "/product",
    "/security",
    "/pricing",
    "/register",
    "/sign-in",
)

APP_ROUTES = (
    "/app/today",
    "/app/queue",
    "/app/people",
    "/app/settings",
)


def _client(*, principal_id: str = "exec-browser-contract") -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ["EA_API_TOKEN"] = ""
    os.environ.pop("EA_ENABLE_PUBLIC_SIDE_SURFACES", None)
    os.environ.pop("EA_ENABLE_PUBLIC_RESULTS", None)
    os.environ.pop("EA_ENABLE_PUBLIC_TOURS", None)
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
    assert "operator access ·" not in lower


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
    assert "Wake up to a clear brief, not a wall of inbox noise." in landing.text
    assert "Create personal workspace" in landing.text
    assert "Nothing sends without your review." in landing.text
    for href in _internal_links(landing.text):
        assert not href.startswith("/tours")
        assert not href.startswith("/results")
        resolved = client.get(href, follow_redirects=False)
        assert resolved.status_code in {200, 303, 307}, href


def test_experimental_routes_are_unavailable_in_product_mode_by_default() -> None:
    client = _client()
    for path in ("/tours/example-tour", "/results/example-result"):
        response = client.get(path)
        assert response.status_code == 404, path


def test_app_surface_routes_render_without_product_drift() -> None:
    principal_id = "exec-app-contract"
    client = _client(principal_id=principal_id)
    for path in APP_ROUTES:
        response = client.get(path)
        assert response.status_code == 200, path
        _assert_no_drift(response.text)
        assert principal_id not in response.text

    today = client.get("/app/today")
    assert "Morning Memo" in today.text
    assert "Today" in today.text
    assert "What is most likely to slip" in today.text

    queue = client.get("/app/queue")
    assert "Decision Queue" in queue.text
    assert "What changed since the last memo" in queue.text
    assert "What gets tight first" in queue.text

    people = client.get("/app/people")
    assert "People Graph" in people.text
    assert "What still hangs off those relationships" in people.text
