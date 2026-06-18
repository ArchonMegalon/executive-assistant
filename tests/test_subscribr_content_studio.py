from __future__ import annotations

from datetime import datetime, timezone

from app.services.subscribr_content_studio import (
    build_ea_video_source_packet,
    build_subscribr_script_receipt,
    validate_ea_video_source_packet,
)


NOW = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)


def _release_source() -> dict[str, object]:
    return {
        "path": "PUBLIC_RELEASE_EXPERIENCE.yaml",
        "source_type": "public_release_receipt",
        "sha256": "a" * 64,
        "data_classification": "public",
    }


def test_chummer_strict_canon_packet_is_source_bound_and_publish_blocked() -> None:
    packet = build_ea_video_source_packet(
        packet_id="chummer-install-current-release",
        content_mode="STRICT_CANON",
        subscribr_channel_key="chummer-official",
        title="Installing Chummer",
        audience="new and returning players",
        sources=[_release_source()],
        required_claims=["Official downloads begin at chummer.run"],
        forbidden_claims=["GitHub is the official binary shelf"],
        source_git_head="abc123",
        now=NOW,
    )

    assert packet["status"] == "source_packet_approved"
    assert packet["research_policy"] == "provided_sources_only"
    assert packet["provider_agent_mode_enabled"] is False
    assert packet["publication_allowed"] is False
    assert packet["direct_publish_allowed"] is False
    assert packet["validation"]["status"] == "pass"


def test_chummer_subscribr_receipt_requires_claim_binding_and_never_allows_publication() -> None:
    packet = build_ea_video_source_packet(
        packet_id="chummer-install-current-release",
        content_mode="STRICT_CANON",
        subscribr_channel_key="chummer-official",
        title="Installing Chummer",
        audience="new and returning players",
        sources=[_release_source()],
        required_claims=["Official downloads begin at chummer.run"],
        forbidden_claims=["GitHub is the official binary shelf"],
        source_git_head="abc123",
        now=NOW,
    )

    receipt = build_subscribr_script_receipt(
        packet,
        script_markdown="Official downloads begin at chummer.run. Use the Windows or Linux installer shown on Downloads.",
        provider_job={"channel_id": "subscribr-channel-1", "idea_id": "idea-1", "script_id": "script-1"},
        current_source_git_head="abc123",
        now=NOW,
    )

    assert receipt["status"] == "review_required"
    assert receipt["provider"] == "subscribr"
    assert receipt["account_tier"] == "AppSumo Tier 7 / Scale 3"
    assert receipt["publication_allowed"] is False
    assert receipt["direct_publish_allowed"] is False
    assert receipt["provider_board_status_allowed_to_publish"] is False
    assert receipt["validation"]["source_binding"] == "pass"


def test_chummer_subscribr_blocks_agent_mode_for_strict_canon_and_private_sources() -> None:
    packet = build_ea_video_source_packet(
        packet_id="unsafe-chummer-script",
        content_mode="STRICT_CANON",
        subscribr_channel_key="chummer-academy",
        title="Rules explainer",
        audience="players",
        sources=[
            {
                "path": "private-runner-sheet.md",
                "source_type": "private_campaign_data",
                "sha256": "b" * 64,
                "data_classification": "private",
            }
        ],
        required_claims=["Chummer explains the calculation"],
        forbidden_claims=["sourcebook text may be copied"],
        source_git_head="abc123",
        provider_agent_mode_enabled=True,
        now=NOW,
    )

    validation = validate_ea_video_source_packet(packet, now=NOW)

    assert validation["status"] == "fail"
    assert "agent_mode_not_allowed_for_mode" in validation["issues"]
    assert "forbidden_source_type_private_campaign_data" in validation["issues"]
    assert "source_classification_not_publishable" in validation["issues"]
