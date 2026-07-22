from __future__ import annotations

import base64
import hashlib
import json
import shutil
import stat
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api.routes import public_memorial_surface, public_memorials
from app.services import memorial_recovery_inventory
from app.services.memorial_private_context import (
    PRIVATE_CONTEXT_DECLARATION,
    PRIVATE_CONTEXT_FILENAME,
    PRIVATE_OVERRIDE_FIELDS,
    MemorialPrivateContextError,
    load_private_memorial_context,
    merge_private_memorial_context,
    private_context_payload,
)


_ROOT = Path(__file__).resolve().parents[1]
_PUBLIC_MANIFEST = (
    _ROOT / "memorial_data" / "public_memorials" / "manfred" / "memorial.json"
)
_PRIVATE_ROOT = _ROOT / "memorial_data" / "private_memorial_profiles"
_LOCAL_CONTEXT_DIGEST = (
    "ba2194ce345f05cc81268ad96954e9d1c55e76b7058636a1cf092ff98d18d1de"
)


def _write_json(path: Path, payload: object, *, mode: int = 0o600) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )
    path.write_bytes(document)
    path.chmod(mode)
    return document


def _minimal_overrides(
    *, audio_clips: list[dict[str, object]] | None = None
) -> dict[str, object]:
    return {
        "audio_clips": list(audio_clips or []),
        "memory_cards": [],
        "candidate_recordings": [],
        "source_grounded_profile": [],
        "character_notes": [],
        "conversation_style": {},
        "external_sources": [],
        "memory_principal_id": "memorial:test",
        "chat_models": [{"llm_model": "memorial-local", "label": "Local"}],
        "chat_model_default": "memorial-local",
    }


def _declared_public_payload() -> dict[str, object]:
    return {
        "slug": "manfred",
        "title": "Public memorial",
        "private_context": dict(PRIVATE_CONTEXT_DECLARATION),
        "memory_cards": [{"visibility": "public", "approved": True, "title": "Public"}],
    }


def test_tracked_manfred_source_is_public_only_without_private_artifact() -> None:
    public_payload = json.loads(_PUBLIC_MANIFEST.read_text(encoding="utf-8"))

    assert public_payload["private_context"] == PRIVATE_CONTEXT_DECLARATION
    assert [
        len(public_payload[field])
        for field in (
            "audio_clips",
            "memory_cards",
            "candidate_recordings",
            "source_grounded_profile",
            "character_notes",
        )
    ] == [0, 6, 0, 9, 0]
    external_sources = public_payload["external_sources"]
    assert len(external_sources) == 13
    assert external_sources[0] == {
        "visibility": "public",
        "label": "Manfred Hoza: öffentliche Jimdo-Quelle",
        "url": (
            "https://mobbing-konkret.jimdofree.com/"
            "notwehrgesetze-angst-der-b%C3%BCrger-waffen-boom/"
        ),
        "status": "approved_public_reference",
        "approved": True,
    }
    assert all(
        isinstance(item, dict)
        and item.get("visibility") == "public"
        and str(item.get("url") or "").startswith("https://")
        and str(item.get("label") or "").strip()
        and str(item.get("status") or "").strip()
        for item in external_sources
    )
    assert "conversation_style" not in public_payload
    assert not {"memory_principal_id", "chat_models", "chat_model_default"} & set(
        public_payload
    )
    for field in ("memory_cards", "source_grounded_profile"):
        assert all(
            isinstance(item, dict)
            and item.get("visibility") == "public"
            and item.get("approved") is True
            for item in public_payload[field]
        )
    projection = public_memorials._public_memorial_payload(public_payload)
    assert "private_context" not in projection
    assert len(projection["external_sources"]) == 1
    assert projection["external_sources"][0]["approved"] is True
    assert str(projection["external_sources"][0]["url"]).startswith("https://")


