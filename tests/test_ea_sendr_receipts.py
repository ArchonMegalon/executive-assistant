from __future__ import annotations

from app.domain.outreach.sendr_campaign import build_sendr_campaign_packet
from app.services.ea_outreach_receipts import build_sendr_campaign_receipt, build_sendr_engagement_receipt


def _packet() -> dict[str, object]:
    return build_sendr_campaign_packet(
        campaign_type="FOUNDER_DEMO_OUTREACH",
        packet_id="ea-founder-demo-review-before-send-001",
        expires_at="2026-07-15T00:00:00Z",
    )


def test_campaign_receipt_stays_review_required_in_dry_run() -> None:
    receipt = build_sendr_campaign_receipt(_packet(), dry_run=True, generated_at="2026-07-01T00:00:00Z")

    assert receipt["contract_name"] == "ea.sendr_campaign_receipt.v1"
    assert receipt["status"] == "setup_review_required"
    assert receipt["validation_status"] == "pass"
    assert receipt["direct_send_allowed"] is False
    assert receipt["limited_send_allowed"] is False
    assert receipt["auto_reply_allowed"] is False
    assert receipt["sendr"]["campaign_id"] == ""
    assert len(receipt["source_packet_sha256"]) == 64


def test_campaign_receipt_records_blocked_recipients() -> None:
    recipient = {
        "recipient_basis": "raw_gmail_contact",
        "source_url_or_note": "",
        "allowed_channel": "whatsapp",
        "suppression_status": "bounce",
        "last_verified_at": "",
    }

    receipt = build_sendr_campaign_receipt(_packet(), recipients=[recipient], dry_run=True)

    assert receipt["status"] == "blocked"
    assert receipt["recipient_policy"]["blocked_recipient_count"] == 1
    assert receipt["validation"]["recipient_basis"] == "blocked"


def test_reply_event_creates_review_candidate_not_auto_action() -> None:
    receipt = build_sendr_engagement_receipt(
        campaign_id="ea:sendr:founder-demo-001",
        event_batch_id="batch-1",
        generated_at="2026-07-01T00:00:00Z",
        events=[
            {
                "event_type": "reply_received",
                "recipient_hash": "recipient-hash",
                "occurred_at": "2026-07-01T00:00:00Z",
                "body": "Interested, can you send the demo?",
            }
        ],
    )

    assert receipt["contract_name"] == "ea.sendr_engagement_batch.v1"
    assert receipt["status"] == "review_required"
    assert receipt["events"][0]["raw_body_stored"] is False
    assert receipt["events"][0]["human_review_required"] is True
    assert receipt["ea_actions"]["draft_reply_candidates"] == 1
    assert receipt["ea_actions"]["people_memory_candidates"] == 0
