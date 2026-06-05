from __future__ import annotations

from pathlib import Path

from tests.product_test_helpers import build_property_client, start_workspace


def _seed_packet(client) -> str:
    response = client.post(
        "/app/api/properties/listing-123/packets/render",
        json={
            "packet_kind": "family_review",
            "privacy_mode": "family_review",
            "fliplink_format": "flipbook_3d",
            "property_payload": {
                "title": "Family flat near Augarten",
                "property_url": "https://www.willhaben.at/iad/immobilien/d/demo",
                "match_reasons": ["Floorplan and family fit."],
                "property_facts": {
                    "rooms": 3,
                    "area_m2": 84,
                    "street_address": "Private Street 4",
                    "map_lat": 48.2,
                    "map_lng": 16.3,
                    "has_floorplan": True,
                    "postal_name": "1020 Wien",
                },
                "public_preference_snapshot": {"prefer_balcony": True},
            },
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["publication"]["publication_id"]


def test_fliplink_manual_packet_lane_and_url_validation(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EA_STORAGE_BACKEND", "memory")
    monkeypatch.setenv("EA_ARTIFACTS_DIR", str(tmp_path))
    client = build_property_client(principal_id="fliplink-owner")
    start_workspace(client, mode="personal", workspace_name="FlipLink Office")

    publication_id = _seed_packet(client)
    pdf = client.get(f"/app/api/properties/packets/{publication_id}/pdf")
    assert pdf.status_code == 200, pdf.text
    assert pdf.content.startswith(b"%PDF-1.4")

    rejected = client.post(
        f"/app/api/properties/packets/{publication_id}/fliplink/manual-link",
        json={"fliplink_url": "https://example.com/p/not-allowed"},
    )
    assert rejected.status_code == 422

    accepted = client.post(
        f"/app/api/properties/packets/{publication_id}/fliplink/manual-link",
        json={
            "fliplink_url": "https://packets.propertyquarry.com/p/family-flat",
            "fliplink_format": "flipbook_3d",
            "lead_capture_enabled": True,
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["publication"]["status"] == "published"
    assert accepted.json()["publication"]["lead_capture_enabled"] is True

    listing = client.get("/app/api/properties/packets")
    assert listing.status_code == 200
    assert listing.json()["total"] >= 1


def test_fliplink_webhook_requires_secret_and_records_untrusted_feedback(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EA_STORAGE_BACKEND", "memory")
    monkeypatch.setenv("EA_ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("FLIPLINK_WEBHOOK_SECRET", "webhook-secret")
    client = build_property_client(principal_id="fliplink-webhook-owner")
    start_workspace(client, mode="personal", workspace_name="FlipLink Webhook Office")
    publication_id = _seed_packet(client)

    denied = client.post("/v1/integrations/fliplink/webhook", json={"publication_id": publication_id})
    assert denied.status_code == 401

    accepted = client.post(
        "/v1/integrations/fliplink/webhook",
        headers={"x-propertyquarry-webhook-secret": "webhook-secret"},
        json={
            "publication_id": publication_id,
            "name": "Alex Reviewer",
            "email": "alex@example.com",
            "custom_fields": {
                "viewer_role": "family",
                "reaction": "maybe",
                "question": "How noisy is the street?",
            },
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"
    assert accepted.json()["trust"] == "untrusted_external"

    inbox = client.get("/app/api/properties/packets/feedback-inbox")
    assert inbox.status_code == 200
    items = inbox.json()["items"]
    assert items
    assert items[0]["trust"] == "untrusted_external"
    assert items[0]["status"] == "pending_owner_review"
    assert items[0]["reviewer"]["email_masked"] == "al***@example.com"
    assert "alex@example.com" not in str(items[0])

    reviewed = client.post(
        f"/app/api/properties/packets/feedback/{items[0]['event_id']}/review",
        json={"action": "accept_as_preference_signal", "note": "Useful family concern."},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["status"] == "reviewed"


def test_fliplink_packet_dashboard_and_property_actions_render(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EA_STORAGE_BACKEND", "memory")
    monkeypatch.setenv("EA_ARTIFACTS_DIR", str(tmp_path))
    client = build_property_client(principal_id="fliplink-dashboard-owner")
    start_workspace(client, mode="personal", workspace_name="FlipLink Dashboard")
    _seed_packet(client)

    dashboard = client.get("/app/properties/packets", headers={"host": "propertyquarry.com"})
    assert dashboard.status_code == 200, dashboard.text
    assert "data-property-packets-dashboard" in dashboard.text
    assert "FlipLink packet lane" in dashboard.text
    assert "Family flat near Augarten" in dashboard.text
    assert "Download PDF" in dashboard.text

    properties = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert properties.status_code == 200
    assert "Packets" in properties.text
    assert "/app/properties/packets" in properties.text
