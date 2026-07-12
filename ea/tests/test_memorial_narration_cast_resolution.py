from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.services import memorial_narration_cast_resolution as cast_resolution_service
from app.services.memorial_narration_cast_resolution import (
    REQUIRED_REVIEW_SCOPE,
    build_memorial_narration_cast_review,
    cast_resolution_safe_receipt,
    cast_review_safe_receipt,
    read_json_artifact,
    resolve_memorial_narration_cast as _resolve_memorial_narration_cast,
    verify_memorial_narration_cast as _verify_memorial_narration_cast,
    write_json_artifact,
)
from app.services.memorial_narration_work_package import (
    REQUIRED_SPEAKER_ATTRIBUTION_SCOPE,
    REQUIRED_SPEAKER_CASTING_SCOPE,
    build_memorial_narration_work_package,
)


REVIEW_SECRET = b"bounded-test-review-secret-32-bytes"
REVIEWED_AT = "2026-07-11T10:00:00Z"
VERIFY_AT = datetime(2026, 7, 11, 10, 1, tzinfo=UTC)
_PROFILE_TRAIT_ALIASES = {
    "gender_presentation": ("gender_presentation", "gender"),
    "age_band": ("age_band", "approximate_age", "age_range", "age"),
    "cultural_or_ethnic_background": (
        "cultural_or_ethnic_background",
        "cultural_background",
        "cultural_identity",
        "ethnic_background",
        "ethnicity",
    ),
    "accent": ("accent", "dialect"),
    "language": ("language", "locale", "spoken_language", "native_language"),
    "role": ("role", "character_role"),
    "style": ("style", "performance_style"),
}


class _TestWorkPackage(dict[str, object]):
    current_speaker_profiles: dict[str, dict[str, object]] | None = None
    current_memorial_manifest: dict[str, object] | None = None


def resolve_memorial_narration_cast(**kwargs: object) -> dict[str, object]:
    package = kwargs.get("work_package")
    if isinstance(package, _TestWorkPackage):
        kwargs.setdefault(
            "current_speaker_profiles",
            package.current_speaker_profiles,
        )
        kwargs.setdefault(
            "current_memorial_manifest",
            package.current_memorial_manifest,
        )
    return _resolve_memorial_narration_cast(**kwargs)


def verify_memorial_narration_cast(**kwargs: object) -> dict[str, object]:
    package = kwargs.get("work_package")
    if isinstance(package, _TestWorkPackage):
        kwargs.setdefault(
            "current_speaker_profiles",
            package.current_speaker_profiles,
        )
        kwargs.setdefault(
            "current_memorial_manifest",
            package.current_memorial_manifest,
        )
    return _verify_memorial_narration_cast(**kwargs)


