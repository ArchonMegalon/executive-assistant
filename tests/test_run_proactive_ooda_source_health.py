from __future__ import annotations

from types import SimpleNamespace
import sys

from scripts import run_proactive_ooda as script


def _args(**overrides):
    base = {
        "signals_json": "",
        "discovery_json": "",
        "opportunity_rules_json": "",
        "personal_rules_json": "",
        "include_goal_action_queue": False,
        "goal_posture_json": "",
        "goal_action_queue_limit": 0,
        "goal_action_operator_streams": "",
        "skip_observation_source": True,
        "skip_workspace_source": False,
        "principal_id": "exec-1",
        "email_limit": 5,
        "calendar_limit": 5,
        "gmail_query": "",
        "observation_limit": 0,
        "observation_lookback_hours": 0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_load_signals_surfaces_active_google_workspace_runtime_cooldown(monkeypatch) -> None:
    rows = [
        SimpleNamespace(
            channel="product",
            event_type="google_workspace_signal_sync_recovery_blocked",
            created_at="2026-07-08T15:00:28Z",
            payload={
                "reason": "google_oauth_invalid_grant",
                "blocked_until": "2026-07-08T21:00:28Z",
                "cooldown_seconds": 21600,
                "cooldown_active": True,
                "recovery_mode": "scheduler_cooldown",
            },
        ),
    ]
    workspace_calls: list[dict[str, object]] = []
    container = SimpleNamespace(
        channel_runtime=SimpleNamespace(
            list_recent_observations=lambda limit, principal_id: list(rows),
        )
    )
    monkeypatch.setattr(script, "_build_postgres_container_for_script", lambda: container)
    monkeypatch.setitem(
        sys.modules,
        "app.services.google_oauth",
        SimpleNamespace(
            list_recent_workspace_signals=lambda **kwargs: workspace_calls.append(dict(kwargs)) or None,
        ),
    )

    signals = script._load_signals(
        _args(),
        state_store=None,
        persist_opportunity_state=False,
    )

    assert workspace_calls == []
    assert len(signals) == 1
    issue = dict(signals[0]["payload"]["source_health"])
    assert issue["source_key"] == "google_workspace"
    assert issue["error_code"] == "google_oauth_invalid_grant"
    assert issue["recovery_mode"] == "scheduler_cooldown"
    assert issue["blocked_until"] == "2026-07-08T21:00:28Z"
    assert issue["cooldown_active"] is True
    assert issue["cooldown_seconds_remaining"] > 0
    assert "bounded recovery cooldown" in str(signals[0]["summary"])


def test_workspace_source_error_signal_preserves_runtime_cooldown_fields() -> None:
    signal = script._workspace_source_error_signal(
        RuntimeError("google_oauth_invalid_grant"),
        cooldown_state={
            "reason": "google_oauth_invalid_grant",
            "blocked_until": "2026-07-08T21:00:28Z",
            "last_observed_at": "2026-07-08T15:00:28Z",
            "seconds_remaining": 3600,
            "recovery_mode": "scheduler_cooldown",
            "active": True,
        },
    )

    issue = dict(signal["payload"]["source_health"])
    assert issue["error_code"] == "google_oauth_invalid_grant"
    assert issue["recovery_mode"] == "scheduler_cooldown"
    assert issue["blocked_until"] == "2026-07-08T21:00:28Z"
    assert issue["cooldown_active"] is True
    assert issue["cooldown_seconds_remaining"] == 3600
    assert issue["last_observed_at"] == "2026-07-08T15:00:28Z"
