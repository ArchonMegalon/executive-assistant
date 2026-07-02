from __future__ import annotations

from types import SimpleNamespace

from app import runner
from app.product.service import ProductService


def test_scheduler_property_scout_requires_flat_search_enabled(monkeypatch: object) -> None:
    monkeypatch.setenv("EA_ASSISTANT_PROPERTY_LANE_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_SCHEDULER_PROFILE", "property")
    monkeypatch.setenv("EA_PROACTIVE_OODA_FLAT_SEARCH_ENABLED", "0")
    monkeypatch.setenv("EA_SCHEDULER_PROPERTY_SCOUT_ENABLED", "1")

    assert runner._scheduler_property_scout_enabled() is False


def test_scheduler_property_scout_requires_scheduler_flag(monkeypatch: object) -> None:
    monkeypatch.setenv("EA_ASSISTANT_PROPERTY_LANE_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_SCHEDULER_PROFILE", "property")
    monkeypatch.setenv("EA_PROACTIVE_OODA_FLAT_SEARCH_ENABLED", "1")
    monkeypatch.setenv("EA_SCHEDULER_PROPERTY_SCOUT_ENABLED", "0")

    assert runner._scheduler_property_scout_enabled() is False


def test_scheduler_property_scout_requires_propertyquarry_profile(monkeypatch: object) -> None:
    monkeypatch.setenv("EA_ASSISTANT_PROPERTY_LANE_ENABLED", "1")
    monkeypatch.delenv("PROPERTYQUARRY_SCHEDULER_PROFILE", raising=False)
    monkeypatch.setenv("EA_PROACTIVE_OODA_FLAT_SEARCH_ENABLED", "1")
    monkeypatch.setenv("EA_SCHEDULER_PROPERTY_SCOUT_ENABLED", "1")

    assert runner._scheduler_property_scout_enabled() is False


def test_scheduler_property_scout_stays_disabled_without_assistant_property_lane(monkeypatch: object) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_SCHEDULER_PROFILE", "property")
    monkeypatch.setenv("EA_PROACTIVE_OODA_FLAT_SEARCH_ENABLED", "1")
    monkeypatch.setenv("EA_SCHEDULER_PROPERTY_SCOUT_ENABLED", "1")

    assert runner._scheduler_property_scout_enabled() is False


def test_scheduler_property_scout_enabled_only_with_boundary_and_flags(monkeypatch: object) -> None:
    monkeypatch.setenv("EA_ASSISTANT_PROPERTY_LANE_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_SCHEDULER_PROFILE", "property")
    monkeypatch.setenv("EA_PROACTIVE_OODA_DISABLE_FLAT_SEARCH", "0")
    monkeypatch.setenv("EA_PROACTIVE_OODA_FLAT_SEARCH_ENABLED", "1")
    monkeypatch.setenv("EA_SCHEDULER_PROPERTY_SCOUT_ENABLED", "1")

    assert runner._scheduler_property_scout_enabled() is True


def test_scheduler_property_scout_disabled_when_flat_search_is_disallowed(monkeypatch: object) -> None:
    monkeypatch.setenv("EA_ASSISTANT_PROPERTY_LANE_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_SCHEDULER_PROFILE", "property")
    monkeypatch.setenv("EA_PROACTIVE_OODA_DISABLE_FLAT_SEARCH", "1")
    monkeypatch.setenv("EA_PROACTIVE_OODA_FLAT_SEARCH_ENABLED", "1")
    monkeypatch.setenv("EA_SCHEDULER_PROPERTY_SCOUT_ENABLED", "1")

    assert runner._scheduler_property_scout_enabled() is False


def test_scheduler_property_alert_accounts_require_property_runtime_profile(monkeypatch: object) -> None:
    monkeypatch.setenv("EA_ASSISTANT_PROPERTY_LANE_ENABLED", "1")
    monkeypatch.setenv("EA_PROPERTY_ALERT_ACCOUNT_EMAILS", "alerts@example.com")
    monkeypatch.delenv("PROPERTYQUARRY_SCHEDULER_PROFILE", raising=False)
    monkeypatch.delenv("PROPERTYQUARRY_WORKER_PROFILE", raising=False)

    assert runner._scheduler_property_alert_account_emails() == ()


def test_sync_direct_property_scout_is_blocked_when_flat_search_is_disabled_by_kill_switch(monkeypatch: object) -> None:
    monkeypatch.setenv("EA_PROACTIVE_OODA_DISABLE_FLAT_SEARCH", "1")
    monkeypatch.setenv("EA_PROACTIVE_OODA_FLAT_SEARCH_ENABLED", "1")

    service = ProductService(SimpleNamespace(preference_profiles=SimpleNamespace()))
    payload = service.sync_direct_property_scout(principal_id="principal", actor="test")

    assert payload["status"] == "disabled"
    assert payload["sources_total"] == 0


def test_sync_direct_property_scout_is_blocked_when_flat_search_feature_is_not_enabled(monkeypatch: object) -> None:
    monkeypatch.setenv("EA_PROACTIVE_OODA_DISABLE_FLAT_SEARCH", "0")
    monkeypatch.setenv("EA_PROACTIVE_OODA_FLAT_SEARCH_ENABLED", "0")

    service = ProductService(SimpleNamespace(preference_profiles=SimpleNamespace()))
    payload = service.sync_direct_property_scout(principal_id="principal", actor="test")

    assert payload["status"] == "disabled"
    assert payload["sources_total"] == 0


def test_start_property_search_run_is_blocked_when_flat_search_disabled(monkeypatch: object) -> None:
    monkeypatch.setenv("EA_PROACTIVE_OODA_DISABLE_FLAT_SEARCH", "1")
    monkeypatch.setenv("EA_PROACTIVE_OODA_FLAT_SEARCH_ENABLED", "1")

    service = ProductService(SimpleNamespace(preference_profiles=SimpleNamespace()))
    payload = service.start_property_search_run(
        principal_id="principal",
        actor="test",
        selected_platforms=(),
        property_search_preferences={},
        force_refresh=False,
        max_results_per_source=None,
    )

    assert payload["status"] == "disabled"
    assert payload["run_id"] == ""
    assert "Flat-search feature is disabled" in str(payload.get("message") or "")
