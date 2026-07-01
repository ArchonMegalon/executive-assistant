from __future__ import annotations

from app.services.proactive_ooda_operator_actions import proactive_next_action_surface


def test_proactive_next_action_surface_maps_google_reauth() -> None:
    surface = proactive_next_action_surface("reauthorize_google_workspace_binding")

    assert surface == {
        "href": "https://myexternalbrain.com/app/actions/google/connect?return_to=%2Fapp%2Fsettings%2Fgoogle&scope_bundle=full_workspace",
        "label": "Reconnect Google workspace",
        "method": "get",
    }


def test_proactive_next_action_surface_maps_whatsapp_qr_recovery() -> None:
    surface = proactive_next_action_surface("scan_whatsapp_web_qr")

    assert surface == {
        "href": "https://myexternalbrain.com/integrations/whatsapp",
        "label": "Open WhatsApp pairing",
        "method": "get",
    }


def test_proactive_next_action_surface_maps_approval_capture() -> None:
    surface = proactive_next_action_surface(
        "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome"
    )

    assert surface == {
        "href": "https://myexternalbrain.com/admin/proactive-ooda/approval",
        "label": "Open approval capture",
        "method": "get",
    }


def test_proactive_next_action_surface_maps_pocket_transcript_sync() -> None:
    surface = proactive_next_action_surface("sync_pocket_ai_audio_transcripts")

    assert surface == {
        "href": "https://myexternalbrain.com/app/api/signals/pocket/sync?limit=10",
        "label": "Sync Pocket transcripts",
        "method": "post",
    }


def test_proactive_next_action_surface_maps_google_workspace_sync() -> None:
    surface = proactive_next_action_surface("reauthorize_or_sync_google_workspace_sources")

    assert surface == {
        "href": "https://myexternalbrain.com/app/actions/signals/google/sync?return_to=%2Fapp%2Fsettings%2Fgoogle",
        "label": "Sync Google workspace",
        "method": "get",
    }


def test_proactive_next_action_surface_maps_source_coverage_probe_to_goals() -> None:
    surface = proactive_next_action_surface("probe_proactive_source_coverage")

    assert surface == {
        "href": "https://myexternalbrain.com/admin/goals",
        "label": "Open goals",
        "method": "get",
    }


def test_proactive_next_action_surface_maps_context_grounding_repair_to_today() -> None:
    surface = proactive_next_action_surface("repair_proactive_context_grounding")

    assert surface == {
        "href": "https://myexternalbrain.com/app/today",
        "label": "Open Today",
        "method": "get",
    }


def test_proactive_next_action_surface_maps_safe_work_audit_repair() -> None:
    surface = proactive_next_action_surface("repair_proactive_safe_work_audit")

    assert surface == {
        "href": "https://myexternalbrain.com/app/queue",
        "label": "Review safe work",
        "method": "get",
    }


def test_proactive_next_action_surface_returns_blank_for_unknown_action() -> None:
    surface = proactive_next_action_surface("unknown_action")

    assert surface == {"href": "", "label": "", "method": ""}
