from __future__ import annotations

import logging
from types import SimpleNamespace

from app import runner
from app.product.service import ProductService


def test_scheduler_property_scout_requires_flat_search_enabled(monkeypatch: object) -> None:
    monkeypatch.setenv("EA_ASSISTANT_PROPERTY_LANE_ENABLED", "1")
    monkeypatch.setenv("EA_DEPLOY_PRIMARY_MODE", "PROPERTY")
    monkeypatch.setenv("PROPERTYQUARRY_DEFAULT_BRAND", "1")
    monkeypatch.setenv("PROPERTYQUARRY_SCHEDULER_PROFILE", "property")
    monkeypatch.setenv("EA_PROACTIVE_OODA_FLAT_SEARCH_ENABLED", "0")
    monkeypatch.setenv("EA_SCHEDULER_PROPERTY_SCOUT_ENABLED", "1")

    assert runner._scheduler_property_scout_enabled() is False


def test_scheduler_property_scout_requires_scheduler_flag(monkeypatch: object) -> None:
    monkeypatch.setenv("EA_ASSISTANT_PROPERTY_LANE_ENABLED", "1")
    monkeypatch.setenv("EA_DEPLOY_PRIMARY_MODE", "PROPERTY")
    monkeypatch.setenv("PROPERTYQUARRY_DEFAULT_BRAND", "1")
    monkeypatch.setenv("PROPERTYQUARRY_SCHEDULER_PROFILE", "property")
    monkeypatch.setenv("EA_PROACTIVE_OODA_FLAT_SEARCH_ENABLED", "1")
    monkeypatch.setenv("EA_SCHEDULER_PROPERTY_SCOUT_ENABLED", "0")

    assert runner._scheduler_property_scout_enabled() is False


def test_scheduler_property_scout_requires_propertyquarry_profile(monkeypatch: object) -> None:
    monkeypatch.setenv("EA_ASSISTANT_PROPERTY_LANE_ENABLED", "1")
    monkeypatch.setenv("EA_DEPLOY_PRIMARY_MODE", "PROPERTY")
    monkeypatch.setenv("PROPERTYQUARRY_DEFAULT_BRAND", "1")
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
    monkeypatch.setenv("EA_DEPLOY_PRIMARY_MODE", "PROPERTY")
    monkeypatch.setenv("PROPERTYQUARRY_DEFAULT_BRAND", "1")
    monkeypatch.setenv("PROPERTYQUARRY_SCHEDULER_PROFILE", "property")
    monkeypatch.setenv("EA_PROACTIVE_OODA_DISABLE_FLAT_SEARCH", "0")
    monkeypatch.setenv("EA_PROACTIVE_OODA_FLAT_SEARCH_ENABLED", "1")
    monkeypatch.setenv("EA_SCHEDULER_PROPERTY_SCOUT_ENABLED", "1")

    assert runner._scheduler_property_scout_enabled() is True


def test_scheduler_property_scout_disabled_when_flat_search_is_disallowed(monkeypatch: object) -> None:
    monkeypatch.setenv("EA_ASSISTANT_PROPERTY_LANE_ENABLED", "1")
    monkeypatch.setenv("EA_DEPLOY_PRIMARY_MODE", "PROPERTY")
    monkeypatch.setenv("PROPERTYQUARRY_DEFAULT_BRAND", "1")
    monkeypatch.setenv("PROPERTYQUARRY_SCHEDULER_PROFILE", "property")
    monkeypatch.setenv("EA_PROACTIVE_OODA_DISABLE_FLAT_SEARCH", "1")
    monkeypatch.setenv("EA_PROACTIVE_OODA_FLAT_SEARCH_ENABLED", "1")
    monkeypatch.setenv("EA_SCHEDULER_PROPERTY_SCOUT_ENABLED", "1")

    assert runner._scheduler_property_scout_enabled() is False


def test_scheduler_property_alert_accounts_require_property_runtime_profile(monkeypatch: object) -> None:
    monkeypatch.setenv("EA_ASSISTANT_PROPERTY_LANE_ENABLED", "1")
    monkeypatch.setenv("EA_DEPLOY_PRIMARY_MODE", "PROPERTY")
    monkeypatch.setenv("PROPERTYQUARRY_DEFAULT_BRAND", "1")
    monkeypatch.setenv("EA_PROPERTY_ALERT_ACCOUNT_EMAILS", "alerts@example.com")
    monkeypatch.delenv("PROPERTYQUARRY_SCHEDULER_PROFILE", raising=False)
    monkeypatch.delenv("PROPERTYQUARRY_WORKER_PROFILE", raising=False)

    assert runner._scheduler_property_alert_account_emails() == ()


def test_scheduler_property_scout_stays_disabled_without_propertyquarry_brand(monkeypatch: object) -> None:
    monkeypatch.setenv("EA_ASSISTANT_PROPERTY_LANE_ENABLED", "1")
    monkeypatch.setenv("EA_DEPLOY_PRIMARY_MODE", "PROPERTY")
    monkeypatch.delenv("PROPERTYQUARRY_DEFAULT_BRAND", raising=False)
    monkeypatch.setenv("PROPERTYQUARRY_SCHEDULER_PROFILE", "property")
    monkeypatch.setenv("EA_PROACTIVE_OODA_FLAT_SEARCH_ENABLED", "1")
    monkeypatch.setenv("EA_SCHEDULER_PROPERTY_SCOUT_ENABLED", "1")

    assert runner._scheduler_property_scout_enabled() is False


