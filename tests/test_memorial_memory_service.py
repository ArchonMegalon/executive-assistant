from __future__ import annotations

import json
import multiprocessing
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.services import memorial_memory


class _FakeMemoryRuntime:
    snapshot_storage_durable = False

    def __init__(self) -> None:
        self.created_items: list[dict[str, object]] = []

    def create_memory_item(self, **kwargs):
        item = dict(kwargs)
        if not item.get("last_verified_at"):
            item["last_verified_at"] = "2026-06-19T00:00:00+00:00"
        self.created_items.append(item)
        return None

    def list_items(self, *, limit: int = 100, principal_id: str | None = None):
        rows = []
        for index, item in enumerate(self.created_items):
            if principal_id and item.get("principal_id") != principal_id:
                continue
            rows.append(
                SimpleNamespace(
                    item_id=f"item-{index}",
                    principal_id=item.get("principal_id", ""),
                    category=item.get("category", ""),
                    summary=item.get("summary", ""),
                    fact_json=item.get("fact_json", {}),
                    provenance_json=item.get("provenance_json", {}),
                    confidence=item.get("confidence", 0.5),
                    sensitivity=item.get("sensitivity", "internal"),
                    sharing_policy=item.get("sharing_policy", "private"),
                    reviewer=item.get("reviewer", ""),
                    last_verified_at=item.get("last_verified_at"),
                    updated_at=f"2026-06-19T00:00:{index:02d}Z",
                )
            )
        return rows[:limit]

    def export_principal_snapshot(self, *, principal_id: str, max_items: int):
        rows = self.list_items(limit=max_items + 1, principal_id=principal_id)
        if len(rows) > max_items:
            raise memorial_memory.MemoryItemSnapshotLimitExceeded(
                principal_id=principal_id,
                max_items=max_items,
            )
        return rows


def test_seed_memorial_source_memories_repairs_fresh_store_from_existing_manifest(
    monkeypatch,
) -> None:
    manifest: dict[str, object] = {"processed_keys": []}

    def load_manifest(_slug: str) -> dict[str, object]:
        return dict(manifest)

    def save_manifest(_slug: str, payload: dict[str, object]) -> None:
        manifest.clear()
        manifest.update(payload)

    monkeypatch.setattr(memorial_memory, "_load_seed_manifest", load_manifest)
    monkeypatch.setattr(memorial_memory, "_save_seed_manifest", save_manifest)
    payload = {
        "memory_cards": [
            {
                "public": True,
                "title": "Gerechtigkeit",
                "body": "Tatsachen, Verantwortung und Fairness gehoeren zusammen.",
            }
        ]
    }

    first_runtime = _FakeMemoryRuntime()
    first = memorial_memory.seed_memorial_source_memories(
        memory_runtime=first_runtime,
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        memorial_payload=payload,
        reviewer="test",
    )
    fresh_runtime = _FakeMemoryRuntime()
    repaired = memorial_memory.seed_memorial_source_memories(
        memory_runtime=fresh_runtime,
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        memorial_payload=payload,
        reviewer="test",
    )
    manifest["processed_keys"] = []
    replayed = memorial_memory.seed_memorial_source_memories(
        memory_runtime=fresh_runtime,
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        memorial_payload=payload,
        reviewer="test",
    )

    assert first["created"] == 1
    assert repaired["created"] == 1
    assert repaired["public_approval_keys"] == first["public_approval_keys"]
    assert replayed["created"] == 0
    assert replayed["public_approval_keys"] == first["public_approval_keys"]
    assert len(fresh_runtime.created_items) == 1
    stored = fresh_runtime.created_items[0]
    assert stored["fact_json"]["public_approved"] is True
    assert (
        stored["fact_json"]["public_approval_key"]
        == repaired["public_approval_keys"][0]
    )
    assert (
        stored["provenance_json"]["public_approval_key"]
        == repaired["public_approval_keys"][0]
    )
    retrieved = memorial_memory.retrieve_memorial_memory_items(
        memory_runtime=fresh_runtime,
        principal_id="memorial:manfred",
        question="Gerechtigkeit Verantwortung Fairness",
        public_only=True,
        public_approval_keys=repaired["public_approval_keys"],
    )
    assert len(retrieved) == 1
    assert retrieved[0].summary.startswith("Gerechtigkeit:")


def test_seed_memorial_source_memories_ignores_malformed_legacy_provenance(
    monkeypatch,
) -> None:
    runtime = _FakeMemoryRuntime()
    runtime.created_items.append(
        {
            "principal_id": "memorial:manfred",
            "category": "legacy",
            "summary": "Malformed legacy row",
            "fact_json": {},
            "provenance_json": ["not", "a", "mapping"],
        }
    )
    monkeypatch.setattr(
        memorial_memory,
        "_load_seed_manifest",
        lambda _slug: {"processed_keys": []},
    )
    monkeypatch.setattr(
        memorial_memory,
        "_save_seed_manifest",
        lambda _slug, _payload: None,
    )

    result = memorial_memory.seed_memorial_source_memories(
        memory_runtime=runtime,
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        memorial_payload={
            "suggested_prompts": ["Welche Erinnerung ist freigegeben?"],
        },
        reviewer="test",
    )

    assert result["created"] == 1
    assert len(runtime.created_items) == 2


def test_seed_memorial_source_memories_fails_closed_on_incomplete_snapshot(
    monkeypatch,
) -> None:
    class _OversizedMemoryRuntime(_FakeMemoryRuntime):
        def export_principal_snapshot(
            self,
            *,
            principal_id: str,
            max_items: int,
        ):
            raise memorial_memory.MemoryItemSnapshotLimitExceeded(
                principal_id=principal_id,
                max_items=max_items,
            )

    monkeypatch.setattr(
        memorial_memory,
        "_load_seed_manifest",
        lambda _slug: {"processed_keys": []},
    )
    runtime = _OversizedMemoryRuntime()

    with pytest.raises(
        ValueError,
        match="memorial_seed_reconciliation_incomplete",
    ):
        memorial_memory.seed_memorial_source_memories(
            memory_runtime=runtime,
            principal_id="memorial:manfred",
            memorial_slug="manfred",
            memorial_payload={
                "suggested_prompts": ["Welche Erinnerung ist freigegeben?"],
            },
            reviewer="test",
        )

    assert runtime.created_items == []


def test_seed_memorial_source_memories_rotates_key_when_public_material_changes(
    monkeypatch,
) -> None:
    runtime = _FakeMemoryRuntime()
    manifest: dict[str, object] = {"processed_keys": []}
    monkeypatch.setattr(
        memorial_memory,
        "_load_seed_manifest",
        lambda _slug: dict(manifest),
    )

    def save_manifest(_slug: str, payload: dict[str, object]) -> None:
        manifest.clear()
        manifest.update(payload)

    monkeypatch.setattr(memorial_memory, "_save_seed_manifest", save_manifest)
    original = {
        "memory_cards": [
            {
                "public": True,
                "title": "Gerechtigkeit",
                "body": "Tatsachen und Fairness gehoeren zusammen.",
                "source_label": "Quelle A",
            }
        ]
    }
    corrected = {
        "memory_cards": [
            {
                **original["memory_cards"][0],
                "source_label": "Quelle B",
            }
        ]
    }

    first = memorial_memory.seed_memorial_source_memories(
        memory_runtime=runtime,
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        memorial_payload=original,
        reviewer="test",
    )
    second = memorial_memory.seed_memorial_source_memories(
        memory_runtime=runtime,
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        memorial_payload=corrected,
        reviewer="test",
    )

    assert first["created"] == 1
    assert second["created"] == 1
    assert first["public_approval_keys"] != second["public_approval_keys"]
    rows = memorial_memory.retrieve_memorial_memory_items(
        memory_runtime=runtime,
        principal_id="memorial:manfred",
        question="Gerechtigkeit Fairness",
        public_only=True,
        public_approval_keys=second["public_approval_keys"],
    )
    assert len(rows) == 1
    assert rows[0].fact_json["source_label"] == "Quelle B"


