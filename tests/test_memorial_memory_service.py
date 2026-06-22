from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from app.services import memorial_memory


class _FakeMemoryRuntime:
    def __init__(self) -> None:
        self.created_items: list[dict[str, object]] = []

    def create_memory_item(self, **kwargs):
        self.created_items.append(dict(kwargs))
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
                    updated_at=f"2026-06-19T00:00:{index:02d}Z",
                )
            )
        return rows[:limit]


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
    assert created["reviewer"] == "test"


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
