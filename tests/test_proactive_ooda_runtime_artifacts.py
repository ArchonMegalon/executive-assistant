from __future__ import annotations

from pathlib import Path

from app.services import proactive_ooda_runtime_artifacts as artifacts


def test_overlay_current_source_health_prefers_newer_primary_receipt() -> None:
    primary_path = Path("/tmp/proactive_ooda_latest_run.generated.json")
    archived_path = Path("/tmp/proactive_ooda_run_receipts/sent.json")
    primary = {
        "generated_at": "2026-07-08T15:30:34.750282+00:00",
        "source_health": {
            "present": True,
            "issue_count": 1,
            "issues": [
                {
                    "source_key": "google_workspace",
                    "error_code": "google_oauth_invalid_grant",
                    "recovery_mode": "scheduler_cooldown",
                    "blocked_until": "2026-07-08T21:29:49.591351Z",
                    "cooldown_active": True,
                }
            ],
        },
    }
    archived = {
        "generated_at": "2026-07-08T15:27:32.832947+00:00",
        "notification_status": "sent",
        "source_health": {
            "present": True,
            "issue_count": 1,
            "issues": [
                {
                    "source_key": "google_workspace",
                    "error_code": "google_oauth_invalid_grant",
                }
            ],
        },
    }

    merged = artifacts._overlay_current_source_health(
        primary_run_receipt_path=primary_path,
        primary_run_receipt=primary,
        run_receipt_path=archived_path,
        run_receipt=archived,
    )

    assert merged["notification_status"] == "sent"
    assert merged["source_health"]["issues"][0]["recovery_mode"] == "scheduler_cooldown"
    assert merged["source_health"]["issues"][0]["blocked_until"] == "2026-07-08T21:29:49.591351Z"


def test_overlay_current_source_health_keeps_selected_receipt_when_primary_is_older() -> None:
    primary = {
        "generated_at": "2026-07-08T15:27:32.832947+00:00",
        "source_health": {"present": False},
    }
    selected = {
        "generated_at": "2026-07-08T15:30:34.750282+00:00",
        "source_health": {
            "present": True,
            "issues": [{"source_key": "google_workspace", "error_code": "google_oauth_invalid_grant"}],
        },
    }

    merged = artifacts._overlay_current_source_health(
        primary_run_receipt_path=Path("/tmp/proactive_ooda_latest_run.generated.json"),
        primary_run_receipt=primary,
        run_receipt_path=Path("/tmp/proactive_ooda_run_receipts/sent.json"),
        run_receipt=selected,
    )

    assert merged == selected