def test_scheduler_property_scout_stays_disabled_in_mixed_deploy_modes(monkeypatch: object) -> None:
    monkeypatch.setenv("EA_ASSISTANT_PROPERTY_LANE_ENABLED", "1")
    monkeypatch.setenv("EA_DEPLOY_ENABLED_MODES", "EA_CORE,PROPERTY")
    monkeypatch.setenv("PROPERTYQUARRY_DEFAULT_BRAND", "1")
    monkeypatch.setenv("PROPERTYQUARRY_SCHEDULER_PROFILE", "property")
    monkeypatch.setenv("EA_PROACTIVE_OODA_FLAT_SEARCH_ENABLED", "1")
    monkeypatch.setenv("EA_SCHEDULER_PROPERTY_SCOUT_ENABLED", "1")

    assert runner._scheduler_property_scout_enabled() is False


def test_scheduler_property_scout_stays_disabled_without_explicit_property_deploy_mode(monkeypatch: object) -> None:
    monkeypatch.setenv("EA_ASSISTANT_PROPERTY_LANE_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_DEFAULT_BRAND", "1")
    monkeypatch.setenv("PROPERTYQUARRY_SCHEDULER_PROFILE", "property")
    monkeypatch.delenv("EA_DEPLOY_PRIMARY_MODE", raising=False)
    monkeypatch.delenv("EA_DEPLOY_PROJECT_MODE", raising=False)
    monkeypatch.delenv("EA_DEPLOY_ENABLED_MODES", raising=False)
    monkeypatch.setenv("EA_PROACTIVE_OODA_FLAT_SEARCH_ENABLED", "1")
    monkeypatch.setenv("EA_SCHEDULER_PROPERTY_SCOUT_ENABLED", "1")

    assert runner._scheduler_property_scout_enabled() is False


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


def test_assistant_property_boundary_cleanup_skips_when_lane_enabled(monkeypatch: object) -> None:
    monkeypatch.setenv("EA_ASSISTANT_PROPERTY_LANE_ENABLED", "1")
    monkeypatch.setenv("EA_DEPLOY_PRIMARY_MODE", "PROPERTY")
    monkeypatch.setenv("PROPERTYQUARRY_DEFAULT_BRAND", "1")
    monkeypatch.setenv("PROPERTYQUARRY_SCHEDULER_PROFILE", "property")

    container = SimpleNamespace(
        settings=SimpleNamespace(auth=SimpleNamespace(default_principal_id="principal-1")),
        tool_runtime=SimpleNamespace(list_connector_bindings_for_connector=lambda *args, **kwargs: []),
    )

    result = runner._run_scheduler_assistant_property_boundary_cleanup(container, logging.getLogger("test"))

    assert result["ran"] is False
    assert result["reason"] == "assistant_property_lane_enabled"


def test_assistant_property_boundary_cleanup_archives_runtime_and_closes_hidden_tasks(monkeypatch: object) -> None:
    import app.product.service as product_service_module
    import app.services.assistant_property_boundary_cleanup as cleanup_module

    monkeypatch.delenv("EA_ASSISTANT_PROPERTY_LANE_ENABLED", raising=False)
    monkeypatch.delenv("EA_DEPLOY_PRIMARY_MODE", raising=False)
    monkeypatch.delenv("EA_DEPLOY_ENABLED_MODES", raising=False)
    monkeypatch.delenv("EA_DEFAULT_PRINCIPAL_ID", raising=False)
    monkeypatch.delenv("EA_TELEGRAM_DEFAULT_PRINCIPAL_ID", raising=False)

    cleanup_calls: list[tuple[str, str]] = []

    class _CleanupService:
        def cleanup_hidden_property_tasks(self, *, principal_id: str, actor: str) -> dict[str, object]:
            cleanup_calls.append((principal_id, actor))
            return {"closed_total": 2, "skipped_total": 1}

    monkeypatch.setattr(
        cleanup_module,
        "cleanup_hidden_property_runtime_state",
        lambda **kwargs: {
            "archived_total": 3,
            "stage_packet_total": 1,
            "safe_work_result_total": 1,
            "approval_callback_total": 1,
        },
    )
    monkeypatch.setattr(product_service_module, "build_product_service", lambda container: _CleanupService())

    container = SimpleNamespace(
        settings=SimpleNamespace(auth=SimpleNamespace(default_principal_id="principal-1")),
        tool_runtime=SimpleNamespace(
            list_connector_bindings_for_connector=lambda connector_name, limit=1000: [
                SimpleNamespace(principal_id="principal-1", status="enabled"),
                SimpleNamespace(principal_id="principal-2", status="enabled"),
            ]
        ),
    )

    result = runner._run_scheduler_assistant_property_boundary_cleanup(container, logging.getLogger("test"))

    assert result["ran"] is True
    assert result["archived_total"] == 3
    assert result["task_cleanup_attempted"] == 2
    assert result["task_cleanup_closed"] == 4
    assert result["task_cleanup_skipped"] == 2
    assert result["errors"] == 0
    assert cleanup_calls == [("principal-1", "scheduler"), ("principal-2", "scheduler")]
