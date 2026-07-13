from __future__ import annotations

from types import SimpleNamespace

from app.product.service import ProductService
from app.services.assistant_property_lane import (
    assistant_property_lane_enabled,
    assistant_property_signal_present,
)
from app.services.proactive_ooda_flat_search_policy import material_mentions_flat_property_search


def _product_service() -> ProductService:
    container = SimpleNamespace(
        preference_profiles=SimpleNamespace(),
        channel_runtime=SimpleNamespace(
            find_observation_by_dedupe=lambda *args, **kwargs: None,
            ingest_observation=lambda **kwargs: SimpleNamespace(
                observation_id="obs-1",
                channel=kwargs.get("channel", ""),
                event_type=kwargs.get("event_type", ""),
                source_id=kwargs.get("source_id", ""),
                external_id=kwargs.get("external_id", ""),
                created_at="2026-07-02T12:00:00Z",
                payload=kwargs.get("payload", {}),
            ),
            list_recent_observations=lambda **kwargs: [],
        ),
    )
    service = ProductService(container)
    service._record_product_event = lambda **kwargs: None  # type: ignore[method-assign]
    return service


def test_sync_google_willhaben_signals_is_disabled_for_ea_by_default(monkeypatch: object) -> None:
    monkeypatch.delenv("EA_ASSISTANT_PROPERTY_LANE_ENABLED", raising=False)
    service = _product_service()

    payload = service.sync_google_willhaben_signals(
        principal_id="principal-1",
        actor="test",
        account_email="alerts@example.com",
    )

    assert payload["status"] == "disabled"
    assert payload["reason"] == "property_search_not_available"
    assert payload["product_boundary"] == "propertyquarry"
    assert payload["total"] == 0


def test_sync_google_willhaben_signals_stays_disabled_without_property_runtime_profile(monkeypatch: object) -> None:
    monkeypatch.setenv("EA_ASSISTANT_PROPERTY_LANE_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_DEFAULT_BRAND", "1")
    monkeypatch.delenv("PROPERTYQUARRY_SCHEDULER_PROFILE", raising=False)
    monkeypatch.delenv("PROPERTYQUARRY_WORKER_PROFILE", raising=False)
    service = _product_service()

    payload = service.sync_google_willhaben_signals(
        principal_id="principal-1",
        actor="test",
        account_email="alerts@example.com",
    )

    assert payload["status"] == "disabled"
    assert payload["reason"] == "property_search_not_available"
    assert payload["product_boundary"] == "propertyquarry"


def test_property_lane_stays_disabled_in_mixed_deploy_modes(monkeypatch: object) -> None:
    monkeypatch.setenv("EA_ASSISTANT_PROPERTY_LANE_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_DEFAULT_BRAND", "1")
    monkeypatch.setenv("PROPERTYQUARRY_SCHEDULER_PROFILE", "property")
    monkeypatch.setenv("EA_DEPLOY_ENABLED_MODES", "EA_CORE,PROPERTY")

    assert assistant_property_lane_enabled() is False


def test_property_lane_stays_disabled_without_explicit_property_deploy_mode(monkeypatch: object) -> None:
    monkeypatch.setenv("EA_ASSISTANT_PROPERTY_LANE_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_DEFAULT_BRAND", "1")
    monkeypatch.setenv("PROPERTYQUARRY_SCHEDULER_PROFILE", "property")
    monkeypatch.delenv("EA_DEPLOY_PRIMARY_MODE", raising=False)
    monkeypatch.delenv("EA_DEPLOY_PROJECT_MODE", raising=False)
    monkeypatch.delenv("EA_DEPLOY_ENABLED_MODES", raising=False)

    assert assistant_property_lane_enabled() is False


def test_property_lane_stays_disabled_even_for_legacy_property_primary_mode(monkeypatch: object) -> None:
    monkeypatch.setenv("EA_ASSISTANT_PROPERTY_LANE_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_DEFAULT_BRAND", "1")
    monkeypatch.setenv("PROPERTYQUARRY_SCHEDULER_PROFILE", "property")
    monkeypatch.setenv("EA_DEPLOY_PRIMARY_MODE", "PROPERTY")

    assert assistant_property_lane_enabled() is False


