from __future__ import annotations
from app.services.proactive_signal_discovery import observation_row_to_signal


def _telegram_message_signal(*, text: str, created_at: str = "2026-06-30T12:00:00+00:00") -> object | None:
    return observation_row_to_signal(
        observation_id="obs-test",
        principal_id="principal-1",
        channel="telegram",
        event_type="telegram.message",
        payload={
            "text": text,
            "analysis_summary": text,
            "chat_id": "1200",
            "message_id": "77",
        },
        created_at=created_at,
        source_id="telegram:1200",
        external_id="77",
        dedupe_key="telegram:1200:77",
    )


def _property_scout_signal(*, payload: dict) -> object | None:
    return observation_row_to_signal(
        observation_id="obs-property-scout",
        principal_id="principal-1",
        channel="product",
        event_type="property_scout_sync_completed",
        payload=payload,
        created_at="2026-06-30T12:00:00+00:00",
        source_id="property-scout",
        external_id="psc-1",
        dedupe_key="psc-1",
    )


def test_property_scout_signal_is_dropped_when_flat_search_disabled(monkeypatch: object) -> None:
    monkeypatch.setenv("EA_PROACTIVE_OODA_PROPERTY_SCOUT_SIGNALS_ENABLED", "1")
    monkeypatch.setenv("EA_PROACTIVE_OODA_FLAT_SEARCH_ENABLED", "0")
    signal = _property_scout_signal(
        payload={
            "status": "completed",
            "scanned_listing_total": 12,
            "filtered_low_fit_total": 12,
            "sources": [
                {
                    "source_url": "https://example.com/listings",
                    "source_label": "FlatScout",
                    "scanned_listing_total": 12,
                    "filtered_low_fit_total": 12,
                }
            ],
        }
    )
    assert signal is None


def test_transcript_flat_property_query_is_ignored() -> None:
    signal = _telegram_message_signal(text="suche mir bitte eine 2 Zimmer Wohnung in 1200 Wien")
    assert signal is None


def test_transcript_flat_property_query_is_ignored_when_flat_search_is_disabled_explicitly(monkeypatch: object) -> None:
    monkeypatch.setenv("EA_PROACTIVE_OODA_DISABLE_FLAT_SEARCH", "1")
    signal = _telegram_message_signal(text="Find me an apartment in Vienna and compare prices")
    assert signal is None


def test_transcript_non_flat_query_is_unchanged() -> None:
    signal = _telegram_message_signal(text="Suche mir bitte einen Rauchfangkehrer für mein Klimagerät.")
    assert signal is not None
    assert signal.signal_type == "telegram_message"


def test_transcript_zimmer_query_is_not_flat_property() -> None:
    signal = _telegram_message_signal(text="Suche mir bitte einen Vorhang für mein Wohnzimmer in 1200 Wien.")
    assert signal is not None
    assert signal.signal_type == "telegram_message"


def test_transcript_flat_search_query_in_english_is_ignored() -> None:
    signal = _telegram_message_signal(text="Find me an apartment in 1200 Vienna please")
    assert signal is None


def test_transcript_property_candidate_search_is_ignored() -> None:
    signal = _telegram_message_signal(text="Compare the two best property candidates.")
    assert signal is None


def test_transcript_generic_purchase_query_is_not_flat_property() -> None:
    signal = _telegram_message_signal(text="Kauf bitte Blumen für meine Frau und such einen guten Anbieter.")
    assert signal is not None
    assert signal.signal_type == "telegram_message"


def test_transcript_recording_studio_query_is_not_flat_property() -> None:
    signal = _telegram_message_signal(text="Book a recording studio for next week and compare options.")
    assert signal is not None
    assert signal.signal_type == "telegram_message"


def test_transcript_house_purchase_query_is_ignored_when_flat_search_disabled() -> None:
    signal = _telegram_message_signal(text="Suche mir ein Haus zum Kaufen in Wien.")
    assert signal is None
