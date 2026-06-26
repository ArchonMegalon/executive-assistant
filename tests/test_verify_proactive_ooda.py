from __future__ import annotations

import json
from argparse import Namespace

import scripts.run_proactive_ooda as runner
import scripts.verify_proactive_ooda as verifier
from app.services.proactive_ooda_service import ProactiveSignal


def _stub_empty_workspace(monkeypatch) -> None:
    from app import container as app_container
    from app.services import google_oauth

    monkeypatch.setattr(app_container, "build_container", lambda: object())
    monkeypatch.setattr(google_oauth, "list_recent_workspace_signals", lambda **_kwargs: Namespace(signals=()))


def test_verify_proactive_ooda_accepts_static_signal_source(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("EA_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("EA_PROACTIVE_OODA_TELEGRAM_CHAT_ID", raising=False)
    signal_file = tmp_path / "signals.json"
    signal_file.write_text(
        json.dumps(
            [
                {
                    "source_ref": "operator:approval",
                    "title": "Approval needed today",
                    "summary": "Approve the provider renewal.",
                }
            ]
        ),
        encoding="utf-8",
    )

    report = verifier._build_report(
        Namespace(
            principal_id="exec",
            signals_json=str(signal_file),
            discovery_json="",
            state_path=str(tmp_path / "state.json"),
            max_items=5,
            observation_lookback_hours=24,
            observation_limit=50,
            skip_observation_source=True,
            require_source=True,
            require_telegram=False,
            require_receipt_observation=False,
        )
    )

    assert report["ok"] is True
    assert report["source_mode"] == "signals_json"
    assert report["signal_count"] == 1
    assert report["actionable_count"] == 1


def test_verify_proactive_ooda_aggregates_static_discovery_and_observations(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("EA_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("EA_PROACTIVE_OODA_TELEGRAM_CHAT_ID", raising=False)
    signal_file = tmp_path / "signals.json"
    signal_file.write_text(
        json.dumps(
            [
                {
                    "source_ref": "operator:approval",
                    "title": "Approval needed today",
                    "summary": "Approve the provider renewal.",
                }
            ]
        ),
        encoding="utf-8",
    )
    discovery_file = tmp_path / "discovery.json"
    discovery_file.write_text(
        json.dumps(
            [
                {
                    "source_ref": "market:contract",
                    "title": "Contract review due tomorrow",
                    "summary": "Review the supplier risk before renewal.",
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        verifier,
        "discover_postgres_observation_signals",
        lambda **_kwargs: [
            ProactiveSignal(
                source_ref="observation:reply",
                signal_type="telegram_message",
                channel="telegram",
                title="Reply needed today",
                summary="Reply to the operator before the deadline.",
            )
        ],
    )

    report = verifier._build_report(
        Namespace(
            principal_id="exec",
            signals_json=str(signal_file),
            discovery_json=json.dumps({"sources": [{"type": "json", "path": str(discovery_file)}]}),
            state_path=str(tmp_path / "state.json"),
            max_items=5,
            observation_lookback_hours=24,
            observation_limit=50,
            skip_observation_source=False,
            require_source=True,
            require_telegram=False,
            require_receipt_observation=False,
        )
    )

    assert report["ok"] is True
    assert report["source_mode"] == "signals_json+discovery_json+postgres_observations"
    assert report["signal_count"] == 3
    assert report["actionable_count"] == 3


def test_runner_load_signals_aggregates_configured_sources_and_observations(tmp_path, monkeypatch) -> None:
    _stub_empty_workspace(monkeypatch)
    signal_file = tmp_path / "signals.json"
    signal_file.write_text(
        json.dumps([{"source_ref": "static:1", "title": "Approval needed", "summary": "Approve this."}]),
        encoding="utf-8",
    )
    discovery_file = tmp_path / "discovery.json"
    discovery_file.write_text(
        json.dumps([{"source_ref": "discovery:1", "title": "Review needed", "summary": "Review this."}]),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        runner,
        "discover_postgres_observation_signals",
        lambda **_kwargs: [
            ProactiveSignal(
                source_ref="observation:1",
                signal_type="office_signal",
                channel="observation",
                title="Decision needed",
                summary="Decide this.",
            )
        ],
    )

    signals = runner._load_signals(
        Namespace(
            principal_id="exec",
            signals_json=str(signal_file),
            discovery_json=json.dumps({"sources": [{"type": "json", "path": str(discovery_file)}]}),
            observation_lookback_hours=24,
            observation_limit=50,
            skip_observation_source=False,
            email_limit=8,
            calendar_limit=8,
            gmail_query="",
        )
    )

    assert [signal["source_ref"] for signal in signals] == ["static:1", "discovery:1", "observation:1"]


def test_verify_proactive_ooda_warns_but_passes_when_one_discovery_source_fails(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("EA_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("EA_PROACTIVE_OODA_TELEGRAM_CHAT_ID", raising=False)
    good_file = tmp_path / "good.json"
    missing_file = tmp_path / "missing-private-feed.json"
    good_file.write_text(
        json.dumps([{"source_ref": "good:1", "title": "Approval needed", "summary": "Approve this today."}]),
        encoding="utf-8",
    )

    report = verifier._build_report(
        Namespace(
            principal_id="exec",
            signals_json="",
            discovery_json=json.dumps(
                {
                    "sources": [
                        {"type": "json", "path": str(missing_file), "channel": "teable_admin"},
                        {"type": "json", "path": str(good_file), "channel": "teable_admin"},
                    ]
                }
            ),
            state_path=str(tmp_path / "state.json"),
            max_items=5,
            observation_lookback_hours=24,
            observation_limit=50,
            skip_observation_source=True,
            require_source=True,
            require_telegram=False,
            require_receipt_observation=False,
        )
    )

    assert report["ok"] is True
    assert report["source_mode"] == "discovery_json"
    assert report["signal_count"] == 1
    assert report["warnings"][0].startswith("discovery_source_failed:teable_admin:json:FileNotFoundError:")
    assert str(missing_file) not in report["warnings"][0]
    assert "missing-private-feed" not in report["warnings"][0]


def test_runner_load_signals_continues_after_discovery_failure(tmp_path, monkeypatch) -> None:
    _stub_empty_workspace(monkeypatch)
    missing_file = tmp_path / "missing.json"
    monkeypatch.setattr(
        runner,
        "discover_postgres_observation_signals",
        lambda **_kwargs: [
            ProactiveSignal(
                source_ref="observation:still-loaded",
                signal_type="office_signal",
                channel="observation",
                title="Decision needed",
                summary="Decide this.",
            )
        ],
    )

    signals = runner._load_signals(
        Namespace(
            principal_id="exec",
            signals_json="",
            discovery_json=json.dumps({"sources": [{"type": "json", "path": str(missing_file)}]}),
            observation_lookback_hours=24,
            observation_limit=50,
            skip_observation_source=False,
            email_limit=8,
            calendar_limit=8,
            gmail_query="",
        )
    )

    source_refs = [signal["source_ref"] for signal in signals]
    assert "observation:still-loaded" in source_refs
    assert any(ref.startswith("proactive_source_error:discovery:") for ref in source_refs)


def test_verify_proactive_ooda_fails_enabled_without_source_or_telegram(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("EA_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("EA_PROACTIVE_OODA_TELEGRAM_CHAT_ID", raising=False)

    report = verifier._build_report(
        Namespace(
            principal_id="exec",
            signals_json="",
            discovery_json="",
            state_path=str(tmp_path / "state.json"),
            max_items=5,
            observation_lookback_hours=24,
            observation_limit=50,
            skip_observation_source=True,
            require_source=True,
            require_telegram=True,
            require_receipt_observation=False,
        )
    )

    assert report["ok"] is False
    assert "no_signal_source_configured" in report["errors"]
    assert "telegram_notification_not_configured" in report["errors"]


def test_verify_proactive_ooda_reports_unhealthy_workspace_source(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("EA_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("EA_PROACTIVE_OODA_TELEGRAM_CHAT_ID", raising=False)

    from app import container as app_container
    from app.services import google_oauth

    monkeypatch.setattr(app_container, "build_container", lambda: object())
    monkeypatch.setattr(
        google_oauth,
        "list_recent_workspace_signals",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("google_oauth_invalid_grant")),
    )

    report = verifier._build_report(
        Namespace(
            principal_id="exec",
            signals_json="",
            discovery_json="",
            opportunity_rules_json="",
            state_path=str(tmp_path / "state.json"),
            max_items=5,
            observation_lookback_hours=24,
            observation_limit=50,
            skip_observation_source=True,
            skip_workspace_source=False,
            require_source=True,
            require_telegram=False,
            require_receipt_observation=False,
        )
    )

    assert report["ok"] is False
    assert report["source_mode"] == "google_workspace_error"
    assert report["workspace_source_checked"] is True
    assert report["workspace_source_healthy"] is False
    assert report["errors"] == ["google_workspace_signal_source_unhealthy:RuntimeError"]
