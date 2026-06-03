from __future__ import annotations

import time

import app.product.service as product_service
from app.product.service import ProductService
from app.services.property_billing import property_commercial_snapshot
from tests.product_test_helpers import build_product_client, seed_product_state, start_workspace


def _poll_property_search_run_status(client, run_id: str) -> dict[str, object]:
    latest_status: dict[str, object] = {}
    for _ in range(120):
        response = client.get(f"/app/api/signals/property/search/run/{run_id}")
        assert response.status_code == 200, response.text
        latest_status = response.json()
        if str(latest_status.get("status") or "").strip() in {"processed", "failed", "noop", "cancelled"}:
            return latest_status
        time.sleep(0.02)
    return latest_status


def test_free_property_plan_keeps_agent_depth_but_stays_capped_per_provider() -> None:
    snapshot = property_commercial_snapshot({})

    assert snapshot["current_plan_key"] == "free"
    assert snapshot["research_depth"] == "deep"
    assert snapshot["max_platforms"] == 1
    assert snapshot["max_results_per_source"] == 2


def test_property_search_run_starts_with_explicit_platform_and_tracks_progress(monkeypatch) -> None:
    principal_id = "exec-property-search-run-explicit"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Search Run Office")
    seed_product_state(client, principal_id=principal_id)

    observed: dict[str, object] = {}

    def _fake_sync_direct_property_scout(
        self,
        *,
        principal_id: str,
        actor: str,
        selected_platforms: tuple[str, ...] = (),
        property_search_preferences: dict[str, object] | None = None,
        force_refresh: bool = False,
        max_results_per_source: int | None = None,
        progress_callback: callable | None = None,
    ) -> dict[str, object]:
        observed["principal_id"] = principal_id
        observed["actor"] = actor
        observed["selected_platforms"] = tuple(selected_platforms)
        observed["property_search_preferences"] = dict(property_search_preferences or {})
        observed["force_refresh"] = bool(force_refresh)
        observed["max_results_per_source"] = max_results_per_source
        if callable(progress_callback):
            progress_callback(
                step="mock-progress",
                message="mock scout step",
                status="in_progress",
                steps_delta=2,
                summary_updates={"sources_total": 1},
            )
        return {
            "generated_at": product_service._now_iso(),
            "status": "processed",
            "sources_total": 1,
            "listing_total": 1,
            "review_created_total": 1,
            "review_existing_total": 0,
            "notified_total": 0,
            "tour_created_total": 0,
            "tour_existing_total": 0,
            "high_fit_total": 0,
            "watch_notified_total": 0,
            "sources": [
                {
                    "source_url": "https://www.willhaben.at/iad/immobilien/mietwohnungen",
                    "source_label": "Willhaben Rentals",
                    "preference_person_id": "self",
                    "listing_total": 1,
                    "review_created_total": 1,
                    "review_existing_total": 0,
                    "notified_total": 0,
                    "tour_created_total": 0,
                    "tour_existing_total": 0,
                    "high_fit_total": 0,
                    "watch_notified_total": 0,
                    "top_fit_score": 0.0,
                }
            ],
        }

    monkeypatch.setattr(ProductService, "sync_direct_property_scout", _fake_sync_direct_property_scout)

    started = client.post(
        "/app/api/signals/property/search/run",
        json={
            "selected_platforms": ["willhaben"],
            "property_preferences": {"preference_person_id": "elisabeth"},
            "force_refresh": True,
            "max_results_per_source": 2,
        },
    )
    assert started.status_code == 200, started.text

    started_body = started.json()
    run_id = started_body["run_id"]
    assert run_id
    assert started_body["selected_platforms"] == ["willhaben"]
    assert run_id in started_body["status_url"]

    status = _poll_property_search_run_status(client, run_id)
    assert status["status"] == "processed"
    assert status["summary"]["sources_total"] == 1
    assert status["steps_completed"] > 0
    assert status["progress"] >= 0
    assert status["principal_id"] == principal_id
    assert observed["selected_platforms"] == ("willhaben",)
    assert observed["force_refresh"] is True
    assert observed["max_results_per_source"] == 2
    assert observed["property_search_preferences"]["preference_person_id"] == "elisabeth"


