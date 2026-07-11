from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

import pytest

from app.services import memorial_family_contributions as family_contributions
from app.services import memorial_recovery_inventory


_SECRET = "PROVIDER_SECRET_MUST_NOT_LEAK"
_ARCHIVE_SOURCE = b"# Manfred life overview\n\nSource-faithful remembrance.\n"


@pytest.fixture(autouse=True)
def _clear_contribution_root_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EA_PUBLIC_MEMORIAL_CONTRIBUTION_DIR", raising=False)
    monkeypatch.delenv("EA_PRIVATE_MEMORIAL_CONTRIBUTION_DIR", raising=False)


def _write_json(path: Path, payload: dict[str, object], *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    path.chmod(mode)


def _roots(tmp_path: Path, name: str) -> tuple[Path, Path, Path]:
    base = tmp_path / name
    public = base / "public"
    private = base / "private"
    archive = base / "archive"
    public.mkdir(parents=True)
    private.mkdir(parents=True)
    archive.mkdir(parents=True)
    return public, private, archive


def _seed_flagship(public: Path, private: Path, archive: Path) -> None:
    public_slug = public / "manfred"
    private_slug = private / "manfred"
    public_audio = b"private-original-audio"
    voice_audio = b"reviewed-voice-profile-audio"
    (public_slug / "audio").mkdir(parents=True)
    (public_slug / "audio" / "original.mp3").write_bytes(public_audio)
    _write_json(
        public_slug / "memorial.json",
        {
            "slug": "manfred",
            "audio_clips": [
                {
                    "visibility": "private",
                    "asset_relpath": "audio/original.mp3",
                    "title": "Private source",
                }
            ],
        },
        mode=0o644,
    )

    (private_slug / "voice_profile").mkdir(parents=True)
    (private_slug / "voice_profile" / "voice.mp3").write_bytes(voice_audio)
    _write_json(
        private_slug / "tts_voice.json",
        {
            "voice_consent": True,
            "consent_basis": "documented_family_consent",
            "synthetic_voice_clone_of_memorial_person": False,
            "voice_profile_id": "manfred-reviewed-v1",
            "tts_mode": "provider_voice",
            "api_key": _SECRET,
        },
    )
    _write_json(
        private_slug / "voice_profile_manifest.json",
        {
            "manifest_version": "1",
            "slug": "manfred",
            "policy": {"voice_cloning_supported": False, "secret_note": _SECRET},
            "source": {"download_url": f"https://example.test/audio?token={_SECRET}"},
            "audio_assets": [
                {
                    "kind": "reviewed_clip",
                    "asset_relpath": "voice_profile/voice.mp3",
                    "sha256": hashlib.sha256(voice_audio).hexdigest(),
                    "size_bytes": len(voice_audio),
                    "analysis_status": "ok",
                    "source_label": _SECRET,
                }
            ],
        },
    )

    document_root = archive / "manfred" / "public" / "manfred-life-overview"
    (document_root / "build").mkdir(parents=True)
    html = b"<html><body>Manfred overview</body></html>"
    pdf = b"%PDF-1.4 recovery-test"
    (document_root / "build" / "index.html").write_bytes(html)
    (document_root / "build" / "output.pdf").write_bytes(pdf)
    (document_root / "source.md").write_bytes(_ARCHIVE_SOURCE)
    _write_json(
        document_root / "manifest.json",
        {
            "document_id": "manfred-life-overview",
            "title": "Life overview",
            "version": "1",
            "audience": "public",
            "sensitivity": "PUBLIC",
            "review_status": "published",
            "fliplink_url": f"https://archive.example.test/?secret={_SECRET}",
            "provider_api_key": _SECRET,
            "source_sha256": hashlib.sha256(b"source").hexdigest(),
            "sha256": hashlib.sha256(pdf).hexdigest(),
            "build_artifacts": {
                "html_path": "build/index.html",
                "pdf_path": "build/output.pdf",
            },
        },
    )

    private_record = {
        "contribution_id": "contribution-1",
        "status": "published",
        "visibility": "public",
        "submission": {
            "title": "A family memory",
            "body": "A private submitted version",
            "source_label": "Family",
            "contributor_name": "Relative",
            "relationship": "Family",
        },
        "publication_consent": True,
        "manage_token_hash": hashlib.sha256(b"manage-token").hexdigest(),
        "submitted_at": "2026-07-11T08:00:00Z",
        "updated_at": "2026-07-11T09:00:00Z",
        "published_at": "2026-07-11T09:00:00Z",
        "review": {"reviewer": "family-reviewer"},
        "public_memory": {
            "source_label": "Family",
            "title": "A family memory",
            "body": "The approved public version",
        },
        "history": [],
    }
    private_ledger = {
        "schema": family_contributions.PRIVATE_SCHEMA,
        "slug": "manfred",
        "created_at": "2026-07-11T08:00:00Z",
        "updated_at": "2026-07-11T09:00:00Z",
        "contributions": [private_record],
    }
    public_projection = {
        "schema": family_contributions.PUBLIC_SCHEMA,
        "slug": "manfred",
        "generated_at": "2026-07-11T09:00:00Z",
        "memory_cards": family_contributions._public_projection_rows([private_record]),  # noqa: SLF001
    }
    _write_json(private_slug / family_contributions.PRIVATE_FILENAME, private_ledger)
    _write_json(
        public_slug / family_contributions.PUBLIC_FILENAME,
        public_projection,
        mode=0o644,
    )


def _inventory_path(private: Path, filename: str = "flagship.inventory.json") -> Path:
    return private / "manfred" / "recovery_snapshots" / filename


def test_inventory_is_private_secret_free_and_fresh_root_restore_is_idempotent(
    tmp_path: Path,
) -> None:
    source_public, source_private, source_archive = _roots(tmp_path, "source")
    _seed_flagship(source_public, source_private, source_archive)
    source_inventory = _inventory_path(source_private)

    materialized = memorial_recovery_inventory.materialize_memorial_recovery_inventory(
        memorial_slug="manfred",
        destination_path=str(source_inventory),
        public_root=source_public,
        private_root=source_private,
        archive_root=source_archive,
    )

    assert materialized["source_media_count"] == 2
    assert materialized["archive_document_count"] == 1
    assert materialized["family_private_present"] is True
    assert materialized["family_public_present"] is True
    assert materialized["canonical_publication_state_included"] is False
    assert materialized["private_media_publication_performed"] is False
    assert stat.S_IMODE(source_inventory.stat().st_mode) == 0o600
    assert _SECRET.encode() not in source_inventory.read_bytes()
    verified = memorial_recovery_inventory.verify_memorial_recovery_inventory(
        inventory_path=str(source_inventory),
        expected_memorial_slug="manfred",
        private_root=source_private,
    )
    assert verified["valid"] is True
    assert verified["payload_sha256"] == materialized["payload_sha256"]

    target_public, target_private, target_archive = _roots(tmp_path, "target")
    target_inventory = _inventory_path(target_private)
    target_inventory.parent.mkdir(parents=True)
    target_inventory.write_bytes(source_inventory.read_bytes())
    target_inventory.chmod(0o600)

    planned = memorial_recovery_inventory.restore_memorial_recovery_inventory(
        inventory_path=str(target_inventory),
        expected_memorial_slug="manfred",
        dry_run=True,
        public_root=target_public,
        private_root=target_private,
        archive_root=target_archive,
    )
    assert planned["files_to_create"] == planned["files_in_inventory"]
    assert planned["files_created"] == 0
    assert not (target_private / "manfred" / "recovered_source_media").exists()

    restored = memorial_recovery_inventory.restore_memorial_recovery_inventory(
        inventory_path=str(target_inventory),
        expected_memorial_slug="manfred",
        dry_run=False,
        confirmed_payload_sha256=str(materialized["payload_sha256"]),
        public_root=target_public,
        private_root=target_private,
        archive_root=target_archive,
    )
    assert restored["files_created"] == restored["files_in_inventory"]
    assert restored["atomic_file_writes"] is True
    assert restored["idempotent_merge"] is True
    assert restored["private_media_published"] is False

    recovered_public_source = (
        target_private
        / "manfred"
        / "recovered_source_media"
        / "public_manifest"
        / "audio"
        / "original.mp3"
    )
    recovered_voice_source = (
        target_private
        / "manfred"
        / "recovered_source_media"
        / "voice_profile"
        / "voice_profile"
        / "voice.mp3"
    )
    assert recovered_public_source.read_bytes() == b"private-original-audio"
    assert recovered_voice_source.read_bytes() == b"reviewed-voice-profile-audio"
    assert stat.S_IMODE(recovered_public_source.stat().st_mode) == 0o600
    assert stat.S_IMODE(recovered_voice_source.stat().st_mode) == 0o600
    assert stat.S_IMODE(recovered_public_source.parent.stat().st_mode) == 0o700
    assert not (target_public / "manfred" / "audio").exists()

    recovered_html = (
        target_archive
        / "manfred"
        / "recovered_documents"
        / "public"
        / "manfred-life-overview"
        / "build"
        / "index.html"
    )
    assert recovered_html.read_bytes().startswith(b"<html>")
    assert stat.S_IMODE(recovered_html.stat().st_mode) == 0o600
    recovered_source = recovered_html.parent.parent / "source.md"
    assert recovered_source.read_bytes() == _ARCHIVE_SOURCE
    assert stat.S_IMODE(recovered_source.stat().st_mode) == 0o600
    archive_reference = recovered_html.parent.parent / "manifest.reference.json"
    assert _SECRET not in archive_reference.read_text(encoding="utf-8")
    assert "fliplink_url" not in archive_reference.read_text(encoding="utf-8")

    private_ledger = target_private / "manfred" / family_contributions.PRIVATE_FILENAME
    public_projection = target_public / "manfred" / family_contributions.PUBLIC_FILENAME
    references = target_private / "manfred" / "recovery_inventory.references.json"
    assert stat.S_IMODE(private_ledger.stat().st_mode) == 0o600
    assert stat.S_IMODE(public_projection.stat().st_mode) == 0o644
    assert stat.S_IMODE(references.stat().st_mode) == 0o600
    assert _SECRET not in references.read_text(encoding="utf-8")
    assert (
        json.loads(private_ledger.read_text(encoding="utf-8"))["contributions"][0][
            "manage_token_hash"
        ]
        == hashlib.sha256(b"manage-token").hexdigest()
    )
    assert (
        json.loads(public_projection.read_text(encoding="utf-8"))["memory_cards"][0][
            "body"
        ]
        == "The approved public version"
    )

    repeated = memorial_recovery_inventory.restore_memorial_recovery_inventory(
        inventory_path=str(target_inventory),
        expected_memorial_slug="manfred",
        dry_run=False,
        confirmed_payload_sha256=str(materialized["payload_sha256"]),
        public_root=target_public,
        private_root=target_private,
        archive_root=target_archive,
    )
    assert repeated["files_to_create"] == 0
    assert repeated["files_created"] == 0
    assert repeated["files_existing"] == repeated["files_in_inventory"]


def test_inventory_roundtrip_keeps_source_and_contribution_roots_separate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_public, source_private, source_archive = _roots(tmp_path, "split-source")
    _seed_flagship(source_public, source_private, source_archive)
    source_public_contributions = tmp_path / "split-source-contributions" / "public"
    source_private_contributions = tmp_path / "split-source-contributions" / "private"
    source_public_contribution = (
        source_public_contributions / "manfred" / family_contributions.PUBLIC_FILENAME
    )
    source_private_contribution = (
        source_private_contributions / "manfred" / family_contributions.PRIVATE_FILENAME
    )
    source_public_contribution.parent.mkdir(parents=True)
    source_private_contribution.parent.mkdir(parents=True)
    (source_public / "manfred" / family_contributions.PUBLIC_FILENAME).replace(
        source_public_contribution
    )
    (source_private / "manfred" / family_contributions.PRIVATE_FILENAME).replace(
        source_private_contribution
    )
    monkeypatch.setenv(
        "EA_PUBLIC_MEMORIAL_CONTRIBUTION_DIR",
        str(source_public_contributions),
    )
    monkeypatch.setenv(
        "EA_PRIVATE_MEMORIAL_CONTRIBUTION_DIR",
        str(source_private_contributions),
    )
    inventory = _inventory_path(source_private_contributions, "split.inventory.json")

    materialized = memorial_recovery_inventory.materialize_memorial_recovery_inventory(
        memorial_slug="manfred",
        destination_path=str(inventory),
        public_root=source_public,
        private_root=source_private,
        archive_root=source_archive,
    )

    assert materialized["family_private_present"] is True
    assert materialized["family_public_present"] is True
    assert not (
        source_public / "manfred" / family_contributions.PUBLIC_FILENAME
    ).exists()
    assert not (
        source_private / "manfred" / family_contributions.PRIVATE_FILENAME
    ).exists()
    assert not (source_private / "manfred" / "recovery_snapshots").exists()
    verified = memorial_recovery_inventory.verify_memorial_recovery_inventory(
        inventory_path=str(inventory),
        expected_memorial_slug="manfred",
        private_root=source_private,
        public_root=source_public,
    )
    assert verified["contribution_sources_verified"] is True
    changed_projection = json.loads(
        source_public_contribution.read_text(encoding="utf-8")
    )
    changed_projection["generated_at"] = "2026-07-11T10:00:00Z"
    _write_json(source_public_contribution, changed_projection, mode=0o644)
    with pytest.raises(ValueError, match="family_source_mismatch"):
        memorial_recovery_inventory.verify_memorial_recovery_inventory(
            inventory_path=str(inventory),
            expected_memorial_slug="manfred",
            private_root=source_private,
            public_root=source_public,
        )

    target_public, target_private, target_archive = _roots(tmp_path, "split-target")
    target_public_contributions = tmp_path / "split-target-contributions" / "public"
    target_private_contributions = tmp_path / "split-target-contributions" / "private"
    target_inventory = _inventory_path(
        target_private_contributions,
        "split.inventory.json",
    )
    target_inventory.parent.mkdir(parents=True)
    target_inventory.write_bytes(inventory.read_bytes())
    target_inventory.chmod(0o600)

    restored = memorial_recovery_inventory.restore_memorial_recovery_inventory(
        inventory_path=str(target_inventory),
        expected_memorial_slug="manfred",
        dry_run=False,
        confirmed_payload_sha256=str(materialized["payload_sha256"]),
        public_root=target_public,
        private_root=target_private,
        archive_root=target_archive,
        public_contribution_root=target_public_contributions,
        private_contribution_root=target_private_contributions,
    )

    assert restored["files_created"] == restored["files_in_inventory"]
    restored_private = (
        target_private_contributions / "manfred" / family_contributions.PRIVATE_FILENAME
    )
    restored_public = (
        target_public_contributions / "manfred" / family_contributions.PUBLIC_FILENAME
    )
    assert stat.S_IMODE(restored_private.stat().st_mode) == 0o600
    assert stat.S_IMODE(restored_private.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(restored_public.stat().st_mode) == 0o644
    assert not (
        target_private / "manfred" / family_contributions.PRIVATE_FILENAME
    ).exists()
    assert not (
        target_public / "manfred" / family_contributions.PUBLIC_FILENAME
    ).exists()
    assert json.loads(restored_private.read_text(encoding="utf-8"))["contributions"]
    assert json.loads(restored_public.read_text(encoding="utf-8"))["memory_cards"]


def test_inventory_rejects_inner_media_tamper_even_with_recomputed_envelope_digest(
    tmp_path: Path,
) -> None:
    public, private, archive = _roots(tmp_path, "tamper")
    _seed_flagship(public, private, archive)
    original = _inventory_path(private, "original.json")
    memorial_recovery_inventory.materialize_memorial_recovery_inventory(
        memorial_slug="manfred",
        destination_path=str(original),
        public_root=public,
        private_root=private,
        archive_root=archive,
    )
    envelope = json.loads(original.read_text(encoding="utf-8"))
    envelope["payload"]["source_media"][0]["content_base64"] = "dGFtcGVyZWQ="
    envelope["payload"]["source_media"][0]["size_bytes"] = len(b"tampered")
    envelope["payload_sha256"] = hashlib.sha256(
        memorial_recovery_inventory._canonical_json_bytes(envelope["payload"])  # noqa: SLF001
    ).hexdigest()
    tampered = _inventory_path(private, "tampered.json")
    tampered.write_text(json.dumps(envelope), encoding="utf-8")
    tampered.chmod(0o600)

    with pytest.raises(ValueError, match="file_digest_mismatch"):
        memorial_recovery_inventory.verify_memorial_recovery_inventory(
            inventory_path=str(tampered),
            expected_memorial_slug="manfred",
            private_root=private,
        )


def test_inventory_verification_requires_private_file_permissions(
    tmp_path: Path,
) -> None:
    public, private, archive = _roots(tmp_path, "permissions")
    _seed_flagship(public, private, archive)
    inventory = _inventory_path(private)
    memorial_recovery_inventory.materialize_memorial_recovery_inventory(
        memorial_slug="manfred",
        destination_path=str(inventory),
        public_root=public,
        private_root=private,
        archive_root=archive,
    )
    inventory.chmod(0o644)

    with pytest.raises(ValueError, match="file_not_private"):
        memorial_recovery_inventory.verify_memorial_recovery_inventory(
            inventory_path=str(inventory),
            expected_memorial_slug="manfred",
            private_root=private,
        )


def test_inventory_rejects_extra_fields_in_public_family_projection(
    tmp_path: Path,
) -> None:
    public, private, archive = _roots(tmp_path, "public-leak")
    _seed_flagship(public, private, archive)
    projection_path = public / "manfred" / family_contributions.PUBLIC_FILENAME
    projection = json.loads(projection_path.read_text(encoding="utf-8"))
    projection["provider_secret"] = _SECRET
    _write_json(projection_path, projection, mode=0o644)
    inventory = _inventory_path(private)

    with pytest.raises(ValueError, match="family_public_mismatch"):
        memorial_recovery_inventory.materialize_memorial_recovery_inventory(
            memorial_slug="manfred",
            destination_path=str(inventory),
            public_root=public,
            private_root=private,
            archive_root=archive,
        )

    assert not inventory.exists()