def test_local_manfred_context_exact_audit_skips_when_not_provisioned() -> None:
    context_path = _PRIVATE_ROOT / "manfred" / PRIVATE_CONTEXT_FILENAME
    if not context_path.is_file():
        pytest.skip("private Manfred context is provisioned out of band")
    assert stat.S_IMODE(context_path.stat().st_mode) in {0o400, 0o600}
    raw_context = json.loads(context_path.read_text(encoding="utf-8"))
    assert raw_context["overrides_sha256"] == _LOCAL_CONTEXT_DIGEST

    overrides = load_private_memorial_context(
        private_root=_PRIVATE_ROOT, slug="manfred"
    )
    public_payload = json.loads(_PUBLIC_MANIFEST.read_text(encoding="utf-8"))
    internal_payload = merge_private_memorial_context(
        public_payload=public_payload,
        private_root=_PRIVATE_ROOT,
        slug="manfred",
    )
    assert [
        len(overrides[field])
        for field in (
            "audio_clips",
            "memory_cards",
            "candidate_recordings",
            "source_grounded_profile",
            "character_notes",
            "external_sources",
            "chat_models",
        )
    ] == [1, 9, 6, 38, 31, 12, 3]
    assert all(
        internal_payload[field] == overrides[field] for field in PRIVATE_OVERRIDE_FIELDS
    )


def test_manfred_public_projection_matches_with_or_without_private_provisioning() -> (
    None
):
    public_payload = json.loads(_PUBLIC_MANIFEST.read_text(encoding="utf-8"))
    internal_payload = merge_private_memorial_context(
        public_payload=public_payload,
        private_root=_PRIVATE_ROOT,
        slug="manfred",
    )
    assert public_memorials._public_memorial_payload(
        internal_payload
    ) == public_memorials._public_memorial_payload(public_payload)
    story_html = public_memorials._public_memorial_story_html(
        internal_payload,
        slug="manfred",
    )
    assert all(
        str(source.get("label") or "") not in story_html
        for source in list(internal_payload.get("external_sources") or [])
        if isinstance(source, dict) and source.get("approved") is not True
    )


def test_private_context_merge_is_idempotent_and_preserves_original_public_projection(
    tmp_path: Path,
) -> None:
    public_payload = _declared_public_payload()
    private_root = tmp_path / "private"
    overrides = _minimal_overrides()
    overrides["memory_cards"] = [
        {
            "visibility": "public",
            "approved": True,
            "title": "PRIVATE_IDEMPOTENCE_CANARY",
        }
    ]
    _write_json(
        private_root / "manfred" / PRIVATE_CONTEXT_FILENAME,
        private_context_payload(slug="manfred", overrides=overrides),
    )

    first = merge_private_memorial_context(
        public_payload=public_payload,
        private_root=private_root,
        slug="manfred",
    )
    second = merge_private_memorial_context(
        public_payload=first,
        private_root=private_root,
        slug="manfred",
    )

    assert second == first
    assert public_memorials._public_memorial_payload(second) == (
        public_memorials._public_memorial_payload(public_payload)
    )
    assert "PRIVATE_IDEMPOTENCE_CANARY" not in json.dumps(
        public_memorials._public_memorial_payload(second),
        ensure_ascii=False,
    )


