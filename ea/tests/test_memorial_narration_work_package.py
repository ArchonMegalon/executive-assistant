from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.memorial_narration_work_package import (
    build_memorial_narration_work_package,
    materialize_memorial_narration_work_package,
    provider_safe_receipt,
    write_json_artifact,
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
                "approved": True,
                "review_status": "approved",
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
    assert package["cast_resolution_authorized"] is True
    assert package["render_authorized"] is False
    assert package["synthesis_authorized"] is False
    assert package["cast_mapping_review_required"] is True
    assert package["human_listening_review_required"] is True
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
                "approved": True,
                "review_status": "approved",
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
                "approved": True,
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


def test_archive_source_symlink_cannot_escape_the_approved_public_document(
    tmp_path: Path,
) -> None:
    archive_root = tmp_path / "archive"
    document_root = archive_root / "public" / "approved-publication"
    document_root.mkdir(parents=True)
    (document_root / "manifest.json").write_text(
        json.dumps(
            {
                "audience": "public",
                "approved": True,
                "review_status": "approved",
            }
        ),
        encoding="utf-8",
    )
    private_source = tmp_path / "private-source.md"
    private_source.write_text("PRIVATE_ARCHIVE_SYMLINK_SENTINEL", encoding="utf-8")
    (document_root / "source.md").symlink_to(private_source)

    package = build_memorial_narration_work_package(
        slug="manfred",
        memorial_manifest=_manifest("Approved public card."),
        voice_profile=_voice_profile(),
        archive_registry={
            "fliplink_publications": [
                {
                    "slug": "approved-publication",
                    "audience": "public",
                    "approved": True,
                    "review_status": "published",
                }
            ]
        },
        archive_root=archive_root,
        max_chars=256,
    )

    serialized = json.dumps(package, ensure_ascii=False, sort_keys=True)
    receipt = provider_safe_receipt(package)
    assert "PRIVATE_ARCHIVE_SYMLINK_SENTINEL" not in serialized
    assert receipt["approved_public_source_count"] == 1
    assert receipt["excluded_source_reason_counts"] == {
        "archive_document_source_missing_or_unsafe": 1
    }


def test_public_card_requires_explicit_approval_and_review() -> None:
    unapproved = build_memorial_narration_work_package(
        slug="manfred",
        memorial_manifest={
            "memory_cards": [
                {
                    "body": "Not yet approved for narration.",
                    "visibility": "public",
                }
            ]
        },
        voice_profile=_voice_profile(),
        max_chars=256,
    )
    approved_without_review = build_memorial_narration_work_package(
        slug="manfred",
        memorial_manifest={
            "memory_cards": [
                {
                    "body": "Approved flag without completed review.",
                    "visibility": "public",
                    "approved": True,
                }
            ]
        },
        voice_profile=_voice_profile(),
        max_chars=256,
    )

    assert unapproved["status"] == "blocked_no_approved_public_sources"
    assert provider_safe_receipt(unapproved)["excluded_source_reason_counts"] == {
        "memorial_card_not_approved": 1
    }
    assert approved_without_review["status"] == "blocked_no_approved_public_sources"
    assert provider_safe_receipt(approved_without_review)[
        "excluded_source_reason_counts"
    ] == {"memorial_card_review_not_approved": 1}


def test_speaker_demographics_require_purpose_specific_casting_approval() -> None:
    package = _build(
        "“Good morning,” Anna said.",
        speaker_profiles={
            "Anna": {
                "approved": True,
                "speaker_profile_id": "private-anna-profile",
                "gender": "feminine",
                "age_band": "older_adult",
                "ethnicity": "Austrian",
            }
        },
    )

    anna = next(
        row
        for row in package["narration_plan"]["speakers"]
        if row["speaker_label"] == "Anna"
    )
    handoff = next(
        row
        for row in package["cast_handoff"]["speakers"]
        if row["speaker_id"] == anna["speaker_id"]
    )
    assert anna["traits"] == {}
    assert handoff["explicit_profile"] is False
    assert handoff["mapping"] == "neutral_unprofiled_speaker"


def test_maps_only_explicit_approved_speaker_profile_and_redacts_receipt() -> None:
    profiles = {
        "Anna": {
            "approved": True,
            "casting_approved": True,
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
    assert package["cast_resolution_authorized"] is False
    assert package["synthesis_authorized"] is False
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


def test_artifact_writer_never_repermissions_shared_or_symlinked_parents(
    tmp_path: Path,
) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o1777)
    public_receipt = shared / "receipt.json"

    write_json_artifact(public_receipt, {"status": "safe"}, private=False)

    assert shared.stat().st_mode & 0o7777 == 0o1777
    assert public_receipt.stat().st_mode & 0o777 == 0o644
    with pytest.raises(ValueError, match="private_artifact_parent_unsafe"):
        write_json_artifact(shared / "private.json", {"private": True}, private=True)
    assert shared.stat().st_mode & 0o7777 == 0o1777

    real_parent = tmp_path / "real-parent"
    real_parent.mkdir(mode=0o700)
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink_ancestor_forbidden"):
        write_json_artifact(
            linked_parent / "private.json",
            {"private": True},
            private=True,
        )
