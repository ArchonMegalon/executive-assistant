from __future__ import annotations

from app.repositories.property_packet_publications import InMemoryPropertyPacketPublicationRepository


def test_property_packet_publication_repository_records_publications_and_events() -> None:
    repo = InMemoryPropertyPacketPublicationRepository()
    row = repo.create_publication(
        {
            "publication_id": "pub_repo",
            "principal_id": "owner",
            "property_ref": "listing:1",
            "packet_kind": "family_review",
            "privacy_mode": "family_review",
            "fliplink_format": "flipbook_3d",
            "source_pdf_artifact_ref": "/tmp/pub_repo.pdf",
            "source_pdf_sha256": "abc",
            "source_pdf_size_bytes": 123,
            "redaction_policy_version": "property_packet_v1",
        }
    )
    assert row["status"] == "rendered"
    updated = repo.update_publication(
        publication_id="pub_repo",
        updates={"fliplink_url": "https://packets.propertyquarry.com/p/repo", "status": "published"},
    )
    assert updated is not None
    assert updated["status"] == "published"
    assert repo.find_publication(fliplink_url="https://packets.propertyquarry.com/p/repo")["publication_id"] == "pub_repo"

    event = repo.record_event(
        {
            "publication_id": "pub_repo",
            "principal_id": "owner",
            "event_type": "fliplink_lead_captured",
            "actor": "test",
            "payload_json": {"trust": "untrusted_external"},
        }
    )
    assert event["event_id"]
    assert repo.list_events(principal_id="owner", event_type="fliplink_lead_captured")[0]["event_id"] == event["event_id"]
