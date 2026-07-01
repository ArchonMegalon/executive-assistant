from __future__ import annotations

from app.domain.outreach.sendr_campaign import build_sendr_campaign_packet
from app.services.ea_outreach_policy import validate_sendr_campaign_packet


def _packet() -> dict[str, object]:
    return build_sendr_campaign_packet(
        campaign_type="FOUNDER_DEMO_OUTREACH",
        packet_id="ea-founder-demo-review-before-send-001",
        expires_at="2026-07-15T00:00:00Z",
    )


def test_raw_gmail_and_calendar_sources_are_rejected() -> None:
    packet = _packet()
    packet["allowed_inputs"] = ["raw_gmail", "raw calendar"]

    receipt = validate_sendr_campaign_packet(packet)

    assert receipt["status"] == "blocked"
    assert {"private_workspace_data_requested"} <= {issue["code"] for issue in receipt["issues"]}


def test_people_memory_and_customer_drafts_are_rejected() -> None:
    packet = _packet()
    packet["message_copy"] = "Use people memory and a draft reply from a real workspace."

    receipt = validate_sendr_campaign_packet(packet)

    assert receipt["status"] == "blocked"
    assert "private_workspace_data_requested" in {issue["code"] for issue in receipt["issues"]}


def test_recipient_without_basis_is_rejected() -> None:
    packet = _packet()
    recipient = {
        "source_url_or_note": "manual note",
        "allowed_channel": "email",
        "suppression_status": "clear",
        "last_verified_at": "2026-07-01T00:00:00Z",
    }

    receipt = validate_sendr_campaign_packet(packet, recipients=[recipient])

    assert receipt["status"] == "blocked"
    assert "recipient_0_recipient_basis_missing_or_forbidden" in {issue["code"] for issue in receipt["issues"]}


def test_public_business_contact_with_review_before_send_passes() -> None:
    packet = _packet()
    packet["message_copy"] = "EA turns Gmail and Calendar into a morning brief. Nothing sensitive sends without review."
    recipient = {
        "recipient_basis": "public_business_contact",
        "source_url_or_note": "public company contact page",
        "allowed_channel": "email",
        "suppression_status": "clear",
        "last_verified_at": "2026-07-01T00:00:00Z",
    }

    receipt = validate_sendr_campaign_packet(packet, recipients=[recipient])

    assert receipt["status"] == "pass"


def test_suppression_blocks_send() -> None:
    packet = _packet()
    recipient = {
        "recipient_basis": "prior_conversation",
        "source_url_or_note": "demo request",
        "allowed_channel": "email",
        "suppression_status": "unsubscribe",
        "last_verified_at": "2026-07-01T00:00:00Z",
    }

    receipt = validate_sendr_campaign_packet(packet, recipients=[recipient])

    assert receipt["status"] == "blocked"
    assert receipt["validation"]["suppression"] == "blocked"


def test_direct_send_auto_reply_and_whatsapp_default_disabled() -> None:
    packet = _packet()

    assert packet["direct_send_allowed"] is False
    assert packet["auto_reply_allowed"] is False
    assert packet["channels"]["whatsapp"] is False
    assert validate_sendr_campaign_packet(packet)["status"] == "pass"
