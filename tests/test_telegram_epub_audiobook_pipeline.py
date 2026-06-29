from __future__ import annotations

import errno
import json
import math
import os
from pathlib import Path
import shutil
import struct
import wave
import zipfile
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import pytest
from fastapi import HTTPException


def _write_minimal_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as book:
        book.writestr("mimetype", "application/epub+zip")
        book.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        book.writestr(
            "OEBPS/content.opf",
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Test Book</dc:title>
    <dc:creator>A. Writer</dc:creator>
    <dc:language>en-US</dc:language>
  </metadata>
  <manifest>
    <item id="chap1" href="chapters/chapter-1.xhtml" media-type="application/xhtml+xml"/>
    <item id="chap2" href="chapters/chapter-2.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="chap1"/>
    <itemref idref="chap2"/>
  </spine>
</package>
""",
        )
        book.writestr(
            "OEBPS/chapters/chapter-1.xhtml",
            "<html><head><title>Opening</title></head><body><h1>Opening</h1><p>Hello audiobook.</p></body></html>",
        )
        book.writestr(
            "OEBPS/chapters/chapter-2.xhtml",
            "<html><body><h1>Second Chapter</h1><p>More narrated words.</p></body></html>",
        )


def _write_fake_ebook_convert(tmp_path: Path) -> Path:
    template_epub = tmp_path / "converted-template.epub"
    _write_minimal_epub(template_epub)
    converter = tmp_path / "fake-ebook-convert"
    converter.write_text(
        "#!/usr/bin/env python3\n"
        "import shutil\n"
        "import sys\n"
        f"template = {json.dumps(str(template_epub))}\n"
        "if len(sys.argv) < 3:\n"
        "    raise SystemExit(2)\n"
        "shutil.copyfile(template, sys.argv[2])\n",
        encoding="utf-8",
    )
    converter.chmod(0o755)
    return converter


def _write_epub_with_cover(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as book:
        book.writestr("mimetype", "application/epub+zip")
        book.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        book.writestr(
            "OEBPS/content.opf",
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Covered Book</dc:title>
    <dc:creator>A. Writer</dc:creator>
    <dc:language>en-US</dc:language>
    <meta name="cover" content="cover-image"/>
  </metadata>
  <manifest>
    <item id="cover-image" href="images/cover.jpg" media-type="image/jpeg" properties="cover-image"/>
    <item id="chap1" href="chapters/chapter-1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="chap1"/>
  </spine>
</package>
""",
        )
        book.writestr("OEBPS/images/cover.jpg", b"\xff\xd8\xff\xe0cover\xff\xd9")
        book.writestr(
            "OEBPS/chapters/chapter-1.xhtml",
            "<html><head><title>Opening</title></head><body><h1>Opening</h1><p>Hello covered audiobook.</p></body></html>",
        )