def test_public_surface_excludes_public_looking_private_overlay(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    public_payload = {
        "slug": "manfred",
        "person_name": "Manfred",
        "title": "Tracked public title",
        "private_context": dict(PRIVATE_CONTEXT_DECLARATION),
        "audio_clips": [
            {
                "visibility": "public",
                "public": True,
                "title": "Tracked public audio",
                "asset_relpath": "audio/tracked-public.mp3",
            }
        ],
        "memory_cards": [
            {
                "visibility": "public",
                "public": True,
                "approved": True,
                "title": "TRACKED_PUBLIC_CANARY",
                "body": "Tracked public body",
            }
        ],
        "candidate_recordings": [],
        "source_grounded_profile": [],
        "character_notes": [],
        "external_sources": [],
    }
    private_root = tmp_path / "private"
    private_overrides = _minimal_overrides(
        audio_clips=[
            {
                "visibility": "public",
                "public": True,
                "title": "Private public-looking audio",
                "asset_relpath": "audio/private-canary.mp3",
            }
        ]
    )
    private_overrides["memory_cards"] = [
        {
            "visibility": "public",
            "public": True,
            "approved": True,
            "title": "PRIVATE_PROJECTION_CANARY",
            "body": "Private public-looking body",
        }
    ]
    _write_json(
        private_root / "manfred" / PRIVATE_CONTEXT_FILENAME,
        private_context_payload(slug="manfred", overrides=private_overrides),
    )
    merged = merge_private_memorial_context(
        public_payload=public_payload,
        private_root=private_root,
        slug="manfred",
    )
    monkeypatch.setattr(public_memorial_surface, "_load_memorial", lambda slug: merged)
    monkeypatch.setattr(
        public_memorial_surface,
        "merge_public_family_contributions",
        lambda *, slug, memorial: dict(memorial),
    )

    public_surface = public_memorial_surface._load_public_surface_memorial("manfred")
    public_json = json.dumps(
        public_memorial_surface._public_memorial_payload(public_surface),
        ensure_ascii=False,
    )
    public_html = public_memorial_surface._public_memorial_page_html(public_surface)

    assert "PRIVATE_PROJECTION_CANARY" not in public_json
    assert "PRIVATE_PROJECTION_CANARY" not in public_html
    assert "TRACKED_PUBLIC_CANARY" in public_json
    # The minimal public landing page is conversation-only. Approved public
    # archive material remains available through the JSON/asset projection but
    # must not be rendered back into the landing-page document.
    assert "TRACKED_PUBLIC_CANARY" not in public_html
    assert "Tracked public body" not in public_html

    bundle = tmp_path / "bundle"
    (bundle / "audio").mkdir(parents=True)
    tracked_audio = bundle / "audio" / "tracked-public.mp3"
    tracked_audio.write_bytes(b"tracked-public-audio")
    (bundle / "audio" / "private-canary.mp3").write_bytes(b"private-audio")
    monkeypatch.setattr(
        public_memorial_surface, "_memorial_bundle", lambda slug: bundle
    )
    monkeypatch.setattr(public_memorials, "_memorial_bundle", lambda slug: bundle)
    monkeypatch.setattr(public_memorials, "_load_memorial", lambda slug: merged)

    assert (
        public_memorial_surface._public_memorial_asset_file(
            "manfred", "audio/tracked-public.mp3"
        )
        == tracked_audio
    )
    assert (
        public_memorials._asset_file("manfred", "audio/tracked-public.mp3")
        == tracked_audio
    )
    with pytest.raises(HTTPException, match="memorial_file_not_found"):
        public_memorial_surface._public_memorial_asset_file(
            "manfred", "audio/private-canary.mp3"
        )
    with pytest.raises(HTTPException, match="memorial_file_not_found"):
        public_memorials._asset_file("manfred", "audio/private-canary.mp3")


def test_loader_reconstructs_exact_values_and_order_then_falls_back_for_malformed_context(
    monkeypatch, tmp_path: Path
) -> None:
    public_path = tmp_path / "public" / "manfred" / "memorial.json"
    private_root = tmp_path / "private"
    public_payload = _declared_public_payload()
    _write_json(public_path, public_payload, mode=0o644)
    monkeypatch.setattr(public_memorials, "_manifest_path", lambda slug: public_path)
    monkeypatch.setattr(public_memorials, "_private_profile_dir", lambda: private_root)

    assert public_memorials._load_memorial("manfred") == public_payload

    context_path = private_root / "manfred" / PRIVATE_CONTEXT_FILENAME
    ordered_memories = [
        {"visibility": "private", "title": "First", "body": "one"},
        {"visibility": "public", "title": "Second", "body": "two"},
        {"visibility": "private", "title": "Third", "body": "three"},
    ]
    overrides = _minimal_overrides()
    overrides["memory_cards"] = ordered_memories
    overrides["character_notes"] = ["first note", "second note"]
    stored = private_context_payload(slug="manfred", overrides=overrides)
    _write_json(context_path, stored)

    assert all(
        isinstance(item, dict) for item in stored["overrides"]["character_notes"]
    )
    reconstructed = public_memorials._load_memorial("manfred")
    assert reconstructed["memory_cards"] == ordered_memories
    assert reconstructed["character_notes"] == ["first note", "second note"]
    assert [item["title"] for item in reconstructed["memory_cards"]] == [
        "First",
        "Second",
        "Third",
    ]
    assert reconstructed["chat_models"] == overrides["chat_models"]

    context_path.write_text('{"schema":', encoding="utf-8")
    context_path.chmod(0o600)
    assert public_memorials._load_memorial("manfred") == public_payload
    assert (
        merge_private_memorial_context(
            public_payload=public_payload,
            private_root=private_root,
            slug="manfred",
        )
        == public_payload
    )


def test_private_context_reader_rejects_permissions_symlinks_and_nondict_items(
    tmp_path: Path,
) -> None:
    private_root = tmp_path / "private"
    context_path = private_root / "manfred" / PRIVATE_CONTEXT_FILENAME
    payload = private_context_payload(slug="manfred", overrides=_minimal_overrides())
    _write_json(context_path, payload, mode=0o644)
    with pytest.raises(MemorialPrivateContextError, match="permissions_invalid"):
        load_private_memorial_context(private_root=private_root, slug="manfred")

    context_path.unlink()
    target = tmp_path / "target.json"
    _write_json(target, payload)
    context_path.symlink_to(target)
    with pytest.raises(MemorialPrivateContextError, match="path_invalid"):
        load_private_memorial_context(private_root=private_root, slug="manfred")

    invalid = _minimal_overrides()
    for field in (
        "audio_clips",
        "memory_cards",
        "candidate_recordings",
        "source_grounded_profile",
        "external_sources",
        "chat_models",
    ):
        candidate = dict(invalid)
        candidate[field] = ["not-a-dict"]
        with pytest.raises(MemorialPrivateContextError, match="overrides_invalid"):
            private_context_payload(slug="manfred", overrides=candidate)


def _seed_split_recovery(tmp_path: Path) -> tuple[Path, Path, Path, Path, bytes, bytes]:
    public_root = tmp_path / "public"
    private_root = tmp_path / "private"
    archive_root = tmp_path / "archive"
    archive_root.mkdir(parents=True)
    public_slug = public_root / "manfred"
    private_slug = private_root / "manfred"
    media = b"private-source-audio"
    media_path = public_slug / "audio" / "original.mp3"
    media_path.parent.mkdir(parents=True)
    media_path.write_bytes(media)
    _write_json(
        public_slug / "memorial.json",
        {
            "slug": "manfred",
            "audio_clips": [],
            "private_context": dict(PRIVATE_CONTEXT_DECLARATION),
        },
        mode=0o644,
    )
    overrides = _minimal_overrides(
        audio_clips=[
            {
                "visibility": "private",
                "title": "Private source",
                "asset_relpath": "audio/original.mp3",
            }
        ]
    )
    context_document = _write_json(
        private_slug / PRIVATE_CONTEXT_FILENAME,
        private_context_payload(slug="manfred", overrides=overrides),
    )
    return (
        public_root,
        private_root,
        archive_root,
        private_slug,
        media,
        context_document,
    )


def test_recovery_v2_captures_media_and_restores_exact_private_context(
    tmp_path: Path,
) -> None:
    public_root, private_root, archive_root, private_slug, media, context_document = (
        _seed_split_recovery(tmp_path / "source")
    )
    inventory_path = private_slug / "recovery_snapshots" / "split.inventory.json"
    materialized = memorial_recovery_inventory.materialize_memorial_recovery_inventory(
        memorial_slug="manfred",
        destination_path=str(inventory_path),
        public_root=public_root,
        private_root=private_root,
        archive_root=archive_root,
    )
    verified = memorial_recovery_inventory.verify_memorial_recovery_inventory(
        inventory_path=str(inventory_path),
        expected_memorial_slug="manfred",
        private_root=private_root,
    )
    assert materialized["private_context_present"] is True
    assert materialized["source_media_count"] == 1
    assert verified["private_context_present"] is True

    target_public = tmp_path / "target" / "public"
    target_private = tmp_path / "target" / "private"
    target_archive = tmp_path / "target" / "archive"
    for root in (target_public, target_private, target_archive):
        root.mkdir(parents=True)
    target_inventory = (
        target_private / "manfred" / "recovery_snapshots" / "split.inventory.json"
    )
    target_inventory.parent.mkdir(parents=True)
    shutil.copyfile(inventory_path, target_inventory)
    target_inventory.chmod(0o600)
    restored = memorial_recovery_inventory.restore_memorial_recovery_inventory(
        inventory_path=str(target_inventory),
        expected_memorial_slug="manfred",
        dry_run=False,
        confirmed_payload_sha256=str(materialized["payload_sha256"]),
        public_root=target_public,
        private_root=target_private,
        archive_root=target_archive,
    )
    restored_context = target_private / "manfred" / PRIVATE_CONTEXT_FILENAME
    restored_media = (
        target_private
        / "manfred"
        / "recovered_source_media"
        / "private_context"
        / "audio"
        / "original.mp3"
    )
    assert restored["private_context_present"] is True
    assert restored_context.read_bytes() == context_document
    assert stat.S_IMODE(restored_context.stat().st_mode) == 0o600
    assert restored_media.read_bytes() == media
    load_private_memorial_context(private_root=target_private, slug="manfred")

    repeated = memorial_recovery_inventory.restore_memorial_recovery_inventory(
        inventory_path=str(target_inventory),
        expected_memorial_slug="manfred",
        dry_run=False,
        confirmed_payload_sha256=str(materialized["payload_sha256"]),
        public_root=target_public,
        private_root=target_private,
        archive_root=target_archive,
    )
    assert repeated["files_created"] == 0
    assert repeated["files_existing"] == repeated["files_in_inventory"]


def test_recovery_v2_rejects_inner_private_context_tamper_with_recomputed_outer_digest(
    tmp_path: Path,
) -> None:
    public_root, private_root, archive_root, private_slug, _media, _context = (
        _seed_split_recovery(tmp_path)
    )
    original = private_slug / "recovery_snapshots" / "original.json"
    memorial_recovery_inventory.materialize_memorial_recovery_inventory(
        memorial_slug="manfred",
        destination_path=str(original),
        public_root=public_root,
        private_root=private_root,
        archive_root=archive_root,
    )
    envelope = json.loads(original.read_text(encoding="utf-8"))
    context_entry = envelope["payload"]["private_context"]
    context_payload = json.loads(
        base64.b64decode(context_entry["content_base64"], validate=True)
    )
    context_payload["overrides"]["memory_principal_id"] = "tampered"
    tampered_context = json.dumps(
        context_payload, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    context_entry["content_base64"] = base64.b64encode(tampered_context).decode("ascii")
    context_entry["size_bytes"] = len(tampered_context)
    context_entry["sha256"] = hashlib.sha256(tampered_context).hexdigest()
    envelope["payload_sha256"] = hashlib.sha256(
        memorial_recovery_inventory._canonical_json_bytes(envelope["payload"])
    ).hexdigest()
    tampered = private_slug / "recovery_snapshots" / "tampered.json"
    _write_json(tampered, envelope)

    with pytest.raises(ValueError, match="private_context_invalid"):
        memorial_recovery_inventory.verify_memorial_recovery_inventory(
            inventory_path=str(tampered),
            expected_memorial_slug="manfred",
            private_root=private_root,
        )
