from __future__ import annotations

import re
from pathlib import Path

from app.api.routes import landing as landing_routes
from app.product.models import HandoffNote
from app.product.service import ProductService
from tests.product_test_helpers import build_property_client, start_workspace


def test_propertyquarry_app_templates_do_not_reintroduce_legacy_dark_theme_tokens() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    template_paths = [
        repo_root / "ea/app/templates/base_console.html",
        repo_root / "ea/app/templates/console_shell.html",
        repo_root / "ea/app/templates/app/object_detail.html",
        repo_root / "ea/app/templates/app/people_detail.html",
        repo_root / "ea/app/templates/app/commitment_candidate_review.html",
        repo_root / "ea/app/templates/app/property_decision_workbench.html",
    ]
    forbidden_tokens = (
        "rgba(18, 23, 34",
        "rgba(15, 19, 26",
        "rgba(49, 60, 77",
        "#070a10",
        "#0a0d14",
        "#0b1017",
        "360 not ready",
        "not scheduled yet",
    )
    for template_path in template_paths:
        body = template_path.read_text(encoding="utf-8")
        assert "background: var(--panel);" in body or "background: var(--pq-paper);" in body
        for token in forbidden_tokens:
            assert token not in body, f"{token!r} leaked into {template_path.relative_to(repo_root)}"


