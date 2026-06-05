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

    query_secret_denied = client.post(
        f"/v1/integrations/fliplink/webhook?secret=webhook-secret",
        json={"publication_id": publication_id},
    )
    assert query_secret_denied.status_code == 401
    assert query_secret_denied.json()["error"]["code"] == "fliplink_webhook_query_secret_disabled"

    oversized = client.post(
        "/v1/integrations/fliplink/webhook",
        headers={"x-propertyquarry-webhook-secret": "webhook-secret", "content-type": "application/json"},
        content=b'{"publication_id":"' + publication_id.encode("utf-8") + b'","blob":"' + (b"x" * 65_000) + b'"}',
    )
    assert oversized.status_code == 413

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
                "rawNested": {"must": "not persist"},
                "unexpected_field": "not needed",
            },
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"
    assert accepted.json()["trust"] == "untrusted_external"
    assert accepted.json()["secret_mode"] == "header"

    inbox = client.get("/app/api/properties/packets/feedback-inbox")
    assert inbox.status_code == 200
    items = inbox.json()["items"]
    assert items
    assert items[0]["trust"] == "untrusted_external"
    assert items[0]["status"] == "pending_owner_review"
    assert items[0]["reviewer"]["email_masked"] == "al***@example.com"
    assert "alex@example.com" not in str(items[0])
    assert items[0]["custom_fields"]["question"] == "How noisy is the street?"
    assert items[0]["custom_fields"]["custom_fields_extra_redacted"] is True
    assert "rawNested" not in str(items[0])

    reviewed = client.post(
        f"/app/api/properties/packets/feedback/{items[0]['event_id']}/review",
        json={"action": "convert_to_hard_rule", "note": "Quiet micro-location should be a hard screening rule."},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["status"] == "reviewed"
    applied = reviewed.json()["preference_application"]
    assert applied["hard_rule_node"]["key"] == "require_quiet_micro_location"
    assert applied["hard_rule_node"]["category"] == "constraint"
    bundle = client.app.state.container.preference_profiles.get_profile_bundle(
        principal_id="fliplink-webhook-owner",
        person_id="self",
    )
    nodes_by_key = {node["key"]: node for node in bundle["preference_nodes"]}
    assert nodes_by_key["require_quiet_micro_location"]["value_json"] is True
    recent_event = bundle["recent_evidence_events"][0]
    assert recent_event["domain"] == "property"
    assert recent_event["event_type"] == "feedback_inbox_accepted"
    assert recent_event["object_type"] == "feedback"

    monkeypatch.setenv("FLIPLINK_WEBHOOK_ALLOW_QUERY_SECRET", "1")
    query_accepted = client.post(
        f"/v1/integrations/fliplink/webhook?secret=webhook-secret",
        json={"publication_id": publication_id, "custom_fields": {"viewer_role": "agent", "intent": "viewing"}},
    )
    assert query_accepted.status_code == 200, query_accepted.text
    assert query_accepted.json()["secret_mode"] == "query"


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