def test_seed_memorial_source_memories_rejects_conflicting_duplicate_key(
    monkeypatch,
) -> None:
    runtime = _FakeMemoryRuntime()
    manifest: dict[str, object] = {"processed_keys": []}
    monkeypatch.setattr(
        memorial_memory,
        "_load_seed_manifest",
        lambda _slug: dict(manifest),
    )

    def save_manifest(_slug: str, payload: dict[str, object]) -> None:
        manifest.clear()
        manifest.update(payload)

    monkeypatch.setattr(memorial_memory, "_save_seed_manifest", save_manifest)
    payload = {
        "suggested_prompts": ["Welche Erinnerung ist freigegeben?"],
    }
    first = memorial_memory.seed_memorial_source_memories(
        memory_runtime=runtime,
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        memorial_payload=payload,
        reviewer="test",
    )
    conflicting = dict(runtime.created_items[0])
    conflicting["summary"] = "CONFLICTING_DUPLICATE_SENTINEL"
    runtime.created_items.append(conflicting)

    with pytest.raises(
        ValueError,
        match="memorial_seed_reconciliation_mismatch",
    ):
        memorial_memory.seed_memorial_source_memories(
            memory_runtime=runtime,
            principal_id="memorial:manfred",
            memorial_slug="manfred",
            memorial_payload=payload,
            reviewer="test",
        )

    assert first["created"] == 1
    assert len(runtime.created_items) == 2


def test_seed_memorial_source_memories_uses_exact_store_when_manifest_is_unwritable(
    monkeypatch,
) -> None:
    runtime = _FakeMemoryRuntime()
    monkeypatch.setattr(
        memorial_memory,
        "_load_seed_manifest",
        lambda _slug: {"processed_keys": []},
    )

    def fail_save(_slug: str, _payload: dict[str, object]) -> None:
        raise PermissionError("read-only candidate mount")

    monkeypatch.setattr(memorial_memory, "_save_seed_manifest", fail_save)
    payload = {
        "memory_cards": [
            {
                "public": True,
                "title": "Gerechtigkeit",
                "body": "Tatsachen, Verantwortung und Fairness gehoeren zusammen.",
            }
        ]
    }

    first = memorial_memory.seed_memorial_source_memories(
        memory_runtime=runtime,
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        memorial_payload=payload,
        reviewer="test",
    )
    replayed = memorial_memory.seed_memorial_source_memories(
        memory_runtime=runtime,
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        memorial_payload=payload,
        reviewer="test",
    )
    rows = memorial_memory.retrieve_memorial_memory_items(
        memory_runtime=runtime,
        principal_id="memorial:manfred",
        question="Gerechtigkeit Verantwortung Fairness",
        public_only=True,
        public_approval_keys=replayed["public_approval_keys"],
    )

    assert first["created"] == 1
    assert first["manifest_persisted"] is False
    assert replayed["created"] == 0
    assert replayed["manifest_persisted"] is False
    assert replayed["public_approval_keys"] == first["public_approval_keys"]
    assert len(runtime.created_items) == 1
    assert len(rows) == 1


def _hold_memorial_storage_lock(archive_root: str, acquired, release) -> None:
    memorial_memory._ARCHIVE_ROOT = Path(archive_root)
    with memorial_memory._memorial_storage_lock("manfred"):
        acquired.set()
        if release is not None:
            release.wait(5)


def test_seed_memorial_source_memories_includes_public_source_notes(monkeypatch) -> None:
    runtime = _FakeMemoryRuntime()
    monkeypatch.setattr(memorial_memory, "_load_seed_manifest", lambda slug: {"processed_keys": []})
    monkeypatch.setattr(memorial_memory, "_save_seed_manifest", lambda slug, payload: None)

    result = memorial_memory.seed_memorial_source_memories(
        memory_runtime=runtime,
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        memorial_payload={},
        private_profile={
            "public_source_notes": [
                {
                    "public": True,
                    "label": "Jimdo",
                    "source_url": "https://manfred-hoza.jimdofree.com/",
                    "note": "Stellt ihn als autoritaetskritisch und opferschutzorientiert dar.",
                    "confidence": "hoch",
                }
            ]
        },
        reviewer="test",
    )

    assert result["created"] == 1
    assert len(runtime.created_items) == 1
    created = runtime.created_items[0]
    assert created["category"] == "memorial_public_source_note"
    assert created["fact_json"]["memory_kind"] == "public_source_note"
    assert created["fact_json"]["label"] == "Jimdo"
    assert created["fact_json"]["source_url"] == "https://manfred-hoza.jimdofree.com/"
    assert created["fact_json"]["confidence_label"] == "hoch"
    assert created["fact_json"]["memory_axis"] in {"general", "legal", "stylistic", "episodic"}
    assert created["fact_json"]["public_approved"] is True
    assert created["provenance_json"]["public_approved"] is True
    assert created["fact_json"]["public_approval_key"].startswith("public_v2:")
    assert created["provenance_json"]["public_approval_key"] == created["fact_json"]["public_approval_key"]
    assert result["public_approval_keys"] == [created["fact_json"]["public_approval_key"]]
    assert created["reviewer"] == "test"


def test_public_only_memorial_retrieval_excludes_private_implicit_and_mail_items(monkeypatch) -> None:
    runtime = _FakeMemoryRuntime()
    monkeypatch.setattr(memorial_memory, "_load_seed_manifest", lambda slug: {"processed_keys": []})
    monkeypatch.setattr(memorial_memory, "_save_seed_manifest", lambda slug, payload: None)

    seed_result = memorial_memory.seed_memorial_source_memories(
        memory_runtime=runtime,
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        memorial_payload={
            "memory_cards": [
                {"public": True, "title": "Public memory", "body": "Approved detail"},
                {"visibility": "private", "title": "PRIVATE_MEMORY_SENTINEL", "body": "Do not expose"},
                {"title": "IMPLICIT_MEMORY_SENTINEL", "body": "Do not infer approval"},
                {
                    "visibility": "public",
                    "public": False,
                    "title": "CONFLICTING_PUBLIC_SENTINEL",
                    "body": "Do not expose",
                },
                {
                    "visibility": "private",
                    "public": True,
                    "title": "CONFLICTING_PRIVATE_SENTINEL",
                    "body": "Do not expose",
                },
            ],
            "source_grounded_profile": [
                {"trait": "IMPLICIT_PROFILE_SENTINEL", "evidence": "Do not infer approval"},
            ],
            "external_sources": [
                {"visibility": "public", "label": "Public source", "url": "https://example.test"},
                {"visibility": "public", "label": "UNSAFE_SOURCE_SENTINEL", "url": "javascript:alert(1)"},
            ],
            "suggested_prompts": ["Public prompt", {"prompt": "MALFORMED_PROMPT_SENTINEL"}],
        },
        private_profile={
            "public_source_notes": [
                {"public": True, "label": "Reviewed note", "note": "Approved public source note"},
            ],
            "family_context_notes": [
                {"trait": "PRIVATE_FAMILY_SENTINEL", "evidence": "Do not expose"},
            ],
        },
        reviewer="test",
    )
    runtime.create_memory_item(
        principal_id="memorial:manfred",
        category="memorial_mail_message",
        summary="PRIVATE_MAIL_SENTINEL",
        fact_json={"memory_kind": "mail_message", "body": "Do not expose"},
        provenance_json={"source_type": "mail_import"},
        confidence=0.8,
        sensitivity="private",
        sharing_policy="private",
        reviewer="test",
    )

    rows = memorial_memory.retrieve_memorial_memory_items(
        memory_runtime=runtime,
        principal_id="memorial:manfred",
        question="",
        limit=20,
        public_only=True,
        public_approval_keys=seed_result["public_approval_keys"],
    )

    summaries = [str(row.summary) for row in rows]
    assert len(rows) == 4
    assert all(dict(row.fact_json or {}).get("public_approved") is True for row in rows)
    assert all(
        dict(row.fact_json or {}).get("public_approval_key") in set(seed_result["public_approval_keys"])
        for row in rows
    )
    assert any("Public memory" in summary for summary in summaries)
    assert any("Public source" in summary for summary in summaries)
    assert any("Public prompt" in summary for summary in summaries)
    assert any("Reviewed note" in summary for summary in summaries)
    assert not any(
        marker in summary
        for summary in summaries
        for marker in ("PRIVATE_", "IMPLICIT_", "MALFORMED_", "CONFLICTING_", "UNSAFE_")
    )


