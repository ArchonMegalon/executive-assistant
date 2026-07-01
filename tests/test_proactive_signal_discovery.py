from __future__ import annotations

import json
import sys
from io import BytesIO

from app.services import proactive_signal_discovery as signal_discovery
from app.services.proactive_ooda_safe_work import build_safe_work_result
from app.services.proactive_ooda_service import JsonOodaStateStore, ProactiveOodaService
from app.services.proactive_ooda_stage_packets import build_stage_packets
from app.services.proactive_signal_discovery import (
    discover_opportunity_rule_signals,
    discover_signals,
    discover_signals_resilient,
    discover_postgres_observation_signals,
    load_signal_sources_config,
    observation_row_to_signal,
)


def test_discovery_loads_json_sources_into_proactive_signals(tmp_path) -> None:
    signal_file = tmp_path / "signals.json"
    signal_file.write_text(
        json.dumps(
            [
                {
                    "title": "Decision needed today",
                    "summary": "Approve the launch budget.",
                    "counterparty": "Launch",
                }
            ]
        ),
        encoding="utf-8",
    )
    sources = load_signal_sources_config(
        json.dumps(
            [
                {
                    "type": "json",
                    "path": str(signal_file),
                    "channel": "operator_feed",
                    "signal_type": "operator_signal",
                }
            ]
        )
    )

    signals = discover_signals(sources=sources, base_dir=tmp_path)

    assert len(signals) == 1
    assert signals[0].channel == "operator_feed"
    assert signals[0].signal_type == "operator_signal"
    assert signals[0].source_ref.startswith("operator_feed:")


def test_discovery_loads_rss_sources_into_proactive_signals(tmp_path) -> None:
    feed = tmp_path / "feed.xml"
    feed.write_text(
        """<?xml version="1.0"?>
<rss><channel><item>
<title>Provider risk deadline today</title>
<link>https://example.test/risk</link>
<description>Review the provider before renewal.</description>
<pubDate>Sat, 20 Jun 2026 09:00:00 GMT</pubDate>
</item></channel></rss>
""",
        encoding="utf-8",
    )
    sources = load_signal_sources_config(
        json.dumps({"sources": [{"path": str(feed), "channel": "market_watch", "counterparty": "RSS"}]})
    )

    signals = discover_signals(sources=sources, base_dir=tmp_path)

    assert len(signals) == 1
    assert signals[0].title == "Provider risk deadline today"
    assert signals[0].external_id == "https://example.test/risk"
    assert signals[0].counterparty == "RSS"


