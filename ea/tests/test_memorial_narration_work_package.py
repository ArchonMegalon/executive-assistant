from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.memorial_narration_work_package import (
    build_memorial_narration_work_package,
    materialize_memorial_narration_work_package,
    provider_safe_receipt,
)


def _voice_profile(*, revoked: bool = False) -> dict[str, object]:
    return {
        "lang": "en-US",
        "voice_profile_id": "private-memorial-profile",
        "tts_plugin_voice_id": "provider-voice-id-must-not-escape",
        "voice_consent": {
            "status": "approved",
            "scope": ["synthesize", "conversation_turn"],
            "authorized_by": "private-owner-record",
            "revoked": revoked,
        },
    }


def _manifest(text: str) -> dict[str, object]:
    return {
        "slug": "manfred",
        "memory_cards": [
            {
                "title": "Approved card",
                "body": text,
                "visibility": "public",
            }
        ],
    }


def _build(text: str, **kwargs: object) -> dict[str, object]:
    return build_memorial_narration_work_package(
        slug="manfred",
        memorial_manifest=_manifest(text),
        voice_profile=_voice_profile(),
        max_chars=256,
        **kwargs,
    )


def test_separates_narrator_from_attributed_dialogue_without_rewriting_source() -> None:
    source = "Before the call. “Hello,” Anna said. After the call."

    package = _build(source)

    plan = dict(package["narration_plan"])
    spans = list(plan["spans"])
    rendered_roles = {
        str(row["speaker_role"])
        for row in spans
        if isinstance(row, dict) and row.get("render") is True
    }
    dialogue = [
        row for row in spans if isinstance(row, dict) and row.get("kind") == "dialogue"
    ]
    assert package["status"] == "ready_for_private_cast_resolution"
    assert rendered_roles == {"narrator", "dialogue"}
    assert len(dialogue) == 1
    assert dialogue[0]["speaker_label"] == "Anna"
    assert "Hello" in str(dialogue[0]["source_text"])
    assert "Anna said" not in str(dialogue[0]["source_text"])
    assert "".join(str(row["source_text"]) for row in spans) == source
    assert plan["coverage_complete"] is True


def test_excludes_private_memorial_and_archive_sources_by_default(
    tmp_path: Path,
) -> None:
    archive_root = tmp_path / "archive"
    public_document = archive_root / "public" / "approved-publication"
    public_document.mkdir(parents=True)
    (public_document / "manifest.json").write_text(
        json.dumps(
            {
                "audience": "public",
                "approved": True,
                "review_status": "approved",
            }
        ),
        encoding="utf-8",
    )
    (public_document / "source.md").write_text(
        "Approved archive remembrance.", encoding="utf-8"
    )
    manifest = {
        "memory_cards": [
            {
                "title": "Public",
                "body": "Approved public card.",
                "visibility": "public",
            },
            {
                "title": "Private",
                "body": "PRIVATE_CARD_SENTINEL",
                "visibility": "private",
            },
        ]
    }
    registry = {
        "fliplink_publications": [
            {
                "slug": "approved-publication",
                "audience": "public",
                "review_status": "published",
            },
            {
                "slug": "family-publication",
                "audience": "family",
                "review_status": "approved",
                "body": "PRIVATE_ARCHIVE_SENTINEL",
            },
        ]
    }

    package = build_memorial_narration_work_package(
        slug="manfred",
        memorial_manifest=manifest,
        voice_profile=_voice_profile(),
        archive_registry=registry,
        archive_root=archive_root,
        max_chars=256,
    )

    serialized = json.dumps(package, ensure_ascii=False, sort_keys=True)
    receipt = provider_safe_receipt(package)
    assert "Approved public card." in serialized
    assert "Approved archive remembrance." in serialized
    assert "PRIVATE_CARD_SENTINEL" not in serialized
    assert "PRIVATE_ARCHIVE_SENTINEL" not in serialized
    assert receipt["approved_public_source_count"] == 2
    assert receipt["excluded_source_count"] == 2
    assert receipt["private_sources_excluded_by_default"] is True


