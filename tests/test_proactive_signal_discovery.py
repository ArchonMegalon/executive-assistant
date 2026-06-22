from __future__ import annotations

import json
from io import BytesIO

from app.services.proactive_signal_discovery import (
    discover_signals,
    discover_signals_resilient,
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


def test_observation_mapper_summarizes_property_scout_counts() -> None:
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

    assert signal is not None
    assert signal.title == "Property scout found items to review"
    assert "2 high-fit" in signal.summary
    assert "4 review" in signal.summary


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
