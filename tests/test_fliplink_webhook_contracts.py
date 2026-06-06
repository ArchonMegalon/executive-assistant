from __future__ import annotations

from pathlib import Path

import pytest

from app.repositories import property_packet_publications
from app.repositories.property_packet_publications import build_property_packet_publication_repository
from tests.product_test_helpers import build_property_client, start_workspace


@pytest.fixture(autouse=True)
def _reset_packet_publication_repo() -> None:
    repo = property_packet_publications._MEMORY_REPO
    repo._publications.clear()
    repo._publication_order.clear()
    repo._events.clear()
    repo._event_order.clear()


def _seed_packet(
    client,
    *,
    packet_kind: str = "family_review",
    privacy_mode: str = "family_review",
    fliplink_format: str = "flipbook_3d",
    property_ref: str = "listing-123",
    payload: dict[str, object] | None = None,
) -> str:
    property_payload = payload or {
        "title": "Family flat near Augarten",
        "property_url": "https://www.willhaben.at/iad/immobilien/d/demo",
        "match_reasons": ["Floorplan and family fit."],
        "floorplan_refs": ["https://packets.propertyquarry.com/assets/floorplan.pdf"],
        "photo_refs": ["https://packets.propertyquarry.com/assets/photo.jpg"],
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
    }
    response = client.post(
        f"/app/api/properties/{property_ref}/packets/render",
        json={
            "packet_kind": packet_kind,
            "privacy_mode": privacy_mode,
            "fliplink_format": fliplink_format,
            "property_payload": property_payload,
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

    analytics = client.post(
        f"/app/api/properties/packets/{publication_id}/fliplink/analytics-snapshot",
        json={"views": 14, "unique_visitors": 4, "average_time_seconds": 91},
    )
    assert analytics.status_code == 200, analytics.text
    assert analytics.json()["snapshot"]["views"] == 14
    assert analytics.json()["snapshot"]["trust"] == "operator_entered_or_imported"

    listing = client.get("/app/api/properties/packets")
    assert listing.status_code == 200
    assert listing.json()["total"] >= 1
    assert listing.json()["capacity"]["cap"] >= 1
    listed = next(item for item in listing.json()["items"] if item["publication_id"] == publication_id)
    assert listed["analytics"]["views"] == 14
    assert listed["renderer_version"] == "v3_visual_packet_pdf"

    archived = client.post(
        f"/app/api/properties/packets/{publication_id}/archive",
        json={"note": "No longer needed."},
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["publication"]["status"] == "archived"
    events = client.get(f"/app/api/properties/packets/{publication_id}")
    assert events.status_code == 200
    assert any(event["event_type"] == "fliplink_publication_archived" for event in events.json()["events"])


def test_fliplink_manual_publish_enforces_privacy_and_sale_policy(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EA_STORAGE_BACKEND", "memory")
    monkeypatch.setenv("EA_ARTIFACTS_DIR", str(tmp_path))
    client = build_property_client(principal_id="fliplink-policy-owner")
    start_workspace(client, mode="personal", workspace_name="Policy Office")

    private_publication = _seed_packet(
        client,
        packet_kind="owner_review",
        privacy_mode="owner_private",
        fliplink_format="smart_document",
        property_ref="owner-private",
    )
    private_denied = client.post(
        f"/app/api/properties/packets/{private_publication}/fliplink/manual-link",
        json={"fliplink_url": "https://packets.propertyquarry.com/p/owner-private"},
    )
    assert private_denied.status_code == 422
    assert private_denied.json()["error"]["code"] == "owner_private_requires_password"

    family_publication = _seed_packet(client, property_ref="family-sale-blocked")
    sale_denied = client.post(
        f"/app/api/properties/packets/{family_publication}/fliplink/manual-link",
        json={
            "fliplink_url": "https://packets.propertyquarry.com/p/family-sale",
            "fliplink_format": "flipbook_3d",
            "sale_mode_enabled": True,
        },
    )
    assert sale_denied.status_code == 422
    assert sale_denied.json()["error"]["code"] == "sale_mode_requires_paid_market_report"

    report_publication = _seed_packet(
        client,
        packet_kind="paid_market_report",
        privacy_mode="paid_customer",
        fliplink_format="smart_document",
        property_ref="paid-report",
        payload={
            "title": "Vienna market report",
            "property_facts": {
                "district": "Vienna",
                "methodology": "Provider scan and benchmark model.",
                "freshness_date": "2026-06-06",
            },
        },
    )
    sale_ok = client.post(
        f"/app/api/properties/packets/{report_publication}/fliplink/manual-link",
        json={
            "fliplink_url": "https://reports.propertyquarry.com/r/vienna-market",
            "fliplink_format": "smart_document",
            "sale_mode_enabled": True,
        },
    )
    assert sale_ok.status_code == 200, sale_ok.text
    assert sale_ok.json()["publication"]["sale_mode_enabled"] is True


def test_fliplink_browseract_publish_request_is_guarded_and_audited(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EA_STORAGE_BACKEND", "memory")
    monkeypatch.setenv("EA_ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("FLIPLINK_BROWSERACT_ENABLED", "0")
    client = build_property_client(principal_id="fliplink-browseract-owner")
    start_workspace(client, mode="personal", workspace_name="FlipLink BrowserAct Office")
    publication_id = _seed_packet(client)

    disabled = client.post(f"/app/api/properties/packets/{publication_id}/fliplink/browseract-publish", json={})
    assert disabled.status_code == 409

    monkeypatch.setenv("FLIPLINK_BROWSERACT_ENABLED", "1")
    queued = client.post(
        f"/app/api/properties/packets/{publication_id}/fliplink/browseract-publish",
        json={"lead_capture_enabled": True, "password_required": False},
    )
    assert queued.status_code == 200, queued.text
    assert queued.json()["status"] == "queued_operator_assist"
    assert queued.json()["task_name"] == "browseract.fliplink_publish_property_packet"
    events = client.get(f"/app/api/properties/packets/{publication_id}")
    assert events.status_code == 200
    assert any(event["event_type"] == "fliplink_browser_publish_requested" for event in events.json()["events"])

    completed = client.post(
        f"/app/api/properties/packets/{publication_id}/fliplink/browseract-complete",
        json={
            "fliplink_url": "https://packets.propertyquarry.com/p/browseract-family",
            "screenshot_proof_ref": "artifact:screenshot.png",
            "qr_url": "https://packets.propertyquarry.com/qr/browseract-family.png",
            "lead_capture_enabled": True,
        },
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["publication"]["status"] == "published"
    events_after = client.get(f"/app/api/properties/packets/{publication_id}")
    assert any(event["event_type"] == "fliplink_browser_publish_completed" for event in events_after.json()["events"])


def test_fliplink_packet_capacity_blocks_new_renders_until_archive(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EA_STORAGE_BACKEND", "memory")
    monkeypatch.setenv("EA_ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("FLIPLINK_ACTIVE_PUBLICATION_CAP", "1")
    client = build_property_client(principal_id="fliplink-capacity-owner")
    start_workspace(client, mode="personal", workspace_name="FlipLink Capacity Office")

    publication_id = _seed_packet(client)
    listing = client.get("/app/api/properties/packets")
    assert listing.status_code == 200
    assert listing.json()["capacity"]["state"] == "blocked"
    assert listing.json()["capacity"]["active"] == 1
    assert listing.json()["capacity"]["global_active"] == 1
    assert listing.json()["capacity"]["principal_active"] == 1

    blocked = client.post(
        "/app/api/properties/listing-456/packets/render",
        json={
            "packet_kind": "family_review",
            "privacy_mode": "family_review",
            "property_payload": {"title": "Second packet"},
        },
    )
    assert blocked.status_code == 422
    assert blocked.json()["error"]["code"] == "fliplink_active_publication_cap_reached"

    archived = client.post(f"/app/api/properties/packets/{publication_id}/archive", json={})
    assert archived.status_code == 200
    second = client.post(
        "/app/api/properties/listing-456/packets/render",
        json={
            "packet_kind": "family_review",
            "privacy_mode": "family_review",
            "property_payload": {"title": "Second packet"},
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["capacity"]["active"] == 1
    assert second.json()["capacity"]["global_remaining"] == 0


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

    viewing = client.post(
        f"/app/api/properties/packets/feedback/{items[0]['event_id']}/review",
        json={"action": "accept_as_viewing_question", "note": "Ask about road noise at the viewing."},
    )
    assert viewing.status_code == 200, viewing.text
    assert viewing.json()["viewing_question_event"]["event_type"] == "fliplink_viewing_question_accepted"

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

    unmatched = client.post(
        "/v1/integrations/fliplink/webhook",
        headers={"x-propertyquarry-webhook-secret": "webhook-secret"},
        json={"publication_id": "missing-publication", "url": "https://packets.propertyquarry.com/p/missing"},
    )
    assert unmatched.status_code == 200, unmatched.text
    assert unmatched.json()["status"] == "accepted_unmatched"
    repo_events = build_property_packet_publication_repository(client.app.state.container.settings).list_events(
        event_type="fliplink_webhook_unmatched"
    )
    assert repo_events
    assert repo_events[0]["payload_json"]["publication_id_present"] is True

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
    assert "Sharing cockpit" in dashboard.text
    assert "Viewer responses" in dashboard.text
    assert "FlipLink leads" not in dashboard.text
    assert "Leads" not in dashboard.text
    assert "Family flat near Augarten" in dashboard.text
    assert "Download PDF" in dashboard.text
    assert "Record analytics" in dashboard.text
    assert "data-fliplink-manual-form" in dashboard.text
    assert "data-copy-kind=\"webhook\"" in dashboard.text
    assert "data-copy-lead-schema" in dashboard.text
    assert "data-browseract-publish" in dashboard.text
    assert "data-archive-publication" in dashboard.text
    assert "data-feedback-action=\"accept_as_preference_signal\"" in dashboard.text or "No viewer responses" in dashboard.text

    properties = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert properties.status_code == 200
    assert "Packets" in properties.text
    assert "/app/properties/packets" in properties.text