def test_propertyquarry_workspace_routes_render_greenfield_surfaces(monkeypatch) -> None:
    principal_id = "pq-redesign-browser"
    client = build_property_client(principal_id=principal_id)
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
    profile_node = client.post(
        "/app/api/people/elisabeth/preference-profile/nodes",
        json={
            "domain": "willhaben",
            "category": "soft_preference",
            "key": "prefer_balcony",
            "value_json": True,
            "strength": "medium",
            "confidence": 0.9,
        },
    )
    assert profile_node.status_code == 200, profile_node.text

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
            "map_lat": 52.531,
            "map_lng": 13.384,
            "nearest_supermarket_m": 280,
            "nearest_supermarket_name": "Demo Supermarket",
            "nearest_supermarket_lat": 52.532,
            "nearest_supermarket_lng": 13.385,
            "nearest_pharmacy_m": 410,
            "nearest_playground_m": 520,
            "nearest_subway_m": 1200,
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
        "tour_status": "skipped",
        "match_reasons": ["Larger layout and quieter block."],
        "mismatch_reasons": ["No 360 tour yet."],
        "property_facts": {
            "price_display": "EUR 465,000",
            "price_eur": 465000.0,
            "rooms": 4,
            "area_m2": 92,
            "postal_name": "Berlin Tiergarten",
            "has_floorplan": False,
            "floorplan_count": 0,
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
    assert 'data-property-app-shell' in search.text
    assert 'data-property-spa-shell' in search.text
    assert 'data-property-pulse-strip' in search.text
    assert 'data-property-mobile-dock' in search.text
    assert 'data-property-decision-workbench' in search.text
    assert 'data-pq-greenfield-shell' in search.text
    assert 'data-pq-theater' in search.text
    assert 'data-workbench-results-table' in search.text
    assert 'data-workbench-dossier' in search.text
    assert 'data-workbench-row' in search.text
    assert "Ranked shortlist" in search.text
    assert "select one to update the 360 and decision panel" in search.text
    assert "Altbau near U6" in search.text
    assert "Family flat near Tiergarten" in search.text
    assert "360 ready" in search.text
    assert "360 unavailable" in search.text
    assert "Floorplan missing" in search.text
    assert "not scheduled yet" not in search.text
    assert "360 not ready" not in search.text
    assert "360" in search.text
    assert "Candidate" in search.text
    assert "Price" in search.text
    assert "Layout" in search.text
    assert "OODA" in search.text
    assert "Playground" in search.text
    assert "Supermarket" in search.text
    assert "Underground" in search.text
    assert "Decision reasons" in search.text
    assert "Risk and investment" in search.text
    assert "EUR 5,385/m2" in search.text
    assert "Open 360" in search.text
    assert "Review packet" in search.text
    assert 'data-candidate-packet-url="/app/research/' in search.text
    assert "Launch search" not in search.text
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
    assert "Open the space before you read the rest" in packet.text
    assert "Live 360 ready" in packet.text
    assert "OODA summary" in packet.text
    assert "Why this was selected" in packet.text
    assert "Nearest supermarket" in packet.text
    assert "https://www.google.com/maps/dir/" in packet.text
    assert "Open navigation" in packet.text
    assert "Nearest underground" in packet.text
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
    assert "Preference feedback" in packet.text
    assert "Tune this search profile" in packet.text
    assert 'data-object-feedback-reaction="like"' in packet.text
    assert 'data-object-feedback-save' in packet.text
    assert "Manage preferences" in packet.text
    assert "rgba(18, 23, 34" not in packet.text
    assert "rgba(15, 19, 26" not in packet.text
    assert "background: var(--panel);" in packet.text

    profile = client.get("/app/profile", params={"run_id": "run-42"}, headers=headers)
    assert profile.status_code == 200
    assert "Make the learning loop visible and editable." in profile.text
    assert 'data-property-learning-list' in profile.text
    assert 'data-property-preference-manager' in profile.text
    assert "Prefer Balcony (Soft Preference)" in profile.text
    assert 'data-preference-remove' in profile.text
    assert 'data-preference-add-form' in profile.text
    assert 'name="key" list="pq-preference-key-options"' in profile.text

    alerts = client.get("/app/alerts", params={"run_id": "run-42"}, headers=headers)
    assert alerts.status_code == 200
    assert "Recent outbound property follow-ups" in alerts.text
    assert "The alert lane should still expose the search brief driving it" in alerts.text

    billing = client.get("/app/billing", params={"run_id": "run-42"}, headers=headers)
    assert billing.status_code == 200
    assert "Current commercial state" in billing.text
    assert "Open pricing" in billing.text


def test_propertyquarry_in_progress_run_hides_search_form_and_shows_live_run(monkeypatch) -> None:
    principal_id = "pq-live-run-focus"
    client = build_property_client(principal_id=principal_id)
    headers = {"host": "propertyquarry.com"}
    start_workspace(client, mode="personal", workspace_name="Run Focus")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "region_code": "vienna",
            "all_of_vienna": True,
            "location_query": "Vienna",
            "selected_platforms": ["willhaben", "genossenschaften_at"],
        },
    )
    assert stored.status_code == 200, stored.text

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "status": "in_progress",
            "progress": 42,
            "message": "Scoring shortlist candidate 2 of 4 for Willhaben | Austria | Buy | Wien.",
            "summary": {
                "sources_total": 4,
                "listing_total": 6,
                "tour_created_total": 0,
                "tour_existing_total": 0,
                "sources": [],
            },
            "events": [
                {"step": "source_assessing", "message": "Scoring shortlist candidate 2 of 4 for Willhaben | Austria | Buy | Wien.", "status": "in_progress"},
            ],
        }

    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)
    live = client.get("/app/properties", params={"run_id": "run-live"}, headers=headers)
    assert live.status_code == 200
    assert 'data-property-spa-shell' in live.text
    assert 'data-property-decision-workbench' in live.text
    assert 'data-pq-greenfield-shell' in live.text
    assert 'data-pqx-state="running"' in live.text
    assert "Search is running. Inputs are locked." in live.text
    assert 'class="pqx-run-head"' in live.text
    assert live.text.index("data-pqx-progress-ring") < live.text.index("Search is running. Inputs are locked.")
    assert "Run activity" in live.text
    assert "Scoring shortlist candidate 2 of 4" in live.text
    assert "Launch search" not in live.text
    assert "Save defaults" not in live.text


