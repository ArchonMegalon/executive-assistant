from __future__ import annotations

import hashlib
from pathlib import Path

from app.services.fliplink.models import FlipLinkFormat, PacketPrivacyMode, PropertyPacketKind
from app.services.fliplink.pdf_renderer import render_property_packet_pdf
from app.services.fliplink.privacy import redact_property_packet


def _source_payload() -> dict[str, object]:
    return {
        "principal_id": "owner-secret",
        "recipient_email": "private@example.com",
        "title": "1020 Vienna apartment",
        "property_ref": "listing:vienna-1020",
        "property_url": "https://www.willhaben.at/iad/immobilien/d/demo",
        "fit_summary": "Strong family fit near daily-life infrastructure.",
        "match_reasons": ["Floorplan, lift, and usable outdoor space."],
        "floorplan_refs": ["https://packets.propertyquarry.com/assets/floorplan.pdf"],
        "photo_refs": ["https://packets.propertyquarry.com/assets/photo.jpg"],
        "public_preference_snapshot": {"prefer_balcony": True},
        "property_facts": {
            "rooms": 3,
            "area_m2": 82,
            "price_display": "EUR 520,000",
            "street_address": "Exact Street 12",
            "map_lat": 48.2,
            "map_lng": 16.3,
            "postal_name": "1020 Wien",
            "has_floorplan": True,
            "nearest_supermarket_m": 300,
            "internal_source_diagnostics": {"cookie": "secret"},
        },
    }


def test_fliplink_packet_redacts_private_keys_and_exact_address_by_default() -> None:
    redacted = redact_property_packet(
        source=_source_payload(),
        privacy_mode=PacketPrivacyMode.FAMILY_REVIEW,
        include_exact_address=False,
    )

    assert "principal_id" not in redacted.payload
    assert "public_preference_snapshot" not in redacted.payload
    facts = redacted.payload["facts"]
    assert facts["rooms"] == 3
    assert facts["has_floorplan"] is True
    assert facts["nearest_supermarket_m"] == 300
    assert "street_address" not in facts
    assert "map_lat" not in facts
    assert "internal_source_diagnostics" not in facts
    assert "facts.street_address" in redacted.receipt["removed_fields"]
    assert "principal_id" in redacted.receipt["removed_fields"]


def test_fliplink_owner_private_can_keep_exact_address_but_not_secrets() -> None:
    redacted = redact_property_packet(
        source=_source_payload(),
        privacy_mode=PacketPrivacyMode.OWNER_PRIVATE,
        include_exact_address=True,
    )

    facts = redacted.payload["facts"]
    assert facts["street_address"] == "Exact Street 12"
    assert facts["map_lat"] == 48.2
    assert "principal_id" not in redacted.payload
    assert "public_preference_snapshot" not in redacted.payload


def test_fliplink_packet_media_flags_remove_floorplans_and_photos() -> None:
    redacted = redact_property_packet(
        source=_source_payload(),
        privacy_mode=PacketPrivacyMode.FAMILY_REVIEW,
        include_floorplan=False,
        include_photos=False,
    )

    assert "floorplan_refs" not in redacted.payload
    assert "photo_refs" not in redacted.payload
    assert "floorplan_refs" in redacted.receipt["removed_fields"]
    assert "photo_refs" in redacted.receipt["removed_fields"]
    assert redacted.receipt["include_floorplan"] is False
    assert redacted.receipt["include_photos"] is False


def test_fliplink_pdf_receipt_matches_pdf_hash(tmp_path: Path) -> None:
    rendered = render_property_packet_pdf(
        artifact_root=tmp_path,
        publication_id="pub_test",
        principal_id="owner-1",
        source=_source_payload(),
        packet_kind=PropertyPacketKind.FAMILY_REVIEW,
        privacy_mode=PacketPrivacyMode.FAMILY_REVIEW,
        fliplink_format=FlipLinkFormat.FLIPBOOK_3D,
    )

    pdf_path = Path(str(rendered["pdf_path"]))
    pdf_bytes = pdf_path.read_bytes()
    assert pdf_bytes.startswith(b"%PDF-1.4")
    assert hashlib.sha256(pdf_bytes).hexdigest() == rendered["pdf_sha256"]
    assert rendered["receipt"]["pdf_sha256"] == rendered["pdf_sha256"]
    assert rendered["receipt"]["source_pdf_size_bytes"] == len(pdf_bytes)
    assert rendered["receipt"]["renderer_version"] == "v3_visual_packet_pdf"
