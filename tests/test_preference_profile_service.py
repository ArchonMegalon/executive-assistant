from __future__ import annotations

from app.repositories.preference_profiles import InMemoryPreferenceProfileRepository
from app.services.preference_profile_service import PreferenceProfileService


def _service() -> PreferenceProfileService:
    return PreferenceProfileService(repo=InMemoryPreferenceProfileRepository())


def test_preference_profile_service_can_upsert_profile_and_node_bundle() -> None:
    service = _service()

    profile = service.ensure_profile(
        principal_id="pref-principal",
        person_id="self",
        display_name="Tibor",
        consent_mode="behavioral_learning",
        learning_enabled=True,
    )
    node = service.upsert_preference_node(
        principal_id="pref-principal",
        person_id="self",
        domain="willhaben",
        category="constraint",
        key="max_total_rent_eur",
        value_json=2500,
        confidence=1.0,
    )
    bundle = service.get_profile_bundle(principal_id="pref-principal", person_id="self")

    assert profile["display_name"] == "Tibor"
    assert profile["learning_enabled"] is True
    assert node["key"] == "max_total_rent_eur"
    assert bundle["profile"]["person_id"] == "self"
    assert bundle["preference_nodes"][0]["key"] == "max_total_rent_eur"


def test_preference_profile_service_applies_correction_and_records_receipt() -> None:
    service = _service()

    applied = service.apply_correction(
        principal_id="pref-principal",
        person_id="self",
        domain="willhaben",
        category="aversion",
        key="avoid_heating_types",
        value_json=["Gasheizung"],
        reason="Strong no for future screening",
        corrected_by="operator-1",
    )
    bundle = service.get_profile_bundle(principal_id="pref-principal", person_id="self")

    assert applied["node"]["source_mode"] == "explicit_correction"
    assert applied["node"]["confidence"] == 1.0
    assert applied["correction"]["reason"] == "Strong no for future screening"
    assert bundle["recent_corrections"][0]["corrected_by"] == "operator-1"


def test_preference_profile_service_records_evidence_and_applies_preference_hints() -> None:
    service = _service()
    service.ensure_profile(
        principal_id="pref-principal",
        person_id="self",
        consent_mode="behavioral_learning",
        learning_enabled=True,
    )

    result = service.record_evidence_event(
        principal_id="pref-principal",
        person_id="self",
        domain="willhaben",
        event_type="listing_shortlisted",
        object_type="listing",
        object_id="listing-1",
        interpreted_signal_json={
            "preference_hints": [
                {
                    "domain": "willhaben",
                    "category": "soft_preference",
                    "key": "preferred_districts",
                    "value_json": ["Waehring"],
                    "strength": "medium",
                    "merge_mode": "append_unique",
                }
            ]
        },
    )

    assert result["event"]["event_type"] == "listing_shortlisted"
    assert result["applied_nodes"][0]["key"] == "preferred_districts"
    assert result["applied_nodes"][0]["value_json"] == ["Waehring"]


def test_preference_profile_service_scores_willhaben_candidate_from_profile() -> None:
    service = _service()
    service.ensure_profile(
        principal_id="pref-principal",
        person_id="self",
        consent_mode="behavioral_learning",
        learning_enabled=True,
    )
    service.upsert_preference_node(
        principal_id="pref-principal",
        person_id="self",
        domain="willhaben",
        category="constraint",
        key="require_floorplan",
        value_json=True,
        confidence=1.0,
    )
    service.upsert_preference_node(
        principal_id="pref-principal",
        person_id="self",
        domain="willhaben",
        category="aversion",
        key="avoid_heating_types",
        value_json=["Gasheizung"],
        confidence=1.0,
    )
    assessment = service.assess_candidate(
        principal_id="pref-principal",
        person_id="self",
        domain="willhaben",
        object_type="listing",
        object_id="listing-1",
        object_payload={
            "postal_name": "Waehring",
            "total_rent_eur": 2200.0,
            "rooms": 4.0,
            "area_sqm": 106.0,
            "heating": "Gasheizung",
            "floorplan_count": 1,
            "tour_media_mode": "panorama_360",
        },
        persist=False,
        require_existing_profile=True,
    )

    assert assessment is not None
    assert assessment["recommendation"] == "reject"
    assert any("Gasheizung" in entry for entry in assessment["mismatch_reasons_json"])
    assert assessment["blocking_constraints_json"] == []


def test_preference_profile_service_builds_teable_projection_rows() -> None:
    service = _service()
    service.ensure_profile(principal_id="pref-principal", person_id="self", display_name="Tibor")
    service.upsert_preference_node(
        principal_id="pref-principal",
        person_id="self",
        domain="willhaben",
        category="soft_preference",
        key="preferred_districts",
        value_json=["Waehring"],
        confidence=0.8,
    )

    projection = service.build_teable_projection_records(principal_id="pref-principal", person_id="self")

    assert "preference_review_queue" in projection
    assert projection["preference_review_queue"][0]["display_name"] == "Tibor"
    assert projection["preference_review_queue"][0]["domain"] == "willhaben"


def test_preference_profile_service_partial_profile_update_keeps_existing_flags() -> None:
    service = _service()

    first = service.ensure_profile(
        principal_id="pref-principal",
        person_id="self",
        display_name="Tibor",
        consent_mode="behavioral_learning",
        learning_enabled=True,
        high_stakes_domains_enabled=True,
    )
    second = service.ensure_profile(
        principal_id="pref-principal",
        person_id="self",
        display_name="Updated Tibor",
    )

    assert first["learning_enabled"] is True
    assert second["display_name"] == "Updated Tibor"
    assert second["learning_enabled"] is True
    assert second["high_stakes_domains_enabled"] is True