def test_maps_only_explicit_approved_speaker_profile_and_redacts_receipt() -> None:
    profiles = {
        "Anna": {
            "approved": True,
            "speaker_profile_id": "private-anna-cast-profile",
            "voice_id": "raw-dialogue-provider-voice-id",
            "gender": "feminine",
            "age_band": "older_adult",
            "ethnicity": "Austrian",
            "style": "warm",
        }
    }

    package = _build("“Good morning,” Anna said.", speaker_profiles=profiles)

    plan = dict(package["narration_plan"])
    anna = next(row for row in plan["speakers"] if row["speaker_label"] == "Anna")
    cast = dict(package["cast_handoff"])
    anna_cast = next(
        row for row in cast["speakers"] if row["speaker_id"] == anna["speaker_id"]
    )
    receipt_json = json.dumps(
        provider_safe_receipt(package), ensure_ascii=False, sort_keys=True
    )
    package_json = json.dumps(package, ensure_ascii=False, sort_keys=True)
    assert anna["traits"] == {
        "age_band": {
            "confidence": 1.0,
            "provenance": "explicit_approved_speaker_profile",
            "sensitive_hint": False,
            "value": "older_adult",
        },
        "cultural_or_ethnic_background": {
            "confidence": 1.0,
            "provenance": "explicit_approved_speaker_profile",
            "sensitive_hint": True,
            "value": "Austrian",
        },
        "gender_presentation": {
            "confidence": 1.0,
            "provenance": "explicit_approved_speaker_profile",
            "sensitive_hint": False,
            "value": "feminine",
        },
        "style": {
            "confidence": 1.0,
            "provenance": "explicit_approved_speaker_profile",
            "sensitive_hint": False,
            "value": "warm",
        },
    }
    assert anna_cast["mapping"] == "explicit_approved_speaker_profile"
    assert anna_cast["explicit_profile"] is True
    assert "raw-dialogue-provider-voice-id" not in package_json
    assert "Austrian" not in receipt_json
    assert "feminine" not in receipt_json
    assert "older_adult" not in receipt_json
    assert provider_safe_receipt(package)["sensitive_trait_values_exposed"] is False


def test_unattributed_dialogue_stays_neutral_without_demographic_claims() -> None:
    package = _build("“Who is there?”")

    plan = dict(package["narration_plan"])
    unknown = next(row for row in plan["speakers"] if row["speaker_id"] != "narrator")
    cast = dict(package["cast_handoff"])
    unknown_cast = next(
        row for row in cast["speakers"] if row["speaker_id"] == unknown["speaker_id"]
    )
    assert unknown["speaker_label"] == "Unknown speaker"
    assert unknown["traits"] == {}
    assert unknown_cast["mapping"] == "neutral_ambiguity"
    assert unknown_cast["neutral_fallback"] is True
    assert provider_safe_receipt(package)["neutral_dialogue_speaker_count"] == 1


def test_consent_revocation_blocks_cast_and_render_but_not_offline_source_planning() -> (
    None
):
    source = "“Hello,” Anna said."

    package = build_memorial_narration_work_package(
        slug="manfred",
        memorial_manifest=_manifest(source),
        voice_profile=_voice_profile(revoked=True),
        max_chars=256,
    )

    receipt = provider_safe_receipt(package)
    plan = dict(package["narration_plan"])
    assert package["status"] == "blocked_voice_consent"
    assert package["reason"] == "voice_consent_revoked"
    assert package["render_authorized"] is False
    assert dict(package["cast_handoff"])["speakers"] == []
    assert plan["coverage_complete"] is True
    assert "".join(str(row["source_text"]) for row in plan["spans"]) == source
    assert receipt["voice_consent"]["revoked"] is True
    assert receipt["provider_calls_made"] == 0
    assert receipt["synthesis_requested"] is False


def test_work_package_is_deterministic_for_identical_inputs() -> None:
    first = _build("A deterministic public remembrance.")
    second = _build("A deterministic public remembrance.")

    assert first == second


def test_materializer_rejects_shared_private_and_public_output_path(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "memorial.json"
    voice_path = tmp_path / "tts_voice.json"
    output_path = tmp_path / "shared-output.json"
    manifest_path.write_text(
        json.dumps(_manifest("Approved source.")), encoding="utf-8"
    )
    voice_path.write_text(json.dumps(_voice_profile()), encoding="utf-8")

    with pytest.raises(ValueError, match="narration_output_paths_must_be_distinct"):
        materialize_memorial_narration_work_package(
            slug="manfred",
            memorial_manifest_path=manifest_path,
            voice_profile_path=voice_path,
            output_path=output_path,
            receipt_output_path=output_path,
        )

    assert not output_path.exists()
