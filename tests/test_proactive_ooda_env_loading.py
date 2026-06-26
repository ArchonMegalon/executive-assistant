from __future__ import annotations

import os
import json
from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.proactive_ooda_service import JsonOodaStateStore, ProactiveOodaService, build_run_receipt

import scripts.run_proactive_ooda as runner
import scripts.verify_proactive_ooda as verifier


def test_dotenv_loader_fills_missing_values_without_overriding(tmp_path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            (
                "EA_PROACTIVE_OODA_PRINCIPAL_ID=from-file",
                'EA_PROACTIVE_OODA_DISCOVERY_JSON="{\\"sources\\":[]}"',
                "EXISTING_VALUE=from-file",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EXISTING_VALUE", "from-env")
    monkeypatch.delenv("EA_PROACTIVE_OODA_PRINCIPAL_ID", raising=False)

    runner._load_dotenv_if_present(env_path)

    assert os.environ["EA_PROACTIVE_OODA_PRINCIPAL_ID"] == "from-file"
    assert os.environ["EA_PROACTIVE_OODA_DISCOVERY_JSON"] == '{\\"sources\\":[]}'
    assert os.environ["EXISTING_VALUE"] == "from-env"


def test_verify_dotenv_loader_matches_runner(tmp_path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("EA_PROACTIVE_OODA_MAX_ITEMS=2\n", encoding="utf-8")
    monkeypatch.delenv("EA_PROACTIVE_OODA_MAX_ITEMS", raising=False)

    verifier._load_dotenv_if_present(env_path)

    assert os.environ["EA_PROACTIVE_OODA_MAX_ITEMS"] == "2"


def test_proactive_ooda_default_principal_is_generic_and_uses_runtime_default(monkeypatch) -> None:
    monkeypatch.delenv("EA_PROACTIVE_OODA_PRINCIPAL_ID", raising=False)
    monkeypatch.delenv("EA_DEFAULT_PRINCIPAL_ID", raising=False)

    assert runner._default_principal_id() == "principal-default"
    assert verifier._default_principal_id() == "principal-default"

    monkeypatch.setenv("EA_DEFAULT_PRINCIPAL_ID", "workspace-owner")
    assert runner._default_principal_id() == "workspace-owner"
    assert verifier._default_principal_id() == "workspace-owner"

    monkeypatch.setenv("EA_PROACTIVE_OODA_PRINCIPAL_ID", "proactive-owner")
    assert runner._default_principal_id() == "proactive-owner"
    assert verifier._default_principal_id() == "proactive-owner"


def test_dotenv_loader_ignores_missing_or_unreadable_paths(tmp_path) -> None:
    runner._load_dotenv_if_present(tmp_path / "missing.env")


def test_runner_ingests_all_available_sources_when_workspace_scan_fails(tmp_path, monkeypatch) -> None:
    signal_file = tmp_path / "signals.json"
    signal_file.write_text(
        json.dumps(
            [
                {
                    "source_ref": "manual:1",
                    "title": "Decision needed today",
                    "summary": "Approve the action.",
                }
            ]
        ),
        encoding="utf-8",
    )

    from app import container as app_container
    from app.services import google_oauth

    monkeypatch.setattr(app_container, "build_container", lambda: object())
    monkeypatch.setattr(
        google_oauth,
        "list_recent_workspace_signals",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("google_oauth_invalid_grant")),
    )

    rows = runner._load_signals(
        SimpleNamespace(
            signals_json=str(signal_file),
            discovery_json="",
            opportunity_rules_json=json.dumps(
                {
                    "rules": [
                        {
                            "id": "generic-opportunity",
                            "title": "Prepare useful next step",
                            "summary": "EA can stage the next useful step.",
                            "trigger": {"kind": "always"},
                        }
                    ]
                }
            ),
            skip_observation_source=True,
            principal_id="exec",
            observation_limit=0,
            observation_lookback_hours=0,
            email_limit=1,
            calendar_limit=1,
            gmail_query="",
        )
    )

    source_refs = {str(row.get("source_ref") or "") for row in rows}
    assert "manual:1" in source_refs
    assert any(ref.startswith("opportunity:generic-opportunity:") for ref in source_refs)
    assert any(ref.startswith("proactive_source_error:google_workspace:") for ref in source_refs)


def test_runner_quiet_hours_defer_non_high_priority_digest() -> None:
    digest = ProactiveOodaService().build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "opportunity:vendor-review",
                "signal_type": "opportunity",
                "channel": "assistant_opportunity",
                "title": "Review vendor options",
                "summary": "Review the provider notes.",
            }
        ],
    )
    args = SimpleNamespace(
        quiet_hours_start="22:00",
        quiet_hours_end="07:00",
        quiet_hours_timezone="UTC",
        quiet_hours_allow_high_priority=True,
    )

    reason = runner._quiet_hours_defer_reason(
        args,
        digest,
        now=datetime(2026, 6, 26, 23, 30, tzinfo=timezone.utc),
    )

    assert reason == "deferred_by_quiet_hours"


