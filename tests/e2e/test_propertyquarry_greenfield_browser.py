from __future__ import annotations

import json
import socket
import threading
import time
import urllib.request
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

uvicorn = pytest.importorskip("uvicorn")
pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

Config = uvicorn.Config
Server = uvicorn.Server

from app.api.app import create_app
from app.product.models import HandoffNote
from app.product.service import ProductService


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def _wait_for_http(base_url: str, *, timeout_seconds: float = 15.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/sign-in", timeout=2.0) as response:
                if int(getattr(response, "status", 0) or 0) == 200:
                    return
        except Exception:
            time.sleep(0.1)
    raise AssertionError(f"server at {base_url} did not become ready in time")


@pytest.fixture()
def propertyquarry_browser_server(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, object]]:
    from tests.product_test_helpers import build_product_client, start_workspace

    client = build_product_client(principal_id="pq-greenfield-browser")
    start_workspace(client, mode="personal", workspace_name="Property Office")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "paypal-client")
    monkeypatch.setenv("PAYPAL_SECRET", "paypal-secret")
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "DE",
            "language_code": "de",
            "listing_mode": "buy",
            "property_type": "apartment",
            "location_query": "Berlin",
            "keywords": "lift family balcony",
            "selected_platforms": ["immoscout_de", "immowelt"],
            "preference_person_id": "elisabeth",
            "max_results_per_source": 4,
        },
    )
    assert stored.status_code == 200, stored.text

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        assert principal_id == "pq-greenfield-browser"
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "status": "processed",
            "progress": 100,
            "message": "Property scouting run completed.",
            "summary": {
                "sources_total": 2,
                "listing_total": 7,
                "tour_created_total": 1,
                "tour_existing_total": 1,
                "sources": [
                    {
                        "source_label": "ImmoScout24 Germany",
                        "listing_total": 4,
                        "high_fit_total": 2,
                        "tour_created_total": 1,
                        "notified_total": 1,
                        "top_candidates": [
                            {
                                "title": "Altbau near U6",
                                "property_url": "https://www.immobilienscout24.de/expose/altbau-u6",
                                "fit_summary": "Personal fit 92/100 · shortlist · Lift and transit fit.",
                                "recommendation": "shortlist",
                                "review_url": "https://myexternalbrain.com/app/handoffs/human_task:review-1",
                                "tour_url": "https://myexternalbrain.com/tours/altbau-u6",
                                "match_reasons": ["Lift and transit fit."],
                                "mismatch_reasons": [],
                                "property_facts": {
                                    "price_display": "EUR 420,000",
                                    "price_eur": 420000.0,
                                    "rooms": 3,
                                    "area_m2": 78,
                                    "postal_name": "Berlin Mitte",
                                    "nearest_supermarket_m": 280,
                                    "nearest_pharmacy_m": 410,
                                    "nearest_playground_m": 520,
                                    "nearest_subway_m": 1200,
                                },
                            },
                            {
                                "title": "Family flat near Tiergarten",
                                "property_url": "https://www.immobilienscout24.de/expose/family-tiergarten",
                                "fit_summary": "Personal fit 87/100 · shortlist · Larger layout and quieter block.",
                                "recommendation": "shortlist",
                                "review_url": "https://myexternalbrain.com/app/handoffs/human_task:review-2",
                                "tour_url": "",
                                "match_reasons": ["Larger layout and quieter block."],
                                "mismatch_reasons": ["No 360 tour yet."],
                                "property_facts": {
                                    "price_display": "EUR 465,000",
                                    "price_eur": 465000.0,
                                    "rooms": 4,
                                    "area_m2": 92,
                                    "postal_name": "Berlin Tiergarten",
                                },
                            },
                        ],
                    }
                ],
            },
            "events": [
                {"step": "sources_resolved", "message": "Resolved 2 source(s) for scanning.", "status": "in_progress"},
                {"step": "completed", "message": "Property scouting run completed.", "status": "processed"},
            ],
        }

    def _fake_handoffs(self, *, principal_id: str, limit: int = 20, operator_id: str = "", status: str | None = "pending"):
        assert principal_id == "pq-greenfield-browser"
        return (
            HandoffNote(
                id="human_task:tour-1",
                queue_item_ref="queue:tour-1",
                summary="Hosted 3D page for Auhofstrasse shortlist",
                owner="office",
                due_time=None,
                escalation_status="high",
                task_type="property_tour_followup",
                delivery_reason="Lift, playground and subway fit the profile.",
                property_url="https://www.kalandra.at/objekt/14997053",
                tour_url="https://myexternalbrain.com/tours/auhofstrasse-14997053",
            ),
        )

    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)
    monkeypatch.setattr(ProductService, "list_handoffs", _fake_handoffs)

    app = create_app()
    test_client = TestClient(app, base_url="https://propertyquarry.com")
    test_client.headers.update({"X-EA-Principal-ID": "pq-greenfield-browser", "host": "propertyquarry.com"})

    port = _free_port()
    config = Config(app=app, host="127.0.0.1", port=port, log_level="warning")
    server = Server(config)
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    local_base_url = f"http://127.0.0.1:{port}"
    browser_base_url = f"http://propertyquarry.com:{port}"
    _wait_for_http(local_base_url)
    try:
        yield {"base_url": browser_base_url}
    finally:
        server.should_exit = True
        thread.join(timeout=10.0)


