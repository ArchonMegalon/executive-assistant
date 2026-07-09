from __future__ import annotations

import json
from pathlib import Path

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
