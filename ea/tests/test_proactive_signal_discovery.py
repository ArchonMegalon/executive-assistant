from __future__ import annotations

import json
from pathlib import Path
from app.services import proactive_signal_discovery
from app.services.proactive_signal_discovery import SignalSource, observation_row_to_signal


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


def test_property_scout_signal_is_always_dropped_from_ea(monkeypatch: object) -> None:
    monkeypatch.setenv("EA_PROACTIVE_OODA_PROPERTY_SCOUT_SIGNALS_ENABLED", "1")
    monkeypatch.setenv("EA_PROACTIVE_OODA_FLAT_SEARCH_ENABLED", "1")
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


def test_transcript_flat_property_query_is_ignored_even_when_feature_flag_is_on(monkeypatch: object) -> None:
    monkeypatch.setenv("EA_PROACTIVE_OODA_FLAT_SEARCH_ENABLED", "1")
    signal = _telegram_message_signal(text="Find me an apartment in 1200 Vienna and compare the best ones")
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


def test_transcript_search_query_expansion_ignores_ambient_context_terms() -> None:
    queries = proactive_signal_discovery._search_queries_from_request(
        research_query="Elektriker fuer zusaetzliche Steckdosen",
        request_text=(
            "[Mikrofongeraeusche] Also ich bin ein bisschen nervoes. "
            "Ich bin entlassen worden. Suche einen Elektriker fuer zusaetzliche Steckdosen."
        ),
    )

    assert queries == ["Elektriker fuer zusaetzliche Steckdosen"]


def test_office_signal_property_scout_ooda_is_ignored_from_ea_loop() -> None:
    signal = observation_row_to_signal(
        observation_id="obs-property-ooda",
        principal_id="principal-1",
        channel="product",
        event_type="office_signal_ooda_evaluated",
        payload={
            "summary": "Property scout found items to review.",
            "counterparty": "Property Scout",
            "signal_type": "office_signal",
            "ooda_loop": {
                "summary": "Property scout found items to review.",
                "observe": {
                    "summary": "Apartment alert: 2 Zimmer Wohnung in 1200 Wien",
                    "counterparty": "Property Scout",
                    "signal_type": "property_scout",
                },
            },
        },
        created_at="2026-07-02T12:00:00+00:00",
        source_id="property-scout-sync:principal-1",
        external_id="property-scout-sync",
        dedupe_key="property-scout-sync",
    )

    assert signal is None


def test_office_signal_with_flat_property_summary_without_explicit_markers_is_ignored() -> None:
    signal = observation_row_to_signal(
        observation_id="obs-property-ooda-wohnung",
        principal_id="principal-1",
        channel="product",
        event_type="office_signal_ooda_evaluated",
        payload={
            "summary": "2 Zimmer Wohnung in 1200 Wien vergleichen und entscheiden.",
            "counterparty": "Wohnungssuche",
            "signal_type": "office_signal",
            "ooda_loop": {
                "summary": "Ziel: Wohnung in 1200 Wien",
                "observe": {
                    "summary": "2 Zimmer Wohnung in 1200 Wien",
                    "counterparty": "Wohnungssuche",
                    "signal_type": "research_task",
                },
            },
        },
        created_at="2026-07-02T12:00:00+00:00",
        source_id="office-signal:1",
        external_id="office-signal-wohnung",
        dedupe_key="office-signal-wohnung",
    )

    assert signal is None


def test_signal_from_row_is_ignored_when_row_mentions_flat_property() -> None:
    source = SignalSource(source_type="json", ref="/tmp/test.json")
    signal = proactive_signal_discovery._signal_from_row(
        {
            "title": "Wohnung suchen",
            "summary": "2 Zimmer Wohnung in 1200 Wien vergleichen.",
            "counterparty": "PropertyScout",
        },
        source=source,
        index=0,
    )

    assert signal is None


def test_signal_from_teable_record_is_ignored_when_record_mentions_flat_property() -> None:
    source = SignalSource(source_type="teable", ref="table-123")
    signal = proactive_signal_discovery._signal_from_teable_record(
        {
            "title": "Wohnungssuche",
            "summary": "Apartment in 1200 Wien gefunden.",
            "counterparty": "PropertyScout",
        },
        record_id="row-1",
        source=source,
    )

    assert signal is None


def test_load_json_source_filters_property_rows_before_signal_materialization(tmp_path: Path) -> None:
    source_path = tmp_path / "signals.json"
    source_path.write_text(
        json.dumps(
            {
                "signals": [
                    {
                        "title": "Wohnung in 1200 Wien",
                        "summary": "Apartment candidate found.",
                        "counterparty": "PropertyScout",
                    },
                    {
                        "title": "Rauchfangkehrer Termin",
                        "summary": "Vergleichsmailing to electrician?",
                        "counterparty": "Support",
                    },
                ]
            }
        )
    )
    source = SignalSource(source_type="json", ref=str(source_path))

    signals = proactive_signal_discovery._load_json_source(source, base_dir=Path("/"), timeout_seconds=20)

    assert len(signals) == 1
    assert signals[0].title == "Rauchfangkehrer Termin"
