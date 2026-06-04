from __future__ import annotations

import re

from app.api.routes import landing as landing_routes
from app.product.models import HandoffNote
from app.product.service import ProductService
from tests.product_test_helpers import build_product_client, start_workspace


def test_propertyquarry_workspace_routes_render_greenfield_surfaces(monkeypatch) -> None:
    principal_id = "pq-redesign-browser"
    client = build_product_client(principal_id=principal_id)
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
            "investment_research_mode": "auto",
            "location_query": "Berlin",
            "keywords": "lift family balcony",
            "selected_platforms": ["immoscout_de", "immowelt"],
            "preference_person_id": "elisabeth",
            "max_results_per_source": 4,
        },
    )
    assert stored.status_code == 200, stored.text

    top_candidate = {
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
            "street_address": "Invalidenstrasse 14",
            "nearest_supermarket_m": 280,
            "nearest_pharmacy_m": 410,
            "listing_research_snapshot": {
                "street_address": "Invalidenstrasse 14",
                "nearest_supermarket_m": 280,
                "map_lat": 52.531,
            },
            "listing_research_meta": {
                "strategy": "provider_html_plus_geo",
            },
        },
    }
    second_candidate = {
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
    }
    def _fake_run_status(self, *, principal_id: str, run_id: str):
        assert principal_id == "pq-redesign-browser"
        assert run_id == "run-42"
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
                            "top_candidates": [top_candidate, second_candidate],
                        }
                    ],
                },
            "events": [
                {"step": "sources_resolved", "message": "Resolved 2 source(s) for scanning.", "status": "in_progress"},
                {"step": "completed", "message": "Property scouting run completed.", "status": "processed"},
            ],
        }

    def _fake_handoffs(self, *, principal_id: str, limit: int = 20, operator_id: str = "", status: str | None = "pending"):
        assert principal_id == "pq-redesign-browser"
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
    monkeypatch.setattr(landing_routes, "_property_investment_research_access_level", lambda *args, **kwargs: "full")
    monkeypatch.setattr(
        landing_routes,
        "_property_investment_research_snapshot",
        lambda **kwargs: {
            "current_price_eur": 420000.0,
            "current_area_sqm": 78.0,
            "current_price_per_sqm_eur": 5384.62,
            "market_buy_per_sqm_eur": 5600.0,
            "market_buy_delta_pct": -3.8,
            "market_rent_per_sqm_eur": 19.5,
            "expected_monthly_rent_eur": 1521.0,
            "gross_yield_pct": 4.35,
            "payback_years": 23.0,
            "buy_sample_count": 3,
            "rent_sample_count": 2,
            "buy_samples": [{"title": "Comp A", "per_sqm_eur": 5600.0, "source_label": "ImmoScout24 Germany"}],
            "rent_samples": [{"title": "Rent Comp A", "per_sqm_eur": 19.5, "source_label": "ImmoScout24 Germany"}],
        },
    )

    headers = {"host": "propertyquarry.com"}
    search = client.get("/app/properties", params={"run_id": "run-42"}, headers=headers)
    assert search.status_code == 200
    assert "Shape the next market sweep before the crawlers fan out." in search.text
    assert "Open shortlist" in search.text
    assert "Providers" in search.text
    assert "Investment research" in search.text
    assert 'href="/app/shortlist"' in search.text
    assert 'href="/app/research"' in search.text
    assert 'href="/app/profile"' in search.text
    assert 'href="/app/alerts"' in search.text
    assert 'href="/app/billing"' in search.text
    assert 'data-console-form-variant="property_search"' in search.text
    assert "JavaScript is unavailable. The guided wizard is disabled" in search.text
    assert "Morning Memo" not in search.text
    assert "Office signals ingested" not in search.text

    shortlist = client.get("/app/shortlist", params={"run_id": "run-42"}, headers=headers)
    assert shortlist.status_code == 200
    assert "Review only the few properties that deserve attention now." in shortlist.text
    assert "Compare the top shortlist before opening deeper packets" in shortlist.text
    assert "Altbau near U6" in shortlist.text
    assert "Review packet" in shortlist.text
    assert "Hosted review" in shortlist.text

    research = client.get("/app/research", params={"run_id": "run-42"}, headers=headers)
    assert research.status_code == 200
    assert "Inspect the evidence before you open the raw listing." in research.text
    assert "Hosted 3D page for Auhofstrasse shortlist" in research.text
    assert "/app/research/" in research.text
    packet_match = re.search(r'href="(/app/research/[^"?]+)\?run_id=run-42"', research.text)
    assert packet_match is not None

    packet = client.get(packet_match.group(1), params={"run_id": "run-42", "investment": 1}, headers=headers)
    assert packet.status_code == 200
    assert "Internal property dossier with fit reasoning" in packet.text
    assert "Decision call" in packet.text
    assert "Why now" in packet.text
    assert "Missing-data severity" in packet.text
    assert "Decision scorecard" in packet.text
    assert "Evidence and provenance" in packet.text
    assert "Investment research" in packet.text
    assert "Gross yield" in packet.text
    assert "Expected monthly rent" in packet.text
    assert "Open questions" in packet.text
    assert "Compare next" in packet.text
    assert "Candidate" in packet.text
    assert "Layout" in packet.text
    assert "Family flat near Tiergarten" in packet.text
    assert "Researched" in packet.text
    assert "Hosted review" in packet.text
    assert "Original listing" in packet.text

    profile = client.get("/app/profile", params={"run_id": "run-42"}, headers=headers)
    assert profile.status_code == 200
    assert "Make the learning loop visible and editable." in profile.text
    assert 'data-property-learning-list' in profile.text

    alerts = client.get("/app/alerts", params={"run_id": "run-42"}, headers=headers)
    assert alerts.status_code == 200
    assert "Recent outbound property follow-ups" in alerts.text
    assert "The alert lane should still expose the search brief driving it" in alerts.text

    billing = client.get("/app/billing", params={"run_id": "run-42"}, headers=headers)
    assert billing.status_code == 200
    assert "Current commercial state" in billing.text
    assert "Plus checkout" in billing.text


def test_propertyquarry_workspace_search_surface_keeps_internal_review_link(monkeypatch) -> None:
    principal_id = "pq-redesign-no-fallback"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Office")

    def _fake_handoffs(self, *, principal_id: str, limit: int = 20, operator_id: str = "", status: str | None = "pending"):
        assert principal_id == "pq-redesign-no-fallback"
        return (
            HandoffNote(
                id="human_task:tour-2",
                queue_item_ref="queue:tour-2",
                summary="Review shortlisted property packet",
                owner="office",
                due_time=None,
                escalation_status="high",
                task_type="property_alert_review",
                delivery_reason="Research page is still pending.",
                property_url="https://www.kalandra.at/objekt/14997053",
                tour_url="",
            ),
        )

    monkeypatch.setattr(ProductService, "list_handoffs", _fake_handoffs)

    response = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert response.status_code == 200
    assert "Review shortlisted property packet" in response.text


def test_propertyquarry_settings_hide_generic_google_sync_metrics() -> None:
    client = build_product_client(principal_id="pq-redesign-settings")
    start_workspace(client, mode="personal", workspace_name="Property Office")

    settings = client.get("/app/settings", headers={"host": "propertyquarry.com"})
    assert settings.status_code == 200
    assert "Identity and return access" in settings.text
    assert "Current search brief state" in settings.text
    assert "Operating posture" in settings.text
    assert "Open pricing" in settings.text
    assert "Open security" in settings.text
    assert "Sync runs" not in settings.text
    assert "Last Google sync" not in settings.text
    assert "Office signals ingested" not in settings.text
