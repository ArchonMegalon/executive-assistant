from __future__ import annotations

from app.repositories.preference_profiles import InMemoryPreferenceProfileRepository
from app.services.preference_profile_service import PreferenceProfileService
from app.services.teable_projection_adapter import build_teable_projection_records, build_teable_projection_summary


def test_teable_projection_adapter_keeps_static_fallback_without_principal() -> None:
    records = build_teable_projection_records()

    assert "product_signals" in records
    assert "preference_review_queue" in records
    assert records["preference_review_queue"][0]["display_name"] == "Principal"


def test_teable_projection_adapter_can_project_live_preference_rows() -> None:
    service = PreferenceProfileService(repo=InMemoryPreferenceProfileRepository())
    service.ensure_profile(
        principal_id="pref-principal",
        person_id="self",
        display_name="Tibor",
        consent_mode="behavioral_learning",
        learning_enabled=True,
    )
    service.upsert_preference_node(
        principal_id="pref-principal",
        person_id="self",
        domain="willhaben",
        category="soft_preference",
        key="preferred_districts",
        value_json=["Waehring"],
        confidence=0.8,
    )

    records = build_teable_projection_records(
        preference_profile_service=service,
        principal_id="pref-principal",
        person_id="self",
    )
    summary = build_teable_projection_summary(
        preference_profile_service=service,
        principal_id="pref-principal",
        person_id="self",
    )

    assert records["preference_review_queue"][0]["display_name"] == "Tibor"
    assert records["preference_review_queue"][0]["key"] == "preferred_districts"
    table = next(item for item in summary["tables"] if item["table_name"] == "preference_review_queue")
    assert table["record_count"] >= 1