def test_ingest_office_signal_marks_property_alert_email_ignored(monkeypatch: object) -> None:
    monkeypatch.delenv("EA_ASSISTANT_PROPERTY_LANE_ENABLED", raising=False)
    service = _product_service()

    payload = service.ingest_office_signal(
        principal_id="principal-1",
        signal_type="email_thread",
        channel="gmail",
        title="Willhaben Suchagent: Neue Anzeige in Wien",
        summary="Neue Anzeige fuer deine Suche.",
        counterparty="Willhaben Suchagent",
        source_ref="gmail:thread-1",
        external_id="thread-1",
        payload={
            "from_email": "no-reply@agent.willhaben.at",
            "from_name": "Willhaben Suchagent",
        },
        actor="test",
    )

    assert payload["ignored"] is True
    assert payload["ignore_reason"] == "property_search_not_available"
    assert payload["product_boundary"] == "propertyquarry"
    assert payload["staged_count"] == 0
    assert payload["draft_count"] == 0


def test_ingest_office_signal_property_alert_stays_ignored_without_property_runtime_profile(monkeypatch: object) -> None:
    monkeypatch.setenv("EA_ASSISTANT_PROPERTY_LANE_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_DEFAULT_BRAND", "1")
    monkeypatch.delenv("PROPERTYQUARRY_SCHEDULER_PROFILE", raising=False)
    monkeypatch.delenv("PROPERTYQUARRY_WORKER_PROFILE", raising=False)
    service = _product_service()

    payload = service.ingest_office_signal(
        principal_id="principal-1",
        signal_type="email_thread",
        channel="gmail",
        title="Willhaben Suchagent: Neue Anzeige in Wien",
        summary="Neue Anzeige fuer deine Suche.",
        counterparty="Willhaben Suchagent",
        source_ref="gmail:thread-2",
        external_id="thread-2",
        payload={
            "from_email": "no-reply@agent.willhaben.at",
            "from_name": "Willhaben Suchagent",
        },
        actor="test",
    )

    assert payload["ignored"] is True
    assert payload["ignore_reason"] == "property_search_not_available"
    assert payload["product_boundary"] == "propertyquarry"


def test_property_alert_ingest_stays_disabled_without_propertyquarry_brand(monkeypatch: object) -> None:
    monkeypatch.setenv("EA_ASSISTANT_PROPERTY_LANE_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_SCHEDULER_PROFILE", "property")
    monkeypatch.delenv("PROPERTYQUARRY_DEFAULT_BRAND", raising=False)
    service = _product_service()

    payload = service.ingest_office_signal(
        principal_id="principal-1",
        signal_type="email_thread",
        channel="gmail",
        title="Willhaben Suchagent: Neue Anzeige in Wien",
        summary="Neue Anzeige fuer deine Suche.",
        counterparty="Willhaben Suchagent",
        source_ref="gmail:thread-3",
        external_id="thread-3",
        payload={
            "from_email": "no-reply@agent.willhaben.at",
            "from_name": "Willhaben Suchagent",
        },
        actor="test",
    )

    assert payload["ignored"] is True
    assert payload["ignore_reason"] == "property_search_not_available"
    assert payload["product_boundary"] == "propertyquarry"


def test_assistant_property_signal_present_catches_freeform_apartment_request() -> None:
    assert (
        assistant_property_signal_present("Kannst du mir eine Wohnung in 1200 Wien suchen?")
        is True
    )


def test_assistant_property_signal_present_does_not_treat_recording_studio_as_property() -> None:
    assert (
        assistant_property_signal_present("Book a recording studio for next week and compare options.")
        is False
    )


def test_assistant_property_signal_present_catches_connector_tokens() -> None:
    assert assistant_property_signal_present("flat_candidate_waiting") is True
    assert assistant_property_signal_present("apartment_search_pending") is True


def test_assistant_property_signal_present_ignores_structured_metadata_keys() -> None:
    assert (
        assistant_property_signal_present(
            {
                "observe": {"property_url": "", "summary": "Confirm the board memo owner."},
                "decide": {"recommended_actions": ["stage_commitment_candidates"]},
            }
        )
        is False
    )


def test_assistant_property_signal_present_checks_structured_material_values() -> None:
    assert (
        assistant_property_signal_present(
            {
                "observe": {"property_url": "", "summary": "Search for an apartment in Vienna."},
            }
        )
        is True
    )


def test_flat_search_policy_ignores_structured_runtime_key_names() -> None:
    assert (
        material_mentions_flat_property_search(
            {
                "flat_search_enabled": False,
                "approval_callback_property_scoped_pending_count": 0,
                "artifact_filter_reason": "",
            }
        )
        is False
    )


def test_flat_search_policy_catches_structured_connector_values() -> None:
    assert material_mentions_flat_property_search({"state": "apartment_search_pending"}) is True