def test_property_search_run_rejects_invalid_platform_and_enforces_run_principal_scope(monkeypatch) -> None:
    principal_id = "exec-property-search-run-scope"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Search Run Scope Office")

    response = client.post(
        "/app/api/signals/property/search/run",
        json={"selected_platforms": ["not-a-real-platform"]},
    )
    assert response.status_code == 400

    observed_sync: dict[str, object] = {}

    def _fake_sync_direct_property_scout(
        self,
        *,
        principal_id: str,
        actor: str,
        selected_platforms: tuple[str, ...] = (),
        property_search_preferences: dict[str, object] | None = None,
        force_refresh: bool = False,
        max_results_per_source: int | None = None,
        progress_callback: callable | None = None,
    ) -> dict[str, object]:
        observed_sync["called"] = True
        observed_sync["selected_platforms"] = tuple(selected_platforms)
        observed_sync["force_refresh"] = bool(force_refresh)
        observed_sync["max_results_per_source"] = max_results_per_source
        if callable(progress_callback):
            progress_callback(
                step="mock-progress",
                message="mocked from onboarding prefs",
                status="in_progress",
                steps_delta=3,
                summary_updates={"sources_total": 1},
            )
        return {
            "generated_at": product_service._now_iso(),
            "status": "processed",
            "sources_total": 1,
            "listing_total": 1,
            "review_created_total": 1,
            "review_existing_total": 0,
            "notified_total": 1,
            "tour_created_total": 0,
            "tour_existing_total": 0,
            "high_fit_total": 1,
            "watch_notified_total": 0,
            "sources": [],
        }

    monkeypatch.setattr(ProductService, "sync_direct_property_scout", _fake_sync_direct_property_scout)

    owner = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "selected_platforms": ["willhaben", "kalandra"],
            "preference_person_id": "elisabeth",
            "max_results_per_source": 2,
            "property_commercial": {"active_plan_key": "plus", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"},
        },
    )
    assert owner.status_code == 200, owner.text

    started = client.post("/app/api/signals/property/search/run", json={"property_preferences": {}})
    assert started.status_code == 200
    run_id = started.json()["run_id"]
    assert observed_sync.get("called") is True
    assert set(observed_sync.get("selected_platforms") or ()) == {"willhaben", "kalandra"}

    status = _poll_property_search_run_status(client, run_id)
    assert status["status"] == "processed"
    assert status["summary"]["sources_total"] == 1

    intruder = build_product_client(principal_id="intruder-property-search-run-scope")
    intruder_status = intruder.get(f"/app/api/signals/property/search/run/{run_id}")
    assert intruder_status.status_code == 404


def test_property_search_preferences_persist_and_merge_into_run(monkeypatch) -> None:
    principal_id = "exec-property-search-run-merge"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Search Merge Office")
    seed_product_state(client, principal_id=principal_id)

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "selected_platforms": ["willhaben", "kalandra"],
            "preference_person_id": "elisabeth",
            "max_results_per_source": 50,
            "property_commercial": {"active_plan_key": "agent", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"},
        },
    )
    assert stored.status_code == 200, stored.text
    assert stored.json()["property_search_preferences"]["max_results_per_source"] == 50

    status_snapshot = client.get("/v1/onboarding/property-search/preferences")
    assert status_snapshot.status_code == 200
    assert set(status_snapshot.json()["property_search_preferences"]["selected_platforms"]) == {"willhaben", "kalandra"}

    observed: dict[str, object] = {}

    def _fake_sync_direct_property_scout(
        self,
        *,
        principal_id: str,
        actor: str,
        selected_platforms: tuple[str, ...] = (),
        property_search_preferences: dict[str, object] | None = None,
        force_refresh: bool = False,
        max_results_per_source: int | None = None,
        progress_callback: callable | None = None,
    ) -> dict[str, object]:
        observed["selected_platforms"] = tuple(selected_platforms)
        observed["preference_person_id"] = str((property_search_preferences or {}).get("preference_person_id") or "").strip()
        observed["max_results_per_source"] = max_results_per_source
        observed["force_refresh"] = bool(force_refresh)
        return {
            "generated_at": product_service._now_iso(),
            "status": "processed",
            "sources_total": 1,
            "listing_total": 1,
            "review_created_total": 1,
            "review_existing_total": 0,
            "notified_total": 0,
            "tour_created_total": 0,
            "tour_existing_total": 0,
            "high_fit_total": 0,
            "watch_notified_total": 0,
            "sources": [],
        }

    monkeypatch.setattr(ProductService, "sync_direct_property_scout", _fake_sync_direct_property_scout)

    started = client.post(
        "/app/api/signals/property/search/run",
        json={"property_preferences": {"preference_person_id": "override"}},
    )
    assert started.status_code == 200
    assert set(observed.get("selected_platforms") or ()) == {"willhaben", "kalandra"}
    assert observed.get("preference_person_id") == "override"
    assert observed.get("max_results_per_source") == 10


def test_property_search_run_defaults_platforms_from_country_preferences(monkeypatch) -> None:
    principal_id = "exec-property-search-country-defaults"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Search Country Defaults")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "UK",
            "language_code": "en",
            "listing_mode": "rent",
            "location_query": "London",
            "selected_platforms": [],
            "property_commercial": {"active_plan_key": "agent", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"},
        },
    )
    assert stored.status_code == 200, stored.text

    observed: dict[str, object] = {}

    def _fake_sync_direct_property_scout(
        self,
        *,
        principal_id: str,
        actor: str,
        selected_platforms: tuple[str, ...] = (),
        property_search_preferences: dict[str, object] | None = None,
        force_refresh: bool = False,
        max_results_per_source: int | None = None,
        progress_callback: callable | None = None,
    ) -> dict[str, object]:
        observed["selected_platforms"] = tuple(selected_platforms)
        observed["property_search_preferences"] = dict(property_search_preferences or {})
        return {
            "generated_at": product_service._now_iso(),
            "status": "processed",
            "sources_total": 1,
            "listing_total": 1,
            "review_created_total": 1,
            "review_existing_total": 0,
            "notified_total": 0,
            "tour_created_total": 0,
            "tour_existing_total": 0,
            "high_fit_total": 0,
            "watch_notified_total": 0,
            "sources": [],
        }

    monkeypatch.setattr(ProductService, "sync_direct_property_scout", _fake_sync_direct_property_scout)

    started = client.post("/app/api/signals/property/search/run", json={"property_preferences": {}})
    assert started.status_code == 200, started.text
    assert set(observed.get("selected_platforms") or ()) == {"rightmove", "zoopla", "onthemarket"}
    assert observed["property_search_preferences"]["country_code"] == "UK"
    assert observed["property_search_preferences"]["location_query"] == "London"
