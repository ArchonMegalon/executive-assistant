from __future__ import annotations

from types import SimpleNamespace

from app.product.service import ProductService


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