def _write_epub_with_publisher_tail(path: Path) -> None:
    def _body(title: str, text: str) -> str:
        return f"<html><head><title>{title}</title></head><body><h1>{title}</h1><p>{text}</p></body></html>"

    real_text = (
        "Dies ist ein echtes Kapitel mit genug Inhalt fuer ein Hoerbuch. "
        "Es erklaert den Gedanken ruhig und ausfuehrlich, damit der Abschnitt "
        "nicht als Navigationsseite oder Verlagshinweis behandelt wird. "
    ) * 5
    with zipfile.ZipFile(path, "w") as book:
        book.writestr("mimetype", "application/epub+zip")
        book.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        manifest_rows = []
        spine_rows = []
        chapters = {
            "cover": ("Cover", "Cover"),
            "legal": ("Test Book", "Der Inhalt dieses E-Books ist urheberrechtlich geschützt und enthält technische Sicherungsmaßnahmen."),
            "toc": ("Test Book", "Inhalt Einleitung Kapitel eins Kapitel zwei Schluss Anhang"),
            "intro": ("Einleitung", real_text),
            "chapter": ("Kapitel eins", real_text),
            "part": ("Test Book", "ANHANG"),
            "thanks": ("Danksagung", real_text),
            "promo": ("Weitere interessante Titel", "Weitere interessante Titel Haben Sie Lust gleich weiterzulesen?"),
            "sample": ("Other Book", real_text),
            "newsletter": ("Zum Newsletter anmelden", "Bestellen Sie unseren exklusiven Newsletter."),
        }
        for key in chapters:
            manifest_rows.append(f'<item id="{key}" href="chapters/{key}.xhtml" media-type="application/xhtml+xml"/>')
            spine_rows.append(f'<itemref idref="{key}"/>')
        book.writestr(
            "OEBPS/content.opf",
            f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Test Book</dc:title>
    <dc:creator>A. Writer</dc:creator>
    <dc:language>de</dc:language>
  </metadata>
  <manifest>{''.join(manifest_rows)}</manifest>
  <spine>{''.join(spine_rows)}</spine>
</package>
""",
        )
        for key, (title, text) in chapters.items():
            book.writestr(f"OEBPS/chapters/{key}.xhtml", _body(title, text))


def _write_plain_zip(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("notes.txt", "This is a ZIP, not an EPUB.")


def _write_unsafe_rootfile_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as book:
        book.writestr("mimetype", "application/epub+zip")
        book.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="../evil.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        book.writestr("../evil.opf", "<package></package>")


def _write_tone_wav(path: Path, *, seconds: float = 0.12, sample_rate: int = 16000) -> None:
    samples = [
        0.12 * math.sin(2 * math.pi * 220 * i / sample_rate)
        for i in range(max(int(sample_rate * seconds), 1))
    ]
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"".join(struct.pack("<h", int(value * 32767)) for value in samples))


def _write_tone_with_silent_tail_wav(
    path: Path,
    *,
    tone_seconds: float = 0.8,
    silence_seconds: float = 1.8,
    sample_rate: int = 16000,
) -> None:
    samples = [
        0.12 * math.sin(2 * math.pi * 220 * i / sample_rate)
        for i in range(max(int(sample_rate * tone_seconds), 1))
    ]
    samples.extend([0.0 for _ in range(max(int(sample_rate * silence_seconds), 1))])
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"".join(struct.pack("<h", int(value * 32767)) for value in samples))


def test_epub_detection_uses_filename_and_mime_type() -> None:
    from app.services.audiobook_epub_pipeline import is_audiobook_source_document, is_epub_document

    assert is_audiobook_source_document(filename="Book.epub", mime_type="application/epub+zip")
    assert is_audiobook_source_document(filename="Book.epub", mime_type="")
    assert not is_audiobook_source_document(filename="Book.pdf", mime_type="application/pdf")
    assert not is_audiobook_source_document(filename="Book.epub", mime_type="application/pdf")
    assert is_epub_document(filename="Book.epub", mime_type="application/epub+zip")


def test_extract_epub_chapters(tmp_path: Path) -> None:
    from app.services.audiobook_epub_pipeline import extract_epub_chapters

    epub = tmp_path / "book.epub"
    _write_minimal_epub(epub)

    metadata, chapters = extract_epub_chapters(epub_path=epub, chapter_dir=tmp_path / "chapters", source_filename="book.epub")

    assert metadata.title == "Test Book"
    assert metadata.author == "A. Writer"
    assert len(chapters) == 2
    first_text = (tmp_path / "chapters" / chapters[0].text_path).read_text(encoding="utf-8")
    assert "Hello audiobook" in first_text
    assert chapters[0].audio_filename.startswith("001 - ")


def test_extract_epub_chapters_filters_publisher_furniture_by_default(tmp_path: Path) -> None:
    from app.services.audiobook_epub_pipeline import extract_epub_chapters

    epub = tmp_path / "book.epub"
    _write_epub_with_publisher_tail(epub)

    metadata, chapters = extract_epub_chapters(epub_path=epub, chapter_dir=tmp_path / "chapters", source_filename="book.epub")

    assert metadata.language == "de"
    assert [chapter.title for chapter in chapters] == ["Einleitung", "Kapitel eins", "Danksagung"]
    rendered = "\n".join((tmp_path / "chapters" / chapter.text_path).read_text(encoding="utf-8") for chapter in chapters)
    assert "urheberrechtlich geschützt" not in rendered
    assert "Weitere interessante Titel" not in rendered
    assert "Other Book" not in rendered
    assert chapters[0].audio_filename.startswith("001 - ")


def test_validate_epub_archive_rejects_plain_zip(tmp_path: Path) -> None:
    from app.services.audiobook_epub_pipeline import validate_epub_archive

    archive = tmp_path / "not-a-book.epub"
    _write_plain_zip(archive)

    with pytest.raises(RuntimeError, match="epub_mimetype_missing"):
        validate_epub_archive(archive)


def test_extract_epub_chapters_rejects_unsafe_rootfile_path(tmp_path: Path) -> None:
    from app.services.audiobook_epub_pipeline import extract_epub_chapters

    epub = tmp_path / "unsafe.epub"
    _write_unsafe_rootfile_epub(epub)

    with pytest.raises(RuntimeError, match="epub_archive_unsafe_member_path|epub_rootfile_unsafe_or_missing"):
        extract_epub_chapters(epub_path=epub, chapter_dir=tmp_path / "chapters", source_filename="unsafe.epub")


def test_process_telegram_epub_job_rejects_declared_oversize(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.audiobook_epub_pipeline import process_telegram_epub_audiobook_job

    called = {"downloaded": False}

    def fake_download(*, source_url: str, target_path: Path, max_bytes: int | None = None) -> dict[str, object]:
        called["downloaded"] = True
        raise AssertionError("download must not run when declared size exceeds limit")

    monkeypatch.setattr("app.services.audiobook_epub_pipeline.download_telegram_epub", fake_download)
    monkeypatch.setenv("EA_AUDIOBOOK_TELEGRAM_MAX_BYTES", "50000")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", "/tmp")  # overridden by env only in this negative-path test

    with pytest.raises(RuntimeError, match="telegram_epub_too_large_declared"):
        process_telegram_epub_audiobook_job(
            download_url="https://api.telegram.org/file/botTOKEN/books/book.epub",
            filename="book.epub",
            file_size=60000,
            principal_id="principal-1",
        )

    assert called["downloaded"] is False


def test_create_job_stores_manifest_without_telegram_url(monkeypatch, tmp_path: Path) -> None:
    from app.services.audiobook_epub_pipeline import create_job_from_epub, telegram_epub_reply_text

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "0")
    monkeypatch.setenv("EA_M4B_TOOL_BIN", "definitely-missing-m4b-tool")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": "voice-clear", "label": "Clear narrator", "language": "en-US", "tags": ["narration", "clear", "nonfiction"], "default": True},
                {"voice_id": "voice-story", "label": "Story narrator", "language": "en-US", "tags": ["narration", "expressive", "fiction", "dialogue"]},
            ]
        ),
    )

    epub = tmp_path / "book.epub"
    _write_minimal_epub(epub)
    source_url = "https://api.telegram.org/file/botSECRET/books/book.epub"

    job = create_job_from_epub(
        epub_path=epub,
        original_filename="book.epub",
        principal_id="principal-1",
        chat_id="42",
        message_id="99",
        caption="make audiobook",
        source_url=source_url,
    )

    assert job["status"] == "blocked_external_tts"
    assert job["provider"]["raw_book_text_leaves_ea"] is False
    rendered = json.dumps(job, sort_keys=True)
    assert "botSECRET" not in rendered
    assert "voice-clear" not in rendered
    assert "voice-story" not in rendered
    assert source_url not in rendered
    assert "source_url_sha256" in rendered
    assert job["provider"]["voice_selection"]["selected"]["label"] == "Clear narrator"
    assert "voice_id_sha256" in job["provider"]["voice_selection"]["selected"]
    reply = telegram_epub_reply_text(job)
    assert "did not send the book text to audio generation" in reply
    assert "Unmixr" not in reply
    assert "ETA" in reply


def test_audiobook_job_receipt_is_sanitized(monkeypatch, tmp_path: Path) -> None:
    from app.services.audiobook_epub_pipeline import build_audiobook_job_receipt, create_job_from_epub

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "0")
    monkeypatch.setenv("UNMIXR_VOICE_ID", "raw-secret-voice-id")

    epub = tmp_path / "book.epub"
    _write_minimal_epub(epub)
    source_url = "https://api.telegram.org/file/botSECRET/books/book.epub"
    job = create_job_from_epub(
        epub_path=epub,
        original_filename="book.epub",
        principal_id="principal-1",
        chat_id="42",
        message_id="99",
        caption="please make this audiobook",
        source_url=source_url,
    )

    receipt = build_audiobook_job_receipt(job_dir=Path(job["storage"]["job_dir"]))
    receipt_path = Path(job["storage"]["job_dir"]) / "job_receipt.json"
    stored_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    rendered = json.dumps(receipt, sort_keys=True)

    assert receipt["contract_name"] == "ea.telegram_epub_audiobook_job_receipt.v1"
    assert receipt_path.is_file()
    assert stored_receipt["contract_name"] == receipt["contract_name"]
    assert stored_receipt["status"] == job["status"]
    assert receipt["privacy"]["raw_book_text_in_receipt"] is False
    assert receipt["privacy"]["telegram_chat_id_exposed"] is False
    assert receipt["privacy"]["telegram_message_id_exposed"] is False
    assert receipt["privacy"]["telegram_file_url_exposed"] is False
    assert receipt["privacy"]["provider_voice_id_exposed"] is False
    assert receipt["source"]["priority_for_resume"] is False
    assert receipt["scheduler_resume"]["priority_label"] == "bulk_or_standard"
    assert receipt["scheduler_resume"]["priority_score"] == 10
    assert receipt["telegram"]["chat_bound"] is True
    assert receipt["telegram"]["message_bound"] is True
    assert receipt["telegram"]["caption_present"] is True
    assert receipt["source"]["source_url_sha256"]
    assert source_url not in rendered
    assert "botSECRET" not in rendered
    assert "raw-secret-voice-id" not in rendered
    assert "Hello audiobook" not in rendered
    assert str(tmp_path) not in rendered
    assert '"chat_id"' not in rendered
    assert '"message_id"' not in rendered


def test_existing_chapter_wavs_merge_with_ffmpeg_fallback_and_import(monkeypatch, tmp_path: Path) -> None:
    from app.services.audiobook_epub_pipeline import create_job_from_epub, continue_job, resolve_player_scoped_audiobook_file
    from app.api.app import create_app
    from fastapi.testclient import TestClient

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "0")
    monkeypatch.setenv("EA_M4B_TOOL_BIN", "definitely-missing-m4b-tool")
    monkeypatch.setenv("EA_AUDIOBOOK_FFMPEG_M4B_FALLBACK", "1")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_AUTO_IMPORT", "1")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_IMPORT_ROOT", str(tmp_path / "audiobookshelf"))
    monkeypatch.setenv("EA_AUDIOBOOK_ACCESS_SIGNING_SECRET", "test-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_PLAYER_ACCESS_BASE_URL", "https://app.example.com")
    monkeypatch.setenv("EA_AUDIOBOOK_PUBLICATION_STT_GATE_REQUIRED", "0")

    epub = tmp_path / "book.epub"
    _write_minimal_epub(epub)
    job = create_job_from_epub(
        epub_path=epub,
        original_filename="book.epub",
        principal_id="principal-1",
    )
    job_dir = Path(job["storage"]["job_dir"])
    audio_dir = job_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    for index, chapter in enumerate(job["chapters"], start=1):
        _write_tone_wav(
            audio_dir / chapter["audio_filename"],
            sample_rate=192000 if index == 1 else 44100,
        )

    completed = continue_job(job_dir)

    assert completed["status"] == "audiobookshelf_imported"
    assert completed["merge_result"]["provider"] == "ffmpeg"
    assert completed["merge_result"]["normalized_audio"] is True
    assert completed["merge_result"]["normalized_sample_rate"] == 44100
    assert completed["merge_result"]["normalized_audio_count"] == len(job["chapters"])
    concat_text = (job_dir / "m4b" / "concat.txt").read_text(encoding="utf-8")
    assert "normalized-audio" in concat_text
    assert completed["merge_result"]["cover_embedded"] is True
    assert completed["merge_result"]["cover_filename"] == "generated-audiobook-cover.jpg"
    assert completed["audio_publication_gate"]["status"] == "pass"
    assert completed["audio_publication_gate"]["cover_streams"] >= 1
    imported_path = Path(completed["audiobookshelf_import"]["target_path"])
    assert imported_path.is_file()
    assert imported_path.suffix == ".m4b"
    scoped = completed["audiobookshelf_import"]["player_scoped_reference"]
    assert scoped["status"] == "signed_reference_ready"
    assert scoped["vendor_token_exposed"] is False
    assert scoped["raw_library_path_exposed"] is False
    token = str(scoped["relative_url"]).rsplit("/", 1)[-1]
    resolved_path, resolved_metadata = resolve_player_scoped_audiobook_file(token)
    assert resolved_path == imported_path.resolve()
    assert resolved_metadata["library_scope"] == "single_player_runner_audiobook"

    from app.services.audiobook_epub_pipeline import telegram_epub_reply_text

    reply = telegram_epub_reply_text(completed)
    assert "Player-scoped playback link" in reply
    assert "https://app.example.com/internal/audiobooks/player/" in reply
    assert str(imported_path) not in reply
    assert "Audiobookshelf import storage:" not in reply

    monkeypatch.setenv("EA_STORAGE_BACKEND", "memory")
    monkeypatch.delenv("EA_LEDGER_BACKEND", raising=False)
    monkeypatch.setenv("EA_API_TOKEN", "")
    client = TestClient(create_app())

    metadata_response = client.get(scoped["relative_url"])
    assert metadata_response.status_code == 200
    assert metadata_response.headers["cache-control"] == "no-store"
    metadata_payload = metadata_response.json()
    assert metadata_payload["status"] == "ready"
    assert metadata_payload["library_scope"] == "single_player_runner_audiobook"
    assert metadata_payload["vendor_token_exposed"] is False
    assert metadata_payload["raw_library_path_exposed"] is False
    assert metadata_payload["download_url"] == f"{scoped['relative_url']}?download=1"
    assert str(tmp_path) not in json.dumps(metadata_payload)

    download_response = client.get(metadata_payload["download_url"])
    assert download_response.status_code == 200
    assert download_response.headers["cache-control"] == "no-store"
    assert download_response.headers["content-type"].startswith("audio/mp4")
    assert download_response.content

    missing_response = client.get("/internal/audiobooks/player/not-a-valid-token")
    assert missing_response.status_code == 404
    assert "player_audiobook_not_found" in missing_response.text


def test_single_chapter_ffmpeg_m4b_merge_uses_direct_audio_input(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    monkeypatch.setenv("EA_AUDIOBOOK_GENERATE_FALLBACK_COVER", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_M4B_SAMPLE_RATE", "44100")
    monkeypatch.setenv("EA_AUDIOBOOK_M4B_CHANNELS", "1")

    job_dir = tmp_path / "job"
    audio_dir = job_dir / "audio"
    output_file = job_dir / "output" / "book.m4b"
    audio_dir.mkdir(parents=True)
    output_file.parent.mkdir(parents=True)
    _write_tone_wav(audio_dir / "001 - Opening.wav", sample_rate=192000)

    metadata = pipeline.EpubMetadata(
        title="Single Chapter",
        author="A. Writer",
        language="en-US",
        source_filename="single.epub",
        source_sha256="source-sha",
    )
    chapter = pipeline.EpubChapter(
        index=1,
        title="Opening",
        source_href="story:1",
        text_path="001 - Opening.txt",
        audio_filename="001 - Opening.wav",
        char_count=12,
        sha256="chapter-sha",
    )

    result = pipeline._merge_m4b_with_ffmpeg(
        job_dir=job_dir,
        metadata=metadata,
        chapters=(chapter,),
        output_file=output_file,
    )

    assert result["status"] == "m4b_ready"
    assert result["provider"] == "ffmpeg"
    assert result["normalized_audio_count"] == 1
    assert result["command"][:3] == [pipeline._ffmpeg_bin(), "-y", "-i"]
    assert "-f" not in result["command"]
    assert "concat" not in result["command"]
    assert "-map_chapters" in result["command"]
    assert output_file.is_file()


def test_player_scoped_audiobook_reference_fails_closed_on_publication_gate(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services.audiobook_epub_pipeline import (
        create_player_scoped_audiobook_reference,
        resolve_player_scoped_audiobook_file,
    )

    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-gated"
    job_dir.mkdir(parents=True)
    import_root = tmp_path / "audiobookshelf"
    target_path = import_root / "A. Writer" / "Test Book" / "Test Book.m4b"
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(b"fake m4b bytes")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_IMPORT_ROOT", str(import_root))
    monkeypatch.setenv("EA_AUDIOBOOK_ACCESS_SIGNING_SECRET", "test-secret")

    job = {
        "job_id": "job-gated",
        "status": "audiobookshelf_imported",
        "principal_id": "principal-1",
        "metadata": {"title": "Test Book", "author": "A. Writer", "language": "en-US"},
        "storage": {"job_dir": str(job_dir)},
        "audiobookshelf_import": {"status": "imported", "target_path": str(target_path)},
        "audio_publication_gate": {"status": "pass", "issues": []},
    }
    (job_dir / "job.json").write_text(json.dumps(job, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    reference = create_player_scoped_audiobook_reference(job=job)
    assert reference["status"] == "signed_reference_ready"
    token = str(reference["relative_url"]).rsplit("/", 1)[-1]

    job["audio_publication_gate"] = {"status": "fail", "issues": ["audio_too_quiet"]}
    (job_dir / "job.json").write_text(json.dumps(job, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    blocked = create_player_scoped_audiobook_reference(job=job)
    assert blocked["status"] == "blocked"
    assert blocked["reason"] == "audio_publication_gate_fail"
    with pytest.raises(RuntimeError, match="audiobook_access_publication_gate_failed:audio_publication_gate_fail"):
        resolve_player_scoped_audiobook_file(token)


def test_player_scoped_audiobook_reference_blocks_revoked_wrong_voice(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services.audiobook_epub_pipeline import create_player_scoped_audiobook_reference

    import_root = tmp_path / "audiobookshelf"
    target_path = import_root / "A. Writer" / "Test Book" / "Test Book.m4b"
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(b"fake m4b bytes")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_IMPORT_ROOT", str(import_root))
    monkeypatch.setenv("EA_AUDIOBOOK_ACCESS_SIGNING_SECRET", "test-secret")

    job = {
        "job_id": "job-wrong-voice",
        "status": "audiobookshelf_imported",
        "metadata": {"title": "Test Book", "author": "A. Writer", "language": "en-US"},
        "storage": {"job_dir": str(tmp_path / "jobs" / "job-wrong-voice")},
        "provider": {"voice_selection": {"local_fallback_render": {"status": "revoked_wrong_voice"}}},
        "audiobookshelf_import": {
            "status": "imported",
            "target_path": str(target_path),
            "public_share": {"status": "revoked_wrong_voice"},
        },
        "audio_publication_gate": {"status": "pass", "issues": []},
    }

    blocked = create_player_scoped_audiobook_reference(job=job)

    assert blocked["status"] == "blocked"
    assert blocked["reason"] == "public_share_revoked_wrong_voice"


def test_audio_publication_gate_blocks_quiet_tail(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    import_root = tmp_path / "audiobookshelf"
    target_path = import_root / "A. Writer" / "Test Book" / "Test Book.m4b"
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(b"fake m4b bytes")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_IMPORT_ROOT", str(import_root))
    monkeypatch.setenv("EA_AUDIOBOOK_PUBLICATION_MIN_MEAN_VOLUME_DB", "-30")
    monkeypatch.setenv("EA_AUDIOBOOK_PUBLICATION_TAIL_MIN_MEAN_VOLUME_DB", "-35")
    monkeypatch.setattr(
        pipeline,
        "_probe_audio_publication_file",
        lambda path: {
            "format": {"duration": "120.0", "size": str(target_path.stat().st_size)},
            "streams": [
                {"codec_type": "audio", "codec_name": "aac"},
                {"codec_type": "video", "codec_name": "mjpeg"},
            ],
            "chapters": [{"id": 0}],
        },
    )

    def fake_volume(path: Path, *, position: str = "head"):
        if position == "tail":
            return {
                "status": "checked",
                "position": "tail",
                "window_seconds": 30,
                "mean_volume_db": "-48.0",
                "max_volume_db": "-42.0",
            }
        return {
            "status": "checked",
            "position": "head",
            "window_seconds": 30,
            "mean_volume_db": "-20.0",
            "max_volume_db": "-8.0",
        }

    monkeypatch.setattr(pipeline, "_audio_publication_volume", fake_volume)

    gate = pipeline._build_audiobook_publication_gate(
        job={"status": "audiobookshelf_imported", "metadata": {"title": "Test Book"}},
        target_path=target_path,
    )

    assert gate["status"] == "fail"
    assert "audio_tail_too_quiet" in gate["issues"]
    assert gate["volume"]["head"]["position"] == "head"
    assert gate["volume"]["tail"]["position"] == "tail"
    assert gate["raw_paths_exposed"] is False


def test_audio_publication_gate_blocks_stt_text_that_is_not_from_book(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    import_root = tmp_path / "audiobookshelf"
    target_path = import_root / "A. Writer" / "Test Book" / "Test Book.m4b"
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(b"fake m4b bytes")
    job_dir = tmp_path / "jobs" / "job-stt-mismatch"
    chapter_dir = job_dir / "chapters"
    chapter_dir.mkdir(parents=True)
    source_text = "This is the exact book sentence that should be heard in the audiobook sample window."
    (chapter_dir / "001 - Chapter.txt").write_text(source_text, encoding="utf-8")

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_IMPORT_ROOT", str(import_root))
    monkeypatch.setenv("EA_AUDIOBOOK_PUBLICATION_STT_GATE_REQUIRED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_PUBLICATION_STT_SAMPLE_COUNT", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_PUBLICATION_STT_MIN_TRANSCRIPT_TOKENS", "6")
    monkeypatch.setattr(
        pipeline,
        "_probe_audio_publication_file",
        lambda path: {
            "format": {"duration": "120.0", "size": str(target_path.stat().st_size)},
            "streams": [
                {"codec_type": "audio", "codec_name": "aac"},
                {"codec_type": "video", "codec_name": "mjpeg"},
            ],
            "chapters": [{"id": 0}],
        },
    )
    monkeypatch.setattr(
        pipeline,
        "_audio_publication_volume",
        lambda path, *, position="head": {
            "status": "checked",
            "position": position,
            "window_seconds": 30,
            "mean_volume_db": "-20.0",
            "max_volume_db": "-8.0",
        },
    )

    def fake_extract(**kwargs):
        Path(kwargs["output_path"]).write_bytes(b"fake wav")
        return {"status": "ready", "sample_file_size": 8}

    monkeypatch.setattr(pipeline, "_extract_audiobook_publication_stt_sample", fake_extract)
    monkeypatch.setattr(
        pipeline,
        "_transcribe_audiobook_publication_stt_sample",
        lambda **kwargs: {
            "status": "transcribed",
            "transcript_text": "unrelated weather market sports traffic nonsense words today",
            "transcriber": "test",
        },
    )

    gate = pipeline._build_audiobook_publication_gate(
        job={
            "status": "audiobookshelf_imported",
            "metadata": {"title": "Test Book", "language": "en-US"},
            "storage": {"job_dir": str(job_dir)},
            "chapters": [{"text_path": "001 - Chapter.txt"}],
        },
        target_path=target_path,
    )

    assert gate["status"] == "fail"
    assert "stt_transcript_not_book_text" in gate["issues"]
    assert gate["stt"]["status"] == "fail"
    assert gate["stt"]["raw_text_exposed"] is False
    assert gate["stt"]["samples"][0]["raw_text_exposed"] is False
    assert "unrelated weather" not in json.dumps(gate)
    assert source_text not in json.dumps(gate)


def test_audio_publication_gate_passes_stt_text_from_book(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    import_root = tmp_path / "audiobookshelf"
    target_path = import_root / "A. Writer" / "Test Book" / "Test Book.m4b"
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(b"fake m4b bytes")
    job_dir = tmp_path / "jobs" / "job-stt-pass"
    chapter_dir = job_dir / "chapters"
    chapter_dir.mkdir(parents=True)
    source_text = "This is the exact book sentence that should be heard in the audiobook sample window."
    (chapter_dir / "001 - Chapter.txt").write_text(source_text, encoding="utf-8")

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_IMPORT_ROOT", str(import_root))
    monkeypatch.setenv("EA_AUDIOBOOK_PUBLICATION_STT_GATE_REQUIRED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_PUBLICATION_STT_SAMPLE_COUNT", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_PUBLICATION_STT_MIN_TRANSCRIPT_TOKENS", "6")
    monkeypatch.setattr(
        pipeline,
        "_probe_audio_publication_file",
        lambda path: {
            "format": {"duration": "120.0", "size": str(target_path.stat().st_size)},
            "streams": [
                {"codec_type": "audio", "codec_name": "aac"},
                {"codec_type": "video", "codec_name": "mjpeg"},
            ],
            "chapters": [{"id": 0}],
        },
    )
    monkeypatch.setattr(
        pipeline,
        "_audio_publication_volume",
        lambda path, *, position="head": {
            "status": "checked",
            "position": position,
            "window_seconds": 30,
            "mean_volume_db": "-20.0",
            "max_volume_db": "-8.0",
        },
    )

    def fake_extract(**kwargs):
        Path(kwargs["output_path"]).write_bytes(b"fake wav")
        return {"status": "ready", "sample_file_size": 8}

    monkeypatch.setattr(pipeline, "_extract_audiobook_publication_stt_sample", fake_extract)
    monkeypatch.setattr(
        pipeline,
        "_transcribe_audiobook_publication_stt_sample",
        lambda **kwargs: {
            "status": "transcribed",
            "transcript_text": "This is the exact book sentence that should be heard",
            "transcriber": "test",
        },
    )

    gate = pipeline._build_audiobook_publication_gate(
        job={
            "status": "audiobookshelf_imported",
            "metadata": {"title": "Test Book", "language": "en-US"},
            "storage": {"job_dir": str(job_dir)},
            "chapters": [{"text_path": "001 - Chapter.txt"}],
        },
        target_path=target_path,
    )

    assert gate["status"] == "pass"
    assert gate["stt"]["status"] == "pass"
    assert gate["stt"]["passed_samples"] == 1
    assert gate["stt"]["raw_text_exposed"] is False


def test_audio_publication_gate_requires_stt_by_default(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    import_root = tmp_path / "audiobookshelf"
    target_path = import_root / "A. Writer" / "Default STT Book" / "Default STT Book.m4b"
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(b"fake m4b bytes")
    job_dir = tmp_path / "jobs" / "job-default-stt"
    chapter_dir = job_dir / "chapters"
    chapter_dir.mkdir(parents=True)
    source_text = "Default publication must prove the audiobook audio still says words from the book."
    (chapter_dir / "001 - Chapter.txt").write_text(source_text, encoding="utf-8")

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_IMPORT_ROOT", str(import_root))
    monkeypatch.delenv("EA_AUDIOBOOK_PUBLICATION_STT_GATE_REQUIRED", raising=False)
    monkeypatch.delenv("EA_AUDIOBOOK_PUBLICATION_STT_GATE_ENABLED", raising=False)
    monkeypatch.setenv("EA_AUDIOBOOK_PUBLICATION_STT_SAMPLE_COUNT", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_PUBLICATION_STT_MIN_TRANSCRIPT_TOKENS", "6")
    monkeypatch.setattr(
        pipeline,
        "_probe_audio_publication_file",
        lambda path: {
            "format": {"duration": "120.0", "size": str(target_path.stat().st_size)},
            "streams": [
                {"codec_type": "audio", "codec_name": "aac"},
                {"codec_type": "video", "codec_name": "mjpeg"},
            ],
            "chapters": [{"id": 0}],
        },
    )
    monkeypatch.setattr(
        pipeline,
        "_audio_publication_volume",
        lambda path, *, position="head": {
            "status": "checked",
            "position": position,
            "window_seconds": 30,
            "mean_volume_db": "-20.0",
            "max_volume_db": "-8.0",
        },
    )

    def fake_extract(**kwargs):
        Path(kwargs["output_path"]).write_bytes(b"fake wav")
        return {"status": "ready", "sample_file_size": 8, "seek_mode": "output_side_audio_stream"}

    monkeypatch.setattr(pipeline, "_extract_audiobook_publication_stt_sample", fake_extract)
    monkeypatch.setattr(
        pipeline,
        "_transcribe_audiobook_publication_stt_sample",
        lambda **kwargs: {
            "status": "transcribed",
            "transcript_text": "publication must prove the audiobook audio still says words from the book",
            "transcriber": "test",
        },
    )

    gate = pipeline._build_audiobook_publication_gate(
        job={
            "status": "audiobookshelf_imported",
            "metadata": {"title": "Default STT Book", "language": "en-US"},
            "storage": {"job_dir": str(job_dir)},
            "chapters": [{"text_path": "001 - Chapter.txt"}],
        },
        target_path=target_path,
    )

    assert gate["status"] == "pass"
    assert gate["stt"]["enabled"] is True
    assert gate["stt"]["required"] is True
    assert gate["stt"]["status"] == "pass"
    assert gate["stt"]["passed_samples"] == 1
    assert gate["stt"]["raw_text_exposed"] is False
    assert source_text not in json.dumps(gate)


def test_stt_sample_extract_uses_output_side_audio_seek(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    target_path = tmp_path / "book.m4b"
    output_path = tmp_path / "sample.wav"
    target_path.write_bytes(b"fake m4b")
    seen: dict[str, object] = {}

    def fake_run(command, **kwargs):
        seen["command"] = list(command)
        output_path.write_bytes(b"fake wav")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(pipeline.subprocess, "run", fake_run)

    result = pipeline._extract_audiobook_publication_stt_sample(
        target_path=target_path,
        output_path=output_path,
        offset_seconds=8292.077,
        sample_seconds=30,
    )

    command = list(seen["command"])
    assert result["status"] == "ready"
    assert result["seek_mode"] == "output_side_audio_stream"
    assert command.index("-i") < command.index("-ss")
    assert command[command.index("-map") + 1] == "0:a:0"


def test_audio_publication_gate_resamples_too_short_stt_window(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    import_root = tmp_path / "audiobookshelf"
    target_path = import_root / "A. Writer" / "Test Book" / "Test Book.m4b"
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(b"fake m4b bytes")
    job_dir = tmp_path / "jobs" / "job-stt-resample"
    chapter_dir = job_dir / "chapters"
    chapter_dir.mkdir(parents=True)
    source_text = "This is the exact book sentence that should be heard in the audiobook sample window."
    (chapter_dir / "001 - Chapter.txt").write_text(source_text, encoding="utf-8")

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_IMPORT_ROOT", str(import_root))
    monkeypatch.setenv("EA_AUDIOBOOK_PUBLICATION_STT_GATE_REQUIRED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_PUBLICATION_STT_SAMPLE_COUNT", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_PUBLICATION_STT_MIN_TRANSCRIPT_TOKENS", "6")
    monkeypatch.setenv("EA_AUDIOBOOK_PUBLICATION_STT_RESAMPLE_SHIFTS_SECONDS", "15")
    monkeypatch.setattr(
        pipeline,
        "_probe_audio_publication_file",
        lambda path: {
            "format": {"duration": "120.0", "size": str(target_path.stat().st_size)},
            "streams": [
                {"codec_type": "audio", "codec_name": "aac"},
                {"codec_type": "video", "codec_name": "mjpeg"},
            ],
            "chapters": [{"id": 0}],
        },
    )
    monkeypatch.setattr(
        pipeline,
        "_audio_publication_volume",
        lambda path, *, position="head": {
            "status": "checked",
            "position": position,
            "window_seconds": 30,
            "mean_volume_db": "-20.0",
            "max_volume_db": "-8.0",
        },
    )
    seen_offsets: list[float] = []

    def fake_extract(**kwargs):
        seen_offsets.append(float(kwargs["offset_seconds"]))
        Path(kwargs["output_path"]).write_bytes(b"fake wav")
        return {"status": "ready", "sample_file_size": 8, "seek_mode": "output_side_audio_stream"}

    transcripts = iter(
        [
            "pause",
            "This is the exact book sentence that should be heard",
        ]
    )
    monkeypatch.setattr(pipeline, "_extract_audiobook_publication_stt_sample", fake_extract)
    monkeypatch.setattr(
        pipeline,
        "_transcribe_audiobook_publication_stt_sample",
        lambda **kwargs: {
            "status": "transcribed",
            "transcript_text": next(transcripts),
            "transcriber": "test",
        },
    )

    gate = pipeline._build_audiobook_publication_gate(
        job={
            "status": "audiobookshelf_imported",
            "metadata": {"title": "Test Book", "language": "en-US"},
            "storage": {"job_dir": str(job_dir)},
            "chapters": [{"text_path": "001 - Chapter.txt"}],
        },
        target_path=target_path,
    )

    assert gate["status"] == "pass"
    assert seen_offsets == [0.0, 15.0]
    assert gate["stt"]["samples"][0]["attempt_count"] == 2
    assert gate["stt"]["samples"][0]["extractor_seek_mode"] == "output_side_audio_stream"
    assert gate["stt"]["samples"][0]["recovered_from_issue"] == "stt_transcript_too_short"
    assert gate["stt"]["samples"][0]["raw_text_exposed"] is False
    assert "This is the exact book" not in json.dumps(gate)


def test_audio_publication_gate_tolerates_one_short_book_text_sample(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    import_root = tmp_path / "audiobookshelf"
    target_path = import_root / "A. Writer" / "Test Book" / "Test Book.m4b"
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(b"fake m4b bytes")
    job_dir = tmp_path / "jobs" / "job-stt-short-book-text"
    chapter_dir = job_dir / "chapters"
    chapter_dir.mkdir(parents=True)
    source_text = "This is the exact book sentence that should be heard in the audiobook sample window."
    (chapter_dir / "001 - Chapter.txt").write_text(source_text, encoding="utf-8")

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_IMPORT_ROOT", str(import_root))
    monkeypatch.setenv("EA_AUDIOBOOK_PUBLICATION_STT_GATE_REQUIRED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_PUBLICATION_STT_SAMPLE_COUNT", "3")
    monkeypatch.setenv("EA_AUDIOBOOK_PUBLICATION_STT_MIN_TRANSCRIPT_TOKENS", "6")
    monkeypatch.setenv("EA_AUDIOBOOK_PUBLICATION_STT_RESAMPLE_SHIFTS_SECONDS", "0")
    monkeypatch.setattr(
        pipeline,
        "_probe_audio_publication_file",
        lambda path: {
            "format": {"duration": "120.0", "size": str(target_path.stat().st_size)},
            "streams": [
                {"codec_type": "audio", "codec_name": "aac"},
                {"codec_type": "video", "codec_name": "mjpeg"},
            ],
            "chapters": [{"id": 0}],
        },
    )
    monkeypatch.setattr(
        pipeline,
        "_audio_publication_volume",
        lambda path, *, position="head": {
            "status": "checked",
            "position": position,
            "window_seconds": 30,
            "mean_volume_db": "-20.0",
            "max_volume_db": "-8.0",
        },
    )

    def fake_extract(**kwargs):
        Path(kwargs["output_path"]).write_bytes(b"fake wav")
        return {"status": "ready", "sample_file_size": 8, "seek_mode": "output_side_audio_stream"}

    transcripts = iter(
        [
            "This is the exact book sentence that should be heard",
            "This",
            "This is the exact book sentence that should be heard",
        ]
    )
    monkeypatch.setattr(pipeline, "_extract_audiobook_publication_stt_sample", fake_extract)
    monkeypatch.setattr(
        pipeline,
        "_transcribe_audiobook_publication_stt_sample",
        lambda **kwargs: {
            "status": "transcribed",
            "transcript_text": next(transcripts),
            "transcriber": "test",
        },
    )

    gate = pipeline._build_audiobook_publication_gate(
        job={
            "status": "audiobookshelf_imported",
            "metadata": {"title": "Test Book", "language": "en-US"},
            "storage": {"job_dir": str(job_dir)},
            "chapters": [{"text_path": "001 - Chapter.txt"}],
        },
        target_path=target_path,
    )

    assert gate["status"] == "pass"
    assert gate["stt"]["status"] == "pass"
    assert gate["stt"]["warnings"] == ["stt_transcript_too_short_tolerated_book_text"]
    assert gate["stt"]["passed_samples"] == 3
    assert gate["stt"]["samples"][1]["warning"] == "stt_transcript_too_short_tolerated_book_text"
    assert gate["stt"]["samples"][1]["issue"] == ""


def test_completed_import_creates_audiobookshelf_public_share_link(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import create_job_from_epub, continue_job, telegram_epub_reply_text

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "0")
    monkeypatch.setenv("EA_M4B_TOOL_BIN", "definitely-missing-m4b-tool")
    monkeypatch.setenv("EA_AUDIOBOOK_FFMPEG_M4B_FALLBACK", "1")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_AUTO_IMPORT", "1")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_IMPORT_ROOT", str(tmp_path / "audiobookshelf"))
    monkeypatch.setenv("EA_AUDIOBOOK_ACCESS_SIGNING_SECRET", "test-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_PLAYER_ACCESS_BASE_URL", "https://app.example.com")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_PUBLIC_SHARE_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_API_BASE_URL", "https://abs.internal")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_PUBLIC_BASE_URL", "https://abs.example.com")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_API_TOKEN", "abs-secret-token")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_LIBRARY_ID", "library-1")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_SCAN_POLL_SECONDS", "0")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_PUBLIC_SHARE_EXPIRES_DAYS", "30")
    monkeypatch.setenv("EA_AUDIOBOOK_PUBLICATION_STT_GATE_REQUIRED", "0")
    seen: list[dict[str, object]] = []

    class FakeResponse:
        def __init__(self, *, status: int = 200, payload: dict[str, object] | None = None, text: str = ""):
            self.status = status
            self._body = text.encode("utf-8") if text else json.dumps(payload or {}).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return self._body

    def fake_urlopen(request, timeout=None):
        method = str(getattr(request, "method", "") or request.get_method())
        url = str(request.full_url)
        body = getattr(request, "data", None)
        seen.append({"method": method, "url": url, "body": body.decode("utf-8") if body else ""})
        assert request.get_header("Authorization") == "Bearer abs-secret-token"
        if method == "GET" and url == "https://abs.internal/api/libraries/library-1":
            return FakeResponse(
                payload={
                    "folders": [
                        {"fullPath": str(tmp_path / "audiobookshelf")},
                    ]
                }
            )
        if method == "POST" and url == "https://abs.internal/api/libraries/library-1/scan":
            return FakeResponse(status=200)
        if method == "GET" and url.startswith("https://abs.internal/api/libraries/library-1/items"):
            return FakeResponse(
                payload={
                    "results": [
                        {
                            "id": "library-item-1",
                            "libraryId": "library-1",
                            "path": "/library/A. Writer/Test Book/Test Book.m4b",
                            "relPath": "A. Writer/Test Book/Test Book.m4b",
                            "mediaType": "book",
                            "media": {"id": "media-book-1", "metadata": {"title": "Test Book"}},
                            "libraryFiles": [],
                        }
                    ],
                    "total": 1,
                }
            )
        if method == "POST" and url == "https://abs.internal/api/share/mediaitem":
            payload = json.loads(body.decode("utf-8"))
            assert payload["mediaItemType"] == "book"
            assert payload["mediaItemId"] == "media-book-1"
            assert payload["isDownloadable"] is False
            assert payload["expiresAt"] > 0
            return FakeResponse(
                status=201,
                payload={
                    "id": "share-1",
                    "mediaItemId": "media-book-1",
                    "mediaItemType": "book",
                    "slug": payload["slug"],
                    "expiresAt": "2026-07-19T00:00:00.000Z",
                    "isDownloadable": False,
                },
            )
        raise AssertionError(f"unexpected Audiobookshelf request {method} {url}")

    monkeypatch.setattr(pipeline.urllib.request, "urlopen", fake_urlopen)

    epub = tmp_path / "book.epub"
    _write_minimal_epub(epub)
    job = create_job_from_epub(epub_path=epub, original_filename="book.epub", principal_id="principal-1")
    job_dir = Path(job["storage"]["job_dir"])
    audio_dir = job_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    for chapter in job["chapters"]:
        _write_tone_wav(audio_dir / chapter["audio_filename"])

    completed = continue_job(job_dir)

    assert completed["status"] == "audiobookshelf_imported"
    public_share = completed["audiobookshelf_import"]["public_share"]
    assert public_share["status"] == "public_share_ready"
    assert public_share["source"] == "created_audiobookshelf_share"
    assert public_share["absolute_url"].startswith("https://abs.example.com/share/ea-")
    assert public_share["token_exposed"] is False
    assert public_share["raw_library_path_exposed"] is False
    assert [row["method"] for row in seen] == ["GET", "POST", "GET", "POST"]
    reply = telegram_epub_reply_text(completed)
    assert "Audiobookshelf public share link: https://abs.example.com/share/" in reply
    assert "Player-scoped playback link: https://app.example.com/internal/audiobooks/player/" in reply
    rendered = json.dumps(completed, sort_keys=True)
    assert "abs-secret-token" not in rendered
    assert "media-book-1" not in rendered
    assert "library-item-1" not in rendered
    assert str(tmp_path / "audiobookshelf") not in reply


def test_audiobookshelf_import_root_prefers_scanned_durable_audiobooks_folder(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    durable_root = tmp_path / "durable-audiobooks"
    configured_root = durable_root / "media" / "Audiobooks"
    library_root = durable_root / "My Music" / "Audiobooks"
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_TRUST_LIBRARY_FOLDER_PATHS", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_DURABLE_STORAGE_ROOT", str(durable_root))
    monkeypatch.setattr(pipeline, "_path_is_existing_writable_dir", lambda path: path == library_root)
    monkeypatch.setattr(
        pipeline,
        "_audiobookshelf_library_folders",
        lambda: (
            durable_root / "My Music" / "Requested",
            library_root,
            durable_root / "My Books" / "Requested",
        ),
    )

    selected, detail = pipeline._effective_audiobookshelf_import_root(configured_root)

    assert selected == library_root
    assert detail["source"] == "audiobookshelf_library_folder"
    assert detail["configured_root"] == str(configured_root)
    assert detail["configured_root_in_library"] is False
    assert detail["library_folder_checked"] is True


def test_audiobookshelf_import_root_uses_configured_root_when_library_folder_unmounted(monkeypatch) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    configured_root = Path("/mnt/pcloud/media/Audiobooks")
    library_root = Path("/mnt/pcloud/My Music/Audiobooks")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_TRUST_LIBRARY_FOLDER_PATHS", "1")
    monkeypatch.setattr(pipeline, "_path_is_existing_writable_dir", lambda path: False)
    monkeypatch.setattr(
        pipeline,
        "_audiobookshelf_library_folders",
        lambda: (library_root,),
    )

    selected, detail = pipeline._effective_audiobookshelf_import_root(configured_root)

    assert selected == configured_root
    assert detail["source"] == "configured_root_library_folder_unavailable"
    assert detail["configured_root"] == str(configured_root)
    assert detail["configured_root_in_library"] is False
    assert detail["library_folder_checked"] is True


def test_audiobookshelf_import_root_uses_configured_root_by_default_on_library_mismatch(monkeypatch) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    configured_root = Path("/mnt/pcloud/media/Audiobooks")
    library_root = Path("/mnt/pcloud/My Music/Audiobooks")
    monkeypatch.setattr(pipeline, "_path_is_existing_writable_dir", lambda path: path == library_root)
    monkeypatch.setattr(
        pipeline,
        "_audiobookshelf_library_folders",
        lambda: (library_root,),
    )

    selected, detail = pipeline._effective_audiobookshelf_import_root(configured_root)

    assert selected == configured_root
    assert detail["source"] == "configured_root_library_folder_mismatch"
    assert detail["configured_root"] == str(configured_root)
    assert detail["configured_root_in_library"] is False
    assert detail["library_folder_paths_trusted"] is False


def test_audiobookshelf_lookup_skips_epub_only_title_match(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    monkeypatch.setenv("EA_AUDIOBOOKSHELF_API_BASE_URL", "https://abs.internal")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_API_TOKEN", "abs-secret-token")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_LIBRARY_ID", "library-1")
    target_path = tmp_path / "A. Writer" / "Test Book" / "Test Book.m4b"
    metadata = pipeline.EpubMetadata(
        title="Test Book",
        author="A. Writer",
        language="en-US",
        source_filename="book.epub",
        source_sha256="abc123",
    )

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {
                    "results": [
                        {
                            "id": "epub-only-item",
                            "path": "/mnt/pcloud/Mybooks/requested/A. Writer/Test Book/book.epub",
                            "mediaType": "book",
                            "media": {
                                "id": "epub-only-media",
                                "metadata": {"title": "Test Book"},
                                "numAudioFiles": 0,
                            },
                            "libraryFiles": [
                                {"metadata": {"path": "/mnt/pcloud/Mybooks/requested/A. Writer/Test Book/book.epub"}}
                            ],
                        },
                        {
                            "id": "audio-item",
                            "path": str(target_path),
                            "mediaType": "book",
                            "media": {
                                "id": "audio-media",
                                "metadata": {"title": "Test Book"},
                                "numAudioFiles": 1,
                            },
                            "libraryFiles": [],
                        },
                    ],
                    "total": 2,
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout=None):
        assert request.get_header("Authorization") == "Bearer abs-secret-token"
        assert str(request.full_url).startswith("https://abs.internal/api/libraries/library-1/items")
        return FakeResponse()

    monkeypatch.setattr(pipeline.urllib.request, "urlopen", fake_urlopen)

    item = pipeline._find_audiobookshelf_imported_item(target_path=target_path, metadata=metadata)

    assert item["status"] == "item_found"
    assert item["library_item_id"] == "audio-item"
    assert item["media_item_id"] == "audio-media"


def test_continue_job_preserves_ready_public_share_when_refresh_fails(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import continue_job, create_job_from_epub

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "0")
    monkeypatch.setenv("EA_M4B_TOOL_BIN", "definitely-missing-m4b-tool")
    monkeypatch.setenv("EA_AUDIOBOOK_FFMPEG_M4B_FALLBACK", "1")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_AUTO_IMPORT", "1")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_IMPORT_ROOT", str(tmp_path / "audiobookshelf"))
    monkeypatch.setenv("EA_AUDIOBOOK_ACCESS_SIGNING_SECRET", "test-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_PLAYER_ACCESS_BASE_URL", "https://app.example.com")
    monkeypatch.setenv("EA_AUDIOBOOK_PUBLICATION_STT_GATE_REQUIRED", "0")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_PUBLIC_SHARE_ENABLED", "1")
    epub = tmp_path / "book.epub"
    _write_minimal_epub(epub)
    job = create_job_from_epub(epub_path=epub, original_filename="book.epub", principal_id="principal-1")
    job_dir = Path(job["storage"]["job_dir"])
    audio_dir = job_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    for chapter in job["chapters"]:
        _write_tone_wav(audio_dir / chapter["audio_filename"])
    previous_import = {
        "status": "imported",
        "target_path": str(tmp_path / "audiobookshelf" / "A. Writer" / "Test Book" / "Test Book.m4b"),
        "target_root": str(tmp_path / "audiobookshelf"),
        "player_scoped_reference": {
            "status": "signed_reference_ready",
            "relative_url": "/internal/audiobooks/player/old-token",
            "absolute_url": "https://app.example.com/internal/audiobooks/player/old-token",
        },
        "public_share": {
            "status": "public_share_ready",
            "absolute_url": "https://abs.example.com/share/ea-test-book",
            "telegram_delivery": {"status": "sent", "message_id": 123},
            "token_exposed": False,
            "raw_library_path_exposed": False,
        },
    }
    job["audiobookshelf_import"] = previous_import
    (job_dir / "job.json").write_text(json.dumps(job, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        pipeline,
        "_create_or_reuse_audiobookshelf_public_share",
        lambda **kwargs: {"status": "share_failed", "reason": "dns_failed", "token_exposed": False},
    )
    monkeypatch.setattr(
        pipeline,
        "create_player_scoped_audiobook_reference",
        lambda **kwargs: {"status": "blocked", "reason": "secret_missing"},
    )
    monkeypatch.setattr(
        pipeline,
        "_build_audiobook_publication_gate",
        lambda **kwargs: {
            "contract_name": "ea.audiobook_publication_audio_gate.v1",
            "status": "pass",
            "issues": [],
            "raw_paths_exposed": False,
        },
    )

    completed = continue_job(job_dir)

    imported = completed["audiobookshelf_import"]
    assert imported["public_share"]["status"] == "public_share_ready"
    assert imported["public_share"]["absolute_url"] == "https://abs.example.com/share/ea-test-book"
    assert imported["public_share"]["preserved_after_refresh_failure"] is True
    assert imported["public_share"]["latest_refresh_reason"] == "dns_failed"
    assert imported["player_scoped_reference"]["status"] == "signed_reference_ready"
    assert imported["player_scoped_reference"]["relative_url"] == "/internal/audiobooks/player/old-token"


def test_blocked_publication_gate_does_not_preserve_stale_player_reference() -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    refreshed_import = {
        "status": "imported",
        "public_share": {"status": "blocked_audio_publication_gate", "reason": "audio_tail_too_quiet"},
    }
    previous_import = {
        "status": "imported",
        "player_scoped_reference": {
            "status": "signed_reference_ready",
            "relative_url": "/internal/audiobooks/player/stale-token",
            "absolute_url": "https://app.example.com/internal/audiobooks/player/stale-token",
        },
        "public_share": {"status": "public_share_ready", "absolute_url": "https://abs.example.com/share/old"},
    }

    imported = pipeline._preserve_ready_audiobookshelf_access(
        import_result=refreshed_import,
        previous_import=previous_import,
    )

    assert imported["public_share"]["status"] == "blocked_audio_publication_gate"
    assert imported["player_scoped_reference"]["status"] == "blocked"
    assert imported["player_scoped_reference"]["reason"] == "audio_tail_too_quiet"
    assert "stale-token" not in json.dumps(imported)


def test_retryable_stt_publication_gate_refreshes_public_share_for_whatsapp(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-retry-stt-share"
    target_path = tmp_path / "Audiobooks" / "Writer" / "Book" / "Book.m4b"
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(b"m4b")
    job_dir.mkdir(parents=True)
    job = {
        "job_id": "job-retry-stt-share",
        "status": "audiobookshelf_imported",
        "principal_id": "cf-email:user@example.com",
        "source": {"player_id": "cf-email:user@example.com", "runner_id": "runner-1"},
        "metadata": {"title": "Retry STT Book", "author": "A. Writer", "language": "en-US"},
        "whatsapp": {"sender_ref": "4368120864006", "session_ref": "session-1", "chat_ref": "chat-1"},
        "audio_publication_gate": {
            "contract_name": "ea.audiobook_publication_audio_gate.v1",
            "status": "fail",
            "issues": ["stt_transcription_failed"],
            "stt": {"samples": [{"issue": "stt_transcription_failed"}]},
        },
        "audiobookshelf_import": {
            "status": "imported",
            "target_path": str(target_path),
            "public_share": {
                "status": "blocked_audio_publication_gate",
                "reason": "stt_transcription_failed",
                "token_exposed": False,
                "raw_library_path_exposed": False,
            },
            "player_scoped_reference": {"status": "blocked", "reason": "stt_transcription_failed"},
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job, indent=2, sort_keys=True), encoding="utf-8")

    monkeypatch.setenv("EA_AUDIOBOOKSHELF_PUBLIC_SHARE_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(
        pipeline,
        "_build_audiobook_publication_gate",
        lambda **kwargs: {
            "contract_name": "ea.audiobook_publication_audio_gate.v1",
            "status": "pass",
            "issues": [],
            "raw_paths_exposed": False,
        },
    )
    monkeypatch.setattr(
        pipeline,
        "create_player_scoped_audiobook_reference",
        lambda **kwargs: {
            "status": "signed_reference_ready",
            "relative_url": "/internal/audiobooks/player/recovered-token",
            "absolute_url": "https://app.example.com/internal/audiobooks/player/recovered-token",
            "vendor_token_exposed": False,
            "raw_library_path_exposed": False,
        },
    )
    monkeypatch.setattr(
        pipeline,
        "_create_or_reuse_audiobookshelf_public_share",
        lambda **kwargs: {
            "status": "public_share_ready",
            "absolute_url": "https://abs.example.com/share/retry-stt-book",
            "token_exposed": False,
            "raw_library_path_exposed": False,
        },
    )

    assert pipeline._audiobook_public_share_followup_pending(job)

    updated = pipeline._refresh_audiobookshelf_public_share_for_job(job_dir)

    imported = updated["audiobookshelf_import"]
    assert updated["audio_publication_gate"]["status"] == "pass"
    assert imported["player_scoped_reference"]["status"] == "signed_reference_ready"
    assert imported["public_share"]["status"] == "public_share_ready"
    assert imported["public_share"]["absolute_url"] == "https://abs.example.com/share/retry-stt-book"
    assert updated["next_action"] == "send_whatsapp_audiobookshelf_public_share_link"


def test_passed_publication_gate_refresh_repairs_blocked_player_reference(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-repair-player-reference"
    target_path = tmp_path / "Audiobooks" / "Writer" / "Book" / "Book.m4b"
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(b"m4b")
    job_dir.mkdir(parents=True)
    job = {
        "job_id": "job-repair-player-reference",
        "status": "audiobookshelf_imported",
        "principal_id": "cf-email:user@example.com",
        "source": {"player_id": "cf-email:user@example.com", "runner_id": "runner-1"},
        "metadata": {"title": "Repair Reference Book", "author": "A. Writer", "language": "en-US"},
        "whatsapp": {"sender_ref": "4368120864006", "session_ref": "session-1"},
        "audio_publication_gate": {
            "contract_name": "ea.audiobook_publication_audio_gate.v1",
            "status": "pass",
            "issues": [],
            "raw_paths_exposed": False,
        },
        "audiobookshelf_import": {
            "status": "imported",
            "target_path": str(target_path),
            "public_share": {"status": "share_failed", "reason": "dns_failed"},
            "player_scoped_reference": {"status": "blocked", "reason": "old_gate_failure"},
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job, indent=2, sort_keys=True), encoding="utf-8")

    monkeypatch.setenv("EA_AUDIOBOOKSHELF_PUBLIC_SHARE_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(
        pipeline,
        "create_player_scoped_audiobook_reference",
        lambda **kwargs: {
            "status": "signed_reference_ready",
            "relative_url": "/internal/audiobooks/player/repaired-token",
            "absolute_url": "https://app.example.com/internal/audiobooks/player/repaired-token",
            "vendor_token_exposed": False,
            "raw_library_path_exposed": False,
        },
    )
    monkeypatch.setattr(
        pipeline,
        "_create_or_reuse_audiobookshelf_public_share",
        lambda **kwargs: {
            "status": "public_share_ready",
            "absolute_url": "https://abs.example.com/share/repaired-book",
            "token_exposed": False,
            "raw_library_path_exposed": False,
        },
    )

    updated = pipeline._refresh_audiobookshelf_public_share_for_job(job_dir)

    imported = updated["audiobookshelf_import"]
    assert imported["player_scoped_reference"]["status"] == "signed_reference_ready"
    assert imported["public_share"]["status"] == "public_share_ready"
    assert updated["next_action"] == "send_whatsapp_audiobookshelf_public_share_link"


def test_nonretryable_publication_gate_is_not_share_followup_pending(monkeypatch) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    monkeypatch.setenv("EA_AUDIOBOOKSHELF_PUBLIC_SHARE_ENABLED", "1")
    for issue in ("audio_tail_too_quiet", "stt_transcript_not_book_text"):
        job = {
            "status": "audiobookshelf_imported",
            "audio_publication_gate": {"status": "fail", "issues": [issue]},
            "audiobookshelf_import": {
                "status": "imported",
                "public_share": {
                    "status": "blocked_audio_publication_gate",
                    "reason": issue,
                    "token_exposed": False,
                    "raw_library_path_exposed": False,
                },
            },
        }

        assert not pipeline._audiobook_public_share_followup_pending(job)


def test_legacy_too_short_stt_gate_gets_one_resample_followup(monkeypatch) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    monkeypatch.setenv("EA_AUDIOBOOKSHELF_PUBLIC_SHARE_ENABLED", "1")
    job = {
        "status": "audiobookshelf_imported",
        "audio_publication_gate": {
            "status": "fail",
            "issues": ["stt_transcript_too_short"],
            "stt": {"samples": [{"status": "fail", "issue": "stt_transcript_too_short"}]},
        },
        "audiobookshelf_import": {
            "status": "imported",
            "public_share": {
                "status": "blocked_audio_publication_gate",
                "reason": "stt_transcript_too_short",
                "token_exposed": False,
                "raw_library_path_exposed": False,
            },
        },
    }

    assert pipeline._audiobook_public_share_followup_pending(job)

    resampled_job = json.loads(json.dumps(job))
    resampled_job["audio_publication_gate"]["stt"]["samples"][0]["attempt_count"] = 5
    resampled_job["audio_publication_gate"]["stt"]["samples"][0]["extractor_seek_mode"] = "output_side_audio_stream"
    resampled_job["audio_publication_gate"]["stt"]["short_book_text_tolerance"] = "v1"
    assert not pipeline._audiobook_public_share_followup_pending(resampled_job)


def test_receipt_suppresses_revoked_public_share_url(monkeypatch, tmp_path: Path) -> None:
    from app.services.audiobook_epub_pipeline import build_audiobook_job_receipt

    job_dir = tmp_path / "job-revoked-share"
    job_dir.mkdir()
    (job_dir / "job.json").write_text(
        json.dumps(
            {
                "job_id": "job-revoked-share",
                "status": "waiting_voice_selection",
                "metadata": {"title": "Book", "author": "A. Writer", "language": "en-US"},
                "audiobookshelf_import": {
                    "status": "imported",
                    "public_share": {
                        "status": "revoked_wrong_voice",
                        "absolute_url": "https://abs.example.com/share/stale",
                        "slug_sha256": "s" * 64,
                    },
                    "player_scoped_reference": {"status": "blocked", "reason": "waiting_voice_selection"},
                },
                "audio_publication_gate": {"status": "fail", "issues": ["public_share_revoked_wrong_voice"]},
            }
        ),
        encoding="utf-8",
    )

    receipt = build_audiobook_job_receipt(job_dir=job_dir)

    imported = receipt["audiobookshelf_import"]
    assert imported["public_share_status"] == "revoked_wrong_voice"
    assert imported["public_share_url"] == ""
    assert imported["public_share_url_suppressed"] is True
    assert "https://abs.example.com/share/stale" not in json.dumps(receipt)


def test_audiobook_job_receipt_includes_sanitized_stt_gate(tmp_path: Path) -> None:
    from app.services.audiobook_epub_pipeline import build_audiobook_job_receipt

    job_dir = tmp_path / "job-stt-receipt"
    job_dir.mkdir()
    (job_dir / "job.json").write_text(
        json.dumps(
            {
                "job_id": "job-stt-receipt",
                "status": "audiobookshelf_imported",
                "metadata": {"title": "Book", "author": "A. Writer", "language": "en-US"},
                "audio_publication_gate": {
                    "status": "pass",
                    "issues": [],
                    "stt": {
                        "status": "pass",
                        "enabled": True,
                        "required": True,
                        "sample_count": 1,
                        "sample_seconds": 30,
                        "passed_samples": 1,
                        "failed_samples": 0,
                        "source_text_sha256": "s" * 64,
                        "source_token_count": 42,
                        "raw_text_exposed": False,
                        "samples": [
                            {
                                "index": 1,
                                "status": "pass",
                                "transcriber": "cartesia/ink-whisper",
                                "transcript_sha256": "t" * 64,
                                "transcript_token_count": 12,
                                "book_token_overlap": 1.0,
                                "book_unique_token_overlap": 1.0,
                                "extractor_seek_mode": "output_side_audio_stream",
                                "raw_text_exposed": False,
                            }
                        ],
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    receipt = build_audiobook_job_receipt(job_dir=job_dir)
    stt = receipt["audio_publication_gate"]["stt"]

    assert stt["status"] == "pass"
    assert stt["enabled"] is True
    assert stt["required"] is True
    assert stt["passed_samples"] == 1
    assert stt["raw_text_exposed"] is False
    assert stt["samples"][0]["transcript_sha256"] == "t" * 64
    assert stt["samples"][0]["raw_text_exposed"] is False
    assert "transcript_text" not in json.dumps(receipt)


def test_resume_due_audiobook_jobs_sends_public_share_after_audiobookshelf_scan(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-share"
    job_dir.mkdir(parents=True)
    import_root = tmp_path / "audiobookshelf"
    target_path = import_root / "A. Writer" / "Test Book" / "Test Book.m4b"
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(b"fake m4b")
    job_payload = {
        "job_id": "job-share",
        "principal_id": "principal-1",
        "status": "audiobookshelf_imported",
        "updated_at": "2026-06-19T20:00:00Z",
        "metadata": {
            "title": "Test Book",
            "author": "A. Writer",
            "language": "en-US",
            "source_filename": "book.epub",
        },
        "storage": {"job_dir": str(job_dir)},
        "telegram": {"chat_id": "42", "message_id": "7"},
        "audiobookshelf_import": {
            "status": "imported",
            "target_path": str(target_path),
            "public_share": {
                "status": "waiting_for_audiobookshelf_scan",
                "telegram_followup_pending": True,
                "token_exposed": False,
                "raw_library_path_exposed": False,
            },
        },
        "audio_publication_gate": {"status": "pass", "issues": []},
    }
    (job_dir / "job.json").write_text(json.dumps(job_payload, indent=2, sort_keys=True), encoding="utf-8")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_IMPORT_ROOT", str(import_root))
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_PUBLIC_SHARE_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_API_BASE_URL", "https://abs.internal")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_PUBLIC_BASE_URL", "https://abs.example.com")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_API_TOKEN", "abs-secret-token")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_LIBRARY_ID", "library-1")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_SCAN_POLL_SECONDS", "0")
    monkeypatch.setenv("EA_TELEGRAM_BOT_TOKEN", "telegram-secret-token")
    seen_abs: list[dict[str, object]] = []
    sent_telegram: list[dict[str, object]] = []

    class FakeResponse:
        def __init__(self, *, status: int = 200, payload: dict[str, object] | None = None, text: str = ""):
            self.status = status
            self._body = text.encode("utf-8") if text else json.dumps(payload or {}).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return self._body

    def fake_urlopen(request, timeout=None):
        method = str(getattr(request, "method", "") or request.get_method())
        url = str(request.full_url)
        body = getattr(request, "data", None)
        if url.startswith("https://api.telegram.org/bottelegram-secret-token/sendMessage"):
            payload = urllib_parse_qs(body.decode("utf-8") if body else "")
            sent_telegram.append({"method": method, "url": url, "payload": payload})
            return FakeResponse(payload={"ok": True, "result": {"message_id": 99}})
        seen_abs.append({"method": method, "url": url, "body": body.decode("utf-8") if body else ""})
        assert request.get_header("Authorization") == "Bearer abs-secret-token"
        if method == "POST" and url == "https://abs.internal/api/libraries/library-1/scan":
            return FakeResponse(status=200)
        if method == "GET" and url.startswith("https://abs.internal/api/libraries/library-1/items"):
            return FakeResponse(
                payload={
                    "results": [
                        {
                            "id": "library-item-1",
                            "path": str(target_path),
                            "mediaType": "book",
                            "media": {"id": "media-book-1", "metadata": {"title": "Test Book"}},
                            "libraryFiles": [],
                        }
                    ],
                    "total": 1,
                }
            )
        if method == "POST" and url == "https://abs.internal/api/share/mediaitem":
            payload = json.loads(body.decode("utf-8"))
            return FakeResponse(
                status=201,
                payload={
                    "id": "share-1",
                    "slug": payload["slug"],
                    "expiresAt": "2026-07-19T00:00:00.000Z",
                    "isDownloadable": False,
                },
            )
        raise AssertionError(f"unexpected request {method} {url}")

    def urllib_parse_qs(value: str) -> dict[str, str]:
        from urllib.parse import parse_qs

        return {key: values[0] for key, values in parse_qs(value).items()}

    monkeypatch.setattr(pipeline.urllib.request, "urlopen", fake_urlopen)

    summary = pipeline.resume_due_audiobook_jobs(notify_telegram=True)

    assert summary["attempted"] == 0
    assert summary["share_link_attempted"] == 1
    assert summary["share_links_ready"] == 1
    assert summary["share_link_pending"] == 0
    assert summary["share_link_notifications"][0]["notification"]["status"] == "sent"
    assert [row["method"] for row in seen_abs] == ["POST", "GET", "POST"]
    assert len(sent_telegram) == 1
    telegram_payload = sent_telegram[0]["payload"]
    assert telegram_payload["chat_id"] == "42"
    assert telegram_payload["reply_to_message_id"] == "7"
    assert "Audiobookshelf finished scanning Test Book" in telegram_payload["text"]
    assert "https://abs.example.com/share/ea-" in telegram_payload["text"]
    reply_markup = json.loads(telegram_payload["reply_markup"])
    callback_values = [
        str(button.get("callback_data") or "")
        for row in list(reply_markup.get("inline_keyboard") or [])
        for button in row
    ]
    assert any(value.startswith("ap|a|") for value in callback_values)
    assert any(value.startswith("ap|r|") for value in callback_values)
    updated = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    public_share = updated["audiobookshelf_import"]["public_share"]
    assert public_share["status"] == "public_share_ready"
    assert public_share["telegram_followup_pending"] is False
    assert public_share["telegram_delivery"]["status"] == "sent"
    assert public_share["playback_acceptance_callback"]["status"] == "ready"
    assert public_share["playback_acceptance_callback"]["raw_token_exposed"] is False
    job_receipt = json.loads((job_dir / "job_receipt.json").read_text(encoding="utf-8"))
    receipt_import = job_receipt["audiobookshelf_import"]
    assert receipt_import["public_share_telegram_delivery_status"] == "sent"
    assert receipt_import["public_share_telegram_message_id_present"] is True
    assert receipt_import["public_share_telegram_message_id_sha256"]
    assert job_receipt["playback_acceptance"]["callback_ready"] is True
    assert job_receipt["playback_acceptance"]["callback_token_exposed"] is False
    rendered = json.dumps(updated, sort_keys=True)
    assert "abs-secret-token" not in rendered
    assert "telegram-secret-token" not in rendered
    assert "media-book-1" not in rendered
    assert "library-item-1" not in rendered


def test_resume_due_audiobook_jobs_force_bypasses_public_share_cooldown(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-share-force"
    job_dir.mkdir(parents=True)
    target_path = tmp_path / "audiobookshelf" / "A. Writer" / "Ready Book" / "Ready Book.m4b"
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(b"fake m4b")
    job_payload = {
        "job_id": "job-share-force",
        "principal_id": "principal-1",
        "status": "audiobookshelf_imported",
        "updated_at": "2026-06-19T20:00:00Z",
        "metadata": {"title": "Ready Book", "author": "A. Writer", "language": "en-US"},
        "storage": {"job_dir": str(job_dir)},
        "telegram": {"chat_id": "42", "message_id": "7"},
        "audiobookshelf_import": {
            "status": "imported",
            "target_path": str(target_path),
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://abs.example.com/share/ea-ready-book",
                "telegram_followup_pending": True,
                "token_exposed": False,
                "raw_library_path_exposed": False,
            },
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job_payload, indent=2, sort_keys=True), encoding="utf-8")
    (job_dir / "audiobookshelf_share_state.json").write_text(
        json.dumps({"attempted_at": "2026-06-19T20:00:00Z", "status": "started"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setenv("EA_AUDIOBOOK_PUBLIC_SHARE_ATTEMPT_COOLDOWN_SECONDS", "3600")
    sent: list[dict[str, object]] = []

    def fake_send(*, job: dict[str, object], text: str) -> dict[str, object]:
        sent.append({"job_id": job["job_id"], "text": text})
        return {"status": "sent", "message_id": 123}

    monkeypatch.setattr(pipeline, "_send_telegram_audiobook_status", fake_send)

    blocked = pipeline.resume_due_audiobook_jobs(
        now=datetime(2026, 6, 19, 20, 1, tzinfo=UTC),
        notify_telegram=True,
    )
    assert blocked["share_link_attempted"] == 0
    assert blocked["share_link_pending"] == 1
    assert sent == []

    summary = pipeline.resume_due_audiobook_jobs(
        now=datetime(2026, 6, 19, 20, 1, tzinfo=UTC),
        notify_telegram=True,
        force_public_share_followup=True,
    )

    assert summary["share_link_attempted"] == 1
    assert summary["share_links_ready"] == 1
    assert summary["share_link_pending"] == 0
    assert sent[0]["job_id"] == "job-share-force"
    assert "Audiobookshelf finished scanning Ready Book" in str(sent[0]["text"])
    updated = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    public_share = updated["audiobookshelf_import"]["public_share"]
    assert public_share["telegram_followup_pending"] is False
    assert public_share["telegram_delivery"]["status"] == "sent"
    assert public_share["telegram_delivery"]["message_id"] == 123


def test_resume_due_audiobook_jobs_blocks_default_voice_share_when_user_voice_job_pending(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    jobs_root = tmp_path / "jobs"
    default_dir = jobs_root / "job-default-voice"
    pending_dir = jobs_root / "job-selected-voice"
    default_dir.mkdir(parents=True)
    pending_dir.mkdir(parents=True)
    source_sha = "a" * 64
    default_payload = {
        "job_id": "job-default-voice",
        "principal_id": "principal-1",
        "status": "audiobookshelf_imported",
        "created_at": "2026-06-19T20:00:00Z",
        "updated_at": "2026-06-19T20:03:00Z",
        "metadata": {
            "title": "Wrong Voice Book",
            "author": "A. Writer",
            "language": "de-DE",
            "source_sha256": source_sha,
        },
        "source": {"kind": "epub", "source_sha256": source_sha},
        "storage": {"job_dir": str(default_dir)},
        "telegram": {"chat_id": "42", "message_id": "7"},
        "provider": {
            "preferred": "unmixr_ai",
            "voice_selection": {
                "status": "selected",
                "selected": {"label": "Auto Voice", "default": True},
            },
        },
        "audiobookshelf_import": {
            "status": "imported",
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://abs.example.com/share/wrong-voice",
                "telegram_followup_pending": True,
                "token_exposed": False,
                "raw_library_path_exposed": False,
            },
        },
    }
    pending_payload = {
        "job_id": "job-selected-voice",
        "principal_id": "principal-1",
        "status": "blocked_external_tts",
        "created_at": "2026-06-19T20:04:00Z",
        "updated_at": "2026-06-19T20:05:00Z",
        "metadata": {
            "title": "Wrong Voice Book",
            "author": "A. Writer",
            "language": "de-DE",
            "source_sha256": source_sha,
        },
        "source": {"kind": "epub", "source_sha256": source_sha},
        "storage": {"job_dir": str(pending_dir)},
        "provider": {
            "preferred": "unmixr_ai",
            "voice_selection": {
                "status": "selected_by_user",
                "selected_candidate_key": "seraphina_de",
                "selected": {"label": "Seraphina"},
                "raw_voice_ids_exposed": False,
            },
        },
        "render_result": {
            "status": "blocked",
            "reason": "Insufficient API balance for selected voice",
            "replacement_voice_required": True,
        },
    }
    (default_dir / "job.json").write_text(json.dumps(default_payload, indent=2, sort_keys=True), encoding="utf-8")
    (pending_dir / "job.json").write_text(json.dumps(pending_payload, indent=2, sort_keys=True), encoding="utf-8")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))

    def fail_send(*, job: dict[str, object], text: str) -> dict[str, object]:
        raise AssertionError("stale default-voice share must not be sent")

    monkeypatch.setattr(pipeline, "_send_telegram_audiobook_status", fail_send)

    summary = pipeline.resume_due_audiobook_jobs(
        notify_telegram=True,
        force_public_share_followup=True,
    )

    assert summary["share_link_attempted"] == 1
    assert summary["share_links_ready"] == 0
    assert summary["share_links_blocked"] == 1
    assert summary["share_link_notifications"][0]["notification"] == {
        "status": "blocked",
        "reason": "same_source_user_selected_voice_pending",
    }
    updated = json.loads((default_dir / "job.json").read_text(encoding="utf-8"))
    public_share = updated["audiobookshelf_import"]["public_share"]
    assert public_share["telegram_followup_pending"] is False
    assert public_share["telegram_delivery"]["status"] == "blocked"
    assert public_share["telegram_delivery"]["reason"] == "same_source_user_selected_voice_pending"
    assert public_share["telegram_delivery"]["message_id"] == ""
    assert updated["next_action"] == "finish_user_selected_voice_audiobook_before_sending_public_share_link"
    receipt = json.loads((default_dir / "job_receipt.json").read_text(encoding="utf-8"))
    receipt_import = receipt["audiobookshelf_import"]
    assert receipt_import["public_share_telegram_delivery_status"] == "blocked"
    assert receipt_import["public_share_telegram_delivery_reason"] == "same_source_user_selected_voice_pending"
    serialized = json.dumps(updated, sort_keys=True)
    assert "Seraphina" not in serialized
    assert source_sha not in json.dumps(public_share["delivery_block"], sort_keys=True)


def test_resume_due_audiobook_jobs_retries_imported_job_missing_public_share(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-share-missing"
    job_dir.mkdir(parents=True)
    target_path = tmp_path / "audiobookshelf" / "A. Writer" / "Missing Share" / "Missing Share.m4b"
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(b"fake m4b")
    job_payload = {
        "job_id": "job-share-missing",
        "principal_id": "principal-1",
        "status": "audiobookshelf_imported",
        "metadata": {"title": "Missing Share", "author": "A. Writer", "language": "en-US"},
        "storage": {"job_dir": str(job_dir)},
        "telegram": {"chat_id": "42", "message_id": "7"},
        "audiobookshelf_import": {
            "status": "imported",
            "target_path": str(target_path),
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job_payload, indent=2, sort_keys=True), encoding="utf-8")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_PUBLIC_SHARE_ENABLED", "1")
    sent: list[str] = []

    def fake_refresh(job_dir: Path) -> dict[str, object]:
        job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
        imported = dict(job["audiobookshelf_import"])
        imported["public_share"] = {
            "status": "public_share_ready",
            "absolute_url": "https://abs.example.com/share/ea-missing-share",
            "telegram_followup_pending": True,
            "token_exposed": False,
            "raw_library_path_exposed": False,
        }
        job["audiobookshelf_import"] = imported
        (job_dir / "job.json").write_text(json.dumps(job, indent=2, sort_keys=True), encoding="utf-8")
        return job

    def fake_send(*, job: dict[str, object], text: str) -> dict[str, object]:
        sent.append(text)
        return {"status": "sent", "message_id": 321}

    monkeypatch.setattr(pipeline, "_refresh_audiobookshelf_public_share_for_job", fake_refresh)
    monkeypatch.setattr(pipeline, "_send_telegram_audiobook_status", fake_send)

    summary = pipeline.resume_due_audiobook_jobs(notify_telegram=True)

    assert summary["share_link_attempted"] == 1
    assert summary["share_links_ready"] == 1
    assert summary["share_link_pending"] == 0
    assert "Audiobookshelf finished scanning Missing Share" in sent[0]
    updated = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    public_share = updated["audiobookshelf_import"]["public_share"]
    assert public_share["telegram_followup_pending"] is False
    assert public_share["telegram_delivery"]["status"] == "sent"


def test_telegram_async_public_share_reply_records_live_delivery_receipt(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.api.routes import channels
    from app.services.audiobook_epub_pipeline import build_audiobook_job_receipt

    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-share-ready"
    job_dir.mkdir(parents=True)
    import_root = tmp_path / "audiobookshelf"
    target_path = import_root / "A. Writer" / "Test Book" / "Test Book.m4b"
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(b"fake m4b")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_IMPORT_ROOT", str(import_root))
    job = {
        "job_id": "job-share-ready",
        "status": "audiobookshelf_imported",
        "metadata": {"title": "Test Book", "author": "A. Writer", "language": "en-US"},
        "storage": {"job_dir": str(job_dir)},
        "telegram": {"chat_id": "42", "message_id": "7"},
        "merge_result": {"status": "m4b_ready", "output_file": str(target_path), "chapter_count": 2},
        "audiobookshelf_import": {
            "status": "imported",
            "target_path": str(target_path),
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://abs.example.com/share/ea-test-book",
                "slug_sha256": "c" * 64,
                "telegram_followup_pending": True,
                "token_exposed": False,
                "raw_library_path_exposed": False,
            },
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    updated = channels._record_audiobook_public_share_reply_delivery(
        job=job,
        send_receipt={"status": "sent", "message_id": "101"},
    )

    public_share = updated["audiobookshelf_import"]["public_share"]
    assert public_share["telegram_followup_pending"] is False
    assert public_share["telegram_delivery"]["status"] == "sent"
    assert public_share["telegram_delivery"]["message_id"] == "101"
    receipt = build_audiobook_job_receipt(job_dir=job_dir)
    receipt_import = receipt["audiobookshelf_import"]
    assert receipt_import["public_share_telegram_delivery_status"] == "sent"
    assert receipt_import["public_share_telegram_message_id_present"] is True
    assert receipt_import["public_share_telegram_message_id_sha256"]
    rendered = json.dumps(receipt, sort_keys=True)
    assert '"message_id": "101"' not in rendered
    assert "https://abs.example.com/share/ea-test-book" in rendered


def test_audiobook_playback_acceptance_is_redacted_in_job_receipt(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services.audiobook_epub_pipeline import (
        build_audiobook_job_receipt,
        record_audiobook_playback_acceptance,
    )

    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-playback-ok"
    job_dir.mkdir(parents=True)
    import_root = tmp_path / "audiobookshelf"
    target_path = import_root / "A. Writer" / "Test Book" / "Test Book.m4b"
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(b"fake m4b")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_IMPORT_ROOT", str(import_root))
    job = {
        "job_id": "job-playback-ok",
        "status": "audiobookshelf_imported",
        "metadata": {"title": "Test Book", "author": "A. Writer", "language": "en-US"},
        "storage": {"job_dir": str(job_dir)},
        "telegram": {"chat_id": "42", "message_id": "7"},
        "merge_result": {"status": "m4b_ready", "output_file": str(target_path), "chapter_count": 2},
        "audiobookshelf_import": {
            "status": "imported",
            "target_path": str(target_path),
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://abs.example.com/share/ea-test-book",
                "slug_sha256": "c" * 64,
                "telegram_delivery": {"status": "sent", "message_id": "101"},
                "token_exposed": False,
                "raw_library_path_exposed": False,
            },
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    updated = record_audiobook_playback_acceptance(
        job_dir=job_dir,
        accepted=True,
        source="telegram",
        message_id="202",
        feedback="Played the full sample and it sounds good.",
    )

    assert updated["playback_acceptance"]["status"] == "accepted"
    assert updated["playback_acceptance"]["accepted"] is True
    receipt = build_audiobook_job_receipt(job_dir=job_dir)
    playback = receipt["playback_acceptance"]
    assert playback["status"] == "accepted"
    assert playback["accepted"] is True
    assert playback["source"] == "telegram"
    assert playback["feedback_sha256"]
    assert playback["message_id_sha256"]
    assert playback["public_share_url_sha256"]
    assert playback["audiobookshelf_target_file_sha256"]
    assert playback["telegram_public_share_message_id_sha256"]
    assert playback["raw_feedback_exposed"] is False
    assert receipt["updated_at"]
    assert receipt["next_action"] == "playback_accepted"


def test_rejected_playback_review_action_is_exposed_in_job_receipt(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services.audiobook_epub_pipeline import (
        build_audiobook_job_receipt,
        record_audiobook_playback_acceptance,
    )

    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-playback-review"
    job_dir.mkdir(parents=True)
    import_root = tmp_path / "audiobookshelf"
    target_path = import_root / "A. Writer" / "Review Book" / "Review Book.m4b"
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(b"fake m4b")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_IMPORT_ROOT", str(import_root))
    job = {
        "job_id": "job-playback-review",
        "status": "audiobookshelf_imported",
        "metadata": {"title": "Review Book", "author": "A. Writer", "language": "en-US"},
        "storage": {"job_dir": str(job_dir)},
        "whatsapp": {
            "sender_ref": "4368120864006",
            "session_ref": "session-1",
            "public_share_delivery": {"status": "sent", "message_id": "wamid.share.1"},
        },
        "merge_result": {"status": "m4b_ready", "output_file": str(target_path), "chapter_count": 2},
        "audiobookshelf_import": {
            "status": "imported",
            "target_path": str(target_path),
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://abs.example.com/share/review-book",
                "slug_sha256": "c" * 64,
                "whatsapp_delivery": {"status": "sent", "message_id": "wamid.share.1"},
                "token_exposed": False,
                "raw_library_path_exposed": False,
            },
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    updated = record_audiobook_playback_acceptance(
        job_dir=job_dir,
        accepted=False,
        source="whatsapp_button_recovered",
        message_id="wamid.playback.1",
        feedback="whatsapp_button_playback_rejected",
    )

    assert updated["next_action"] == "review_audiobook_playback_problem"
    receipt = build_audiobook_job_receipt(job_dir=job_dir)
    assert receipt["status"] == "audiobookshelf_imported"
    assert receipt["next_action"] == "review_audiobook_playback_problem"
    assert receipt["updated_at"]
    assert receipt["playback_acceptance"]["status"] == "rejected"
    assert receipt["playback_acceptance"]["source"] == "whatsapp_button_recovered"
    assert receipt["playback_acceptance"]["raw_message_id_exposed"] is False
    rendered = json.dumps(receipt, sort_keys=True)
    assert "whatsapp_button_playback_rejected" not in rendered
    assert "wamid.playback.1" not in rendered


def test_telegram_playback_acceptance_callback_records_redacted_receipt(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.api.routes import channels
    from app.services.audiobook_epub_pipeline import build_audiobook_job_receipt

    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-playback-button"
    job_dir.mkdir(parents=True)
    import_root = tmp_path / "audiobookshelf"
    target_path = import_root / "A. Writer" / "Test Book" / "Test Book.m4b"
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(b"fake m4b")
    monkeypatch.setenv("EA_TELEGRAM_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_IMPORT_ROOT", str(import_root))
    job = {
        "job_id": "job-playback-button",
        "status": "audiobookshelf_imported",
        "metadata": {"title": "Test Book", "author": "A. Writer", "language": "en-US"},
        "storage": {"job_dir": str(job_dir)},
        "telegram": {"chat_id": "42", "message_id": "7"},
        "merge_result": {"status": "m4b_ready", "output_file": str(target_path), "chapter_count": 2},
        "audiobookshelf_import": {
            "status": "imported",
            "target_path": str(target_path),
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://abs.example.com/share/ea-test-book",
                "slug_sha256": "c" * 64,
                "telegram_delivery": {"status": "sent", "message_id": "101"},
                "token_exposed": False,
                "raw_library_path_exposed": False,
            },
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    updated_job, buttons = channels._telegram_audiobook_playback_acceptance_buttons(
        bot_config={"token": "telegram-token"},
        chat_id="42",
        job=job,
    )

    assert updated_job["audiobookshelf_import"]["public_share"]["playback_acceptance_callback"]["status"] == "ready"
    assert buttons
    accepted_callback = buttons[0][0][1]
    assert accepted_callback.startswith("ap|a|")
    decision = channels._telegram_callback_turn_decision(
        SimpleNamespace(
            payload={
                "kind": "callback_query",
                "callback_data": accepted_callback,
                "_bot_config": {"token": "telegram-token"},
            },
            chat_id="42",
            current_message_id="202",
        )
    )

    assert decision.reply_text == "Marked the audiobook playback as working."
    receipt = build_audiobook_job_receipt(job_dir=job_dir)
    playback = receipt["playback_acceptance"]
    assert playback["status"] == "accepted"
    assert playback["accepted"] is True
    assert playback["source"] == "telegram_button"
    assert playback["message_id_sha256"]
    assert playback["feedback_sha256"]
    assert playback["callback_ready"] is True
    rendered = json.dumps(receipt, sort_keys=True)
    assert "telegram_button_playback_accepted" not in rendered
    assert '"message_id": "202"' not in rendered
    assert accepted_callback.split("|")[2] not in rendered


def test_playback_acceptance_callback_searches_discovery_roots(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    local_root = tmp_path / "jobs-local"
    host_root = tmp_path / "jobs-host"
    local_root.mkdir()
    host_root.mkdir()
    job_dir = host_root / "job-playback-host"
    job_dir.mkdir(parents=True)
    target_path = tmp_path / "audiobookshelf" / "A. Writer" / "Test Book" / "Test Book.m4b"
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(b"fake m4b")

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(local_root))
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_HOST_ROOT", str(host_root))

    job = {
        "job_id": "job-playback-host",
        "status": "audiobookshelf_imported",
        "metadata": {"title": "Test Book", "author": "A. Writer", "language": "en-US"},
        "storage": {"job_dir": str(job_dir)},
        "merge_result": {"status": "m4b_ready", "output_file": str(target_path), "chapter_count": 2},
        "audiobookshelf_import": {
            "status": "imported",
            "target_path": str(target_path),
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://abs.example.com/share/host-test-book",
                "whatsapp_delivery": {"status": "sent", "message_id": "wamid.share.1"},
            },
        },
        "playback_acceptance": {"status": "not_recorded", "accepted": False},
    }
    prepared = pipeline.ensure_audiobook_playback_acceptance_callback(job)
    (job_dir / "job.json").write_text(json.dumps(prepared, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    token = prepared["audiobookshelf_import"]["public_share"]["playback_acceptance_callback"]["token"]

    updated = pipeline.record_audiobook_playback_acceptance_by_callback_token(
        callback_token=str(token),
        accepted=True,
        source="whatsapp_button",
        message_id="wamid.callback.1",
        feedback="whatsapp_button_playback_accepted",
    )

    assert updated["playback_acceptance"]["status"] == "accepted"
    assert updated["playback_acceptance"]["source"] == "whatsapp_button"


def test_telegram_voice_dismiss_callback_retries_refill_before_responding(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.api.routes import channels

    voice_job_no_replacement = {
        "status": "waiting_voice_selection",
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "last_action": {"action": "dismiss"},
                "pending_batch": [
                    {
                        "preset_key": "voice-two",
                        "callback_token": "sample-token-two",
                        "sample_file": "two.wav",
                        "label": "Voice Two",
                        "sample_audio_ready": True,
                    }
                ],
                "replacement_candidate_keys": [],
            }
        },
        "storage": {"job_dir": str(tmp_path)},
    }
    refilled_job = {
        **voice_job_no_replacement,
        "provider": {
            "voice_selection": {
                **voice_job_no_replacement["provider"]["voice_selection"],
                "last_action": {
                    "action": "dismiss",
                    "replacement_candidate_keys": ["voice-three"],
                },
                "pending_batch": [
                    {
                        "preset_key": "voice-three",
                        "callback_token": "sample-token-three",
                        "sample_file": "three.wav",
                        "label": "Voice Three",
                        "sample_audio_ready": True,
                    }
                ],
            }
        },
    }

    monkeypatch.setenv("EA_TELEGRAM_CALLBACK_SECRET", "callback-secret")

    sent = []

    def fake_apply(*, callback_token: str, action: str) -> dict[str, object]:
        assert callback_token == "sample-token-two"
        assert action == "dismiss"
        return voice_job_no_replacement

    def fake_refill(*, job_dir: Path, refill_pending: bool = False) -> dict[str, object]:
        assert refill_pending is True
        return refilled_job

    def fake_send_samples(*, bot_config: dict[str, object], chat_id: str, job: dict[str, object]) -> list[dict[str, object]]:
        sent.append([row["label"] for row in job["provider"]["voice_selection"]["pending_batch"] if isinstance(row, dict)])
        return [{"token": "sample-token-three", "status": "sent"}]

    monkeypatch.setattr(channels, "apply_audiobook_voice_audition_action", fake_apply)
    monkeypatch.setattr(channels, "prepare_audiobook_voice_audition", fake_refill)
    monkeypatch.setattr(channels, "_telegram_send_audiobook_voice_samples", fake_send_samples)
    monkeypatch.setattr(channels, "record_audiobook_voice_sample_delivery", lambda **kwargs: kwargs["job"])

    decision = channels._telegram_callback_turn_decision(
        SimpleNamespace(
            payload={
                "kind": "callback_query",
                "callback_data": channels._telegram_encode_audiobook_voice_callback(
                    bot_config={"token": "bot-token"},
                    action="d",
                    token="sample-token-two",
                    chat_id="42",
                ),
                "_bot_config": {"token": "bot-token", "secret": "callback-secret"},
            },
            chat_id="42",
            container=object(),
        )
    )

    assert decision.reply_text == "Dismissed. I sent 1 replacement audiobook voice sample."
    assert sent == [["Voice Three"]]


def test_telegram_voice_use_callback_sends_explicit_replacement_sample(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.api.routes import channels

    replacement_job = {
        "status": "waiting_voice_selection",
        "metadata": {"title": "Test Book"},
        "totals": {"chapter_count": 1, "char_count": 1000},
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "reason": "selected_voice_provider_balance_blocked",
                "last_action": {
                    "action": "offer_replacement",
                    "replacement_candidate_keys": ["piper-local"],
                },
                "pending_batch": [
                    {
                        "provider": "piper_local_fast",
                        "preset_key": "piper-local",
                        "callback_token": "replacement-token",
                        "sample_file": "replacement.wav",
                        "label": "Piper German Thorsten high",
                        "sample_audio_ready": True,
                    }
                ],
                "selected": {"label": "Seraphina"},
                "replacement_candidate_keys": ["piper-local"],
            }
        },
        "telegram": {},
        "storage": {"job_dir": str(tmp_path)},
    }
    recorded_job = {
        **replacement_job,
        "telegram": {
            "voice_sample_delivery": {
                "status": "sent",
                "sent_count": 1,
                "expected_count": 1,
            }
        },
    }
    monkeypatch.setenv("EA_TELEGRAM_CALLBACK_SECRET", "callback-secret")
    sent: list[list[str]] = []

    def fake_apply(*, callback_token: str, action: str) -> dict[str, object]:
        assert callback_token == "seraphina-token"
        assert action == "use"
        return replacement_job

    def fake_send_samples(*, bot_config: dict[str, object], chat_id: str, job: dict[str, object]) -> list[dict[str, object]]:
        sent.append([row["label"] for row in job["provider"]["voice_selection"]["pending_batch"] if isinstance(row, dict)])
        return [{"token": "replacement-token", "status": "sent"}]

    def fake_record(**kwargs) -> dict[str, object]:
        assert kwargs["sample_receipts"][0]["token"] == "replacement-token"
        return recorded_job

    monkeypatch.setattr(channels, "apply_audiobook_voice_audition_action", fake_apply)
    monkeypatch.setattr(channels, "_telegram_send_audiobook_voice_samples", fake_send_samples)
    monkeypatch.setattr(channels, "record_audiobook_voice_sample_delivery", fake_record)

    decision = channels._telegram_callback_turn_decision(
        SimpleNamespace(
            payload={
                "kind": "callback_query",
                "callback_data": channels._telegram_encode_audiobook_voice_callback(
                    bot_config={"token": "bot-token"},
                    action="u",
                    token="seraphina-token",
                    chat_id="42",
                ),
                "_bot_config": {"token": "bot-token", "secret": "callback-secret"},
            },
            chat_id="42",
            container=object(),
        )
    )

    assert "selected voice for Test Book is blocked" in decision.reply_text
    assert "I sent 1 replacement voice sample" in decision.reply_text
    assert sent == [["Piper German Thorsten high"]]


def test_m4b_command_uses_chaptered_merge_shape(tmp_path: Path) -> None:
    from app.services.audiobook_epub_pipeline import build_m4b_tool_command

    command = build_m4b_tool_command(
        audio_dir=tmp_path / "audio",
        output_file=tmp_path / "Test Book.m4b",
        title="Test Book",
        author="A. Writer",
        narrator="Narrator",
    )

    assert command[:2] == ["m4b-tool", "merge"]
    assert "--output-file" in command
    assert "--audio-codec" in command
    assert "aac" in command
    assert "--audio-bitrate" in command


def test_voice_selection_prefers_expressive_fiction_voice(monkeypatch, tmp_path: Path) -> None:
    from app.services.audiobook_epub_pipeline import EpubChapter, EpubMetadata, select_unmixr_voice_for_book

    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": "calm-id", "label": "Calm explainer", "language": "en-US", "tags": ["narration", "clear", "nonfiction"], "default": True},
                {"voice_id": "story-id", "label": "Fiction performer", "language": "en-US", "tags": ["narration", "fiction", "dialogue", "expressive"]},
            ]
        ),
    )
    chapter_dir = tmp_path / "chapters"
    chapter_dir.mkdir()
    text = '"Run," she said. "The clinic knows." He asked whether the deck was still hot. This novel opens in a shadow market.'
    (chapter_dir / "001 - Opening.txt").write_text(text, encoding="utf-8")
    metadata = EpubMetadata(title="Shadow Novel", author="A. Writer", language="en-US", source_filename="story.txt", source_sha256="sha")
    chapter = EpubChapter(index=1, title="Opening", source_href="story:1", text_path="001 - Opening.txt", audio_filename="001 - Opening.wav", char_count=len(text), sha256="sha")

    selection = select_unmixr_voice_for_book(metadata=metadata, chapters=(chapter,), job_dir=tmp_path)

    assert selection["status"] == "selected"
    public = selection["public"]
    assert public["selected"]["label"] == "Fiction performer"
    assert "story-id" not in json.dumps(public)
    assert public["selected"]["voice_id_sha256"]


def test_default_unmixr_voice_language_can_be_inferred_from_tags(monkeypatch, tmp_path: Path) -> None:
    from app.services.audiobook_epub_pipeline import EpubChapter, EpubMetadata, select_unmixr_voice_for_book

    monkeypatch.delenv("EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON", raising=False)
    monkeypatch.delenv("EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_PATH", raising=False)
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "0")
    monkeypatch.delenv("EA_AUDIOBOOK_DEFAULT_VOICE_LANGUAGE", raising=False)
    monkeypatch.setenv("UNMIXR_VOICE_ID", "default-secret-voice")
    monkeypatch.setenv("UNMIXR_LANGUAGE", "en-US")
    monkeypatch.setenv("EA_AUDIOBOOK_DEFAULT_VOICE_TAGS", "audiobook,narration,german,calm,nonfiction")

    chapter_dir = tmp_path / "chapters"
    chapter_dir.mkdir()
    text = "Dies ist ein ruhiger deutscher Abschnitt ueber Selbstmitgefuehl und Alltag."
    (chapter_dir / "001 - Test.txt").write_text(text, encoding="utf-8")
    metadata = EpubMetadata(title="Deutsches Sachbuch", author="A. Writer", language="de", source_filename="book.epub", source_sha256="sha")
    chapter = EpubChapter(index=1, title="Test", source_href="test.xhtml", text_path="001 - Test.txt", audio_filename="001 - Test.wav", char_count=len(text), sha256="sha")

    selection = select_unmixr_voice_for_book(metadata=metadata, chapters=(chapter,), job_dir=tmp_path)

    selected = selection["public"]["selected"]
    assert selected["language"] == "de"
    assert selected["score"] > 30
    assert "default-secret-voice" not in json.dumps(selection["public"])


def test_azw3_document_is_accepted_as_audiobook_source(monkeypatch) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    assert pipeline.is_audiobook_source_document(filename="book.azw3", mime_type="application/vnd.amazon.ebook")
    assert pipeline.is_audiobook_source_document(filename="book.mobi", mime_type="application/x-mobipocket-ebook")
    assert pipeline.is_audiobook_source_document(filename="book.azw", mime_type="application/octet-stream")
    assert pipeline.is_epub_document(filename="book.azw3", mime_type="application/vnd.amazon.ebook")


def test_create_job_from_azw3_converts_to_epub_before_extraction(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import create_job_from_epub

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    source = tmp_path / "kindle-book.azw3"
    source.write_bytes(b"fake kindle bytes")

    def fake_convert(*, source_path: Path, output_path: Path) -> dict[str, object]:
        assert source_path.name.endswith(".azw3")
        _write_minimal_epub(output_path)
        return {
            "status": "converted",
            "converter": "fake",
            "source_sha256": pipeline._sha256_file(source_path),
            "epub_sha256": pipeline._sha256_file(output_path),
            "raw_paths_exposed": False,
        }

    monkeypatch.setattr(pipeline, "_convert_kindle_source_to_epub", fake_convert)
    monkeypatch.setattr(pipeline, "continue_job", lambda job_dir: json.loads((Path(job_dir) / "job.json").read_text(encoding="utf-8")))

    job = create_job_from_epub(
        epub_path=source,
        original_filename="kindle-book.azw3",
        principal_id="principal-1",
    )

    source_payload = job["source"]
    assert job["job_id"].startswith("azw3-audiobook-")
    assert source_payload["kind"] == "azw3"
    assert source_payload["rights_basis"] == "operator_supplied_kindle_file"
    assert source_payload["source_original"].endswith(".azw3")
    assert source_payload["source_kindle"].endswith(".azw3")
    assert source_payload["source_epub"].endswith(".converted.epub")
    assert source_payload["kindle_conversion"]["status"] == "converted"
    assert job["metadata"]["source_sha256"] == pipeline._sha256_file(source)
    assert Path(source_payload["source_epub"]).is_file()


def test_kindle_source_formats_complete_audiobook_pipeline_without_external_tts(monkeypatch, tmp_path: Path) -> None:
    from app.services.audiobook_epub_pipeline import create_job_from_epub, continue_job

    fake_converter = _write_fake_ebook_convert(tmp_path)
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EBOOK_CONVERT_BIN", str(fake_converter))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "0")
    monkeypatch.setenv("EA_M4B_TOOL_BIN", "definitely-missing-m4b-tool")
    monkeypatch.setenv("EA_AUDIOBOOK_FFMPEG_M4B_FALLBACK", "1")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_AUTO_IMPORT", "1")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_IMPORT_ROOT", str(tmp_path / "audiobookshelf"))
    monkeypatch.setenv("EA_AUDIOBOOK_ACCESS_SIGNING_SECRET", "test-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_PLAYER_ACCESS_BASE_URL", "https://app.example.com")
    monkeypatch.setenv("EA_AUDIOBOOK_PUBLICATION_STT_GATE_REQUIRED", "0")

    completed_by_suffix: dict[str, dict[str, object]] = {}
    for suffix in ("azw", "azw3", "mobi"):
        filename = f"short-example.{suffix}"
        source = tmp_path / filename
        source.write_bytes(f"super short {suffix} fixture\n".encode("utf-8"))

        job = create_job_from_epub(
            epub_path=source,
            original_filename=filename,
            principal_id="principal-1",
        )
        job_dir = Path(job["storage"]["job_dir"])
        audio_dir = job_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        for chapter in job["chapters"]:
            _write_tone_wav(audio_dir / chapter["audio_filename"], seconds=0.08)

        completed = continue_job(job_dir)
        completed_by_suffix[suffix] = completed

    assert set(completed_by_suffix) == {"azw", "azw3", "mobi"}
    for suffix, completed in completed_by_suffix.items():
        source_payload = completed["source"]
        assert completed["status"] == "audiobookshelf_imported"
        assert completed["metadata"]["title"] == "Test Book"
        assert completed["metadata"]["source_filename"] == f"short-example.{suffix}"
        assert completed["provider"]["raw_book_text_leaves_ea"] is False
        assert source_payload["kind"] == suffix
        assert source_payload["rights_basis"] == "operator_supplied_kindle_file"
        assert source_payload["source_original"].endswith(f".{suffix}")
        assert source_payload["source_kindle"].endswith(f".{suffix}")
        assert source_payload["source_epub"].endswith(".converted.epub")
        assert source_payload["kindle_conversion"]["status"] == "converted"
        assert source_payload["kindle_conversion"]["converter"] == str(fake_converter)
        assert source_payload["kindle_conversion"]["raw_paths_exposed"] is False
        assert completed["merge_result"]["provider"] == "ffmpeg"
        assert "-movflags" in completed["merge_result"]["command"]
        assert "+faststart" in completed["merge_result"]["command"]
        assert completed["audio_publication_gate"]["status"] == "pass"
        imported_path = Path(completed["audiobookshelf_import"]["target_path"])
        assert imported_path.is_file()
        assert imported_path.suffix == ".m4b"


def test_create_job_from_azw3_blocks_when_converter_missing(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import create_job_from_epub

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setattr(pipeline, "_kindle_to_epub_converter_available", lambda: False)
    source = tmp_path / "kindle-book.azw3"
    source.write_bytes(b"fake kindle bytes")

    with pytest.raises(RuntimeError, match="kindle_audiobook_converter_missing"):
        create_job_from_epub(
            epub_path=source,
            original_filename="kindle-book.azw3",
            principal_id="principal-1",
        )


def test_voice_selection_prefers_language_match_over_tag_match(monkeypatch, tmp_path: Path) -> None:
    from app.services.audiobook_epub_pipeline import EpubChapter, EpubMetadata, select_unmixr_voice_for_book

    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "0")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {
                    "voice_id": "english-perfect-tags",
                    "label": "English calm audiobook",
                    "language": "en-US",
                    "tags": ["audiobook", "narration", "nonfiction", "clear", "calm", "professional", "male"],
                },
                {
                    "voice_id": "german-simple",
                    "label": "German narrator",
                    "language": "de-DE",
                    "tags": ["audiobook", "narration"],
                },
            ]
        ),
    )
    chapter_dir = tmp_path / "chapters"
    chapter_dir.mkdir()
    text = "Dies ist ein ruhiger deutscher Abschnitt ueber Selbstmitgefuehl und Alltag."
    (chapter_dir / "001 - Test.txt").write_text(text, encoding="utf-8")
    metadata = EpubMetadata(title="Deutsches Sachbuch", author="Andreas Knuf", language="de", source_filename="book.epub", source_sha256="sha")
    chapter = EpubChapter(index=1, title="Test", source_href="test.xhtml", text_path="001 - Test.txt", audio_filename="001 - Test.wav", char_count=len(text), sha256="sha")

    selection = select_unmixr_voice_for_book(metadata=metadata, chapters=(chapter,), job_dir=tmp_path)

    selected = selection["public"]["selected"]
    assert selected["label"] == "German narrator"
    assert selected["language_match"] is True
    assert selection["public"]["candidate_scores"][1]["label"] == "English calm audiobook"
    assert selection["public"]["candidate_scores"][1]["language_match"] is False


def test_voice_selection_uses_author_gender_as_soft_signal(monkeypatch, tmp_path: Path) -> None:
    from app.services.audiobook_epub_pipeline import EpubChapter, EpubMetadata, select_unmixr_voice_for_book

    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": "male-id", "label": "Male narrator", "language": "en-US", "tags": ["audiobook", "narration", "clear", "male"]},
                {"voice_id": "female-id", "label": "Female narrator", "language": "en-US", "tags": ["audiobook", "narration", "clear", "female"]},
            ]
        ),
    )
    chapter_dir = tmp_path / "chapters"
    chapter_dir.mkdir()
    text = "This nonfiction chapter explains the process in a calm practical way."
    (chapter_dir / "001 - Test.txt").write_text(text, encoding="utf-8")
    metadata = EpubMetadata(title="Calm Guide", author="Andreas Knuf", language="en-US", source_filename="book.epub", source_sha256="sha")
    chapter = EpubChapter(index=1, title="Test", source_href="test.xhtml", text_path="001 - Test.txt", audio_filename="001 - Test.wav", char_count=len(text), sha256="sha")

    selection = select_unmixr_voice_for_book(metadata=metadata, chapters=(chapter,), job_dir=tmp_path)

    assert selection["public"]["book_profile"]["author_gender_signal"] == "male"
    assert selection["public"]["selected"]["label"] == "Male narrator"
    assert selection["public"]["selected"]["author_gender_match"] is True


def test_voice_selection_learns_from_selected_and_dismissed_feedback(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import EpubChapter, EpubMetadata, select_unmixr_voice_for_book

    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_FEEDBACK_PATH", str(tmp_path / "voice-feedback.json"))
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": "dismissed-id", "preset_key": "dismissed", "label": "Often dismissed", "language": "en-US", "tags": ["audiobook", "narration", "clear"]},
                {"voice_id": "selected-id", "preset_key": "selected", "label": "Often selected", "language": "en-US", "tags": ["audiobook", "narration", "clear"]},
            ]
        ),
    )
    pipeline.record_audiobook_voice_feedback(
        job={"metadata": {"source_sha256": "other-book"}},
        candidate={"preset_key": "dismissed", "voice_id_sha256": pipeline._sha256_bytes(b"dismissed-id"), "label": "Often dismissed"},
        action="dismiss",
    )
    pipeline.record_audiobook_voice_feedback(
        job={"metadata": {"source_sha256": "other-book"}},
        candidate={"preset_key": "selected", "voice_id_sha256": pipeline._sha256_bytes(b"selected-id"), "label": "Often selected"},
        action="selected",
    )
    chapter_dir = tmp_path / "chapters"
    chapter_dir.mkdir()
    text = "This nonfiction chapter explains the process in a calm practical way."
    (chapter_dir / "001 - Test.txt").write_text(text, encoding="utf-8")
    metadata = EpubMetadata(title="Calm Guide", author="A. Writer", language="en-US", source_filename="book.epub", source_sha256="book-sha")
    chapter = EpubChapter(index=1, title="Test", source_href="test.xhtml", text_path="001 - Test.txt", audio_filename="001 - Test.wav", char_count=len(text), sha256="sha")

    selection = select_unmixr_voice_for_book(metadata=metadata, chapters=(chapter,), job_dir=tmp_path)

    selected = selection["public"]["selected"]
    assert selected["label"] == "Often selected"
    assert selected["voice_feedback_adjustment"] > 0
    scores = selection["public"]["candidate_scores"]
    dismissed = next(row for row in scores if row["label"] == "Often dismissed")
    assert dismissed["voice_feedback_adjustment"] < 0
    assert "dismissed-id" not in json.dumps(selection["public"])
    assert "selected-id" not in json.dumps(selection["public"])


def test_voice_selection_reuses_completed_same_book_voice(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import EpubChapter, EpubMetadata, select_unmixr_voice_for_book

    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_FEEDBACK_PATH", str(tmp_path / "voice-feedback.json"))
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": "default-id", "preset_key": "default", "label": "Default narrator", "language": "en-US", "tags": ["audiobook", "narration", "clear"], "default": True},
                {"voice_id": "previous-id", "preset_key": "previous", "label": "Previous book voice", "language": "en-US", "tags": ["audiobook", "narration", "clear"]},
            ]
        ),
    )
    same_source_sha = "same-book-sha"
    pipeline.record_audiobook_completed_voice_feedback(
        {
            "status": "audiobookshelf_imported",
            "source": {"source_sha256": same_source_sha},
            "provider": {
                "voice_selection": {
                    "selected_candidate_key": "previous",
                    "selected": {
                        "preset_key": "previous",
                        "label": "Previous book voice",
                        "voice_id_sha256": pipeline._sha256_bytes(b"previous-id"),
                    },
                }
            },
        }
    )
    chapter_dir = tmp_path / "chapters"
    chapter_dir.mkdir()
    text = "This nonfiction chapter explains the process in a calm practical way."
    (chapter_dir / "001 - Test.txt").write_text(text, encoding="utf-8")
    metadata = EpubMetadata(title="Calm Guide", author="A. Writer", language="en-US", source_filename="book.epub", source_sha256=same_source_sha)
    chapter = EpubChapter(index=1, title="Test", source_href="test.xhtml", text_path="001 - Test.txt", audio_filename="001 - Test.wav", char_count=len(text), sha256="sha")

    selection = select_unmixr_voice_for_book(metadata=metadata, chapters=(chapter,), job_dir=tmp_path)

    selected = selection["public"]["selected"]
    assert selected["label"] == "Previous book voice"
    assert selected["same_book_voice_reuse"] is True
    assert selected["same_book_voice_adjustment"] > selected["voice_feedback_adjustment"]


def test_generic_voice_discovery_loads_unmixr_audiobook_catalog(monkeypatch) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    pipeline._VOICE_DISCOVERY_CACHE.clear()
    monkeypatch.delenv("EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON", raising=False)
    monkeypatch.delenv("EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_PATH", raising=False)
    monkeypatch.delenv("UNMIXR_VOICE_ID", raising=False)
    monkeypatch.setenv("UNMIXR_API_KEY", "test-api-key")
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_TARGET_COUNT", "30")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_VOICE_DISCOVERY_USE_CASES", "audiobook-voices")
    seen_urls: list[str] = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {
                    "count": 30,
                    "results": [
                        {
                            "uuid": f"voice-{index:02d}",
                            "character": f"Catalog Voice {index}",
                            "gender": "Female" if index % 2 else "Male",
                            "language": "en-US",
                            "quality": "Premium",
                            "capabilities": ["speech", "speech:rate", "speech:pitch"],
                            "use_cases": ["Audiobook", "Narration"],
                            "supported_locales": {"en-US": "https://example.test/en.mp3", "de-DE": "https://example.test/de.mp3"},
                            "is_available": True,
                            "is_multilingual": True,
                            "description": "Warm clear audiobook storytelling voice.",
                            "age": "Adult",
                            "personality": ["Warm", "Calm"],
                        }
                        for index in range(1, 31)
                    ],
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout=None):
        seen_urls.append(str(request.full_url))
        return FakeResponse()

    monkeypatch.setattr(pipeline.urllib.request, "urlopen", fake_urlopen)

    presets = pipeline.load_unmixr_voice_presets()

    assert len(presets) == 30
    assert seen_urls
    assert "c=audiobook-voices" in seen_urls[0]
    assert "page_size=100" in seen_urls[0]
    assert presets[0].source == "discovery:unmixr:audiobook-voices"
    assert "de-de" in presets[0].supported_languages
    assert {"audiobook", "narration", "warm", "clear"}.issubset(set(presets[0].tags))
    assert "test-api-key" not in json.dumps([preset.__dict__ for preset in presets])


def test_voice_discovery_default_target_is_broad_generic_pool(monkeypatch) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    monkeypatch.delenv("EA_AUDIOBOOK_VOICE_DISCOVERY_TARGET_COUNT", raising=False)

    assert pipeline.audiobook_voice_discovery_target_count() == 100


def test_voice_discovery_default_use_cases_include_unfiltered_catalog(monkeypatch) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    monkeypatch.delenv("EA_AUDIOBOOK_UNMIXR_VOICE_DISCOVERY_USE_CASES", raising=False)

    specs = pipeline._unmixr_voice_discovery_specs()

    assert specs[-1] == ("", "", "all")
    assert pipeline._unmixr_voice_list_url(filter_param="", filter_value="", page_size=100).endswith(
        "page_size=100&fields="
        + pipeline._unmixr_voice_discovery_fields().replace(",", "%2C")
    )


def test_voice_discovery_queries_later_generic_specs_after_target_is_met(monkeypatch) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    pipeline._VOICE_DISCOVERY_CACHE.clear()
    monkeypatch.delenv("EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON", raising=False)
    monkeypatch.delenv("EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_PATH", raising=False)
    monkeypatch.delenv("UNMIXR_VOICE_ID", raising=False)
    monkeypatch.setenv("UNMIXR_API_KEY", "test-api-key")
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_TARGET_COUNT", "3")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_VOICE_DISCOVERY_USE_CASES", "audiobook-voices,all")
    seen_urls: list[str] = []

    class FakeResponse:
        def __init__(self, payload: dict[str, object]):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout=None):
        url = str(request.full_url)
        seen_urls.append(url)
        if "c=audiobook-voices" in url:
            return FakeResponse(
                {
                    "results": [
                        {
                            "uuid": f"premium-{index}",
                            "character": f"Premium {index}",
                            "language": "de-DE",
                            "quality": "Premium",
                            "is_available": True,
                        }
                        for index in range(1, 4)
                    ]
                }
            )
        return FakeResponse(
            {
                "results": [
                    {
                        "uuid": "standard-generic-1",
                        "character": "Standard Generic",
                        "language": "de-DE",
                        "quality": "Standard",
                        "use_cases": ["General"],
                        "is_available": True,
                    }
                ]
            }
        )

    monkeypatch.setattr(pipeline.urllib.request, "urlopen", fake_urlopen)

    presets = pipeline.load_unmixr_voice_presets()

    assert any("c=audiobook-voices" in url for url in seen_urls)
    assert any("c=" not in url and "uc=" not in url for url in seen_urls)
    assert [preset.voice_id for preset in presets] == [
        "premium-1",
        "premium-2",
        "premium-3",
        "standard-generic-1",
    ]


def test_configured_voice_catalog_is_augmented_by_generic_discovery(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import create_job_from_epub

    pipeline._VOICE_DISCOVERY_CACHE.clear()
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_VOICE_DISCOVERY_USE_CASES", "audiobook-voices")
    monkeypatch.setenv("UNMIXR_API_KEY", "test-api-key")
    monkeypatch.delenv("UNMIXR_VOICE_ID", raising=False)
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps([{"voice_id": "alice-id", "label": "Alice", "language": "en-US", "tags": ["audiobook", "narration"]}]),
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {
                    "count": 4,
                    "results": [
                        {
                            "uuid": f"discovered-{index}",
                            "character": f"Discovered Voice {index}",
                            "language": "en-US",
                            "quality": "Premium",
                            "capabilities": ["speech"],
                            "use_cases": ["Audiobook", "Narration"],
                            "supported_locales": {"en-US": "https://example.test/en.mp3"},
                            "is_available": True,
                            "description": "Warm clear audiobook storytelling voice.",
                            "personality": ["Warm", "Calm"],
                        }
                        for index in range(1, 5)
                    ],
                }
            ).encode("utf-8")

    monkeypatch.setattr(pipeline.urllib.request, "urlopen", lambda request, timeout=None: FakeResponse())
    tones: dict[str, bytes] = {}
    for index, voice_id in enumerate(("discovered-1", "discovered-2", "discovered-3", "discovered-4"), start=1):
        tone = tmp_path / f"{voice_id}.wav"
        _write_tone_wav(tone, seconds=0.10 + index * 0.02)
        tones[voice_id] = tone.read_bytes()

    def fake_synthesize_request(**kwargs):
        voice_id = str(kwargs.get("voice_id") or "")
        return tones[voice_id], "audio/wav"

    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", fake_synthesize_request)
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)
    epub = tmp_path / "book.epub"
    _write_minimal_epub(epub)

    job = create_job_from_epub(epub_path=epub, original_filename="book.epub", principal_id="principal-1")

    voice_selection = job["provider"]["voice_selection"]
    labels = [row["label"] for row in voice_selection["pending_batch"]]
    assert job["status"] == "waiting_voice_selection"
    assert voice_selection["status"] == "waiting_user_choice"
    assert voice_selection["strategy"] == "generic_voice_discovery_then_book_profile_voice_audition"
    assert voice_selection["candidate_count"] == 5
    assert voice_selection["target_catalog_count"] == 100
    assert labels == ["Discovered Voice 1", "Discovered Voice 2", "Discovered Voice 3"]
    assert "Alice" not in labels
    assert "alice-id" not in json.dumps(job)


def test_voice_audition_batch_prefers_book_language_matches(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import create_job_from_epub

    pipeline._VOICE_DISCOVERY_CACHE.clear()
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "0")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {
                    "voice_id": "english-best-tags",
                    "label": "English perfect tag fit",
                    "language": "en-US",
                    "tags": ["audiobook", "narration", "nonfiction", "clear", "calm", "professional", "male"],
                },
                {
                    "voice_id": "german-one",
                    "label": "German One",
                    "language": "de-DE",
                    "tags": ["audiobook", "narration"],
                },
                {
                    "voice_id": "german-two",
                    "label": "German Two",
                    "language": "de-DE",
                    "tags": ["audiobook", "narration", "calm"],
                },
                {
                    "voice_id": "german-three",
                    "label": "German Three",
                    "language": "de-DE",
                    "tags": ["audiobook", "narration", "clear"],
                },
            ]
        ),
    )
    tones: dict[str, bytes] = {}
    for index, voice_id in enumerate(("english-best-tags", "german-one", "german-two", "german-three"), start=1):
        tone = tmp_path / f"{voice_id}.wav"
        _write_tone_wav(tone, seconds=0.10 + index * 0.02)
        tones[voice_id] = tone.read_bytes()

    def fake_synthesize_request(**kwargs):
        voice_id = str(kwargs.get("voice_id") or "")
        return tones[voice_id], "audio/wav"

    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", fake_synthesize_request)
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)
    epub = tmp_path / "book.epub"
    _write_epub_with_publisher_tail(epub)

    job = create_job_from_epub(epub_path=epub, original_filename="book.epub", principal_id="principal-1")

    voice_selection = job["provider"]["voice_selection"]
    labels = [row["label"] for row in voice_selection["pending_batch"]]
    assert job["status"] == "waiting_voice_selection"
    assert set(labels) == {"German One", "German Two", "German Three"}
    assert all(row["language_match"] is True for row in voice_selection["pending_batch"])
    assert "English perfect tag fit" not in labels
    assert "english-best-tags" not in json.dumps(job)


def test_voice_audition_expands_discovery_when_language_pool_is_underfilled(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import create_job_from_epub

    pipeline._VOICE_DISCOVERY_CACHE.clear()
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_TARGET_COUNT", "100")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_VOICE_DISCOVERY_USE_CASES", "audiobook-voices,uc:general")
    monkeypatch.setenv("UNMIXR_API_KEY", "test-api-key")
    monkeypatch.delenv("EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON", raising=False)
    monkeypatch.delenv("UNMIXR_VOICE_ID", raising=False)

    class FakeResponse:
        def __init__(self, url: str):
            self.url = url

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            if "uc=general" in self.url:
                rows = [
                    {
                        "uuid": f"de-general-{index}",
                        "character": f"German General {index}",
                        "language": "de-DE",
                        "quality": "Wavenet",
                        "capabilities": ["speech"],
                        "use_cases": ["General"],
                        "supported_locales": {"de-DE": "https://example.test/de.mp3"},
                        "is_available": True,
                    }
                    for index in range(1, 4)
                ]
            else:
                rows = [
                    {
                        "uuid": f"en-audiobook-{index}",
                        "character": f"English Audiobook {index}",
                        "language": "en-US",
                        "quality": "Premium",
                        "capabilities": ["speech"],
                        "use_cases": ["Audiobook"],
                        "supported_locales": {"en-US": "https://example.test/en.mp3"},
                        "is_available": True,
                    }
                    for index in range(1, 101)
                ]
            return json.dumps({"count": len(rows), "results": rows}).encode("utf-8")

    seen_urls: list[str] = []

    def fake_urlopen(request, timeout=None):
        seen_urls.append(str(request.full_url))
        return FakeResponse(str(request.full_url))

    monkeypatch.setattr(pipeline.urllib.request, "urlopen", fake_urlopen)
    tones: dict[str, bytes] = {}
    for index, voice_id in enumerate(("de-general-1", "de-general-2", "de-general-3"), start=1):
        tone = tmp_path / f"{voice_id}.wav"
        _write_tone_wav(tone, seconds=0.10 + index * 0.02)
        tones[voice_id] = tone.read_bytes()

    def fake_synthesize_request(**kwargs):
        voice_id = str(kwargs.get("voice_id") or "")
        return tones[voice_id], "audio/wav"

    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", fake_synthesize_request)
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)
    epub = tmp_path / "book.epub"
    _write_epub_with_publisher_tail(epub)

    job = create_job_from_epub(epub_path=epub, original_filename="book.epub", principal_id="principal-1")

    voice_selection = job["provider"]["voice_selection"]
    labels = [row["label"] for row in voice_selection["pending_batch"]]
    assert labels == ["German General 1", "German General 2", "German General 3"]
    assert voice_selection["target_catalog_count"] == 200
    assert voice_selection["discovery_expanded_target_count"] == 200
    assert any("uc=general" in url for url in seen_urls)


def test_generic_voice_discovery_runs_by_default_when_configured_voice_is_underfilled(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import create_job_from_epub

    pipeline._VOICE_DISCOVERY_CACHE.clear()
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.delenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", raising=False)
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_VOICE_DISCOVERY_USE_CASES", "audiobook-voices")
    monkeypatch.setenv("UNMIXR_API_KEY", "test-api-key")
    monkeypatch.delenv("UNMIXR_VOICE_ID", raising=False)
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps([{"voice_id": "alice-id", "label": "Alice", "language": "en-US", "tags": ["audiobook", "narration"]}]),
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {
                    "count": 4,
                    "results": [
                        {
                            "uuid": f"generic-{index}",
                            "character": f"Generic Narrator {index}",
                            "language": "en-US",
                            "quality": "Premium",
                            "capabilities": ["speech"],
                            "use_cases": ["Audiobook", "Narration"],
                            "supported_locales": {"en-US": "https://example.test/en.mp3"},
                            "is_available": True,
                            "description": "Warm clear audiobook storytelling voice.",
                            "personality": ["Warm", "Calm"],
                        }
                        for index in range(1, 5)
                    ],
                }
            ).encode("utf-8")

    seen_urls: list[str] = []

    def fake_urlopen(request, timeout=None):
        seen_urls.append(str(request.full_url))
        return FakeResponse()

    monkeypatch.setattr(pipeline.urllib.request, "urlopen", fake_urlopen)
    tones: dict[str, bytes] = {}
    for index, voice_id in enumerate(("generic-1", "generic-2", "generic-3", "generic-4"), start=1):
        tone = tmp_path / f"{voice_id}.wav"
        _write_tone_wav(tone, seconds=0.10 + index * 0.02)
        tones[voice_id] = tone.read_bytes()

    def fake_synthesize_request(**kwargs):
        voice_id = str(kwargs.get("voice_id") or "")
        return tones[voice_id], "audio/wav"

    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", fake_synthesize_request)
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)
    epub = tmp_path / "book.epub"
    _write_minimal_epub(epub)

    job = create_job_from_epub(epub_path=epub, original_filename="book.epub", principal_id="principal-1")

    voice_selection = job["provider"]["voice_selection"]
    labels = [row["label"] for row in voice_selection["pending_batch"]]
    assert pipeline.audiobook_voice_discovery_enabled() is True
    assert job["status"] == "waiting_voice_selection"
    assert voice_selection["status"] == "waiting_user_choice"
    assert voice_selection["strategy"] == "generic_voice_discovery_then_book_profile_voice_audition"
    assert voice_selection["candidate_count"] == 5
    assert voice_selection["target_catalog_count"] == 100
    assert labels == ["Generic Narrator 1", "Generic Narrator 2", "Generic Narrator 3"]
    assert seen_urls
    assert "page_size=100" in seen_urls[0]
    assert "Alice" not in labels
    assert "alice-id" not in json.dumps(job)


def test_voice_selection_deprioritizes_alice_by_default(monkeypatch, tmp_path: Path) -> None:
    from app.services.audiobook_epub_pipeline import EpubChapter, EpubMetadata, select_unmixr_voice_for_book

    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": "alice-id", "label": "Alice", "language": "en-US", "tags": ["audiobook", "narration", "clear"], "default": True},
                {"voice_id": "warm-id", "label": "Warm narrator", "language": "en-US", "tags": ["audiobook", "narration", "warm", "nonfiction"]},
            ]
        ),
    )
    chapter_dir = tmp_path / "chapters"
    chapter_dir.mkdir()
    text = "This nonfiction chapter explains self compassion in a calm practical way."
    (chapter_dir / "001 - Test.txt").write_text(text, encoding="utf-8")
    metadata = EpubMetadata(title="Self Compassion", author="A. Writer", language="en-US", source_filename="book.epub", source_sha256="sha")
    chapter = EpubChapter(index=1, title="Test", source_href="test.xhtml", text_path="001 - Test.txt", audio_filename="001 - Test.wav", char_count=len(text), sha256="sha")

    selection = select_unmixr_voice_for_book(metadata=metadata, chapters=(chapter,), job_dir=tmp_path)

    assert selection["public"]["selected"]["label"] == "Warm narrator"
    scores = selection["public"]["candidate_scores"]
    assert scores[-1]["label"] == "Alice"
    assert scores[-1]["blocked_by_user"] is True


def test_epub_voice_audition_blocks_underfilled_catalog(monkeypatch, tmp_path: Path) -> None:
    from app.services.audiobook_epub_pipeline import create_job_from_epub, telegram_epub_reply_text

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_AUDITION_MIN_CANDIDATES", "3")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps([{"voice_id": "alice-id", "label": "Alice", "language": "en-US", "tags": ["audiobook", "narration"]}]),
    )
    epub = tmp_path / "book.epub"
    _write_minimal_epub(epub)

    job = create_job_from_epub(epub_path=epub, original_filename="book.epub", principal_id="principal-1")

    assert job["status"] == "blocked_voice_catalog"
    assert job["next_action"] == "discover_or_configure_audiobook_voice_catalog"
    voice_selection = job["provider"]["voice_selection"]
    assert voice_selection["status"] == "blocked"
    assert voice_selection["reason"] == "voice_catalog_underfilled"
    assert voice_selection["candidate_count"] == 1
    assert voice_selection["required_candidate_count"] == 3
    assert voice_selection["target_catalog_count"] == 100
    assert voice_selection["pending_batch"] == []
    assert not (Path(job["storage"]["job_dir"]) / "voice_audition" / "samples").exists()
    assert "alice-id" not in json.dumps(job)
    reply = telegram_epub_reply_text(job)
    assert "need at least 3 available voices" in reply
    assert "catalog currently has 1" in reply


def test_epub_voice_audition_generates_three_samples_and_waits_for_choice(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import create_job_from_epub

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_M4B_TOOL_BIN", "definitely-missing-m4b-tool")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_AUTO_IMPORT", "0")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": "voice-clear", "label": "Clear narrator", "language": "en-US", "tags": ["audiobook", "narration", "clear", "nonfiction"]},
                {"voice_id": "voice-warm", "label": "Warm narrator", "language": "en-US", "tags": ["audiobook", "narration", "warm", "memoir"]},
                {"voice_id": "voice-story", "label": "Story narrator", "language": "en-US", "tags": ["audiobook", "narration", "fiction", "dialogue"]},
                {"voice_id": "voice-four", "label": "Fourth narrator", "language": "en-US", "tags": ["audiobook", "narration"]},
            ]
        ),
    )
    tones: dict[str, bytes] = {}
    for index, voice_id in enumerate(("voice-clear", "voice-warm", "voice-story", "voice-four"), start=1):
        tone = tmp_path / f"{voice_id}.wav"
        _write_tone_wav(tone, seconds=0.10 + index * 0.02)
        tones[voice_id] = tone.read_bytes()
    calls: list[dict[str, object]] = []

    def fake_synthesize_request(**kwargs):
        calls.append(dict(kwargs))
        voice_id = str(kwargs.get("voice_id") or "")
        return tones[voice_id], "audio/wav"

    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", fake_synthesize_request)
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)
    epub = tmp_path / "book.epub"
    _write_minimal_epub(epub)

    job = create_job_from_epub(epub_path=epub, original_filename="book.epub", principal_id="principal-1", chat_id="42")

    assert job["status"] == "waiting_voice_selection"
    voice_selection = job["provider"]["voice_selection"]
    assert voice_selection["status"] == "waiting_user_choice"
    assert voice_selection["book_profile"]["language"] == "en-US"
    assert voice_selection["book_profile"]["topic"]
    assert len(voice_selection["pending_batch"]) == 3
    assert len(calls) == 3
    assert all(len(str(call.get("text") or "")) <= 240 for call in calls)
    rendered = json.dumps(job, sort_keys=True)
    assert "voice-clear" not in rendered
    assert "voice-warm" not in rendered
    assert "voice-story" not in rendered
    for row in voice_selection["pending_batch"]:
        assert row["callback_token"]
        assert row["sample_audio_ready"] is True
        assert (Path(job["storage"]["job_dir"]) / "voice_audition" / "samples" / row["sample_file"]).is_file()


def test_epub_voice_audition_continues_past_failed_premium_samples(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import create_job_from_epub

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_SAMPLE_GENERATION_MAX_ATTEMPTS", "6")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": "premium-one", "label": "Premium One", "language": "en-US", "tags": ["audiobook", "narration", "premium"]},
                {"voice_id": "premium-two", "label": "Premium Two", "language": "en-US", "tags": ["audiobook", "narration", "premium"]},
                {"voice_id": "premium-three", "label": "Premium Three", "language": "en-US", "tags": ["audiobook", "narration", "premium"]},
                {"voice_id": "standard-one", "label": "Standard One", "language": "en-US", "tags": ["general", "wavenet"]},
                {"voice_id": "standard-two", "label": "Standard Two", "language": "en-US", "tags": ["general", "neural2"]},
                {"voice_id": "standard-three", "label": "Standard Three", "language": "en-US", "tags": ["general", "natural"]},
            ]
        ),
    )
    tones: dict[str, bytes] = {}
    for index, voice_id in enumerate(("standard-one", "standard-two", "standard-three"), start=1):
        tone = tmp_path / f"{voice_id}.wav"
        _write_tone_wav(tone, seconds=0.10 + index * 0.02)
        tones[voice_id] = tone.read_bytes()
    calls: list[str] = []

    def fake_synthesize_request(**kwargs):
        voice_id = str(kwargs.get("voice_id") or "")
        calls.append(voice_id)
        if voice_id.startswith("premium-"):
            raise RuntimeError("unmixr_prebuilt_credit_exhausted")
        return tones[voice_id], "audio/wav"

    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", fake_synthesize_request)
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)
    epub = tmp_path / "book.epub"
    _write_minimal_epub(epub)

    job = create_job_from_epub(epub_path=epub, original_filename="book.epub", principal_id="principal-1")

    voice_selection = job["provider"]["voice_selection"]
    labels = [row["label"] for row in voice_selection["pending_batch"]]
    assert labels == ["Standard One", "Standard Two", "Standard Three"]
    assert calls == ["premium-one", "premium-two", "premium-three", "standard-one", "standard-two", "standard-three"]
    assert voice_selection["sample_generation_failed_count"] == 3
    assert voice_selection["sample_generation_attempt_limit"] == 6
    assert voice_selection["underfilled"] is False
    assert voice_selection["underfilled_reason"] == ""


def test_epub_voice_audition_skips_duplicate_sample_audio(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import create_job_from_epub

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_SAMPLE_GENERATION_MAX_ATTEMPTS", "4")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": "voice-one", "label": "Voice One", "language": "en-US", "tags": ["general", "wavenet"]},
                {"voice_id": "voice-two", "label": "Voice Two", "language": "en-US", "tags": ["general", "wavenet"]},
                {"voice_id": "voice-three", "label": "Voice Three", "language": "en-US", "tags": ["general", "wavenet"]},
                {"voice_id": "voice-four", "label": "Voice Four", "language": "en-US", "tags": ["general", "wavenet"]},
            ]
        ),
    )
    duplicate_tone = tmp_path / "duplicate.wav"
    third_tone = tmp_path / "third.wav"
    fourth_tone = tmp_path / "fourth.wav"
    _write_tone_wav(duplicate_tone, seconds=0.12)
    _write_tone_wav(third_tone, seconds=0.16)
    _write_tone_wav(fourth_tone, seconds=0.20)
    tones = {
        "voice-one": duplicate_tone.read_bytes(),
        "voice-two": duplicate_tone.read_bytes(),
        "voice-three": third_tone.read_bytes(),
        "voice-four": fourth_tone.read_bytes(),
    }
    calls: list[str] = []

    def fake_synthesize_request(**kwargs):
        voice_id = str(kwargs.get("voice_id") or "")
        calls.append(voice_id)
        return tones[voice_id], "audio/wav"

    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", fake_synthesize_request)
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)
    epub = tmp_path / "book.epub"
    _write_minimal_epub(epub)

    job = create_job_from_epub(epub_path=epub, original_filename="book.epub", principal_id="principal-1")

    voice_selection = job["provider"]["voice_selection"]
    assert [row["label"] for row in voice_selection["pending_batch"]] == ["Voice One", "Voice Three", "Voice Four"]
    assert calls == ["voice-one", "voice-two", "voice-three", "voice-four"]
    assert voice_selection["sample_generation_failed_count"] == 1
    assert voice_selection["sample_generation_failures"][0]["reason"] == "duplicate_voice_sample_audio"


def test_epub_voice_audition_use_this_renders_with_chosen_voice(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import apply_audiobook_voice_audition_action, create_job_from_epub

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_M4B_TOOL_BIN", "definitely-missing-m4b-tool")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": "voice-one", "label": "Voice One", "language": "en-US", "tags": ["audiobook", "narration", "clear"]},
                {"voice_id": "voice-two", "label": "Voice Two", "language": "en-US", "tags": ["audiobook", "narration", "warm"]},
                {"voice_id": "voice-three", "label": "Voice Three", "language": "en-US", "tags": ["audiobook", "narration", "story"]},
            ]
        ),
    )
    tone = tmp_path / "tone.wav"
    _write_tone_wav(tone)
    calls: list[str] = []

    def fake_synthesize_request(**kwargs):
        calls.append(str(kwargs.get("voice_id") or ""))
        return tone.read_bytes(), "audio/wav"

    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", fake_synthesize_request)
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)
    epub = tmp_path / "book.epub"
    _write_minimal_epub(epub)

    job = create_job_from_epub(epub_path=epub, original_filename="book.epub", principal_id="principal-1")
    chosen = next(row for row in job["provider"]["voice_selection"]["pending_batch"] if row["label"] == "Voice Two")
    completed = apply_audiobook_voice_audition_action(callback_token=chosen["callback_token"], action="use")

    assert completed["provider"]["voice_selection"]["status"] == "selected_by_user"
    assert completed["provider"]["voice_selection"]["selected"]["label"] == "Voice Two"
    assert completed["render_result"]["status"] == "rendered"
    assert "voice-two" in calls[3:]
    assert "voice-one" not in calls[3:]
    assert "voice-three" not in calls[3:]


def test_epub_voice_audition_use_this_clears_previous_voice_render_outputs(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services.audiobook_epub_pipeline import apply_audiobook_voice_audition_action

    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-change-voice"
    audio_dir = job_dir / "audio"
    output_dir = job_dir / "output"
    private_dir = job_dir / "voice_audition"
    audio_dir.mkdir(parents=True)
    output_dir.mkdir()
    private_dir.mkdir()
    _write_tone_wav(audio_dir / "001.wav")
    (output_dir / "book.m4b").write_bytes(b"old m4b")
    old_selection = {
        "status": "selected_by_user",
        "selected_candidate_key": "old-voice",
        "selected_callback_token": "old-token",
        "selected": {"label": "Old Voice", "language": "en-US", "voice_id_sha256": "o" * 64},
    }
    job_payload = {
        "job_id": "job-change-voice",
        "status": "blocked_external_tts",
        "storage": {"job_dir": str(job_dir)},
        "metadata": {"title": "Book", "author": "A. Writer", "language": "en-US"},
        "provider": {"voice_selection": old_selection},
        "render_result": {"status": "blocked", "reason": "selected_voice_language_mismatch"},
        "merge_result": {"status": "m4b_ready", "output_file": str(output_dir / "book.m4b")},
        "audiobookshelf_import": {"status": "waiting_for_m4b"},
    }
    (job_dir / "job.json").write_text(json.dumps(job_payload), encoding="utf-8")
    (private_dir / "private.json").write_text(
        json.dumps(
            {
                "contract_name": "ea.telegram_epub_audiobook_voice_audition.v1",
                "candidates": {
                    "new-token": {
                        "candidate_key": "new-voice",
                        "voice_id": "new-secret-voice",
                        "public": {
                            "label": "New Voice",
                            "language": "en-US",
                            "voice_id_sha256": "n" * 64,
                            "callback_token": "new-token",
                            "preset_key": "new-voice",
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "0")

    updated = apply_audiobook_voice_audition_action(callback_token="new-token", action="use")

    assert updated["status"] == "voice_selected"
    assert updated["provider"]["voice_selection"]["selected"]["label"] == "New Voice"
    assert updated["provider"]["voice_selection"]["render_reset_for_new_voice"]["status"] == "reset"
    assert updated["render_result"]["status"] == "reset_for_new_voice"
    assert not audio_dir.exists()
    assert not output_dir.exists()
    assert "new-secret-voice" not in json.dumps(updated)


def test_epub_voice_audition_use_this_clears_stale_revoked_publication_without_previous_selection(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services.audiobook_epub_pipeline import apply_audiobook_voice_audition_action

    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-stale-publication"
    audio_dir = job_dir / "audio"
    output_dir = job_dir / "output"
    private_dir = job_dir / "voice_audition"
    audio_dir.mkdir(parents=True)
    output_dir.mkdir()
    private_dir.mkdir()
    _write_tone_wav(audio_dir / "001.wav")
    (output_dir / "book.m4b").write_bytes(b"old wrong voice m4b")
    job_payload = {
        "job_id": "job-stale-publication",
        "status": "waiting_voice_selection",
        "storage": {"job_dir": str(job_dir)},
        "metadata": {"title": "Book", "author": "A. Writer", "language": "de"},
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "pending_candidate_keys": ["new-voice"],
                "pending_batch": [{"preset_key": "new-voice", "callback_token": "new-token", "label": "New Voice"}],
            }
        },
        "render_result": {"status": "waiting_voice_selection"},
        "merge_result": {"status": "m4b_ready", "output_file": str(output_dir / "book.m4b")},
        "audiobookshelf_import": {
            "status": "imported",
            "wrong_voice_artifact_revoked": True,
            "player_scoped_reference": {
                "status": "signed_reference_ready",
                "relative_url": "/internal/audiobooks/player/stale-token",
                "absolute_url": "https://app.example.com/internal/audiobooks/player/stale-token",
            },
            "public_share": {"status": "revoked_wrong_voice"},
        },
        "audio_publication_gate": {
            "status": "fail",
            "issues": ["previous_piper_fallback_revoked_wrong_voice"],
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job_payload), encoding="utf-8")
    (private_dir / "private.json").write_text(
        json.dumps(
            {
                "contract_name": "ea.telegram_epub_audiobook_voice_audition.v1",
                "candidates": {
                    "new-token": {
                        "candidate_key": "new-voice",
                        "voice_id": "new-secret-voice",
                        "public": {
                            "label": "New Voice",
                            "language": "de-DE",
                            "voice_id_sha256": "n" * 64,
                            "callback_token": "new-token",
                            "preset_key": "new-voice",
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "0")

    updated = apply_audiobook_voice_audition_action(callback_token="new-token", action="use")

    assert updated["status"] == "voice_selected"
    assert updated["provider"]["voice_selection"]["selected"]["label"] == "New Voice"
    assert updated["provider"]["voice_selection"]["render_reset_for_new_voice"]["status"] == "reset"
    assert updated["merge_result"] == {"status": "waiting_for_chapter_audio"}
    assert updated["audiobookshelf_import"]["status"] == "waiting_for_m4b"
    assert updated["audiobookshelf_import"]["player_scoped_reference"]["status"] == "blocked"
    assert updated["audiobookshelf_import"]["public_share"]["status"] == "blocked_audio_publication_gate"
    assert "stale-token" not in json.dumps(updated["audiobookshelf_import"])
    assert "revoked_wrong_voice" not in json.dumps(updated["audiobookshelf_import"])
    assert updated["audio_publication_gate"]["status"] == "pending"
    assert updated["audio_publication_gate"]["issues"] == ["waiting_for_new_voice_render"]
    assert not audio_dir.exists()
    assert not output_dir.exists()
    assert "new-secret-voice" not in json.dumps(updated)


def test_epub_voice_audition_use_this_ignores_stale_non_pending_token(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services.audiobook_epub_pipeline import apply_audiobook_voice_audition_action, telegram_epub_reply_text

    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-stale-use"
    private_dir = job_dir / "voice_audition"
    private_dir.mkdir(parents=True)
    job_payload = {
        "job_id": "job-stale-use",
        "status": "waiting_voice_selection",
        "storage": {"job_dir": str(job_dir)},
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "pending_candidate_keys": ["active-voice"],
                "pending_batch": [
                    {
                        "preset_key": "active-voice",
                        "callback_token": "active-token",
                        "label": "Active Voice",
                    }
                ],
                "dismissed_candidate_keys": ["stale-voice"],
            }
        },
        "render_result": {"status": "waiting_voice_selection"},
        "merge_result": {"status": "waiting_for_chapter_audio"},
        "audiobookshelf_import": {"status": "waiting_for_m4b"},
    }
    (job_dir / "job.json").write_text(json.dumps(job_payload), encoding="utf-8")
    (private_dir / "private.json").write_text(
        json.dumps(
            {
                "contract_name": "ea.telegram_epub_audiobook_voice_audition.v1",
                "candidates": {
                    "stale-token": {
                        "candidate_key": "stale-voice",
                        "voice_id": "stale-secret-voice",
                        "public": {
                            "label": "Stale Voice",
                            "language": "en-US",
                            "voice_id_sha256": "s" * 64,
                            "callback_token": "stale-token",
                            "preset_key": "stale-voice",
                        },
                    },
                    "active-token": {
                        "candidate_key": "active-voice",
                        "voice_id": "active-secret-voice",
                        "public": {
                            "label": "Active Voice",
                            "language": "en-US",
                            "voice_id_sha256": "a" * 64,
                            "callback_token": "active-token",
                            "preset_key": "active-voice",
                        },
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "0")

    updated = apply_audiobook_voice_audition_action(callback_token="stale-token", action="use")

    selection = updated["provider"]["voice_selection"]
    assert updated["status"] == "waiting_voice_selection"
    assert selection["status"] == "waiting_user_choice"
    assert selection.get("selected", {}) == {}
    assert selection["pending_candidate_keys"] == ["active-voice"]
    assert selection["last_action"]["status"] == "stale_candidate_ignored"
    assert selection["last_action"]["candidate_key"] == "stale-voice"
    assert "stale-secret-voice" not in json.dumps(updated)
    reply = telegram_epub_reply_text(updated)
    assert "button is stale" in reply
    assert "Active Voice" in reply


def test_epub_voice_audition_dismiss_ignores_stale_non_pending_token(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services.audiobook_epub_pipeline import apply_audiobook_voice_audition_action, telegram_epub_reply_text

    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-stale-dismiss"
    private_dir = job_dir / "voice_audition"
    private_dir.mkdir(parents=True)
    job_payload = {
        "job_id": "job-stale-dismiss",
        "status": "voice_selected",
        "storage": {"job_dir": str(job_dir)},
        "provider": {
            "voice_selection": {
                "status": "selected_by_user",
                "selected_candidate_key": "selected-voice",
                "selected_callback_token": "selected-token",
                "selected": {
                    "label": "Selected Voice",
                    "language": "en-US",
                    "voice_id_sha256": "x" * 64,
                    "callback_token": "selected-token",
                    "preset_key": "selected-voice",
                },
                "pending_candidate_keys": [],
                "pending_batch": [],
            }
        },
        "next_action": "render_chapter_audio",
        "render_result": {"status": "rendering"},
        "merge_result": {"status": "waiting_for_chapter_audio"},
        "audiobookshelf_import": {"status": "waiting_for_m4b"},
    }
    (job_dir / "job.json").write_text(json.dumps(job_payload), encoding="utf-8")
    (private_dir / "private.json").write_text(
        json.dumps(
            {
                "contract_name": "ea.telegram_epub_audiobook_voice_audition.v1",
                "candidates": {
                    "stale-token": {
                        "candidate_key": "stale-voice",
                        "voice_id": "stale-secret-voice",
                        "public": {
                            "label": "Stale Voice",
                            "language": "en-US",
                            "voice_id_sha256": "s" * 64,
                            "callback_token": "stale-token",
                            "preset_key": "stale-voice",
                        },
                    },
                    "selected-token": {
                        "candidate_key": "selected-voice",
                        "voice_id": "selected-secret-voice",
                        "public": {
                            "label": "Selected Voice",
                            "language": "en-US",
                            "voice_id_sha256": "x" * 64,
                            "callback_token": "selected-token",
                            "preset_key": "selected-voice",
                        },
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "0")

    updated = apply_audiobook_voice_audition_action(callback_token="stale-token", action="dismiss")

    selection = updated["provider"]["voice_selection"]
    assert updated["status"] == "voice_selected"
    assert updated["next_action"] == "render_chapter_audio"
    assert selection["status"] == "selected_by_user"
    assert selection["selected"]["label"] == "Selected Voice"
    assert selection["pending_candidate_keys"] == []
    assert selection["last_action"]["status"] == "stale_candidate_ignored"
    assert selection["last_action"]["action"] == "dismiss"
    assert selection["last_action"]["candidate_key"] == "stale-voice"
    assert "stale-secret-voice" not in json.dumps(updated)
    reply = telegram_epub_reply_text(updated)
    assert "button is stale" in reply


def test_epub_voice_audition_use_this_clears_outputs_after_reopened_mismatch(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services.audiobook_epub_pipeline import apply_audiobook_voice_audition_action

    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-reopened-mismatch"
    audio_dir = job_dir / "audio"
    output_dir = job_dir / "output"
    private_dir = job_dir / "voice_audition"
    audio_dir.mkdir(parents=True)
    output_dir.mkdir()
    private_dir.mkdir()
    _write_tone_wav(audio_dir / "001.wav")
    (output_dir / "book.m4b").write_bytes(b"old m4b")
    job_payload = {
        "job_id": "job-reopened-mismatch",
        "status": "waiting_voice_selection",
        "storage": {"job_dir": str(job_dir)},
        "metadata": {"title": "Book", "author": "A. Writer", "language": "de"},
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "reason": "selected_voice_language_mismatch",
                "selected": {},
                "selected_candidate_key": "",
                "selected_callback_token": "",
            }
        },
        "render_result": {"status": "waiting_voice_selection", "reason": "selected_voice_language_mismatch"},
        "merge_result": {"status": "m4b_ready", "output_file": str(output_dir / "book.m4b")},
        "audiobookshelf_import": {"status": "waiting_for_m4b"},
    }
    (job_dir / "job.json").write_text(json.dumps(job_payload), encoding="utf-8")
    (private_dir / "private.json").write_text(
        json.dumps(
            {
                "contract_name": "ea.telegram_epub_audiobook_voice_audition.v1",
                "candidates": {
                    "new-token": {
                        "candidate_key": "new-voice",
                        "voice_id": "new-secret-voice",
                        "public": {
                            "label": "Neue Stimme",
                            "language": "de-DE",
                            "voice_id_sha256": "n" * 64,
                            "callback_token": "new-token",
                            "preset_key": "new-voice",
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "0")

    updated = apply_audiobook_voice_audition_action(callback_token="new-token", action="use")

    assert updated["status"] == "voice_selected"
    assert updated["provider"]["voice_selection"]["render_reset_for_new_voice"]["status"] == "reset"
    assert updated["render_result"]["status"] == "reset_for_new_voice"
    assert not audio_dir.exists()
    assert not output_dir.exists()
    assert "new-secret-voice" not in json.dumps(updated)


def test_epub_voice_audition_dismiss_replaces_voice_immediately(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import apply_audiobook_voice_audition_action, create_job_from_epub

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": f"voice-{index}", "label": f"Voice {index}", "language": "en-US", "tags": ["audiobook", "narration"]}
                for index in range(1, 7)
            ]
        ),
    )
    tone = tmp_path / "tone.wav"
    _write_tone_wav(tone)
    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", lambda **kwargs: (tone.read_bytes(), "audio/wav"))
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)
    epub = tmp_path / "book.epub"
    _write_minimal_epub(epub)

    job = create_job_from_epub(epub_path=epub, original_filename="book.epub", principal_id="principal-1")
    first_tokens = [row["callback_token"] for row in job["provider"]["voice_selection"]["pending_batch"]]
    job = apply_audiobook_voice_audition_action(callback_token=first_tokens[0], action="dismiss")

    assert job["provider"]["voice_selection"]["last_action"]["batch_advanced"] is True
    assert job["provider"]["voice_selection"]["last_action"]["status"] == "replacement_ready"
    assert job["provider"]["voice_selection"]["last_action"]["replacement_count"] == 1
    labels = [row["label"] for row in job["provider"]["voice_selection"]["pending_batch"]]
    assert labels == ["Voice 2", "Voice 3", "Voice 4"]

    job = apply_audiobook_voice_audition_action(callback_token=first_tokens[1], action="dismiss")
    labels = [row["label"] for row in job["provider"]["voice_selection"]["pending_batch"]]
    assert labels == ["Voice 3", "Voice 4", "Voice 5"]


def test_epub_voice_audition_dismiss_survives_replacement_tts_failure(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import apply_audiobook_voice_audition_action, create_job_from_epub

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": f"voice-{index}", "label": f"Voice {index}", "language": "en-US", "tags": ["audiobook", "narration"]}
                for index in range(1, 7)
            ]
        ),
    )
    tone = tmp_path / "tone.wav"
    _write_tone_wav(tone)
    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", lambda **kwargs: (tone.read_bytes(), "audio/wav"))
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)
    epub = tmp_path / "book.epub"
    _write_minimal_epub(epub)

    job = create_job_from_epub(epub_path=epub, original_filename="book.epub", principal_id="principal-1")
    first_tokens = [row["callback_token"] for row in job["provider"]["voice_selection"]["pending_batch"]]
    monkeypatch.setattr(
        pipeline,
        "unmixr_synthesize_request",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("unmixr_tts_no_audio_url")),
    )

    job = apply_audiobook_voice_audition_action(callback_token=first_tokens[0], action="dismiss")

    selection = job["provider"]["voice_selection"]
    labels = [row["label"] for row in selection["pending_batch"]]
    assert labels == ["Voice 2", "Voice 3"]
    assert selection["last_action"]["status"] == "replacement_failed"
    assert selection["sample_generation_failed_count"] >= 1
    assert selection["underfilled_reason"] == "voice_sample_generation_failed_after_dismissal"


def test_epub_voice_audition_refreshes_voice_discovery_when_no_replacement_available(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import apply_audiobook_voice_audition_action, create_job_from_epub

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_TARGET_COUNT", "6")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_VOICE_DISCOVERY_USE_CASES", "audiobook-voices")
    monkeypatch.setenv("UNMIXR_API_KEY", "test-api-key")
    monkeypatch.delenv("EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON", raising=False)
    monkeypatch.delenv("EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_PATH", raising=False)
    monkeypatch.delenv("UNMIXR_VOICE_ID", raising=False)

    pipeline._VOICE_DISCOVERY_CACHE.clear()
    discover_calls = {"count": 0}

    class FakeResponse:
        def __init__(self, payload: dict[str, object]):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps(self.payload).encode("utf-8")

    def _fake_discovery_payload(total: int) -> dict[str, object]:
        return {
            "count": total,
            "results": [
                {
                    "uuid": f"discovered-{index}",
                    "character": f"Discovered Voice {index}",
                    "language": "en-US",
                    "quality": "Premium",
                    "capabilities": ["speech"],
                    "use_cases": ["Audiobook", "Narration"],
                    "supported_locales": {"en-US": "https://example.test/en.mp3"},
                    "is_available": True,
                    "description": "Warm clear audiobook storytelling voice.",
                    "personality": ["Warm", "Calm"],
                }
                for index in range(1, total + 1)
            ],
        }

    def fake_urlopen(request, timeout=None):
        discover_calls["count"] += 1
        if discover_calls["count"] == 1:
            payload = _fake_discovery_payload(3)
        else:
            payload = _fake_discovery_payload(6)
        return FakeResponse(payload)

    monkeypatch.setattr(pipeline.urllib.request, "urlopen", fake_urlopen)
    tone = tmp_path / "tone.wav"
    _write_tone_wav(tone)
    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", lambda **kwargs: (tone.read_bytes(), "audio/wav"))
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)
    epub = tmp_path / "book.epub"
    _write_minimal_epub(epub)

    job = create_job_from_epub(epub_path=epub, original_filename="book.epub", principal_id="principal-1")
    first_tokens = [row["callback_token"] for row in job["provider"]["voice_selection"]["pending_batch"]]
    job = apply_audiobook_voice_audition_action(callback_token=first_tokens[0], action="dismiss")

    labels = [row["label"] for row in job["provider"]["voice_selection"]["pending_batch"]]
    assert labels == ["Discovered Voice 2", "Discovered Voice 3", "Discovered Voice 4"]
    assert job["provider"]["voice_selection"]["last_action"]["replacement_count"] == 1
    assert discover_calls["count"] >= 2


def test_epub_voice_audition_exhausts_small_catalog_instead_of_recycling_dismissed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import apply_audiobook_voice_audition_action, create_job_from_epub

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": f"voice-{index}", "label": f"Voice {index}", "language": "en-US", "tags": ["audiobook", "narration"]}
                for index in range(1, 4)
            ]
        ),
    )
    tone = tmp_path / "tone.wav"
    _write_tone_wav(tone)
    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", lambda **kwargs: (tone.read_bytes(), "audio/wav"))
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)

    epub = tmp_path / "book.epub"
    _write_minimal_epub(epub)
    job = create_job_from_epub(epub_path=epub, original_filename="book.epub", principal_id="principal-1")

    for _ in range(3):
        token = str(job["provider"]["voice_selection"]["pending_batch"][0]["callback_token"])
        job = apply_audiobook_voice_audition_action(callback_token=token, action="dismiss")

    selection = job["provider"]["voice_selection"]
    assert job["status"] == "voice_selection_exhausted"
    assert selection["status"] == "exhausted"
    assert selection["reason"] == "voice_catalog_exhausted"
    assert selection["pending_batch"] == []
    assert selection["pending_candidate_keys"] == []
    assert selection["dismissed_candidate_keys"] == ["voice_01", "voice_02", "voice_03"]


def test_epub_voice_audition_expands_discovery_target_on_refill(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import apply_audiobook_voice_audition_action, create_job_from_epub

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_TARGET_COUNT", "3")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_VOICE_DISCOVERY_USE_CASES", "audiobook-voices")
    monkeypatch.setenv("UNMIXR_API_KEY", "test-api-key")
    monkeypatch.delenv("EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON", raising=False)
    monkeypatch.delenv("EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_PATH", raising=False)
    monkeypatch.delenv("UNMIXR_VOICE_ID", raising=False)

    pipeline._VOICE_DISCOVERY_CACHE.clear()
    discover_calls = {"count": 0}

    class FakeResponse:
        def __init__(self, payload: dict[str, object]):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps(self.payload).encode("utf-8")

    def _fake_discovery_payload(total: int) -> dict[str, object]:
        return {
            "count": total,
            "results": [
                {
                    "uuid": f"discovered-{index}",
                    "character": f"Discovered Voice {index}",
                    "language": "en-US",
                    "quality": "Premium",
                    "capabilities": ["speech"],
                    "use_cases": ["Audiobook", "Narration"],
                    "supported_locales": {"en-US": "https://example.test/en.mp3"},
                    "is_available": True,
                    "description": "Warm clear audiobook storytelling voice.",
                    "personality": ["Warm", "Calm"],
                }
                for index in range(1, total + 1)
            ],
        }

    def fake_urlopen(request, timeout=None):
        discover_calls["count"] += 1
        if discover_calls["count"] == 1:
            return FakeResponse(_fake_discovery_payload(3))
        return FakeResponse(_fake_discovery_payload(6))

    monkeypatch.setattr(pipeline.urllib.request, "urlopen", fake_urlopen)
    tone = tmp_path / "tone.wav"
    _write_tone_wav(tone)
    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", lambda **kwargs: (tone.read_bytes(), "audio/wav"))
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)
    epub = tmp_path / "book.epub"
    _write_minimal_epub(epub)

    job = create_job_from_epub(epub_path=epub, original_filename="book.epub", principal_id="principal-1")
    assert len(job["provider"]["voice_selection"]["pending_batch"]) == 3
    first_tokens = [row["callback_token"] for row in job["provider"]["voice_selection"]["pending_batch"]]
    job = apply_audiobook_voice_audition_action(callback_token=first_tokens[0], action="dismiss")

    labels = [row["label"] for row in job["provider"]["voice_selection"]["pending_batch"]]
    assert labels == ["Discovered Voice 2", "Discovered Voice 3", "Discovered Voice 4"]
    assert job["provider"]["voice_selection"]["last_action"]["replacement_count"] == 1
    assert discover_calls["count"] >= 2


def test_telegram_epub_voice_dismiss_sends_replacement_sample_immediately(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.api.routes import channels
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import create_job_from_epub
    from app.services.telegram_session_service import TelegramTurnContext

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_TELEGRAM_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": f"voice-{index}", "label": f"Voice {index}", "language": "en-US", "tags": ["audiobook", "narration"]}
                for index in range(1, 7)
            ]
        ),
    )
    tone = tmp_path / "tone.wav"
    _write_tone_wav(tone)
    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", lambda **kwargs: (tone.read_bytes(), "audio/wav"))
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)
    epub = tmp_path / "book.epub"
    _write_minimal_epub(epub)

    job = create_job_from_epub(epub_path=epub, original_filename="book.epub", principal_id="principal-1", chat_id="42")
    first_tokens = [row["callback_token"] for row in job["provider"]["voice_selection"]["pending_batch"]]
    sent_batches: list[list[str]] = []

    def fake_send_samples(*, bot_config, chat_id, job):
        labels = [row["label"] for row in job["provider"]["voice_selection"]["pending_batch"]]
        sent_batches.append(labels)
        return [{"token": row["callback_token"], "status": "sent"} for row in job["provider"]["voice_selection"]["pending_batch"]]

    monkeypatch.setattr(channels, "_telegram_send_audiobook_voice_samples", fake_send_samples)

    def decision_for(token: str):
        callback_data = channels._telegram_encode_audiobook_voice_callback(
            bot_config={"token": "bot-token", "secret": "callback-secret"},
            action="d",
            token=token,
            chat_id="42",
        )
        ctx = TelegramTurnContext(
            container=object(),
            principal_id="principal-1",
            text="",
            payload={
                "kind": "callback_query",
                "callback_data": callback_data,
                "_bot_config": {"token": "bot-token", "secret": "callback-secret"},
            },
            bot_handle="",
            preferred_onemin_labels=(),
            current_message_id="7",
            chat_id="42",
            normalized="",
            lower="",
            alpha_words=(),
            is_completion_cue=False,
        )
        return channels._telegram_callback_turn_decision(ctx)

    first = decision_for(first_tokens[0])
    second = decision_for(first_tokens[1])

    assert "replacement audiobook voice sample" in first.reply_text
    assert "replacement audiobook voice sample" in second.reply_text
    assert sent_batches == [["Voice 4"], ["Voice 5"]]


def test_voice_audition_refill_drops_local_piper_when_replacement_offer_disabled(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import create_job_from_epub, prepare_audiobook_voice_audition, telegram_epub_reply_text

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.delenv("EA_AUDIOBOOK_OFFER_LOCAL_PIPER_REPLACEMENT_ON_PROVIDER_BALANCE", raising=False)
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": f"voice-{index}", "label": f"Voice {index}", "language": "en-US", "tags": ["audiobook", "narration"]}
                for index in range(1, 6)
            ]
        ),
    )
    tone = tmp_path / "tone.wav"
    _write_tone_wav(tone)
    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", lambda **kwargs: (tone.read_bytes(), "audio/wav"))
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)
    epub = tmp_path / "book.epub"
    _write_minimal_epub(epub)

    job = create_job_from_epub(epub_path=epub, original_filename="book.epub", principal_id="principal-1")
    job_dir = Path(job["storage"]["job_dir"])
    selection = dict(job["provider"]["voice_selection"])
    kept = dict(selection["pending_batch"][0])
    piper = {
        "provider": "piper_local_fast",
        "preset_key": "piper_local_fast_high",
        "label": "Piper German Thorsten high",
        "language": "en-US",
        "supported_languages": ["en-US"],
        "callback_token": "piper-token",
        "sample_file": "piper-token.wav",
        "sample_audio_ready": True,
        "voice_id_sha256": "p" * 64,
    }
    selection["pending_candidate_keys"] = ["piper_local_fast_high", kept["preset_key"]]
    selection["pending_batch"] = [piper, kept]
    job["provider"]["voice_selection"] = selection
    pipeline._write_job(job_dir, job)

    updated = prepare_audiobook_voice_audition(job_dir=job_dir, batch_size=3, refill_pending=True)

    pending = updated["provider"]["voice_selection"]["pending_batch"]
    assert len(pending) == 3
    assert all(row.get("provider") != "piper_local_fast" for row in pending)
    assert "piper_local_fast_high" not in updated["provider"]["voice_selection"]["pending_candidate_keys"]


def test_voice_audition_underfilled_after_dismissals_is_explicit(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import create_job_from_epub, prepare_audiobook_voice_audition, telegram_epub_reply_text

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": "voice-one", "label": "Voice One", "language": "en-US", "supported_languages": ["en-US"], "tags": ["audiobook", "narration"]},
                {"voice_id": "voice-two", "label": "Voice Two", "language": "en-US", "supported_languages": ["en-US"], "tags": ["audiobook", "narration"]},
                {"voice_id": "voice-three", "label": "Voice Three", "language": "en-US", "supported_languages": ["en-US"], "tags": ["audiobook", "narration"]},
            ]
        ),
    )
    tone = tmp_path / "tone.wav"
    _write_tone_wav(tone)
    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", lambda **kwargs: (tone.read_bytes(), "audio/wav"))
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)
    epub = tmp_path / "book.epub"
    _write_minimal_epub(epub)

    job = create_job_from_epub(epub_path=epub, original_filename="book.epub", principal_id="principal-1")
    job_dir = Path(job["storage"]["job_dir"])
    selection = dict(job["provider"]["voice_selection"])
    rows = list(selection["pending_batch"])
    selection["dismissed_candidate_keys"] = [rows[0]["preset_key"], rows[1]["preset_key"]]
    selection["pending_candidate_keys"] = [rows[2]["preset_key"]]
    selection["pending_batch"] = [rows[2]]
    job["provider"]["voice_selection"] = selection
    job["render_result"] = {
        "status": "waiting_voice_selection",
        "reason": "selected_voice_provider_balance_blocked",
        "voice_selection": {
            "status": "waiting_user_choice",
            "pending_candidate_keys": ["piper_local_fast_high"],
            "pending_batch": [{"provider": "piper_local_fast", "preset_key": "piper_local_fast_high"}],
        },
    }
    pipeline._write_job(job_dir, job)

    updated = prepare_audiobook_voice_audition(job_dir=job_dir, batch_size=3, refill_pending=True)

    voice_selection = updated["provider"]["voice_selection"]
    assert voice_selection["underfilled"] is True
    assert voice_selection["underfilled_reason"] == "voice_catalog_underfilled_after_dismissals"
    assert voice_selection["batch_size"] == 1
    reply = telegram_epub_reply_text(updated)
    assert "1 language-matched voice sample remains after your dismissals" in reply
    assert "3 short voice samples" not in reply
    render_selection = updated["render_result"]["voice_selection"]
    assert "piper_local_fast_high" not in render_selection["pending_candidate_keys"]
    assert all(row.get("provider") != "piper_local_fast" for row in render_selection["pending_batch"])


def test_voice_audition_refill_relaxes_language_after_all_language_matches_dismissed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import create_job_from_epub, prepare_audiobook_voice_audition

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": "voice-one", "label": "Voice One", "language": "en-US", "supported_languages": ["en-US"], "tags": ["audiobook", "narration"]},
                {"voice_id": "voice-two", "label": "Voice Two", "language": "en-US", "supported_languages": ["en-US"], "tags": ["audiobook", "narration"]},
                {"voice_id": "voice-three", "label": "Voice Three", "language": "en-US", "supported_languages": ["en-US"], "tags": ["audiobook", "narration"]},
                {"voice_id": "voice-four", "label": "Voice Four", "language": "fr-FR", "supported_languages": ["fr-FR"], "tags": ["audiobook", "narration"]},
                {"voice_id": "voice-five", "label": "Voice Five", "language": "fr-FR", "supported_languages": ["fr-FR"], "tags": ["audiobook", "narration"]},
                {"voice_id": "voice-six", "label": "Voice Six", "language": "fr-FR", "supported_languages": ["fr-FR"], "tags": ["audiobook", "narration"]},
            ]
        ),
    )
    tone = tmp_path / "tone.wav"
    _write_tone_wav(tone)
    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", lambda **kwargs: (tone.read_bytes(), "audio/wav"))
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)
    epub = tmp_path / "book.epub"
    _write_minimal_epub(epub)

    job = create_job_from_epub(epub_path=epub, original_filename="book.epub", principal_id="principal-1")
    job_dir = Path(job["storage"]["job_dir"])
    selection = dict(job["provider"]["voice_selection"])
    rows = list(selection["pending_batch"])
    selection["dismissed_candidate_keys"] = [str(row["preset_key"]) for row in rows]
    selection["pending_candidate_keys"] = []
    selection["pending_batch"] = []
    job["provider"]["voice_selection"] = selection
    pipeline._write_job(job_dir, job)

    updated = prepare_audiobook_voice_audition(job_dir=job_dir, batch_size=3, refill_pending=True)

    voice_selection = updated["provider"]["voice_selection"]
    assert voice_selection["status"] == "waiting_user_choice"
    assert voice_selection["language_relaxed_after_dismissals"] is True
    assert voice_selection["underfilled_reason"] == "voice_catalog_language_relaxed_after_dismissals"
    assert [row["label"] for row in voice_selection["pending_batch"]] == ["Voice Four", "Voice Five", "Voice Six"]


def test_voice_sample_delivery_summary_prevents_false_sent_reply(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import (
        build_audiobook_job_receipt,
        create_job_from_epub,
        record_audiobook_voice_sample_delivery,
        telegram_epub_reply_text,
    )

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": f"voice-{index}", "label": f"Voice {index}", "language": "en-US", "tags": ["audiobook", "narration"]}
                for index in range(1, 4)
            ]
        ),
    )
    tone = tmp_path / "tone.wav"
    _write_tone_wav(tone)
    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", lambda **kwargs: (tone.read_bytes(), "audio/wav"))
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)
    epub = tmp_path / "book.epub"
    _write_minimal_epub(epub)

    job = create_job_from_epub(epub_path=epub, original_filename="book.epub", principal_id="principal-1", chat_id="42")
    skipped_receipts = [
        {"token": row["callback_token"], "status": "skipped", "reason": "telegram_audio_send_skipped"}
        for row in job["provider"]["voice_selection"]["pending_batch"]
    ]

    updated = record_audiobook_voice_sample_delivery(job=job, sample_receipts=skipped_receipts)
    reply = telegram_epub_reply_text(updated)
    receipt = build_audiobook_job_receipt(job_dir=Path(updated["storage"]["job_dir"]))

    assert "I prepared 3 short voice samples" in reply
    assert "Telegram could not deliver them" in reply
    assert "I sent 3 short voice samples" not in reply
    assert receipt["telegram"]["voice_sample_delivery_status"] == "failed"
    assert receipt["telegram"]["voice_sample_delivery_expected_count"] == 3
    assert receipt["telegram"]["voice_sample_delivery_sent_count"] == 0
    assert receipt["telegram"]["voice_sample_delivery_skipped_count"] == 3
    assert receipt["telegram"]["voice_sample_callback_tokens_exposed"] is False


def test_telegram_send_audiobook_voice_samples_returns_per_sample_failures(monkeypatch, tmp_path: Path) -> None:
    from app.api.routes import channels
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import create_job_from_epub

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": f"voice-{index}", "label": f"Voice {index}", "language": "en-US", "tags": ["audiobook", "narration"]}
                for index in range(1, 4)
            ]
        ),
    )
    tone = tmp_path / "tone.wav"
    _write_tone_wav(tone)
    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", lambda **kwargs: (tone.read_bytes(), "audio/wav"))
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)
    monkeypatch.setattr(channels, "_telegram_send_audio", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("telegram_audio_failed")))
    epub = tmp_path / "book.epub"
    _write_minimal_epub(epub)
    job = create_job_from_epub(epub_path=epub, original_filename="book.epub", principal_id="principal-1", chat_id="42")

    receipts = channels._telegram_send_audiobook_voice_samples(
        bot_config={"token": "bot-token", "secret": "callback-secret"},
        chat_id="42",
        job=job,
    )

    assert len(receipts) == 3
    assert {row["status"] for row in receipts} == {"failed"}
    assert {row["reason"] for row in receipts} == {"RuntimeError"}


def test_epub_cover_is_extracted_and_passed_to_m4b_tool(monkeypatch, tmp_path: Path) -> None:
    from app.services.audiobook_epub_pipeline import create_job_from_epub

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "0")
    monkeypatch.setenv("EA_M4B_TOOL_BIN", "definitely-missing-m4b-tool")
    epub = tmp_path / "covered.epub"
    _write_epub_with_cover(epub)

    job = create_job_from_epub(epub_path=epub, original_filename="covered.epub", principal_id="principal-1")

    cover_path = Path(job["metadata"]["cover_image_path"])
    assert cover_path.is_file()
    command = job["merge_result"]["command"]
    assert "--cover" in command
    assert str(cover_path) in command


def test_continue_job_backfills_epub_cover_for_existing_job(monkeypatch, tmp_path: Path) -> None:
    from app.services.audiobook_epub_pipeline import continue_job, create_job_from_epub

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "0")
    monkeypatch.setenv("EA_M4B_TOOL_BIN", "definitely-missing-m4b-tool")
    epub = tmp_path / "covered.epub"
    _write_epub_with_cover(epub)
    job = create_job_from_epub(epub_path=epub, original_filename="covered.epub", principal_id="principal-1")
    job_dir = Path(job["storage"]["job_dir"])
    original_cover = Path(job["metadata"]["cover_image_path"])
    original_cover.unlink()
    job["metadata"].pop("cover_image_path", None)
    job["metadata"].pop("cover_media_type", None)
    (job_dir / "job.json").write_text(json.dumps(job, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    resumed = continue_job(job_dir)

    cover_path = Path(resumed["metadata"]["cover_image_path"])
    assert cover_path.is_file()
    assert resumed["metadata"]["cover_media_type"] == "image/jpeg"
    command = resumed["merge_result"]["command"]
    assert "--cover" in command
    assert str(cover_path) in command


def test_audiobook_runtime_preflight_passes_with_ffmpeg_fallback_without_secret_leaks(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_TELEGRAM_AUDIOBOOK_EPUB_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_DEFAULT_VOICE_LABEL", "German narrator")
    monkeypatch.setenv("EA_AUDIOBOOK_DEFAULT_VOICE_LANGUAGE", "de")
    monkeypatch.setenv("EA_AUDIOBOOK_DEFAULT_VOICE_TAGS", "audiobook,narration,german,clear")
    monkeypatch.setenv("UNMIXR_API_KEY", "raw-primary-unmixr-key")
    monkeypatch.setenv("UNMIXR_API_KEY_FALLBACK_1", "raw-fallback-unmixr-key")
    monkeypatch.setenv("UNMIXR_VOICE_ID", "raw-secret-voice-id")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": "voice-preflight-1", "label": "German narrator", "language": "de", "tags": ["audiobook", "narration", "german", "clear"]},
                {"voice_id": "voice-preflight-2", "label": "Warm German narrator", "language": "de", "tags": ["audiobook", "narration", "german", "warm"]},
                {"voice_id": "voice-preflight-3", "label": "Calm German narrator", "language": "de", "tags": ["audiobook", "narration", "german", "calm"]},
            ]
        ),
    )
    monkeypatch.setenv("EA_AUDIOBOOK_M4B_AUTO_MERGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_FFMPEG_M4B_FALLBACK", "1")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_AUTO_IMPORT", "1")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_IMPORT_ROOT", str(tmp_path / "audiobookshelf"))
    monkeypatch.setenv("EA_AUDIOBOOK_ACCESS_SIGNING_SECRET", "raw-signing-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_PLAYER_ACCESS_BASE_URL", "https://ea.example.com")
    monkeypatch.setenv("EA_SCHEDULER_AUDIOBOOK_RESUME_ENABLED", "1")
    monkeypatch.setenv("EA_SCHEDULER_AUDIOBOOK_RESUME_INTERVAL_SECONDS", "300")

    def fake_which(binary: str) -> str | None:
        if binary in {"ffmpeg", "ffprobe"}:
            return f"/usr/bin/{binary}"
        return None

    monkeypatch.setattr(pipeline.shutil, "which", fake_which)

    receipt = pipeline.audiobook_runtime_preflight()
    rendered = json.dumps(receipt, sort_keys=True)

    assert receipt["contract_name"] == "ea.telegram_epub_audiobook_runtime_preflight.v1"
    assert receipt["status"] == "pass"
    assert receipt["assembly"]["m4b_tool_available"] is False
    assert receipt["assembly"]["ffmpeg_m4b_fallback_available"] is True
    assert receipt["assembly"]["m4b_assembly_available"] is True
    assert receipt["access"]["player_access_signing_secret_present"] is True
    assert receipt["provider"]["api_key_slot_count"] == 2
    assert receipt["scheduler"]["priority_source_kinds"] == ["origin_dossier_story", "origin_dossier"]
    assert receipt["scheduler"]["resume_order"] == ("priority_source", "retry_at", "job_dir_name")
    assert receipt["provider"]["voice_catalog"][0]["language"] == "de"
    assert receipt["provider"]["raw_voice_ids_exposed"] is False
    assert receipt["access"]["tokens_exposed"] is False
    assert "raw-secret-voice-id" not in rendered
    assert "raw-primary-unmixr-key" not in rendered
    assert "raw-fallback-unmixr-key" not in rendered
    assert "raw-signing-secret" not in rendered
    assert str(tmp_path) not in rendered


def test_audiobook_runtime_preflight_keeps_optional_player_access_base_url_and_bulk_pacing_as_warnings(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_TELEGRAM_AUDIOBOOK_EPUB_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_MAX_SEGMENTS_PER_RUN", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_DEFAULT_VOICE_LABEL", "German narrator")
    monkeypatch.setenv("EA_AUDIOBOOK_DEFAULT_VOICE_LANGUAGE", "de")
    monkeypatch.setenv("EA_AUDIOBOOK_DEFAULT_VOICE_TAGS", "audiobook,narration,german,clear")
    monkeypatch.setenv("UNMIXR_API_KEY", "raw-primary-unmixr-key")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": f"voice-preflight-{index}", "label": f"Voice {index}", "language": "de", "tags": ["audiobook", "narration", "german"]}
                for index in range(1, 4)
            ]
        ),
    )
    monkeypatch.setenv("EA_AUDIOBOOK_M4B_AUTO_MERGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_FFMPEG_M4B_FALLBACK", "1")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_AUTO_IMPORT", "1")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_PUBLIC_SHARE_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_IMPORT_ROOT", str(tmp_path / "audiobookshelf"))
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_API_BASE_URL", "https://abs.internal")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_PUBLIC_BASE_URL", "https://abs.example.com")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_API_TOKEN", "fake-abs-token")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_LIBRARY_ID", "library-1")
    monkeypatch.setenv("EA_AUDIOBOOK_ACCESS_SIGNING_SECRET", "raw-signing-secret")
    monkeypatch.delenv("EA_AUDIOBOOK_PLAYER_ACCESS_BASE_URL", raising=False)

    def fake_which(binary: str) -> str | None:
        if binary in {"ffmpeg", "ffprobe"}:
            return f"/usr/bin/{binary}"
        return None

    monkeypatch.setattr(pipeline.shutil, "which", fake_which)

    receipt = pipeline.audiobook_runtime_preflight()

    assert receipt["status"] == "warn"
    assert receipt["failed_checks"] == []
    assert sorted(receipt["warned_checks"]) == [
        "player_access_base_url_present",
        "unmixr_bulk_pacing_configured",
    ]
    assert receipt["access"]["player_access_base_url_present"] is False
    assert receipt["provider"]["bulk_pacing"]["max_segments_per_run"] == 0


def test_unmixr_short_tts_uses_fallback_api_key_after_throttle(monkeypatch, tmp_path: Path) -> None:
    from app.services import memorial_openvoice

    for name in list(os.environ):
        if name.startswith("UNMIXR_API_KEY_FALLBACK_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("UNMIXR_API_KEYS", raising=False)
    monkeypatch.setenv("EA_UNMIXR_SLOT_SELECTOR_STATE_FILE", str(tmp_path / "unmixr-slots.json"))
    monkeypatch.setenv("UNMIXR_API_KEY", "primary-key")
    monkeypatch.setenv("UNMIXR_API_KEY_FALLBACK_1", "fallback-key")
    seen_auth: list[str] = []

    class FakeResponse:
        def __init__(self, *, status_code: int, payload: dict[str, object] | None = None, content: bytes = b"", headers: dict[str, str] | None = None):
            self.status_code = status_code
            self._payload = payload or {}
            self.content = content
            self.headers = headers or {}
            self.ok = status_code < 400

        def json(self):
            return self._payload

    def fake_request(*, method, url, headers, json=None, files=None, data=None, timeout=None):
        seen_auth.append(str(headers.get("Authorization") or ""))
        if len(seen_auth) == 1:
            return FakeResponse(status_code=429, payload={"detail": "Request was throttled. Expected available in 3600 seconds."})
        return FakeResponse(status_code=200, payload={"audio_url": "https://audio.example.test/render.wav"})

    def fake_get(url, timeout=None):
        return FakeResponse(status_code=200, content=b"RIFF....WAVE", headers={"Content-Type": "audio/wav"})

    monkeypatch.setattr(memorial_openvoice.requests, "request", fake_request)
    monkeypatch.setattr(memorial_openvoice.requests, "get", fake_get)

    audio, content_type = memorial_openvoice.unmixr_synthesize_request(
        text="Hello",
        voice_id="voice-1",
        lang="en-US",
    )

    assert audio == b"RIFF....WAVE"
    assert content_type == "audio/wav"
    assert seen_auth == ["Bearer primary-key", "Bearer fallback-key"]


def test_unmixr_render_retries_transient_missing_audio_url(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import EpubChapter, EpubMetadata, render_unmixr_chapter_audio

    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_RETRY_COUNT", "2")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_RETRY_BACKOFF_SECONDS", "0")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps([{"voice_id": "voice-1", "label": "Narrator", "language": "de", "tags": ["audiobook", "narration", "clear"], "default": True}]),
    )
    chapter_dir = tmp_path / "chapters"
    chapter_dir.mkdir()
    text = "Ein kurzer deutscher Testabschnitt fuer die robuste TTS-Ausgabe."
    (chapter_dir / "001 - Test.txt").write_text(text, encoding="utf-8")
    chapter = EpubChapter(index=1, title="Test", source_href="test.xhtml", text_path="001 - Test.txt", audio_filename="001 - Test.wav", char_count=len(text), sha256="sha")
    metadata = EpubMetadata(title="Test Book", author="A. Writer", language="de", source_filename="book.epub", source_sha256="sha")
    tone = tmp_path / "tone.wav"
    _write_tone_wav(tone)
    calls = {"count": 0}

    def fake_synthesize_request(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise HTTPException(status_code=502, detail="unmixr_tts_no_audio_url")
        return tone.read_bytes(), "audio/wav"

    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", fake_synthesize_request)

    result = render_unmixr_chapter_audio(job_dir=tmp_path, chapters=(chapter,), metadata=metadata)

    assert result["status"] == "rendered"
    assert calls["count"] == 2
    assert result["chapters"][0]["retry_errors"] == ["attempt_1:unmixr_tts_no_audio_url"]
    assert (tmp_path / "audio" / "001 - Test.wav").is_file()


def test_unmixr_balance_blocker_does_not_publish_replacement_voice_without_selection(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import EpubChapter, EpubMetadata, render_unmixr_chapter_audio

    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_RETRY_COUNT", "1")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {
                    "voice_id": "voice-1",
                    "label": "Seraphina",
                    "language": "de-DE",
                    "supported_languages": ["de-DE"],
                    "tags": ["audiobook", "narration", "german"],
                    "default": True,
                }
            ]
        ),
    )
    chapter_dir = tmp_path / "chapters"
    chapter_dir.mkdir()
    text = "Ein kurzer deutscher Testabschnitt fuer die lokale Fallback-Ausgabe."
    (chapter_dir / "001 - Test.txt").write_text(text, encoding="utf-8")
    chapter = EpubChapter(
        index=1,
        title="Test",
        source_href="test.xhtml",
        text_path="001 - Test.txt",
        audio_filename="001 - Test.wav",
        char_count=len(text),
        sha256="sha",
    )
    metadata = EpubMetadata(title="Test Book", author="A. Writer", language="de", source_filename="book.epub", source_sha256="sha")
    piper_calls: list[dict[str, object]] = []

    def fake_unmixr(**kwargs):
        raise HTTPException(
            status_code=502,
            detail="unmixr_tts_no_audio_url:Insufficient API balance (prebuilt characters)",
        )

    def fake_piper(**kwargs):
        piper_calls.append(dict(kwargs))
        raise AssertionError("replacement TTS must not run without an explicit voice choice")

    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", fake_unmixr)
    monkeypatch.setattr(pipeline, "piper_fast_synthesize_request", fake_piper)
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)

    result = render_unmixr_chapter_audio(job_dir=tmp_path, chapters=(chapter,), metadata=metadata)

    assert result["status"] == "blocked"
    assert result["provider"] == "unmixr"
    assert result["replacement_voice_required"] is True
    assert "local_fallback_render" not in result["voice_selection"]
    assert not piper_calls
    assert not (tmp_path / "audio" / "001 - Test.wav").exists()


def test_selected_voice_balance_blocker_ignores_removed_piper_replacement_flag(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import apply_audiobook_voice_audition_action, create_job_from_epub

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_RETRY_COUNT", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_LOCAL_PIPER_FALLBACK_ENABLED", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_OFFER_LOCAL_PIPER_REPLACEMENT_ON_PROVIDER_BALANCE", "1")
    monkeypatch.setenv("EA_M4B_TOOL_BIN", "definitely-missing-m4b-tool")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": "voice-one", "label": "Seraphina", "language": "en-US", "supported_languages": ["en-US"], "tags": ["audiobook", "narration"]},
                {"voice_id": "voice-two", "label": "Voice Two", "language": "en-US", "supported_languages": ["en-US"], "tags": ["audiobook", "narration"]},
                {"voice_id": "voice-three", "label": "Voice Three", "language": "en-US", "supported_languages": ["en-US"], "tags": ["audiobook", "narration"]},
            ]
        ),
    )
    tone = tmp_path / "tone.wav"
    _write_tone_wav(tone)
    calls = {"unmixr": 0, "piper": 0}

    def fake_unmixr(**kwargs):
        calls["unmixr"] += 1
        if calls["unmixr"] <= 3:
            return tone.read_bytes(), "audio/wav"
        raise HTTPException(
            status_code=502,
            detail="unmixr_tts_no_audio_url:Insufficient API balance (prebuilt characters)",
        )

    def fake_piper(**kwargs):
        calls["piper"] += 1
        raise AssertionError("removed Piper fallback must not render a replacement sample")

    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", fake_unmixr)
    monkeypatch.setattr(pipeline, "piper_fast_synthesize_request", fake_piper)
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)
    epub = tmp_path / "book.epub"
    _write_minimal_epub(epub)

    job = create_job_from_epub(epub_path=epub, original_filename="book.epub", principal_id="principal-1")
    chosen = next(row for row in job["provider"]["voice_selection"]["pending_batch"] if row["label"] == "Seraphina")
    updated = apply_audiobook_voice_audition_action(callback_token=chosen["callback_token"], action="use")

    selection = updated["provider"]["voice_selection"]
    assert updated["status"] == "blocked_external_tts"
    assert updated["next_action"] == "restore_selected_voice_provider_balance"
    assert selection["status"] == "selected_by_user"
    assert selection["selected"]["label"] == "Seraphina"
    assert selection["pending_batch"] == []
    assert calls["piper"] == 0
    assert not list((Path(updated["storage"]["job_dir"]) / "audio").glob("*.wav"))
    reply = pipeline.telegram_epub_reply_text(updated)
    assert "stopped instead of publishing" in reply
    assert "replacement voice sample" not in reply


def test_selected_voice_balance_blocker_without_replacement_offer_keeps_selected_voice(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import apply_audiobook_voice_audition_action, create_job_from_epub

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_RETRY_COUNT", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_LOCAL_PIPER_FALLBACK_ENABLED", "0")
    monkeypatch.delenv("EA_AUDIOBOOK_OFFER_LOCAL_PIPER_REPLACEMENT_ON_PROVIDER_BALANCE", raising=False)
    monkeypatch.setenv("EA_M4B_TOOL_BIN", "definitely-missing-m4b-tool")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": "voice-one", "label": "Seraphina", "language": "en-US", "supported_languages": ["en-US"], "tags": ["audiobook", "narration"]},
                {"voice_id": "voice-two", "label": "Voice Two", "language": "en-US", "supported_languages": ["en-US"], "tags": ["audiobook", "narration"]},
                {"voice_id": "voice-three", "label": "Voice Three", "language": "en-US", "supported_languages": ["en-US"], "tags": ["audiobook", "narration"]},
            ]
        ),
    )
    tone = tmp_path / "tone.wav"
    _write_tone_wav(tone)
    calls = {"unmixr": 0, "piper": 0}

    def fake_unmixr(**kwargs):
        calls["unmixr"] += 1
        if calls["unmixr"] <= 3:
            return tone.read_bytes(), "audio/wav"
        raise HTTPException(
            status_code=502,
            detail="unmixr_tts_no_audio_url:Insufficient API balance (prebuilt characters)",
        )

    def fake_piper(**kwargs):
        calls["piper"] += 1
        raise AssertionError("Piper replacement must stay disabled by default")

    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", fake_unmixr)
    monkeypatch.setattr(pipeline, "piper_fast_synthesize_request", fake_piper)
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)
    epub = tmp_path / "book.epub"
    _write_minimal_epub(epub)

    job = create_job_from_epub(epub_path=epub, original_filename="book.epub", principal_id="principal-1")
    chosen = next(row for row in job["provider"]["voice_selection"]["pending_batch"] if row["label"] == "Seraphina")
    updated = apply_audiobook_voice_audition_action(callback_token=chosen["callback_token"], action="use")

    selection = updated["provider"]["voice_selection"]
    assert updated["status"] == "blocked_external_tts"
    assert updated["next_action"] == "restore_selected_voice_provider_balance"
    assert selection["status"] == "selected_by_user"
    assert selection["selected"]["label"] == "Seraphina"
    assert selection["pending_batch"] == []
    assert calls["piper"] == 0
    assert not list((Path(updated["storage"]["job_dir"]) / "audio").glob("*.wav"))
    reply = pipeline.telegram_epub_reply_text(updated)
    assert "stopped instead of publishing" in reply
    assert "replacement voice sample" not in reply


def test_explicit_local_replacement_voice_is_blocked_after_user_selection(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import apply_audiobook_voice_audition_action

    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-local-replacement"
    chapter_dir = job_dir / "chapters"
    private_dir = job_dir / "voice_audition" / "samples"
    chapter_dir.mkdir(parents=True)
    private_dir.mkdir(parents=True)
    text = "This replacement voice was explicitly selected."
    (chapter_dir / "001 - Test.txt").write_text(text, encoding="utf-8")
    tone = tmp_path / "tone.wav"
    _write_tone_wav(tone)
    sample = private_dir / "local-token.wav"
    sample.write_bytes(tone.read_bytes())
    job_payload = {
        "job_id": "job-local-replacement",
        "status": "waiting_voice_selection",
        "storage": {"job_dir": str(job_dir)},
        "metadata": {"title": "Book", "author": "A. Writer", "language": "en-US", "source_filename": "book.epub"},
        "chapters": [
            {
                "index": 1,
                "title": "Test",
                "source_href": "test.xhtml",
                "text_path": "001 - Test.txt",
                "audio_filename": "001 - Test.wav",
                "char_count": len(text),
                "sha256": "c" * 64,
            }
        ],
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "reason": "selected_voice_provider_balance_blocked",
                "pending_candidate_keys": ["piper_local_fast_high"],
                "pending_batch": [
                    {
                        "provider": "piper_local_fast",
                        "preset_key": "piper_local_fast_high",
                        "label": "Piper German Thorsten high",
                        "language": "en-US",
                        "voice_id_sha256": "p" * 64,
                        "callback_token": "local-token",
                        "sample_file": sample.name,
                        "sample_audio_ready": True,
                    }
                ],
            }
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job_payload), encoding="utf-8")
    (job_dir / "voice_audition" / "private.json").write_text(
        json.dumps(
            {
                "contract_name": "ea.telegram_epub_audiobook_voice_audition.v1",
                "candidates": {
                    "local-token": {
                        "candidate_key": "piper_local_fast_high",
                        "voice_id": "local:piper:high",
                        "voice_id_sha256": "p" * 64,
                        "sample_path": str(sample),
                        "public": job_payload["provider"]["voice_selection"]["pending_batch"][0],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    piper_calls: list[dict[str, object]] = []

    def fake_piper(**kwargs):
        piper_calls.append(dict(kwargs))
        raise AssertionError("removed Piper fallback must not render even from a stale active token")

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_LOCAL_PIPER_FALLBACK_ENABLED", "0")
    monkeypatch.setenv("EA_M4B_TOOL_BIN", "definitely-missing-m4b-tool")
    monkeypatch.setattr(pipeline, "piper_fast_synthesize_request", fake_piper)
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)

    updated = apply_audiobook_voice_audition_action(callback_token="local-token", action="use")

    assert updated["provider"]["voice_selection"]["selected"]["provider"] == "piper_local_fast"
    assert updated["status"] == "blocked_external_tts"
    assert updated["next_action"] == "local_piper_fallback_removed"
    assert updated["render_result"]["status"] == "blocked"
    assert updated["render_result"]["reason"] == "local_piper_fallback_removed"
    assert not piper_calls
    assert not (job_dir / "audio" / "001 - Test.wav").is_file()


def test_successful_selected_voice_render_clears_stale_replacement_blocker() -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    job = {
        "provider": {
            "voice_selection": {
                "status": "selected_by_user",
                "reason": "selected_voice_provider_balance_blocked",
                "selected_candidate_key": "unmixr_seraphina",
                "selected": {
                    "default": False,
                    "label": "Seraphina",
                    "voice_id_sha256": "v" * 64,
                },
                "pending_candidate_keys": ["piper-local"],
                "pending_batch": [{"preset_key": "piper-local"}],
                "replacement_candidate_keys": ["piper-local"],
                "last_action": {
                    "action": "offer_replacement",
                    "status": "replacement_ready",
                    "reason": "provider_balance_or_prebuilt_characters",
                    "replacement_candidate_keys": ["piper-local"],
                    "replacement_count": 1,
                },
            }
        }
    }
    render_result = {"status": "already_rendered"}

    updated = pipeline._clear_resolved_selected_voice_provider_blocker(job, render_result=render_result)

    selection = updated["provider"]["voice_selection"]
    assert "reason" not in selection
    assert selection["pending_candidate_keys"] == []
    assert selection["pending_batch"] == []
    assert selection["replacement_candidate_keys"] == []
    assert selection["last_action"]["status"] == "selected_by_user"
    assert "replacement_candidate_keys" not in selection["last_action"]
    assert selection["provider_blocker_resolved"]["status"] == "cleared_after_selected_voice_render"


def test_provider_audio_write_runs_normalization_hook(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    target = tmp_path / "sample.wav"
    normalized: list[Path] = []

    def fake_normalize(path: Path) -> Path:
        normalized.append(path)
        return path

    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", fake_normalize)

    rendered = pipeline._write_provider_audio_file(audio_bytes=b"RIFF....WAVE", content_type="audio/wav", target_wav=target)

    assert rendered == target
    assert target.is_file()
    assert normalized == [target]


def test_audio_quality_report_flags_quiet_silent_tail(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    monkeypatch.setenv("EA_AUDIOBOOK_AUDIO_QUALITY_REPORT_ENABLED", "1")
    path = tmp_path / "quiet-tail.wav"
    _write_tone_with_silent_tail_wav(path)

    report = pipeline._rendered_audio_quality_report(path)

    assert report["status"] == "warn"
    assert report["speech_energy_present"] is True
    assert report["quiet_tail"] is True
    assert report["excessive_trailing_silence"] is True
    assert "quiet_tail" in report["issues"]
    assert "trailing_silence" in report["issues"]


def test_voice_sample_audio_quality_gate_rejects_clipped_wav(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_SAMPLE_AUDIO_QUALITY_GATE_ENABLED", "1")
    path = tmp_path / "clipped.wav"
    sample_rate = 16000
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"".join(struct.pack("<h", 32767 if i % 2 else -32768) for i in range(sample_rate // 4)))

    gate = pipeline.audiobook_voice_sample_audio_quality_gate(path)

    assert gate["ok"] is False
    assert str(gate["reason"]).startswith("voice_sample_audio_quality_failed")
    assert "clipping" in gate["reason"]
    assert dict(gate["audio_quality"])["status"] == "failed"


def test_render_receipt_summarizes_quiet_tail_audio_quality(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import EpubChapter, EpubMetadata, build_audiobook_job_receipt, render_unmixr_chapter_audio

    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("UNMIXR_VOICE_ID", "voice-default")
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)
    chapter_dir = tmp_path / "chapters"
    chapter_dir.mkdir()
    text = "This chapter has a rendered ending that should not fade into silence."
    (chapter_dir / "001 - Test.txt").write_text(text, encoding="utf-8")
    chapter = EpubChapter(index=1, title="Test", source_href="test.xhtml", text_path="001 - Test.txt", audio_filename="001 - Test.wav", char_count=len(text), sha256="sha")
    metadata = EpubMetadata(title="Test Book", author="A. Writer", language="en-US", source_filename="book.epub", source_sha256="source-sha")
    tone = tmp_path / "quiet-tail-source.wav"
    _write_tone_with_silent_tail_wav(tone)
    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", lambda **kwargs: (tone.read_bytes(), "audio/wav"))

    result = render_unmixr_chapter_audio(job_dir=tmp_path, chapters=(chapter,), metadata=metadata)
    pipeline._write_job(
        tmp_path,
        {
            "job_id": "job-quiet-tail",
            "status": "blocked_m4b_assembly_missing",
            "metadata": {
                "title": metadata.title,
                "author": metadata.author,
                "language": metadata.language,
                "source_filename": metadata.source_filename,
                "source_sha256": metadata.source_sha256,
            },
            "source": {"kind": "epub", "rights_basis": "operator_supplied_epub", "source_filename": metadata.source_filename},
            "storage": {},
            "telegram": {},
            "totals": {"chapter_count": 1, "char_count": len(text)},
            "chapters": [
                {
                    "index": chapter.index,
                    "title": chapter.title,
                    "source_href": chapter.source_href,
                    "text_path": chapter.text_path,
                    "audio_filename": chapter.audio_filename,
                    "char_count": chapter.char_count,
                    "sha256": chapter.sha256,
                }
            ],
            "provider": {"preferred": "unmixr"},
            "render_result": result,
            "merge_result": {"status": "waiting_for_m4b_assembly_tool"},
            "audiobookshelf_import": {"status": "waiting_for_m4b"},
        },
    )

    assert result["chapters"][0]["audio_quality"]["status"] == "warn"
    receipt = build_audiobook_job_receipt(job_dir=tmp_path)
    quality = receipt["render"]["audio_quality"]
    assert quality["status"] == "warn"
    assert quality["quiet_tail_count"] >= 1
    assert quality["trailing_silence_count"] >= 1
    assert quality["raw_audio_paths_exposed"] is False


def test_unmixr_provider_throttle_is_resumable_wait_state(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import create_job_from_epub, telegram_epub_reply_text

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_AUDITION_ENABLED", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_RETRY_BACKOFF_SECONDS", "0")
    monkeypatch.setenv("EA_M4B_TOOL_BIN", "definitely-missing-m4b-tool")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps([{"voice_id": "voice-1", "label": "Narrator", "language": "en-US", "tags": ["audiobook", "narration", "clear"], "default": True}]),
    )

    def throttled_synthesize_request(**kwargs):
        raise HTTPException(status_code=502, detail="Request was throttled. Expected available in 3600 seconds.:429")

    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", throttled_synthesize_request)
    epub = tmp_path / "book.epub"
    _write_minimal_epub(epub)

    job = create_job_from_epub(epub_path=epub, original_filename="book.epub", principal_id="principal-1")

    assert job["status"] == "waiting_provider_throttle"
    assert job["next_action"] == "resume_after_unmixr_throttle"
    assert job["render_result"]["provider_wait_seconds"] == 3600
    assert job["render_result"]["chapter_index"] == 1
    reply = telegram_epub_reply_text(job)
    assert "throttled" in reply
    assert "resume from there" in reply


def test_large_epub_render_pauses_before_unmixr_throttle(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import build_audiobook_job_receipt, create_job_from_text_chapters, telegram_epub_reply_text

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_MAX_CHARS_PER_REQUEST", "1000")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_MAX_SEGMENTS_PER_RUN", "2")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_PACING_WAIT_SECONDS", "600")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_BULK_PACING_CHAR_THRESHOLD", "1")
    monkeypatch.setenv("EA_M4B_TOOL_BIN", "definitely-missing-m4b-tool")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps([{"voice_id": "voice-1", "label": "Narrator", "language": "en-US", "tags": ["audiobook", "narration", "clear"], "default": True}]),
    )
    text = ("This is a long audiobook section that should be split into multiple provider calls. " * 18 + "\n\n") * 4
    tone = tmp_path / "tone.wav"
    _write_tone_wav(tone)
    calls = {"count": 0}

    def fake_synthesize_request(**kwargs):
        calls["count"] += 1
        return tone.read_bytes(), "audio/wav"

    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", fake_synthesize_request)

    job = create_job_from_text_chapters(
        title="Bulk Book",
        chapters=[{"title": "Long Chapter", "text": text}],
        principal_id="principal-1",
        source_kind="epub",
    )

    assert job["status"] == "waiting_provider_throttle"
    assert job["next_action"] == "resume_after_unmixr_pacing"
    assert job["render_result"]["status"] == "provider_pacing_wait"
    assert job["render_result"]["provider_wait_seconds"] == 600
    assert job["render_result"]["segments_rendered_this_run"] == 2
    assert calls["count"] == 2
    receipt = build_audiobook_job_receipt(job_dir=Path(job["storage"]["job_dir"]))
    assert receipt["render"]["wait_kind"] == "bulk_pacing"
    assert receipt["render"]["pacing"]["source_kind"] == "epub"
    assert receipt["scheduler_resume"]["priority_label"] == "bulk_or_standard"
    reply = telegram_epub_reply_text(job)
    assert "paused bulk audio generation" in reply
    assert "throttled the audiobook lane" not in reply
    assert "Unmixr" not in reply


def test_resume_due_audiobook_jobs_resumes_due_throttled_job(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-1"
    job_dir.mkdir(parents=True)
    retry_after = (datetime.now(UTC) - timedelta(seconds=5)).isoformat().replace("+00:00", "Z")
    job_payload = {
        "job_id": "job-1",
        "status": "waiting_provider_throttle",
        "provider": {"preferred": "unmixr_ai", "raw_book_text_leaves_ea": True},
        "render_result": {
            "status": "provider_throttled",
            "provider_retry_after": retry_after,
            "provider_wait_seconds": 1,
        },
        "telegram": {"chat_id": "42", "message_id": "7"},
        "metadata": {"title": "Test Book"},
        "totals": {"chapter_count": 1, "char_count": 1000},
        "eta": {"estimated_minutes_after_unblocked": 3},
    }
    (job_dir / "job.json").write_text(json.dumps(job_payload), encoding="utf-8")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    resumed = {**job_payload, "status": "audiobookshelf_imported", "audiobookshelf_import": {"status": "imported", "target_path": "/tmp/book.m4b"}}

    monkeypatch.setattr(pipeline, "_resume_due_job_with_external_tts_consent", lambda path: resumed)
    monkeypatch.setattr(pipeline, "_send_telegram_audiobook_status", lambda *, job, text: {"status": "sent", "message_id": 99})

    summary = pipeline.resume_due_audiobook_jobs(notify_telegram=True)

    assert summary["attempted"] == 1
    assert summary["resumed"] == 1
    assert summary["imported"] == 1
    assert summary["notifications"][0]["notification"]["status"] == "sent"
    resume_state = json.loads((job_dir / "resume_state.json").read_text(encoding="utf-8"))
    assert resume_state["status"] == "audiobookshelf_imported"


def test_resume_due_audiobook_jobs_resumes_due_pacing_wait(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-1"
    job_dir.mkdir(parents=True)
    retry_after = (datetime.now(UTC) - timedelta(seconds=5)).isoformat().replace("+00:00", "Z")
    job_payload = {
        "job_id": "job-1",
        "status": "waiting_provider_throttle",
        "provider": {"preferred": "unmixr_ai", "raw_book_text_leaves_ea": True},
        "render_result": {
            "status": "provider_pacing_wait",
            "provider_retry_after": retry_after,
            "provider_wait_seconds": 1,
        },
        "telegram": {"chat_id": "42", "message_id": "7"},
        "metadata": {"title": "Test Book"},
        "totals": {"chapter_count": 1, "char_count": 1000},
        "eta": {"estimated_minutes_after_unblocked": 3},
    }
    (job_dir / "job.json").write_text(json.dumps(job_payload), encoding="utf-8")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    resumed = {**job_payload, "status": "blocked_m4b_assembly_missing"}

    monkeypatch.setattr(pipeline, "_resume_due_job_with_external_tts_consent", lambda path: resumed)

    summary = pipeline.resume_due_audiobook_jobs(notify_telegram=False)

    assert summary["attempted"] == 1
    assert summary["resumed"] == 1
    assert summary["notifications"][0]["status"] == "blocked_m4b_assembly_missing"


def test_resume_due_audiobook_jobs_retries_due_external_tts_balance_blocker(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-balance"
    job_dir.mkdir(parents=True)
    updated_at = (datetime.now(UTC) - timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    job_payload = {
        "job_id": "job-balance",
        "status": "blocked_external_tts",
        "updated_at": updated_at,
        "provider": {"preferred": "unmixr_ai", "raw_book_text_leaves_ea": True},
        "render_result": {
            "status": "blocked",
            "reason": "unmixr_tts_no_audio_url:Insufficient API balance (prebuilt characters)",
        },
        "telegram": {"chat_id": "42", "message_id": "7"},
        "metadata": {"title": "Test Book"},
        "totals": {"chapter_count": 1, "char_count": 1000},
        "eta": {"estimated_minutes_after_unblocked": 3},
    }
    (job_dir / "job.json").write_text(json.dumps(job_payload), encoding="utf-8")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_BLOCKER_RETRY_SECONDS", "60")
    resumed = {**job_payload, "status": "waiting_provider_throttle"}

    monkeypatch.setattr(pipeline, "_resume_due_job_with_external_tts_consent", lambda path: resumed)

    summary = pipeline.resume_due_audiobook_jobs(notify_telegram=False)

    assert summary["attempted"] == 1
    assert summary["resumed"] == 1
    assert summary["notifications"][0]["status"] == "waiting_provider_throttle"
    resume_state = json.loads((job_dir / "resume_state.json").read_text(encoding="utf-8"))
    assert resume_state["status"] == "waiting_provider_throttle"


def test_resume_due_audiobook_jobs_retries_due_audio_generation_slot_cooldown(
    monkeypatch, tmp_path: Path
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-slot-cooldown"
    job_dir.mkdir(parents=True)
    updated_at = (datetime.now(UTC) - timedelta(seconds=900)).isoformat().replace("+00:00", "Z")
    job_payload = {
        "job_id": "job-slot-cooldown",
        "status": "blocked_external_tts",
        "updated_at": updated_at,
        "provider": {
            "raw_book_text_leaves_ea": True,
            "voice_selection": {
                "status": "selected_by_user",
                "selected_candidate_key": "voice-1",
                "selected": {"label": "Remy"},
            },
        },
        "render_result": {
            "status": "blocked",
            "reason": "unmixr_slots_cooling_down:887",
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job_payload), encoding="utf-8")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    resumed = {**job_payload, "status": "waiting_provider_throttle"}

    monkeypatch.setattr(pipeline, "_resume_due_job_with_external_tts_consent", lambda path: resumed)

    summary = pipeline.resume_due_audiobook_jobs(notify_telegram=False)

    assert summary["attempted"] == 1
    assert summary["resumed"] == 1
    assert summary["throttled"] == 1
    receipt = pipeline.build_audiobook_job_receipt(job_dir=job_dir)
    assert receipt["render"]["external_tts_blocker_code"] == "provider_cooling_down"
    assert receipt["render"]["external_tts_blocker_retryable"] is True


def test_resume_due_job_uses_selected_unmixr_voice_consent_without_preferred_provider(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    job_dir = tmp_path / "job-selected-unmixr"
    job_dir.mkdir()
    job_payload = {
        "job_id": "job-selected-unmixr",
        "status": "blocked_external_tts",
        "provider": {
            "raw_book_text_leaves_ea": True,
            "voice_selection": {
                "status": "selected_by_user",
                "selected_candidate_key": "unmixr_seraphina",
                "selected": {"label": "Seraphina"},
            },
        },
        "render_result": {
            "status": "blocked",
            "reason": "unmixr_tts_no_audio_url:Insufficient API balance (prebuilt characters)",
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job_payload), encoding="utf-8")
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "0")
    observed_env: dict[str, str | None] = {}

    def fake_continue(path: Path):
        observed_env["external"] = os.getenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED")
        observed_env["unmixr"] = os.getenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER")
        return {**job_payload, "status": "blocked_external_tts", "next_action": "restore_selected_voice_provider_balance"}

    monkeypatch.setattr(pipeline, "continue_job", fake_continue)

    resumed = pipeline._resume_due_job_with_external_tts_consent(job_dir)

    assert resumed["next_action"] == "restore_selected_voice_provider_balance"
    assert observed_env == {"external": "1", "unmixr": "1"}
    assert os.getenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED") == "0"
    assert os.getenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER") == "0"


def test_audiobook_job_receipt_summarizes_retryable_external_tts_balance_blocker(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services.audiobook_epub_pipeline import build_audiobook_job_receipt

    job_dir = tmp_path / "job-balance-receipt"
    job_dir.mkdir()
    updated_at = "2026-06-20T09:07:55Z"
    job_payload = {
        "job_id": "job-balance-receipt",
        "status": "blocked_external_tts",
        "updated_at": updated_at,
        "metadata": {"title": "Test Book", "author": "A. Writer", "language": "en-US"},
        "source": {"kind": "epub", "source_sha256": "s" * 64, "source_filename": "book.epub"},
        "storage": {"job_dir": str(job_dir)},
        "provider": {"preferred": "unmixr_ai", "raw_book_text_leaves_ea": True},
        "chapters": [
            {
                "index": 1,
                "title": "Chapter",
                "source_href": "",
                "text_path": "001.txt",
                "audio_filename": "001.wav",
                "char_count": 100,
                "sha256": "c" * 64,
            }
        ],
        "render_result": {
            "status": "blocked",
            "provider": "unmixr",
            "reason": "unmixr_tts_no_audio_url:Insufficient API balance (prebuilt characters)",
            "chapter_index": 11,
            "segment_index": 4,
            "segment_count": 13,
        },
        "merge_result": {"status": "waiting_for_unmixr_audio"},
        "audiobookshelf_import": {"status": "waiting_for_m4b"},
        "next_action": "unmixr_tts_no_audio_url:Insufficient API balance (prebuilt characters)",
    }
    (job_dir / "job.json").write_text(json.dumps(job_payload), encoding="utf-8")
    (job_dir / "chapters").mkdir()
    (job_dir / "chapters" / "001.txt").write_text("Text", encoding="utf-8")
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_BLOCKER_RETRY_SECONDS", "60")

    receipt = build_audiobook_job_receipt(job_dir=job_dir, observed_at=datetime(2026, 6, 20, 9, 8, tzinfo=UTC))

    assert receipt["render"]["external_tts_blocker_code"] == "provider_balance_or_prebuilt_characters"
    assert receipt["render"]["external_tts_blocker_retryable"] is True
    assert receipt["render"]["external_tts_blocker_reason_sha256"]
    assert receipt["scheduler_resume"]["external_tts_blocker_retryable"] is True
    assert receipt["scheduler_resume"]["external_tts_blocker_code"] == "provider_balance_or_prebuilt_characters"
    assert receipt["scheduler_resume"]["retry_after"] == "2026-06-20T09:08:55Z"
    assert "Insufficient API balance" not in json.dumps(receipt)


def test_telegram_epub_reply_sanitizes_retryable_external_tts_balance_blocker(
    monkeypatch,
) -> None:
    from app.services.audiobook_epub_pipeline import telegram_epub_reply_text

    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_BLOCKER_RETRY_SECONDS", "60")
    job = {
        "job_id": "job-balance-reply",
        "status": "blocked_external_tts",
        "updated_at": "2026-06-20T09:07:55Z",
        "metadata": {"title": "Test Book"},
        "totals": {"chapter_count": 1, "char_count": 1000},
        "eta": {"estimated_minutes_after_unblocked": 3},
        "render_result": {
            "status": "blocked",
            "reason": "unmixr_tts_no_audio_url:Insufficient API balance (prebuilt characters)",
        },
        "provider": {
            "voice_selection": {
                "selected": {"label": "Davis (Express)", "default": False},
                "status": "selected_by_user",
            }
        },
    }

    reply = telegram_epub_reply_text(job)

    assert "provider credits/balance" in reply
    assert "different voice" in reply
    assert "retry after 2026-06-20T09:08:55Z" in reply
    assert "Davis (Express)" in reply
    assert "Insufficient API balance" not in reply
    assert "prebuilt characters" not in reply
    assert "unmixr_tts_no_audio_url" not in reply


def test_selected_voice_language_mismatch_blocks_before_render(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import EpubChapter, EpubMetadata, render_unmixr_chapter_audio

    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setattr(
        pipeline,
        "unmixr_synthesize_request",
        lambda **kwargs: pytest.fail("language-mismatched selected voice must not render"),
    )
    job_dir = tmp_path / "job"
    chapter_dir = job_dir / "chapters"
    chapter_dir.mkdir(parents=True)
    text = "Dies ist ein deutsches Kapitel ueber Selbstmitgefuehl."
    (chapter_dir / "001.txt").write_text(text, encoding="utf-8")
    job_payload = {
        "job_id": "job-language-mismatch",
        "metadata": {"title": "Deutsches Buch", "author": "Andreas Knuf", "language": "de"},
        "provider": {
            "voice_selection": {
                "status": "selected_by_user",
                "selected_callback_token": "tok",
                "selected": {
                    "label": "English Voice",
                    "language": "en-US",
                    "supported_languages": ["en-US"],
                    "voice_id_sha256": "v" * 64,
                },
            }
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job_payload), encoding="utf-8")
    private_dir = job_dir / "voice_audition"
    private_dir.mkdir()
    (private_dir / "private.json").write_text(
        json.dumps(
            {
                "contract_name": "ea.telegram_epub_audiobook_voice_audition.v1",
                "selected_callback_token": "tok",
                "selected_candidate_key": "english",
                "candidates": {
                    "tok": {
                        "candidate_key": "english",
                        "voice_id": "english-voice-secret",
                        "public": job_payload["provider"]["voice_selection"]["selected"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    metadata = EpubMetadata(title="Deutsches Buch", author="Andreas Knuf", language="de", source_filename="book.epub", source_sha256="sha")
    chapter = EpubChapter(index=1, title="Test", source_href="test.xhtml", text_path="001.txt", audio_filename="001.wav", char_count=len(text), sha256="sha")

    result = render_unmixr_chapter_audio(job_dir=job_dir, chapters=(chapter,), metadata=metadata)

    assert result["status"] == "blocked"
    assert result["reason"] == "selected_voice_language_mismatch"
    assert result["voice_language_mismatch"]["book_language"] == "de"
    assert result["voice_language_mismatch"]["voice_language"] == "en-us"
    assert "english-voice-secret" not in json.dumps(result)


def test_selected_voice_language_mismatch_allows_explicit_user_override() -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import EpubMetadata

    metadata = EpubMetadata(
        title="Deutsches Buch",
        author="Andreas Knuf",
        language="de",
        source_filename="book.epub",
        source_sha256="sha",
    )
    mismatch = pipeline._selected_voice_language_mismatch(
        metadata=metadata,
        voice_selection={
            "status": "selected",
            "voice_id": "remy-secret",
            "public": {
                "status": "selected_by_user",
                "voice_language_override_by_user": True,
                "selected": {
                    "label": "Remy",
                    "language": "fr-fr",
                    "supported_languages": ["fr-fr", "en-us"],
                }
            },
        },
    )

    assert mismatch == {}


def test_continue_job_reopens_language_compatible_samples_after_selected_voice_mismatch(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import continue_job

    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_M4B_TOOL_BIN", "definitely-missing-m4b-tool")
    monkeypatch.setattr(
        pipeline,
        "unmixr_synthesize_request",
        lambda **kwargs: pytest.fail("mismatched selected voice should reopen samples before render"),
    )
    job_dir = tmp_path / "job"
    chapter_dir = job_dir / "chapters"
    sample_dir = job_dir / "voice_audition" / "samples"
    chapter_dir.mkdir(parents=True)
    sample_dir.mkdir(parents=True)
    text = "Dies ist ein deutsches Kapitel ueber Selbstmitgefuehl."
    (chapter_dir / "001.txt").write_text(text, encoding="utf-8")
    for sample in ("de.wav", "de2.wav", "en.wav"):
        _write_tone_wav(sample_dir / sample)
    selected = {
        "label": "English Voice",
        "language": "en-US",
        "supported_languages": ["en-US"],
        "voice_id_sha256": "e" * 64,
    }
    job_payload = {
        "job_id": "job-language-mismatch-reopen",
        "metadata": {"title": "Deutsches Buch", "author": "Andreas Knuf", "language": "de"},
        "chapters": [
            {
                "index": 1,
                "title": "Test",
                "source_href": "test.xhtml",
                "text_path": "001.txt",
                "audio_filename": "001.wav",
                "char_count": len(text),
                "sha256": "c" * 64,
            }
        ],
        "storage": {"job_dir": str(job_dir)},
        "provider": {
            "preferred": "unmixr_ai",
            "voice_selection": {
                "status": "selected_by_user",
                "selected_candidate_key": "english",
                "selected_callback_token": "en-token",
                "selected": selected,
            },
        },
        "totals": {"chapter_count": 1, "char_count": len(text)},
    }
    (job_dir / "job.json").write_text(json.dumps(job_payload), encoding="utf-8")
    (job_dir / "voice_audition" / "private.json").write_text(
        json.dumps(
            {
                "contract_name": "ea.telegram_epub_audiobook_voice_audition.v1",
                "selected_callback_token": "en-token",
                "selected_candidate_key": "english",
                "candidates": {
                    "de-token": {
                        "candidate_key": "german",
                        "voice_id": "de-secret",
                        "public": {
                            "label": "German Voice",
                            "language": "de-DE",
                            "supported_languages": ["de-DE", "en-US"],
                            "callback_token": "de-token",
                            "preset_key": "german",
                            "sample_file": "de.wav",
                            "sample_audio_ready": True,
                            "score": 40,
                            "voice_id_sha256": "d" * 64,
                        },
                    },
                    "de2-token": {
                        "candidate_key": "german-two",
                        "voice_id": "de2-secret",
                        "public": {
                            "label": "German Voice Two",
                            "language": "de-DE",
                            "supported_languages": ["de-DE"],
                            "callback_token": "de2-token",
                            "preset_key": "german-two",
                            "sample_file": "de2.wav",
                            "sample_audio_ready": True,
                            "score": 32,
                            "voice_id_sha256": "f" * 64,
                        },
                    },
                    "en-token": {
                        "candidate_key": "english",
                        "voice_id": "en-secret",
                        "public": {
                            **selected,
                            "callback_token": "en-token",
                            "preset_key": "english",
                            "sample_file": "en.wav",
                            "sample_audio_ready": True,
                            "score": -4,
                        },
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    updated = continue_job(job_dir)

    selection = updated["provider"]["voice_selection"]
    labels = [row["label"] for row in selection["pending_batch"]]
    assert updated["status"] == "waiting_voice_selection"
    assert updated["next_action"] == "choose_audiobook_voice"
    assert labels == ["German Voice", "German Voice Two"]
    assert selection["selected"] == {}
    assert selection["reason"] == "selected_voice_language_mismatch"
    assert "en-secret" not in json.dumps(updated)
    assert "de-secret" not in json.dumps(updated)


def test_reopened_language_mismatch_does_not_reoffer_dismissed_voice(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import reopen_audiobook_voice_selection_for_language_mismatch

    job_dir = tmp_path / "job"
    sample_dir = job_dir / "voice_audition" / "samples"
    sample_dir.mkdir(parents=True)
    for sample in ("dismissed.wav", "kept.wav"):
        _write_tone_wav(sample_dir / sample)
    job_payload = {
        "job_id": "job-reopen-dismissed",
        "metadata": {"title": "Deutsches Buch", "author": "Andreas Knuf", "language": "de"},
        "storage": {"job_dir": str(job_dir)},
        "provider": {
            "voice_selection": {
                "status": "selected_by_user",
                "selected_candidate_key": "english",
                "selected": {"label": "English Voice", "language": "en-US"},
                "dismissed_candidate_keys": ["dismissed-german"],
            }
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job_payload), encoding="utf-8")
    (job_dir / "voice_audition" / "private.json").write_text(
        json.dumps(
            {
                "contract_name": "ea.telegram_epub_audiobook_voice_audition.v1",
                "candidates": {
                    "dismissed-token": {
                        "candidate_key": "dismissed-german",
                        "voice_id": "dismissed-secret",
                        "public": {
                            "label": "Dismissed German",
                            "language": "de-DE",
                            "supported_languages": ["de-DE"],
                            "callback_token": "dismissed-token",
                            "preset_key": "dismissed-german",
                            "sample_file": "dismissed.wav",
                            "sample_audio_ready": True,
                            "score": 50,
                            "voice_id_sha256": "d" * 64,
                        },
                    },
                    "kept-token": {
                        "candidate_key": "kept-german",
                        "voice_id": "kept-secret",
                        "public": {
                            "label": "Kept German",
                            "language": "de-DE",
                            "supported_languages": ["de-DE"],
                            "callback_token": "kept-token",
                            "preset_key": "kept-german",
                            "sample_file": "kept.wav",
                            "sample_audio_ready": True,
                            "score": 40,
                            "voice_id_sha256": "k" * 64,
                        },
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    def fake_refill(*, job_dir: Path, batch_size: int = 3, refill_pending: bool = False):
        current = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
        selection = current["provider"]["voice_selection"]
        assert refill_pending is True
        assert [row["label"] for row in selection["pending_batch"]] == ["Kept German"]
        assert "dismissed-german" not in selection["pending_candidate_keys"]
        return current

    monkeypatch.setattr(pipeline, "prepare_audiobook_voice_audition", fake_refill)

    updated = reopen_audiobook_voice_selection_for_language_mismatch(job_dir=job_dir, limit=3)

    labels = [row["label"] for row in updated["provider"]["voice_selection"]["pending_batch"]]
    assert labels == ["Kept German"]
    assert updated["provider"]["voice_selection"]["dismissed_candidate_keys"] == ["dismissed-german"]
    assert "dismissed-secret" not in json.dumps(updated)
    assert "kept-secret" not in json.dumps(updated)


def test_telegram_epub_reply_for_selected_voice_language_mismatch_is_actionable() -> None:
    from app.services.audiobook_epub_pipeline import telegram_epub_reply_text

    job = {
        "status": "blocked_external_tts",
        "metadata": {"title": "Deutsches Buch"},
        "totals": {"chapter_count": 1, "char_count": 1000},
        "render_result": {"status": "blocked", "reason": "selected_voice_language_mismatch"},
        "provider": {
            "voice_selection": {
                "status": "selected_by_user",
                "selected": {"label": "English Voice", "language": "en-US"},
            }
        },
    }

    reply = telegram_epub_reply_text(job)

    assert "does not match the book language" in reply
    assert "wrong voice" in reply
    assert "Choose another voice" in reply
    assert "provider credits" not in reply


def test_telegram_audiobook_voice_callback_uses_long_lived_ttl(monkeypatch) -> None:
    from app.api.routes import channels

    now = 1_800_000_000
    monkeypatch.setattr(channels.time, "time", lambda: now)
    monkeypatch.delenv("EA_TELEGRAM_AUDIOBOOK_VOICE_CALLBACK_TTL_SECONDS", raising=False)

    callback_data = channels._telegram_encode_audiobook_voice_callback(
        bot_config={"token": "bot-token", "secret": "callback-secret"},
        action="u",
        token="sample-token",
        chat_id="42",
    )
    packet = channels._telegram_decode_audiobook_voice_callback(
        bot_config={"token": "bot-token", "secret": "callback-secret"},
        callback_data=callback_data,
        chat_id="42",
    )

    assert packet["ok"] is True
    assert int(packet["expires_at"]) - now == 604800


def test_resume_due_audiobook_jobs_does_not_retry_selected_voice_language_mismatch(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-language-mismatch"
    job_dir.mkdir(parents=True)
    job_payload = {
        "job_id": "job-language-mismatch",
        "status": "blocked_external_tts",
        "updated_at": (datetime.now(UTC) - timedelta(days=1)).isoformat().replace("+00:00", "Z"),
        "render_result": {"status": "blocked", "reason": "selected_voice_language_mismatch"},
    }
    (job_dir / "job.json").write_text(json.dumps(job_payload), encoding="utf-8")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(
        pipeline,
        "_resume_due_job_with_external_tts_consent",
        lambda path: pytest.fail("voice language mismatch should wait for a new voice, not retry TTS"),
    )

    summary = pipeline.resume_due_audiobook_jobs(notify_telegram=False)

    assert summary["attempted"] == 0
    assert summary["skipped"] == 1
    assert not (job_dir / "resume_state.json").exists()


def test_resume_due_audiobook_jobs_does_not_retry_external_tts_disabled_blocker(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-disabled"
    job_dir.mkdir(parents=True)
    job_payload = {
        "job_id": "job-disabled",
        "status": "blocked_external_tts",
        "updated_at": (datetime.now(UTC) - timedelta(days=1)).isoformat().replace("+00:00", "Z"),
        "render_result": {
            "status": "blocked",
            "reason": "external_tts_disabled_or_auto_render_off",
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job_payload), encoding="utf-8")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(
        pipeline,
        "_resume_due_job_with_external_tts_consent",
        lambda path: pytest.fail("disabled external TTS blocker should not be retried"),
    )

    summary = pipeline.resume_due_audiobook_jobs(notify_telegram=False)

    assert summary["attempted"] == 0
    assert summary["skipped"] == 1
    assert not (job_dir / "resume_state.json").exists()


def test_resume_due_audiobook_jobs_prioritizes_origin_dossier_over_bulk_epub(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    jobs_root = tmp_path / "jobs"
    older_retry = (datetime.now(UTC) - timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    newer_retry = (datetime.now(UTC) - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    bulk_dir = jobs_root / "bulk-book"
    dossier_dir = jobs_root / "origin-dossier"
    bulk_dir.mkdir(parents=True)
    dossier_dir.mkdir(parents=True)
    bulk_job = {
        "job_id": "bulk-book",
        "status": "waiting_provider_throttle",
        "source": {"kind": "epub"},
        "provider": {"preferred": "unmixr_ai", "raw_book_text_leaves_ea": True},
        "render_result": {"status": "provider_pacing_wait", "provider_retry_after": older_retry},
    }
    dossier_job = {
        "job_id": "origin-dossier",
        "status": "waiting_provider_throttle",
        "source": {"kind": "origin_dossier_story"},
        "provider": {"preferred": "unmixr_ai", "raw_book_text_leaves_ea": True},
        "render_result": {"status": "provider_throttled", "provider_retry_after": newer_retry},
    }
    (bulk_dir / "job.json").write_text(json.dumps(bulk_job), encoding="utf-8")
    (dossier_dir / "job.json").write_text(json.dumps(dossier_job), encoding="utf-8")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    resumed_paths: list[str] = []

    def fake_resume(path: Path):
        resumed_paths.append(path.name)
        return {**dossier_job, "status": "blocked_m4b_assembly_missing"}

    monkeypatch.setattr(pipeline, "_resume_due_job_with_external_tts_consent", fake_resume)

    summary = pipeline.resume_due_audiobook_jobs(limit=1, notify_telegram=False)

    assert resumed_paths == ["origin-dossier"]
    assert summary["attempted"] == 1
    assert summary["pending"] == 1
    assert (dossier_dir / "resume_state.json").is_file()
    assert not (bulk_dir / "resume_state.json").exists()


def test_resume_due_audiobook_jobs_keeps_future_throttle_pending(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-1"
    job_dir.mkdir(parents=True)
    retry_after = (datetime.now(UTC) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    (job_dir / "job.json").write_text(
        json.dumps(
            {
                "job_id": "job-1",
                "status": "waiting_provider_throttle",
                "render_result": {"status": "provider_throttled", "provider_retry_after": retry_after},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))

    summary = pipeline.resume_due_audiobook_jobs(notify_telegram=False)

    assert summary["attempted"] == 0
    assert summary["pending"] == 1
    assert summary["skip_reasons"] == {}


def test_resume_due_audiobook_jobs_reports_skip_reasons(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    jobs_root = tmp_path / "jobs"
    waiting_dir = jobs_root / "job-waiting"
    duplicate_dir = jobs_root / "job-duplicate"
    imported_dir = jobs_root / "job-imported"
    waiting_dir.mkdir(parents=True)
    duplicate_dir.mkdir(parents=True)
    imported_dir.mkdir(parents=True)

    (waiting_dir / "job.json").write_text(
        json.dumps(
            {
                "job_id": "job-waiting",
                "status": "waiting_voice_selection",
                "next_action": "choose_audiobook_voice",
            }
        ),
        encoding="utf-8",
    )
    (duplicate_dir / "job.json").write_text(
        json.dumps(
            {
                "job_id": "job-duplicate",
                "status": "superseded_duplicate",
                "next_action": "none",
            }
        ),
        encoding="utf-8",
    )
    (imported_dir / "job.json").write_text(
        json.dumps(
            {
                "job_id": "job-imported",
                "status": "audiobookshelf_imported",
                "audiobookshelf_import": {
                    "status": "imported",
                    "public_share": {
                        "status": "public_share_ready",
                        "absolute_url": "https://abs.example.com/share/skip-book",
                        "telegram_followup_pending": False,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))

    summary = pipeline.resume_due_audiobook_jobs(notify_telegram=False)

    assert summary["attempted"] == 0
    assert summary["resumed"] == 0
    assert summary["skipped"] == 2
    assert summary["skip_reasons"] == {
        "audiobookshelf_imported": 1,
        "waiting_voice_selection": 1,
    }
    assert summary["ignored_terminal"] == 1
    assert summary["ignored_terminal_reasons"] == {"superseded_duplicate": 1}
    assert summary["completed_terminal"] == 0
    assert summary["completed_terminal_reasons"] == {}


def test_resume_due_audiobook_jobs_only_treats_accepted_playback_as_completed_terminal(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    jobs_root = tmp_path / "jobs"
    rejected_dir = jobs_root / "job-rejected"
    accepted_dir = jobs_root / "job-accepted"
    waiting_dir = jobs_root / "job-waiting"
    rejected_dir.mkdir(parents=True)
    accepted_dir.mkdir(parents=True)
    waiting_dir.mkdir(parents=True)

    (rejected_dir / "job.json").write_text(
        json.dumps(
            {
                "job_id": "job-rejected",
                "status": "audiobookshelf_imported",
                "next_action": "review_audiobook_playback_problem",
                "audiobookshelf_import": {
                    "status": "imported",
                    "public_share": {
                        "status": "public_share_ready",
                        "absolute_url": "https://abs.example.com/share/rejected-book",
                        "telegram_followup_pending": False,
                        "whatsapp_followup_pending": False,
                    },
                },
                "playback_acceptance": {"status": "rejected", "accepted": False},
            }
        ),
        encoding="utf-8",
    )
    (accepted_dir / "job.json").write_text(
        json.dumps(
            {
                "job_id": "job-accepted",
                "status": "audiobookshelf_imported",
                "next_action": "playback_accepted",
                "audiobookshelf_import": {
                    "status": "imported",
                    "public_share": {
                        "status": "public_share_ready",
                        "absolute_url": "https://abs.example.com/share/accepted-book",
                        "telegram_followup_pending": False,
                        "whatsapp_followup_pending": False,
                    },
                },
                "playback_acceptance": {"status": "accepted", "accepted": True},
            }
        ),
        encoding="utf-8",
    )
    (waiting_dir / "job.json").write_text(
        json.dumps(
            {
                "job_id": "job-waiting",
                "status": "waiting_voice_selection",
                "next_action": "choose_audiobook_voice",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))

    summary = pipeline.resume_due_audiobook_jobs(notify_telegram=False)

    assert summary["attempted"] == 0
    assert summary["resumed"] == 0
    assert summary["skipped"] == 1
    assert summary["skip_reasons"] == {"waiting_voice_selection": 1}
    assert summary["ignored_terminal"] == 0
    assert summary["ignored_terminal_reasons"] == {}
    assert summary["operator_review_pending"] == 1
    assert summary["operator_review_reasons"] == {"review_audiobook_playback_problem": 1}
    assert summary["completed_terminal"] == 1
    assert summary["completed_terminal_reasons"] == {"playback_accepted": 1}


def test_resume_due_audiobook_jobs_ignores_stale_recovered_rejection_after_machine_pass(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    jobs_root = tmp_path / "jobs"
    rejected_dir = jobs_root / "job-rejected"
    rejected_dir.mkdir(parents=True)

    (rejected_dir / "job.json").write_text(
        json.dumps(
            {
                "job_id": "job-rejected",
                "status": "audiobookshelf_imported",
                "next_action": "review_audiobook_playback_problem",
                "audiobookshelf_import": {
                    "status": "imported",
                    "public_share": {
                        "status": "public_share_ready",
                        "absolute_url": "https://abs.example.com/share/rejected-book",
                        "telegram_followup_pending": False,
                        "whatsapp_followup_pending": False,
                        "playback_e2e": {
                            "status": "pass",
                            "checked_at": "2026-06-23T12:32:14Z",
                        },
                    },
                },
                "playback_acceptance": {
                    "status": "rejected",
                    "accepted": False,
                    "source": "whatsapp_button_recovered",
                    "recorded_at": "2026-06-22T15:57:46Z",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))

    summary = pipeline.resume_due_audiobook_jobs(notify_telegram=False)

    assert summary["operator_review_pending"] == 0
    assert summary["operator_review_reasons"] == {}


def test_origin_dossier_text_job_uses_same_audiobook_pipeline(monkeypatch, tmp_path: Path) -> None:
    from app.services.audiobook_epub_pipeline import build_audiobook_job_receipt, create_origin_dossier_audiobook_job

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "0")
    monkeypatch.setenv("EA_M4B_TOOL_BIN", "definitely-missing-m4b-tool")
    monkeypatch.setenv("UNMIXR_VOICE_ID", "default-secret-voice")
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"cover bytes")

    job = create_origin_dossier_audiobook_job(
        origin_story_text="The runner owes a clinic and carries the debt into every job.",
        runner_name="Kobalt",
        principal_id="player-1",
        dossier_id="dossier-1",
        player_id="player-1",
        runner_id="runner-1",
        cover_image_path=cover,
    )

    assert job["status"] == "blocked_external_tts"
    assert job["source"]["kind"] == "origin_dossier_story"
    assert job["source"]["rights_basis"] == "player_or_gm_approved_origin_story"
    assert job["source"]["runner_id"] == "runner-1"
    assert job["provider"]["voice_selection"]["selected"]["label"] == "Configured audio voice"
    assert "default-secret-voice" not in json.dumps(job)
    cover_path = Path(job["metadata"]["cover_image_path"])
    assert cover_path.name == "cover.jpg"
    assert cover_path.read_bytes() == b"cover bytes"
    receipt = build_audiobook_job_receipt(job_dir=Path(job["storage"]["job_dir"]))
    assert receipt["source"]["priority_for_resume"] is True
    assert receipt["scheduler_resume"]["priority_label"] == "priority_small_narration"
    assert receipt["scheduler_resume"]["priority_score"] == 0


def test_origin_dossier_audiobook_bypasses_bulk_epub_pacing(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import create_origin_dossier_audiobook_job

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_MAX_CHARS_PER_REQUEST", "1000")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_MAX_SEGMENTS_PER_RUN", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_BULK_PACING_CHAR_THRESHOLD", "1")
    monkeypatch.setenv("EA_M4B_TOOL_BIN", "definitely-missing-m4b-tool")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_AUTO_IMPORT", "0")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps([{"voice_id": "voice-1", "label": "Narrator", "language": "en-US", "tags": ["audiobook", "narration", "story"], "default": True}]),
    )
    text = ("Kestrel remembers the clinic, the debt, and the rule that nobody gets left behind. " * 16 + "\n\n") * 3
    tone = tmp_path / "tone.wav"
    _write_tone_wav(tone)
    calls = {"count": 0}

    def fake_synthesize_request(**kwargs):
        calls["count"] += 1
        return tone.read_bytes(), "audio/wav"

    def fake_merge_segments(*, segment_paths, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(Path(segment_paths[0]).read_bytes())
        return True

    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", fake_synthesize_request)
    monkeypatch.setattr(pipeline, "_merge_audio_segments_to_wav", fake_merge_segments)

    job = create_origin_dossier_audiobook_job(
        origin_story_text=text,
        runner_name="Kestrel",
        principal_id="player-1",
        dossier_id="dossier-1",
        player_id="player-1",
        runner_id="runner-1",
    )

    assert calls["count"] > 1
    assert job["source"]["kind"] == "origin_dossier_story"
    assert job["status"] != "waiting_provider_throttle"
    assert job["render_result"]["status"] in {"rendered", "already_rendered"}


def test_unmixr_render_inserts_silence_between_paragraphs(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import EpubChapter, EpubMetadata, render_unmixr_chapter_audio

    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_PARAGRAPH_PAUSES_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_PARAGRAPH_PAUSE_SECONDS", "0.35")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_MAX_CHARS_PER_REQUEST", "1000")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps([{"voice_id": "voice-1", "label": "Narrator", "language": "en-US", "tags": ["audiobook", "narration"], "default": True}]),
    )
    chapter_dir = tmp_path / "chapters"
    chapter_dir.mkdir()
    text = "First paragraph should be narrated as its own unit.\n\nSecond paragraph should follow after a small pause."
    (chapter_dir / "001 - Test.txt").write_text(text, encoding="utf-8")
    chapter = EpubChapter(index=1, title="Test", source_href="test.xhtml", text_path="001 - Test.txt", audio_filename="001 - Test.wav", char_count=len(text), sha256="sha")
    metadata = EpubMetadata(title="Test Book", author="A. Writer", language="en-US", source_filename="book.epub", source_sha256="sha")
    tone = tmp_path / "tone.wav"
    _write_tone_wav(tone)
    tts_texts: list[str] = []
    merge_inputs: list[str] = []

    def fake_synthesize_request(**kwargs):
        tts_texts.append(str(kwargs["text"]))
        return tone.read_bytes(), "audio/wav"

    def fake_merge_segments(*, segment_paths, target):
        merge_inputs.extend(Path(path).name for path in segment_paths)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(Path(segment_paths[0]).read_bytes())
        return True

    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", fake_synthesize_request)
    monkeypatch.setattr(pipeline, "_merge_audio_segments_to_wav", fake_merge_segments)

    result = render_unmixr_chapter_audio(job_dir=tmp_path, chapters=(chapter,), metadata=metadata)

    assert result["status"] == "rendered"
    assert tts_texts == [
        "First paragraph should be narrated as its own unit.",
        "Second paragraph should follow after a small pause.",
    ]
    assert len(merge_inputs) == 3
    assert merge_inputs[1].endswith("paragraph-pause.wav")
    assert result["chapters"][0]["segment_count"] == 2
    assert result["chapters"][0]["paragraph_pause_count"] == 1
    assert result["chapters"][0]["paragraph_pause_seconds"] == 0.35


def test_telegram_adapter_preserves_document_mime_and_size() -> None:
    from app.channels.telegram.adapter import TelegramObservationAdapter

    fields = TelegramObservationAdapter().to_observation_fields(
        {
            "message": {
                "message_id": 7,
                "chat": {"id": 42},
                "document": {
                    "file_id": "file-1",
                    "file_name": "book.epub",
                    "mime_type": "application/epub+zip",
                    "file_size": 1234,
                },
            }
        }
    )

    metadata = fields["payload"]["message_metadata"]
    assert metadata["file_name"] == "book.epub"
    assert metadata["mime_type"] == "application/epub+zip"
    assert metadata["file_size"] == 1234


def test_telegram_epub_turn_decision_routes_before_generic_document(monkeypatch) -> None:
    from app.api.routes import channels
    from app.services.telegram_session_service import TelegramTurnContext

    monkeypatch.setenv("EA_AUDIOBOOK_INSTANT_SENDER_WHITELIST", "telegram:42")
    ctx = TelegramTurnContext(
        container=object(),
        principal_id="principal-1",
        text="Document: book.epub",
        payload={
            "kind": "document",
            "message_id": "7",
            "message_metadata": {
                "file_id": "file-1",
                "file_name": "book.epub",
                "mime_type": "application/epub+zip",
                "file_size": 2048,
                "download_url": "https://api.telegram.org/file/botTOKEN/books/book.epub",
            },
        },
        bot_handle="",
        preferred_onemin_labels=(),
        current_message_id="7",
        chat_id="42",
        normalized="Document: book.epub",
        lower="document: book.epub",
        alpha_words=("document", "book", "epub"),
        is_completion_cue=False,
    )

    decision = channels._telegram_audiobook_epub_turn_decision(ctx)

    assert decision.schedule_async is True
    assert decision.suppress_async_ack is True
    assert decision.reply_text == ""
    assert decision.async_payload["kind"] == "audiobook_epub_document"
    assert decision.async_payload["source_epub_file_size"] == 2048


def test_telegram_epub_turn_decision_routes_file_id_before_generic_document(monkeypatch) -> None:
    from app.api.routes import channels
    from app.services.telegram_session_service import TelegramTurnContext

    monkeypatch.setenv("EA_AUDIOBOOK_INSTANT_SENDER_WHITELIST", "telegram:42")
    ctx = TelegramTurnContext(
        container=object(),
        principal_id="principal-1",
        text="Document: book.epub",
        payload={
            "kind": "document",
            "message_id": "7",
            "message_metadata": {
                "file_id": "file-1",
                "file_name": "book.epub",
                "mime_type": "application/epub+zip",
                "file_size": 2048,
            },
        },
        bot_handle="",
        preferred_onemin_labels=(),
        current_message_id="7",
        chat_id="42",
        normalized="Document: book.epub",
        lower="document: book.epub",
        alpha_words=("document", "book", "epub"),
        is_completion_cue=False,
    )

    decision = channels._telegram_audiobook_epub_turn_decision(ctx)

    assert decision.schedule_async is True
    assert decision.suppress_async_ack is True
    assert decision.reply_text == ""
    assert decision.async_payload["kind"] == "audiobook_epub_document"
    assert decision.async_payload["source_epub_url"] == ""
    assert decision.async_payload["telegram_file_id"] == "file-1"


def test_telegram_azw3_turn_decision_routes_as_audiobook_source(monkeypatch) -> None:
    from app.api.routes import channels
    from app.services.telegram_session_service import TelegramTurnContext

    monkeypatch.setenv("EA_AUDIOBOOK_INSTANT_SENDER_WHITELIST", "telegram:42")
    ctx = TelegramTurnContext(
        container=object(),
        principal_id="principal-1",
        text="Document: kindle-book.azw3",
        payload={
            "kind": "document",
            "message_id": "7",
            "message_metadata": {
                "file_id": "file-1",
                "file_name": "kindle-book.azw3",
                "mime_type": "application/vnd.amazon.ebook",
                "file_size": 4096,
                "download_url": "https://api.telegram.org/file/botTOKEN/books/kindle-book.azw3",
            },
        },
        bot_handle="",
        preferred_onemin_labels=(),
        current_message_id="7",
        chat_id="42",
        normalized="Document: kindle-book.azw3",
        lower="document: kindle-book.azw3",
        alpha_words=("document", "kindle", "book", "azw3"),
        is_completion_cue=False,
    )

    decision = channels._telegram_audiobook_epub_turn_decision(ctx)

    assert decision.schedule_async is True
    assert decision.suppress_async_ack is True
    assert decision.reply_text == ""
    assert decision.async_payload["kind"] == "audiobook_epub_document"
    assert decision.async_payload["source_epub_filename"] == "kindle-book.azw3"
    assert decision.async_payload["source_epub_file_size"] == 4096


def test_telegram_epub_turn_decision_requires_approval_for_unknown_sender(monkeypatch) -> None:
    from app.api.routes import channels
    from app.services.telegram_session_service import TelegramTurnContext

    monkeypatch.delenv("EA_AUDIOBOOK_INSTANT_SENDER_WHITELIST", raising=False)
    monkeypatch.delenv("EA_AUDIOBOOK_INSTANT_PHONE_WHITELIST", raising=False)
    ctx = TelegramTurnContext(
        container=object(),
        principal_id="principal-1",
        text="Document: book.epub",
        payload={
            "kind": "document",
            "message_id": "7",
            "message_metadata": {
                "file_id": "file-1",
                "file_name": "book.epub",
                "mime_type": "application/epub+zip",
                "file_size": 2048,
                "download_url": "https://api.telegram.org/file/botTOKEN/books/book.epub",
            },
        },
        bot_handle="",
        preferred_onemin_labels=(),
        current_message_id="7",
        chat_id="42",
        normalized="Document: book.epub",
        lower="document: book.epub",
        alpha_words=("document", "book", "epub"),
        is_completion_cue=False,
    )

    decision = channels._telegram_audiobook_epub_turn_decision(ctx)

    assert decision.schedule_async is True
    assert decision.suppress_async_ack is True
    assert decision.async_payload["kind"] == "audiobook_access_approval_request"
    assert decision.async_payload["sender_ref"] == "telegram:42"
    assert "operator approval" in decision.reply_text


def test_telegram_audiobook_epub_payload_rejects_non_telegram_urls() -> None:
    from app.api.routes import channels
    from app.services.telegram_session_service import TelegramTurnContext

    ctx = TelegramTurnContext(
        container=object(),
        principal_id="principal-1",
        text="Document: book.epub",
        payload={
            "kind": "document",
            "message_id": "7",
            "message_metadata": {
                "file_id": "file-1",
                "file_name": "book.epub",
                "mime_type": "application/epub+zip",
                "download_url": "https://example.com/file/book.epub",
            },
        },
        bot_handle="",
        preferred_onemin_labels=(),
        current_message_id="7",
        chat_id="42",
        normalized="Document: book.epub",
        lower="document: book.epub",
        alpha_words=("document", "book", "epub"),
        is_completion_cue=False,
    )

    decision = channels._telegram_audiobook_epub_turn_decision(ctx)
    assert decision.reply_text == ""
    assert decision.schedule_async is False
    assert decision.async_payload is None


def test_telegram_audiobook_status_explains_missing_voice_samples(monkeypatch, tmp_path: Path) -> None:
    from app.api.routes import channels

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_IMPORT_ROOT", str(tmp_path / "audiobookshelf"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "0")
    monkeypatch.delenv("EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON", raising=False)
    monkeypatch.delenv("EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_PATH", raising=False)
    monkeypatch.delenv("UNMIXR_VOICE_ID", raising=False)
    monkeypatch.delenv("UNMIXR_API_KEY", raising=False)
    monkeypatch.delenv("UNMIXR_API_KEY_FALLBACK_1", raising=False)
    monkeypatch.delenv("UNMIXR_API_KEY_FALLBACK_2", raising=False)

    reply = channels._telegram_audiobook_runtime_status_reply_text("why do i not get the 3 voice samples?")

    assert "Audiobook voice samples are not live-ready yet" in reply
    assert "external audiobook TTS is disabled" in reply
    assert "audio generation is disabled" in reply
    assert "fewer than three audiobook voices are available" in reply
    assert "no owned audio generation account slot is configured" in reply
    assert "Voice catalog: 0/3" in reply
    assert "audio generation account slots configured: 0" in reply
    assert "Use this/Dismiss" in reply


def test_telegram_audiobook_status_separates_sample_readiness_from_completion_blockers(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.api.routes import channels

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_IMPORT_ROOT", str(tmp_path / "audiobookshelf"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("UNMIXR_API_KEY", "fake-unmixr-key")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": f"voice-{index}", "label": f"Voice {index}", "language": "en-US", "tags": ["audiobook", "narration"]}
                for index in range(1, 4)
            ]
        ),
    )
    monkeypatch.delenv("EA_AUDIOBOOK_ACCESS_SIGNING_SECRET", raising=False)
    monkeypatch.delenv("EA_AUDIOBOOK_PLAYER_ACCESS_BASE_URL", raising=False)

    reply = channels._telegram_audiobook_runtime_status_reply_text("audiobook status")

    assert "Audiobook voice samples are ready" in reply
    assert "Voice catalog: 3/3" in reply
    assert "full delivery is not complete-ready" in reply
    assert "player-scoped playback signing is not configured" in reply
    assert "player-scoped playback base URL is not configured" in reply


def test_telegram_audiobook_status_reports_pending_explicit_replacement_choice(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.api.routes import channels

    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-replacement-choice"
    job_dir.mkdir(parents=True)
    job = {
        "job_id": "job-replacement-choice",
        "status": "waiting_voice_selection",
        "metadata": {"title": "Test Book", "source_filename": "book.epub"},
        "telegram": {
            "chat_id": "42",
            "voice_sample_delivery": {"status": "sent", "sent_count": 1, "expected_count": 1},
        },
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "reason": "selected_voice_provider_balance_blocked",
                "selected": {"label": "Seraphina"},
                "pending_batch": [
                    {
                        "label": "Piper German Thorsten high",
                        "preset_key": "piper-local",
                        "callback_token": "secret-token",
                    }
                ],
            }
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job, indent=2, sort_keys=True), encoding="utf-8")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))

    reply = channels._telegram_audiobook_runtime_status_reply_text("audiobook status", chat_id="42")

    assert "waiting for your explicit voice choice" in reply
    assert "selected provider voice is blocked" in reply
    assert "Seraphina" in reply
    assert "Piper German Thorsten high" in reply
    assert "Use this/Dismiss" in reply
    assert "secret-token" not in reply


def test_telegram_audiobook_voice_sample_status_resends_pending_sample(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.api.routes import channels
    from app.services.telegram_session_service import TelegramTurnContext

    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-replacement-choice"
    job_dir.mkdir(parents=True)
    job = {
        "job_id": "job-replacement-choice",
        "status": "waiting_voice_selection",
        "metadata": {"title": "Test Book", "source_filename": "book.epub"},
        "storage": {"job_dir": str(job_dir)},
        "telegram": {"chat_id": "42", "voice_sample_delivery": {"status": "sent", "sent_count": 1}},
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "reason": "selected_voice_provider_balance_blocked",
                "selected": {"label": "Seraphina"},
                "replacement_candidate_keys": ["piper-local"],
                "last_action": {"replacement_candidate_keys": ["piper-local"]},
                "pending_batch": [
                    {
                        "label": "Piper German Thorsten high",
                        "preset_key": "piper-local",
                        "callback_token": "replacement-token",
                        "sample_file": "replacement.wav",
                        "sample_audio_ready": True,
                    }
                ],
            }
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job, indent=2, sort_keys=True), encoding="utf-8")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    sent: list[list[str]] = []

    def fake_send_samples(*, bot_config: dict[str, object], chat_id: str, job: dict[str, object]) -> list[dict[str, object]]:
        assert chat_id == "42"
        sent.append([row["label"] for row in job["provider"]["voice_selection"]["pending_batch"] if isinstance(row, dict)])
        return [{"token": "replacement-token", "status": "sent"}]

    def fake_record(**kwargs) -> dict[str, object]:
        assert kwargs["sample_receipts"][0]["token"] == "replacement-token"
        return kwargs["job"]

    monkeypatch.setattr(channels, "_telegram_send_audiobook_voice_samples", fake_send_samples)
    monkeypatch.setattr(channels, "record_audiobook_voice_sample_delivery", fake_record)

    ctx = TelegramTurnContext(
        container=object(),
        principal_id="principal-1",
        text="why do i not get the voice samples?",
        payload={"_bot_config": {"token": "telegram-token"}},
        bot_handle="",
        preferred_onemin_labels=(),
        current_message_id="8",
        chat_id="42",
        normalized="why do i not get the voice samples?",
        lower="why do i not get the voice samples?",
        alpha_words=("why", "do", "i", "not", "get", "the", "voice", "samples"),
        is_completion_cue=False,
    )

    decision = channels._telegram_local_turn_decision(ctx)

    assert "waiting for your explicit voice choice" in decision.reply_text
    assert "I resent 1 audiobook voice sample." in decision.reply_text
    assert sent == [["Piper German Thorsten high"]]


def test_telegram_audiobook_status_resends_playback_acceptance_buttons(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.api.routes import channels
    from app.services.telegram_session_service import TelegramTurnContext

    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-ready"
    job_dir.mkdir(parents=True)
    target_path = tmp_path / "audiobookshelf" / "A. Writer" / "Ready Book" / "Ready Book.m4b"
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(b"fake m4b")
    job = {
        "job_id": "job-ready",
        "status": "audiobookshelf_imported",
        "updated_at": "2026-06-20T04:06:00Z",
        "metadata": {"title": "Ready Book", "author": "A. Writer", "language": "en-US"},
        "storage": {"job_dir": str(job_dir)},
        "telegram": {"chat_id": "42", "message_id": "7"},
        "audiobookshelf_import": {
            "status": "imported",
            "target_path": str(target_path),
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://abs.example.com/share/ea-ready-book",
                "telegram_followup_pending": False,
                "telegram_delivery": {"status": "sent", "message_id": "2942"},
                "playback_acceptance_callback": {
                    "status": "ready",
                    "token": "callback-token",
                    "raw_token_exposed": False,
                },
            },
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job, indent=2, sort_keys=True), encoding="utf-8")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setenv("EA_TELEGRAM_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("UNMIXR_API_KEY", "fake-unmixr-key")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": f"voice-{index}", "label": f"Voice {index}", "language": "en-US", "tags": ["audiobook", "narration"]}
                for index in range(1, 4)
            ]
        ),
    )

    ctx = TelegramTurnContext(
        container=object(),
        principal_id="principal-1",
        text="audiobook status",
        payload={"_bot_config": {"token": "telegram-token"}},
        bot_handle="",
        preferred_onemin_labels=(),
        current_message_id="8",
        chat_id="42",
        normalized="audiobook status",
        lower="audiobook status",
        alpha_words=("audiobook", "status"),
        is_completion_cue=False,
    )

    decision = channels._telegram_local_turn_decision(ctx)

    assert "Latest Audiobookshelf delivery awaiting playback confirmation: Ready Book" in decision.reply_text
    assert decision.inline_buttons
    labels = [label for row in decision.inline_buttons for label, _callback in row]
    callbacks = [callback for row in decision.inline_buttons for _label, callback in row]
    assert "Playback works" in labels
    assert "Problem" in labels
    assert any(callback.startswith("ap|a|callback-token|") for callback in callbacks)
    assert any(callback.startswith("ap|r|callback-token|") for callback in callbacks)


def test_telegram_owner_label_is_generic_by_default(monkeypatch) -> None:
    from app.api.routes import channels
    from app.services.telegram_session_service import TelegramTurnContext

    for env_key in (
        "EA_ASSISTANT_OWNER_LABEL",
        "EA_WHATSAPP_WEB_DEFAULT_TENANT_NAME",
        "EA_WHATSAPP_DEFAULT_TENANT_NAME",
        "EA_WHATSAPP_WEB_DEFAULT_DISPLAY_NAME",
        "EA_WHATSAPP_DEFAULT_DISPLAY_NAME",
    ):
        monkeypatch.delenv(env_key, raising=False)
    monkeypatch.setattr(channels, "_recent_telegram_texts", lambda *_args, **_kwargs: ["please record this"])

    ctx = TelegramTurnContext(container=object(), principal_id="principal-1", text="/start", payload={}, normalized="/start")
    decision = channels._telegram_command_turn_decision(ctx)
    reply = channels._telegram_general_reply_text(container=object(), principal_id="principal-1", text="really?")

    assert "for the principal" in decision.reply_text
    assert "the principal's assistant flow" in reply
    assert "Tibor" not in decision.reply_text
    assert "Tibor" not in reply


def test_telegram_owner_label_uses_configured_assistant_owner(monkeypatch) -> None:
    from app.api.routes import channels
    from app.services.telegram_session_service import TelegramTurnContext

    monkeypatch.setenv("EA_ASSISTANT_OWNER_LABEL", "Alex")
    monkeypatch.setattr(channels, "_telegram_supported_property_link", lambda _text: "")
    monkeypatch.setattr(channels, "_telegram_login_walled_property_link", lambda _text: "")
    monkeypatch.setattr(channels, "_telegram_local_assistant_reply_text", lambda *_args, **_kwargs: "")
    ctx = TelegramTurnContext(
        container=object(),
        principal_id="principal-1",
        text="https://example.test/note",
        payload={},
        normalized="https://example.test/note",
    )

    start = channels._telegram_command_turn_decision(
        TelegramTurnContext(container=object(), principal_id="principal-1", text="/start", payload={}, normalized="/start")
    )
    link = channels._telegram_link_turn_decision(ctx)

    assert "for Alex" in start.reply_text
    assert "Alex's assistant workspace" in link.reply_text
    assert "Tibor" not in start.reply_text
    assert "Tibor" not in link.reply_text


def test_assistant_owner_label_is_exposed_in_runtime_templates() -> None:
    root = Path(__file__).resolve().parents[1]

    env_example = (root / ".env.example").read_text(encoding="utf-8")
    env_local_example = (root / ".env.local.example").read_text(encoding="utf-8")
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")

    assert "EA_ASSISTANT_OWNER_LABEL=the principal" in env_example
    assert "EA_ASSISTANT_OWNER_LABEL=the principal" in env_local_example
    assert "EA_ASSISTANT_OWNER_LABEL=${EA_ASSISTANT_OWNER_LABEL:-the principal}" in compose


def test_cleanup_audiobook_job_artifacts_removes_transient_render_files(tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    job_dir = tmp_path / "epub-audiobook-20260622T000000Z-test"
    (job_dir / "audio").mkdir(parents=True)
    (job_dir / "output").mkdir()
    (job_dir / "m4b").mkdir()
    (job_dir / "source").mkdir()
    (job_dir / "chapters").mkdir()
    (job_dir / "audio" / "chapter-001.wav").write_bytes(b"a" * 32)
    (job_dir / "output" / "book.m4b").write_bytes(b"b" * 32)
    (job_dir / "m4b" / "normalized.m4b").write_bytes(b"c" * 32)
    (job_dir / "source" / "book.epub").write_text("original", encoding="utf-8")
    (job_dir / "source" / "book.converted.epub").write_text("converted", encoding="utf-8")
    (job_dir / "job_receipt.json").write_text("{}", encoding="utf-8")
    (job_dir / "resume_state.json").write_text("{}", encoding="utf-8")
    (job_dir / "audiobookshelf_share_state.json").write_text("{}", encoding="utf-8")
    (job_dir / "job.json.deadbeef.partial").write_text("{}", encoding="utf-8")
    (job_dir / "job.json").write_text(
        json.dumps(
            {
                "job_id": job_dir.name,
                "status": "audiobookshelf_imported",
                "updated_at": "2026-06-20T00:00:00Z",
                "storage": {"job_dir": str(job_dir)},
            }
        ),
        encoding="utf-8",
    )

    result = pipeline.cleanup_audiobook_job_artifacts(
        job_dir,
        force=True,
        now=datetime(2026, 6, 22, 12, 0, tzinfo=UTC),
    )

    assert result["status"] == "cleaned"
    assert not (job_dir / "audio").exists()
    assert not (job_dir / "output").exists()
    assert not (job_dir / "m4b").exists()
    assert not (job_dir / "source" / "book.converted.epub").exists()
    assert not (job_dir / "resume_state.json").exists()
    assert not (job_dir / "audiobookshelf_share_state.json").exists()
    assert not (job_dir / "job.json.deadbeef.partial").exists()
    assert (job_dir / "source" / "book.epub").exists()
    assert (job_dir / "job_receipt.json").exists()
    assert (job_dir / "job.json").exists()


def test_cleanup_audiobook_job_artifacts_records_removal_errors_without_raising(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    job_dir = tmp_path / "job-cleanup-error"
    (job_dir / "audio").mkdir(parents=True)
    (job_dir / "audio" / "chapter.wav").write_text("audio", encoding="utf-8")
    (job_dir / "job.json").write_text(
        json.dumps(
            {
                "job_id": "job-cleanup-error",
                "status": "audiobookshelf_imported",
                "updated_at": "2026-06-20T10:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    real_remove = pipeline._audiobook_cleanup_remove_path

    def _fail_audio(path: Path) -> int:
        if path.name == "audio":
            raise OSError("simulated_io_error")
        return real_remove(path)

    monkeypatch.setattr(pipeline, "_audiobook_cleanup_remove_path", _fail_audio)

    result = pipeline.cleanup_audiobook_job_artifacts(
        job_dir,
        force=True,
        now=datetime(2026, 6, 22, 12, 0, tzinfo=UTC),
    )

    assert result["status"] == "failed"
    assert result["job_status"] == "audiobookshelf_imported"
    assert result["removed_paths"] == []
    assert result["removal_errors"] == [{"path": "audio", "error": "OSError"}]
    assert (job_dir / "audio").exists()


def test_cleanup_audiobook_job_artifacts_treats_disappearing_manifest_as_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    job_dir = tmp_path / "job-disappearing-manifest"
    job_dir.mkdir()
    monkeypatch.setattr(pipeline, "_load_job", lambda _job_dir: (_ for _ in ()).throw(FileNotFoundError("raced")))

    result = pipeline.cleanup_audiobook_job_artifacts(
        job_dir,
        force=True,
        now=datetime(2026, 6, 22, 12, 0, tzinfo=UTC),
    )

    assert result["status"] == "missing"
    assert result["reason"] == "FileNotFoundError"
    assert result["removed_paths"] == []


def test_cleanup_audiobook_job_artifacts_falls_back_to_job_receipt_when_manifest_is_corrupt(tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    job_dir = tmp_path / "job-corrupt-manifest"
    (job_dir / "audio").mkdir(parents=True)
    (job_dir / "audio" / "chapter.wav").write_text("audio", encoding="utf-8")
    (job_dir / "resume_state.json").write_text("{}", encoding="utf-8")
    (job_dir / "job.json").write_text("", encoding="utf-8")
    (job_dir / "job_receipt.json").write_text(
        json.dumps(
            {
                "job_id": "job-corrupt-manifest",
                "status": "audiobookshelf_imported",
                "updated_at": "2026-06-20T10:00:00Z",
                "storage": {"job_dir": str(job_dir)},
            }
        ),
        encoding="utf-8",
    )

    result = pipeline.cleanup_audiobook_job_artifacts(
        job_dir,
        force=True,
        now=datetime(2026, 6, 22, 12, 0, tzinfo=UTC),
    )

    assert result["status"] == "cleaned"
    assert result["job_status"] == "audiobookshelf_imported"
    assert result["job_manifest_source"] == "job_receipt.json"
    assert not (job_dir / "audio").exists()
    assert not (job_dir / "resume_state.json").exists()
    assert (job_dir / "job_receipt.json").exists()
    assert (job_dir / "job.json").exists()


def test_cleanup_finished_audiobook_jobs_prunes_stale_incoming_files(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path))
    monkeypatch.setenv("EA_AUDIOBOOK_JOB_CLEANUP_STAGING_RETENTION_DAYS", "1")
    incoming_dir = tmp_path / "_incoming" / "20260619"
    incoming_dir.mkdir(parents=True)
    stale = incoming_dir / "stale.epub"
    stale.write_text("payload", encoding="utf-8")
    old_ts = datetime(2026, 6, 19, 12, 0, tzinfo=UTC).timestamp()
    os.utime(stale, (old_ts, old_ts))

    result = pipeline.cleanup_finished_audiobook_jobs(
        force=True,
        now=datetime(2026, 6, 22, 12, 0, tzinfo=UTC),
    )

    assert result["staging"]["status"] == "cleaned"
    assert result["staging"]["removed_files"] == 1
    assert not stale.exists()


def test_cleanup_finished_audiobook_jobs_prunes_staging_across_discovery_roots(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    local_root = tmp_path / "jobs-local"
    host_root = tmp_path / "jobs-host"
    local_root.mkdir()
    host_root.mkdir()
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(local_root))
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_HOST_ROOT", str(host_root))
    monkeypatch.setenv("EA_AUDIOBOOK_JOB_CLEANUP_STAGING_RETENTION_DAYS", "1")

    incoming_dir = host_root / "_incoming" / "20260619"
    incoming_dir.mkdir(parents=True)
    stale = incoming_dir / "stale.epub"
    stale.write_text("payload", encoding="utf-8")
    old_ts = datetime(2026, 6, 19, 12, 0, tzinfo=UTC).timestamp()
    os.utime(stale, (old_ts, old_ts))

    result = pipeline.cleanup_finished_audiobook_jobs(
        force=True,
        now=datetime(2026, 6, 22, 12, 0, tzinfo=UTC),
    )

    assert result["staging"]["status"] == "cleaned"
    assert result["staging"]["removed_files"] == 1
    assert not stale.exists()


def test_cleanup_finished_audiobook_jobs_tolerates_disappearing_empty_staging_dirs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path))
    monkeypatch.setenv("EA_AUDIOBOOK_JOB_CLEANUP_STAGING_RETENTION_DAYS", "1")
    incoming_parent = tmp_path / "_incoming"
    empty_dir = incoming_parent / "20260620"
    empty_dir.mkdir(parents=True)

    real_rmdir = Path.rmdir

    def _racing_rmdir(self: Path) -> None:
        if self == empty_dir:
            real_rmdir(self)
            raise FileNotFoundError(self)
        real_rmdir(self)

    monkeypatch.setattr(Path, "rmdir", _racing_rmdir)

    result = pipeline.cleanup_finished_audiobook_jobs(
        force=True,
        now=datetime(2026, 6, 22, 12, 0, tzinfo=UTC),
    )

    assert result["staging"]["status"] == "not_needed"


def test_cleanup_finished_audiobook_jobs_observes_disconnected_staging_roots(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path))
    incoming_root = tmp_path / "_incoming"

    real_is_dir = Path.is_dir

    def _racing_is_dir(self: Path) -> bool:
        if self == incoming_root:
            raise OSError(errno.ENOTCONN, "Transport endpoint is not connected")
        return real_is_dir(self)

    monkeypatch.setattr(Path, "is_dir", _racing_is_dir)

    result = pipeline.cleanup_finished_audiobook_jobs(
        force=True,
        now=datetime(2026, 6, 22, 12, 0, tzinfo=UTC),
    )

    assert result["status"] == "not_needed"
    assert result["staging"]["status"] == "missing"
    assert result["staging"]["skipped_paths"] == [
        {"path": str(incoming_root), "reason": "OSError", "errno": errno.ENOTCONN},
    ]


def test_cleanup_finished_audiobook_jobs_contains_per_job_cleanup_exceptions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path))
    job_dir = tmp_path / "job-cleanup-race"
    job_dir.mkdir()
    (job_dir / "job.json").write_text("{}", encoding="utf-8")

    def _raise_cleanup(*_args, **_kwargs):
        raise OSError("transient cleanup race")

    monkeypatch.setattr(pipeline, "cleanup_audiobook_job_artifacts", _raise_cleanup)

    result = pipeline.cleanup_finished_audiobook_jobs(
        force=True,
        now=datetime(2026, 6, 22, 12, 0, tzinfo=UTC),
    )

    assert result["status"] == "failed"
    assert result["failed_jobs"] == 1
    assert result["results"][0]["status"] == "failed"
    assert result["results"][0]["reason"] == "OSError"


def test_cleanup_finished_audiobook_jobs_prunes_superseded_duplicate_jobs(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path))
    shared_sha = "same-book-sha"

    def _write_job(job_dir: Path, *, status: str, updated_at: str) -> None:
        job_dir.mkdir(parents=True)
        (job_dir / "job.json").write_text(
            json.dumps(
                {
                    "job_id": job_dir.name,
                    "status": status,
                    "updated_at": updated_at,
                    "source": {
                        "kind": "epub",
                        "source_sha256": shared_sha,
                    },
                    "metadata": {
                        "title": "Duplicate Book",
                        "author": "A. Writer",
                        "source_sha256": shared_sha,
                    },
                    "storage": {"job_dir": str(job_dir)},
                }
            ),
            encoding="utf-8",
        )

    stale_waiting = tmp_path / "job-stale-waiting"
    stale_m4b = tmp_path / "job-stale-m4b"
    current_imported = tmp_path / "job-current-imported"
    _write_job(stale_waiting, status="waiting_voice_selection", updated_at="2026-06-20T00:00:00Z")
    _write_job(stale_m4b, status="m4b_ready", updated_at="2026-06-21T00:00:00Z")
    _write_job(current_imported, status="audiobookshelf_imported", updated_at="2026-06-22T00:00:00Z")

    result = pipeline.cleanup_finished_audiobook_jobs(
        force=True,
        now=datetime(2026, 6, 23, 12, 0, tzinfo=UTC),
    )

    assert result["superseded"]["status"] == "cleaned"
    assert result["superseded"]["cleaned_jobs"] == 2
    assert stale_waiting.exists()
    assert stale_m4b.exists()
    assert current_imported.exists()
    assert json.loads((stale_waiting / "job.json").read_text(encoding="utf-8"))["status"] == "superseded_duplicate"
    assert json.loads((stale_m4b / "job.json").read_text(encoding="utf-8"))["status"] == "superseded_duplicate"
    reasons = {row["reason"] for row in result["superseded"]["results"]}
    assert "superseded_waiting_voice_selection_duplicate" in reasons
    assert "superseded_m4b_ready_after_import" in reasons


def test_cleanup_finished_audiobook_jobs_keeps_newer_m4b_ready_when_import_is_older(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path))
    shared_sha = "same-book-sha"

    def _write_job(job_dir: Path, *, status: str, updated_at: str) -> None:
        job_dir.mkdir(parents=True)
        (job_dir / "job.json").write_text(
            json.dumps(
                {
                    "job_id": job_dir.name,
                    "status": status,
                    "updated_at": updated_at,
                    "source": {
                        "kind": "epub",
                        "source_sha256": shared_sha,
                    },
                    "metadata": {
                        "title": "Duplicate Book",
                        "author": "A. Writer",
                        "source_sha256": shared_sha,
                    },
                    "storage": {"job_dir": str(job_dir)},
                }
            ),
            encoding="utf-8",
        )

    older_imported = tmp_path / "job-older-imported"
    newer_m4b = tmp_path / "job-newer-m4b"
    _write_job(older_imported, status="audiobookshelf_imported", updated_at="2026-06-20T00:00:00Z")
    _write_job(newer_m4b, status="m4b_ready", updated_at="2026-06-22T00:00:00Z")

    result = pipeline.cleanup_finished_audiobook_jobs(
        force=True,
        now=datetime(2026, 6, 23, 12, 0, tzinfo=UTC),
    )

    assert result["superseded"]["status"] == "not_needed"
    assert result["superseded"]["cleaned_jobs"] == 0
    assert older_imported.exists()
    assert newer_m4b.exists()


def test_cleanup_finished_audiobook_jobs_prunes_older_imported_and_extracted_duplicates(
    monkeypatch, tmp_path: Path
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path))
    shared_sha = "same-book-sha"

    def _write_job(job_dir: Path, *, status: str, updated_at: str) -> None:
        job_dir.mkdir(parents=True)
        (job_dir / "job.json").write_text(
            json.dumps(
                {
                    "job_id": job_dir.name,
                    "status": status,
                    "updated_at": updated_at,
                    "next_action": "noop",
                    "source": {
                        "kind": "epub",
                        "source_sha256": shared_sha,
                    },
                    "metadata": {
                        "title": "Duplicate Book",
                        "author": "A. Writer",
                        "source_sha256": shared_sha,
                    },
                    "storage": {"job_dir": str(job_dir)},
                }
            ),
            encoding="utf-8",
        )

    stale_extracted = tmp_path / "job-stale-extracted"
    stale_imported = tmp_path / "job-stale-imported"
    current_imported = tmp_path / "job-current-imported"
    _write_job(stale_extracted, status="chapters_extracted", updated_at="2026-06-19T00:00:00Z")
    _write_job(stale_imported, status="audiobookshelf_imported", updated_at="2026-06-20T00:00:00Z")
    _write_job(current_imported, status="audiobookshelf_imported", updated_at="2026-06-22T00:00:00Z")

    result = pipeline.cleanup_finished_audiobook_jobs(
        force=True,
        now=datetime(2026, 6, 23, 12, 0, tzinfo=UTC),
    )

    assert result["superseded"]["status"] == "cleaned"
    assert result["superseded"]["cleaned_jobs"] == 2
    assert json.loads((stale_extracted / "job.json").read_text(encoding="utf-8"))["status"] == "superseded_duplicate"
    assert json.loads((stale_imported / "job.json").read_text(encoding="utf-8"))["status"] == "superseded_duplicate"
    reasons = {row["reason"] for row in result["superseded"]["results"]}
    assert "superseded_older_imported_duplicate" in reasons
    assert "superseded_chapters_extracted_after_import" in reasons


def test_cleanup_finished_audiobook_jobs_prunes_same_contact_resend_with_different_source_sha(
    monkeypatch, tmp_path: Path
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path))

    def _write_job(
        job_dir: Path,
        *,
        status: str,
        updated_at: str,
        source_sha: str,
        sender_ref: str = "4368120864006",
        chat_ref: str = "chat-ref-1",
    ) -> None:
        job_dir.mkdir(parents=True)
        (job_dir / "job.json").write_text(
            json.dumps(
                {
                    "job_id": job_dir.name,
                    "status": status,
                    "updated_at": updated_at,
                    "source": {
                        "kind": "epub",
                        "source_sha256": source_sha,
                    },
                    "metadata": {
                        "title": "Proof Book",
                        "author": "A. Writer",
                        "source_sha256": source_sha,
                    },
                    "totals": {
                        "chapter_count": 2,
                        "char_count": 115,
                    },
                    "whatsapp": {
                        "sender_ref": sender_ref,
                        "chat_ref": chat_ref,
                    },
                    "storage": {"job_dir": str(job_dir)},
                }
            ),
            encoding="utf-8",
        )

    stale_waiting = tmp_path / "job-stale-waiting"
    current_waiting = tmp_path / "job-current-waiting"
    _write_job(
        stale_waiting,
        status="waiting_voice_selection",
        updated_at="2026-06-20T00:00:00Z",
        source_sha="old-proof-sha",
    )
    _write_job(
        current_waiting,
        status="waiting_voice_selection",
        updated_at="2026-06-22T00:00:00Z",
        source_sha="new-proof-sha",
    )

    result = pipeline.cleanup_finished_audiobook_jobs(
        force=True,
        now=datetime(2026, 6, 23, 12, 0, tzinfo=UTC),
    )

    assert result["superseded"]["status"] == "cleaned"
    assert result["superseded"]["cleaned_jobs"] == 1
    assert json.loads((stale_waiting / "job.json").read_text(encoding="utf-8"))["status"] == "superseded_duplicate"
    assert json.loads((current_waiting / "job.json").read_text(encoding="utf-8"))["status"] == "waiting_voice_selection"
    assert result["superseded"]["results"][0]["reason"] == "superseded_waiting_voice_selection_duplicate"


def test_cleanup_finished_audiobook_jobs_keeps_same_title_different_contact_isolated(
    monkeypatch, tmp_path: Path
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path))
    shared_sha = "same-source-different-contact-sha"

    def _write_job(job_dir: Path, *, sender_ref: str, chat_ref: str, updated_at: str) -> None:
        job_dir.mkdir(parents=True)
        (job_dir / "job.json").write_text(
            json.dumps(
                {
                    "job_id": job_dir.name,
                    "status": "waiting_voice_selection",
                    "updated_at": updated_at,
                    "source": {
                        "kind": "epub",
                        "source_sha256": shared_sha,
                    },
                    "metadata": {
                        "title": "Proof Book",
                        "author": "A. Writer",
                        "source_sha256": shared_sha,
                    },
                    "totals": {
                        "chapter_count": 2,
                        "char_count": 115,
                    },
                    "whatsapp": {
                        "sender_ref": sender_ref,
                        "chat_ref": chat_ref,
                    },
                    "storage": {"job_dir": str(job_dir)},
                }
            ),
            encoding="utf-8",
        )

    first_job = tmp_path / "job-first"
    second_job = tmp_path / "job-second"
    _write_job(first_job, sender_ref="4368120864006", chat_ref="chat-ref-1", updated_at="2026-06-20T00:00:00Z")
    _write_job(second_job, sender_ref="4368120864999", chat_ref="chat-ref-2", updated_at="2026-06-22T00:00:00Z")

    result = pipeline.cleanup_finished_audiobook_jobs(
        force=True,
        now=datetime(2026, 6, 23, 12, 0, tzinfo=UTC),
    )

    assert result["superseded"]["status"] == "not_needed"
    assert result["superseded"]["cleaned_jobs"] == 0
    assert json.loads((first_job / "job.json").read_text(encoding="utf-8"))["status"] == "waiting_voice_selection"
    assert json.loads((second_job / "job.json").read_text(encoding="utf-8"))["status"] == "waiting_voice_selection"


def test_cleanup_finished_audiobook_jobs_does_not_cascade_waiting_cleanup_after_superseded_duplicate(
    monkeypatch, tmp_path: Path
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path))

    def _write_job(job_dir: Path, *, status: str, updated_at: str, source_sha: str) -> None:
        job_dir.mkdir(parents=True)
        (job_dir / "job.json").write_text(
            json.dumps(
                {
                    "job_id": job_dir.name,
                    "status": status,
                    "updated_at": updated_at,
                    "source": {
                        "kind": "epub",
                        "source_sha256": source_sha,
                    },
                    "metadata": {
                        "title": "Proof Book",
                        "author": "A. Writer",
                        "source_sha256": source_sha,
                    },
                    "totals": {
                        "chapter_count": 2,
                        "char_count": 115,
                    },
                    "whatsapp": {
                        "sender_ref": "4368120864006",
                        "chat_ref": "chat-ref-1",
                    },
                    "storage": {"job_dir": str(job_dir)},
                }
            ),
            encoding="utf-8",
        )

    already_superseded = tmp_path / "job-superseded"
    current_waiting = tmp_path / "job-current-waiting"
    _write_job(
        already_superseded,
        status="superseded_duplicate",
        updated_at="2026-06-23T04:30:52Z",
        source_sha="old-proof-sha",
    )
    _write_job(
        current_waiting,
        status="waiting_voice_selection",
        updated_at="2026-06-22T18:18:07Z",
        source_sha="new-proof-sha",
    )

    result = pipeline.cleanup_finished_audiobook_jobs(
        force=True,
        now=datetime(2026, 6, 23, 12, 0, tzinfo=UTC),
    )

    assert result["superseded"]["status"] == "not_needed"
    assert result["superseded"]["cleaned_jobs"] == 0
    assert json.loads((already_superseded / "job.json").read_text(encoding="utf-8"))["status"] == "superseded_duplicate"
    assert json.loads((current_waiting / "job.json").read_text(encoding="utf-8"))["status"] == "waiting_voice_selection"


def test_audiobook_cleanup_remove_path_tolerates_disappearing_files(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    target = tmp_path / "job-dir"
    nested = target / "audio"
    nested.mkdir(parents=True)
    disappearing = nested / "concat.txt"
    disappearing.write_text("gone soon", encoding="utf-8")

    real_rmtree = shutil.rmtree

    def _racing_rmtree(path: Path, *, onerror=None) -> None:
        disappearing.unlink(missing_ok=True)
        real_rmtree(path, onerror=onerror)

    monkeypatch.setattr(shutil, "rmtree", _racing_rmtree)

    removed_bytes = pipeline._audiobook_cleanup_remove_path(target)

    assert removed_bytes >= 0
    assert not target.exists()
