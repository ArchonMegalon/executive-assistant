from __future__ import annotations

from app.services.proactive_ooda_service import ProactiveOodaService, format_telegram_digest
from scripts import run_proactive_ooda


def test_google_workspace_source_health_signal_reaches_user_digest() -> None:
    root_module = getattr(run_proactive_ooda, "_module", run_proactive_ooda)
    signal = root_module._workspace_source_error_signal(Exception("google_oauth_invalid_grant"))  # noqa: SLF001

    source_health = signal["payload"]["source_health"]
    ooda_loop = signal["payload"]["ooda_loop"]

    assert source_health["user_action_required"] is True
    assert ooda_loop["decide"]["approval_required"] is True
    assert ooda_loop["decide"]["user_action_required"] is True

    service = ProactiveOodaService()
    digest = service.build_digest(principal_id="principal-1", signals=[signal])

    assert len(digest.items) == 1
    assert digest.items[0].approval_required is True

    text = format_telegram_digest(digest)
    assert text.startswith("EA needs your decision")
    assert "Repair the source or accept that EA will miss reminders from it." in text
    assert "Reauthorize Google for the EA principal" in text


def test_generic_source_health_signal_stays_internal_when_no_user_action_is_needed() -> None:
    root_module = getattr(run_proactive_ooda, "_module", run_proactive_ooda)
    signal = root_module._source_error_signals(("table_mapping_missing",), source_label="postgres_observations")[0]  # noqa: SLF001

    source_health = signal["payload"]["source_health"]
    ooda_loop = signal["payload"]["ooda_loop"]

    assert source_health["user_action_required"] is False
    assert ooda_loop["decide"]["approval_required"] is False

    service = ProactiveOodaService()
    digest = service.build_digest(principal_id="principal-1", signals=[signal])

    assert digest.items == ()


def test_source_health_summary_promotes_google_reauth_issue_to_user_action_required() -> None:
    root_module = getattr(run_proactive_ooda, "_module", run_proactive_ooda)
    row = {
        "signal_type": "proactive_source_health",
        "channel": "proactive_runtime",
        "source_ref": "proactive_source_error:google_workspace:deadbeef",
        "payload": {
            "source_health": {
                "source_key": "google_workspace",
                "source_type": "google_workspace",
                "status": "unhealthy",
                "error_code": "google_oauth_invalid_grant",
                "next_action": "reauthorize_google_workspace_binding",
                "operator_action_required": True,
                "user_action_required": False,
            }
        },
    }

    summary = root_module._source_health_summary([row])  # noqa: SLF001

    assert summary["user_action_required"] is True
    assert summary["issues"][0]["user_action_required"] is True