def test_propertyquarry_running_progress_ring_stays_compact_and_top_aligned() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    template = (repo_root / "ea/app/templates/app/property_decision_workbench.html").read_text(encoding="utf-8")
    run_hero = re.search(r"\.pqx-run-hero \{(?P<body>.*?)\n    \}", template, re.S)
    assert run_hero is not None
    assert ".pqx-run-head" in template
    assert "grid-template-columns: auto minmax(0, 1fr);" in template
    assert "width: clamp(86px, 10vw, 118px);" in template
    assert "width: 78px;" in template
    assert "align-content: space-between;" not in run_hero.group("body")
    assert "width: min(260px, 58vw);" not in template


def test_propertyquarry_workspace_supports_all_of_vienna_toggle() -> None:
    principal_id = "pq-vienna-scope"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Vienna Scope Office")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "region_code": "vienna",
            "all_of_vienna": True,
            "location_query": "Vienna",
            "selected_platforms": ["willhaben"],
        },
    )
    assert stored.status_code == 200, stored.text

    search = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert search.status_code == 200
    assert 'data-workbench-brief-drawer' in search.text
    assert 'name="all_of_vienna" value="true" checked' in search.text
    assert 'name="use_stored_feedback_preferences" value="true" checked' in search.text
    assert "Use stored feedback preferences" in search.text
    assert "Manage feedback preferences" in search.text
    assert "All of Vienna" in search.text
    assert 'name="location_query"' in search.text
    assert re.search(
        r'data-property-field-step="areas" data-property-field-name="location_query" hidden>\s*<div class="pqx-field-title">Target areas</div>',
        search.text,
    )


def test_propertyquarry_failed_run_stays_on_activity_surface(monkeypatch) -> None:
    principal_id = "pq-failed-run-visible"
    client = build_property_client(principal_id=principal_id)
    headers = {"host": "propertyquarry.com"}
    start_workspace(client, mode="personal", workspace_name="Failed Run Office")

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "status": "failed",
            "progress": 100,
            "message": "Provider returned 403 while fetching Willhaben.",
            "summary": {"sources_total": 1, "listing_total": 0, "tour_created_total": 0, "tour_existing_total": 0, "sources": []},
            "events": [
                {"step": "source_fetching", "message": "Fetching source page for Willhaben.", "status": "in_progress"},
                {"step": "failed", "message": "Provider returned 403 while fetching Willhaben.", "status": "failed"},
            ],
        }

    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)
    page = client.get("/app/properties", params={"run_id": "run-failed"}, headers=headers)
    assert page.status_code == 200
    assert 'data-pqx-state="empty_results"' in page.text
    assert "The search did not finish cleanly." in page.text
    assert "Source scan result" in page.text
    assert "Provider returned 403 while fetching Willhaben." in page.text
    assert "Run activity" in page.text
    assert 'data-workbench-brief-drawer' not in page.text
    assert "Build the brief. Then let the agents work." not in page.text