@pytest.fixture()
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--host-resolver-rules=MAP propertyquarry.com 127.0.0.1",
                "--no-proxy-server",
            ],
        )
        try:
            yield browser
        finally:
            browser.close()


def _new_context(browser: Browser, *, mobile: bool = False) -> BrowserContext:
    return browser.new_context(
        viewport={"width": 430 if mobile else 1440, "height": 932 if mobile else 1100},
        extra_http_headers={"X-EA-Principal-ID": "pq-greenfield-browser"},
    )


def test_propertyquarry_greenfield_workspace_in_real_browser(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/properties?run_id=run-42", wait_until="networkidle")
        assert response is not None and response.ok
        content = page.content()
        assert 'data-property-spa-shell' in content
        assert 'data-property-mobile-dock' in content
        assert 'data-property-decision-workbench' in content
        assert 'data-pq-greenfield-shell' in content
        assert 'data-pq-theater' in content
        assert 'data-workbench-results-table' in content
        assert 'data-workbench-dossier' in content
        assert "Ranked shortlist" in content
        assert "Altbau near U6" in content
        assert "Family flat near Tiergarten" in content
        assert "360 ready" in content
        assert "Review packet" in content
        assert "Open 360" in content
        assert "OODA" in content

        page.locator("[data-workbench-row]", has_text="Family flat near Tiergarten").click()
        assert page.locator("[data-workbench-dossier]", has_text="Family flat near Tiergarten").is_visible()
        assert page.locator("[data-workbench-dossier]", has_text="360 not ready").is_visible()
        assert page.get_by_role("link", name="Review packet").first.is_visible()
    finally:
        context.close()


def test_propertyquarry_greenfield_workspace_is_mobile_usable(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=True)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/properties?run_id=run-42", wait_until="networkidle")
        assert response is not None and response.ok
        content = page.content()
        assert 'data-property-decision-workbench' in content
        assert 'data-pq-greenfield-shell' in content
        assert 'data-property-mobile-dock' in content
        assert page.locator('[data-workbench-mobile-mode="results"]').is_visible()
        assert page.locator('[data-workbench-mobile-mode="property"]').is_visible()
        mode_box = page.locator('[data-workbench-mobile-mode="results"]').bounding_box()
        assert mode_box is not None and mode_box["width"] <= 430
        mobile_dock = page.locator("[data-property-mobile-dock]")
        assert mobile_dock.is_visible()
        page.locator("[data-workbench-row]", has_text="Family flat near Tiergarten").click()
        page.locator('[data-workbench-mobile-mode="property"]').click()
        assert page.locator("[data-workbench-dossier]", has_text="Family flat near Tiergarten").is_visible()
        assert page.locator("[data-workbench-dossier]", has_text="360 not ready").is_visible()

        review_action = page.get_by_role("link", name="Review packet").first.bounding_box()
        assert review_action is not None and review_action["width"] <= 430
    finally:
        context.close()


def test_propertyquarry_setup_wizard_changes_visible_controls_and_collapses_all_vienna(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/properties", wait_until="networkidle")
        assert response is not None and response.ok
        page.wait_for_function("document.querySelector('[data-console-form-variant=\"property_search\"]')?.dataset.propertyActiveStep === 'search'")
        assert page.locator('[data-property-field-name="country_code"]').is_visible()
        assert page.locator('[data-property-field-name="location_query"]').is_hidden()

        page.select_option('select[name="country_code"]', "AT")
        page.locator("[data-property-step-next]").click()
        page.wait_for_function("document.querySelector('[data-console-form-variant=\"property_search\"]')?.dataset.propertyActiveStep === 'areas'")
        assert page.locator('[data-property-field-name="region_code"]').is_visible()
        assert page.locator('[data-property-field-name="country_code"]').is_hidden()
        assert page.locator('[data-property-field-name="location_query"]').is_visible()

        page.locator('input[name="all_of_vienna"]').check()
        assert page.locator('[data-property-field-name="location_query"]').is_hidden()
        assert page.locator('[data-property-field-name="location_query"]').get_attribute("data-property-collapsed-by") == "all_of_vienna"

        page.locator('input[name="all_of_vienna"]').uncheck()
        assert page.locator('[data-property-field-name="location_query"]').is_visible()
    finally:
        context.close()


def test_propertyquarry_start_failure_explains_backend_reason(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False)
    page: Page = context.new_page()
    try:
        page.route(
            "**/app/api/signals/property/search/run",
            lambda route: route.fulfill(
                status=409,
                content_type="application/json",
                body=json.dumps({"detail": "property_plan_upgrade_required:plus"}),
            ),
        )
        response = page.goto(f"{base_url}/app/properties", wait_until="networkidle")
        assert response is not None and response.ok
        page.locator('[data-property-step-trigger="providers"]').click()
        page.wait_for_function("document.querySelector('[data-console-form-variant=\"property_search\"]')?.dataset.propertyActiveStep === 'providers'")
        page.locator("[data-property-start]").click()
        page.wait_for_function("document.querySelector('[data-property-inline-error]')?.textContent.includes('Upgrade required for this run')")
        assert page.locator("[data-property-inline-error]", has_text="Upgrade required for this run").is_visible()
        assert page.locator("[data-property-inline-error]", has_text="plus plan").is_visible()
    finally:
        context.close()
