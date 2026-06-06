from __future__ import annotations

from app.repositories.property_packet_publications import (
    InMemoryPropertyPacketPublicationRepository,
    PROPERTY_PACKET_SCHEMA_NAME,
    PROPERTY_PACKET_SCHEMA_VERSION,
)


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


def test_property_packet_repository_counts_active_publications() -> None:
    repo = InMemoryPropertyPacketPublicationRepository()
    for index, status in enumerate(("rendered", "published", "archived"), start=1):
        repo.create_publication(
            {
                "publication_id": f"pub_count_{index}",
                "principal_id": "owner",
                "property_ref": f"listing:{index}",
                "packet_kind": "family_review",
                "privacy_mode": "family_review",
                "fliplink_format": "flipbook_3d",
                "source_pdf_artifact_ref": f"/tmp/pub_count_{index}.pdf",
                "source_pdf_sha256": "abc",
                "source_pdf_size_bytes": 123,
                "redaction_policy_version": "property_packet_v1",
                "status": status,
            }
        )

    assert repo.count_publications(principal_id="owner") == 3
    assert repo.count_publications(principal_id="owner", statuses={"rendered", "published"}) == 2
    assert PROPERTY_PACKET_SCHEMA_NAME == "property_packet_publications"
    assert PROPERTY_PACKET_SCHEMA_VERSION >= 2