def _reviewed_speaker_profiles(
    profiles: dict[str, dict[str, object]] | None,
) -> dict[str, dict[str, object]] | None:
    if profiles is None:
        return None
    reviewed: dict[str, dict[str, object]] = {}
    for label, raw in profiles.items():
        profile = deepcopy(raw)
        if isinstance(profile.get("casting_review"), dict):
            reviewed[label] = profile
            continue
        traits: dict[str, str] = {}
        for canonical, aliases in _PROFILE_TRAIT_ALIASES.items():
            for alias in aliases:
                value = " ".join(str(profile.get(alias) or "").split())
                if value:
                    traits[canonical] = value
                    break
        profile_ref = next(
            (
                str(profile.get(key) or "").strip()
                for key in (
                    "speaker_profile_id",
                    "profile_id",
                    "voice_profile_ref",
                    "voice_profile_id",
                )
                if str(profile.get(key) or "").strip()
            ),
            "",
        )
        profile["casting_review"] = {
            "status": "approved",
            "scope": [REQUIRED_SPEAKER_CASTING_SCOPE],
            "revoked": False,
            "approved_by_family": True,
            "speaker_profile_ref_sha256": hashlib.sha256(
                profile_ref.encode("utf-8")
            ).hexdigest(),
            "speaker_traits_sha256": hashlib.sha256(
                json.dumps(
                    traits,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest(),
            "reviewed_at": "2026-07-11T09:00:00Z",
            "expires_at": "2026-07-31T09:00:00Z",
        }
        reviewed[label] = profile
    return reviewed


def _voice_profile() -> dict[str, object]:
    return {
        "voice_profile_id": "private-manfred-narrator-profile",
        "provider": "unmixr_clone",
        "tts_plugin_voice_id": "raw-private-narrator-voice-id",
        "lang": "en-US",
        "voice_consent": {
            "status": "approved",
            "scope": ["synthesize", "conversation_turn"],
            "authorized_by": "private-family-review-record",
            "revoked": False,
        },
    }


def _package(
    text: str,
    *,
    speaker_profiles: dict[str, dict[str, object]] | None = None,
    approve_uncertain_attributions: bool = True,
) -> dict[str, object]:
    reviewed_profiles = _reviewed_speaker_profiles(speaker_profiles)
    narration_review = {
        "status": "approved",
        "scope": ["memorial_audiobook_narration"],
        "revoked": False,
        "source_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }
    manifest = {
        "slug": "manfred",
        "memory_cards": [
            {
                "title": "Reviewed remembrance",
                "body": text,
                "visibility": "public",
                "approved": True,
                "review_status": "approved",
                "narration_review": narration_review,
            }
        ],
    }
    package = build_memorial_narration_work_package(
        slug="manfred",
        memorial_manifest=manifest,
        voice_profile=_voice_profile(),
        speaker_profiles=reviewed_profiles,
        language="en-US",
        max_chars=256,
        observed_at=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )
    requirements = list(
        package.get("speaker_attribution_review_requirements") or []
    )
    if approve_uncertain_attributions and requirements:
        manifest["speaker_attribution_reviews"] = [
            {
                "status": "approved",
                "scope": [REQUIRED_SPEAKER_ATTRIBUTION_SCOPE],
                "revoked": False,
                "approved_by_family": True,
                "reviewed_at": "2026-07-11T09:58:00Z",
                "speaker_id": str(row["speaker_id"]),
                "span_fingerprint": str(row["span_fingerprint"]),
                "source_text_sha256": str(row["source_text_sha256"]),
            }
            for row in requirements
        ]
        package = build_memorial_narration_work_package(
            slug="manfred",
            memorial_manifest=manifest,
            voice_profile=_voice_profile(),
            speaker_profiles=reviewed_profiles,
            language="en-US",
            max_chars=256,
            observed_at=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
        )
    wrapped = _TestWorkPackage(package)
    wrapped.current_speaker_profiles = reviewed_profiles
    wrapped.current_memorial_manifest = manifest
    return wrapped


def _review(resolution: dict[str, object]) -> dict[str, object]:
    return build_memorial_narration_cast_review(
        resolution=resolution,
        reviewer="family-reviewer-private-id",
        signing_secret=REVIEW_SECRET,
        status="approved",
        scope=REQUIRED_REVIEW_SCOPE,
        reviewed_at=REVIEWED_AT,
        expires_at="2026-07-18T10:00:00Z",
    )


def _approved_mapping(**values: object) -> dict[str, object]:
    mapping: dict[str, object] = {
        "status": "approved",
        "approved_by_family": True,
        "revoked": False,
        "reviewed_at": "2026-07-11T09:58:00Z",
        "expires_at": "2026-07-18T09:58:00Z",
    }
    mapping.update(values)
    return mapping


def _dialogue_handoff(package: dict[str, object]) -> list[dict[str, object]]:
    return [
        dict(row)
        for row in package["cast_handoff"]["speakers"]
        if row["speaker_role"] == "dialogue"
    ]


def test_narrator_only_mapping_review_still_requires_audition_before_synthesis() -> None:
    package = _package("A calm and faithful remembrance.")

    assert package["cast_resolution_authorized"] is True
    assert package["render_authorized"] is False
    assert package["synthesis_authorized"] is False

    resolution = resolve_memorial_narration_cast(
        work_package=package,
        voice_profile=_voice_profile(),
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )

    assert resolution["status"] == "ready_for_mapping_review"
    assert resolution["synthesis_authorized"] is False
    assert resolution["provider_calls_made"] == 0
    assert resolution["narrator"]["voice_id"] == (
        "raw-private-narrator-voice-id"
    )

    review = _review(resolution)
    receipt = verify_memorial_narration_cast(
        work_package=package,
        resolution=resolution,
        review=review,
        voice_profile=_voice_profile(),
        signing_secret=REVIEW_SECRET,
        now=VERIFY_AT,
    )

    assert receipt["status"] == "pass"
    assert receipt["cast_mapping_reviewed"] is True
    assert receipt["ready_for_provider_preflight"] is True
    assert receipt["ready_for_private_audition"] is False
    assert receipt["audition_authorized"] is False
    assert receipt["synthesis_authorized"] is False
    assert receipt["render_authorized"] is False
    assert receipt["human_listening_review_required"] is True
    assert receipt["provider_capability_receipt_required"] is True
    assert receipt["provider_calls_made"] == 0
    serialized = json.dumps(receipt, ensure_ascii=False, sort_keys=True)
    assert "raw-private-narrator-voice-id" not in serialized
    assert "family-reviewer-private-id" not in serialized


def test_stale_v2_work_package_is_rejected_before_cast_resolution() -> None:
    package = _package("A purpose-reviewed source.")
    package["contract_name"] = "ea.memorial_narration_work_package.v2"
    package["version"] = 2

    resolution = resolve_memorial_narration_cast(
        work_package=package,
        voice_profile=_voice_profile(),
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )

    assert resolution["status"] == "blocked"
    assert resolution["synthesis_authorized"] is False
    assert "work_package_contract_mismatch" in resolution["issues"]
    assert "work_package_version_mismatch" in resolution["issues"]


def test_stale_v3_profile_without_casting_eligibility_is_rejected() -> None:
    package = _package(
        '“Good morning,” Anna said.',
        speaker_profiles={
            "Anna": {
                "approved": True,
                "casting_approved": True,
                "speaker_profile_id": "private-anna-stale-profile",
                "gender": "feminine",
            }
        },
    )
    anna = next(
        row
        for row in package["narration_plan"]["speakers"]
        if row["speaker_label"] == "Anna"
    )
    anna["traits"]["gender_presentation"].pop("casting_eligible")

    resolution = resolve_memorial_narration_cast(
        work_package=package,
        voice_profile=_voice_profile(),
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )

    assert resolution["status"] == "blocked"
    assert any(
        issue.startswith("narration_plan_casting_eligibility_missing:")
        for issue in resolution["issues"]
    )


def test_cached_work_package_cannot_resolve_after_casting_review_expiry() -> None:
    package = _package(
        '“Good morning,” Anna said.',
        speaker_profiles={
            "Anna": {
                "approved": True,
                "casting_approved": True,
                "speaker_profile_id": "private-anna-expiring-profile",
                "gender": "feminine",
            }
        },
    )

    resolution = resolve_memorial_narration_cast(
        work_package=package,
        voice_profile=_voice_profile(),
        now=datetime(2026, 7, 31, 9, 0, 1, tzinfo=UTC),
    )

    assert package["status"] == "ready_for_private_cast_resolution"
    assert resolution["status"] == "blocked"
    assert "speaker_casting_review_expired" in resolution["issues"]


def test_current_casting_review_revocation_invalidates_cached_work_package() -> None:
    package = _package(
        '“Good morning,” Anna said.',
        speaker_profiles={
            "Anna": {
                "approved": True,
                "casting_approved": True,
                "speaker_profile_id": "private-anna-revocable-profile",
                "gender": "feminine",
            }
        },
    )
    current_profiles = deepcopy(package.current_speaker_profiles)
    assert current_profiles is not None
    current_profiles["Anna"]["casting_review"]["revoked"] = True

    resolution = resolve_memorial_narration_cast(
        work_package=package,
        voice_profile=_voice_profile(),
        current_speaker_profiles=current_profiles,
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )

    assert resolution["status"] == "blocked"
    assert "current_speaker_casting_review_not_approved" in resolution["issues"]
    assert (
        "current_speaker_casting_review_revocation_state_invalid"
        in resolution["issues"]
    )


def test_current_normalized_profile_alias_tombstone_invalidates_cached_package() -> None:
    package = _package(
        '“Hello,” José said.',
        speaker_profiles={
            "José": {
                "approved": True,
                "casting_approved": True,
                "speaker_profile_id": "private-jose-current-profile",
                "gender": "masculine",
            }
        },
    )
    current_profiles = deepcopy(package.current_speaker_profiles)
    assert current_profiles is not None
    current_profiles["Jose"] = {
        "approved": False,
        "casting_approved": False,
        "speaker_profile_id": "private-jose-revocation-tombstone",
    }

    resolution = resolve_memorial_narration_cast(
        work_package=package,
        voice_profile=_voice_profile(),
        current_speaker_profiles=current_profiles,
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )

    assert resolution["status"] == "blocked"
    assert "current_speaker_casting_review_key_collision" in resolution["issues"]


@pytest.mark.parametrize(
    ("field", "value", "issue"),
    [
        (
            "speaker_casting_review_evidence_aggregate_sha256",
            "0" * 64,
            "work_package_speaker_casting_evidence_mismatch",
        ),
        (
            "revoked",
            True,
            "speaker_casting_review_revocation_state_invalid",
        ),
    ],
)
def test_cast_resolver_revalidates_casting_review_bindings(
    field: str,
    value: object,
    issue: str,
) -> None:
    package = _package(
        '“Good morning,” Anna said.',
        speaker_profiles={
            "Anna": {
                "approved": True,
                "casting_approved": True,
                "speaker_profile_id": "private-anna-bound-profile",
                "gender": "feminine",
            }
        },
    )
    if field == "revoked":
        package["speaker_casting_review_requirements"][0][field] = value
    else:
        package[field] = value

    resolution = resolve_memorial_narration_cast(
        work_package=package,
        voice_profile=_voice_profile(),
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )

    assert resolution["status"] == "blocked"
    assert issue in resolution["issues"]


def test_cast_resolution_rejects_malformed_and_duplicate_source_rows() -> None:
    package = _package("A purpose-reviewed source.")

    malformed = deepcopy(package)
    malformed["sources"].append("not-a-source-object")
    malformed_resolution = resolve_memorial_narration_cast(
        work_package=malformed,
        voice_profile=_voice_profile(),
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )

    duplicate = deepcopy(package)
    duplicate["sources"].append(deepcopy(duplicate["sources"][0]))
    duplicate_resolution = resolve_memorial_narration_cast(
        work_package=duplicate,
        voice_profile=_voice_profile(),
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )

    assert malformed_resolution["status"] == "blocked"
    assert "work_package_source_entry_invalid" in malformed_resolution["issues"]
    assert duplicate_resolution["status"] == "blocked"
    assert "work_package_source_href_duplicate" in duplicate_resolution["issues"]


@pytest.mark.parametrize("malformation", ["confidence", "traits"])
def test_malformed_plan_fields_block_instead_of_raising(
    malformation: str,
) -> None:
    package = _package('“Good morning,” Anna said.')
    if malformation == "confidence":
        dialogue = next(
            row
            for row in package["narration_plan"]["spans"]
            if row["kind"] == "dialogue"
        )
        dialogue["attribution_confidence"] = {"invalid": True}
    else:
        speaker = next(
            row
            for row in package["narration_plan"]["speakers"]
            if row["speaker_id"] != "narrator"
        )
        speaker["traits"] = "not-a-trait-mapping"

    resolution = resolve_memorial_narration_cast(
        work_package=package,
        voice_profile=_voice_profile(),
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )

    assert resolution["status"] == "blocked"
    assert "work_package_structure_invalid" in resolution["issues"]


def test_cast_resolution_rejects_legacy_permission_aggregate_without_source_id() -> (
    None
):
    package = _package("A purpose-reviewed source.")
    source = dict(package["sources"][0])
    package["provider_safe_receipt"][
        "narration_permission_evidence_aggregate_sha256"
    ] = cast_resolution_service._stable_json_sha256(
        [
            {
                "kind": source["kind"],
                "text_sha256": source["text_sha256"],
                "narration_review_evidence_sha256": source[
                    "narration_review_evidence_sha256"
                ],
            }
        ]
    )

    resolution = resolve_memorial_narration_cast(
        work_package=package,
        voice_profile=_voice_profile(),
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )

    assert resolution["status"] == "blocked"
    assert "receipt_narration_permission_evidence_mismatch" in resolution[
        "issues"
    ]


def test_current_consent_revocation_invalidates_a_previously_approved_review() -> None:
    package = _package("A reviewed source.")
    profile = _voice_profile()
    resolution = resolve_memorial_narration_cast(
        work_package=package,
        voice_profile=profile,
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )
    review = _review(resolution)
    revoked_profile = deepcopy(profile)
    revoked_profile["voice_consent"]["revoked"] = True

    receipt = verify_memorial_narration_cast(
        work_package=package,
        resolution=resolution,
        review=review,
        voice_profile=revoked_profile,
        signing_secret=REVIEW_SECRET,
        now=VERIFY_AT,
    )

    assert receipt["status"] == "blocked"
    assert receipt["synthesis_authorized"] is False
    assert "voice_consent_revoked" in receipt["issues"]
    assert "voice_consent_evidence_changed_since_resolution" in receipt["issues"]


def test_current_narrator_profile_ref_change_invalidates_narrator_only_review() -> None:
    package = _package("A reviewed narrator-only source.")
    profile = _voice_profile()
    resolution = resolve_memorial_narration_cast(
        work_package=package,
        voice_profile=profile,
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )
    review = _review(resolution)
    changed_profile = deepcopy(profile)
    changed_profile["voice_profile_id"] = "different-private-narrator-profile"

    receipt = verify_memorial_narration_cast(
        work_package=package,
        resolution=resolution,
        review=review,
        voice_profile=changed_profile,
        signing_secret=REVIEW_SECRET,
        now=VERIFY_AT,
    )

    assert receipt["status"] == "blocked"
    assert receipt["cast_mapping_reviewed"] is False
    assert (
        "narrator_voice_profile_ref_changed_since_resolution" in receipt["issues"]
    )
    assert "current_cast_narrator_voice_profile_ref_mismatch" in receipt["issues"]


def test_final_verifier_re_resolves_narrator_only_cast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _package("A reviewed narrator-only source.")
    profile = _voice_profile()
    resolution = resolve_memorial_narration_cast(
        work_package=package,
        voice_profile=profile,
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )
    review = _review(resolution)
    original_resolver = cast_resolution_service.resolve_memorial_narration_cast
    resolver_calls: list[dict[str, object]] = []

    def tracked_resolver(**kwargs: object) -> dict[str, object]:
        resolver_calls.append(dict(kwargs))
        return original_resolver(**kwargs)

    monkeypatch.setattr(
        cast_resolution_service,
        "resolve_memorial_narration_cast",
        tracked_resolver,
    )

    receipt = verify_memorial_narration_cast(
        work_package=package,
        resolution=resolution,
        review=review,
        voice_profile=profile,
        signing_secret=REVIEW_SECRET,
        now=VERIFY_AT,
    )

    assert receipt["status"] == "pass"
    assert len(resolver_calls) == 1
    assert resolver_calls[0]["work_package"] is package
    assert resolver_calls[0]["voice_profile"] is profile


def test_mapping_review_requires_bounded_nonfuture_expiry() -> None:
    package = _package("A reviewed source.")
    resolution = resolve_memorial_narration_cast(
        work_package=package,
        voice_profile=_voice_profile(),
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="cast_review_expiry_required"):
        build_memorial_narration_cast_review(
            resolution=resolution,
            reviewer="private-reviewer",
            signing_secret=REVIEW_SECRET,
            reviewed_at=REVIEWED_AT,
        )
    with pytest.raises(ValueError, match="cast_review_timestamp_in_future"):
        build_memorial_narration_cast_review(
            resolution=resolution,
            reviewer="private-reviewer",
            signing_secret=REVIEW_SECRET,
            reviewed_at="2099-01-01T00:00:00Z",
            expires_at="2099-01-02T00:00:00Z",
        )
    with pytest.raises(ValueError, match="cast_review_expiry_too_distant"):
        build_memorial_narration_cast_review(
            resolution=resolution,
            reviewer="private-reviewer",
            signing_secret=REVIEW_SECRET,
            reviewed_at=REVIEWED_AT,
            expires_at="2026-07-19T10:00:01Z",
        )

    review = _review(resolution)
    expired = verify_memorial_narration_cast(
        work_package=package,
        resolution=resolution,
        review=review,
        voice_profile=_voice_profile(),
        signing_secret=REVIEW_SECRET,
        now=datetime(2026, 7, 18, 10, 0, 1, tzinfo=UTC),
    )
    assert expired["cast_mapping_reviewed"] is False
    assert expired["synthesis_authorized"] is False
    assert "cast_review_expired" in expired["issues"]


def test_dialogue_requires_an_explicit_approved_mapping() -> None:
    package = _package('“Please come in,” Anna said.')
    speaker_id = _dialogue_handoff(package)[0]["speaker_id"]

    missing = resolve_memorial_narration_cast(
        work_package=package,
        voice_profile=_voice_profile(),
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )

    assert missing["status"] == "blocked"
    assert f"dialogue_voice_mapping_missing:{speaker_id}" in missing["issues"]

    approved = resolve_memorial_narration_cast(
        work_package=package,
        voice_profile=_voice_profile(),
        speaker_voice_mappings={
            speaker_id: _approved_mapping(
                provider="unmixr_clone",
                voice_id="raw-private-anna-voice-id",
                language="en-US",
            )
        },
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )

    assert approved["status"] == "ready_for_mapping_review"
    assert approved["dialogue_cast"][0]["speaker_id"] == speaker_id
    assert approved["dialogue_cast"][0]["mapping_kind"] == (
        "explicit_approved_per_speaker_mapping"
    )
    assert approved["narrator_excluded_from_dialogue"] is True


@pytest.mark.parametrize(
    "invalid_state",
    [
        {"revoked": True},
        {"expires_at": "2026-07-11T09:58:59Z"},
        {"expires_at": "not-a-time"},
    ],
)
def test_revoked_or_expired_dialogue_mapping_is_never_approved(
    invalid_state: dict[str, object],
) -> None:
    package = _package('“Please come in,” Anna said.')
    speaker_id = str(_dialogue_handoff(package)[0]["speaker_id"])
    mapping = _approved_mapping(
        provider="unmixr_clone",
        voice_id="raw-private-revoked-dialogue-voice",
        language="en-US",
        **invalid_state,
    )

    resolution = resolve_memorial_narration_cast(
        work_package=package,
        voice_profile=_voice_profile(),
        speaker_voice_mappings={speaker_id: mapping},
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )

    assert resolution["status"] == "blocked"
    assert (
        f"dialogue_voice_mapping_not_explicitly_approved:{speaker_id}"
        in resolution["issues"]
    )


@pytest.mark.parametrize(
    "invalid_state",
    [
        "missing_revoked",
        "string_revoked",
        "missing_reviewed_at",
        "missing_expires_at",
        "multiple_approvers",
        "future_review",
        "ttl_too_long",
    ],
)
def test_mapping_approval_requires_one_bounded_current_authority_record(
    invalid_state: str,
) -> None:
    now = datetime(2026, 7, 11, 9, 59, tzinfo=UTC)
    mapping = _approved_mapping()
    assert cast_resolution_service._mapping_is_approved(
        mapping,
        now=now,
    ) is True
    if invalid_state == "missing_revoked":
        mapping.pop("revoked")
    elif invalid_state == "string_revoked":
        mapping["revoked"] = "false"
    elif invalid_state == "missing_reviewed_at":
        mapping.pop("reviewed_at")
    elif invalid_state == "missing_expires_at":
        mapping.pop("expires_at")
    elif invalid_state == "multiple_approvers":
        mapping["approved_by_user"] = True
    elif invalid_state == "future_review":
        mapping["reviewed_at"] = "2026-07-11T10:05:01Z"
    else:
        mapping["expires_at"] = "2026-07-18T09:58:01Z"

    assert cast_resolution_service._mapping_is_approved(
        mapping,
        now=now,
    ) is False


@pytest.mark.parametrize(
    "tombstone",
    [
        {"status": "approved", "approved_by_family": True, "revoked": True},
        {"status": "rejected", "approved_by_family": False},
    ],
)
def test_competing_mapping_tombstone_clears_prior_approval(
    tombstone: dict[str, object],
) -> None:
    package = _package('“Please come in,” Anna said.')
    speaker_id = str(_dialogue_handoff(package)[0]["speaker_id"])
    approved = _approved_mapping(
        speaker_id=speaker_id,
        provider="unmixr_clone",
        voice_id="raw-private-old-dialogue-voice",
        language="en-US",
    )
    competing = {
        **approved,
        **tombstone,
        "voice_id": "raw-private-tombstone-dialogue-voice",
    }

    resolution = resolve_memorial_narration_cast(
        work_package=package,
        voice_profile=_voice_profile(),
        speaker_voice_mappings=[approved, competing],
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )

    assert resolution["status"] == "blocked"
    assert f"dialogue_voice_mapping_ambiguous:{speaker_id}" in (
        resolution["issues"]
    )


def test_cast_resolution_rejects_unreviewed_uncertain_attribution() -> None:
    package = _package(
        '“Who is there?”',
        approve_uncertain_attributions=False,
    )

    resolution = resolve_memorial_narration_cast(
        work_package=package,
        voice_profile=_voice_profile(),
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )

    assert package["status"] == "blocked_speaker_attribution_review"
    assert resolution["status"] == "blocked"
    assert "speaker_attribution_review_not_approved" in resolution["issues"]
    assert "cast_handoff_speaker_attribution_review_incomplete" in (
        resolution["issues"]
    )


def test_signed_cast_review_explicitly_attests_speaker_attribution_scope() -> None:
    package = _package('“Who is there?”')
    speaker_id = str(_dialogue_handoff(package)[0]["speaker_id"])
    mappings = {
        "neutral_mapping": _approved_mapping(
            neutral_approved=True,
            provider="unmixr_clone",
            voice_id="raw-private-neutral-dialogue-voice",
            language="en-US",
        )
    }
    resolution = resolve_memorial_narration_cast(
        work_package=package,
        voice_profile=_voice_profile(),
        speaker_voice_mappings=mappings,
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )

    assert resolution["status"] == "ready_for_mapping_review"
    assert resolution["dialogue_cast"][0]["speaker_id"] == speaker_id
    assert resolution["speaker_attribution_review_required_count"] == 1
    review = _review(resolution)
    assert REQUIRED_SPEAKER_ATTRIBUTION_SCOPE in review["attested_scopes"]

    receipt = verify_memorial_narration_cast(
        work_package=package,
        resolution=resolution,
        review=review,
        voice_profile=_voice_profile(),
        speaker_voice_mappings=mappings,
        signing_secret=REVIEW_SECRET,
        now=VERIFY_AT,
    )

    assert receipt["status"] == "pass"
    assert receipt["speaker_attribution_review_attested"] is True
    assert receipt["review"]["speaker_attribution_scope_attested"] is True


def test_current_attribution_revocation_invalidates_cached_work_package() -> None:
    package = _package('“Who is there?”')
    current_manifest = deepcopy(package.current_memorial_manifest)
    assert current_manifest is not None
    current_manifest["speaker_attribution_reviews"][0]["revoked"] = True

    resolution = resolve_memorial_narration_cast(
        work_package=package,
        voice_profile=_voice_profile(),
        current_memorial_manifest=current_manifest,
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )

    assert resolution["status"] == "blocked"
    assert (
        "current_speaker_attribution_review_not_approved"
        in resolution["issues"]
    )


@pytest.mark.parametrize(
    "tombstone",
    [
        {"revoked": True},
        {"status": "rejected"},
    ],
)
def test_competing_attribution_tombstone_clears_prior_approval(
    tombstone: dict[str, object],
) -> None:
    package = _package('“Who is there?”')
    current_manifest = deepcopy(package.current_memorial_manifest)
    assert current_manifest is not None
    competing = deepcopy(current_manifest["speaker_attribution_reviews"][0])
    competing.update(tombstone)
    current_manifest["speaker_attribution_reviews"].append(competing)

    resolution = resolve_memorial_narration_cast(
        work_package=package,
        voice_profile=_voice_profile(),
        current_memorial_manifest=current_manifest,
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )

    assert resolution["status"] == "blocked"
    assert (
        "current_speaker_attribution_review_not_approved"
        in resolution["issues"]
    )


def test_signed_cast_review_explicitly_attests_speaker_casting_scope() -> None:
    package = _package(
        '“Good morning,” Anna said.',
        speaker_profiles={
            "Anna": {
                "approved": True,
                "casting_approved": True,
                "speaker_profile_id": "private-anna-attested-profile",
                "gender": "feminine",
            }
        },
    )
    handoff = _dialogue_handoff(package)[0]
    speaker_id = str(handoff["speaker_id"])
    mappings = {
        speaker_id: _approved_mapping(
            speaker_profile_ref_sha256=handoff["profile_ref_sha256"],
            provider="unmixr_clone",
            voice_id="raw-private-anna-attested-voice",
            language="en-US",
            voice_traits={"gender": "female"},
        )
    }
    resolution = resolve_memorial_narration_cast(
        work_package=package,
        voice_profile=_voice_profile(),
        speaker_voice_mappings=mappings,
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )

    assert resolution["status"] == "ready_for_mapping_review"
    assert resolution["speaker_casting_review_required_count"] == 1
    review = _review(resolution)
    assert REQUIRED_SPEAKER_CASTING_SCOPE in review["attested_scopes"]

    receipt = verify_memorial_narration_cast(
        work_package=package,
        resolution=resolution,
        review=review,
        voice_profile=_voice_profile(),
        speaker_voice_mappings=mappings,
        signing_secret=REVIEW_SECRET,
        now=VERIFY_AT,
    )

    assert receipt["status"] == "pass"
    assert receipt["speaker_casting_review_attested"] is True
    assert receipt["review"]["speaker_casting_scope_attested"] is True


def test_non_latin_speaker_profile_key_resolves_end_to_end() -> None:
    package = _package(
        '“Доброе утро,” Анна said.',
        speaker_profiles={
            "Анна": {
                "approved": True,
                "casting_approved": True,
                "speaker_profile_id": "private-cyrillic-anna-profile",
                "gender": "feminine",
            }
        },
    )
    handoff = _dialogue_handoff(package)[0]
    speaker_id = str(handoff["speaker_id"])

    resolution = resolve_memorial_narration_cast(
        work_package=package,
        voice_profile=_voice_profile(),
        speaker_voice_mappings={
            speaker_id: _approved_mapping(
                speaker_profile_ref_sha256=handoff[
                    "profile_ref_sha256"
                ],
                provider="unmixr_clone",
                voice_id="raw-private-cyrillic-anna-voice",
                language="en-US",
                voice_traits={"gender": "female"},
            )
        },
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )

    assert package["status"] == "ready_for_private_cast_resolution"
    assert handoff["explicit_profile"] is True
    assert resolution["status"] == "ready_for_mapping_review"


def test_dialogue_speakers_cannot_silently_share_one_voice() -> None:
    package = _package(
        '“Please come in,” Anna said. “I am here,” Ben replied.'
    )
    speaker_ids = [str(row["speaker_id"]) for row in _dialogue_handoff(package)]
    assert len(speaker_ids) == 2
    mappings = {
        speaker_id: _approved_mapping(
            provider="unmixr_clone",
            voice_id="raw-private-shared-dialogue-voice",
            language="en-US",
        )
        for speaker_id in speaker_ids
    }

    resolution = resolve_memorial_narration_cast(
        work_package=package,
        voice_profile=_voice_profile(),
        speaker_voice_mappings=mappings,
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )

    assert resolution["status"] == "blocked"
    assert any(
        issue.startswith("dialogue_voice_not_distinct_between_speakers:")
        for issue in resolution["issues"]
    )


def test_explicit_trait_mismatch_blocks_but_approved_neutral_is_allowed() -> None:
    profiles = {
        "Anna": {
            "approved": True,
            "casting_approved": True,
            "speaker_profile_id": "private-anna-speaker-profile",
            "gender": "feminine",
            "age_band": "older_adult",
            "ethnicity": "Austrian",
        }
    }
    profiled_package = _package(
        '“Good morning,” Anna said.', speaker_profiles=profiles
    )
    handoff = _dialogue_handoff(profiled_package)[0]
    speaker_id = str(handoff["speaker_id"])
    unverified = resolve_memorial_narration_cast(
        work_package=profiled_package,
        voice_profile=_voice_profile(),
        speaker_voice_mappings={
            speaker_id: _approved_mapping(
                speaker_profile_ref_sha256=handoff["profile_ref_sha256"],
                provider="unmixr_clone",
                voice_id="raw-private-unverified-profile-voice",
                language="en-US",
            )
        },
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )
    assert unverified["status"] == "blocked"
    assert f"dialogue_voice_trait_unverified:{speaker_id}" in unverified["issues"]

    mismatched = resolve_memorial_narration_cast(
        work_package=profiled_package,
        voice_profile=_voice_profile(),
        speaker_voice_mappings={
            speaker_id: _approved_mapping(
                speaker_profile_ref_sha256=handoff["profile_ref_sha256"],
                provider="unmixr_clone",
                voice_id="raw-private-wrong-profile-voice",
                language="en-US",
                voice_traits={
                    "gender": "male",
                    "age_band": "young_adult",
                    "ethnicity": "Canadian",
                },
            )
        },
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )

    assert mismatched["status"] == "blocked"
    assert f"dialogue_voice_trait_mismatch:{speaker_id}" in mismatched["issues"]

    unknown_package = _package('“Who is there?”')
    unknown_id = str(_dialogue_handoff(unknown_package)[0]["speaker_id"])
    neutral = resolve_memorial_narration_cast(
        work_package=unknown_package,
        voice_profile=_voice_profile(),
        speaker_voice_mappings={
            "neutral_mapping": _approved_mapping(
                neutral_approved=True,
                provider="unmixr_clone",
                voice_id="raw-private-neutral-dialogue-voice",
                language="en-US",
            )
        },
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )

    assert neutral["status"] == "ready_for_mapping_review"
    assert neutral["dialogue_cast"][0]["speaker_id"] == unknown_id
    assert neutral["dialogue_cast"][0]["mapping_kind"] == (
        "explicit_approved_neutral_mapping"
    )
    assert neutral["dialogue_cast"][0]["source_traits"] == {}
    assert neutral["identity_or_demographics_inferred"] is False


def test_profiled_speaker_voice_must_match_approved_language_and_style() -> None:
    package = _package(
        '“Good morning,” Anna said.',
        speaker_profiles={
            "Anna": {
                "approved": True,
                "casting_approved": True,
                "speaker_profile_id": "private-anna-language-style-profile",
                "language": "en-US",
                "style": "warm",
            }
        },
    )
    handoff = _dialogue_handoff(package)[0]
    speaker_id = str(handoff["speaker_id"])
    base_mapping = _approved_mapping(
        speaker_profile_ref_sha256=handoff["profile_ref_sha256"],
        provider="unmixr_clone",
        voice_id="raw-private-anna-voice-id",
        language="en-US",
    )

    mismatched = resolve_memorial_narration_cast(
        work_package=package,
        voice_profile=_voice_profile(),
        speaker_voice_mappings={
            speaker_id: {
                **base_mapping,
                "voice_traits": {"language": "de-DE", "style": "warm"},
            }
        },
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )
    assert mismatched["status"] == "blocked"
    assert f"dialogue_voice_trait_mismatch:{speaker_id}" in mismatched["issues"]

    unbound_catalog = resolve_memorial_narration_cast(
        work_package=package,
        voice_profile=_voice_profile(),
        speaker_voice_mappings={
            speaker_id: {
                **base_mapping,
                "catalog_traits": {
                    "style": {
                        "value": "warm",
                        "provenance": "provider_catalog_snapshot",
                    }
                },
            }
        },
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )
    assert unbound_catalog["status"] == "blocked"
    assert f"dialogue_voice_trait_unverified:{speaker_id}" in (
        unbound_catalog["issues"]
    )

    forged_catalog = resolve_memorial_narration_cast(
        work_package=package,
        voice_profile=_voice_profile(),
        speaker_voice_mappings={
            speaker_id: {
                **base_mapping,
                "catalog_snapshot_sha256": "d" * 64,
                "catalog_traits": {
                    "language": {
                        "value": "en",
                        "provenance": "provider_catalog_snapshot",
                    },
                    "style": {
                        "value": "warm",
                        "provenance": "provider_catalog_snapshot",
                    },
                },
            }
        },
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )
    assert forged_catalog["status"] == "blocked"
    assert f"dialogue_voice_trait_unverified:{speaker_id}" in (
        forged_catalog["issues"]
    )

    compatible = resolve_memorial_narration_cast(
        work_package=package,
        voice_profile=_voice_profile(),
        speaker_voice_mappings={
            speaker_id: {
                **base_mapping,
                "voice_traits": {"language": "en", "style": "warm"},
            }
        },
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )
    assert compatible["status"] == "ready_for_mapping_review"
    comparison = compatible["dialogue_cast"][0]["trait_comparison"]
    assert comparison["matched_trait_kinds"] == ["language", "style"]
    assert comparison["mismatched_trait_kinds"] == []
    assert comparison["unverified_trait_kinds"] == []


def test_resolution_and_review_tampering_fail_closed() -> None:
    package = _package("A reviewed source.")
    resolution = resolve_memorial_narration_cast(
        work_package=package,
        voice_profile=_voice_profile(),
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )
    review = _review(resolution)
    tampered_resolution = deepcopy(resolution)
    tampered_resolution["narrator"]["voice_id"] = "tampered-raw-voice-id"
    tampered_review = deepcopy(review)
    tampered_review["reviewer"] = "different-reviewer"

    resolution_receipt = verify_memorial_narration_cast(
        work_package=package,
        resolution=tampered_resolution,
        review=review,
        voice_profile=_voice_profile(),
        signing_secret=REVIEW_SECRET,
        now=VERIFY_AT,
    )
    review_receipt = verify_memorial_narration_cast(
        work_package=package,
        resolution=resolution,
        review=tampered_review,
        voice_profile=_voice_profile(),
        signing_secret=REVIEW_SECRET,
        now=VERIFY_AT,
    )

    assert resolution_receipt["synthesis_authorized"] is False
    assert "cast_resolution_sha256_mismatch" in resolution_receipt["issues"]
    assert "cast_resolution_narrator_voice_hash_mismatch" in (
        resolution_receipt["issues"]
    )
    assert review_receipt["synthesis_authorized"] is False
    assert "cast_review_sha256_mismatch" in review_receipt["issues"]
    assert "cast_review_signature_invalid" in review_receipt["issues"]


def test_final_verifier_requires_complete_dialogue_coverage_and_current_mapping() -> None:
    package = _package('“Please come in,” Anna said.')
    speaker_id = str(_dialogue_handoff(package)[0]["speaker_id"])
    mappings = {
        speaker_id: _approved_mapping(
            provider="unmixr_clone",
            voice_id="raw-private-anna-voice-id",
            language="en-US",
        )
    }
    resolution = resolve_memorial_narration_cast(
        work_package=package,
        voice_profile=_voice_profile(),
        speaker_voice_mappings=mappings,
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )
    assert resolution["status"] == "ready_for_mapping_review"

    missing_cast = deepcopy(resolution)
    missing_cast["dialogue_cast"] = []
    missing_cast["dialogue_speaker_count"] = 0
    missing_cast["resolved_cast_map_sha256"] = (
        cast_resolution_service._resolved_cast_map_sha256(  # noqa: SLF001
            dict(missing_cast["narrator"]), []
        )
    )
    missing_cast.pop("resolution_sha256", None)
    missing_cast["resolution_sha256"] = cast_resolution_service._stable_json_sha256(  # noqa: SLF001
        missing_cast
    )
    missing_review = _review(missing_cast)
    missing_receipt = verify_memorial_narration_cast(
        work_package=package,
        resolution=missing_cast,
        review=missing_review,
        voice_profile=_voice_profile(),
        speaker_voice_mappings=mappings,
        signing_secret=REVIEW_SECRET,
        now=VERIFY_AT,
    )
    assert missing_receipt["synthesis_authorized"] is False
    assert "cast_resolution_dialogue_coverage_mismatch" in missing_receipt["issues"]

    review = _review(resolution)
    revoked_mappings = deepcopy(mappings)
    revoked_mappings[speaker_id]["status"] = "rejected"
    revoked_mappings[speaker_id]["approved_by_user"] = False
    revoked_receipt = verify_memorial_narration_cast(
        work_package=package,
        resolution=resolution,
        review=review,
        voice_profile=_voice_profile(),
        speaker_voice_mappings=revoked_mappings,
        signing_secret=REVIEW_SECRET,
        now=VERIFY_AT,
    )
    assert revoked_receipt["synthesis_authorized"] is False
    assert (
        "current_cast_dialogue_voice_mapping_not_explicitly_approved"
        in revoked_receipt["issues"]
    )


def test_private_artifacts_are_atomic_mode_0600_and_symlinks_are_rejected(
    tmp_path: Path,
) -> None:
    package = _package("A reviewed source.")
    resolution = resolve_memorial_narration_cast(
        work_package=package,
        voice_profile=_voice_profile(),
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )
    output = tmp_path / "private" / "resolution.json"

    write_json_artifact(output, resolution, private=True)

    assert output.stat().st_mode & 0o777 == 0o600
    assert output.parent.stat().st_mode & 0o777 == 0o700
    assert read_json_artifact(output, private=True) == resolution

    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    symlink = output.parent / "symlink.json"
    symlink.symlink_to(target)
    with pytest.raises(ValueError, match="symlink_forbidden"):
        write_json_artifact(symlink, resolution, private=True)


def test_public_receipt_write_preserves_existing_sticky_parent_mode(
    tmp_path: Path,
) -> None:
    shared_root = tmp_path / "shared"
    shared_root.mkdir()
    shared_root.chmod(0o1777)
    receipt_path = shared_root / "cast.receipt.json"

    write_json_artifact(
        receipt_path,
        {"status": "ready", "raw_voice_ids_exposed": False},
        private=False,
    )

    assert shared_root.stat().st_mode & 0o7777 == 0o1777
    assert receipt_path.stat().st_mode & 0o777 == 0o644
    with pytest.raises(ValueError, match="private_parent_permissions_invalid"):
        write_json_artifact(
            shared_root / "private.json",
            {"private": True},
            private=True,
        )
    assert shared_root.stat().st_mode & 0o7777 == 0o1777

    private_root = tmp_path / "private-root"
    private_root.mkdir(mode=0o700)
    linked_root = tmp_path / "linked-root"
    linked_root.symlink_to(private_root, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink_ancestor_forbidden"):
        write_json_artifact(
            linked_root / "private.json",
            {"private": True},
            private=True,
        )


def test_safe_receipts_omit_linkable_voice_trait_and_reviewer_hashes() -> None:
    profiles = {
        "Anna": {
            "approved": True,
            "casting_approved": True,
            "speaker_profile_id": "private-anna-speaker-profile",
            "gender": "feminine",
            "age_band": "older_adult",
            "ethnicity": "Austrian",
        }
    }
    package = _package('“Good morning,” Anna said.', speaker_profiles=profiles)
    handoff = _dialogue_handoff(package)[0]
    speaker_id = str(handoff["speaker_id"])
    mappings = {
        speaker_id: _approved_mapping(
            speaker_profile_ref_sha256=handoff["profile_ref_sha256"],
            provider="unmixr_clone",
            voice_id="raw-private-anna-voice-id",
            language="en-US",
            voice_traits={
                "gender": "female",
                "age_band": "senior",
                "ethnicity": "Austrian",
            },
        )
    }
    resolution = resolve_memorial_narration_cast(
        work_package=package,
        voice_profile=_voice_profile(),
        speaker_voice_mappings=mappings,
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )
    review = _review(resolution)
    resolution_receipt = cast_resolution_safe_receipt(resolution)
    review_receipt = cast_review_safe_receipt(review)
    final_receipt = verify_memorial_narration_cast(
        work_package=package,
        resolution=resolution,
        review=review,
        voice_profile=_voice_profile(),
        signing_secret=REVIEW_SECRET,
        speaker_voice_mappings=mappings,
        now=VERIFY_AT,
    )
    serialized = json.dumps(
        {
            "resolution": resolution_receipt,
            "review": review_receipt,
            "final": final_receipt,
        },
        ensure_ascii=False,
        sort_keys=True,
    )

    assert resolution["status"] == "ready_for_mapping_review"
    assert final_receipt["cast_mapping_reviewed"] is True
    assert final_receipt["synthesis_authorized"] is False
    assert resolution_receipt["dialogue_cast"][0]["trait_match_status"] == (
        "matched_or_human_approved"
    )
    for private_value in (
        "raw-private-narrator-voice-id",
        "raw-private-anna-voice-id",
        "Austrian",
        "feminine",
        "older_adult",
        "family-reviewer-private-id",
    ):
        assert private_value not in serialized
    assert resolution_receipt["raw_voice_ids_exposed"] is False
    assert resolution_receipt["sensitive_trait_values_exposed"] is False
    assert review_receipt["raw_reviewer_exposed"] is False
    assert "reviewer_sha256" not in review_receipt
    assert "narrator_voice_id_sha256" not in resolution_receipt
    assert "voice_id_sha256" not in serialized
    assert "trait_value_sha256" not in serialized


def test_cli_resolve_review_verify_is_provider_free_and_keeps_private_parent_closed(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[2]
    script = root / "scripts" / "resolve_memorial_narration_cast.py"
    private_dir = tmp_path / "private"
    package_path = private_dir / "work-package.json"
    profile_path = private_dir / "voice-profile.json"
    resolution_path = private_dir / "resolution.json"
    review_path = private_dir / "review.json"
    receipt_path = private_dir / "verification-receipt.json"
    speaker_profiles_path = private_dir / "speaker-profiles.json"
    manifest_path = private_dir / "memorial-manifest.json"
    mappings_path = private_dir / "speaker-mappings.json"
    package = _package(
        '“Good morning,” Anna said.',
        speaker_profiles={
            "Anna": {
                "approved": True,
                "casting_approved": True,
                "speaker_profile_id": "private-cli-anna-profile",
                "gender": "feminine",
            }
        },
    )
    handoff = _dialogue_handoff(package)[0]
    speaker_id = str(handoff["speaker_id"])
    mappings = {
        speaker_id: _approved_mapping(
            speaker_profile_ref_sha256=handoff["profile_ref_sha256"],
            provider="unmixr_clone",
            voice_id="raw-private-cli-anna-voice",
            language="en-US",
            voice_traits={"gender": "female"},
        )
    }
    write_json_artifact(package_path, package, private=True)
    write_json_artifact(profile_path, _voice_profile(), private=True)
    write_json_artifact(
        speaker_profiles_path,
        package.current_speaker_profiles or {},
        private=True,
    )
    write_json_artifact(
        manifest_path,
        package.current_memorial_manifest or {},
        private=True,
    )
    write_json_artifact(mappings_path, mappings, private=True)
    env = os.environ.copy()
    env["EA_MEMORIAL_NARRATION_REVIEW_SIGNING_SECRET"] = REVIEW_SECRET.decode(
        "utf-8"
    )

    resolved = subprocess.run(
        [
            sys.executable,
            str(script),
            "resolve",
            "--work-package",
            str(package_path),
            "--voice-profile",
            str(profile_path),
            "--speaker-profiles",
            str(speaker_profiles_path),
            "--memorial-manifest",
            str(manifest_path),
            "--speaker-mappings",
            str(mappings_path),
            "--output",
            str(resolution_path),
        ],
        cwd=root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    reviewed = subprocess.run(
        [
            sys.executable,
            str(script),
            "review",
            "--resolution",
            str(resolution_path),
            "--reviewer",
            "private-cli-reviewer",
            "--expires-at",
            "2026-07-18T10:00:00Z",
            "--output",
            str(review_path),
        ],
        cwd=root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    verified = subprocess.run(
        [
            sys.executable,
            str(script),
            "verify",
            "--work-package",
            str(package_path),
            "--voice-profile",
            str(profile_path),
            "--resolution",
            str(resolution_path),
            "--review",
            str(review_path),
            "--speaker-profiles",
            str(speaker_profiles_path),
            "--memorial-manifest",
            str(manifest_path),
            "--speaker-mappings",
            str(mappings_path),
            "--receipt-output",
            str(receipt_path),
        ],
        cwd=root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert resolved.returncode == 0, resolved.stdout + resolved.stderr
    assert reviewed.returncode == 0, reviewed.stdout + reviewed.stderr
    assert verified.returncode == 0, verified.stdout + verified.stderr
    receipt = json.loads(verified.stdout)
    assert receipt["cast_mapping_reviewed"] is True
    assert receipt["synthesis_authorized"] is False
    assert receipt["provider_calls_made"] == 0
    assert private_dir.stat().st_mode & 0o777 == 0o700
    assert resolution_path.stat().st_mode & 0o777 == 0o600
    assert review_path.stat().st_mode & 0o777 == 0o600
    assert receipt_path.stat().st_mode & 0o777 == 0o644
    serialized = json.dumps(receipt, sort_keys=True)
    assert "raw-private-narrator-voice-id" not in serialized
    assert "private-cli-reviewer" not in serialized