def test_propertyquarry_packet_enriches_sparse_candidate_facts_for_investment(monkeypatch) -> None:
    principal_id = "pq-packet-fact-enrichment"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Packet Enrichment")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "property_type": "apartment",
            "investment_research_mode": "auto",
            "location_query": "Wien",
            "selected_platforms": ["willhaben"],
            "preference_person_id": "self",
            "property_commercial": {
                "status": "active",
                "active_plan_key": "agent",
                "active_until": "2099-12-31T23:59:59+00:00",
            },
        },
    )
    assert stored.status_code == 200, stored.text

    sparse_candidate = {
        "title": "Familien-Maisonette mit weitläufiger Terrasse und drei Zimmern, 88,48 m², € 659.000,-, (1160 Wien) - willhaben",
        "property_url": "https://www.willhaben.at/iad/object?adId=2113641102",
        "fit_summary": "Sparse candidate facts should still allow underwriting.",
        "recommendation": "shortlist",
        "review_url": "",
        "tour_url": "",
        "match_reasons": ["Location and layout fit."],
        "mismatch_reasons": [],
        "property_facts": {"has_360": False},
    }

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "status": "processed",
            "progress": 100,
            "message": "done",
            "summary": {
                "sources_total": 1,
                "listing_total": 1,
                "tour_created_total": 0,
                "tour_existing_total": 0,
                "sources": [
                    {
                        "source_label": "Willhaben | Austria | Buy | Wien",
                        "listing_total": 1,
                        "top_candidates": [sparse_candidate],
                    }
                ],
            },
            "events": [],
        }

    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)
    monkeypatch.setattr(
        landing_routes,
        "_property_investment_research_snapshot",
        lambda **kwargs: {
            "current_price_eur": 659000.0,
            "current_area_sqm": 88.48,
            "current_price_per_sqm_eur": 7448.01,
            "market_buy_per_sqm_eur": 7000.0,
            "market_buy_delta_pct": 6.4,
            "market_rent_per_sqm_eur": 18.5,
            "expected_monthly_rent_eur": 1636.88,
            "gross_yield_pct": 2.98,
            "payback_years": 33.5,
            "buy_sample_count": 4,
            "rent_sample_count": 3,
            "buy_samples": [{"title": "Comp A", "per_sqm_eur": 7000.0, "source_label": "Willhaben"}],
            "rent_samples": [{"title": "Rent Comp A", "per_sqm_eur": 18.5, "source_label": "Willhaben"}],
        },
    )

    headers = {"host": "propertyquarry.com"}
    research = client.get("/app/research", params={"run_id": "run-88"}, headers=headers)
    packet_match = re.search(r'href="(/app/research/[^"?]+)\?run_id=run-88"', research.text)
    assert packet_match is not None
    packet = client.get(packet_match.group(1), params={"run_id": "run-88", "investment": 1}, headers=headers)
    assert packet.status_code == 200
    assert "Investment research is waiting on core facts" not in packet.text
    assert "Current underwriting base" in packet.text
    assert "Buy-side benchmark" in packet.text
    assert "Gross yield" in packet.text


def test_propertyquarry_workspace_search_surface_keeps_internal_review_link(monkeypatch) -> None:
    principal_id = "pq-redesign-no-fallback"
    client = build_property_client(principal_id=principal_id)
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


def test_propertyquarry_research_packet_shows_auction_investment_context_when_benchmark_is_pending(monkeypatch) -> None:
    principal_id = "pq-redesign-auction-investment"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Office")
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "property_type": "apartment",
            "investment_research_mode": "auto",
            "location_query": "Wien",
            "selected_platforms": ["justiz_edikte_at"],
            "preference_person_id": "self",
            "property_commercial": {
                "status": "active",
                "active_plan_key": "agent",
                "active_until": "2099-12-31T23:59:59+00:00",
            },
        },
    )
    assert stored.status_code == 200, stored.text

    auction_candidate = {
        "title": "BG Innere Stadt Wien, 001 50 E 30/25a",
        "summary": "",
        "property_url": "https://edikte2.justiz.gv.at/edikte/ex/exedi3.nsf/alldoc/example!OpenDocument",
        "fit_score": 37.0,
        "fit_summary": "",
        "recommendation": "",
        "review_url": "",
        "tour_url": "",
        "match_reasons": [],
        "mismatch_reasons": [],
        "property_facts": {
            "court": "BG Innere Stadt Wien",
            "court_file_reference": "001 50 E 30/25a",
            "valuation_display": "EUR 310,000",
            "reserve_price_display": "EUR 155,000",
            "occupancy_status": "occupied",
        },
    }

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "status": "processed",
            "progress": 100,
            "message": "done",
            "summary": {
                "sources_total": 1,
                "listing_total": 1,
                "tour_created_total": 0,
                "tour_existing_total": 0,
                "sources": [
                    {
                        "source_label": "Justiz Edikte Auctions | Austria | Buy | Wien",
                        "listing_total": 1,
                        "top_candidates": [auction_candidate],
                    }
                ],
            },
            "events": [],
        }

    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)
    monkeypatch.setattr(landing_routes, "_property_investment_research_snapshot", lambda **kwargs: {})

    headers = {"host": "propertyquarry.com"}
    research = client.get("/app/research", params={"run_id": "run-auction"}, headers=headers)
    packet_match = re.search(r'href="(/app/research/[^"?]+)\?run_id=run-auction"', research.text)
    assert packet_match is not None
    packet = client.get(packet_match.group(1), params={"run_id": "run-auction", "investment": 1}, headers=headers)
    assert packet.status_code == 200
    assert "Court process" in packet.text
    assert "Case reference" in packet.text
    assert "Judicial valuation" in packet.text
    assert "Reserve or deposit" in packet.text
    assert "Judicial sale diligence" in packet.text


