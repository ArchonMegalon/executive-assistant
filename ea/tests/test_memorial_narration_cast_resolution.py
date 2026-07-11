from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
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
    resolve_memorial_narration_cast,
    verify_memorial_narration_cast,
    write_json_artifact,
)
from app.services.memorial_narration_work_package import (
    build_memorial_narration_work_package,
)


REVIEW_SECRET = b"bounded-test-review-secret-32-bytes"
REVIEWED_AT = "2026-07-11T10:00:00Z"
VERIFY_AT = datetime(2026, 7, 11, 10, 1, tzinfo=UTC)


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
) -> dict[str, object]:
    return build_memorial_narration_work_package(
        slug="manfred",
        memorial_manifest={
            "slug": "manfred",
            "memory_cards": [
                {
                    "title": "Reviewed remembrance",
                    "body": text,
                    "visibility": "public",
                    "approved": True,
                    "review_status": "approved",
                }
            ],
        },
        voice_profile=_voice_profile(),
        speaker_profiles=speaker_profiles,
        language="en-US",
        max_chars=256,
    )


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
            speaker_id: {
                "status": "approved",
                "approved_by_user": True,
                "provider": "unmixr_clone",
                "voice_id": "raw-private-anna-voice-id",
                "language": "en-US",
            }
        },
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )

    assert approved["status"] == "ready_for_mapping_review"
    assert approved["dialogue_cast"][0]["speaker_id"] == speaker_id
    assert approved["dialogue_cast"][0]["mapping_kind"] == (
        "explicit_approved_per_speaker_mapping"
    )
    assert approved["narrator_excluded_from_dialogue"] is True


def test_dialogue_speakers_cannot_silently_share_one_voice() -> None:
    package = _package(
        '“Please come in,” Anna said. “I am here,” Ben replied.'
    )
    speaker_ids = [str(row["speaker_id"]) for row in _dialogue_handoff(package)]
    assert len(speaker_ids) == 2
    mappings = {
        speaker_id: {
            "status": "approved",
            "approved_by_user": True,
            "provider": "unmixr_clone",
            "voice_id": "raw-private-shared-dialogue-voice",
            "language": "en-US",
        }
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
            speaker_id: {
                "status": "approved",
                "approved_by_user": True,
                "speaker_profile_ref_sha256": handoff["profile_ref_sha256"],
                "provider": "unmixr_clone",
                "voice_id": "raw-private-unverified-profile-voice",
                "language": "en-US",
            }
        },
        now=datetime(2026, 7, 11, 9, 59, tzinfo=UTC),
    )
    assert unverified["status"] == "blocked"
    assert f"dialogue_voice_trait_unverified:{speaker_id}" in unverified["issues"]

    mismatched = resolve_memorial_narration_cast(
        work_package=profiled_package,
        voice_profile=_voice_profile(),
        speaker_voice_mappings={
            speaker_id: {
                "status": "approved",
                "approved_by_user": True,
                "speaker_profile_ref_sha256": handoff["profile_ref_sha256"],
                "provider": "unmixr_clone",
                "voice_id": "raw-private-wrong-profile-voice",
                "language": "en-US",
                "voice_traits": {
                    "gender": "male",
                    "age_band": "young_adult",
                    "ethnicity": "Canadian",
                },
            }
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
            "neutral_mapping": {
                "status": "approved",
                "approved_by_user": True,
                "neutral_approved": True,
                "provider": "unmixr_clone",
                "voice_id": "raw-private-neutral-dialogue-voice",
                "language": "en-US",
            }
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
        speaker_id: {
            "status": "approved",
            "approved_by_user": True,
            "provider": "unmixr_clone",
            "voice_id": "raw-private-anna-voice-id",
            "language": "en-US",
        }
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
        speaker_id: {
            "status": "approved",
            "approved_by_family": True,
            "speaker_profile_ref_sha256": handoff["profile_ref_sha256"],
            "provider": "unmixr_clone",
            "voice_id": "raw-private-anna-voice-id",
            "language": "en-US",
            "voice_traits": {
                "gender": "female",
                "age_band": "senior",
                "ethnicity": "Austrian",
            },
        }
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
    write_json_artifact(package_path, _package("A reviewed source."), private=True)
    write_json_artifact(profile_path, _voice_profile(), private=True)
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