def test_public_only_memorial_retrieval_revokes_stale_and_legacy_approvals(monkeypatch) -> None:
    runtime = _FakeMemoryRuntime()
    manifest: dict[str, object] = {"processed_keys": []}

    def load_manifest(_slug: str) -> dict[str, object]:
        return dict(manifest)

    def save_manifest(_slug: str, payload: dict[str, object]) -> None:
        manifest.clear()
        manifest.update(payload)

    monkeypatch.setattr(memorial_memory, "_load_seed_manifest", load_manifest)
    monkeypatch.setattr(memorial_memory, "_save_seed_manifest", save_manifest)

    approved = memorial_memory.seed_memorial_source_memories(
        memory_runtime=runtime,
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        memorial_payload={
            "memory_cards": [
                {"visibility": "public", "title": "Revocable memory", "body": "Approved once"},
            ]
        },
        reviewer="test",
    )
    approved_keys = set(approved["public_approval_keys"])
    assert len(approved_keys) == 1
    assert len(
        memorial_memory.retrieve_memorial_memory_items(
            memory_runtime=runtime,
            principal_id="memorial:manfred",
            question="",
            public_only=True,
            public_approval_keys=approved_keys,
        )
    ) == 1

    runtime.create_memory_item(
        principal_id="memorial:manfred",
        category="memorial_memory_card",
        summary="LEGACY_APPROVAL_SENTINEL",
        fact_json={
            "public_approved": True,
            "public_approval_key": "public_v1:legacy",
        },
        provenance_json={"public_approved": True, "public_approval_key": "public_v1:legacy"},
        confidence=0.8,
        sensitivity="private",
        sharing_policy="private",
        reviewer="test",
    )

    revoked = memorial_memory.seed_memorial_source_memories(
        memory_runtime=runtime,
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        memorial_payload={
            "memory_cards": [
                {"visibility": "private", "title": "Revocable memory", "body": "Approved once"},
            ]
        },
        reviewer="test",
    )

    assert revoked["public_approval_keys"] == []
    assert memorial_memory.retrieve_memorial_memory_items(
        memory_runtime=runtime,
        principal_id="memorial:manfred",
        question="",
        public_only=True,
        public_approval_keys=revoked["public_approval_keys"],
    ) == []


def test_memorial_mail_import_dedupes_per_principal(monkeypatch, tmp_path) -> None:
    archive_root = tmp_path / "archive"
    monkeypatch.setattr(memorial_memory, "_ARCHIVE_ROOT", archive_root)

    eml_path = tmp_path / "manfred-message.eml"
    eml_path.write_bytes(
        b"Message-ID: <manfred-1@example.test>\n"
        b"From: Manfred <manfred@example.test>\n"
        b"To: Tibor <tibor@example.test>\n"
        b"Subject: Re: Wohnung und Verantwortung\n"
        b"Date: Mon, 1 Jun 2026 10:00:00 +0000\n"
        b"Content-Type: text/plain; charset=utf-8\n"
        b"\n"
        b"Wir muessen die Fakten sauber trennen und dann verantwortlich handeln.\n"
    )

    office_runtime = _FakeMemoryRuntime()
    office_import = memorial_memory.ingest_memorial_mail_archive(
        memory_runtime=office_runtime,
        principal_id="cf-email:principal@example.test",
        memorial_slug="manfred",
        source_path=str(eml_path),
        mailbox_format="eml",
    )
    assert office_import["imported"] == 1
    assert office_import["skipped"] == 0
    assert office_runtime.created_items[0]["principal_id"] == "cf-email:principal@example.test"

    memorial_runtime = _FakeMemoryRuntime()
    memorial_import = memorial_memory.ingest_memorial_mail_archive(
        memory_runtime=memorial_runtime,
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        source_path=str(eml_path),
        mailbox_format="eml",
    )
    assert memorial_import["imported"] == 1
    assert memorial_import["skipped"] == 0
    assert memorial_runtime.created_items[0]["principal_id"] == "memorial:manfred"

    duplicate_import = memorial_memory.ingest_memorial_mail_archive(
        memory_runtime=memorial_runtime,
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        source_path=str(eml_path),
        mailbox_format="eml",
    )
    assert duplicate_import["imported"] == 0
    assert duplicate_import["skipped"] == 1

    manifest = json.loads((archive_root / "manfred" / "ingest_manifest.json").read_text(encoding="utf-8"))
    assert sorted(manifest["processed_by_principal"]) == [
        "cf-email:principal@example.test",
        "memorial:manfred",
    ]
    assert len(manifest["processed_by_principal"]["cf-email:principal@example.test"]) == 1
    assert len(manifest["processed_by_principal"]["memorial:manfred"]) == 1