def test_propertyquarry_research_packet_shows_cooperative_investment_context_when_benchmark_is_pending(monkeypatch) -> None:
    principal_id = "pq-redesign-coop-investment"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Office")
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "property_type": "apartment",
            "investment_research_mode": "auto",
            "location_query": "Wien",
            "selected_platforms": ["genossenschaften_at"],
            "preference_person_id": "self",
            "property_commercial": {
                "status": "active",
                "active_plan_key": "agent",
                "active_until": "2099-12-31T23:59:59+00:00",
            },
        },
    )
    assert stored.status_code == 200, stored.text

    coop_candidate = {
        "title": "1210 Wien | Antonie-Lehr-Straße 18 / Leopoldauer Haide Gasse 12",
        "summary": "Miete | 144 units | August 2026 | 37486 registrations",
        "property_url": "https://angebote.sozialbau.at/sobitvX/htmlprospect/home.xhtml?pq_listing=1",
        "fit_score": 52.0,
        "fit_summary": "",
        "recommendation": "",
        "review_url": "",
        "tour_url": "",
        "tour_status": "skipped",
        "match_reasons": [],
        "mismatch_reasons": [],
        "property_facts": {
            "provider_group": "genossenschaften_at",
            "provider_channel": "sozialbau",
            "marketing_type": "Miete",
            "availability_label": "August 2026",
            "registration_count": 37486,
            "postal_name": "1210 Wien",
            "has_floorplan": False,
            "floorplan_count": 0,
        },
    }

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "status": "processed",
            "progress": 100,
            "message": "done",
            "summary": {
                "sources_total": 1,
                "listing_total": 1,
                "tour_created_total": 0,
                "tour_existing_total": 0,
                "sources": [
                    {
                        "source_label": "Genossenschaften | Austria | Buy | Wien | Sozialbau Projekte in Bau",
                        "listing_total": 1,
                        "top_candidates": [coop_candidate],
                    }
                ],
            },
            "events": [],
        }

    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)
    monkeypatch.setattr(landing_routes, "_property_investment_research_snapshot", lambda **kwargs: {})

    headers = {"host": "propertyquarry.com"}
    research = client.get("/app/research", params={"run_id": "run-coop"}, headers=headers)
    packet_match = re.search(r'href="(/app/research/[^"?]+)\?run_id=run-coop"', research.text)
    assert packet_match is not None
    packet = client.get(packet_match.group(1), params={"run_id": "run-coop", "investment": 1}, headers=headers)
    assert packet.status_code == 200
    assert "Provider lane" in packet.text
    assert "Offer posture" in packet.text
    assert "Applicant pressure" in packet.text
    assert "Rental-led cooperative lane" in packet.text
    assert "Extremely high applicant pressure" in packet.text
    assert "360 unavailable" in packet.text
    assert "Floorplan missing" in packet.text
    assert "not scheduled yet" not in packet.text


def test_propertyquarry_settings_hide_generic_google_sync_metrics() -> None:
    client = build_property_client(principal_id="pq-redesign-settings")
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
