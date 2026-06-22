from __future__ import annotations

from datetime import datetime, timezone
import hashlib

from app.services.premium_delivery import build_premium_delivery_packet


NOW = datetime(2026, 6, 18, 12, 0, 0, tzinfo=timezone.utc)


def _approved_source_packet() -> dict[str, object]:
    return {
        "packet_id": "board-pack-weekly-001",
        "title": "Weekly Board Preparation Book",
        "data_classification": "internal",
        "approval_status": "approved",
        "source_refs": [
            {"source_type": "ea_approved_html_memo", "path": "packets/board-pack.html"},
            {"source_type": "approved_release_receipt", "path": "receipts/release.json"},
        ],
        "content_html": "<h1>Weekly Board Preparation Book</h1><p>Approved board summary.</p>",
    }


def _private_source_packet() -> dict[str, object]:
    packet = _approved_source_packet()
    packet.update(
        {
            "packet_id": "board-pack-private-001",
            "data_classification": "board_private",
            "redaction_policy": {"status": "pass", "removed_fields": ["attendee_email", "raw_calendar_body"]},
            "access_policy": {
                "expires_at": "2026-06-25T00:00:00+00:00",
                "revocation_supported": True,
                "download_policy": "disabled",
                "viewer_analytics_policy": "aggregate_only",
                "no_public_indexing": True,
            },
        }
    )
    return packet


def test_premium_delivery_requires_approved_source_packet() -> None:
    packet = _approved_source_packet()
    packet["approval_status"] = "draft"

    receipt = build_premium_delivery_packet(packet, principal_id="principal-1", now=NOW)

    assert receipt["status"] == "blocked"
    assert "approved_source_packet_required" in receipt["blocking_reasons"]
    assert receipt["render_request"]["status"] == "blocked"  # type: ignore[index]
    assert receipt["publication_allowed"] is False
    assert receipt["direct_publish_allowed"] is False


def test_premium_delivery_blocks_forbidden_raw_workspace_sources() -> None:
    packet = _approved_source_packet()
    packet["source_refs"] = [{"source_type": "raw_gmail", "id": "mail-secret"}]

    receipt = build_premium_delivery_packet(packet, principal_id="principal-1", now=NOW)

    assert receipt["status"] == "blocked"
    assert receipt["validation"]["approved_source_packet"] == "fail"  # type: ignore[index]
    assert any("forbidden_source_type_raw_gmail" == reason for reason in receipt["blocking_reasons"])


def test_private_board_packet_requires_redaction_and_access_policy() -> None:
    packet = _approved_source_packet()
    packet["data_classification"] = "board_private"

    receipt = build_premium_delivery_packet(packet, principal_id="principal-1", now=NOW)

    assert receipt["status"] == "blocked"
    assert receipt["validation"]["private_redaction_access_policy"] == "fail"  # type: ignore[index]
    assert receipt["blocking_reasons"] == ["redaction_policy_required"]


def test_private_board_packet_with_policy_is_render_ready_and_hashes_artifact() -> None:
    source = _private_source_packet()
    rendered = b"%PDF-1.4\napproved packet\n%%EOF"

    receipt = build_premium_delivery_packet(
        source,
        principal_id="principal-1",
        workspace_id="workspace-1",
        rendered_artifact_bytes=rendered,
        rendered_filename="weekly-board-pack.pdf",
        fliplink_publication={"publication_id": "flip-123", "url": "https://fliplink.example/flip-123"},
        now=NOW,
    )

    assert receipt["status"] == "render_ready"
    assert receipt["blocking_reasons"] == []
    assert receipt["validation"]["private_redaction_access_policy"] == "pass"  # type: ignore[index]
    assert receipt["validation"]["artifact_hash"] == "pass"  # type: ignore[index]
    assert receipt["rendered_artifact"]["sha256"] == hashlib.sha256(rendered).hexdigest()  # type: ignore[index]
    assert receipt["rendered_artifact"]["filename"] == "weekly-board-pack.pdf"  # type: ignore[index]
    assert receipt["presentation"]["provider"] == "fliplink"  # type: ignore[index]
    assert receipt["presentation"]["owns_truth"] is False  # type: ignore[index]
    assert receipt["external_delivery_allowed"] is False
    assert receipt["publication_allowed"] is False
    assert receipt["provider_truth_allowed"] is False


def test_direct_publish_and_content_mutation_flags_are_rejected() -> None:
    packet = _approved_source_packet()
    packet["direct_publish_allowed"] = True

    direct_publish = build_premium_delivery_packet(packet, principal_id="principal-1", now=NOW)
    assert direct_publish["status"] == "blocked"
    assert direct_publish["blocking_reasons"] == ["direct_publish_not_allowed"]

    packet = _approved_source_packet()
    packet["content_mutation_allowed"] = True
    content_mutation = build_premium_delivery_packet(packet, principal_id="principal-1", now=NOW)
    assert content_mutation["status"] == "blocked"
    assert content_mutation["blocking_reasons"] == ["content_mutation_not_allowed"]