def test_runner_quiet_hours_can_allow_high_priority_digest() -> None:
    digest = ProactiveOodaService().build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "gmail:approval",
                "signal_type": "email_thread",
                "channel": "gmail",
                "title": "Approval needed today",
                "summary": "Approve the provider renewal today.",
            }
        ],
    )
    args = SimpleNamespace(
        quiet_hours_start="22:00",
        quiet_hours_end="07:00",
        quiet_hours_timezone="UTC",
        quiet_hours_allow_high_priority=True,
    )

    reason = runner._quiet_hours_defer_reason(
        args,
        digest,
        now=datetime(2026, 6, 26, 23, 30, tzinfo=timezone.utc),
    )

    assert reason == ""


def test_runner_quiet_hours_can_defer_high_priority_when_configured() -> None:
    digest = ProactiveOodaService().build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "gmail:approval",
                "signal_type": "email_thread",
                "channel": "gmail",
                "title": "Approval needed today",
                "summary": "Approve the provider renewal today.",
            }
        ],
    )
    args = SimpleNamespace(
        quiet_hours_start="22:00",
        quiet_hours_end="07:00",
        quiet_hours_timezone="UTC",
        quiet_hours_allow_high_priority=False,
    )

    reason = runner._quiet_hours_defer_reason(
        args,
        digest,
        now=datetime(2026, 6, 26, 23, 30, tzinfo=timezone.utc),
    )

    assert reason == "deferred_by_quiet_hours"


def test_runner_deferred_digest_clears_notified_refs() -> None:
    digest = ProactiveOodaService().build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "opportunity:quiet",
                "signal_type": "opportunity",
                "channel": "assistant_opportunity",
                "title": "Review vendor options",
                "summary": "Review the provider notes.",
            }
        ],
    )

    deferred = runner._without_notified_refs(digest)
    receipt = build_run_receipt(digest=deferred, dry_run=False, error_code="deferred_by_quiet_hours")

    assert digest.notified_refs == ("opportunity:quiet",)
    assert deferred.items == digest.items
    assert deferred.notified_refs == ()
    assert receipt.notification_status == "deferred"
    assert receipt.notified_ref_hashes == ()


def test_runner_operator_pause_defers_actionable_digest() -> None:
    digest = ProactiveOodaService().build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "opportunity:pause",
                "signal_type": "opportunity",
                "channel": "assistant_opportunity",
                "title": "Review vendor options",
                "summary": "Review the provider notes.",
            }
        ],
    )
    args = SimpleNamespace(paused=True, pause_reason="maintenance")

    reason = runner._operator_pause_defer_reason(args, digest)
    deferred = runner._without_notified_refs(digest)
    receipt = build_run_receipt(digest=deferred, dry_run=False, error_code=reason)

    assert reason == "deferred_by_operator_pause"
    assert deferred.notified_refs == ()
    assert receipt.notification_status == "deferred"
    assert receipt.notified_ref_hashes == ()


def test_runner_interruption_budget_defers_when_window_is_exhausted(tmp_path) -> None:
    state_store = JsonOodaStateStore(tmp_path / "state.json")
    state_store.save_interruption_events(
        "exec",
        [
            "2026-06-26T10:00:00+00:00",
            "2026-06-26T11:00:00+00:00",
        ],
    )
    digest = ProactiveOodaService().build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "opportunity:vendor-review",
                "signal_type": "opportunity",
                "channel": "assistant_opportunity",
                "title": "Review vendor options",
                "summary": "Review the provider notes.",
            }
        ],
    )
    args = SimpleNamespace(
        interruption_budget_limit=2,
        interruption_budget_window_hours=24,
        interruption_budget_allow_high_priority=True,
    )

    reason = runner._interruption_budget_defer_reason(
        args,
        state_store=state_store,
        principal_id="exec",
        digest=digest,
        now=datetime(2026, 6, 26, 12, 0, tzinfo=timezone.utc),
    )

    assert reason == "deferred_by_interruption_budget"


def test_runner_interruption_budget_allows_high_priority_when_configured(tmp_path) -> None:
    state_store = JsonOodaStateStore(tmp_path / "state.json")
    state_store.save_interruption_events("exec", ["2026-06-26T10:00:00+00:00"])
    digest = ProactiveOodaService().build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "gmail:approval",
                "signal_type": "email_thread",
                "channel": "gmail",
                "title": "Approval needed today",
                "summary": "Approve the provider renewal today.",
            }
        ],
    )
    args = SimpleNamespace(
        interruption_budget_limit=1,
        interruption_budget_window_hours=24,
        interruption_budget_allow_high_priority=True,
    )

    reason = runner._interruption_budget_defer_reason(
        args,
        state_store=state_store,
        principal_id="exec",
        digest=digest,
        now=datetime(2026, 6, 26, 12, 0, tzinfo=timezone.utc),
    )

    assert reason == ""


def test_runner_interruption_budget_records_and_prunes_window(tmp_path) -> None:
    state_store = JsonOodaStateStore(tmp_path / "state.json")
    state_store.save_interruption_events(
        "exec",
        [
            "2026-06-24T10:00:00+00:00",
            "2026-06-26T10:00:00+00:00",
        ],
    )
    args = SimpleNamespace(interruption_budget_window_hours=24)

    runner._record_interruption_event(
        args,
        state_store=state_store,
        principal_id="exec",
        occurred_at="2026-06-26T12:00:00+00:00",
    )

    assert state_store.load_interruption_events("exec") == (
        "2026-06-26T10:00:00+00:00",
        "2026-06-26T12:00:00+00:00",
    )
