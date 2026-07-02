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
    "/data-deletion",
    "/pricing",
    "/register",
    "/sign-in",
)

APP_ROUTES = (
    "/app/properties",
    "/app/settings",
)

LEGACY_APP_ROUTE_REDIRECTS = {
    "/app/briefing": "/app/queue",
    "/app/inbox": "/app/queue",
    "/app/follow-ups": "/app/commitments",
    "/app/memory": "/app/people",
    "/app/contacts": "/app/evidence",
    "/app/channels": "/app/settings",
    "/app/automations": "/app/settings",
}


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

    client = TestClient(create_app(), base_url="https://propertyquarry.com")
    client.headers.update({"X-EA-Principal-ID": principal_id, "host": "propertyquarry.com"})
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
    assert "Search once. Rank hard. Research the shortlist." in landing.text
    assert "Create account" in landing.text
    assert "Personalized search" in landing.text

    pricing = client.get("/pricing")
    assert "Typical search path" in pricing.text
    assert "Plus and Agent usually add" in pricing.text
    assert "Typical office path" not in pricing.text

    security = client.get("/security")
    assert "Automatic digests" in security.text
    assert "Morning memo schedule" not in security.text

    deletion = client.get("/data-deletion")
    assert "Request deletion of your PropertyQuarry data." in deletion.text
    assert "property@propertyquarry.com" in deletion.text
    assert "Data deletion request" in deletion.text

    sign_in = client.get("/sign-in")
    assert "Shared review when needed" in sign_in.text

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

    properties = client.get("/app/properties")
    assert "Run a premium market sweep" in properties.text
    assert "What this search is optimizing for" in properties.text

    settings = client.get("/app/settings")
    assert "Rules" in settings.text or "Preferences" in settings.text


def test_legacy_app_aliases_redirect_to_canonical_routes() -> None:
    client = _client()
    for path, target in LEGACY_APP_ROUTE_REDIRECTS.items():
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 307, path
        assert response.headers["location"] == target

    redirected = client.get("/app/inbox?focus=board", follow_redirects=False)
    assert redirected.status_code == 307
    assert redirected.headers["location"] == "/app/queue?focus=board"


def test_unauthenticated_browser_app_navigation_redirects_to_sign_in() -> None:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ["EA_API_TOKEN"] = "test-token"
    os.environ.pop("EA_ENABLE_PUBLIC_SIDE_SURFACES", None)
    os.environ.pop("EA_ENABLE_PUBLIC_RESULTS", None)
    os.environ.pop("EA_ENABLE_PUBLIC_TOURS", None)
    os.environ.pop("EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER", None)
    os.environ.pop("EA_OPERATOR_PRINCIPAL_IDS", None)
    from app.api.app import create_app

    client = TestClient(create_app())
    response = client.get("/app/properties", headers={"accept": "text/html"}, follow_redirects=False)
    assert response.status_code == 404
    assert response.json()["error"]["message"] == "property_search_not_available"


def test_unauthenticated_api_calls_still_return_json_auth_error() -> None:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ["EA_API_TOKEN"] = "test-token"
    os.environ.pop("EA_ENABLE_PUBLIC_SIDE_SURFACES", None)
    os.environ.pop("EA_ENABLE_PUBLIC_RESULTS", None)
    os.environ.pop("EA_ENABLE_PUBLIC_TOURS", None)
    os.environ.pop("EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER", None)
    os.environ.pop("EA_OPERATOR_PRINCIPAL_IDS", None)
    from app.api.app import create_app

    client = TestClient(create_app())
    response = client.get("/app/api/brief", headers={"accept": "application/json"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth_required"


def test_browser_setup_does_not_expose_or_accept_principal_override() -> None:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ["EA_API_TOKEN"] = ""
    os.environ["EA_DEFAULT_PRINCIPAL_ID"] = "browser-default"
    from app.api.app import create_app

    client = TestClient(create_app(), base_url="https://propertyquarry.com")

    setup = client.get("/get-started")
    assert setup.status_code == 200
    assert "Workspace ID (advanced)" not in setup.text
    assert "Switching workspaces from the browser is disabled here." not in setup.text

    override = client.post(
        "/setup/start",
        data={
            "principal_id": "spoofed-browser-principal",
            "workspace_name": "Spoofed Workspace",
            "workspace_mode": "personal",
            "region": "AT",
            "language": "en",
            "timezone": "Europe/Vienna",
            "selected_channels": "google",
        },
        follow_redirects=False,
    )
    assert override.status_code == 403
