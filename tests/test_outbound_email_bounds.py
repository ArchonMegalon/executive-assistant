from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import outbound_email_bounds


def test_outbound_email_guard_summary_prunes_stale_entries_and_caps_retained_keys(
    monkeypatch,
    tmp_path: Path,
) -> None:
    guard_path = tmp_path / "outbound_email_guard.json"
    guard_path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": {
                    "ea_registration_verification|stale@example.com": [
                        {
                            "attempt_id": "stale-1",
                            "attempted_at": 100.0,
                            "status": "sent",
                        }
                    ],
                    "ea_registration_verification|older@example.com": [
                        {
                            "attempt_id": "older-1",
                            "attempted_at": 950.0,
                            "status": "sent",
                        }
                    ],
                    "ea_registration_verification|recent@example.com": [
                        {
                            "attempt_id": "recent-1",
                            "attempted_at": 990.0,
                            "status": "sent",
                        }
                    ],
                    "ea_property_match_delivery|latest@example.com": [
                        {
                            "attempt_id": "latest-1",
                            "attempted_at": 995.0,
                            "status": "sent",
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_OUTBOUND_EMAIL_GUARD_STATE_PATH", str(guard_path))
    monkeypatch.setenv("EA_OUTBOUND_EMAIL_AUTH_WINDOW_SECONDS", "60")
    monkeypatch.setenv("EA_OUTBOUND_EMAIL_PROACTIVE_WINDOW_SECONDS", "60")
    monkeypatch.setenv("EA_OUTBOUND_EMAIL_GUARD_MAX_KEYS", "2")
    monkeypatch.setattr(outbound_email_bounds.time, "time", lambda: 1_000.0)

    summary = outbound_email_bounds.outbound_email_guard_summary(now=1_000.0)

    assert summary["status"] == "bounded"
    assert summary["entry_count"] == 2
    assert summary["attempt_count"] == 2
    assert summary["active_cooldown_count"] == 2
    assert summary["active_window_budget_count"] == 0
    assert summary["categories"]["auth"]["entry_count"] == 1
    assert summary["categories"]["proactive"]["entry_count"] == 1
    assert summary["most_recent_attempt_at"] == "1970-01-01T00:16:35Z"
    assert summary["privacy"] == {
        "raw_recipient_exposed": False,
        "raw_subject_exposed": False,
    }

    payload = json.loads(guard_path.read_text(encoding="utf-8"))
    assert sorted(payload["entries"]) == [
        "ea_property_match_delivery|latest@example.com",
        "ea_registration_verification|recent@example.com",
    ]


def test_failed_delivery_uses_short_retry_cooldown_but_sent_delivery_keeps_full_cooldown(
    monkeypatch,
    tmp_path: Path,
) -> None:
    guard_path = tmp_path / "outbound_email_guard.json"
    now = [1_000.0]
    monkeypatch.setenv("EA_OUTBOUND_EMAIL_GUARD_STATE_PATH", str(guard_path))
    monkeypatch.setenv("EA_OUTBOUND_EMAIL_AUTH_COOLDOWN_SECONDS", "600")
    monkeypatch.setenv("EA_OUTBOUND_EMAIL_FAILURE_COOLDOWN_SECONDS", "30")
    monkeypatch.setattr(outbound_email_bounds.time, "time", lambda: now[0])

    with pytest.raises(RuntimeError, match="provider unavailable"):
        with outbound_email_bounds.bounded_outbound_email(
            kind="ea_workspace_access_session",
            recipient_email="operator@example.com",
            provider="emailit",
        ):
            raise RuntimeError("provider unavailable")

    now[0] = 1_010.0
    with pytest.raises(outbound_email_bounds.OutboundEmailRateLimitedError) as retry_error:
        with outbound_email_bounds.bounded_outbound_email(
            kind="ea_workspace_access_session",
            recipient_email="operator@example.com",
            provider="emailit",
        ):
            pass
    assert retry_error.value.retry_after_seconds == 20

    now[0] = 1_031.0
    with outbound_email_bounds.bounded_outbound_email(
        kind="ea_workspace_access_session",
        recipient_email="operator@example.com",
        provider="emailit",
    ):
        pass

    now[0] = 1_061.0
    with pytest.raises(outbound_email_bounds.OutboundEmailRateLimitedError) as cooldown_error:
        with outbound_email_bounds.bounded_outbound_email(
            kind="ea_workspace_access_session",
            recipient_email="operator@example.com",
            provider="emailit",
        ):
            pass
    assert cooldown_error.value.retry_after_seconds == 570


def test_provider_retry_after_is_preserved_for_failed_delivery(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class ProviderRateLimit(RuntimeError):
        retry_after_seconds = 300

    guard_path = tmp_path / "outbound_email_guard.json"
    now = [2_000.0]
    monkeypatch.setenv("EA_OUTBOUND_EMAIL_GUARD_STATE_PATH", str(guard_path))
    monkeypatch.setenv("EA_OUTBOUND_EMAIL_AUTH_COOLDOWN_SECONDS", "600")
    monkeypatch.setenv("EA_OUTBOUND_EMAIL_AUTH_WINDOW_SECONDS", "3600")
    monkeypatch.setenv("EA_OUTBOUND_EMAIL_FAILURE_COOLDOWN_SECONDS", "30")
    monkeypatch.setattr(outbound_email_bounds.time, "time", lambda: now[0])

    with pytest.raises(ProviderRateLimit):
        with outbound_email_bounds.bounded_outbound_email(
            kind="ea_workspace_access_session",
            recipient_email="operator@example.com",
            provider="emailit",
        ):
            raise ProviderRateLimit("provider cooldown")

    now[0] = 2_100.0
    with pytest.raises(outbound_email_bounds.OutboundEmailRateLimitedError) as retry_error:
        with outbound_email_bounds.bounded_outbound_email(
            kind="ea_workspace_access_session",
            recipient_email="operator@example.com",
            provider="emailit",
        ):
            pass
    assert retry_error.value.retry_after_seconds == 200

    payload = json.loads(guard_path.read_text(encoding="utf-8"))
    attempts = payload["entries"]["ea_workspace_access_session|operator@example.com"]
    assert attempts[-1]["retry_after_seconds"] == 300
