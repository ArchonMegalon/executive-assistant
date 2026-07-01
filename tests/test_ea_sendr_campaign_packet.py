from __future__ import annotations

from pathlib import Path

import pytest

from app.domain.outreach.sendr_campaign import build_sendr_campaign_packet
from app.services.ea_outreach_policy import validate_sendr_campaign_packet
from scripts.verify_ea_sendr_campaign_packet import verify


def test_builds_founder_demo_packet_with_fail_closed_defaults(tmp_path: Path) -> None:
    root = tmp_path
    (root / ".codex-design" / "ea").mkdir(parents=True)
    (root / ".codex-design" / "ea" / "VISION.md").write_text("Morning brief and review before send.\n", encoding="utf-8")

    packet = build_sendr_campaign_packet(
        campaign_type="FOUNDER_DEMO_OUTREACH",
        packet_id="ea-founder-demo-review-before-send-001",
        expires_at="2026-07-15T00:00:00Z",
        root=root,
    )

    assert packet["contract_name"] == "ea.sendr_campaign_packet.v1"
    assert packet["campaign_type"] == "FOUNDER_DEMO_OUTREACH"
    assert packet["channels"]["email"] is True
    assert packet["channels"]["whatsapp"] is False
    assert packet["sendr_features_allowed"]["whatsapp"] is False
    assert packet["direct_send_allowed"] is False
    assert packet["auto_reply_allowed"] is False
    assert packet["private_workspace_data_allowed"] is False
    assert packet["human_review_required"] is True
    assert packet["source_material"][0]["classification"] == "approved_public"
    assert len(packet["source_material"][0]["sha256"]) == 64


def test_verifier_accepts_default_packet(tmp_path: Path) -> None:
    packet = build_sendr_campaign_packet(
        campaign_type="TRUST_AND_APPROVAL_CAMPAIGN",
        packet_id="ea-trust-approval-001",
        expires_at="2026-07-15T00:00:00Z",
        root=tmp_path,
    )
    path = tmp_path / "packet.json"
    path.write_text(__import__("json").dumps(packet), encoding="utf-8")

    receipt = verify(path)

    assert receipt["status"] == "pass"
    assert receipt["validation"]["human_review"] == "pass"


def test_verifier_blocks_forbidden_claim_and_direct_send(tmp_path: Path) -> None:
    packet = build_sendr_campaign_packet(
        campaign_type="GOOGLE_WORKSPACE_WORKFLOW",
        packet_id="ea-google-workflow-001",
        expires_at="2026-07-15T00:00:00Z",
        root=tmp_path,
    )
    packet["message_copy"] = "EA sends autonomously without review and guarantees inbox zero."
    packet["direct_send_allowed"] = True
    path = tmp_path / "packet.json"
    path.write_text(__import__("json").dumps(packet), encoding="utf-8")

    receipt = verify(path)
    codes = {issue["code"] for issue in receipt["issues"]}

    assert receipt["status"] == "blocked"
    assert "forbidden_product_claim" in codes
    assert "direct_send_enabled" in codes


def test_unsupported_campaign_type_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsupported_sendr_campaign_type"):
        build_sendr_campaign_packet(
            campaign_type="BROAD_SPAM_BLAST",
            packet_id="bad",
            root=tmp_path,
        )


def test_private_workspace_material_blocks_packet(tmp_path: Path) -> None:
    packet = build_sendr_campaign_packet(
        campaign_type="FOUNDER_DEMO_OUTREACH",
        packet_id="ea-founder-demo-privacy-block",
        expires_at="2026-07-15T00:00:00Z",
        root=tmp_path,
    )
    packet["source_material"] = [{"path": "raw_gmail/export.json", "sha256": "x", "classification": "private"}]

    receipt = validate_sendr_campaign_packet(packet)
    codes = {issue["code"] for issue in receipt["issues"]}

    assert receipt["status"] == "blocked"
    assert "source_material_not_approved_public" in codes
    assert "private_workspace_data_requested" in codes