def test_discovery_loads_teable_records_with_field_map(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps(
                {
                    "records": [
                        {
                            "id": "rec_1",
                            "fields": {
                                "Task": "Budget approval today",
                                "Brief": "Approve the LTD renewal before the deadline.",
                                "Owner": "Ops",
                                "Due": "2026-06-20T18:00:00+02:00",
                            },
                        }
                    ]
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["auth"] = request.headers.get("Authorization")
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setenv("TEABLE_API_KEY", "test-key")
    monkeypatch.setenv("TEABLE_BASE_URL", "https://teable.example")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    sources = load_signal_sources_config(
        json.dumps(
            {
                "sources": [
                    {
                        "type": "teable",
                        "ref": "tbl_exec",
                        "channel": "teable_admin",
                        "signal_type": "admin_signal",
                        "field_map": {
                            "title": "Task",
                            "summary": "Brief",
                            "counterparty": "Owner",
                            "due_at": "Due",
                        },
                    }
                ]
            }
        )
    )

    signals = discover_signals(sources=sources, base_dir=tmp_path, timeout_seconds=7)

    assert len(signals) == 1
    assert signals[0].source_ref == "teable_admin:teable:tbl_exec:rec_1"
    assert signals[0].signal_type == "admin_signal"
    assert signals[0].channel == "teable_admin"
    assert signals[0].title == "Budget approval today"
    assert signals[0].summary == "Approve the LTD renewal before the deadline."
    assert signals[0].counterparty == "Ops"
    assert signals[0].due_at == "2026-06-20T18:00:00+02:00"
    assert captured["url"] == "https://teable.example/api/table/tbl_exec/record?fieldKeyType=name&cellFormat=json&take=20&skip=0"
    assert captured["auth"] == "Bearer test-key"
    assert captured["timeout"] == 7


def test_discovery_infers_teable_source_from_table_id(monkeypatch, tmp_path) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return BytesIO(
                json.dumps(
                    {
                        "records": [
                            {
                                "id": "rec_inferred",
                                "fields": {
                                    "title": "Reply needed",
                                    "summary": "Follow up with the accountant today.",
                                },
                            }
                        ]
                    }
                ).encode("utf-8")
            ).read()

    monkeypatch.setenv("TEABLE_API_KEY", "test-key")
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    sources = load_signal_sources_config(json.dumps([{"ref": "tbl_inferred", "channel": "ops"}]))

    signals = discover_signals(sources=sources, base_dir=tmp_path)

    assert len(signals) == 1
    assert signals[0].channel == "ops"
    assert signals[0].title == "Reply needed"
    assert signals[0].external_id == "rec_inferred"


def test_resilient_discovery_keeps_good_sources_and_hashes_failed_refs(tmp_path) -> None:
    good_file = tmp_path / "good.json"
    missing_file = tmp_path / "missing-secret-name.json"
    good_file.write_text(
        json.dumps([{"source_ref": "good:1", "title": "Decision needed", "summary": "Decide today."}]),
        encoding="utf-8",
    )
    sources = load_signal_sources_config(
        json.dumps(
            [
                {"type": "json", "path": str(missing_file), "channel": "private_feed"},
                {"type": "json", "path": str(good_file), "channel": "private_feed"},
            ]
        )
    )

    result = discover_signals_resilient(sources=sources, base_dir=tmp_path)

    assert [signal.source_ref for signal in result.signals] == ["good:1"]
    assert len(result.errors) == 1
    assert result.errors[0].startswith("private_feed:json:FileNotFoundError:")
    assert str(missing_file) not in result.errors[0]
    assert "missing-secret-name" not in result.errors[0]


def test_discovery_includes_pocket_archive_events_in_postgres_query(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, query: str, params: tuple[object, ...]) -> None:
            captured["query"] = query
            captured["params"] = params

        def fetchall(self) -> list[object]:
            return []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def cursor(self) -> FakeCursor:
            return FakeCursor()

    class FakePsycopg:
        @staticmethod
        def connect(url: str, connect_timeout: int = 5) -> FakeConnection:
            return FakeConnection()

    monkeypatch.setitem(sys.modules, "psycopg", FakePsycopg)
    signals = discover_postgres_observation_signals(
        principal_id="exec",
        database_url="postgres://test",
        limit=12,
        lookback_hours=24,
    )

    assert signals == []
    params = captured.get("params")
    assert isinstance(params, tuple)
    event_types = params[1]
    assert isinstance(event_types, list)
    assert "alexa_history_indexed" in event_types
    assert "pocket_recording_archive_indexed" in event_types


def test_discovery_queries_default_principal_alias_for_pocket_archive_rows(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, query: str, params: tuple[object, ...]) -> None:
            captured["query"] = query
            captured["params"] = params

        def fetchall(self) -> list[object]:
            return []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def cursor(self) -> FakeCursor:
            return FakeCursor()

    class FakePsycopg:
        @staticmethod
        def connect(url: str, connect_timeout: int = 5) -> FakeConnection:
            return FakeConnection()

    monkeypatch.setitem(sys.modules, "psycopg", FakePsycopg)
    monkeypatch.setenv("EA_DEFAULT_PRINCIPAL_ID", "local-user")
    monkeypatch.setenv("EA_TELEGRAM_DEFAULT_PRINCIPAL_ID", "cf-email:tibor.girschele@gmail.com")

    signals = discover_postgres_observation_signals(
        principal_id="cf-email:tibor.girschele@gmail.com",
        database_url="postgres://test",
        limit=12,
        lookback_hours=24,
    )

    assert signals == []
    params = captured.get("params")
    assert isinstance(params, tuple)
    principals = params[0]
    assert principals == ["cf-email:tibor.girschele@gmail.com", "local-user"]


def test_discovery_without_lookback_skips_time_filter(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, query: str, params: tuple[object, ...]) -> None:
            captured["query"] = query
            captured["params"] = params

        def fetchall(self) -> list[object]:
            return []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def cursor(self) -> FakeCursor:
            return FakeCursor()

    class FakePsycopg:
        @staticmethod
        def connect(url: str, connect_timeout: int = 5) -> FakeConnection:
            return FakeConnection()

    monkeypatch.setitem(sys.modules, "psycopg", FakePsycopg)
    discover_postgres_observation_signals(
        principal_id="exec",
        database_url="postgres://test",
        limit=12,
        lookback_hours=0,
    )

    query = captured.get("query")
    assert isinstance(query, str)
    assert "created_at >=" not in query


def test_discovery_skips_property_scout_observations_when_flat_search_disabled(monkeypatch) -> None:
    monkeypatch.setenv("EA_PROACTIVE_OODA_PROPERTY_SCOUT_SIGNALS_ENABLED", "1")
    monkeypatch.setenv("EA_PROACTIVE_OODA_FLAT_SEARCH_ENABLED", "0")
    captured: dict[str, object] = {}
    rows = [
        (
            "obs-new",
            "exec",
            "system",
            "property_scout_sync_completed",
            {
                "status": "processed",
                "generated_at": "2026-06-27T06:31:50+00:00",
                "filtered_low_fit_total": 60,
                "sources": [
                    {
                        "platform": "willhaben",
                        "source_label": "Willhaben Wien rentals",
                        "source_url": "https://www.willhaben.at/iad/immobilien/mietwohnungen/wien/?areaId=900&sort=3",
                        "scanned_listing_total": 60,
                        "filtered_low_fit_total": 60,
                    }
                ],
            },
            "2026-06-27T06:31:50+00:00",
            "ea-proactive-ooda",
            "",
            "exec|property-scout-sync|202606270631",
        ),
        (
            "obs-old",
            "exec",
            "system",
            "property_scout_sync_completed",
            {
                "status": "processed",
                "generated_at": "2026-06-26T19:34:32+00:00",
                "filtered_low_fit_total": 71,
                "sources": [
                    {
                        "platform": "willhaben",
                        "source_label": "Willhaben Wien rentals",
                        "source_url": "https://www.willhaben.at/iad/immobilien/mietwohnungen/wien/?areaId=900&sort=3",
                        "scanned_listing_total": 60,
                        "filtered_low_fit_total": 60,
                    }
                ],
            },
            "2026-06-26T19:34:32+00:00",
            "ea-proactive-ooda",
            "",
            "exec|property-scout-sync|202606261934",
        ),
        (
            "obs-other",
            "exec",
            "system",
            "property_scout_sync_completed",
            {
                "status": "processed",
                "generated_at": "2026-06-27T06:45:00+00:00",
                "filtered_low_fit_total": 10,
                "sources": [
                    {
                        "platform": "immmo",
                        "source_label": "IMMMO Graz rentals",
                        "source_url": "https://www.immmo.at/immo/Wohnung-mieten/Graz",
                        "scanned_listing_total": 10,
                        "filtered_low_fit_total": 10,
                    }
                ],
            },
            "2026-06-27T06:45:00+00:00",
            "ea-proactive-ooda",
            "",
            "exec|property-scout-sync|202606270645",
        ),
    ]

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _query: str, _params: tuple[object, ...]) -> None:
            captured["event_types"] = _params[1]
            return None

        def fetchall(self) -> list[object]:
            return rows

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def cursor(self) -> FakeCursor:
            return FakeCursor()

    class FakePsycopg:
        @staticmethod
        def connect(url: str, connect_timeout: int = 5) -> FakeConnection:
            return FakeConnection()

    monkeypatch.setitem(sys.modules, "psycopg", FakePsycopg)

    signals = discover_postgres_observation_signals(
        principal_id="exec",
        database_url="postgres://test",
        limit=12,
        lookback_hours=24,
    )

    assert signals == []
    assert "property_scout_sync_completed" not in captured["event_types"]


def test_opportunity_rules_create_consent_gated_ooda_signal(tmp_path) -> None:
    result = discover_opportunity_rule_signals(
        raw_config=json.dumps(
            {
                "rules": [
                    {
                        "id": "renewal-review",
                        "title": "Review renewal options",
                        "summary": "The current subscription renewal window is a good moment to compare alternatives.",
                        "decision": "Decide whether to let EA prepare a shortlist.",
                        "action": "Compare options and stage the best candidate for approval.",
                        "action_plan": [
                            "Check current constraints",
                            "Compare two realistic options",
                            "Prepare one approval packet",
                        ],
                        "stage": {
                            "kind": "approval_packet",
                            "summary": "One recommended option with evidence and an approval prompt.",
                            "artifacts": ["shortlist", "candidate_link", "approval_prompt"],
                            "candidate_items": [{"label": "Option A", "url": "https://example.test/option-a"}],
                            "approval_url": "https://example.test/approve",
                            "work_type": "compare_options",
                            "research_query": "Compare renewal options",
                            "target_sites": ["https://example.test/options"],
                            "selection_criteria": ["price", "reversibility"],
                        },
                        "external_action_policy": "Do not buy, book, send, or cancel without explicit approval.",
                        "trigger": {"kind": "always"},
                    }
                ]
            }
        ),
        base_dir=tmp_path,
    )

    assert not result.errors
    assert len(result.signals) == 1
    signal = result.signals[0]
    assert signal.source_ref.startswith("opportunity:renewal-review:")
    assert signal.signal_type == "opportunity"
    assert signal.channel == "assistant_opportunity"
    assert signal.payload is not None
    act = signal.payload["ooda_loop"]["act"]
    assert act["action_plan"] == [
        "Check current constraints",
        "Compare two realistic options",
        "Prepare one approval packet",
    ]
    assert act["stage"] == {
        "kind": "approval_packet",
        "summary": "One recommended option with evidence and an approval prompt.",
        "status": "planned",
        "approval_gate": "Do not buy, book, send, or cancel without explicit approval.",
        "artifacts": ["shortlist", "candidate_link", "approval_prompt"],
        "candidate_items": [{"label": "Option A", "url": "https://example.test/option-a"}],
        "approval_url": "https://example.test/approve",
        "work_type": "compare_options",
        "research_query": "Compare renewal options",
        "target_sites": ["https://example.test/options"],
        "selection_criteria": ["price", "reversibility"],
    }
    assert act["external_action_policy"] == "Do not buy, book, send, or cancel without explicit approval."


def test_discovery_loads_inline_opportunity_rules_without_ref(tmp_path) -> None:
    sources = load_signal_sources_config(
        json.dumps(
            {
                "sources": [
                    {
                        "type": "opportunity_rules",
                        "rules": [
                            {
                                "id": "inline-generic-opportunity",
                                "title": "Stage useful next step",
                                "summary": "A reachable signal crossed the threshold for a proactive assistant packet.",
                                "action": "Research the option and prepare a reversible approval packet.",
                                "trigger": {"kind": "always"},
                            }
                        ],
                    }
                ]
            }
        )
    )

    signals = discover_signals(sources=sources, base_dir=tmp_path)

    assert len(signals) == 1
    assert signals[0].source_ref.startswith("opportunity:inline-generic-opportunity:")
    assert signals[0].payload is not None
    assert signals[0].payload["ooda_loop"]["act"]["stage"]["kind"] == "approval_packet"


def test_opportunity_weather_trigger_uses_inline_weather_without_vendor_lock_in(tmp_path) -> None:
    result = discover_opportunity_rule_signals(
        raw_config=json.dumps(
            {
                "rules": [
                    {
                        "id": "cool-weather-window",
                        "title": "Cool-weather opportunity",
                        "summary": "A weather-sensitive errand may be easier now.",
                        "trigger": {
                            "kind": "cooler_weather",
                            "location": "Vienna",
                            "current_temperature_c": 18,
                            "temperature_at_or_below_c": 20,
                        },
                    }
                ]
            }
        ),
        base_dir=tmp_path,
    )

    assert len(result.signals) == 1
    assert "Vienna is about 18.0 C" in result.signals[0].summary


def test_opportunity_weather_trigger_rearms_when_condition_turns_true_again(tmp_path) -> None:
    config = {
        "rules": [
            {
                "id": "cool-weather-window",
                "title": "Cool-weather opportunity",
                "summary": "A weather-sensitive errand may be easier now.",
                "trigger": {
                    "kind": "cooler_weather",
                    "location": "Vienna",
                    "temperature_at_or_below_c": 20,
                    "current_temperature_c": 18,
                },
            }
        ]
    }
    warm_config = {
        "rules": [
            {
                "id": "cool-weather-window",
                "title": "Cool-weather opportunity",
                "summary": "A weather-sensitive errand may be easier now.",
                "trigger": {
                    "kind": "cooler_weather",
                    "location": "Vienna",
                    "temperature_at_or_below_c": 20,
                    "current_temperature_c": 26,
                },
            }
        ]
    }
    state_store = JsonOodaStateStore(tmp_path / "ooda.json")

    first = discover_opportunity_rule_signals(
        raw_config=json.dumps(config),
        base_dir=tmp_path,
        principal_id="exec",
        opportunity_state_store=state_store,
    )
    second = discover_opportunity_rule_signals(
        raw_config=json.dumps(config),
        base_dir=tmp_path,
        principal_id="exec",
        opportunity_state_store=state_store,
    )
    warm = discover_opportunity_rule_signals(
        raw_config=json.dumps(warm_config),
        base_dir=tmp_path,
        principal_id="exec",
        opportunity_state_store=state_store,
    )
    third = discover_opportunity_rule_signals(
        raw_config=json.dumps(config),
        base_dir=tmp_path,
        principal_id="exec",
        opportunity_state_store=state_store,
    )

    assert [signal.source_ref for signal in first.signals] == ["opportunity:cool-weather-window:occurrence-1"]
    assert [signal.source_ref for signal in second.signals] == ["opportunity:cool-weather-window:occurrence-1"]
    assert warm.signals == ()
    assert [signal.source_ref for signal in third.signals] == ["opportunity:cool-weather-window:occurrence-2"]
    assert third.signals[0].payload is not None
    assert third.signals[0].payload["ooda_loop"]["trigger"] == {
        "kind": "cooler_weather",
        "memory_mode": "edge",
        "occurrence": 2,
        "signal_key": "occurrence-2",
    }


def test_observation_mapper_turns_commitment_candidate_into_signal() -> None:
    signal = observation_row_to_signal(
        observation_id="obs-1",
        principal_id="exec",
        channel="product",
        event_type="commitment_candidate_staged",
        payload={"kind": "commitment", "title": "Return by 8:00 PM", "counterparty": "Pocket"},
        created_at="2026-06-20T10:00:00+00:00",
    )

    assert signal is not None
    assert signal.signal_type == "commitment_candidate"
    assert signal.title == "Return by 8:00 PM"
    assert signal.counterparty == "Pocket"


def test_observation_mapper_preserves_structured_ooda_loop() -> None:
    signal = observation_row_to_signal(
        observation_id="obs-ooda",
        principal_id="exec",
        channel="telegram",
        event_type="office_signal_ooda_evaluated",
        payload={
            "summary": "Fallback summary.",
            "ooda_loop": {
                "reviewed": True,
                "observe": {
                    "summary": "Alice asks for a budget answer today.",
                    "counterparty": "Alice",
                    "signal_type": "telegram_message",
                    "due_at": "2026-06-20T18:00:00+02:00",
                    "channel": "telegram",
                },
                "orient": {"summary": "This affects today's launch preparation.", "tags": ["launch", "budget"]},
                "decide": {"summary": "Decide whether to approve the spend.", "recommended_actions": ["Approve or decline."]},
                "act": {"summary": "Ask the user for a yes/no decision."},
            },
        },
        created_at="2026-06-20T10:00:00+00:00",
    )

    assert signal is not None
    assert signal.title == "Decide whether to approve the spend."
    assert signal.summary == "Alice asks for a budget answer today."
    assert signal.counterparty == "Alice"
    assert signal.signal_type == "telegram_message"
    assert signal.due_at == "2026-06-20T18:00:00+02:00"
    assert signal.payload is not None
    assert signal.payload["ooda_loop"]["observe"]["summary"] == "Alice asks for a budget answer today."
    assert signal.payload["ooda_loop"]["orient"]["tags"] == ["launch", "budget"]


def test_observation_mapper_drops_property_scout_counts_when_flat_search_disabled(monkeypatch) -> None:
    monkeypatch.setenv("EA_PROACTIVE_OODA_PROPERTY_SCOUT_SIGNALS_ENABLED", "1")
    monkeypatch.setenv("EA_PROACTIVE_OODA_FLAT_SEARCH_ENABLED", "0")
    signal = observation_row_to_signal(
        observation_id="obs-2",
        principal_id="exec",
        channel="product",
        event_type="property_scout_sync_completed",
        payload={
            "status": "processed",
            "high_fit_total": 2,
            "review_created_total": 1,
            "review_existing_total": 3,
            "notified_total": 1,
            "failed_total": 0,
        },
        created_at="2026-06-20T10:00:00+00:00",
    )

    assert signal is None


def test_observation_mapper_records_topic_suppression_from_stop_message() -> None:
    signal = observation_row_to_signal(
        observation_id="obs-stop-topic",
        principal_id="exec",
        channel="telegram",
        event_type="telegram.message",
        payload={"text": "Höre auf mit den unter Wand microfonen."},
        created_at="2026-06-20T10:00:00+00:00",
    )

    assert signal is not None
    assert signal.payload is not None
    directive = signal.payload.get("proactive_suppression")
    assert isinstance(directive, dict)
    assert directive["schema"] == "ea.proactive_topic_suppression.v1"
    assert directive["terms"] == ["under", "wall", "microphone"]
    assert directive["observed_at"] == "2026-06-20T10:00:00+00:00"


def test_observation_mapper_turns_telegram_task_message_into_transcript_ooda_signal() -> None:
    signal = observation_row_to_signal(
        observation_id="obs-telegram-task",
        principal_id="exec",
        channel="telegram",
        event_type="telegram.message",
        payload={"text": "When you find a chimney sweep, draft an email inquiry and save it for approval."},
        created_at="2026-06-20T10:00:00+00:00",
    )

    assert signal is not None
    assert signal.signal_type == "telegram_message"
    assert signal.payload is not None
    ooda_loop = signal.payload.get("ooda_loop")
    assert isinstance(ooda_loop, dict)
    assert ooda_loop["act"]["stage"]["work_type"] == "draft"
    assert ooda_loop["act"]["stage"]["kind"] == "approval_packet"
    assert ooda_loop["act"]["stage"]["draft_mode"] == "research_backed_inquiry"
    assert ooda_loop["act"]["stage"]["research_query"] == "chimney sweep"
    assert ooda_loop["act"]["stage"]["search_queries"] == ["chimney sweep"]


def test_observation_mapper_turns_german_telegram_task_message_into_transcript_ooda_signal() -> None:
    signal = observation_row_to_signal(
        observation_id="obs-telegram-task-de",
        principal_id="exec",
        channel="telegram",
        event_type="telegram.message",
        payload={"text": "Wenn du einen Rauchfangkehrer gefunden hast, formuliere eine Emailanfrage und speicher sie als Draft in meiner Inbox."},
        created_at="2026-06-20T10:00:00+00:00",
    )

    assert signal is not None
    assert signal.signal_type == "telegram_message"
    assert signal.payload is not None
    ooda_loop = signal.payload.get("ooda_loop")
    assert isinstance(ooda_loop, dict)
    assert ooda_loop["act"]["stage"]["work_type"] == "draft"
    assert ooda_loop["act"]["stage"]["kind"] == "research_packet"
    assert ooda_loop["act"]["stage"]["draft_mode"] == "research_backed_inquiry"
    assert ooda_loop["act"]["stage"]["auto_execute_action"] == "save_gmail_draft"
    assert ooda_loop["act"]["stage"]["research_query"] == "Rauchfangkehrer"
    assert ooda_loop["act"]["stage"]["search_queries"] == ["Rauchfangkehrer"]
    assert ooda_loop["act"]["stage"]["locale"] == "de"
    assert ooda_loop["decide"]["approval_required"] is False


def test_long_german_transcript_task_adds_contextual_search_query() -> None:
    signal = observation_row_to_signal(
        observation_id="obs-telegram-task-de-long",
        principal_id="exec",
        channel="telegram",
        event_type="telegram.message",
        payload={
            "text": (
                "Suche mir einen Rauchfangkehrer. "
                "Ich brauche ein Gutachten, ob ich meinen Zimmerkamin als Abluftrohr eines Klimageraets verwenden kann. "
                "Wenn du einen gefunden hast, formuliere eine Emailanfrage und speicher sie als Draft in meiner Inbox."
            )
        },
        created_at="2026-06-20T10:00:00+00:00",
    )

    assert signal is not None
    assert signal.payload is not None
    ooda_loop = signal.payload.get("ooda_loop")
    assert isinstance(ooda_loop, dict)
    search_queries = ooda_loop["act"]["stage"]["search_queries"]
    assert search_queries[0].startswith("Rauchfangkehrer ")
    assert "Gutachten" in search_queries[0]
    assert "Zimmerkamin" in search_queries[0]
    assert search_queries[1].startswith("Rauchfangkehrer ")
    assert "Abluftrohr" in search_queries[1]
    assert search_queries[-1] == "Rauchfangkehrer"


def test_hyphenated_german_transcript_task_extracts_compact_provider_query() -> None:
    signal = observation_row_to_signal(
        observation_id="obs-telegram-task-de-hyphen",
        principal_id="exec",
        channel="telegram",
        event_type="telegram.message",
        payload={
            "text": (
                "suche mir rauchfangkehrer - ich brauche ein Gutachten, ob ich meinen Zimmerkamin "
                "als Abluftrohr eines Klimageraets verwenden kann. "
                "wenn du einen gefunden hast formuliere eine emailanfrage und speicher sie als draft in meiner inbox."
            )
        },
        created_at="2026-06-20T10:00:00+00:00",
    )

    assert signal is not None
    assert signal.payload is not None
    ooda_loop = signal.payload.get("ooda_loop")
    assert isinstance(ooda_loop, dict)
    stage = ooda_loop["act"]["stage"]
    assert stage["research_query"] == "rauchfangkehrer"
    assert stage["search_queries"][0].startswith("rauchfangkehrer ")
    assert "Gutachten" in stage["search_queries"][0]
    assert "Zimmerkamin" in stage["search_queries"][0]
    assert "Abluftrohr" in stage["search_queries"][0]
    assert stage["search_queries"][1] == "rauchfangkehrer Gutachten Zimmerkamin Abluftrohr"
    assert stage["search_queries"][-1] == "rauchfangkehrer"


def test_hyphenated_german_compare_task_extracts_compact_provider_query() -> None:
    signal = observation_row_to_signal(
        observation_id="obs-telegram-task-de-hyphen-compare",
        principal_id="exec",
        channel="telegram",
        event_type="telegram.message",
        payload={
            "text": (
                "suche mir rauchfangkehrer - ich brauche ein Gutachten, ob ich meinen Zimmerkamin "
                "als Abluftrohr eines Klimageraets verwenden kann"
            )
        },
        created_at="2026-06-20T10:00:00+00:00",
    )

    assert signal is not None
    assert signal.payload is not None
    ooda_loop = signal.payload.get("ooda_loop")
    assert isinstance(ooda_loop, dict)
    stage = ooda_loop["act"]["stage"]
    assert stage["work_type"] == "compare_options"
    assert stage["research_query"] == "rauchfangkehrer"
    assert "contact details visible" in stage["selection_criteria"]
    assert "reachability" in stage["comparison_dimensions"]
    assert "price" not in stage["selection_criteria"]
    assert "for review" in ooda_loop["act"]["summary"]
    assert "for review" in ooda_loop["act"]["stage"]["summary"]
    assert stage["search_queries"][0].startswith("rauchfangkehrer ")
    assert "Gutachten" in stage["search_queries"][0]
    assert "Zimmerkamin" in stage["search_queries"][0]
    assert stage["search_queries"][1] == "rauchfangkehrer Gutachten Zimmerkamin Abluftrohr"
    assert stage["search_queries"][-1] == "rauchfangkehrer"


def test_research_query_prefers_buried_service_task_clause_over_transcript_noise() -> None:
    request = (
        "[Mikrofongeraeusche] Also ich bin ein bisschen nervoes. "
        "Ich bin entlassen worden. "
        "Ich moechte auch einen Elektriker kommen lassen fuer zusaetzliche Steckdosen. "
        "Wenn du noch irgendwo eine Steckdose haben willst, dann sag mir das einfach und ich werde einen Elektriker kommen lassen. "
        "Ich soll keine Mail geschickt haben, wenn du nicht willst, ist auch in Ordnung."
    )

    query = signal_discovery._research_query_from_request(request)  # noqa: SLF001

    assert "Elektriker" in query
    assert "Steckdosen" in query
    assert "nervoes" not in query.lower()
    assert "[Mikrofongeraeusche]" not in query


def test_transcript_request_text_prefers_the_longest_unique_variant() -> None:
    from app.services.proactive_signal_discovery import _transcript_request_text

    text = _transcript_request_text(
        "Suche mir einen Rauchfangkehrer. Ich brauche ein Gutachten.",
        "Suche mir einen Rauchfangkehrer. Ich brauche ein Gutachten.",
        "Suche mir einen Rauchfangkehrer.",
    )

    assert text == "Suche mir einen Rauchfangkehrer. Ich brauche ein Gutachten."


def test_observation_mapper_turns_pocket_archive_index_into_transcript_signal() -> None:
    signal = observation_row_to_signal(
        observation_id="obs-pocket",
        principal_id="exec",
        channel="product",
        event_type="pocket_recording_archive_indexed",
        payload={
            "recording_id": "rec-9f91",
            "title": "Kitchen notes",
            "recording_at": "2026-06-20T09:15:00+00:00",
            "archive_status": "archived",
            "archive_path": "/mnt/pcloud/EA/pocket-ai-audio/private/kitchen-notes.mp3",
            "archive_sha256": "a" * 64,
            "summary_markdown": "Discussed gift ideas and supplier leads for next week.",
            "transcript_excerpt": "Order flowers for my wife this weekend.",
            "transcript_text": "Order flowers for my wife this weekend. Compare two local options before buying.",
            "topic_keywords_csv": "home,shopping",
            "tags_csv": "home, gifts",
            "location_name": "Vienna",
            "location_address": "Vienna, Austria",
            "location_confidence": "0.91",
            "location_match_status": "matched",
        },
        created_at="2026-06-20T10:00:00+00:00",
        source_id="pocket-recording:rec-9f91",
    )

    assert signal is not None
    assert signal.signal_type == "pocket_transcript"
    assert signal.title == "Kitchen notes"
    assert signal.summary == "Discussed gift ideas and supplier leads for next week."
    assert signal.due_at is None
    assert signal.external_id == "rec-9f91"
    assert signal.counterparty == "Pocket"
    assert signal.channel == "product"
    assert signal.payload is not None
    pocket_payload = signal.payload.get("pocket_recording")
    assert isinstance(pocket_payload, dict)
    assert pocket_payload["provider"] == "pocket.ai"
    assert pocket_payload["recording_id"] == "rec-9f91"
    assert pocket_payload["recording_at"] == "2026-06-20T09:15:00+00:00"
    assert pocket_payload["archive_status"] == "archived"
    assert pocket_payload["archive_sha256"] == "a" * 64
    assert pocket_payload["archive_path_sha256"]
    assert pocket_payload["retention_class"] == "pocket_audio_archive_index"
    assert pocket_payload["retention_status"] == "archived"
    assert pocket_payload["retention_payload"] == "redacted_source_metadata"
    assert pocket_payload["source_current_status"] == "current"
    assert pocket_payload["source_freshness_basis"] == "recording_at_to_indexed_at"
    assert pocket_payload["source_lag_hours"] == 0.75
    assert pocket_payload["source_stale_after_hours"] == 168.0
    assert pocket_payload["topic_keywords_csv"] == "home,shopping"
    assert pocket_payload["tags_csv"] == "home, gifts"
    assert pocket_payload["location_name"] == "Vienna"
    assert pocket_payload["location_address"] == "Vienna, Austria"
    assert pocket_payload["location_confidence"] == "0.91"
    assert pocket_payload["location_match_status"] == "matched"
    assert pocket_payload["summary_markdown_sha256"]
    assert pocket_payload["transcript_excerpt_sha256"]
    assert pocket_payload["transcript_text_sha256"]
    assert pocket_payload["transcript_text_char_count"] == 80
    assert "archive_path" not in pocket_payload
    assert "transcript_text" not in pocket_payload
    assert "transcript_excerpt" not in pocket_payload
    assert "/mnt/pcloud" not in json.dumps(pocket_payload, sort_keys=True)
    assert pocket_payload["privacy"] == {
        "raw_archive_path_stored": False,
        "raw_summary_markdown_stored": False,
        "raw_transcript_excerpt_stored": False,
        "raw_transcript_text_stored": False,
    }
    ooda_loop = signal.payload.get("ooda_loop")
    assert isinstance(ooda_loop, dict)
    assert ooda_loop["act"]["stage"]["work_type"] == "compare_options"
    assert "Order flowers for my wife this weekend." in ooda_loop["act"]["stage"]["research_query"]


def test_observation_mapper_marks_stale_pocket_archive_index_source_context() -> None:
    signal = observation_row_to_signal(
        observation_id="obs-pocket-stale",
        principal_id="exec",
        channel="product",
        event_type="pocket_recording_archive_indexed",
        payload={
            "recording_id": "rec-stale",
            "title": "Old sync",
            "recording_at": "2026-06-01T09:00:00+00:00",
            "archive_status": "archived",
            "transcript_excerpt": "Remember to compare air conditioner installers.",
        },
        created_at="2026-06-20T10:00:00+00:00",
        source_id="pocket-recording:rec-stale",
    )

    assert signal is not None
    pocket_payload = signal.payload.get("pocket_recording")
    assert isinstance(pocket_payload, dict)
    assert pocket_payload["source_current_status"] == "stale"
    assert pocket_payload["source_lag_hours"] == 457.0
    assert pocket_payload["retention_status"] == "archived"


def test_observation_mapper_pocket_archive_index_falls_back_to_excerpt_summary() -> None:
    signal = observation_row_to_signal(
        observation_id="obs-pocket-2",
        principal_id="exec",
        channel="product",
        event_type="pocket_recording_archive_indexed",
        payload={
            "recording_id": "rec-excerpt",
            "title": "Lunch recap",
            "recording_at": "2026-06-20T09:30:00+00:00",
            "transcript_excerpt": "Remember to book flowers when the weather cools down.",
            "transcript_text": "Transcribed full text with several details.",
        },
        created_at="2026-06-20T10:30:00+00:00",
        source_id="pocket-recording:rec-excerpt",
    )

    assert signal is not None
    assert signal.signal_type == "pocket_transcript"
    assert signal.title == "Lunch recap"
    assert signal.summary == "Remember to book flowers when the weather cools down."
    assert signal.due_at is None


def test_pocket_background_transcript_without_action_intent_stays_quiet_context() -> None:
    signal = observation_row_to_signal(
        observation_id="obs-pocket-background-noise",
        principal_id="exec",
        channel="product",
        event_type="pocket_recording_archive_indexed",
        payload={
            "recording_id": "rec-background-noise",
            "title": "Background walk",
            "recording_at": "2026-06-29T09:30:00+00:00",
            "archive_status": "archived",
            "summary_markdown": "Mikrofongeraeusche und lockeres Gespraech beim Gehen.",
            "transcript_excerpt": (
                "[Mikrofongeraeusche] Wir gehen jetzt glaube ich auf die Kinderspielhuegel. "
                "Stimmt schauen anschauen mitgeht."
            ),
            "transcript_text": (
                "[Mikrofongeraeusche] Wir gehen jetzt glaube ich auf die Kinderspielhuegel. "
                "Stimmt schauen anschauen mitgeht. Eine Person ist im Hintergrund."
            ),
            "topic_keywords_csv": "family,background,voices",
        },
        created_at="2026-06-29T10:00:00+00:00",
        source_id="pocket-recording:rec-background-noise",
    )

    assert signal is None


def test_pocket_unicode_microphone_noise_fragment_does_not_stage_research() -> None:
    signal = observation_row_to_signal(
        observation_id="obs-pocket-live-noise",
        principal_id="exec",
        channel="product",
        event_type="pocket_recording_archive_indexed",
        payload={
            "recording_id": "rec-live-noise",
            "title": "Pocket recording",
            "recording_at": "2026-06-29T09:30:00+00:00",
            "archive_status": "archived",
            "summary_markdown": "[Mikrofongeräusche] Wir gehen jetzt, glaube ich auf die Kinderspielhügge.",
            "transcript_excerpt": (
                "[Mikrofongeräusche] Wir gehen jetzt, glaube ich auf die Kinderspielhügge. "
                "Stimmt schauen anschauen mitgeht"
            ),
            "transcript_text": (
                "[Mikrofongeräusche] Wir gehen jetzt, glaube ich auf die Kinderspielhügge. "
                "Stimmt schauen anschauen mitgeht"
            ),
            "topic_keywords_csv": "mikrofongeräusche,family,background",
        },
        created_at="2026-06-29T10:00:00+00:00",
        source_id="pocket-recording:rec-live-noise",
    )

    assert signal is None


def test_observation_mapper_turns_alexa_history_index_into_transcript_signal() -> None:
    signal = observation_row_to_signal(
        observation_id="obs-alexa",
        principal_id="exec",
        channel="product",
        event_type="alexa_history_indexed",
        payload={
            "history_entry_id": "history-search-1",
            "source_ref": "alexa-history:history-search-1",
            "title": "Compare florist options for next week.",
            "occurred_at": "2026-06-20T09:15:00+00:00",
            "summary_markdown": "Okay, I'll compare them.",
            "utterance_text": "Compare florist options for next week.",
            "response_text": "Okay, I'll compare them.",
            "device_name": "Echo Dot",
            "skill_name": "Alexa",
        },
        created_at="2026-06-20T10:00:00+00:00",
        source_id="alexa-history:history-search-1",
    )

    assert signal is not None
    assert signal.signal_type == "alexa_transcript"
    assert signal.title == "Compare florist options for next week."
    assert signal.summary == "Compare florist options for next week."
    assert signal.due_at is None
    assert signal.external_id == "history-search-1"
    assert signal.counterparty == "Alexa"
    assert signal.channel == "product"
    assert signal.payload is not None
    alexa_payload = signal.payload.get("alexa_history")
    assert isinstance(alexa_payload, dict)
    assert alexa_payload["history_entry_id"] == "history-search-1"
    assert alexa_payload["device_name"] == "Echo Dot"
    ooda_loop = signal.payload.get("ooda_loop")
    assert isinstance(ooda_loop, dict)
    assert ooda_loop["act"]["stage"]["work_type"] == "compare_options"
    assert ooda_loop["act"]["stage"]["delivery_window"] == 7.0


def test_actionable_alexa_transcript_stages_safe_research_packet() -> None:
    signal = observation_row_to_signal(
        observation_id="obs-alexa-stage",
        principal_id="exec",
        channel="product",
        event_type="alexa_history_indexed",
        payload={
            "history_entry_id": "history-stage-1",
            "source_ref": "alexa-history:history-stage-1",
            "title": "Compare florist options for next week.",
            "occurred_at": "2026-06-20T09:15:00+00:00",
            "utterance_text": "Compare florist options for next week.",
            "response_text": "Okay, I'll compare them.",
            "device_name": "Echo Dot",
            "skill_name": "Alexa",
        },
        created_at="2026-06-20T10:00:00+00:00",
        source_id="alexa-history:history-stage-1",
    )

    assert signal is not None
    digest = ProactiveOodaService().build_digest(principal_id="exec", signals=[signal])

    assert len(digest.items) == 1
    item = digest.items[0]
    assert item.stage_kind == "research_packet"
    assert item.stage_payload is not None
    assert item.stage_payload["work_type"] == "compare_options"
    assert item.stage_payload["research_query"] == "Compare florist options for next week."

    packet = build_stage_packets(digest)[0]
    result = build_safe_work_result(packet)
    assert result["status"] == "staged_for_user_decision"
    assert result["work_type"] == "compare_options"
    assert result["recommended_option_or_draft"]["kind"] == "research_query"
    assert result["recommended_option_or_draft"]["value"] == "Compare florist options for next week."


def test_actionable_alexa_transcript_stages_draft_reply_packet() -> None:
    signal = observation_row_to_signal(
        observation_id="obs-alexa-draft",
        principal_id="exec",
        channel="product",
        event_type="alexa_history_indexed",
        payload={
            "history_entry_id": "history-draft-1",
            "title": "Reply to the landlord about the viewing.",
            "utterance_text": "Reply to the landlord about the viewing tomorrow.",
            "response_text": "Okay, I'll help with that.",
            "device_name": "Echo Dot",
            "skill_name": "Alexa",
        },
        created_at="2026-06-20T10:00:00+00:00",
        source_id="alexa-history:history-draft-1",
    )

    assert signal is not None
    digest = ProactiveOodaService().build_digest(principal_id="exec", signals=[signal])
    assert len(digest.items) == 1
    item = digest.items[0]
    assert item.approval_required is True
    assert item.stage_payload is not None
    assert item.stage_payload["work_type"] == "draft"
    assert "Draft to review:" in item.stage_payload["draft_text"]


def test_combined_transcript_task_falls_back_to_a_reviewable_draft_even_before_live_research() -> None:
    signal = observation_row_to_signal(
        observation_id="obs-telegram-task-combined",
        principal_id="exec",
        channel="telegram",
        event_type="telegram.message",
        payload={"text": "When you find a chimney sweep, draft an email inquiry and save it for approval."},
        created_at="2026-06-20T10:00:00+00:00",
    )

    assert signal is not None
    digest = ProactiveOodaService().build_digest(principal_id="exec", signals=[signal])
    packet = build_stage_packets(digest)[0]
    result = build_safe_work_result(packet)

    assert result["work_type"] == "draft"
    assert result["status"] == "blocked_needs_research_input"
    assert result["recommended_option_or_draft"] == {}
    assert any(issue["code"] == "draft_not_created" for issue in result["audit"]["issues"])


def test_actionable_pocket_transcript_stages_booking_research_packet() -> None:
    signal = observation_row_to_signal(
        observation_id="obs-pocket-booking",
        principal_id="exec",
        channel="product",
        event_type="pocket_recording_archive_indexed",
        payload={
            "recording_id": "rec-booking",
            "title": "Weekend dinner",
            "transcript_excerpt": "Book a dinner table for this weekend and compare two options first.",
            "transcript_text": "Book a dinner table for this weekend and compare two options first.",
        },
        created_at="2026-06-20T10:30:00+00:00",
        source_id="pocket-recording:rec-booking",
    )

    assert signal is not None
    ooda_loop = signal.payload.get("ooda_loop")
    assert isinstance(ooda_loop, dict)
    stage = ooda_loop["act"]["stage"]
    assert stage["work_type"] == "compare_options"
    assert stage["artifacts"] == ["booking_candidate", "comparison_table", "approval_prompt"]
    assert stage["delivery_window"] == 3.0


def test_pocket_transcript_vendor_request_can_auto_stage_gmail_draft_without_raw_audio_leak() -> None:
    transcript = (
        "Suche mir einen Elektriker in 1200 Wien. "
        "Ich brauche eine Unterputz-Steckdose in einer Regipswand bei der Abluftoeffnung "
        "und eine Doppelsteckdose in einer Betonwand. "
        "Wenn du einen gefunden hast, formuliere eine kurze Emailanfrage und speichere sie als Draft in meiner Inbox."
    )
    signal = observation_row_to_signal(
        observation_id="obs-pocket-electrician-draft",
        principal_id="exec",
        channel="product",
        event_type="pocket_recording_archive_indexed",
        payload={
            "recording_id": "rec-electrician-draft",
            "title": "Home electrical task",
            "recording_at": "2026-06-29T05:55:00+00:00",
            "archive_status": "archived",
            "archive_path": "/mnt/pcloud/EA/pocket-ai-audio/private/electrical-task.mp3",
            "archive_sha256": "b" * 64,
            "summary_markdown": "Find an electrician and prepare a Gmail draft.",
            "transcript_excerpt": transcript,
            "transcript_text": transcript,
            "topic_keywords_csv": "home,electrician,outreach",
            "tags_csv": "home, vendor",
            "location_name": "1200 Wien",
        },
        created_at="2026-06-29T06:10:00+00:00",
        source_id="pocket-recording:rec-electrician-draft",
    )

    assert signal is not None
    assert signal.signal_type == "pocket_transcript"
    assert signal.payload is not None
    pocket_payload = signal.payload.get("pocket_recording")
    assert isinstance(pocket_payload, dict)
    assert pocket_payload["provider"] == "pocket.ai"
    assert pocket_payload["retention_class"] == "pocket_audio_archive_index"
    assert pocket_payload["archive_path_sha256"]
    assert "archive_path" not in pocket_payload
    assert "transcript_text" not in pocket_payload
    assert "/mnt/pcloud" not in json.dumps(pocket_payload, sort_keys=True)

    ooda_loop = signal.payload.get("ooda_loop")
    assert isinstance(ooda_loop, dict)
    stage = ooda_loop["act"]["stage"]
    assert stage["work_type"] == "draft"
    assert stage["draft_mode"] == "research_backed_inquiry"
    assert stage["adapter_hint"] == "transcript_signal"
    assert stage["auto_execute_action"] == "save_gmail_draft"
    assert stage["post_approval_action"] == "save_gmail_draft"
    assert stage["locale"] == "de"
    assert stage["research_query"] == "Elektriker in 1200 Wien"
    assert stage["search_queries"][0].startswith("Elektriker")
    assert "Unterputz" in stage["search_queries"][0]
    assert stage["notes"] == ["Topic keywords: home,electrician,outreach", "Tags: home, vendor", "Location: 1200 Wien"]

    digest = ProactiveOodaService().build_digest(principal_id="exec", signals=[signal])
    assert len(digest.items) == 1
    item = digest.items[0]
    assert item.approval_required is False
    assert item.stage_payload is not None
    assert item.stage_payload["auto_execute_action"] == "save_gmail_draft"

    packet = build_stage_packets(digest)[0]
    assert packet["stage"]["payload"]["work_type"] == "draft"
    assert packet["stage"]["payload"]["auto_execute_action"] == "save_gmail_draft"
    assert packet["safe_work_order"]["work_type"] == "draft"
    assert packet["safe_work_order"]["input_contract"]["private_payload_available"] is True

    result = build_safe_work_result(packet)
    assert result["work_type"] == "draft"
    assert result["status"] == "blocked_needs_research_input"
    assert result["recommended_option_or_draft"] == {}
    assert any(issue["code"] == "draft_not_created" for issue in result["audit"]["issues"])
    assert "research further" in result["approval_prompt"]


def test_pocket_transcript_prefers_raw_transcript_over_markdown_summary_for_request_extraction() -> None:
    transcript = (
        "Suche mir einen Elektriker in 1200 Wien. "
        "Ich brauche eine Unterputz-Steckdose in einer Regipswand."
    )
    signal = observation_row_to_signal(
        observation_id="obs-pocket-summary-fallback",
        principal_id="exec",
        channel="product",
        event_type="pocket_recording_archive_indexed",
        payload={
            "recording_id": "rec-summary-fallback",
            "title": "Home notes",
            "summary_markdown": (
                "* **Window Maintenance:** A technician is scheduled for Wednesday between 08:00 and 14:00.\n"
                "* **Proactive Contributions:** Tibor is organizing small home improvements."
            ),
            "transcript_excerpt": transcript,
            "transcript_text": transcript,
        },
        created_at="2026-07-01T06:10:00+00:00",
        source_id="pocket-recording:rec-summary-fallback",
    )

    assert signal is not None
    ooda_loop = signal.payload.get("ooda_loop")
    assert isinstance(ooda_loop, dict)
    stage = ooda_loop["act"]["stage"]
    assert stage["research_query"] == "Elektriker in 1200 Wien"
    assert "Window Maintenance" not in stage["research_query"]


def test_pocket_transcript_with_medical_chatter_and_buried_provider_note_keeps_compact_provider_query() -> None:
    transcript = (
        "[Mikrofongeraeusche] Also ich bin ein bisschen nervoes. "
        "Ich bin entlassen worden. "
        "Aehm, und zusaetzlich, ich moechte auch einen Elektriker fuer zusaetzliche Steckdosen."
    )
    signal = observation_row_to_signal(
        observation_id="obs-pocket-buried-provider-note",
        principal_id="exec",
        channel="product",
        event_type="pocket_recording_archive_indexed",
        payload={
            "recording_id": "rec-buried-provider-note",
            "title": "Household note",
            "transcript_excerpt": transcript,
            "transcript_text": transcript,
        },
        created_at="2026-07-01T06:15:00+00:00",
        source_id="pocket-recording:rec-buried-provider-note",
    )

    assert signal is not None
    ooda_loop = signal.payload.get("ooda_loop")
    assert isinstance(ooda_loop, dict)
    stage = ooda_loop["act"]["stage"]
    assert stage["research_query"] == "Elektriker fuer zusaetzliche Steckdosen."


def test_pocket_transcript_uses_actionable_display_text_for_mixed_recordings() -> None:
    transcript = (
        "Also ich bin ein bisschen nervoes. "
        "Der Blutdruck war zuletzt eher hoch. "
        "Und zusaetzlich, ich moechte auch einen Elektriker kommen lassen fuer zusaetzliche Steckdosen. "
        "Wenn du einen gefunden hast, formuliere bitte eine kurze Anfrage als Draft."
    )
    signal = observation_row_to_signal(
        observation_id="obs-pocket-mixed-recording-display",
        principal_id="exec",
        channel="product",
        event_type="pocket_recording_archive_indexed",
        payload={
            "recording_id": "rec-mixed-recording-display",
            "title": "Follow-up on leg swelling care",
            "summary_markdown": (
                "This session covers a medical consultation regarding physical symptoms and blood pressure management, "
                "followed by a personal coordination of household logistics. "
                "### Medical Review: Edema & Blood Pressure "
                "* **Edema Management:** Compression stockings, elevation, and warm wraps. "
                "* **Medication Adjustments:** Blood pressure medication review. "
                "### Household Coordination & Logistics "
                "* **Electrical Upgrades:** Plans are underway to bring in an electrician for additional power outlets."
            ),
            "transcript_excerpt": transcript,
            "transcript_text": transcript,
        },
        created_at="2026-07-01T06:16:00+00:00",
        source_id="pocket-recording:rec-mixed-recording-display",
    )

    assert signal is not None
    assert "Elektriker" in signal.title
    assert "Elektriker" in signal.summary
    assert "leg swelling" not in signal.title.lower()
    assert "blood pressure" not in signal.summary.lower()
    ooda_loop = signal.payload.get("ooda_loop")
    assert isinstance(ooda_loop, dict)
    assert ooda_loop["act"]["stage"]["research_query"] == "Elektriker fuer zusaetzliche Steckdosen."


def test_pocket_transcript_ignores_ambient_self_talk_without_direct_task_marker() -> None:
    signal = observation_row_to_signal(
        observation_id="obs-pocket-self-talk",
        principal_id="exec",
        channel="product",
        event_type="pocket_recording_archive_indexed",
        payload={
            "recording_id": "rec-self-talk",
            "title": "Therapy note",
            "transcript_excerpt": (
                "Es passieren halt nach wie vor Missgeschicke. "
                "Ja, also das muss ich schreiben."
            ),
            "transcript_text": (
                "Es passieren halt nach wie vor Missgeschicke. "
                "Ja, also das muss ich schreiben."
            ),
        },
        created_at="2026-07-01T06:20:00+00:00",
        source_id="pocket-recording:rec-self-talk",
    )

    assert signal is None


def test_pocket_transcript_ignores_nonresearchable_ambient_compare_hint() -> None:
    signal = observation_row_to_signal(
        observation_id="obs-pocket-nonresearchable-compare",
        principal_id="exec",
        channel="product",
        event_type="pocket_recording_archive_indexed",
        payload={
            "recording_id": "rec-nonresearchable-compare",
            "title": "Planning",
            "transcript_excerpt": "Versuchen Sie, sich da jetzt nicht frustrieren zu lassen.",
            "transcript_text": "Versuchen Sie, sich da jetzt nicht frustrieren zu lassen.",
        },
        created_at="2026-07-01T06:25:00+00:00",
        source_id="pocket-recording:rec-nonresearchable-compare",
    )

    assert signal is None


def test_pocket_transcript_ignores_ambient_politeness_without_actionable_task() -> None:
    signal = observation_row_to_signal(
        observation_id="obs-pocket-ambient-bitte",
        principal_id="exec",
        channel="product",
        event_type="pocket_recording_archive_indexed",
        payload={
            "recording_id": "rec-ambient-bitte",
            "title": "Neuro training",
            "transcript_excerpt": (
                "Wie gehen wir das an? Bitte achten Sie darauf, dass die Uebungen heute nicht frustrieren."
            ),
            "transcript_text": (
                "Wie gehen wir das an? Bitte achten Sie darauf, dass die Uebungen heute nicht frustrieren."
            ),
        },
        created_at="2026-07-01T06:25:30+00:00",
        source_id="pocket-recording:rec-ambient-bitte",
    )

    assert signal is None


def test_pocket_transcript_rebuilds_stale_embedded_ooda_from_current_transcript_rules() -> None:
    signal = observation_row_to_signal(
        observation_id="obs-pocket-stale-embedded-ooda",
        principal_id="exec",
        channel="product",
        event_type="pocket_recording_archive_indexed",
        payload={
            "recording_id": "rec-stale-embedded-ooda",
            "title": "Therapy note",
            "transcript_excerpt": "Versuchen Sie, sich da jetzt nicht frustrieren zu lassen.",
            "transcript_text": "Versuchen Sie, sich da jetzt nicht frustrieren zu lassen.",
            "ooda_loop": {
                "reviewed": True,
                "observe": {"summary": "stale"},
                "orient": {"summary": "stale"},
                "decide": {"summary": "stale"},
                "act": {
                    "summary": "stale",
                    "stage": {
                        "kind": "research_packet",
                        "work_type": "compare_options",
                        "research_query": "Versuchen Sie, sich da jetzt nicht frustrieren zu lassen.",
                    },
                },
            },
        },
        created_at="2026-07-01T06:26:00+00:00",
        source_id="pocket-recording:rec-stale-embedded-ooda",
    )

    assert signal is None


def test_pocket_transcript_does_not_treat_visita_and_optionen_as_booking_or_compare_tasks() -> None:
    signal = observation_row_to_signal(
        observation_id="obs-pocket-visita-optionen",
        principal_id="exec",
        channel="product",
        event_type="pocket_recording_archive_indexed",
        payload={
            "recording_id": "rec-visita-optionen",
            "title": "Medical planning",
            "transcript_excerpt": (
                "Bei der Visita haben Sie gerade gesagt, dass meine Werte ziemlich gut wären. "
                "Wo es für Sie dann diese Optionen so angenehmer ist wahrscheinlich."
            ),
            "transcript_text": (
                "Bei der Visita haben Sie gerade gesagt, dass meine Werte ziemlich gut wären. "
                "Wo es für Sie dann diese Optionen so angenehmer ist wahrscheinlich."
            ),
        },
        created_at="2026-07-01T06:27:00+00:00",
        source_id="pocket-recording:rec-visita-optionen",
    )

    assert signal is None


def test_observation_mapper_skips_empty_property_scout_sync() -> None:
    signal = observation_row_to_signal(
        observation_id="obs-empty",
        principal_id="exec",
        channel="product",
        event_type="property_scout_sync_completed",
        payload={
            "status": "processed",
            "high_fit_total": 0,
            "review_created_total": 0,
            "review_existing_total": 0,
            "notified_total": 0,
            "watch_notified_total": 0,
            "failed_total": 0,
        },
        created_at="2026-06-20T10:00:00+00:00",
    )

    assert signal is None


def test_observation_mapper_drops_zero_match_property_scout_supply_when_flat_search_disabled(monkeypatch) -> None:
    monkeypatch.setenv("EA_PROACTIVE_OODA_PROPERTY_SCOUT_SIGNALS_ENABLED", "1")
    monkeypatch.setenv("EA_PROACTIVE_OODA_FLAT_SEARCH_ENABLED", "0")
    signal = observation_row_to_signal(
        observation_id="obs-zero-fit",
        principal_id="exec",
        channel="product",
        event_type="property_scout_sync_completed",
        payload={
            "status": "processed",
            "high_fit_total": 0,
            "review_created_total": 0,
            "review_existing_total": 0,
            "notified_total": 0,
            "watch_notified_total": 0,
            "failed_total": 0,
            "scanned_listing_total": 71,
            "filtered_low_fit_total": 71,
            "sources": [
                {
                    "source_label": "Willhaben Wien rentals",
                    "source_url": "https://example.test/willhaben",
                    "raw_listing_total": 60,
                    "filtered_low_fit_total": 60,
                },
                {
                    "source_label": "IMMMO Wien rentals",
                    "source_url": "https://example.test/immmo",
                    "raw_listing_total": 11,
                    "filtered_low_fit_total": 11,
                },
            ],
        },
        created_at="2026-06-20T10:00:00+00:00",
    )

    assert signal is None


def test_property_scout_zero_match_external_id_rolls_by_day() -> None:
    from app.services.proactive_signal_discovery import _property_scout_zero_match_external_id

    payload = {
        "scanned_listing_total": 71,
        "filtered_low_fit_total": 71,
        "sources": [
            {
                "source_label": "Willhaben Wien rentals",
                "source_url": "https://example.test/willhaben",
                "raw_listing_total": 60,
                "filtered_low_fit_total": 60,
            },
            {
                "source_label": "IMMMO Wien rentals",
                "source_url": "https://example.test/immmo",
                "raw_listing_total": 11,
                "filtered_low_fit_total": 11,
            },
        ],
    }

    day_one = _property_scout_zero_match_external_id(payload, created_at="2026-06-20T10:00:00+00:00")
    same_day = _property_scout_zero_match_external_id(payload, created_at="2026-06-20T23:59:00+00:00")
    next_day = _property_scout_zero_match_external_id(payload, created_at="2026-06-21T00:01:00+00:00")

    assert day_one == same_day
    assert day_one != next_day