def test_memorial_mail_ingest_manifest_corruption_fails_closed(monkeypatch, tmp_path) -> None:
    archive_root = tmp_path / "archive"
    monkeypatch.setattr(memorial_memory, "_ARCHIVE_ROOT", archive_root)
    manifest_path = archive_root / "manfred" / "ingest_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("{broken", encoding="utf-8")
    eml_path = tmp_path / "message.eml"
    eml_path.write_bytes(
        b"Message-ID: <corrupt-manifest@example.test>\n"
        b"From: Manfred <manfred@example.test>\n"
        b"Subject: Test\n\n"
        b"Private body.\n"
    )
    runtime = _FakeMemoryRuntime()

    with pytest.raises(ValueError, match="memorial_mail_ingest_manifest_invalid"):
        memorial_memory.ingest_memorial_mail_archive(
            memory_runtime=runtime,
            principal_id="memorial:manfred",
            memorial_slug="manfred",
            source_path=str(eml_path),
            mailbox_format="eml",
        )

    assert runtime.created_items == []
    assert manifest_path.read_text(encoding="utf-8") == "{broken"


def test_memorial_raw_archive_rejects_existing_digest_mismatch(monkeypatch, tmp_path) -> None:
    archive_root = tmp_path / "archive"
    monkeypatch.setattr(memorial_memory, "_ARCHIVE_ROOT", archive_root)
    eml_path = tmp_path / "message.eml"
    eml_path.write_bytes(
        b"Message-ID: <stable-id@example.test>\n"
        b"From: Manfred <manfred@example.test>\n"
        b"Subject: Test\n\n"
        b"Original private body.\n"
    )
    original_runtime = _FakeMemoryRuntime()
    memorial_memory.ingest_memorial_mail_archive(
        memory_runtime=original_runtime,
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        source_path=str(eml_path),
        mailbox_format="eml",
    )
    eml_path.write_bytes(
        b"Message-ID: <stable-id@example.test>\n"
        b"From: Manfred <manfred@example.test>\n"
        b"Subject: Test\n\n"
        b"Tampered private body.\n"
    )

    for principal_id, runtime in (
        ("memorial:manfred", original_runtime),
        ("memorial:second-review-copy", _FakeMemoryRuntime()),
    ):
        with pytest.raises(ValueError, match="memorial_mail_archive_digest_mismatch"):
            memorial_memory.ingest_memorial_mail_archive(
                memory_runtime=runtime,
                principal_id=principal_id,
                memorial_slug="manfred",
                source_path=str(eml_path),
                mailbox_format="eml",
            )


def test_memorial_raw_archive_never_overwrites_racing_conflict(monkeypatch, tmp_path) -> None:
    archive_root = tmp_path / "archive"
    monkeypatch.setattr(memorial_memory, "_ARCHIVE_ROOT", archive_root)
    message_key = "a" * 40
    conflicting = b"conflicting private message"
    original_link = os.link
    injected = False

    def _inject_conflict(source, destination, **kwargs):
        nonlocal injected
        if not injected:
            injected = True
            destination_path = Path(destination)
            destination_path.write_bytes(conflicting)
            destination_path.chmod(0o600)
        return original_link(source, destination, **kwargs)

    monkeypatch.setattr(memorial_memory.os, "link", _inject_conflict)

    with pytest.raises(ValueError, match="memorial_mail_archive_digest_mismatch"):
        memorial_memory._archive_raw_message(
            slug="manfred",
            message_key=message_key,
            raw_bytes=b"incoming private message",
        )

    target = archive_root / "manfred" / "raw" / f"{message_key}.eml"
    assert target.read_bytes() == conflicting


def test_memorial_mail_import_reconciles_after_manifest_save_failure(monkeypatch, tmp_path) -> None:
    archive_root = tmp_path / "archive"
    monkeypatch.setattr(memorial_memory, "_ARCHIVE_ROOT", archive_root)
    eml_path = tmp_path / "reconcile.eml"
    eml_path.write_bytes(
        b"Message-ID: <reconcile-after-crash@example.test>\n"
        b"From: Manfred <manfred@example.test>\n"
        b"Subject: Reconcile\n\n"
        b"Private recovery body.\n"
    )
    runtime = _FakeMemoryRuntime()
    original_save = memorial_memory._save_manifest
    should_fail = True

    def _fail_once(slug, payload):
        nonlocal should_fail
        if should_fail:
            should_fail = False
            raise OSError("injected manifest fsync failure")
        return original_save(slug, payload)

    monkeypatch.setattr(memorial_memory, "_save_manifest", _fail_once)

    with pytest.raises(OSError, match="injected manifest"):
        memorial_memory.ingest_memorial_mail_archive(
            memory_runtime=runtime,
            principal_id="memorial:manfred",
            memorial_slug="manfred",
            source_path=str(eml_path),
            mailbox_format="eml",
        )
    assert len(runtime.created_items) == 1
    assert not (archive_root / "manfred" / "ingest_manifest.json").exists()

    retried = memorial_memory.ingest_memorial_mail_archive(
        memory_runtime=runtime,
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        source_path=str(eml_path),
        mailbox_format="eml",
    )

    assert retried["imported"] == 0
    assert retried["skipped"] == 1
    assert len(runtime.created_items) == 1
    manifest = json.loads(
        (archive_root / "manfred" / "ingest_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["schema"] == "ea.memorial_mail_ingest_manifest.v2"
    assert len(manifest["processed_by_principal"]["memorial:manfred"]) == 1


def test_memorial_mail_v1_manifest_migrates_only_for_exact_memorial_principal(monkeypatch, tmp_path) -> None:
    archive_root = tmp_path / "archive"
    monkeypatch.setattr(memorial_memory, "_ARCHIVE_ROOT", archive_root)
    eml_path = tmp_path / "legacy.eml"
    eml_path.write_bytes(
        b"Message-ID: <legacy-v1@example.test>\n"
        b"From: Manfred <manfred@example.test>\n"
        b"Subject: Legacy\n\n"
        b"Private legacy body.\n"
    )
    runtime = _FakeMemoryRuntime()
    initial = memorial_memory.ingest_memorial_mail_archive(
        memory_runtime=runtime,
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        source_path=str(eml_path),
        mailbox_format="eml",
    )
    message_key = str(initial["new_message_keys"][0])
    manifest_path = archive_root / "manfred" / "ingest_manifest.json"
    legacy_document = (json.dumps({"processed_keys": [message_key]}) + "\n").encode()
    manifest_path.write_bytes(legacy_document)
    manifest_path.chmod(0o600)

    with pytest.raises(ValueError, match="legacy_principal_ambiguous"):
        memorial_memory.ingest_memorial_mail_archive(
            memory_runtime=_FakeMemoryRuntime(),
            principal_id="cf-email:someone@example.test",
            memorial_slug="manfred",
            source_path=str(eml_path),
            mailbox_format="eml",
        )
    assert manifest_path.read_bytes() == legacy_document

    migrated = memorial_memory.ingest_memorial_mail_archive(
        memory_runtime=runtime,
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        source_path=str(eml_path),
        mailbox_format="eml",
    )
    assert migrated["imported"] == 0
    assert migrated["skipped"] == 1
    assert len(runtime.created_items) == 1
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "ea.memorial_mail_ingest_manifest.v2"
    assert payload["processed_keys"] == [message_key]
    assert payload["processed_by_principal"] == {"memorial:manfred": [message_key]}


def test_memorial_storage_lock_serializes_processes(monkeypatch, tmp_path) -> None:
    archive_root = tmp_path / "archive"
    monkeypatch.setattr(memorial_memory, "_ARCHIVE_ROOT", archive_root)
    context = multiprocessing.get_context("fork")
    first_acquired = context.Event()
    release_first = context.Event()
    second_acquired = context.Event()
    first = context.Process(
        target=_hold_memorial_storage_lock,
        args=(str(archive_root), first_acquired, release_first),
    )
    second = context.Process(
        target=_hold_memorial_storage_lock,
        args=(str(archive_root), second_acquired, None),
    )
    first.start()
    try:
        assert first_acquired.wait(5)
        second.start()
        assert not second_acquired.wait(0.25)
        release_first.set()
        assert second_acquired.wait(5)
    finally:
        release_first.set()
        first.join(5)
        if second.pid is not None:
            second.join(5)
        if first.is_alive():
            first.terminate()
        if second.pid is not None and second.is_alive():
            second.terminate()
    assert first.exitcode == 0
    assert second.exitcode == 0


def test_memorial_gmail_import_requires_explicit_private_confirmation(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(memorial_memory, "_ARCHIVE_ROOT", tmp_path / "archive")

    with pytest.raises(ValueError, match="explicit_private_mail_import_confirmation_required"):
        memorial_memory.ingest_memorial_gmail_messages(
            container=SimpleNamespace(),
            memory_runtime=_FakeMemoryRuntime(),
            principal_id="memorial:manfred",
            memorial_slug="manfred",
            account_email_filter="manfred.hoza@gmail.com",
            max_messages=1,
        )


def test_memorial_gmail_import_stages_maildir_and_reuses_archive_dedupe(monkeypatch, tmp_path) -> None:
    archive_root = tmp_path / "archive"
    monkeypatch.setattr(memorial_memory, "_ARCHIVE_ROOT", archive_root)

    from app.services import google_oauth

    raw_message = (
        b"Message-ID: <gmail-manfred-1@example.test>\n"
        b"From: Manfred <manfred.hoza@gmail.com>\n"
        b"To: Tibor <tibor@example.test>\n"
        b"Subject: Klarheit und Verantwortung\n"
        b"Date: Mon, 1 Jun 2026 10:00:00 +0000\n"
        b"Content-Type: text/plain; charset=utf-8\n"
        b"\n"
        b"Wir muessen die Fakten sauber trennen und dann verantwortlich handeln.\n"
    )
    binding = SimpleNamespace(binding_id="memorial:manfred:google_gmail")

    def _fake_export(**kwargs):
        assert kwargs["principal_id"] == "memorial:manfred"
        assert kwargs["account_email_filter"] == "manfred.hoza@gmail.com"
        assert kwargs["gmail_query"] == "in:sent"
        assert kwargs["max_messages"] == 5
        return (
            SimpleNamespace(
                binding=binding,
                account_email="manfred.hoza@gmail.com",
                message_id="gmail-message-1",
                raw_bytes=raw_message,
            ),
        )

    monkeypatch.setattr(google_oauth, "export_google_gmail_raw_messages", _fake_export)

    runtime = _FakeMemoryRuntime()
    result = memorial_memory.ingest_memorial_gmail_messages(
        container=SimpleNamespace(),
        memory_runtime=runtime,
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        account_email_filter="manfred.hoza@gmail.com",
        max_messages=5,
        confirm_private_mail_import=True,
    )

    assert result["exported"] == 1
    assert result["imported"] == 1
    assert result["skipped"] == 0
    assert result["account_email"] == "manfred.hoza@gmail.com"
    assert result["binding_id"] == "memorial:manfred:google_gmail"
    assert "gmail_live" in str(result["source_path"])
    assert runtime.created_items[0]["category"] == "memorial_mail_message"
    assert runtime.created_items[0]["fact_json"]["source_label"].startswith("Gmail live import:")
    assert runtime.created_items[0]["fact_json"]["memory_axis"] in {"stylistic", "legal"}

    duplicate = memorial_memory.ingest_memorial_gmail_messages(
        container=SimpleNamespace(),
        memory_runtime=runtime,
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        account_email_filter="manfred.hoza@gmail.com",
        max_messages=5,
        confirm_private_mail_import=True,
    )

    assert duplicate["exported"] == 1
    assert duplicate["imported"] == 0
    assert duplicate["skipped"] == 1


def test_memorial_mail_style_profile_is_private_idempotent_conversation_style(monkeypatch, tmp_path) -> None:
    archive_root = tmp_path / "archive"
    monkeypatch.setattr(memorial_memory, "_ARCHIVE_ROOT", archive_root)
    runtime = _FakeMemoryRuntime()
    for index, body in enumerate(
        [
            "Sehr geehrte Damen und Herren. Zunaechst muessen wir die Fakten sauber trennen. Rechtlich ist das nicht akzeptabel. Mit freundlichen Gruessen.",
            "Zur Information: Der Sachverhalt ist klarer, wenn man Punkt fuer Punkt vorgeht. Bitte zuerst die Unterlagen pruefen.",
            "Meines Erachtens geht es um Verantwortung, Pflicht und eine klare praktische Folgerung. Daher bitte keine vorschnelle Zusage.",
        ],
        start=1,
    ):
        runtime.create_memory_item(
            principal_id="memorial:manfred",
            category="memorial_mail_message",
            summary=f"Mail {index}",
            fact_json={
                "memorial_slug": "manfred",
                "memory_kind": "mail_message",
                "message_key": f"style-{index}",
                "subject": "Recht und Verantwortung",
                "body_text": body,
                "body_excerpt": body,
                "memory_axis": "stylistic",
            },
            provenance_json={"source_type": "test"},
            confidence=0.8,
            sensitivity="private",
            sharing_policy="private",
            reviewer="test",
        )

    result = memorial_memory.synthesize_memorial_mail_style_profile(
        memory_runtime=runtime,
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        reviewer="test-style",
    )

    assert result["created"] == 1
    style_item = runtime.created_items[-1]
    assert style_item["category"] == "memorial_mail_style_profile"
    assert style_item["sensitivity"] == "private"
    assert style_item["sharing_policy"] == "private"
    assert style_item["fact_json"]["memory_kind"] == "conversation_style"
    assert style_item["fact_json"]["style_key"] == "gmail_mail_style_profile"
    assert style_item["fact_json"]["message_count"] == 3
    assert "Gmail-Stilprofil aus 3 privaten" in style_item["fact_json"]["note"]
    assert "Fakten" in style_item["fact_json"]["note"]
    assert style_item["provenance_json"]["raw_mail_content_embedded"] is False

    duplicate = memorial_memory.synthesize_memorial_mail_style_profile(
        memory_runtime=runtime,
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        reviewer="test-style",
    )

    assert duplicate["created"] == 0
    assert duplicate["skipped"] == 1


def test_memorial_retrieval_includes_style_profile_for_normal_topic_questions() -> None:
    runtime = _FakeMemoryRuntime()
    runtime.create_memory_item(
        principal_id="memorial:manfred",
        category="memorial_mail_style_profile",
        summary="Gmail-Stilprofil aus privaten Mails",
        fact_json={
            "memorial_slug": "manfred",
            "memory_kind": "conversation_style",
            "style_key": "gmail_mail_style_profile",
            "note": "Gmail-Stilprofil: erst Fakten ordnen, dann Konsequenzen nennen, knapp entscheiden.",
            "memory_axis": "stylistic",
        },
        provenance_json={"source_type": "test"},
        confidence=0.8,
        sensitivity="private",
        sharing_policy="private",
        reviewer="test",
    )

    rows = memorial_memory.retrieve_memorial_memory_items(
        memory_runtime=runtime,
        principal_id="memorial:manfred",
        question="Wie stehst du zur Covid-Impfung?",
        limit=3,
    )
    lines = memorial_memory.format_memorial_memory_context(rows)

    assert rows
    assert dict(rows[0].fact_json)["memory_kind"] == "conversation_style"
    assert any(line.startswith("[Stil] Gmail-Stilprofil") for line in lines)


def _import_snapshot_test_mail(*, runtime: _FakeMemoryRuntime, source_path) -> None:
    source_path.write_bytes(
        b"Message-ID: <snapshot-manfred-1@example.test>\n"
        b"From: Manfred <manfred@example.test>\n"
        b"To: Tibor <tibor@example.test>\n"
        b"Subject: Snapshot und Verantwortung\n"
        b"Date: Mon, 1 Jun 2026 10:00:00 +0000\n"
        b"Content-Type: text/plain; charset=utf-8\n"
        b"\n"
        b"Private Erinnerung fuer den lokalen Wiederherstellungstest.\n"
    )
    result = memorial_memory.ingest_memorial_mail_archive(
        memory_runtime=runtime,
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        source_path=str(source_path),
        mailbox_format="eml",
        reviewer="snapshot-test",
    )
    assert result["imported"] == 1


def _snapshot_test_path(archive_root, filename: str):
    return archive_root / "manfred" / "snapshots" / filename


def _restore_test_snapshot(**kwargs):
    return memorial_memory.restore_memorial_local_snapshot(
        **kwargs,
        allow_ephemeral_test_backend=True,
    )


def test_memorial_local_snapshot_rejects_outside_path_and_silent_overwrite(monkeypatch, tmp_path) -> None:
    archive_root = tmp_path / "archive"
    monkeypatch.setattr(memorial_memory, "_ARCHIVE_ROOT", archive_root)
    runtime = _FakeMemoryRuntime()
    outside = tmp_path / "public" / "snapshot.json"

    with pytest.raises(ValueError, match="outside_root"):
        memorial_memory.export_memorial_local_snapshot(
            memory_runtime=runtime,
            principal_id="memorial:manfred",
            memorial_slug="manfred",
            destination_path=str(outside),
        )
    assert not outside.exists()

    destination = _snapshot_test_path(archive_root, "private.snapshot.json")
    memorial_memory.export_memorial_local_snapshot(
        memory_runtime=runtime,
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        destination_path=str(destination),
    )
    original = destination.read_bytes()
    with pytest.raises(ValueError, match="destination_exists"):
        memorial_memory.export_memorial_local_snapshot(
            memory_runtime=runtime,
            principal_id="memorial:manfred",
            memorial_slug="manfred",
            destination_path=str(destination),
        )
    assert destination.read_bytes() == original
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert stat.S_IMODE(archive_root.stat().st_mode) == 0o700
    assert stat.S_IMODE((archive_root / "manfred").stat().st_mode) == 0o700
    assert stat.S_IMODE(destination.parent.stat().st_mode) == 0o700


def test_memorial_local_snapshot_rejects_symlinked_storage_and_source(monkeypatch, tmp_path) -> None:
    archive_root = tmp_path / "archive"
    outside = tmp_path / "outside"
    archive_root.mkdir(mode=0o700)
    (archive_root / "manfred").mkdir(mode=0o700)
    outside.mkdir(mode=0o700)
    (archive_root / "manfred" / "snapshots").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(memorial_memory, "_ARCHIVE_ROOT", archive_root)

    with pytest.raises(ValueError, match="symlink_forbidden"):
        memorial_memory.export_memorial_local_snapshot(
            memory_runtime=_FakeMemoryRuntime(),
            principal_id="memorial:manfred",
            memorial_slug="manfred",
            destination_path=str(archive_root / "manfred" / "snapshots" / "leak.json"),
        )
    assert list(outside.iterdir()) == []

    (archive_root / "manfred" / "snapshots").unlink()
    destination = _snapshot_test_path(archive_root, "real.snapshot.json")
    memorial_memory.export_memorial_local_snapshot(
        memory_runtime=_FakeMemoryRuntime(),
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        destination_path=str(destination),
    )
    alias = destination.parent / "alias.snapshot.json"
    alias.symlink_to(destination.name)
    with pytest.raises(ValueError, match="memorial_local_snapshot_file_invalid"):
        memorial_memory.verify_memorial_local_snapshot(
            snapshot_path=str(alias),
            expected_principal_id="memorial:manfred",
            expected_memorial_slug="manfred",
        )


def test_memorial_local_snapshot_restore_refuses_ephemeral_backend(monkeypatch, tmp_path) -> None:
    archive_root = tmp_path / "archive"
    monkeypatch.setattr(memorial_memory, "_ARCHIVE_ROOT", archive_root)
    snapshot_path = _snapshot_test_path(archive_root, "ephemeral.snapshot.json")
    runtime = _FakeMemoryRuntime()
    memorial_memory.export_memorial_local_snapshot(
        memory_runtime=runtime,
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        destination_path=str(snapshot_path),
    )

    with pytest.raises(ValueError, match="durable_storage_required"):
        memorial_memory.restore_memorial_local_snapshot(
            memory_runtime=runtime,
            principal_id="memorial:manfred",
            memorial_slug="manfred",
            snapshot_path=str(snapshot_path),
            dry_run=True,
        )


def test_memorial_mail_manifest_rejects_inconsistent_v2_union(monkeypatch, tmp_path) -> None:
    archive_root = tmp_path / "archive"
    monkeypatch.setattr(memorial_memory, "_ARCHIVE_ROOT", archive_root)
    memorial_root = memorial_memory._ensure_archive_root("manfred")
    manifest_path = memorial_root / "ingest_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "ea.memorial_mail_ingest_manifest.v2",
                "processed_keys": ["a" * 40],
                "processed_by_principal": {},
            }
        ),
        encoding="utf-8",
    )
    manifest_path.chmod(0o600)

    with pytest.raises(ValueError, match="memorial_mail_ingest_manifest_invalid"):
        memorial_memory._load_manifest(
            "manfred",
            legacy_principal_id="memorial:manfred",
        )


def test_memorial_local_snapshot_is_deterministic_private_and_verifiable(monkeypatch, tmp_path) -> None:
    archive_root = tmp_path / "archive"
    monkeypatch.setattr(memorial_memory, "_ARCHIVE_ROOT", archive_root)
    runtime = _FakeMemoryRuntime()
    _import_snapshot_test_mail(
        runtime=runtime,
        source_path=tmp_path / "mail.eml",
    )
    runtime.create_memory_item(
        principal_id="memorial:manfred",
        category="memorial_memory_card",
        summary="Private local copy of reviewed material",
        fact_json={
            "memorial_slug": "manfred",
            "memory_kind": "memorial_memory_card",
            "public_approved": True,
            "public_approval_key": "public_v2:must-not-survive",
            "nested": {"visibility": "public", "detail": "memory content survives"},
        },
        provenance_json={"public_approved": True, "publication_id": "registry-owned"},
        confidence=0.8,
        sensitivity="private",
        sharing_policy="private",
        reviewer="snapshot-test",
    )

    first_path = _snapshot_test_path(archive_root, "first.snapshot.json")
    second_path = _snapshot_test_path(archive_root, "second.snapshot.json")
    first = memorial_memory.export_memorial_local_snapshot(
        memory_runtime=runtime,
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        destination_path=str(first_path),
    )
    second = memorial_memory.export_memorial_local_snapshot(
        memory_runtime=runtime,
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        destination_path=str(second_path),
    )

    assert first["payload_sha256"] == second["payload_sha256"]
    assert first_path.read_bytes() == second_path.read_bytes()
    assert stat.S_IMODE(first_path.stat().st_mode) == 0o600
    assert first["encrypted"] is False
    assert first["authenticated"] is False
    assert first["integrity_model"] == "sha256_accidental_corruption_only"
    assert first["canonical_publication_state_included"] is False
    bundle = json.loads(first_path.read_text(encoding="utf-8"))
    serialized = json.dumps(bundle, sort_keys=True)
    assert "public_v2:must-not-survive" not in serialized
    assert "registry-owned" not in serialized
    assert '"visibility"' not in serialized
    assert bundle["payload"]["authority"]["restores_publication_state"] is False
    assert all(
        item["record"]["sharing_policy"] == "private"
        and item["record"]["sensitivity"] == "private"
        for item in bundle["payload"]["memory_items"]
    )

    verified = memorial_memory.verify_memorial_local_snapshot(
        snapshot_path=str(first_path),
        expected_principal_id="memorial:manfred",
        expected_memorial_slug="manfred",
    )
    assert verified["valid"] is True
    assert verified["memory_item_count"] == 2
    assert verified["raw_mail_count"] == 1
    assert verified["payload_sha256"] == first["payload_sha256"]
    assert verified["authenticated"] is False
    assert verified["integrity_model"] == "sha256_accidental_corruption_only"


def test_memorial_local_snapshot_migrates_legacy_private_permissions_and_mail_digest(monkeypatch, tmp_path) -> None:
    archive_root = tmp_path / "archive"
    monkeypatch.setattr(memorial_memory, "_ARCHIVE_ROOT", archive_root)
    runtime = _FakeMemoryRuntime()
    _import_snapshot_test_mail(
        runtime=runtime,
        source_path=tmp_path / "legacy-mail.eml",
    )
    mail_fact = runtime.created_items[0]["fact_json"]
    mail_provenance = runtime.created_items[0]["provenance_json"]
    assert isinstance(mail_fact, dict) and isinstance(mail_provenance, dict)
    mail_fact.pop("raw_sha256", None)
    mail_provenance.pop("raw_sha256", None)
    message_key = str(mail_fact["message_key"])
    raw_path = archive_root / "manfred" / "raw" / f"{message_key}.eml"
    manifest_path = archive_root / "manfred" / "ingest_manifest.json"
    raw_path.chmod(0o644)
    raw_path.parent.chmod(0o755)
    manifest_path.chmod(0o644)

    snapshot_path = _snapshot_test_path(archive_root, "legacy-normalized.snapshot.json")
    memorial_memory.export_memorial_local_snapshot(
        memory_runtime=runtime,
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        destination_path=str(snapshot_path),
    )

    bundle = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot_fact = bundle["payload"]["memory_items"][0]["record"]["fact_json"]
    assert len(snapshot_fact["raw_sha256"]) == 64
    assert stat.S_IMODE(raw_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(raw_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(manifest_path.stat().st_mode) == 0o600


def test_memorial_local_snapshot_preserves_missing_legacy_verification_as_untrusted_null(monkeypatch, tmp_path) -> None:
    archive_root = tmp_path / "archive"
    monkeypatch.setattr(memorial_memory, "_ARCHIVE_ROOT", archive_root)
    runtime = _FakeMemoryRuntime()
    runtime.created_items.append(
        {
            "principal_id": "memorial:manfred",
            "category": "memorial_memory_card",
            "summary": "Legacy memory without a verification timestamp",
            "fact_json": {"memorial_slug": "manfred", "memory_kind": "memorial_memory_card"},
            "provenance_json": {"source_type": "legacy"},
            "confidence": 0.7,
            "sensitivity": "private",
            "sharing_policy": "private",
            "reviewer": "legacy-import",
            "last_verified_at": None,
        }
    )
    snapshot_path = _snapshot_test_path(archive_root, "legacy-null-verification.snapshot.json")

    memorial_memory.export_memorial_local_snapshot(
        memory_runtime=runtime,
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        destination_path=str(snapshot_path),
    )
    verified = memorial_memory.verify_memorial_local_snapshot(
        snapshot_path=str(snapshot_path),
        expected_principal_id="memorial:manfred",
        expected_memorial_slug="manfred",
    )
    bundle = json.loads(snapshot_path.read_text(encoding="utf-8"))

    assert verified["memory_item_count"] == 1
    assert bundle["payload"]["memory_items"][0]["record"]["last_verified_at"] is None


def test_memorial_local_snapshot_verification_rejects_tamper_and_scope_mismatch(monkeypatch, tmp_path) -> None:
    archive_root = tmp_path / "archive"
    monkeypatch.setattr(memorial_memory, "_ARCHIVE_ROOT", archive_root)
    runtime = _FakeMemoryRuntime()
    runtime.create_memory_item(
        principal_id="memorial:manfred",
        category="memorial_memory_card",
        summary="Original private memory",
        fact_json={"memorial_slug": "manfred", "memory_kind": "memorial_memory_card"},
        provenance_json={"source_type": "test"},
        sensitivity="private",
        sharing_policy="private",
    )
    snapshot_path = _snapshot_test_path(archive_root, "snapshot.json")
    memorial_memory.export_memorial_local_snapshot(
        memory_runtime=runtime,
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        destination_path=str(snapshot_path),
    )

    with pytest.raises(ValueError, match="memorial_local_snapshot_scope_invalid"):
        memorial_memory.verify_memorial_local_snapshot(
            snapshot_path=str(snapshot_path),
            expected_principal_id="memorial:someone-else",
            expected_memorial_slug="manfred",
        )

    bundle = json.loads(snapshot_path.read_text(encoding="utf-8"))
    bundle["payload"]["memory_items"][0]["record"]["summary"] = "Tampered memory"
    snapshot_path.write_text(json.dumps(bundle), encoding="utf-8")
    with pytest.raises(ValueError, match="memorial_local_snapshot_payload_digest_mismatch"):
        memorial_memory.verify_memorial_local_snapshot(
            snapshot_path=str(snapshot_path),
            expected_principal_id="memorial:manfred",
            expected_memorial_slug="manfred",
        )


def test_memorial_local_snapshot_dry_run_and_merge_restore_are_idempotent(monkeypatch, tmp_path) -> None:
    source_archive = tmp_path / "source-archive"
    monkeypatch.setattr(memorial_memory, "_ARCHIVE_ROOT", source_archive)
    source_runtime = _FakeMemoryRuntime()
    _import_snapshot_test_mail(
        runtime=source_runtime,
        source_path=tmp_path / "restore-mail.eml",
    )
    source_runtime.create_memory_item(
        principal_id="memorial:manfred",
        category="memorial_memory_card",
        summary="Reviewed memory restored only as private",
        fact_json={
            "memorial_slug": "manfred",
            "memory_kind": "memorial_memory_card",
            "public_approved": True,
            "public_approval_key": "public_v2:not-restored",
        },
        provenance_json={"public_approved": True},
        confidence=0.9,
        sensitivity="private",
        sharing_policy="private",
        reviewer="source-reviewer",
    )
    snapshot_path = _snapshot_test_path(source_archive, "restore.snapshot.json")
    exported = memorial_memory.export_memorial_local_snapshot(
        memory_runtime=source_runtime,
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        destination_path=str(snapshot_path),
    )

    target_archive = tmp_path / "target-archive"
    target_snapshot = _snapshot_test_path(target_archive, "restore.snapshot.json")
    target_snapshot.parent.mkdir(mode=0o700, parents=True)
    target_snapshot.write_bytes(snapshot_path.read_bytes())
    target_snapshot.chmod(0o600)
    monkeypatch.setattr(memorial_memory, "_ARCHIVE_ROOT", target_archive)
    target_runtime = _FakeMemoryRuntime()
    planned = _restore_test_snapshot(
        memory_runtime=target_runtime,
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        snapshot_path=str(target_snapshot),
        dry_run=True,
    )
    assert planned["mode"] == "merge"
    assert planned["memory_items_to_create"] == exported["memory_item_count"] == 2
    assert planned["raw_mail_to_write"] == 1
    assert planned["memory_items_created"] == 0
    assert planned["raw_mail_written"] == 0
    assert target_runtime.created_items == []
    assert target_snapshot.exists()
    assert not (target_archive / "manfred" / "raw").exists()
    assert not (target_archive / "manfred" / "ingest_manifest.json").exists()

    with pytest.raises(ValueError, match="memorial_local_snapshot_dry_run_invalid"):
        _restore_test_snapshot(
            memory_runtime=target_runtime,
            principal_id="memorial:manfred",
            memorial_slug="manfred",
            snapshot_path=str(target_snapshot),
            dry_run=0,
        )
    with pytest.raises(ValueError, match="memorial_local_snapshot_apply_confirmation_required"):
        _restore_test_snapshot(
            memory_runtime=target_runtime,
            principal_id="memorial:manfred",
            memorial_slug="manfred",
            snapshot_path=str(target_snapshot),
            dry_run=False,
        )
    with pytest.raises(ValueError, match="memorial_local_snapshot_apply_confirmation_mismatch"):
        _restore_test_snapshot(
            memory_runtime=target_runtime,
            principal_id="memorial:manfred",
            memorial_slug="manfred",
            snapshot_path=str(target_snapshot),
            dry_run=False,
            confirmed_payload_sha256="0" * 64,
        )
    assert target_runtime.created_items == []
    assert not (target_archive / "manfred" / "raw").exists()
    assert not (target_archive / "manfred" / "ingest_manifest.json").exists()

    restored = _restore_test_snapshot(
        memory_runtime=target_runtime,
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        snapshot_path=str(target_snapshot),
        dry_run=False,
        confirmed_payload_sha256=str(exported["payload_sha256"]),
        recovery_reviewer="test-recovery",
    )
    assert restored["memory_items_created"] == 2
    assert restored["raw_mail_written"] == 1
    assert restored["canonical_publication_state_restored"] is False
    assert restored["authenticated"] is False
    assert restored["integrity_model"] == "sha256_accidental_corruption_only"
    assert restored["target_storage_durable"] is False
    assert restored["ephemeral_test_override"] is True
    assert restored["apply_confirmation_matched"] is True
    assert all(item["sharing_policy"] == "private" for item in target_runtime.created_items)
    assert all(item["sensitivity"] == "private" for item in target_runtime.created_items)
    assert all(item["reviewer"] == "test-recovery" for item in target_runtime.created_items)
    assert all(item["last_verified_at"] != "2026-06-19T00:00:00+00:00" for item in target_runtime.created_items)
    restored_serialized = json.dumps(target_runtime.created_items, sort_keys=True)
    assert "public_v2:not-restored" not in restored_serialized
    assert '"public_approved"' not in restored_serialized
    assert "local_recovery_receipt" in restored_serialized
    assert "untrusted_snapshot_metadata" in restored_serialized
    assert "source-reviewer" in restored_serialized
    manifest = json.loads(
        (target_archive / "manfred" / "ingest_manifest.json").read_text(encoding="utf-8")
    )
    assert len(manifest["processed_by_principal"]["memorial:manfred"]) == 1

    repeated = _restore_test_snapshot(
        memory_runtime=target_runtime,
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        snapshot_path=str(target_snapshot),
        dry_run=False,
        confirmed_payload_sha256=str(exported["payload_sha256"]),
    )
    assert repeated["memory_items_to_create"] == 0
    assert repeated["raw_mail_to_write"] == 0
    assert repeated["memory_items_created"] == 0
    assert repeated["raw_mail_written"] == 0
    assert len(target_runtime.created_items) == 2


def test_memorial_local_snapshot_exports_beyond_legacy_list_cap(monkeypatch, tmp_path) -> None:
    archive_root = tmp_path / "archive"
    monkeypatch.setattr(memorial_memory, "_ARCHIVE_ROOT", archive_root)
    runtime = _FakeMemoryRuntime()
    for index in range(501):
        runtime.create_memory_item(
            principal_id="memorial:manfred",
            category="memorial_memory_card",
            summary=f"Memory {index}",
            fact_json={"memorial_slug": "manfred", "memory_kind": "memorial_memory_card"},
            provenance_json={"source_type": "test"},
            sensitivity="private",
            sharing_policy="private",
        )
    destination = _snapshot_test_path(archive_root, "beyond-legacy-cap.snapshot.json")

    exported = memorial_memory.export_memorial_local_snapshot(
        memory_runtime=runtime,
        principal_id="memorial:manfred",
        memorial_slug="manfred",
        destination_path=str(destination),
    )
    verified = memorial_memory.verify_memorial_local_snapshot(
        snapshot_path=str(destination),
        expected_principal_id="memorial:manfred",
        expected_memorial_slug="manfred",
    )

    assert exported["memory_item_count"] == 501
    assert verified["memory_item_count"] == 501


def test_memory_item_repository_snapshot_export_is_exact_scoped_and_bounded() -> None:
    from app.repositories.memory_items import (
        InMemoryMemoryItemRepository,
        MemoryItemSnapshotLimitExceeded,
    )

    repository = InMemoryMemoryItemRepository()
    assert repository.snapshot_storage_durable is False
    for index in range(501):
        repository.create_item(
            principal_id="memorial:manfred",
            category="memorial_memory_card",
            summary=f"Memory {index}",
            sharing_policy="private",
        )
    repository.create_item(
        principal_id="memorial:someone-else",
        category="memorial_memory_card",
        summary="Other principal",
        sharing_policy="private",
    )

    rows = repository.export_principal_snapshot(
        principal_id="memorial:manfred",
        max_items=501,
    )

    assert len(rows) == 501
    assert all(row.principal_id == "memorial:manfred" for row in rows)
    assert [(row.created_at, row.item_id) for row in rows] == sorted(
        (row.created_at, row.item_id) for row in rows
    )
    with pytest.raises(MemoryItemSnapshotLimitExceeded):
        repository.export_principal_snapshot(
            principal_id="memorial:manfred",
            max_items=500,
        )
    with pytest.raises(ValueError):
        repository.export_principal_snapshot(principal_id="", max_items=501)


def test_memorial_local_snapshot_fails_closed_at_configured_memory_bound(monkeypatch, tmp_path) -> None:
    archive_root = tmp_path / "archive"
    monkeypatch.setattr(memorial_memory, "_ARCHIVE_ROOT", archive_root)
    monkeypatch.setattr(memorial_memory, "_LOCAL_SNAPSHOT_MAX_MEMORY_ITEMS", 3)
    runtime = _FakeMemoryRuntime()
    for index in range(4):
        runtime.create_memory_item(
            principal_id="memorial:manfred",
            category="memorial_memory_card",
            summary=f"Memory {index}",
            fact_json={"memorial_slug": "manfred", "memory_kind": "memorial_memory_card"},
            provenance_json={"source_type": "test"},
            sensitivity="private",
            sharing_policy="private",
        )
    destination = _snapshot_test_path(archive_root, "must-not-exist.snapshot.json")

    with pytest.raises(ValueError, match="memorial_local_snapshot_memory_enumeration_incomplete"):
        memorial_memory.export_memorial_local_snapshot(
            memory_runtime=runtime,
            principal_id="memorial:manfred",
            memorial_slug="manfred",
            destination_path=str(destination),
        )

    assert not destination.exists()


def test_memorial_local_snapshot_rejects_raw_mail_memory_digest_mismatch(monkeypatch, tmp_path) -> None:
    archive_root = tmp_path / "archive"
    monkeypatch.setattr(memorial_memory, "_ARCHIVE_ROOT", archive_root)
    runtime = _FakeMemoryRuntime()
    _import_snapshot_test_mail(
        runtime=runtime,
        source_path=tmp_path / "digest-mismatch.eml",
    )
    runtime.created_items[0]["fact_json"]["raw_sha256"] = "0" * 64
    destination = _snapshot_test_path(archive_root, "must-not-exist.snapshot.json")

    with pytest.raises(ValueError, match="memorial_local_snapshot_raw_mail_memory_mismatch"):
        memorial_memory.export_memorial_local_snapshot(
            memory_runtime=runtime,
            principal_id="memorial:manfred",
            memorial_slug="manfred",
            destination_path=str(destination),
        )

    assert not destination.exists()


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("category", "c" * 201),
        ("summary", "s" * 16001),
        ("reviewer", "r" * 501),
        ("last_verified_at", "not-an-iso-timestamp"),
    ],
)
def test_memorial_local_snapshot_export_rejects_records_its_verifier_would_reject(
    monkeypatch,
    tmp_path,
    field,
    invalid_value,
) -> None:
    archive_root = tmp_path / "archive"
    monkeypatch.setattr(memorial_memory, "_ARCHIVE_ROOT", archive_root)
    runtime = _FakeMemoryRuntime()
    item = {
        "principal_id": "memorial:manfred",
        "category": "memorial_memory_card",
        "summary": "Private memory",
        "fact_json": {"memorial_slug": "manfred", "memory_kind": "memorial_memory_card"},
        "provenance_json": {"source_type": "test"},
        "sensitivity": "private",
        "sharing_policy": "private",
        "reviewer": "test",
        "last_verified_at": "2026-07-11T10:00:00+00:00",
    }
    item[field] = invalid_value
    runtime.create_memory_item(**item)
    destination = _snapshot_test_path(archive_root, f"invalid-{field}.snapshot.json")

    with pytest.raises(ValueError, match="memorial_local_snapshot_memory_invalid"):
        memorial_memory.export_memorial_local_snapshot(
            memory_runtime=runtime,
            principal_id="memorial:manfred",
            memorial_slug="manfred",
            destination_path=str(destination),
        )

    assert not destination.exists()
