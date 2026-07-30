from __future__ import annotations

import errno
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import struct
import threading
import wave
import zipfile
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import pytest
from fastapi import HTTPException


def _write_minimal_epub(
    path: Path,
    *,
    title: str = "Test Book",
    author: str = "A. Writer",
    language: str = "en-US",
    chapter_one_html: str = "",
) -> None:
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
            f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>{title}</dc:title>
    <dc:creator>{author}</dc:creator>
    <dc:language>{language}</dc:language>
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
            chapter_one_html
            or "<html><head><title>Opening</title></head><body><h1>Opening</h1><p>Hello audiobook.</p></body></html>",
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


def _distinct_voice_wav_synthesizer(tmp_path: Path):
    audio_by_voice: dict[str, bytes] = {}

    def synthesize(**kwargs):
        voice_id = str(kwargs.get("voice_id") or "anonymous-voice")
        if voice_id not in audio_by_voice:
            voice_index = len(audio_by_voice) + 1
            path = tmp_path / f"distinct-voice-{voice_index:02d}.wav"
            _write_tone_wav(path, seconds=0.10 + (voice_index * 0.01))
            audio_by_voice[voice_id] = path.read_bytes()
        return audio_by_voice[voice_id], "audio/wav"

    return synthesize


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


def test_extract_epub_chapters_preserves_source_paragraphs_scenes_and_spans(tmp_path: Path) -> None:
    from app.services.audiobook_epub_pipeline import SOURCE_DOCUMENT_CONTRACT_NAME, extract_epub_chapters

    epub = tmp_path / "structured.epub"
    _write_minimal_epub(
        epub,
        chapter_one_html=(
            "<html><head><title>Opening</title></head><body>"
            "<h1>Opening</h1><p>First paragraph.</p><p>Second paragraph.</p>"
            "<hr/><p>New scene begins.</p></body></html>"
        ),
    )

    _metadata, chapters = extract_epub_chapters(
        epub_path=epub,
        chapter_dir=tmp_path / "chapters",
        source_filename="structured.epub",
    )

    first = chapters[0]
    text = (tmp_path / "chapters" / first.text_path).read_text(encoding="utf-8").strip()
    assert "Opening\n\nFirst paragraph.\n\nSecond paragraph.\n\n\nNew scene begins." in text
    assert first.structure_path.endswith(".source.json")
    source_document = json.loads(
        (tmp_path / "chapters" / first.structure_path).read_text(encoding="utf-8")
    )
    assert source_document["contract_name"] == SOURCE_DOCUMENT_CONTRACT_NAME
    assert source_document["source_href"] == first.source_href
    assert source_document["extracted_char_count"] == len(text)
    assert source_document["extracted_text_sha256"] == first.sha256
    assert source_document["scene_count"] == 2
    assert source_document["raw_source_text_embedded"] is False
    for block in source_document["blocks"]:
        source_span = text[block["char_start"] : block["char_end"]]
        assert len(source_span) == block["char_count"]
        assert source_span


def test_semantic_audiobook_chunks_prefer_complete_sentences() -> None:
    from app.services.audiobook_epub_pipeline import _semantic_text_chunks

    text = (
        "This opening sentence establishes a calm rhythm. "
        "The second sentence keeps the thought together. "
        "A final sentence closes the passage cleanly."
    )

    chunks = _semantic_text_chunks(text, max_chars=72)

    assert len(chunks) == 3
    assert all(chunk.endswith(".") for chunk in chunks)
    assert " ".join(chunks) == text


@pytest.mark.parametrize(
    "text",
    [
        '"Hello there," she said.',
        "“Hello there,” she said.",
        "„Guten Morgen“, sagte er.",
        "«Bonjour», dit-elle.",
        "— Spoken with an em dash.",
        "– Spoken with an en dash.",
    ],
)
def test_explicit_dialogue_classifier_accepts_only_balanced_explicit_dialogue(text: str) -> None:
    from app.services.audiobook_epub_pipeline import _explicit_dialogue_paragraph

    assert _explicit_dialogue_paragraph(text) is True


@pytest.mark.parametrize(
    "text",
    [
        'The narrator mentions "an inline quotation" here.',
        '"This quotation never closes.',
        "“This curly quotation never closes.",
        "“Malformed same-side quote “ remains uncertain.",
        "- A hyphen bullet is not dialogue.",
        "— — —",
        "Plain narration.",
    ],
)
def test_explicit_dialogue_classifier_falls_back_to_narrator_on_uncertainty(text: str) -> None:
    from app.services.audiobook_epub_pipeline import _explicit_dialogue_paragraph

    assert _explicit_dialogue_paragraph(text) is False


def test_dialogue_voice_requires_explicit_environment_or_private_approval(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    job_dir = tmp_path / "job"
    job_dir.mkdir()
    private_payload = {
        "contract_name": pipeline.VOICE_AUDITION_CONTRACT_NAME,
        "candidates": {
            "approved-token": {
                "candidate_key": "dialogue-candidate",
                "voice_id": "private-dialogue-voice",
                "voice_id_sha256": pipeline._sha256_bytes(b"private-dialogue-voice"),
            }
        },
    }
    pipeline._write_voice_audition_private(job_dir, private_payload)
    expires_at = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    job_payload = {
        "provider": {
            "dialogue_voice_selection": {
                "status": "selected_by_user",
                "approved_by_user": True,
                "revoked": False,
                "expires_at": expires_at,
                "selected_callback_token": "approved-token",
                "voice_id": "must-not-be-read-from-public-job",
            }
        }
    }
    (job_dir / "job.json").write_text(json.dumps(job_payload), encoding="utf-8")

    selected = pipeline._configured_dialogue_voice_selection(job_dir)

    assert selected == {
        "voice_id": "private-dialogue-voice",
        "source": "approved_private_dialogue_voice_selection",
        "status": "selected_by_user",
        "revoked": False,
        "expires_at": expires_at,
        "language": "",
        "supported_languages": [],
        "approved_by_user": True,
    }
    assert (job_dir / "voice_audition" / "private.json").stat().st_mode & 0o777 == 0o600
    job_payload["provider"]["dialogue_voice_selection"]["status"] = "pending"
    job_payload["provider"]["dialogue_voice_selection"]["approved_by_user"] = False
    (job_dir / "job.json").write_text(json.dumps(job_payload), encoding="utf-8")
    assert pipeline._configured_dialogue_voice_selection(job_dir) == {}

    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_DIALOGUE_VOICE_ID", "operator-dialogue-voice")
    assert pipeline._configured_dialogue_voice_selection(job_dir) == {
        "voice_id": "operator-dialogue-voice",
        "source": "explicit_operator_environment",
        "revoked": False,
    }


def test_render_uses_distinct_dialogue_voice_and_private_source_complete_plan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import EpubChapter, EpubMetadata

    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_CINEMATIC_NARRATION", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_DIALOGUE_VOICE_ID", "dialogue-voice-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_MAX_CHARS_PER_REQUEST", "1000")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {
                    "voice_id": "narrator-voice-secret",
                    "label": "Narrator",
                    "language": "en-US",
                    "tags": ["audiobook", "narration", "neutral"],
                    "default": True,
                },
                {
                    "voice_id": "dialogue-voice-secret",
                    "label": "Dialogue actor",
                    "language": "en-US",
                    "tags": ["audiobook", "dialogue"],
                },
            ]
        ),
    )
    chapter_dir = tmp_path / "chapters"
    chapter_dir.mkdir()
    text = "\n\n".join(
        [
            "Narration opens the scene.",
            '"Hello there," she said.',
            'The narrator mentions "an inline quotation" here.',
            "— A second speaker answers.",
            "“This uncertain quotation never closes.",
        ]
    )
    text_path = chapter_dir / "001 - Dialogue.txt"
    text_path.write_text(text, encoding="utf-8")
    chapter = EpubChapter(
        index=1,
        title="Dialogue",
        source_href="dialogue.xhtml",
        text_path=text_path.name,
        audio_filename="001 - Dialogue.wav",
        char_count=len(text),
        sha256=pipeline._sha256_bytes(text.encode("utf-8")),
    )
    metadata = EpubMetadata(
        title="Dialogue Book",
        author="A. Writer",
        language="en-US",
        source_filename="dialogue.epub",
        source_sha256="source-sha",
    )
    tone = tmp_path / "tone.wav"
    _write_tone_wav(tone)
    synthesis_calls: list[dict[str, object]] = []

    def fake_synthesize_request(**kwargs):
        synthesis_calls.append(dict(kwargs))
        return tone.read_bytes(), "audio/wav"

    def fake_write_silence(path, *, seconds, sample_rate=44100):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(tone.read_bytes())
        return path

    def fake_merge_segments(*, segment_paths, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(Path(segment_paths[0]).read_bytes())
        return True

    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", fake_synthesize_request)
    monkeypatch.setattr(pipeline, "_write_silence_wav", fake_write_silence)
    monkeypatch.setattr(pipeline, "_merge_audio_segments_to_wav", fake_merge_segments)

    result = pipeline.render_unmixr_chapter_audio(
        job_dir=tmp_path,
        chapters=(chapter,),
        metadata=metadata,
    )

    assert result["status"] == "rendered"
    assert [row["voice_id"] for row in synthesis_calls] == [
        "narrator-voice-secret",
        "dialogue-voice-secret",
        "narrator-voice-secret",
        "dialogue-voice-secret",
        "narrator-voice-secret",
    ]
    assert result["dialogue_voice_selection"]["distinct_from_narrator"] is True
    assert result["chapters"][0]["dialogue_passage_count"] == 2
    plan_path = tmp_path / result["narration_plan"]["path"]
    assert plan_path.stat().st_mode & 0o777 == 0o600
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert plan["source_coverage"] == "complete"
    assert plan["dialogue_passage_count"] == 2
    assert [row["speaker_role"] for row in plan["passages"]] == [
        "narrator",
        "dialogue",
        "narrator",
        "dialogue",
        "narrator",
    ]
    serialized_plan = plan_path.read_text(encoding="utf-8")
    serialized_result = json.dumps(result, sort_keys=True)
    for raw_voice_id in ("narrator-voice-secret", "dialogue-voice-secret"):
        assert raw_voice_id not in serialized_plan
        assert raw_voice_id not in serialized_result


def test_automatic_multispeaker_cast_ignores_unreviewed_source_demographics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import EpubChapter, EpubMetadata

    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_CINEMATIC_NARRATION", "0")
    monkeypatch.delenv("EA_AUDIOBOOK_UNMIXR_DIALOGUE_VOICE_ID", raising=False)
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {
                    "voice_id": "narrator-id",
                    "label": "Narrator",
                    "language": "en-US",
                    "tags": ["narration", "neutral"],
                    "default": True,
                },
                {
                    "voice_id": "anna-id",
                    "label": "Young Woman",
                    "language": "en-US",
                    "tags": ["dialogue", "female", "young_adult", "warm"],
                },
                {
                    "voice_id": "ben-id",
                    "label": "Second Actor",
                    "language": "en-US",
                    "tags": ["dialogue", "male", "adult", "clear"],
                },
            ]
        ),
    )
    text = '“Come,” said Anna, a young adult woman. “Wait,” Ben replied.'
    chapter_dir = tmp_path / "chapters"
    chapter_dir.mkdir()
    (chapter_dir / "001.txt").write_text(text, encoding="utf-8")
    chapter = EpubChapter(
        index=1,
        title="Two Speakers",
        source_href="chapter.xhtml",
        text_path="001.txt",
        audio_filename="001.wav",
        char_count=len(text),
        sha256=pipeline._sha256_bytes(text.encode("utf-8")),
    )
    metadata = EpubMetadata(
        title="Automatic Cast",
        author="A. Writer",
        language="en-US",
        source_filename="book.epub",
        source_sha256="source-sha",
    )
    tone = tmp_path / "tone.wav"
    _write_tone_wav(tone)
    calls: list[tuple[str, str]] = []

    def fake_synthesize_request(**kwargs):
        calls.append((str(kwargs["text"]), str(kwargs["voice_id"])))
        return tone.read_bytes(), "audio/wav"

    def fake_merge(*, segment_paths, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(Path(segment_paths[0]).read_bytes())
        return True

    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", fake_synthesize_request)
    monkeypatch.setattr(pipeline, "_merge_audio_segments_to_wav", fake_merge)
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)

    result = pipeline.render_unmixr_chapter_audio(
        job_dir=tmp_path,
        chapters=(chapter,),
        metadata=metadata,
    )

    by_text = {spoken_text: voice_id for spoken_text, voice_id in calls}
    assert result["status"] == "rendered"
    assert {
        by_text["“Come,”"],
        by_text["“Wait,”"],
    } == {"anna-id", "ben-id"}
    assert by_text["“Come,”"] != by_text["“Wait,”"]
    assert result["speaker_cast"]["speaker_count"] == 2
    assert result["speaker_cast"]["distinct_dialogue_voice_count"] == 2
    assert result["speaker_cast"]["narrator_voice_excluded"] is True
    public_json = json.dumps(result, sort_keys=True)
    for raw_voice_id in ("narrator-id", "anna-id", "ben-id"):
        assert raw_voice_id not in public_json


def test_selective_repair_reuses_unchanged_single_passage_chapter(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import EpubChapter, EpubMetadata

    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_CINEMATIC_NARRATION", "0")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {
                    "voice_id": "narrator-voice",
                    "label": "Narrator",
                    "language": "en-US",
                    "tags": ["audiobook", "narration", "neutral"],
                    "default": True,
                }
            ]
        ),
    )
    chapter_dir = tmp_path / "chapters"
    chapter_dir.mkdir()
    first_text = "Chapter one remains exactly unchanged."
    second_text = "Chapter two begins with this version."
    (chapter_dir / "001.txt").write_text(first_text, encoding="utf-8")
    (chapter_dir / "002.txt").write_text(second_text, encoding="utf-8")

    def chapter(index: int, text: str) -> EpubChapter:
        return EpubChapter(
            index=index,
            title=f"Chapter {index}",
            source_href=f"chapter-{index}.xhtml",
            text_path=f"{index:03d}.txt",
            audio_filename=f"{index:03d}.wav",
            char_count=len(text),
            sha256=pipeline._sha256_bytes(text.encode("utf-8")),
        )

    metadata = EpubMetadata(
        title="Selective Repair",
        author="A. Writer",
        language="en-US",
        source_filename="book.epub",
        source_sha256="source-sha",
    )
    tone = tmp_path / "tone.wav"
    _write_tone_wav(tone)
    calls: list[str] = []

    def fake_synthesize_request(**kwargs):
        calls.append(str(kwargs["text"]))
        return tone.read_bytes(), "audio/wav"

    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", fake_synthesize_request)
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)

    initial = pipeline.render_unmixr_chapter_audio(
        job_dir=tmp_path,
        chapters=(chapter(1, first_text), chapter(2, second_text)),
        metadata=metadata,
    )
    assert initial["status"] == "rendered"
    assert calls == [first_text, second_text]

    changed_text = "Chapter two now contains a repaired passage."
    (chapter_dir / "002.txt").write_text(changed_text, encoding="utf-8")
    calls.clear()
    repaired = pipeline.render_unmixr_chapter_audio(
        job_dir=tmp_path,
        chapters=(chapter(1, first_text), chapter(2, changed_text)),
        metadata=metadata,
    )

    assert repaired["status"] == "rendered"
    assert calls == [changed_text]
    assert repaired["chapters"][0]["status"] == "already_present"
    assert repaired["chapters"][1]["stale_master_rebuilt"] is True


def test_failed_cached_segment_passage_is_selectively_regenerated(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import EpubChapter, EpubMetadata

    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_CINEMATIC_NARRATION", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_BATCH_PARAGRAPHS_WITH_NATURAL_PAUSES", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "0")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {
                    "voice_id": "narrator-voice",
                    "label": "Narrator",
                    "language": "en-US",
                    "tags": ["audiobook", "narration", "neutral"],
                    "default": True,
                }
            ]
        ),
    )
    first_passage = "First cached passage remains valid source text."
    second_passage = "Second cached passage remains reusable."
    text = f"{first_passage}\n\n{second_passage}"
    chapter_dir = tmp_path / "chapters"
    chapter_dir.mkdir()
    (chapter_dir / "001.txt").write_text(text, encoding="utf-8")
    chapter = EpubChapter(
        index=1,
        title="Selective passage repair",
        source_href="chapter.xhtml",
        text_path="001.txt",
        audio_filename="001.wav",
        char_count=len(text),
        sha256=pipeline._sha256_bytes(text.encode("utf-8")),
    )
    metadata = EpubMetadata(
        title="Selective passage repair",
        author="A. Writer",
        language="en-US",
        source_filename="book.epub",
        source_sha256="source-sha",
    )
    tone = tmp_path / "tone.wav"
    _write_tone_wav(tone)
    calls: list[str] = []

    def fake_synthesize_request(**kwargs):
        calls.append(str(kwargs["text"]))
        return tone.read_bytes(), "audio/wav"

    def fake_merge(*, segment_paths, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(Path(segment_paths[0]).read_bytes())
        return True

    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", fake_synthesize_request)
    monkeypatch.setattr(pipeline, "_merge_audio_segments_to_wav", fake_merge)
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)

    initial = pipeline.render_unmixr_chapter_audio(
        job_dir=tmp_path,
        chapters=(chapter,),
        metadata=metadata,
    )
    assert initial["status"] == "rendered"
    assert calls == [first_passage, second_passage]

    first_fingerprint = pipeline._segment_render_fingerprint(
        text=first_passage,
        voice_id="narrator-voice",
        speaker_role="narrator",
        speaker_id="narrator",
        render_language="en-US",
    )
    failed_cache = (
        tmp_path
        / "audio"
        / "001-parts"
        / f"passage-{first_fingerprint}.wav"
    )
    failed_cache.write_bytes(b"not-a-readable-wav")
    (tmp_path / "audio" / "001.wav").unlink()
    (tmp_path / "audio" / "001.wav.narration.signature").unlink()

    calls.clear()
    repaired = pipeline.render_unmixr_chapter_audio(
        job_dir=tmp_path,
        chapters=(chapter,),
        metadata=metadata,
    )

    assert repaired["status"] == "rendered"
    assert calls == [first_passage]
    assert repaired["chapters"][0]["invalid_cached_passage_count"] == 1
    assert repaired["chapters"][0]["reused_passage_count"] == 1
    assert repaired["chapters"][0]["regenerated_passage_count"] == 1


def _prepare_offline_cached_passage_render(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    text: str,
    cinematic: bool,
):
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import EpubChapter, EpubMetadata

    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_CINEMATIC_NARRATION", "1" if cinematic else "0")
    monkeypatch.setenv("EA_AUDIOBOOK_CINEMATIC_SINGLE_PASS", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_BATCH_PARAGRAPHS_WITH_NATURAL_PAUSES", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_AUDIO_QUALITY_REPORT_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_RETRY_COUNT", "1")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {
                    "voice_id": "narrator-voice",
                    "label": "Narrator",
                    "language": "en-US",
                    "tags": ["audiobook", "narration", "neutral"],
                    "default": True,
                }
            ]
        ),
    )
    chapter_dir = tmp_path / "chapters"
    chapter_dir.mkdir()
    (chapter_dir / "001.txt").write_text(text, encoding="utf-8")
    chapter = EpubChapter(
        index=1,
        title="Offline cache repair",
        source_href="chapter.xhtml",
        text_path="001.txt",
        audio_filename="001.wav",
        char_count=len(text),
        sha256=pipeline._sha256_bytes(text.encode("utf-8")),
    )
    metadata = EpubMetadata(
        title="Offline cache repair",
        author="A. Writer",
        language="en-US",
        source_filename="book.epub",
        source_sha256="source-sha",
    )
    tone = tmp_path / "tone.wav"
    _write_tone_wav(tone)
    calls: list[str] = []

    def fake_synthesize_request(**kwargs):
        calls.append(str(kwargs["text"]))
        return tone.read_bytes(), "audio/wav"

    def fake_merge(*, segment_paths, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(Path(segment_paths[0]).read_bytes())
        return True

    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", fake_synthesize_request)
    monkeypatch.setattr(pipeline, "_merge_audio_segments_to_wav", fake_merge)
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)
    return pipeline, chapter, metadata, calls


def test_valid_cached_cinematic_master_reuses_without_synthesis_or_merge(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    text = "A valid cinematic master must be reused exactly as rendered."
    pipeline, chapter, metadata, calls = _prepare_offline_cached_passage_render(
        monkeypatch,
        tmp_path,
        text=text,
        cinematic=True,
    )
    initial = pipeline.render_unmixr_chapter_audio(
        job_dir=tmp_path,
        chapters=(chapter,),
        metadata=metadata,
    )
    assert initial["status"] == "rendered"
    assert calls == [text]

    calls.clear()

    def fail_merge(**_kwargs):
        raise AssertionError("a valid signed cinematic master must not be rebuilt")

    monkeypatch.setattr(pipeline, "_merge_audio_segments_to_wav", fail_merge)

    reused = pipeline.render_unmixr_chapter_audio(
        job_dir=tmp_path,
        chapters=(chapter,),
        metadata=metadata,
    )

    assert reused["status"] == "already_rendered"
    assert reused["reason"] == "cinematic_master_present"
    assert reused["chapters"][0]["status"] == "already_present"
    assert reused["mastering"]["final_track_mastered_this_run_count"] == 0
    assert calls == []


def test_structurally_valid_swapped_passage_is_not_falsely_reused(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    text = "A structurally valid swapped passage must be regenerated from its source."
    pipeline, chapter, metadata, calls = _prepare_offline_cached_passage_render(
        monkeypatch,
        tmp_path,
        text=text,
        cinematic=False,
    )
    initial = pipeline.render_unmixr_chapter_audio(
        job_dir=tmp_path,
        chapters=(chapter,),
        metadata=metadata,
    )
    assert initial["status"] == "rendered"
    fingerprint = pipeline._segment_render_fingerprint(
        text=text,
        voice_id="narrator-voice",
        speaker_role="narrator",
        speaker_id="narrator",
        render_language="en-US",
    )
    cached_passage = (
        tmp_path / "audio" / "001-parts" / f"passage-{fingerprint}.wav"
    )
    output_binding_path = pipeline._audio_cache_output_binding_path(
        cached_passage
    )
    original_binding = json.loads(
        output_binding_path.read_text(encoding="utf-8")
    )
    assert output_binding_path.stat().st_mode & 0o777 == 0o600
    assert original_binding["audio_sha256"] == pipeline._sha256_file(
        cached_passage
    )

    swapped_wav = tmp_path / "swapped-passage.wav"
    _write_tone_wav(swapped_wav, seconds=0.21, sample_rate=22050)
    cached_passage.write_bytes(swapped_wav.read_bytes())
    swapped_sha256 = pipeline._sha256_file(cached_passage)
    assert swapped_sha256 != original_binding["audio_sha256"]
    assert pipeline._rendered_audio_quality_report(cached_passage)["status"] != "failed"
    (tmp_path / "audio" / "001.wav").unlink()
    (tmp_path / "audio" / "001.wav.narration.signature").unlink()

    calls.clear()
    repaired = pipeline.render_unmixr_chapter_audio(
        job_dir=tmp_path,
        chapters=(chapter,),
        metadata=metadata,
    )

    assert repaired["status"] == "rendered"
    assert calls == [text]
    assert repaired["chapters"][0]["reused_passage_count"] == 0
    assert repaired["chapters"][0]["regenerated_passage_count"] == 1
    assert repaired["chapters"][0]["invalid_cached_passage_count"] == 1
    repaired_binding = pipeline._load_validated_audio_cache_output_binding(
        audio_path=cached_passage,
        cache_kind="passage",
        render_fingerprint=fingerprint,
    )
    assert repaired_binding
    assert repaired_binding["audio_sha256"] != swapped_sha256


@pytest.mark.parametrize("cinematic", [False, True])
def test_structurally_valid_swapped_final_master_rebuilds_from_bound_passage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    cinematic: bool,
) -> None:
    text = "A swapped final master must rebuild without another paid synthesis call."
    pipeline, chapter, metadata, calls = _prepare_offline_cached_passage_render(
        monkeypatch,
        tmp_path,
        text=text,
        cinematic=cinematic,
    )
    initial = pipeline.render_unmixr_chapter_audio(
        job_dir=tmp_path,
        chapters=(chapter,),
        metadata=metadata,
    )
    assert initial["status"] == "rendered"
    master = (
        Path(str(initial["cinematic_master_audio"]))
        if cinematic
        else tmp_path / "audio" / "001.wav"
    )
    render_fingerprint = (
        (tmp_path / "audio" / "_cinematic_master.signature")
        if cinematic
        else tmp_path / "audio" / "001.wav.narration.signature"
    ).read_text(encoding="utf-8").strip()
    original_binding = pipeline._load_validated_audio_cache_output_binding(
        audio_path=master,
        cache_kind="cinematic_master" if cinematic else "chapter_master",
        render_fingerprint=render_fingerprint,
    )
    assert original_binding

    swapped_wav = tmp_path / "swapped-master.wav"
    _write_tone_wav(swapped_wav, seconds=0.23, sample_rate=22050)
    master.write_bytes(swapped_wav.read_bytes())
    swapped_sha256 = pipeline._sha256_file(master)
    assert swapped_sha256 != original_binding["audio_sha256"]
    assert pipeline._rendered_audio_quality_report(master)["status"] != "failed"
    if cinematic:
        assert pipeline._discover_or_build_cinematic_master_audio(
            job_dir=tmp_path,
            chapters=(chapter,),
        ) is None
    else:
        assert not pipeline._signed_chapter_master_output_bindings_ready(
            job_dir=tmp_path,
            chapters=(chapter,),
        )

    calls.clear()
    repaired = pipeline.render_unmixr_chapter_audio(
        job_dir=tmp_path,
        chapters=(chapter,),
        metadata=metadata,
    )

    assert repaired["status"] == "rendered"
    assert calls == []
    assert repaired["chapters"][0]["status"] == "rendered"
    assert repaired["chapters"][0]["stale_master_rebuilt"] is True
    assert repaired["cache"]["reused_passage_count"] == 1
    repaired_binding = pipeline._load_validated_audio_cache_output_binding(
        audio_path=master,
        cache_kind="cinematic_master" if cinematic else "chapter_master",
        render_fingerprint=render_fingerprint,
    )
    assert repaired_binding
    assert repaired_binding["audio_sha256"] != swapped_sha256
    signature_row = (
        {
            "track": "cinematic_master",
            "signature": render_fingerprint,
            "audio_sha256": repaired_binding["audio_sha256"],
        }
        if cinematic
        else {
            "chapter_index": chapter.index,
            "signature": render_fingerprint,
            "audio_sha256": repaired_binding["audio_sha256"],
        }
    )
    assert repaired["mastering"]["signature_set_sha256"] == (
        pipeline._sha256_bytes(
            json.dumps(
                [signature_row],
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
    )


@pytest.mark.parametrize("cinematic", [False, True])
def test_missing_legacy_master_output_binding_rebuilds_without_synthesis(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    cinematic: bool,
) -> None:
    text = "A legacy master without an output digest must rebuild from its passage."
    pipeline, chapter, metadata, calls = _prepare_offline_cached_passage_render(
        monkeypatch,
        tmp_path,
        text=text,
        cinematic=cinematic,
    )
    initial = pipeline.render_unmixr_chapter_audio(
        job_dir=tmp_path,
        chapters=(chapter,),
        metadata=metadata,
    )
    assert initial["status"] == "rendered"
    master = (
        Path(str(initial["cinematic_master_audio"]))
        if cinematic
        else tmp_path / "audio" / "001.wav"
    )
    pipeline._audio_cache_output_binding_path(master).unlink()

    calls.clear()
    repaired = pipeline.render_unmixr_chapter_audio(
        job_dir=tmp_path,
        chapters=(chapter,),
        metadata=metadata,
    )

    assert repaired["status"] == "rendered"
    assert calls == []
    assert repaired["chapters"][0]["stale_master_rebuilt"] is True
    assert repaired["cache"]["reused_passage_count"] == 1
    assert (
        pipeline._audio_cache_output_binding_path(master).stat().st_mode
        & 0o777
        == 0o600
    )


def test_failed_cached_cinematic_passage_is_selectively_regenerated(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    first_passage = "First cinematic passage must be repaired."
    second_passage = "Second cinematic passage remains reusable."
    text = f"{first_passage}\n\n{second_passage}"
    pipeline, chapter, metadata, calls = _prepare_offline_cached_passage_render(
        monkeypatch,
        tmp_path,
        text=text,
        cinematic=True,
    )
    initial = pipeline.render_unmixr_chapter_audio(
        job_dir=tmp_path,
        chapters=(chapter,),
        metadata=metadata,
    )
    assert initial["status"] == "rendered"
    assert calls == [first_passage, second_passage]

    first_fingerprint = pipeline._segment_render_fingerprint(
        text=first_passage,
        voice_id="narrator-voice",
        speaker_role="narrator",
        speaker_id="narrator",
        render_language="en-US",
    )
    failed_cache = (
        tmp_path
        / "audio"
        / "_cinematic-parts"
        / f"passage-{first_fingerprint}.wav"
    )
    failed_cache.write_bytes(b"not-a-readable-wav")
    Path(str(initial["cinematic_master_audio"])).unlink()

    calls.clear()
    repaired = pipeline.render_unmixr_chapter_audio(
        job_dir=tmp_path,
        chapters=(chapter,),
        metadata=metadata,
    )

    assert repaired["status"] == "rendered"
    assert calls == [first_passage]
    assert repaired["cache"] == {
        "reused_passage_count": 1,
        "regenerated_passage_count": 1,
        "invalid_cached_passage_count": 1,
    }
    assert repaired["chapters"][0]["invalid_cached_passage_count"] == 1


@pytest.mark.parametrize("cinematic", [False, True])
@pytest.mark.parametrize(
    "corrupt_master_payload",
    [b"not-a-readable-wav", b""],
    ids=["malformed", "zero-byte"],
)
def test_corrupt_signed_master_is_rebuilt_before_cache_reuse(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    cinematic: bool,
    corrupt_master_payload: bytes,
) -> None:
    text = "A cached passage can rebuild a corrupt signed master."
    pipeline, chapter, metadata, calls = _prepare_offline_cached_passage_render(
        monkeypatch,
        tmp_path,
        text=text,
        cinematic=cinematic,
    )
    initial = pipeline.render_unmixr_chapter_audio(
        job_dir=tmp_path,
        chapters=(chapter,),
        metadata=metadata,
    )
    assert initial["status"] == "rendered"
    master = (
        Path(str(initial["cinematic_master_audio"]))
        if cinematic
        else tmp_path / "audio" / "001.wav"
    )
    master.write_bytes(corrupt_master_payload)

    calls.clear()
    repaired = pipeline.render_unmixr_chapter_audio(
        job_dir=tmp_path,
        chapters=(chapter,),
        metadata=metadata,
    )

    assert repaired["status"] == "rendered"
    assert calls == []
    assert repaired["chapters"][0]["stale_master_rebuilt"] is True
    assert repaired["cache"]["reused_passage_count"] == 1
    assert pipeline._rendered_audio_quality_report(master)["status"] != "failed"


def test_playable_heuristic_failed_cache_blocks_without_paid_regeneration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    text = "Playable cached audio remains intact for quality review."
    pipeline, chapter, metadata, calls = _prepare_offline_cached_passage_render(
        monkeypatch,
        tmp_path,
        text=text,
        cinematic=False,
    )
    initial = pipeline.render_unmixr_chapter_audio(
        job_dir=tmp_path,
        chapters=(chapter,),
        metadata=metadata,
    )
    assert initial["status"] == "rendered"
    fingerprint = pipeline._segment_render_fingerprint(
        text=text,
        voice_id="narrator-voice",
        speaker_role="narrator",
        speaker_id="narrator",
        render_language="en-US",
    )
    cached_passage = tmp_path / "audio" / "001-parts" / f"passage-{fingerprint}.wav"
    cached_bytes = cached_passage.read_bytes()
    (tmp_path / "audio" / "001.wav").unlink()
    (tmp_path / "audio" / "001.wav.narration.signature").unlink()
    original_quality_report = pipeline._rendered_audio_quality_report

    def heuristic_failure(path: Path):
        if path == cached_passage:
            return {"status": "failed", "issues": ["clipping"]}
        return original_quality_report(path)

    monkeypatch.setattr(pipeline, "_rendered_audio_quality_report", heuristic_failure)
    calls.clear()
    blocked = pipeline.render_unmixr_chapter_audio(
        job_dir=tmp_path,
        chapters=(chapter,),
        metadata=metadata,
    )

    assert blocked["status"] == "blocked"
    assert blocked["reason"] == "cached_passage_audio_quality_failed"
    assert blocked["audio_quality"]["issues"] == ["clipping"]
    assert blocked["cache"]["invalid_cached_passage_count"] == 0
    assert calls == []
    assert cached_passage.read_bytes() == cached_bytes


def test_provider_blocked_structural_repair_keeps_cache_and_counter(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    text = "A corrupt passage remains receipted when its repair provider blocks."
    pipeline, chapter, metadata, calls = _prepare_offline_cached_passage_render(
        monkeypatch,
        tmp_path,
        text=text,
        cinematic=False,
    )
    initial = pipeline.render_unmixr_chapter_audio(
        job_dir=tmp_path,
        chapters=(chapter,),
        metadata=metadata,
    )
    assert initial["status"] == "rendered"
    fingerprint = pipeline._segment_render_fingerprint(
        text=text,
        voice_id="narrator-voice",
        speaker_role="narrator",
        speaker_id="narrator",
        render_language="en-US",
    )
    failed_cache = tmp_path / "audio" / "001-parts" / f"passage-{fingerprint}.wav"
    failed_payload = b"not-a-readable-wav"
    failed_cache.write_bytes(failed_payload)
    (tmp_path / "audio" / "001.wav").unlink()
    (tmp_path / "audio" / "001.wav.narration.signature").unlink()
    provider_calls: list[str] = []

    def blocked_provider(**kwargs):
        provider_calls.append(str(kwargs["text"]))
        raise RuntimeError("unmixr_synthesize_upstream_unavailable")

    monkeypatch.setattr(pipeline, "_synthesize_unmixr_with_retries", blocked_provider)
    calls.clear()
    blocked = pipeline.render_unmixr_chapter_audio(
        job_dir=tmp_path,
        chapters=(chapter,),
        metadata=metadata,
    )

    assert blocked["status"] == "blocked"
    assert blocked["cache"]["invalid_cached_passage_count"] == 1
    assert provider_calls == [text]
    assert calls == []
    assert failed_cache.read_bytes() == failed_payload


@pytest.mark.parametrize("cinematic", [False, True])
def test_invalid_provider_repair_is_atomic_and_preserves_zero_byte_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    cinematic: bool,
) -> None:
    text = "A structurally invalid provider repair never replaces the old cache."
    pipeline, chapter, metadata, calls = _prepare_offline_cached_passage_render(
        monkeypatch,
        tmp_path,
        text=text,
        cinematic=cinematic,
    )
    initial = pipeline.render_unmixr_chapter_audio(
        job_dir=tmp_path,
        chapters=(chapter,),
        metadata=metadata,
    )
    assert initial["status"] == "rendered"
    fingerprint = pipeline._segment_render_fingerprint(
        text=text,
        voice_id="narrator-voice",
        speaker_role="narrator",
        speaker_id="narrator",
        render_language="en-US",
    )
    cache_dir = "_cinematic-parts" if cinematic else "001-parts"
    failed_cache = tmp_path / "audio" / cache_dir / f"passage-{fingerprint}.wav"
    failed_cache.write_bytes(b"")
    if cinematic:
        Path(str(initial["cinematic_master_audio"])).unlink()
    else:
        (tmp_path / "audio" / "001.wav").unlink()
        (tmp_path / "audio" / "001.wav.narration.signature").unlink()
    provider_calls: list[str] = []

    def corrupt_provider(**kwargs):
        provider_calls.append(str(kwargs["text"]))
        return b"not-a-readable-wav", "audio/wav", []

    monkeypatch.setattr(pipeline, "_synthesize_unmixr_with_retries", corrupt_provider)
    calls.clear()
    blocked = pipeline.render_unmixr_chapter_audio(
        job_dir=tmp_path,
        chapters=(chapter,),
        metadata=metadata,
    )

    assert blocked["status"] == "blocked"
    assert blocked["reason"] == "provider_segment_audio_invalid"
    assert blocked["cache"]["invalid_cached_passage_count"] == 1
    assert blocked["cache"]["regenerated_passage_count"] == 0
    assert provider_calls == [text]
    assert calls == []
    assert failed_cache.read_bytes() == b""


def test_receipt_prefers_top_level_cache_aggregate_over_shared_chapter_rows(
    tmp_path: Path,
) -> None:
    from app.services.audiobook_epub_pipeline import (
        _sha256_bytes,
        build_audiobook_job_receipt,
    )

    (tmp_path / "audio").mkdir()
    (tmp_path / "output").mkdir()
    job = {
        "job_id": "cache-receipt",
        "status": "rendered",
        "render_result": {
            "status": "rendered",
            "cache": {
                "reused_passage_count": 1,
                "regenerated_passage_count": 1,
                "invalid_cached_passage_count": 1,
            },
            "chapters": [
                {
                    "chapter": 1,
                    "path": "cinematic-master.wav",
                    "reused_passage_count": 1,
                    "regenerated_passage_count": 1,
                    "invalid_cached_passage_count": 1,
                    "stale_master_rebuilt": True,
                },
                {
                    "chapter": 2,
                    "path": "cinematic-master.wav",
                    "reused_passage_count": 1,
                    "regenerated_passage_count": 1,
                    "invalid_cached_passage_count": 1,
                    "stale_master_rebuilt": True,
                },
            ],
        },
    }
    (tmp_path / "job.json").write_text(json.dumps(job), encoding="utf-8")

    receipt = build_audiobook_job_receipt(
        job_dir=tmp_path,
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert receipt["render"]["cache"]["reused_passage_count"] == 1
    assert receipt["render"]["cache"]["regenerated_passage_count"] == 1
    assert receipt["render"]["cache"]["invalid_cached_passage_count"] == 1
    assert receipt["render"]["cache"]["stale_master_rebuilt_count"] == 1


def test_successful_audiobook_receipt_does_not_claim_external_tts_blocker(
    tmp_path: Path,
) -> None:
    from app.services.audiobook_epub_pipeline import build_audiobook_job_receipt

    (tmp_path / "audio").mkdir()
    (tmp_path / "output").mkdir()
    job = {
        "job_id": "successful-receipt",
        "status": "m4b_ready",
        "next_action": "continue_audiobook_job",
        "render_result": {
            "status": "rendered",
            "provider": "unmixr_ai",
        },
        "merge_result": {
            "status": "m4b_ready",
        },
    }
    (tmp_path / "job.json").write_text(json.dumps(job), encoding="utf-8")

    receipt = build_audiobook_job_receipt(
        job_dir=tmp_path,
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert receipt["render"]["external_tts_blocker_code"] == ""
    assert receipt["render"]["external_tts_blocker_reason_sha256"] == ""
    assert receipt["render"]["external_tts_blocker_retryable"] is False
    assert receipt["scheduler_resume"]["external_tts_blocker_code"] == ""
    assert receipt["scheduler_resume"]["external_tts_blocker_retryable"] is False


def test_cinematic_semantic_pass_preserves_exact_source_whitespace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import EpubChapter, EpubMetadata

    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_CINEMATIC_NARRATION", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_CINEMATIC_SINGLE_PASS", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "0")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {
                    "voice_id": "narrator-voice",
                    "label": "Narrator",
                    "language": "en-US",
                    "tags": ["audiobook", "narration", "neutral"],
                    "default": True,
                }
            ]
        ),
    )
    text = "  Exact authorial edge spacing remains in the render input.  "
    chapter_dir = tmp_path / "chapters"
    chapter_dir.mkdir()
    (chapter_dir / "001.txt").write_text(text, encoding="utf-8")
    chapter = EpubChapter(
        index=1,
        title="Exact source",
        source_href="chapter.xhtml",
        text_path="001.txt",
        audio_filename="001.wav",
        char_count=len(text),
        sha256=pipeline._sha256_bytes(text.encode("utf-8")),
    )
    metadata = EpubMetadata(
        title="Exact source",
        author="A. Writer",
        language="en-US",
        source_filename="book.epub",
        source_sha256="source-sha",
    )
    tone = tmp_path / "tone.wav"
    _write_tone_wav(tone)
    calls: list[str] = []

    def fake_synthesize_request(**kwargs):
        calls.append(str(kwargs["text"]))
        return tone.read_bytes(), "audio/wav"

    def fake_merge(*, segment_paths, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(Path(segment_paths[0]).read_bytes())
        return True

    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", fake_synthesize_request)
    monkeypatch.setattr(pipeline, "_merge_audio_segments_to_wav", fake_merge)
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)

    result = pipeline.render_unmixr_chapter_audio(
        job_dir=tmp_path,
        chapters=(chapter,),
        metadata=metadata,
    )

    assert result["status"] == "rendered"
    assert calls == [text]


def test_chapter_master_signature_binds_all_policy_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import EpubChapter

    chapter = EpubChapter(
        index=1,
        title="Chapter",
        source_href="chapter.xhtml",
        text_path="001.txt",
        audio_filename="001.wav",
        char_count=8,
        sha256="c" * 64,
    )
    rows = (
        {
            "text": "“Hello.”",
            "speaker_role": "dialogue",
            "speaker_id": "speaker_anna",
            "boundary_kind_after": "speaker",
            "pause_seconds_after": 0.22,
        },
    )
    private_cast = {
        "speaker_anna": {
            "voice_id": "dialogue-voice",
            "voice_id_sha256": pipeline._sha256_bytes(b"dialogue-voice"),
        }
    }
    first = pipeline._chapter_master_render_signature(
        chapter=chapter,
        segment_rows=rows,
        narrator_voice_id="narrator-voice",
        speaker_cast={"private": private_cast, "cast_map_sha256": "a" * 64},
        render_language="en-US",
    )
    changed_cast = pipeline._chapter_master_render_signature(
        chapter=chapter,
        segment_rows=rows,
        narrator_voice_id="narrator-voice",
        speaker_cast={"private": private_cast, "cast_map_sha256": "b" * 64},
        render_language="en-US",
    )
    monkeypatch.setattr(
        pipeline,
        "BOUNDARY_POLICY_NAME",
        "ea.audiobook_boundary_policy.test-revision",
    )
    changed_boundary = pipeline._chapter_master_render_signature(
        chapter=chapter,
        segment_rows=rows,
        narrator_voice_id="narrator-voice",
        speaker_cast={"private": private_cast, "cast_map_sha256": "b" * 64},
        render_language="en-US",
    )
    monkeypatch.setattr(
        pipeline,
        "NARRATION_PLAN_CONTRACT_NAME",
        "ea.audiobook_narration_plan.test-revision",
    )
    changed_narration_plan = pipeline._chapter_master_render_signature(
        chapter=chapter,
        segment_rows=rows,
        narrator_voice_id="narrator-voice",
        speaker_cast={"private": private_cast, "cast_map_sha256": "b" * 64},
        render_language="en-US",
    )
    monkeypatch.setattr(
        pipeline,
        "SPEAKER_CAST_POLICY_NAME",
        "ea.audiobook_speaker_cast_policy.test-revision",
    )
    changed_speaker_cast_policy = pipeline._chapter_master_render_signature(
        chapter=chapter,
        segment_rows=rows,
        narrator_voice_id="narrator-voice",
        speaker_cast={"private": private_cast, "cast_map_sha256": "b" * 64},
        render_language="en-US",
    )

    assert first != changed_cast
    assert changed_cast != changed_boundary
    assert changed_boundary != changed_narration_plan
    assert changed_narration_plan != changed_speaker_cast_policy


def test_cinematic_master_signature_binds_all_policy_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import EpubChapter

    chapter = EpubChapter(
        index=1,
        title="Chapter",
        source_href="chapter.xhtml",
        text_path="001.txt",
        audio_filename="001.wav",
        char_count=8,
        sha256="c" * 64,
    )

    def signature() -> str:
        return pipeline._cinematic_track_signature(
            chapter_inputs=((chapter, "Narration"),),
            narrator_voice_id="narrator-voice",
            render_language="en-US",
            planner_plan_sha256="a" * 64,
            cast_map_sha256="b" * 64,
        )

    first = signature()
    monkeypatch.setattr(
        pipeline,
        "BOUNDARY_POLICY_NAME",
        "ea.audiobook_boundary_policy.test-revision",
    )
    changed_boundary = signature()
    monkeypatch.setattr(
        pipeline,
        "SPEAKER_CAST_POLICY_NAME",
        "ea.audiobook_speaker_cast_policy.test-revision",
    )
    changed_speaker_cast_policy = signature()
    monkeypatch.setattr(
        pipeline,
        "NARRATION_PLAN_CONTRACT_NAME",
        "ea.audiobook_narration_plan.test-revision",
    )
    changed_narration_plan = signature()

    assert first != changed_boundary
    assert changed_boundary != changed_speaker_cast_policy
    assert changed_speaker_cast_policy != changed_narration_plan


def test_passages_are_cached_unmastered_and_mastering_runs_once_on_chapter(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import EpubChapter, EpubMetadata

    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_CINEMATIC_NARRATION", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_BATCH_PARAGRAPHS_WITH_NATURAL_PAUSES", "0")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {
                    "voice_id": "narrator-voice",
                    "label": "Narrator",
                    "language": "en-US",
                    "tags": ["narration", "neutral"],
                    "default": True,
                }
            ]
        ),
    )
    text = "First paragraph.\n\nSecond paragraph."
    chapter_dir = tmp_path / "chapters"
    chapter_dir.mkdir()
    text_path = chapter_dir / "001.txt"
    text_path.write_text(text, encoding="utf-8")
    chapter = EpubChapter(
        index=1,
        title="Chapter",
        source_href="chapter.xhtml",
        text_path=text_path.name,
        audio_filename="001.wav",
        char_count=len(text),
        sha256=pipeline._sha256_bytes(text.encode("utf-8")),
    )
    metadata = EpubMetadata(
        title="Mastering Scope",
        author="A. Writer",
        language="en-US",
        source_filename="book.epub",
        source_sha256="source-sha",
    )
    tone = tmp_path / "tone.wav"
    _write_tone_wav(tone)
    passage_paths: list[Path] = []
    mastered_paths: list[Path] = []

    def fake_synthesize_request(**_kwargs):
        return tone.read_bytes(), "audio/wav"

    def fake_write_passage(*, target_wav, **_kwargs):
        target_wav.parent.mkdir(parents=True, exist_ok=True)
        target_wav.write_bytes(tone.read_bytes())
        passage_paths.append(target_wav)
        return target_wav

    def fake_merge(*, segment_paths, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(Path(segment_paths[0]).read_bytes())
        return True

    def fake_master(path):
        mastered_paths.append(path)
        return path

    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", fake_synthesize_request)
    monkeypatch.setattr(pipeline, "_write_provider_audio_segment_file", fake_write_passage)
    monkeypatch.setattr(pipeline, "_merge_audio_segments_to_wav", fake_merge)
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", fake_master)

    result = pipeline.render_unmixr_chapter_audio(
        job_dir=tmp_path,
        chapters=(chapter,),
        metadata=metadata,
    )

    assert result["status"] == "rendered"
    assert len(passage_paths) == 2
    assert all("-parts" in str(path.parent) for path in passage_paths)
    assert len(mastered_paths) == 1
    assert mastered_paths[0].parent == tmp_path / "audio"
    assert mastered_paths[0].name.startswith(".001.")
    assert mastered_paths[0].name.endswith(".mastering.wav")
    assert (tmp_path / "audio" / "001.wav").is_file()


def test_mastering_failure_blocks_before_chapter_signature_publication(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import EpubChapter, EpubMetadata

    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_CINEMATIC_NARRATION", "0")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {
                    "voice_id": "narrator-voice",
                    "label": "Narrator",
                    "language": "en-US",
                    "tags": ["narration", "neutral"],
                    "default": True,
                }
            ]
        ),
    )
    text = "A chapter that must be mastered before publication."
    chapter_dir = tmp_path / "chapters"
    chapter_dir.mkdir()
    (chapter_dir / "001.txt").write_text(text, encoding="utf-8")
    chapter = EpubChapter(
        index=1,
        title="Chapter",
        source_href="chapter.xhtml",
        text_path="001.txt",
        audio_filename="001.wav",
        char_count=len(text),
        sha256=pipeline._sha256_bytes(text.encode("utf-8")),
    )
    metadata = EpubMetadata(
        title="Mastering Failure",
        author="A. Writer",
        language="en-US",
        source_filename="book.epub",
        source_sha256="source-sha",
    )
    tone = tmp_path / "tone.wav"
    _write_tone_wav(tone)
    monkeypatch.setattr(
        pipeline,
        "unmixr_synthesize_request",
        lambda **_kwargs: (tone.read_bytes(), "audio/wav"),
    )
    monkeypatch.setattr(
        pipeline,
        "_normalize_rendered_audio_file",
        lambda _path: (_ for _ in ()).throw(
            RuntimeError("audiobook_audio_normalization_failed")
        ),
    )

    result = pipeline.render_unmixr_chapter_audio(
        job_dir=tmp_path,
        chapters=(chapter,),
        metadata=metadata,
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "audiobook_final_mastering_failed"
    assert result["mastering"]["signature_published"] is False
    assert not (tmp_path / "audio" / "001.wav.narration.signature").exists()


def test_source_or_structure_tamper_blocks_before_synthesis(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_CINEMATIC_NARRATION", "0")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {
                    "voice_id": "narrator-voice",
                    "label": "Narrator",
                    "language": "en-US",
                    "tags": ["audiobook", "narration"],
                    "default": True,
                }
            ]
        ),
    )
    epub = tmp_path / "book.epub"
    _write_minimal_epub(epub)
    metadata, chapters = pipeline.extract_epub_chapters(
        epub_path=epub,
        chapter_dir=tmp_path / "chapters",
        source_filename="book.epub",
    )
    first_text_path = tmp_path / "chapters" / chapters[0].text_path
    first_text_path.write_text(
        first_text_path.read_text(encoding="utf-8") + "Tampered after extraction.\n",
        encoding="utf-8",
    )
    synthesis_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        pipeline,
        "unmixr_synthesize_request",
        lambda **kwargs: synthesis_calls.append(dict(kwargs)),
    )

    result = pipeline.render_unmixr_chapter_audio(
        job_dir=tmp_path,
        chapters=chapters,
        metadata=metadata,
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "blocked_source_integrity_or_coverage_mismatch"
    assert synthesis_calls == []
    plan = json.loads((tmp_path / "narration_plan.json").read_text(encoding="utf-8"))
    assert "chapter_text_hash_mismatch:1" in plan["source_integrity_issues"]
    assert "chapter_structure_text_hash_mismatch:1" in plan["source_integrity_issues"]


def test_chapters_from_job_retains_source_structure_path() -> None:
    from app.services.audiobook_epub_pipeline import _chapters_from_job

    chapters = _chapters_from_job(
        {
            "chapters": [
                {
                    "index": 1,
                    "title": "Opening",
                    "source_href": "opening.xhtml",
                    "text_path": "001 - Opening.txt",
                    "audio_filename": "001 - Opening.wav",
                    "char_count": 42,
                    "sha256": "a" * 64,
                    "structure_path": "001 - Opening.source.json",
                }
            ]
        }
    )

    assert chapters[0].structure_path == "001 - Opening.source.json"


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


def test_safe_receipt_mastering_redacts_private_audio_quality_details() -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    private_path = "/private/audiobook/SECRET_TEXT/chapter-01.wav"
    raw_voice_id = "voice_id=provider-private-voice-123"
    safe = pipeline._safe_receipt_mastering(
        {
            "status": "mastered",
            "final_audio_quality": [
                {
                    "status": "failed",
                    "reason": private_path,
                    "issues": [
                        f"{raw_voice_id} exposed near {private_path}",
                    ],
                }
            ],
        }
    )

    quality = safe["final_audio_quality"]
    assert quality == [{"status": "failed", "redacted_issue_count": 1}]
    serialized = json.dumps(safe, sort_keys=True)
    assert private_path not in serialized
    assert "SECRET_TEXT" not in serialized
    assert raw_voice_id not in serialized


def test_audio_quality_receipt_summary_fails_closed_on_unknown_and_malformed_statuses() -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    summary = pipeline._audio_quality_receipt_summary(
        {
            "chapters": [
                {"audio_quality": {"status": "pass"}},
                {
                    "segment_audio_quality": [
                        {"status": "mystery"},
                        "not-an-audio-quality-report",
                    ]
                },
            ]
        }
    )

    assert summary["status"] == "failed"
    assert summary["checked_files"] == 3
    assert summary["passed_files"] == 1
    assert summary["failed_files"] == 2
    assert summary["invalid_status_files"] == 2


def test_audio_quality_receipt_summary_does_not_pass_skipped_reports() -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    summary = pipeline._audio_quality_receipt_summary(
        {
            "chapters": [
                {"audio_quality": {"status": "pass"}},
                {"audio_quality": {"status": "skipped"}},
            ]
        }
    )

    assert summary["status"] == "not_checked"
    assert summary["checked_files"] == 1
    assert summary["skipped_files"] == 1


def test_safe_receipt_mastering_enforces_public_field_types_and_finite_numbers() -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    private_value = "/private/audiobook/SECRET_TEXT/chapter-01.wav"
    safe = pipeline._safe_receipt_mastering(
        {
            "status": private_value,
            "final_audio_quality": [
                {
                    "chapter_index": "1",
                    "status": private_value,
                    "duration_seconds": float("nan"),
                    "channels": True,
                    "sample_rate": "48000",
                    "sample_width_bytes": 2,
                    "peak": float("inf"),
                    "speech_energy_present": "yes",
                    "quiet_tail": False,
                    "trailing_silence_seconds": -1.0,
                    "excessive_trailing_silence": 1,
                    "reason": "clipping",
                    "issues": ["quiet_tail", private_value],
                    "path": private_value,
                },
                {
                    "chapter_index": 2,
                    "status": "pass",
                    "duration_seconds": 12.5,
                    "channels": 1,
                    "sample_rate": 48000,
                    "sample_width_bytes": 2,
                    "peak": 0.75,
                    "speech_energy_present": True,
                    "quiet_tail": False,
                    "trailing_silence_seconds": 0.25,
                    "excessive_trailing_silence": False,
                },
            ],
        }
    )

    assert safe["status"] == "invalid"
    assert safe["final_audio_quality"] == [
        {
            "status": "invalid",
            "sample_width_bytes": 2,
            "quiet_tail": False,
            "reason": "clipping",
            "issues": ["quiet_tail"],
            "redacted_issue_count": 1,
        },
        {
            "status": "pass",
            "chapter_index": 2,
            "channels": 1,
            "sample_rate": 48000,
            "sample_width_bytes": 2,
            "duration_seconds": 12.5,
            "peak": 0.75,
            "trailing_silence_seconds": 0.25,
            "speech_energy_present": True,
            "quiet_tail": False,
            "excessive_trailing_silence": False,
        },
    ]
    serialized = json.dumps(safe, sort_keys=True)
    assert private_value not in serialized
    assert "SECRET_TEXT" not in serialized
    assert "NaN" not in serialized
    assert "Infinity" not in serialized


def test_human_listened_canary_rejects_malformed_numeric_counts_without_exception(
    monkeypatch,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    malformed_private_value = "/private/SECRET_TEXT voice_id=raw-provider-id"
    digest = "a" * 64
    monkeypatch.setenv(
        "EA_AUDIOBOOK_CANARY_RECEIPT_HMAC_KEY",
        "test-canary-hmac-key",
    )
    job = {
        "source": {"source_sha256": digest},
        "metadata": {"language": "en-US"},
        "telegram": {"chat_id": "private-listener-chat"},
        "render_result": {
            "narration_plan": {
                "contract_name": pipeline.NARRATION_PLAN_CONTRACT_NAME,
                "status": "ready",
                "coverage_complete": True,
                "source_integrity_verified": True,
                "plan_sha256": digest,
                "source_aggregate_sha256": digest,
                "render_signature": digest,
                "dialogue_passage_count": malformed_private_value,
            },
            "mastering": {
                "status": "mastered",
                "final_track_mode": "chapter_masters",
                "expected_final_track_count": malformed_private_value,
                "final_track_ready_count": [2],
                "signature_published_or_verified_count": {"count": 2},
                "signature_set_sha256": digest,
                "segment_mastering": False,
                "final_audio_quality": [{"status": "pass"}],
            },
        },
        "merge_result": {
            "status": "m4b_ready",
            "expected_chapter_count": malformed_private_value,
            "actual_chapter_count": [2],
            "chapter_count_matches": True,
        },
        "audio_publication_gate": {
            "contract_name": pipeline.AUDIOBOOK_PUBLICATION_GATE_CONTRACT_NAME,
            "status": "pass",
            "issues": [],
            "target_file_sha256": digest,
            "source_sha256": digest,
            "source_aggregate_sha256": digest,
            "narration_plan_sha256": digest,
            "render_signature_sha256": digest,
            "mastering_signature_set_sha256": digest,
            "mastering": {"final_track_mode": "chapter_masters"},
            "expected_chapter_count": malformed_private_value,
            "actual_chapter_count": [2],
            "chapter_count_matches": True,
            "stt": {
                "status": "pass",
                "required": True,
                "enabled": True,
                "sample_count": {"count": 1},
                "passed_samples": malformed_private_value,
                "failed_samples": [0],
            },
            "loudness": {
                "status": "checked",
                "analysis_scope": "full_file",
                "integrated_lufs": -16.0,
                "true_peak_dbtp": -2.0,
                "min_integrated_lufs": -20.0,
                "max_integrated_lufs": -14.0,
                "max_true_peak_dbtp": -1.0,
            },
        },
        "audiobookshelf_import": {
            "target_path": "",
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://abs.example.com/share/canary-book",
                "telegram_delivery": {"message_id": "101"},
            },
        },
    }

    acceptance = pipeline._human_listened_canary_acceptance(
        job=job,
        accepted=True,
        source="telegram_button",
        message_id="202",
        feedback="Listened to the canary.",
        recorded_at="2026-07-19T12:00:00Z",
        callback_token_verified=True,
    )

    assert acceptance["canary_binding_status"] == "incomplete"
    assert acceptance["listened"] is False
    assert acceptance["dialogue_turn_count"] == 0
    assert acceptance["expected_chapter_count"] == 0
    assert acceptance["actual_chapter_count"] == 0
    assert set(acceptance["binding_issues"]) == {
        "artifact_unavailable",
        "chapter_metadata_unbound",
        "dialogue_continuity_canary_unexercised",
        "mastering_proof_unbound",
        "perceptual_attestation_feedback_unbound",
        "perceptual_attestation_unbound",
        "publication_gate_unbound",
    }
    serialized = json.dumps(acceptance, sort_keys=True)
    assert malformed_private_value not in serialized
    assert "SECRET_TEXT" not in serialized
    assert "raw-provider-id" not in serialized


def test_existing_chapter_wavs_merge_with_ffmpeg_fallback_and_import(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
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
    _mock_publication_gate_contract_pass(monkeypatch, pipeline)

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


def _publication_ready_job(
    pipeline,
    *,
    job_dir: Path,
    source_text: str,
    title: str = "Test Book",
    text_path: str = "001 - Chapter.txt",
) -> dict[str, object]:
    source_text_sha256 = pipeline._sha256_bytes(source_text.encode("utf-8"))
    return {
        "status": "audiobookshelf_imported",
        "source": {"source_sha256": source_text_sha256},
        "metadata": {
            "title": title,
            "language": "en-US",
            "source_sha256": source_text_sha256,
        },
        "storage": {"job_dir": str(job_dir)},
        "chapters": [
            {
                "index": 1,
                "text_path": text_path,
                "char_count": len(source_text),
                "sha256": source_text_sha256,
            }
        ],
        "render_result": {
            "status": "rendered",
            "narration_plan": {
                "contract_name": "ea.audiobook_narration_plan.v5",
                "status": "ready",
                "source_coverage": "complete",
                "coverage_complete": True,
                "source_integrity_verified": True,
                "plan_sha256": "a" * 64,
                "source_aggregate_sha256": "b" * 64,
                "render_signature": "c" * 64,
                "dialogue_passage_count": 0,
                "dialogue_span_count": 0,
                "speaker_cast": {"status": "not_required"},
                "cast_map_sha256": "",
            },
            "speaker_cast": {"status": "not_required"},
            "mastering": {
                "status": "mastered",
                "final_track_mode": "chapter_masters",
                "contract_sha256": "d" * 64,
                "expected_final_track_count": 1,
                "final_track_ready_count": 1,
                "final_track_mastered_this_run_count": 1,
                "signature_published_or_verified_count": 1,
                "signature_set_sha256": "e" * 64,
                "segment_mastering": False,
                "final_audio_quality": [{"status": "pass"}],
            },
        },
        "merge_result": {
            "status": "m4b_ready",
            "expected_chapter_count": 1,
            "actual_chapter_count": 1,
            "chapter_count_matches": True,
        },
    }


def _mock_publication_loudness_pass(monkeypatch, pipeline) -> None:
    monkeypatch.setattr(
        pipeline,
        "_audio_publication_loudness",
        lambda path: {
            "status": "checked",
            "analysis_scope": "full_file",
            "integrated_lufs": -16.0,
            "true_peak_dbtp": -2.0,
            "loudness_range_lu": 8.0,
            "threshold_lufs": -26.0,
            "returncode": 0,
            "raw_output_exposed": False,
        },
    )


def _mock_publication_gate_media_pass(
    monkeypatch,
    pipeline,
    *,
    target_path: Path,
    chapter_count: int = 1,
) -> None:
    monkeypatch.setattr(
        pipeline,
        "_probe_audio_publication_file",
        lambda path: {
            "format": {
                "duration": "120.0",
                "size": str(target_path.stat().st_size),
            },
            "streams": [
                {"codec_type": "audio", "codec_name": "aac"},
                {"codec_type": "video", "codec_name": "mjpeg"},
            ],
            "chapters": [{"id": index} for index in range(chapter_count)],
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
    _mock_publication_loudness_pass(monkeypatch, pipeline)
    monkeypatch.setattr(
        pipeline,
        "_build_audiobook_publication_stt_gate",
        lambda **kwargs: {
            "status": "pass",
            "required": True,
            "enabled": True,
            "sample_count": 1,
            "passed_samples": 1,
            "failed_samples": 0,
            "raw_text_exposed": False,
        },
    )


def _mock_publication_gate_contract_pass(monkeypatch, pipeline) -> None:
    """Keep downstream import/share tests scoped away from gate qualification."""

    def build_gate(*, job, target_path: Path):
        source_sha256 = str(
            dict(job.get("source") or {}).get("source_sha256")
            or dict(job.get("metadata") or {}).get("source_sha256")
            or ""
        )
        chapter_count = len(list(job.get("chapters") or []))
        return {
            "contract_name": pipeline.AUDIOBOOK_PUBLICATION_GATE_CONTRACT_NAME,
            "status": "pass",
            "issues": [],
            "target_file_sha256": pipeline._sha256_file(target_path),
            "source_sha256": source_sha256,
            "source_aggregate_sha256": "a" * 64,
            "narration_plan_sha256": "b" * 64,
            "render_signature_sha256": "c" * 64,
            "cast_map_sha256": "",
            "mastering_signature_set_sha256": "d" * 64,
            "expected_chapter_count": chapter_count,
            "actual_chapter_count": chapter_count,
            "chapter_count_matches": True,
            "cinematic_timeline_sha256": "",
            "cover_streams": 1,
            "raw_paths_exposed": False,
        }

    monkeypatch.setattr(pipeline, "_build_audiobook_publication_gate", build_gate)


def test_preferred_m4b_tool_success_passes_publication_gate_chapter_counts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    job_dir = tmp_path / "jobs" / "preferred-m4b-tool"
    chapter_dir = job_dir / "chapters"
    audio_dir = job_dir / "audio"
    chapter_dir.mkdir(parents=True)
    audio_dir.mkdir()
    source_text = "The preferred assembler preserves this exact chapter."
    text_path = "001.txt"
    (chapter_dir / text_path).write_text(source_text, encoding="utf-8")
    chapter = pipeline.EpubChapter(
        index=1,
        title="Chapter",
        source_href="chapter.xhtml",
        text_path=text_path,
        audio_filename="001.wav",
        char_count=len(source_text),
        sha256=pipeline._sha256_bytes(source_text.encode("utf-8")),
    )
    metadata = pipeline.EpubMetadata(
        title="Test Book",
        author="A. Writer",
        language="en-US",
        source_filename="book.epub",
        source_sha256=chapter.sha256,
    )
    chapter_master = audio_dir / chapter.audio_filename
    _write_tone_wav(chapter_master)
    render_fingerprint = "9" * 64
    pipeline._write_atomic_private_text(
        chapter_master.with_suffix(
            chapter_master.suffix + ".narration.signature"
        ),
        render_fingerprint,
    )
    pipeline._write_audio_cache_output_binding(
        audio_path=chapter_master,
        cache_kind="chapter_master",
        render_fingerprint=render_fingerprint,
    )
    monkeypatch.setenv("EA_AUDIOBOOK_CINEMATIC_NARRATION", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_M4B_AUTO_MERGE", "1")
    monkeypatch.setenv("EA_M4B_TOOL_BIN", "m4b-tool")
    m4b_tool_calls: list[list[str]] = []

    def run_m4b_tool(command, **_kwargs):
        m4b_tool_calls.append(list(command))
        output_path = Path(command[command.index("--output-file") + 1])
        output_path.write_bytes(b"preferred m4b-tool output")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(pipeline, "_m4b_cover_image_path", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline, "_m4b_tool_available", lambda: True)
    monkeypatch.setattr(
        pipeline,
        "_merge_m4b_with_ffmpeg",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("preferred success must not silently select ffmpeg")
        ),
    )
    monkeypatch.setattr(pipeline.subprocess, "run", run_m4b_tool)
    monkeypatch.setattr(
        pipeline,
        "_probe_audio_publication_file",
        lambda _path: {"chapters": [{"id": 1}]},
    )

    merge_result = pipeline._merge_m4b_if_ready(
        job_dir=job_dir,
        metadata=metadata,
        chapters=(chapter,),
    )

    assembled_path = Path(str(merge_result["output_file"]))
    import_root = tmp_path / "audiobookshelf"
    target_path = import_root / "A. Writer" / "Test Book" / "Test Book.m4b"
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(assembled_path.read_bytes())
    job = _publication_ready_job(
        pipeline,
        job_dir=job_dir,
        source_text=source_text,
        text_path=text_path,
    )
    job["merge_result"] = merge_result
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_IMPORT_ROOT", str(import_root))
    _mock_publication_gate_media_pass(
        monkeypatch,
        pipeline,
        target_path=target_path,
        chapter_count=1,
    )

    gate = pipeline._build_audiobook_publication_gate(
        job=job,
        target_path=target_path,
    )

    assert merge_result["provider"] == "m4b-tool"
    assert merge_result["expected_chapter_count"] == 1
    assert merge_result["actual_chapter_count"] == 1
    assert merge_result["chapter_count_matches"] is True
    assert merge_result["output_file_sha256"] == pipeline._sha256_file(
        target_path
    )
    assert len(m4b_tool_calls) == 1
    assert gate["status"] == "pass"
    assert gate["issues"] == []
    assert gate["expected_chapter_count"] == 1
    assert gate["actual_chapter_count"] == 1
    assert gate["chapter_count_matches"] is True


def test_audio_publication_loudness_uses_full_file_loudnorm_json(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    target_path = tmp_path / "book.m4b"
    target_path.write_bytes(b"fake m4b bytes")
    seen: dict[str, object] = {}

    def fake_run(command, **kwargs):
        seen["command"] = list(command)
        return SimpleNamespace(
            returncode=0,
            stderr=(
                "ffmpeg diagnostic\n"
                "{\n"
                '  "input_i" : "-16.42",\n'
                '  "input_tp" : "-2.11",\n'
                '  "input_lra" : "7.60",\n'
                '  "input_thresh" : "-26.80",\n'
                '  "output_i" : "-16.00"\n'
                "}\n"
            ),
        )

    monkeypatch.setattr(pipeline.subprocess, "run", fake_run)

    result = pipeline._audio_publication_loudness(target_path)

    command = list(seen["command"])
    assert result == {
        "status": "checked",
        "analysis_scope": "full_file",
        "integrated_lufs": -16.42,
        "true_peak_dbtp": -2.11,
        "loudness_range_lu": 7.6,
        "threshold_lufs": -26.8,
        "returncode": 0,
        "raw_output_exposed": False,
    }
    assert "-t" not in command
    assert "-ss" not in command
    assert command[command.index("-map") + 1] == "0:a:0"
    assert any("loudnorm=" in value for value in command)


def test_audio_publication_gate_v2_binds_cinematic_release_evidence(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    import_root = tmp_path / "audiobookshelf"
    target_path = import_root / "A. Writer" / "Test Book" / "Test Book.m4b"
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(b"exact m4b bytes")
    job_dir = tmp_path / "jobs" / "job-gate-v2-pass"
    chapter_dir = job_dir / "chapters"
    chapter_dir.mkdir(parents=True)
    source_text = "Exact evidence reaches the public gate."
    (chapter_dir / "001 - Chapter.txt").write_text(source_text, encoding="utf-8")
    job = _publication_ready_job(
        pipeline,
        job_dir=job_dir,
        source_text=source_text,
    )
    timeline_sha256 = "f" * 64
    render_result = dict(job["render_result"])
    render_result["mastering"] = {
        **dict(render_result.get("mastering") or {}),
        "final_track_mode": "cinematic_master",
    }
    render_result.update(
        {
            "cinematic_master_audio": "_cinematic_master.wav",
            "chapter_timeline": {
                "status": "verified",
                "contract_name": "ea.audiobook_cinematic_chapter_timeline.v1",
                "timeline_sha256": timeline_sha256,
                "chapter_count": 1,
            },
        }
    )
    job["render_result"] = render_result
    job["merge_result"]["cinematic_timeline_sha256"] = timeline_sha256

    monkeypatch.setenv("EA_AUDIOBOOKSHELF_IMPORT_ROOT", str(import_root))
    _mock_publication_gate_media_pass(
        monkeypatch,
        pipeline,
        target_path=target_path,
    )

    gate = pipeline._build_audiobook_publication_gate(
        job=job,
        target_path=target_path,
    )

    assert gate["contract_name"] == pipeline.AUDIOBOOK_PUBLICATION_GATE_CONTRACT_NAME
    assert gate["status"] == "pass"
    assert gate["narration_plan_sha256"] == "a" * 64
    assert gate["source_sha256"] == pipeline._sha256_bytes(
        source_text.encode("utf-8")
    )
    assert gate["source_aggregate_sha256"] == "b" * 64
    assert gate["render_signature_sha256"] == "c" * 64
    assert gate["mastering_signature_set_sha256"] == "e" * 64
    assert gate["expected_chapter_count"] == 1
    assert gate["actual_chapter_count"] == 1
    assert gate["chapter_count_matches"] is True
    assert gate["cinematic_timeline_sha256"] == timeline_sha256
    assert gate["loudness"]["analysis_scope"] == "full_file"
    assert gate["loudness"]["integrated_lufs"] == -16.0
    assert gate["loudness"]["true_peak_dbtp"] == -2.0
    assert gate["raw_paths_exposed"] is False


@pytest.mark.parametrize(
    ("case", "expected_issue"),
    (
        ("plan_contract", "narration_plan_contract_not_v5"),
        ("plan_integrity", "narration_plan_source_integrity_unverified"),
        ("plan_sha256", "narration_plan_sha256_invalid"),
        ("source_artifact", "source_artifact_sha256_invalid"),
        ("source_artifact_mismatch", "source_artifact_sha256_mismatch"),
        ("source_sha256", "narration_source_aggregate_sha256_invalid"),
        ("render_signature", "narration_render_signature_sha256_invalid"),
        ("mastering_status", "final_mastering_not_complete"),
        ("mastering_counter", "mastering_final_track_count_mismatch"),
        ("mastering_signature", "mastering_signature_set_sha256_invalid"),
        ("mastering_quality", "final_master_quality_not_acceptable"),
        ("mastering_mode", "final_mastering_track_mode_invalid"),
        (
            "mastering_mode_mismatch",
            "cinematic_mastering_track_count_or_timeline_mismatch",
        ),
        (
            "dialogue_cast",
            "dialogue_speaker_cast_not_distinct_from_narrator",
        ),
        ("chapter_count", "m4b_chapter_count_mismatch"),
        (
            "cinematic_timeline",
            "cinematic_chapter_timeline_sha256_mismatch",
        ),
    ),
)
def test_audio_publication_gate_v2_fails_closed_on_unbound_evidence(
    monkeypatch,
    tmp_path: Path,
    case: str,
    expected_issue: str,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    import_root = tmp_path / "audiobookshelf"
    target_path = import_root / "A. Writer" / "Test Book" / "Test Book.m4b"
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(b"exact m4b bytes")
    job_dir = tmp_path / "jobs" / f"job-gate-v2-{case}"
    chapter_dir = job_dir / "chapters"
    chapter_dir.mkdir(parents=True)
    source_text = "Every publication input is cryptographically bound."
    (chapter_dir / "001 - Chapter.txt").write_text(source_text, encoding="utf-8")
    job = _publication_ready_job(
        pipeline,
        job_dir=job_dir,
        source_text=source_text,
    )
    render_result = job["render_result"]
    plan = render_result["narration_plan"]
    mastering = render_result["mastering"]
    if case == "plan_contract":
        plan["contract_name"] = "ea.audiobook_narration_plan.v4"
    elif case == "plan_integrity":
        plan["source_integrity_verified"] = False
    elif case == "plan_sha256":
        plan["plan_sha256"] = "invalid"
    elif case == "source_artifact":
        job["source"]["source_sha256"] = "invalid"
        job["metadata"]["source_sha256"] = "invalid"
    elif case == "source_artifact_mismatch":
        job["source"]["source_sha256"] = "0" * 64
    elif case == "source_sha256":
        plan["source_aggregate_sha256"] = "invalid"
    elif case == "render_signature":
        plan["render_signature"] = "invalid"
    elif case == "mastering_status":
        mastering["status"] = "incomplete"
    elif case == "mastering_counter":
        mastering["final_track_ready_count"] = 0
    elif case == "mastering_signature":
        mastering["signature_set_sha256"] = "invalid"
    elif case == "mastering_quality":
        mastering["final_audio_quality"] = [{"status": "failed"}]
    elif case == "mastering_mode":
        mastering["final_track_mode"] = "unknown"
    elif case == "mastering_mode_mismatch":
        mastering["final_track_mode"] = "cinematic_master"
    elif case == "dialogue_cast":
        cast_sha256 = "f" * 64
        plan["dialogue_passage_count"] = 1
        plan["dialogue_span_count"] = 1
        plan["cast_map_sha256"] = cast_sha256
        render_result["speaker_cast"] = {
            "status": "ready",
            "narrator_voice_excluded": False,
            "cast_map_sha256": cast_sha256,
        }
    elif case == "chapter_count":
        job["merge_result"]["actual_chapter_count"] = 0
        job["merge_result"]["chapter_count_matches"] = False
    elif case == "cinematic_timeline":
        render_result["cinematic_master_audio"] = "_cinematic_master.wav"
        mastering["final_track_mode"] = "cinematic_master"
        render_result["chapter_timeline"] = {
            "status": "verified",
            "contract_name": "ea.audiobook_cinematic_chapter_timeline.v1",
            "timeline_sha256": "f" * 64,
            "chapter_count": 1,
        }
        job["merge_result"]["cinematic_timeline_sha256"] = "0" * 64

    monkeypatch.setenv("EA_AUDIOBOOKSHELF_IMPORT_ROOT", str(import_root))
    _mock_publication_gate_media_pass(
        monkeypatch,
        pipeline,
        target_path=target_path,
    )

    gate = pipeline._build_audiobook_publication_gate(
        job=job,
        target_path=target_path,
    )

    assert gate["status"] == "fail"
    assert expected_issue in gate["issues"]
    assert gate["raw_paths_exposed"] is False


@pytest.mark.parametrize(
    ("integrated_lufs", "true_peak_dbtp", "expected_issue"),
    (
        (-20.1, -2.0, "integrated_lufs_below_minimum"),
        (-13.9, -2.0, "integrated_lufs_above_maximum"),
        (-16.0, -0.9, "true_peak_above_maximum"),
    ),
)
def test_audio_publication_gate_v2_enforces_full_file_loudness_thresholds(
    monkeypatch,
    tmp_path: Path,
    integrated_lufs: float,
    true_peak_dbtp: float,
    expected_issue: str,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    import_root = tmp_path / "audiobookshelf"
    target_path = import_root / "A. Writer" / "Test Book" / "Test Book.m4b"
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(b"exact m4b bytes")
    job_dir = tmp_path / "jobs" / "job-gate-v2-loudness"
    chapter_dir = job_dir / "chapters"
    chapter_dir.mkdir(parents=True)
    source_text = "The complete file must satisfy the loudness policy."
    (chapter_dir / "001 - Chapter.txt").write_text(source_text, encoding="utf-8")
    job = _publication_ready_job(
        pipeline,
        job_dir=job_dir,
        source_text=source_text,
    )
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_IMPORT_ROOT", str(import_root))
    _mock_publication_gate_media_pass(
        monkeypatch,
        pipeline,
        target_path=target_path,
    )
    monkeypatch.setattr(
        pipeline,
        "_audio_publication_loudness",
        lambda path: {
            "status": "checked",
            "analysis_scope": "full_file",
            "integrated_lufs": integrated_lufs,
            "true_peak_dbtp": true_peak_dbtp,
            "loudness_range_lu": 8.0,
            "threshold_lufs": -26.0,
            "returncode": 0,
            "raw_output_exposed": False,
        },
    )

    gate = pipeline._build_audiobook_publication_gate(
        job=job,
        target_path=target_path,
    )

    assert gate["status"] == "fail"
    assert expected_issue in gate["issues"]


def test_audio_publication_gate_v2_cannot_disable_stt_with_environment(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    import_root = tmp_path / "audiobookshelf"
    target_path = import_root / "A. Writer" / "Test Book" / "Test Book.m4b"
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(b"exact m4b bytes")
    job_dir = tmp_path / "jobs" / "job-gate-v2-stt-disabled"
    chapter_dir = job_dir / "chapters"
    chapter_dir.mkdir(parents=True)
    source_text = "Publication needs a passed transcription sample."
    (chapter_dir / "001 - Chapter.txt").write_text(source_text, encoding="utf-8")
    job = _publication_ready_job(
        pipeline,
        job_dir=job_dir,
        source_text=source_text,
    )
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_IMPORT_ROOT", str(import_root))
    monkeypatch.setenv("EA_AUDIOBOOK_PUBLICATION_STT_GATE_REQUIRED", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_PUBLICATION_STT_GATE_ENABLED", "0")
    _mock_publication_gate_media_pass(
        monkeypatch,
        pipeline,
        target_path=target_path,
    )
    monkeypatch.setattr(
        pipeline,
        "_build_audiobook_publication_stt_gate",
        lambda **kwargs: {
            "status": "skipped",
            "required": False,
            "enabled": False,
            "raw_text_exposed": False,
        },
    )

    gate = pipeline._build_audiobook_publication_gate(
        job=job,
        target_path=target_path,
    )

    assert gate["status"] == "fail"
    assert "stt_gate_not_passed" in gate["issues"]


def test_audio_publication_gate_blocks_quiet_tail(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    import_root = tmp_path / "audiobookshelf"
    target_path = import_root / "A. Writer" / "Test Book" / "Test Book.m4b"
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(b"fake m4b bytes")
    job_dir = tmp_path / "jobs" / "job-quiet-tail"
    chapter_dir = job_dir / "chapters"
    chapter_dir.mkdir(parents=True)
    source_text = "The publication tail must contain audible book text."
    (chapter_dir / "001 - Chapter.txt").write_text(source_text, encoding="utf-8")
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
    _mock_publication_loudness_pass(monkeypatch, pipeline)
    monkeypatch.setattr(
        pipeline,
        "_build_audiobook_publication_stt_gate",
        lambda **kwargs: {
            "status": "pass",
            "required": True,
            "enabled": True,
            "sample_count": 1,
            "passed_samples": 1,
            "failed_samples": 0,
            "raw_text_exposed": False,
        },
    )

    gate = pipeline._build_audiobook_publication_gate(
        job=_publication_ready_job(
            pipeline,
            job_dir=job_dir,
            source_text=source_text,
        ),
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
    _mock_publication_loudness_pass(monkeypatch, pipeline)

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
        job=_publication_ready_job(
            pipeline,
            job_dir=job_dir,
            source_text=source_text,
        ),
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
    _mock_publication_loudness_pass(monkeypatch, pipeline)

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
        job=_publication_ready_job(
            pipeline,
            job_dir=job_dir,
            source_text=source_text,
        ),
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
    _mock_publication_loudness_pass(monkeypatch, pipeline)

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
        job=_publication_ready_job(
            pipeline,
            job_dir=job_dir,
            source_text=source_text,
            title="Default STT Book",
        ),
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
    _mock_publication_loudness_pass(monkeypatch, pipeline)
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
        job=_publication_ready_job(
            pipeline,
            job_dir=job_dir,
            source_text=source_text,
        ),
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
    _mock_publication_loudness_pass(monkeypatch, pipeline)

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
        job=_publication_ready_job(
            pipeline,
            job_dir=job_dir,
            source_text=source_text,
        ),
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
    _mock_publication_gate_contract_pass(monkeypatch, pipeline)
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
                                "path": str(
                                    tmp_path
                                    / "audiobookshelf"
                                    / "A. Writer"
                                    / "Test Book"
                                    / "Test Book.m4b"
                                ),
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
            "audiobookshelf_target_path_sha256": pipeline._sha256_bytes(
                str(tmp_path / "audiobookshelf" / "A. Writer" / "Test Book" / "Test Book.m4b").encode(
                    "utf-8"
                )
            ),
            "audiobookshelf_item_match_kind": "exact_absolute_path",
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
    assert any(value.startswith("ap2|a|") for value in callback_values)
    assert any(value.startswith("ap2|r|") for value in callback_values)
    assert "Attest all 7 checks pass" in telegram_payload["text"]
    assert "Tapping attests every check" in telegram_payload["text"]
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
        "audio_publication_gate": {"status": "pass", "issues": []},
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
        "audio_publication_gate": {"status": "pass", "issues": []},
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
    assert playback["listened"] is False
    assert playback["canary_binding_status"] == "incomplete"
    assert playback["contract_name"] == "ea.telegram_epub_audiobook_playback_acceptance.v1"
    assert "exact_narration_plan_unbound" in playback["binding_issues"]
    assert playback["source"] == "telegram"
    assert playback["feedback_sha256"]
    assert playback["message_id_sha256"]
    assert playback["public_share_url_sha256"]
    assert playback["audiobookshelf_target_file_sha256"]
    assert playback["telegram_public_share_message_id_sha256"]
    assert playback["raw_feedback_exposed"] is False
    assert receipt["updated_at"]
    assert receipt["next_action"] == "playback_accepted"


def test_human_listened_canary_requires_and_binds_full_audio_evidence(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-listened-canary"
    job_dir.mkdir(parents=True)
    import_root = tmp_path / "audiobookshelf"
    target_path = import_root / "A. Writer" / "Canary Book" / "Canary Book.m4b"
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(b"bound m4b bytes")
    artifact_sha256 = pipeline._sha256_file(target_path)
    source_sha256 = "1" * 64
    plan_sha256 = "2" * 64
    source_aggregate_sha256 = "3" * 64
    render_signature_sha256 = "4" * 64
    mastering_signature_set_sha256 = "5" * 64
    cast_map_sha256 = "7" * 64
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_IMPORT_ROOT", str(import_root))
    monkeypatch.setenv(
        "EA_AUDIOBOOK_CANARY_RECEIPT_HMAC_KEY",
        "test-canary-hmac-key",
    )
    job = {
        "job_id": "job-listened-canary",
        "status": "audiobookshelf_imported",
        "source": {"source_sha256": source_sha256},
        "metadata": {
            "title": "Canary Book",
            "author": "A. Writer",
            "language": "en-US",
        },
        "storage": {"job_dir": str(job_dir)},
        "telegram": {"chat_id": "private-listener-chat", "message_id": "7"},
        "render_result": {
            "status": "rendered",
            "narration_plan": {
                "contract_name": pipeline.NARRATION_PLAN_CONTRACT_NAME,
                "status": "ready",
                "source_coverage": "complete",
                "coverage_complete": True,
                "source_integrity_verified": True,
                "plan_sha256": plan_sha256,
                "source_aggregate_sha256": source_aggregate_sha256,
                "render_signature": render_signature_sha256,
                "dialogue_passage_count": 2,
                "cast_map_sha256": cast_map_sha256,
            },
            "speaker_cast": {
                "status": "ready",
                "cast_map_sha256": cast_map_sha256,
                "distinct_dialogue_voice_count": 2,
                "narrator_voice_excluded": True,
            },
            "mastering": {
                "status": "mastered",
                "final_track_mode": "chapter_masters",
                "contract_sha256": "6" * 64,
                "expected_final_track_count": 2,
                "final_track_ready_count": 2,
                "final_track_mastered_this_run_count": 2,
                "signature_published_or_verified_count": 2,
                "signature_set_sha256": mastering_signature_set_sha256,
                "segment_mastering": False,
                "final_audio_quality": [
                    {"chapter_index": 1, "status": "pass"},
                    {"chapter_index": 2, "status": "pass"},
                ],
            },
        },
        "merge_result": {
            "status": "m4b_ready",
            "output_file": str(target_path),
            "chapter_count": 2,
            "expected_chapter_count": 2,
            "actual_chapter_count": 2,
            "chapter_count_matches": True,
        },
        "audio_publication_gate": {
            "contract_name": "ea.audiobook_publication_audio_gate.v2",
            "status": "pass",
            "issues": [],
            "target_file_sha256": artifact_sha256,
            "source_sha256": source_sha256,
            "source_aggregate_sha256": source_aggregate_sha256,
            "narration_plan_sha256": plan_sha256,
            "render_signature_sha256": render_signature_sha256,
            "cast_map_sha256": cast_map_sha256,
            "mastering_signature_set_sha256": mastering_signature_set_sha256,
            "mastering": {"final_track_mode": "chapter_masters"},
            "expected_chapter_count": 2,
            "actual_chapter_count": 2,
            "chapter_count_matches": True,
            "stt": {
                "status": "pass",
                "required": True,
                "enabled": True,
                "sample_count": 1,
                "passed_samples": 1,
                "failed_samples": 0,
            },
            "loudness": {
                "status": "checked",
                "analysis_scope": "full_file",
                "integrated_lufs": -16.0,
                "true_peak_dbtp": -2.0,
                "min_integrated_lufs": -20.0,
                "max_integrated_lufs": -14.0,
                "max_true_peak_dbtp": -1.0,
            },
        },
        "audiobookshelf_import": {
            "status": "imported",
            "target_path": str(target_path),
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://abs.example.com/share/canary-book",
                "telegram_delivery": {"status": "sent", "message_id": "101"},
            },
        },
    }
    legacy_acknowledgement = pipeline._human_listened_canary_acceptance(
        job=job,
        accepted=True,
        source="telegram_button",
        message_id="legacy-202",
        feedback="telegram_button_playback_accepted",
        recorded_at="2026-07-19T09:00:00Z",
        callback_token_verified=True,
    )
    assert legacy_acknowledgement["status"] == "accepted"
    assert legacy_acknowledgement["listened"] is False
    assert "perceptual_attestation_unbound" in legacy_acknowledgement[
        "binding_issues"
    ]
    assert "perceptual_attestation_feedback_unbound" in legacy_acknowledgement[
        "binding_issues"
    ]
    wrong_feedback = pipeline._human_listened_canary_acceptance(
        job=job,
        accepted=True,
        source="telegram_button",
        message_id="wrong-feedback-202",
        feedback="telegram_button_playback_accepted",
        recorded_at="2026-07-19T09:00:01Z",
        callback_token_verified=True,
        perceptual_attestation=pipeline.build_audiobook_perceptual_attestation(
            channel="telegram"
        ),
    )
    assert wrong_feedback["listened"] is False
    assert "perceptual_attestation_unbound" not in wrong_feedback[
        "binding_issues"
    ]
    assert "perceptual_attestation_feedback_unbound" in wrong_feedback[
        "binding_issues"
    ]
    pipeline._write_private_json(job_dir / "job.json", job)
    prepared = pipeline.ensure_audiobook_playback_acceptance_callback(job)
    callback_token = str(
        prepared["audiobookshelf_import"]["public_share"][
            "playback_acceptance_callback"
        ]["token"]
    )

    updated = pipeline.record_audiobook_playback_acceptance_by_callback_token(
        callback_token=callback_token,
        accepted=True,
        source="telegram_button",
        message_id="202",
        feedback=pipeline.audiobook_perceptual_attestation_feedback("telegram"),
        perceptual_attestation=pipeline.build_audiobook_perceptual_attestation(
            channel="telegram"
        ),
    )

    acceptance = dict(updated["playback_acceptance"])
    assert acceptance["contract_name"] == pipeline.HUMAN_LISTENED_CANARY_ACCEPTANCE_CONTRACT_NAME
    assert acceptance["status"] == "listened_canary_accepted"
    assert acceptance["listened"] is True
    assert acceptance["canary_binding_status"] == "complete"
    assert acceptance["binding_issues"] == []
    assert acceptance["artifact_sha256"] == artifact_sha256
    assert acceptance["narration_plan_sha256"] == plan_sha256
    assert acceptance["render_signature_sha256"] == render_signature_sha256
    assert acceptance["cast_map_sha256"] == cast_map_sha256
    assert acceptance["mastering_signature_set_sha256"] == mastering_signature_set_sha256
    assert acceptance["listener_reference_sha256"]
    assert acceptance["receipt_sha256"]
    assert acceptance["receipt_hmac_sha256"]
    attestation = acceptance["perceptual_attestation"]
    assert attestation["contract_name"] == (
        pipeline.AUDIOBOOK_PERCEPTUAL_ATTESTATION_CONTRACT_NAME
    )
    assert attestation["version"] == 1
    assert attestation["all_checks_attested"] is True
    assert attestation["channel_feedback_bound"] is True
    assert all(attestation["checks"].values())
    assert attestation["attestation_sha256"]
    assert attestation["raw_values_exposed"] is False
    assert updated["next_action"] == "playback_listened_canary_accepted"
    callback = updated["audiobookshelf_import"]["public_share"][
        "playback_acceptance_callback"
    ]
    assert callback["status"] == "consumed"
    assert "token" not in callback
    recorded_at = acceptance["recorded_at"]

    with pytest.raises(
        RuntimeError,
        match="audiobook_playback_acceptance_token_not_found",
    ):
        pipeline.record_audiobook_playback_acceptance_by_callback_token(
            callback_token=callback_token,
            accepted=True,
            source="telegram_button",
            message_id="203",
            feedback="Attempted replay.",
        )
    unchanged = pipeline._load_job(job_dir)
    assert unchanged["playback_acceptance"]["recorded_at"] == recorded_at

    receipt = pipeline.build_audiobook_job_receipt(job_dir=job_dir)
    public_acceptance = dict(receipt["playback_acceptance"])
    assert receipt["render"]["mastering"]["status"] == "mastered"
    assert receipt["render"]["mastering"]["signature_set_sha256"] == mastering_signature_set_sha256
    assert receipt["assembly"]["expected_chapter_count"] == 2
    assert receipt["assembly"]["actual_chapter_count"] == 2
    assert receipt["assembly"]["chapter_count_matches"] is True
    assert receipt["assembly"]["chapter_metadata_embedded"] is True
    assert public_acceptance["listened"] is True
    assert public_acceptance["canary_binding_status"] == "complete"
    assert public_acceptance["receipt_sha256"] == acceptance["receipt_sha256"]
    assert public_acceptance["receipt_hmac_sha256"] == acceptance["receipt_hmac_sha256"]
    assert public_acceptance["perceptual_attestation"] == attestation
    serialized = json.dumps(receipt, sort_keys=True)
    assert "private-listener-chat" not in serialized
    assert pipeline.audiobook_perceptual_attestation_feedback("telegram") not in serialized


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
        "audio_publication_gate": {"status": "pass", "issues": []},
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
    assert accepted_callback.startswith("ap2|a|")
    decision = channels._telegram_callback_turn_decision(
        SimpleNamespace(
            payload={
                "kind": "callback_query",
                "callback_data": accepted_callback,
                "_bot_config": {"token": "telegram-token"},
            },
            chat_id="42",
            container=object(),
            principal_id="principal-1",
            current_message_id="202",
        )
    )

    assert decision.reply_text == (
        "Recorded the seven-check response, but the listened-canary proof is "
        "still incomplete. Send 'audiobook status' to retry after the release "
        "evidence is ready."
    )
    receipt = build_audiobook_job_receipt(job_dir=job_dir)
    playback = receipt["playback_acceptance"]
    assert playback["status"] == "accepted"
    assert playback["accepted"] is True
    assert playback["source"] == "telegram_button"
    assert playback["message_id_sha256"]
    assert playback["feedback_sha256"]
    assert playback["perceptual_attestation"]["all_checks_attested"] is True
    assert playback["perceptual_attestation"]["channel_feedback_bound"] is True
    assert all(playback["perceptual_attestation"]["checks"].values())
    assert playback["callback_ready"] is True
    rendered = json.dumps(receipt, sort_keys=True)
    assert "telegram_button_perceptual_attestation_v1_all_checks_passed" not in rendered
    assert '"message_id": "202"' not in rendered
    assert accepted_callback.split("|")[2] not in rendered


def test_telegram_playback_acceptance_callback_does_not_expose_recording_exception(
    monkeypatch,
) -> None:
    from app.api.routes import channels

    monkeypatch.setenv("EA_TELEGRAM_CALLBACK_SECRET", "callback-secret")
    callback_data = channels._telegram_encode_audiobook_playback_callback(
        bot_config={"token": "telegram-token"},
        action="a",
        token="playback-token",
        chat_id="42",
    )

    def _fail_record(**_: object) -> None:
        raise RuntimeError("permission_denied /private/books/Secret.epub voice_id=private-voice")

    monkeypatch.setattr(
        channels,
        "record_audiobook_playback_acceptance_by_callback_token",
        _fail_record,
    )

    decision = channels._telegram_callback_turn_decision(
        SimpleNamespace(
            payload={
                "kind": "callback_query",
                "callback_data": callback_data,
                "_bot_config": {"token": "telegram-token"},
            },
            chat_id="42",
            container=object(),
            principal_id="principal-1",
            current_message_id="202",
        )
    )

    assert decision.reply_text == (
        "I could not record that audiobook playback result. "
        "Current blocker: audiobook_playback_acceptance_failed."
    )
    assert "/private/books/Secret.epub" not in decision.reply_text
    assert "private-voice" not in decision.reply_text
    assert "permission_denied" not in decision.reply_text


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
    monkeypatch.setenv("EA_AUDIOBOOK_CANARY_RECEIPT_HMAC_KEY", "test-canary-key")

    job = {
        "job_id": "job-playback-host",
        "status": "audiobookshelf_imported",
        "metadata": {"title": "Test Book", "author": "A. Writer", "language": "en-US"},
        "storage": {"job_dir": str(job_dir)},
        "whatsapp": {"sender_ref": "4368120864006"},
        "merge_result": {"status": "m4b_ready", "output_file": str(target_path), "chapter_count": 2},
        "audio_publication_gate": {"status": "pass", "issues": []},
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
    pipeline._write_private_json(job_dir / "job.json", job)
    prepared = pipeline.ensure_audiobook_playback_acceptance_callback(job)
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


def test_playback_acceptance_callback_is_atomically_single_use(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-single-use-callback"
    job_dir.mkdir(parents=True)
    target_path = tmp_path / "audiobookshelf" / "Book.m4b"
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(b"artifact")
    job = {
        "job_id": "job-single-use-callback",
        "status": "audiobookshelf_imported",
        "storage": {"job_dir": str(job_dir)},
        "telegram": {"chat_id": "42"},
        "audio_publication_gate": {"status": "pass", "issues": []},
        "audiobookshelf_import": {
            "status": "imported",
            "target_path": str(target_path),
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://abs.example.com/share/single-use",
                "telegram_delivery": {"status": "sent", "message_id": "101"},
            },
        },
    }
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setenv("EA_AUDIOBOOK_CANARY_RECEIPT_HMAC_KEY", "test-canary-key")
    pipeline._write_private_json(job_dir / "job.json", job)
    prepared = pipeline.ensure_audiobook_playback_acceptance_callback(job)
    token = str(
        prepared["audiobookshelf_import"]["public_share"][
            "playback_acceptance_callback"
        ]["token"]
    )
    barrier = threading.Barrier(2)

    def _submit(_: bool) -> str:
        barrier.wait(timeout=5)
        try:
            pipeline.record_audiobook_playback_acceptance_by_callback_token(
                callback_token=token,
                accepted=False,
                source="telegram_button",
                message_id="203",
                feedback="telegram_button_playback_problem",
            )
        except RuntimeError as exc:
            return str(exc)
        return "applied"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(_submit, (True, False)))

    assert outcomes.count("applied") == 1
    assert outcomes.count("audiobook_playback_acceptance_token_not_found") == 1
    persisted = pipeline._load_job(job_dir)
    callback = persisted["audiobookshelf_import"]["public_share"][
        "playback_acceptance_callback"
    ]
    assert callback["status"] == "consumed"
    assert "token" not in callback
    assert persisted["playback_acceptance"]["status"] == "rejected"


def test_playback_callback_state_uses_only_canonical_job_lock(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-callback-lock"
    job_dir.mkdir(parents=True)
    target_path = tmp_path / "audiobookshelf" / "Lock Book.m4b"
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(b"locked artifact")
    job = {
        "job_id": "job-callback-lock",
        "status": "audiobookshelf_imported",
        "storage": {"job_dir": str(job_dir)},
        "telegram": {"chat_id": "42"},
        "audio_publication_gate": {"status": "pass", "issues": []},
        "audiobookshelf_import": {
            "status": "imported",
            "target_path": str(target_path),
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://abs.example.com/share/lock-book",
                "telegram_delivery": {"status": "sent", "message_id": "101"},
            },
        },
    }
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setenv("EA_AUDIOBOOK_CANARY_RECEIPT_HMAC_KEY", "test-canary-key")
    monkeypatch.setenv("EA_AUDIOBOOK_JOB_LOCK_TIMEOUT_SECONDS", "0.1")
    pipeline._write_private_json(job_dir / "job.json", job)
    prepared = pipeline.ensure_audiobook_playback_acceptance_callback(job)
    token = str(
        prepared["audiobookshelf_import"]["public_share"][
            "playback_acceptance_callback"
        ]["token"]
    )

    with pipeline._exclusive_audiobook_job_lock(job_dir):
        with pytest.raises(
            pipeline._AudiobookLockTimeout,
            match="audiobook_job_lock_timeout",
        ):
            pipeline.ensure_audiobook_playback_acceptance_callback(prepared)
        with pytest.raises(
            pipeline._AudiobookLockTimeout,
            match="audiobook_job_lock_timeout",
        ):
            pipeline.record_audiobook_playback_acceptance_by_callback_token(
                callback_token=token,
                accepted=False,
                source="telegram_button",
                message_id="203",
                feedback="telegram_button_playback_problem",
            )
        with pytest.raises(
            pipeline._AudiobookLockTimeout,
            match="audiobook_job_lock_timeout",
        ):
            pipeline.record_audiobook_playback_acceptance(
                job_dir=job_dir,
                accepted=False,
                source="telegram_button",
                message_id="203",
                feedback="telegram_button_playback_problem",
            )

    lock_path = job_dir / ".audiobook-job.lock"
    assert lock_path.is_file()
    assert lock_path.stat().st_mode & 0o777 == 0o600
    assert not (job_dir / ".audiobook-render.lock").exists()


def test_callback_ensure_cannot_resurrect_consumed_stale_state(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-no-callback-resurrection"
    job_dir.mkdir(parents=True)
    target_path = tmp_path / "audiobookshelf" / "No Resurrection.m4b"
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(b"current artifact")
    job = {
        "job_id": "job-no-callback-resurrection",
        "status": "audiobookshelf_imported",
        "storage": {"job_dir": str(job_dir)},
        "telegram": {"chat_id": "42"},
        "audio_publication_gate": {"status": "pass", "issues": []},
        "audiobookshelf_import": {
            "status": "imported",
            "target_path": str(target_path),
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://abs.example.com/share/no-resurrection",
                "telegram_delivery": {"status": "sent", "message_id": "101"},
            },
        },
    }
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setenv("EA_AUDIOBOOK_CANARY_RECEIPT_HMAC_KEY", "test-canary-key")
    pipeline._write_private_json(job_dir / "job.json", job)
    prepared = pipeline.ensure_audiobook_playback_acceptance_callback(job)
    stale_prepared = json.loads(json.dumps(prepared))
    token = str(
        prepared["audiobookshelf_import"]["public_share"][
            "playback_acceptance_callback"
        ]["token"]
    )

    consumed = pipeline.record_audiobook_playback_acceptance_by_callback_token(
        callback_token=token,
        accepted=False,
        source="telegram_button",
        message_id="203",
        feedback="telegram_button_playback_problem",
    )
    assert consumed["audiobookshelf_import"]["public_share"][
        "playback_acceptance_callback"
    ]["status"] == "consumed"

    refreshed = pipeline.ensure_audiobook_playback_acceptance_callback(
        stale_prepared
    )
    callback = refreshed["audiobookshelf_import"]["public_share"][
        "playback_acceptance_callback"
    ]
    assert callback["status"] == "consumed"
    assert "token" not in callback
    persisted = pipeline._load_job(job_dir)
    assert persisted["audiobookshelf_import"]["public_share"][
        "playback_acceptance_callback"
    ] == callback


def test_playback_callback_is_not_issued_before_publication_gate_passes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-gate-missing"
    job_dir.mkdir(parents=True)
    target_path = tmp_path / "audiobookshelf" / "Ungated.m4b"
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(b"ungated artifact")
    job = {
        "job_id": "job-gate-missing",
        "status": "audiobookshelf_imported",
        "storage": {"job_dir": str(job_dir)},
        "audiobookshelf_import": {
            "status": "imported",
            "target_path": str(target_path),
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://abs.example.com/share/ungated",
            },
        },
    }
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    pipeline._write_private_json(job_dir / "job.json", job)

    unchanged = pipeline.ensure_audiobook_playback_acceptance_callback(job)

    public_share = unchanged["audiobookshelf_import"]["public_share"]
    assert "playback_acceptance_callback" not in public_share


def test_registry_only_telegram_callback_is_blocked_without_canary_hmac_key(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-registry-only-callback"
    job_dir.mkdir(parents=True)
    target_path = tmp_path / "audiobookshelf" / "Registry Only.m4b"
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(b"registry-only artifact")
    job = {
        "job_id": "job-registry-only-callback",
        "status": "audiobookshelf_imported",
        "storage": {"job_dir": str(job_dir)},
        "telegram": {"chat_id": "42"},
        "audio_publication_gate": {"status": "pass", "issues": []},
        "audiobookshelf_import": {
            "status": "imported",
            "target_path": str(target_path),
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://abs.example.com/share/registry-only",
                "playback_acceptance_callback": {
                    "status": "ready",
                    "token": "legacy-registry-token",
                },
            },
        },
    }
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setenv(
        "EA_TELEGRAM_BOT_REGISTRY_JSON",
        json.dumps({"registry-bot": {"token": "registry-only-secret"}}),
    )
    for key in (
        "EA_AUDIOBOOK_CANARY_RECEIPT_HMAC_KEY",
        "EA_TELEGRAM_CALLBACK_SECRET",
        "EA_TELEGRAM_BOT_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)
    pipeline._write_private_json(job_dir / "job.json", job)

    blocked = pipeline.ensure_audiobook_playback_acceptance_callback(job)

    callback = blocked["audiobookshelf_import"]["public_share"][
        "playback_acceptance_callback"
    ]
    assert callback["status"] == "blocked"
    assert callback["reason"] == "canary_receipt_hmac_key_unavailable"
    assert "token" not in callback


def test_incomplete_playback_acceptance_is_not_scheduler_terminal() -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    incomplete = {
        "status": "audiobookshelf_imported",
        "playback_acceptance": {
            "status": "accepted",
            "accepted": True,
            "listened": False,
        },
    }
    complete = {
        **incomplete,
        "playback_acceptance": {
            "status": "listened_canary_accepted",
            "accepted": True,
            "listened": True,
        },
    }

    assert pipeline._audiobook_completed_terminal_reason(incomplete) == ""
    assert (
        pipeline._audiobook_completed_terminal_reason(complete)
        == "playback_accepted"
    )


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
            principal_id="principal-1",
            current_message_id="201",
        )
    )

    assert decision.reply_text == (
        "Dismissed. The replacement audiobook voice sample is already in Telegram. "
        "Use the latest buttons, or reply with the voice name."
    )
    assert sent == []


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
            principal_id="principal-1",
            current_message_id="301",
        )
    )

    assert "selected voice for Test Book is blocked" in decision.reply_text
    assert "I sent 1 replacement voice sample" in decision.reply_text
    assert sent == [["Piper German Thorsten high"]]


def test_telegram_voice_dismiss_callback_duplicate_dedupe_key_is_ignored(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.api.routes import channels
    from app.repositories.delivery_outbox import InMemoryDeliveryOutboxRepository
    from app.repositories.observation import InMemoryObservationEventRepository
    from app.services.channel_runtime import ChannelRuntimeService

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

    sent: list[list[str]] = []

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

    runtime = ChannelRuntimeService(InMemoryObservationEventRepository(), InMemoryDeliveryOutboxRepository())
    container = SimpleNamespace(channel_runtime=runtime)
    payload = {
        "kind": "callback_query",
        "callback_query_id": "cb-dismiss-1",
        "callback_data": channels._telegram_encode_audiobook_voice_callback(
            bot_config={"token": "bot-token"},
            action="d",
            token="sample-token-two",
            chat_id="42",
        ),
        "_bot_config": {"token": "bot-token", "secret": "callback-secret"},
        "_dedupe_key": "telegram:42:callback:cb-dismiss-1",
        "text": "Voice sample",
    }

    first = channels._telegram_callback_turn_decision(
        SimpleNamespace(
            payload=dict(payload),
            chat_id="42",
            container=container,
            principal_id="principal-1",
            current_message_id="401",
        )
    )
    second = channels._telegram_callback_turn_decision(
        SimpleNamespace(
            payload=dict(payload),
            chat_id="42",
            container=container,
            principal_id="principal-1",
            current_message_id="401",
        )
    )

    assert first.reply_text == (
        "Dismissed. The replacement audiobook voice sample is already in Telegram. "
        "Use the latest buttons, or reply with the voice name."
    )
    assert second.reply_text == ""
    assert sent == []
    processed = runtime.find_observation_by_dedupe(
        "telegram:42:callback:cb-dismiss-1:callback_processed",
        principal_id="principal-1",
    )
    assert processed is not None
    assert processed.payload["callback_kind"] == "ab"


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
    from app.services import audiobook_epub_pipeline as pipeline
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
    chapter = EpubChapter(index=1, title="Test", source_href="test.xhtml", text_path="001 - Test.txt", audio_filename="001 - Test.wav", char_count=len(text), sha256=pipeline._sha256_bytes(text.encode("utf-8")))

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
    from app.services import audiobook_epub_pipeline as pipeline
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
    _mock_publication_gate_contract_pass(monkeypatch, pipeline)

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


def test_authenticated_catalog_voice_label_is_bounded_normalized_and_private_id_safe() -> None:
    from app.services.audiobook_epub_pipeline import (
        _safe_authenticated_catalog_voice_label,
    )

    assert _safe_authenticated_catalog_voice_label(
        "  Clear\n narrator\t",
        "private-voice-id",
    ) == "Clear narrator"
    assert len(_safe_authenticated_catalog_voice_label("x" * 200)) == 120
    assert _safe_authenticated_catalog_voice_label(
        "Premium RAW-PRIVATE-VOICE-ID",
        "raw-private-voice-id",
    ) == "Dialogue voice"
    assert _safe_authenticated_catalog_voice_label("") == "Dialogue voice"


def test_voice_selection_does_not_infer_author_gender_from_name(
    monkeypatch,
    tmp_path: Path,
) -> None:
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
    text = "This nonfiction chapter explains the process in a calm practical way."
    selections: list[dict[str, object]] = []
    for index, author in enumerate(("Knuf, Andreas", "Austen, Jane"), start=1):
        job_dir = tmp_path / f"job-{index}"
        chapter_dir = job_dir / "chapters"
        chapter_dir.mkdir(parents=True)
        (chapter_dir / "001 - Test.txt").write_text(text, encoding="utf-8")
        metadata = EpubMetadata(
            title="Calm Guide",
            author=author,
            language="en-US",
            source_filename="book.epub",
            source_sha256="sha",
        )
        chapter = EpubChapter(
            index=1,
            title="Test",
            source_href="test.xhtml",
            text_path="001 - Test.txt",
            audio_filename="001 - Test.wav",
            char_count=len(text),
            sha256="sha",
        )
        selections.append(
            select_unmixr_voice_for_book(
                metadata=metadata,
                chapters=(chapter,),
                job_dir=job_dir,
            )
        )

    for selection in selections:
        public = dict(selection["public"])
        profile = dict(public["book_profile"])
        selected = dict(public["selected"])
        assert profile["author_gender_signal"] == ""
        assert profile["author_gender_signal_provenance"] == (
            "not_available_without_explicit_approved_metadata"
        )
        assert public["author_gender_preference_used"] is False
        assert selected["author_gender_match"] is False
    assert [
        dict(row)["voice_id_sha256"]
        for row in list(dict(selections[0]["public"])["candidate_scores"])
    ] == [
        dict(row)["voice_id_sha256"]
        for row in list(dict(selections[1]["public"])["candidate_scores"])
    ]
    assert dict(dict(selections[0]["public"])["selected"])[
        "voice_id_sha256"
    ] == dict(dict(selections[1]["public"])["selected"])["voice_id_sha256"]


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


def test_voice_audition_batch_dedupes_display_voice_family(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import create_job_from_epub

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "0")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": "seraphina-express-id", "label": "Seraphina (Express)", "language": "en-US", "tags": ["audiobook", "narration", "clear"]},
                {"voice_id": "seraphina-standard-id", "label": "Seraphina", "language": "en-US", "tags": ["audiobook", "narration", "clear"]},
                {"voice_id": "gretchen-id", "label": "Gretchen", "language": "en-US", "tags": ["audiobook", "narration", "clear"]},
                {"voice_id": "conrad-id", "label": "Conrad", "language": "en-US", "tags": ["audiobook", "narration", "clear"]},
            ]
        ),
    )
    tones: dict[str, bytes] = {}
    for index, voice_id in enumerate(("seraphina-express-id", "gretchen-id", "conrad-id"), start=1):
        tone = tmp_path / f"{voice_id}.wav"
        _write_tone_wav(tone, seconds=0.10 + index * 0.02)
        tones[voice_id] = tone.read_bytes()
    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", lambda **kwargs: (tones[str(kwargs["voice_id"])], "audio/wav"))
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)
    epub = tmp_path / "book.epub"
    _write_minimal_epub(epub)

    job = create_job_from_epub(epub_path=epub, original_filename="book.epub", principal_id="principal-1")

    voice_selection = job["provider"]["voice_selection"]
    labels = [row["label"] for row in voice_selection["pending_batch"]]
    family_keys = [pipeline._voice_label_family_key(label) for label in labels]
    assert labels == ["Seraphina (Express)", "Gretchen", "Conrad"]
    assert len(family_keys) == len(set(family_keys))
    assert "Seraphina" not in labels[1:]
    assert voice_selection["sample_generation_failed_count"] == 0


def test_voice_audition_does_not_infer_author_gender_from_name(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import create_job_from_epub

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "0")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": "seraphina-id", "label": "Seraphina", "language": "de-DE", "tags": ["audiobook", "narration", "clear", "female"]},
                {"voice_id": "gisela-id", "label": "Gisela", "language": "de-DE", "tags": ["audiobook", "narration", "warm", "female"]},
                {"voice_id": "amala-id", "label": "Amala", "language": "de-DE", "tags": ["audiobook", "narration", "female"]},
                {"voice_id": "florian-id", "label": "Florian", "language": "de-DE", "tags": ["general", "male"]},
                {"voice_id": "hans-id", "label": "Hans", "language": "de-DE", "tags": ["general", "male"]},
                {"voice_id": "dieter-id", "label": "Dieter", "language": "de-DE", "tags": ["general", "male"]},
            ]
        ),
    )
    tones: dict[str, bytes] = {}
    voice_ids = (
        "seraphina-id",
        "gisela-id",
        "amala-id",
        "florian-id",
        "hans-id",
        "dieter-id",
    )
    for index, voice_id in enumerate(voice_ids, start=1):
        tone = tmp_path / f"{voice_id}.wav"
        _write_tone_wav(tone, seconds=0.10 + index * 0.02)
        tones[voice_id] = tone.read_bytes()
    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", lambda **kwargs: (tones[str(kwargs["voice_id"])], "audio/wav"))
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)
    batches: list[list[str]] = []
    for index, author in enumerate(("Knuf, Andreas", "Austen, Jane"), start=1):
        epub = tmp_path / f"book-{index}.epub"
        _write_minimal_epub(epub, author=author, language="de")
        job = create_job_from_epub(
            epub_path=epub,
            original_filename=epub.name,
            principal_id=f"principal-{index}",
        )
        voice_selection = dict(dict(job["provider"])["voice_selection"])
        profile = dict(voice_selection["book_profile"])
        pending = [dict(row) for row in list(voice_selection["pending_batch"])]
        assert profile["author_gender_signal"] == ""
        assert profile["author_gender_signal_provenance"] == (
            "not_available_without_explicit_approved_metadata"
        )
        assert voice_selection["author_gender_preference_used"] is False
        assert len(pending) == 3
        assert all(row["author_gender_match"] is False for row in pending)
        batches.append([str(row["voice_id_sha256"]) for row in pending])

    assert batches[0] == batches[1]


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
    synthesize_voice = _distinct_voice_wav_synthesizer(tmp_path)
    calls: list[str] = []

    def fake_synthesize_request(**kwargs):
        calls.append(str(kwargs.get("voice_id") or ""))
        return synthesize_voice(**kwargs)

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


def test_epub_voice_audition_automatic_cast_skips_optional_preview_and_resumes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-auto-cast"
    private_dir = job_dir / "voice_audition"
    private_dir.mkdir(parents=True)
    job_payload = {
        "job_id": "job-auto-cast",
        "status": "waiting_voice_selection",
        "storage": {"job_dir": str(job_dir)},
        "metadata": {
            "title": "Automatic Cast Book",
            "author": "A. Writer",
            "language": "en-US",
        },
        "totals": {"chapter_count": 1, "char_count": 1200},
        "eta": {"estimated_minutes_after_unblocked": 4},
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "pending_candidate_keys": ["ranked-best", "ranked-second"],
                "pending_batch": [
                    {
                        "preset_key": "ranked-best",
                        "callback_token": "auto-cast-token",
                        "label": "Ranked Best",
                        "language": "en-US",
                    },
                    {
                        "preset_key": "ranked-second",
                        "callback_token": "carrier-token",
                        "label": "Ranked Second",
                        "language": "en-US",
                    }
                ],
            }
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job_payload), encoding="utf-8")
    (private_dir / "private.json").write_text(
        json.dumps(
            {
                "contract_name": "ea.telegram_epub_audiobook_voice_audition.v1",
                "automatic_narrator_selection": {
                    "status": "ready",
                    "voice_id_sha256": "a" * 64,
                },
                "candidates": {
                    "auto-cast-token": {
                        "candidate_key": "ranked-best",
                        "voice_id": "private-ranked-best-voice",
                        "voice_id_sha256": "b" * 64,
                        "public": {
                            "preset_key": "ranked-best",
                            "callback_token": "auto-cast-token",
                            "label": "Ranked Best",
                            "language": "en-US",
                            "voice_id_sha256": "b" * 64,
                        },
                    },
                    "carrier-token": {
                        "candidate_key": "ranked-second",
                        "voice_id": "private-ranked-second-voice",
                        "voice_id_sha256": "c" * 64,
                        "public": {
                            "preset_key": "ranked-second",
                            "callback_token": "carrier-token",
                            "label": "Ranked Second",
                            "language": "en-US",
                            "voice_id_sha256": "c" * 64,
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
    monkeypatch.setattr(
        pipeline,
        "unmixr_synthesize_request",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("automatic-cast choice must not call a live provider")
        ),
    )

    updated = pipeline.apply_audiobook_voice_audition_action(
        callback_token="carrier-token",
        action="use_automatic_cast",
    )

    selection = updated["provider"]["voice_selection"]
    assert updated["status"] == "voice_selected"
    assert updated["next_action"] == "render_chapter_audio"
    assert selection["selected"]["label"] == "Ranked Best"
    assert selection["automatic_cast_approved_by_user"] is True
    assert selection["optional_preview_skipped"] is True
    assert selection["last_action"]["action"] == "use_automatic_cast"
    assert "automatically at your request" in pipeline.telegram_epub_reply_text(updated)
    private = json.loads((private_dir / "private.json").read_text(encoding="utf-8"))
    assert private["selected_callback_token"] == "auto-cast-token"
    assert "automatic_narrator_selection" not in private
    assert "private-ranked-best-voice" not in json.dumps(updated)
    assert "private-ranked-second-voice" not in json.dumps(updated)


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
    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", _distinct_voice_wav_synthesizer(tmp_path))
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


def test_epub_voice_audition_dismiss_replacement_skips_same_display_family(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import apply_audiobook_voice_audition_action, create_job_from_epub

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "0")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": "seraphina-express-id", "label": "Seraphina (Express)", "language": "en-US", "tags": ["audiobook", "narration", "clear"]},
                {"voice_id": "seraphina-standard-id", "label": "Seraphina", "language": "en-US", "tags": ["audiobook", "narration", "clear"]},
                {"voice_id": "gretchen-id", "label": "Gretchen", "language": "en-US", "tags": ["audiobook", "narration", "clear"]},
                {"voice_id": "conrad-id", "label": "Conrad", "language": "en-US", "tags": ["audiobook", "narration", "clear"]},
                {"voice_id": "florian-id", "label": "Florian", "language": "en-US", "tags": ["audiobook", "narration", "clear"]},
            ]
        ),
    )
    tones: dict[str, bytes] = {}
    for index, voice_id in enumerate(("seraphina-express-id", "gretchen-id", "conrad-id", "florian-id"), start=1):
        tone = tmp_path / f"{voice_id}.wav"
        _write_tone_wav(tone, seconds=0.10 + index * 0.02)
        tones[voice_id] = tone.read_bytes()
    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", lambda **kwargs: (tones[str(kwargs["voice_id"])], "audio/wav"))
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)
    epub = tmp_path / "book.epub"
    _write_minimal_epub(epub)

    job = create_job_from_epub(epub_path=epub, original_filename="book.epub", principal_id="principal-1")
    first = job["provider"]["voice_selection"]["pending_batch"][0]
    assert first["label"] == "Seraphina (Express)"

    job = apply_audiobook_voice_audition_action(callback_token=first["callback_token"], action="dismiss")

    selection = job["provider"]["voice_selection"]
    labels = [row["label"] for row in selection["pending_batch"]]
    assert set(labels) == {"Gretchen", "Conrad", "Florian"}
    assert len(labels) == 3
    assert "Seraphina" not in labels
    assert "label_family:seraphina" in selection["dismissed_voice_identity_keys"]
    assert selection["last_action"]["replacement_count"] == 1


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
    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", _distinct_voice_wav_synthesizer(tmp_path))
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
    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", _distinct_voice_wav_synthesizer(tmp_path))
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
    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", _distinct_voice_wav_synthesizer(tmp_path))
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
    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", _distinct_voice_wav_synthesizer(tmp_path))
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
    from app.services.audiobook_epub_pipeline import create_job_from_epub, prepare_audiobook_voice_audition

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
    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", _distinct_voice_wav_synthesizer(tmp_path))
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
    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", _distinct_voice_wav_synthesizer(tmp_path))
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
    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", _distinct_voice_wav_synthesizer(tmp_path))
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
    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", _distinct_voice_wav_synthesizer(tmp_path))
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
    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", _distinct_voice_wav_synthesizer(tmp_path))
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


def test_telegram_send_audiobook_voice_samples_records_inline_controls(monkeypatch, tmp_path: Path) -> None:
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
    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", _distinct_voice_wav_synthesizer(tmp_path))
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)

    sent_payloads: list[dict[str, object]] = []

    def fake_send_audio(**kwargs):
        sent_payloads.append(kwargs)
        return {"ok": True, "result": {"message_id": 4200 + len(sent_payloads)}}

    monkeypatch.setattr(channels, "_telegram_send_audio", fake_send_audio)
    epub = tmp_path / "book.epub"
    _write_minimal_epub(epub)
    job = create_job_from_epub(epub_path=epub, original_filename="book.epub", principal_id="principal-1", chat_id="42")

    receipts = channels._telegram_send_audiobook_voice_samples(
        bot_config={"token": "bot-token", "secret": "callback-secret"},
        chat_id="42",
        job=job,
    )

    assert len(receipts) == 3
    assert {row["status"] for row in receipts} == {"sent"}
    assert [row["button_count"] for row in receipts] == [3, 3, 3]
    assert {row["control_kind"] for row in receipts} == {"inline_keyboard"}
    assert all(row["media_message_id_sha256"] for row in receipts)
    assert all(payload["inline_buttons"] for payload in sent_payloads)
    first_buttons = [
        item
        for row in sent_payloads[0]["inline_buttons"]
        for item in row
    ]
    assert any(
        label == "Use automatic cast" and callback.startswith("ab|a|")
        for label, callback in first_buttons
    )
    assert "Preview is optional" in str(sent_payloads[0]["caption"])
    automatic_callbacks = [
        callback
        for payload in sent_payloads
        for row in payload["inline_buttons"]
        for label, callback in row
        if label == "Use automatic cast"
    ]
    assert len(automatic_callbacks) == 3
    assert {callback.split("|")[2] for callback in automatic_callbacks} == {
        job["provider"]["voice_selection"]["pending_batch"][0]["callback_token"]
    }


def test_telegram_automatic_cast_control_survives_first_preview_send_failure(
    monkeypatch,
) -> None:
    from app.api.routes import channels

    samples = [
        {"token": "ranked-token", "label": "Ranked Voice", "audio_path": "/unused/one.wav"},
        {"token": "second-token", "label": "Second Voice", "audio_path": "/unused/two.wav"},
    ]
    monkeypatch.setenv("EA_TELEGRAM_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setattr(
        channels,
        "_telegram_audiobook_voice_samples_pending_delivery",
        lambda _job: list(samples),
    )
    attempts: list[dict[str, object]] = []

    def _fake_send_audio(**kwargs):
        attempts.append(dict(kwargs))
        if len(attempts) == 1:
            raise RuntimeError("first_preview_delivery_failed")
        return {"ok": True, "result": {"message_id": 2}}

    monkeypatch.setattr(channels, "_telegram_send_audio", _fake_send_audio)

    receipts = channels._telegram_send_audiobook_voice_samples(
        bot_config={"token": "bot-token", "secret": "callback-secret"},
        chat_id="42",
        job={"job_id": "job-first-preview-fails"},
    )

    assert [row["status"] for row in receipts] == ["failed", "sent"]
    delivered_callbacks = [
        callback
        for row in attempts[1]["inline_buttons"]
        for label, callback in row
        if label == "Use automatic cast"
    ]
    assert len(delivered_callbacks) == 1
    assert delivered_callbacks[0].startswith("ab|a|ranked-token|")


@pytest.mark.parametrize(
    "unproven_receipt",
    [
        {"ok": True, "result": {}},
        {"ok": True, "result": {"message_id": {"malformed": "id"}}},
        {"ok": 1, "result": {"message_id": 7}},
    ],
)
def test_telegram_unproven_transport_receipts_are_never_confirmed(
    monkeypatch,
    unproven_receipt: dict[str, object],
) -> None:
    from app.api.routes import channels

    monkeypatch.setattr(
        channels,
        "_telegram_audiobook_voice_samples_pending_delivery",
        lambda _job: [
            {
                "token": "sample-token",
                "label": "Narrator",
                "audio_path": "/unused/sample.wav",
            }
        ],
    )
    monkeypatch.setattr(
        channels,
        "_telegram_send_audio",
        lambda **_: dict(unproven_receipt),
    )
    receipts = channels._telegram_send_audiobook_voice_samples(
        bot_config={"token": "bot-token", "secret": "callback-secret"},
        chat_id="requester",
        job={"job_id": "unproven-receipt"},
    )

    assert receipts[0]["status"] == "skipped"
    assert receipts[0]["effect_state"] == "ambiguous"
    assert receipts[0]["media_message_id_sha256"] == ""

    monkeypatch.setattr(
        channels,
        "_telegram_send_audiobook_voice_samples",
        lambda **_: [],
    )
    monkeypatch.setattr(
        channels,
        "_telegram_audiobook_playback_acceptance_buttons",
        lambda **kwargs: (dict(kwargs["job"]), []),
    )
    monkeypatch.setattr(
        channels,
        "_telegram_send_message",
        lambda **_: dict(unproven_receipt),
    )
    outcome = channels._telegram_deliver_started_audiobook_request(
        bot_config={"token": "bot-token"},
        record={"telegram": {"chat_id": "requester"}},
        job={"job_id": "unproven-final-reply"},
    )
    assert outcome["classification"] == "outcome_unknown"
    assert outcome["confirmed_effect_count"] == 0
    assert outcome["ambiguous_effect_count"] == 1


def test_whatsapp_send_audiobook_voice_samples_exposes_optional_automatic_cast(
    monkeypatch,
) -> None:
    from app.api.routes import channels

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "voice-secret")
    monkeypatch.setattr(
        channels,
        "audiobook_voice_audition_sample_messages",
        lambda _job: [
            {
                "token": "voice-token-one",
                "label": "Voice One",
                "matched_tags": ["warm"],
            },
            {
                "token": "voice-token-two",
                "label": "Voice Two",
                "matched_tags": ["clear"],
            },
        ],
    )
    sent_payloads: list[dict[str, object]] = []

    def _fake_send_whatsapp_delivery_text(**kwargs):
        sent_payloads.append(dict(kwargs))
        return SimpleNamespace(
            message_ids=(
                ()
                if len(sent_payloads) == 1
                else (f"wamid.{len(sent_payloads)}",)
            ),
            delivery_transport="whatsapp_web_session",
        )

    monkeypatch.setattr(
        channels.whatsapp_delivery_router,
        "send_whatsapp_delivery_text",
        _fake_send_whatsapp_delivery_text,
    )

    receipts = channels._whatsapp_send_audiobook_voice_samples(
        tool_runtime=object(),
        principal_id="principal-1",
        recipient="4368120864006",
        job={"job_id": "job-auto-controls"},
    )

    assert [row["status"] for row in receipts] == ["skipped", "sent"]
    first_buttons = [
        item
        for row in sent_payloads[0]["buttons"]
        for item in row
    ]
    assert any(
        label == "Use automatic cast" and callback.startswith("ab|a|")
        for label, callback in first_buttons
    )
    assert "Preview is optional" in str(sent_payloads[0]["text"])
    automatic_callbacks = [
        callback
        for payload in sent_payloads
        for row in payload["buttons"]
        for label, callback in row
        if label == "Use automatic cast"
    ]
    assert len(automatic_callbacks) == 2
    assert {callback.split("|")[2] for callback in automatic_callbacks} == {
        "voice-token-one"
    }


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


def test_audiobook_runtime_preflight_reports_disconnected_jobs_root_without_crashing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    jobs_root = tmp_path / "jobs"
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_TELEGRAM_AUDIOBOOK_EPUB_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_IMPORT_ROOT", str(tmp_path / "audiobookshelf"))
    monkeypatch.setattr(pipeline, "_storage_path_accessible", lambda path: True)

    real_exists = Path.exists

    def disconnected_exists(self: Path) -> bool:
        if self == jobs_root or self.as_posix() == jobs_root.as_posix():
            raise OSError(errno.ENOTCONN, "Transport endpoint is not connected")
        return real_exists(self)

    monkeypatch.setattr(Path, "exists", disconnected_exists)

    receipt = pipeline.audiobook_runtime_preflight()
    rendered = json.dumps(receipt, sort_keys=True)

    assert receipt["status"] == "fail"
    assert "jobs_root_writable" in receipt["failed_checks"]
    jobs_root_check = next(row for row in receipt["checks"] if row["key"] == "jobs_root_writable")
    assert jobs_root_check["status"] == "fail"
    assert str(jobs_root) not in rendered


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
    monkeypatch.setenv("EA_AUDIOBOOK_CINEMATIC_NARRATION", "0")
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
    chapter = EpubChapter(index=1, title="Test", source_href="test.xhtml", text_path="001 - Test.txt", audio_filename="001 - Test.wav", char_count=len(text), sha256=pipeline._sha256_bytes(text.encode("utf-8")))
    metadata = EpubMetadata(title="Test Book", author="A. Writer", language="de", source_filename="book.epub", source_sha256="sha")
    tone = tmp_path / "tone.wav"
    _write_tone_wav(tone)
    calls = {"count": 0}

    def fake_synthesize_request(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise HTTPException(status_code=502, detail="unmixr_tts_no_audio_url voice-1")
        return tone.read_bytes(), "audio/wav"

    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", fake_synthesize_request)

    result = render_unmixr_chapter_audio(job_dir=tmp_path, chapters=(chapter,), metadata=metadata)

    assert result["status"] == "rendered"
    assert calls["count"] == 2
    assert result["chapters"][0]["retry_errors"] == [
        "attempt_1:unmixr_synthesize_upstream_unavailable"
    ]
    assert "voice-1" not in json.dumps(result, sort_keys=True)
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
        sha256=pipeline._sha256_bytes(text.encode("utf-8")),
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
    monkeypatch.setenv("EA_AUDIOBOOK_SEGMENT_EDGE_TRIM_ENABLED", "0")
    monkeypatch.setenv("UNMIXR_VOICE_ID", "voice-default")
    monkeypatch.setattr(pipeline, "_normalize_rendered_audio_file", lambda path: path)
    chapter_dir = tmp_path / "chapters"
    chapter_dir.mkdir()
    text = "This chapter has a rendered ending that should not fade into silence."
    (chapter_dir / "001 - Test.txt").write_text(text, encoding="utf-8")
    chapter = EpubChapter(index=1, title="Test", source_href="test.xhtml", text_path="001 - Test.txt", audio_filename="001 - Test.wav", char_count=len(text), sha256=pipeline._sha256_bytes(text.encode("utf-8")))
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
    text = "\n\n".join(
        (
            f"Section {section_index} is a long audiobook passage that should be split "
            "into multiple provider calls while retaining a unique cache fingerprint. "
        )
        * 18
        for section_index in range(1, 5)
    )
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
    from app.services.audiobook_epub_pipeline import (
        _sha256_bytes,
        build_audiobook_job_receipt,
    )

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


def test_telegram_audiobook_voice_callback_invokes_automatic_cast(
    monkeypatch,
) -> None:
    from app.api.routes import channels

    calls: dict[str, str] = {}

    def _fake_apply(*, callback_token: str, action: str) -> dict[str, object]:
        calls.update(callback_token=callback_token, action=action)
        return {
            "job_id": "job-auto-cast",
            "status": "voice_selected",
            "provider": {
                "voice_selection": {
                    "status": "selected_by_user",
                    "automatic_cast_approved_by_user": True,
                    "optional_preview_skipped": True,
                }
            },
        }

    monkeypatch.setenv("EA_TELEGRAM_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setattr(
        channels,
        "apply_audiobook_voice_audition_action",
        _fake_apply,
    )
    monkeypatch.setattr(
        channels,
        "telegram_epub_reply_text",
        lambda _job: "Automatic narrator and dialogue cast selected.",
    )
    callback_data = channels._telegram_encode_audiobook_voice_callback(
        bot_config={"token": "bot-token", "secret": "callback-secret"},
        action="a",
        token="sample-token-auto",
        chat_id="42",
    )

    decision = channels._telegram_callback_turn_decision(
        SimpleNamespace(
            payload={
                "kind": "callback_query",
                "callback_data": callback_data,
                "_bot_config": {
                    "token": "bot-token",
                    "secret": "callback-secret",
                },
            },
            chat_id="42",
            container=object(),
            principal_id="principal-1",
            current_message_id="901",
        )
    )

    assert callback_data.startswith("ab|a|sample-token-auto|")
    assert calls == {
        "callback_token": "sample-token-auto",
        "action": "use_automatic_cast",
    }
    assert decision.reply_text == "Automatic narrator and dialogue cast selected."


def test_telegram_audiobook_voice_callback_sanitizes_apply_error(
    monkeypatch,
) -> None:
    from app.api.routes import channels

    def _fail_apply(**_: object) -> None:
        raise RuntimeError(
            "permission_denied /private/books/Secret.epub voice_id=private-voice"
        )

    monkeypatch.setenv("EA_TELEGRAM_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setattr(
        channels,
        "apply_audiobook_voice_audition_action",
        _fail_apply,
    )
    callback_data = channels._telegram_encode_audiobook_voice_callback(
        bot_config={"token": "bot-token", "secret": "callback-secret"},
        action="u",
        token="sample-token-error",
        chat_id="42",
    )

    decision = channels._telegram_callback_turn_decision(
        SimpleNamespace(
            payload={
                "kind": "callback_query",
                "callback_data": callback_data,
                "_bot_config": {
                    "token": "bot-token",
                    "secret": "callback-secret",
                },
            },
            chat_id="42",
            container=object(),
            principal_id="principal-1",
            current_message_id="902",
        )
    )

    assert decision.reply_text == (
        "I could not apply that audiobook voice choice. "
        "Current blocker: audiobook_voice_choice_failed."
    )
    assert "/private/books/Secret.epub" not in decision.reply_text
    assert "private-voice" not in decision.reply_text
    assert "permission_denied" not in decision.reply_text


def test_telegram_audiobook_approval_start_failure_is_sanitized_and_hashed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.api.routes import channels

    secret_error = "permission_denied /private/books/Secret.epub token=private-token"
    jobs_root = tmp_path / "jobs"
    source_path = tmp_path / "Secret.epub"
    source_path.write_bytes(b"staged private epub")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    record = channels.audiobook_access_approval.create_pending_request(
        channel="telegram",
        principal_id="principal-1",
        filename="Secret.epub",
        source_path=source_path,
        sender_ref="telegram:requester",
        chat_id="requester",
        message_id="source-message",
    )
    approval_id = str(record["approval_id"])

    monkeypatch.setattr(
        channels.audiobook_access_approval,
        "decode_telegram_approval_callback",
        lambda **_: {
            "ok": True,
            "approval_id": approval_id,
            "action": "approve",
        },
    )
    monkeypatch.setattr(channels, "_telegram_callback_already_processed", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        channels,
        "_telegram_start_approved_audiobook_request",
        lambda **_: (_ for _ in ()).throw(RuntimeError(secret_error)),
    )

    decision = channels._telegram_callback_turn_decision(
        SimpleNamespace(
            payload={
                "kind": "callback_query",
                "callback_data": "aa|signed-approval",
                "_bot_config": {"token": "bot-token"},
            },
            chat_id="42",
            container=object(),
            principal_id="principal-1",
            current_message_id="903",
        )
    )

    assert decision.reply_text == (
        "Approved, but I could not start that audiobook yet. "
        "Current blocker: approved_audiobook_start_failed."
    )
    assert secret_error not in decision.reply_text
    failed = channels.audiobook_access_approval.load_request(approval_id)
    assert failed["status"] == "failed"
    assert failed["decision_reason"] == "approved_audiobook_start_failed"
    assert failed["decision_diagnostic_sha256"] == hashlib.sha256(
        secret_error.encode("utf-8")
    ).hexdigest()
    start = dict(failed["start"])
    assert start["state"] == "failed"
    assert start["job_id"] == failed["job_id"]
    assert len(str(start["idempotency_key_sha256"])) == 64


def test_telegram_approved_audiobook_starter_returns_created_bound_job(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.api.routes import channels

    jobs_root = tmp_path / "jobs"
    source_path = tmp_path / "approved.epub"
    source_path.write_bytes(b"approved source")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    record = channels.audiobook_access_approval.create_pending_request(
        channel="telegram",
        principal_id="principal-1",
        filename="approved.epub",
        source_path=source_path,
        sender_ref="telegram:requester",
        chat_id="requester",
        message_id="source-message",
    )
    expected_job = {
        "job_id": "approval-audiobook-bound-job",
        "status": "waiting_voice_selection",
        "source": {
            "source_sha256": str(dict(record["source"])["source_sha256"]),
            "intake_idempotency_key_sha256": "a" * 64,
        },
    }
    captured: dict[str, object] = {}

    def _create_job_from_epub(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return expected_job

    monkeypatch.setattr(channels, "create_job_from_epub", _create_job_from_epub)

    result = channels._telegram_start_approved_audiobook_request(
        record=record,
        deterministic_job_id="approval-audiobook-bound-job",
        start_identity_sha256="a" * 64,
    )

    assert result is expected_job
    assert captured["epub_path"] == channels.audiobook_access_approval.source_path(record)
    assert captured["deterministic_job_id"] == "approval-audiobook-bound-job"
    assert captured["intake_idempotency_key_sha256"] == "a" * 64
    assert captured["principal_id"] == "principal-1"
    assert captured["chat_id"] == "requester"
    assert captured["message_id"] == "source-message"


def test_telegram_approval_delivery_cannot_overwrite_concurrent_decision(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_access_approval

    jobs_root = tmp_path / "jobs"
    source_path = tmp_path / "race.epub"
    source_path.write_bytes(b"approval delivery race source")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    record = audiobook_access_approval.create_pending_request(
        channel="telegram",
        principal_id="principal-1",
        filename="race.epub",
        source_path=source_path,
        sender_ref="telegram:requester",
        chat_id="requester",
        message_id="source-message",
    )
    approval_id = str(record["approval_id"])
    original_load = audiobook_access_approval.load_request
    delivery_thread_id: dict[str, int] = {}
    delivery_read = threading.Event()
    release_delivery_write = threading.Event()
    decision_entered = threading.Event()
    decision_finished = threading.Event()

    def _instrumented_load(requested_id: str) -> dict[str, object]:
        loaded = original_load(requested_id)
        if threading.get_ident() == delivery_thread_id.get("value") and not delivery_read.is_set():
            delivery_read.set()
            assert release_delivery_write.wait(timeout=5)
        return loaded

    monkeypatch.setattr(audiobook_access_approval, "load_request", _instrumented_load)

    def _record_delivery() -> dict[str, object]:
        delivery_thread_id["value"] = threading.get_ident()
        return audiobook_access_approval.record_telegram_approval_delivery(
            approval_id=approval_id,
            status="sent",
            approver_chat_id="operator-chat",
            message_id="approval-message",
        )

    def _approve() -> dict[str, object]:
        decision_entered.set()
        try:
            return audiobook_access_approval.update_status(
                approval_id,
                status="approved",
                decided_by="operator-chat",
                expected_statuses=("pending",),
            )
        finally:
            decision_finished.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        delivery_future = executor.submit(_record_delivery)
        assert delivery_read.wait(timeout=5)
        decision_future = executor.submit(_approve)
        assert decision_entered.wait(timeout=5)
        try:
            assert not decision_finished.wait(timeout=0.25)
        finally:
            release_delivery_write.set()
        delivery_future.result(timeout=5)
        decision_future.result(timeout=5)

    persisted = original_load(approval_id)
    assert persisted["status"] == "approved"
    assert dict(persisted["approval_delivery"])["status"] == "sent"


def _started_delivery_bound_approval(
    *,
    approval_service,
    tmp_path: Path,
    channel: str,
    suffix: str,
) -> tuple[str, dict[str, object]]:
    source_path = tmp_path / f"delivery-{suffix}.epub"
    source_path.write_bytes(f"delivery source {suffix}".encode("utf-8"))
    request_kwargs: dict[str, object] = {
        "channel": channel,
        "principal_id": "principal-1",
        "filename": source_path.name,
        "source_path": source_path,
        "sender_ref": f"{channel}:requester",
        "message_id": f"source-{suffix}",
    }
    if channel == "telegram":
        request_kwargs["chat_id"] = "requester"
    else:
        request_kwargs.update(
            phone_number="4368120864006",
            session_ref="session-1",
            chat_ref="chat-ref-1",
        )
    record = approval_service.create_pending_request(**request_kwargs)
    approval_id = str(record["approval_id"])

    def _starter(
        claimed: dict[str, object],
        job_id: str,
        identity: str,
    ) -> dict[str, object]:
        job_dir = approval_service.audiobook_epub_pipeline.audiobook_jobs_root() / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        job: dict[str, object] = {
            "contract_name": "ea.audiobook_job.v1",
            "job_id": job_id,
            "principal_id": "principal-1",
            "status": "waiting_voice_selection",
            "source": {
                "kind": "epub",
                "source_filename": source_path.name,
                "source_sha256": str(dict(claimed["source"])["source_sha256"]),
                "intake_idempotency_key_sha256": identity,
            },
            "metadata": {
                "title": f"Delivery {suffix}",
                "author": "A. Writer",
                "language": "en-US",
                "source_filename": source_path.name,
                "source_sha256": str(dict(claimed["source"])["source_sha256"]),
            },
            "provider": {
                "preferred": "unmixr",
                "external_tts_enabled": True,
                "voice_selection": {
                    "contract_name": "ea.audiobook_voice_selection.v1",
                    "strategy": "ranked",
                    "candidate_count": 3,
                },
            },
            "chapters": [],
            "totals": {"chapter_count": 0},
            "storage": {"job_dir": str(job_dir)},
        }
        (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")
        return job

    started = approval_service.run_approved_start_once(
        approval_id,
        approve_pending=True,
        decided_by="telegram:42",
        starter=_starter,
    )
    if channel == "telegram":
        target_snapshot = dict(
            dict(dict(started["record"])["start"])["immutable_snapshot"]
        )["approved_target"]
        assert target_snapshot["chat_id_sha256"] == hashlib.sha256(
            b"requester"
        ).hexdigest()
        assert target_snapshot["message_id_sha256"] == hashlib.sha256(
            f"source-{suffix}".encode("utf-8")
        ).hexdigest()
    return approval_id, dict(started["job"])


@pytest.mark.parametrize("missing_field", ["chat_id", "message_id"])
def test_telegram_incomplete_approved_target_never_starts_or_delivers(
    monkeypatch,
    tmp_path: Path,
    missing_field: str,
) -> None:
    from app.services import audiobook_access_approval

    jobs_root = tmp_path / "jobs"
    source_path = tmp_path / f"incomplete-telegram-{missing_field}.epub"
    source_path.write_bytes(b"incomplete Telegram target")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    record = audiobook_access_approval.create_pending_request(
        channel="telegram",
        principal_id="principal-1",
        filename=source_path.name,
        source_path=source_path,
        sender_ref="telegram:requester",
        chat_id="requester",
        message_id=f"source-incomplete-{missing_field}",
    )
    telegram = dict(record["telegram"])
    telegram[missing_field] = ""
    record["telegram"] = telegram
    audiobook_access_approval._write_request(record)
    approved = audiobook_access_approval.update_status(
        str(record["approval_id"]),
        status="approved",
        decided_by="telegram:42",
        expected_statuses=("pending",),
    )
    callbacks = {"starter": 0, "deliverer": 0}

    def _must_not_start(*_: object) -> dict[str, object]:
        callbacks["starter"] += 1
        raise AssertionError("incomplete target must not invoke starter")

    with pytest.raises(RuntimeError, match="approval_channel_target_incomplete"):
        audiobook_access_approval.run_approved_start_once(
            str(approved["approval_id"]),
            starter=_must_not_start,
        )
    rejected = audiobook_access_approval.load_request(str(approved["approval_id"]))
    assert rejected["status"] == "approved"
    assert "start" not in rejected

    replay_id, replay_job = _started_delivery_bound_approval(
        approval_service=audiobook_access_approval,
        tmp_path=tmp_path,
        channel="telegram",
        suffix=f"incomplete-replay-{missing_field}",
    )
    replay_record = audiobook_access_approval.load_request(replay_id)
    replay_telegram = dict(replay_record["telegram"])
    replay_telegram[missing_field] = ""
    replay_record["telegram"] = replay_telegram
    audiobook_access_approval._write_request(replay_record)
    with pytest.raises(RuntimeError, match="approval_channel_target_incomplete"):
        audiobook_access_approval.run_approved_start_once(
            replay_id,
            starter=_must_not_start,
        )

    def _must_not_deliver() -> object:
        callbacks["deliverer"] += 1
        raise AssertionError("incomplete target must not invoke deliverer")

    with pytest.raises(RuntimeError, match="approval_channel_target_incomplete"):
        audiobook_access_approval.run_approved_delivery_once(
            replay_id,
            channel="telegram",
            job=replay_job,
            deliverer=_must_not_deliver,
        )
    assert callbacks == {"starter": 0, "deliverer": 0}


def test_telegram_delivery_clean_failure_retries_but_partial_waits_for_reconciliation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.api.routes import channels

    jobs_root = tmp_path / "jobs"
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    approval_id, job = _started_delivery_bound_approval(
        approval_service=channels.audiobook_access_approval,
        tmp_path=tmp_path,
        channel="telegram",
        suffix="telegram-clean",
    )
    record = channels.audiobook_access_approval.load_request(approval_id)
    message_receipts = [
        {"ok": False},
        {"ok": True, "result": {"message_id": 1}},
    ]
    monkeypatch.setattr(channels, "_telegram_send_audiobook_voice_samples", lambda **_: [])
    monkeypatch.setattr(
        channels,
        "_telegram_audiobook_playback_acceptance_buttons",
        lambda **kwargs: (dict(kwargs["job"]), []),
    )
    monkeypatch.setattr(
        channels,
        "_telegram_send_message",
        lambda **_: message_receipts.pop(0),
    )

    first = channels.audiobook_access_approval.run_approved_delivery_once(
        approval_id,
        channel="telegram",
        job=job,
        deliverer=lambda: channels._telegram_deliver_started_audiobook_request(
            bot_config={"token": "bot-token"},
            record=record,
            job=job,
        ),
    )
    second = channels.audiobook_access_approval.run_approved_delivery_once(
        approval_id,
        channel="telegram",
        job=job,
        deliverer=lambda: channels._telegram_deliver_started_audiobook_request(
            bot_config={"token": "bot-token"},
            record=record,
            job=job,
        ),
    )

    assert first["delivery_status"] == "failed_before_effect"
    assert second["delivery_status"] == "completed"
    assert dict(second["record"]["first_delivery"])["attempt_count"] == 2
    assert message_receipts == []

    partial_id, partial_job = _started_delivery_bound_approval(
        approval_service=channels.audiobook_access_approval,
        tmp_path=tmp_path,
        channel="telegram",
        suffix="telegram-partial",
    )
    partial_record = channels.audiobook_access_approval.load_request(partial_id)
    sends = {"count": 0}
    monkeypatch.setattr(
        channels,
        "_telegram_send_audiobook_voice_samples",
        lambda **_: [
            {
                "status": "sent",
                "effect_state": "confirmed",
                "media_message_id_sha256": "1" * 64,
                "token": "sample-1",
            }
        ],
    )
    monkeypatch.setattr(
        channels,
        "record_audiobook_voice_sample_delivery",
        lambda *, job, sample_receipts: dict(job),
    )

    def _known_failed_message(**_: object) -> dict[str, object]:
        sends["count"] += 1
        return {"ok": False}

    monkeypatch.setattr(channels, "_telegram_send_message", _known_failed_message)
    partial = channels.audiobook_access_approval.run_approved_delivery_once(
        partial_id,
        channel="telegram",
        job=partial_job,
        deliverer=lambda: channels._telegram_deliver_started_audiobook_request(
            bot_config={"token": "bot-token"},
            record=partial_record,
            job=partial_job,
        ),
    )
    replay = channels.audiobook_access_approval.run_approved_delivery_once(
        partial_id,
        channel="telegram",
        job=partial_job,
        deliverer=lambda: (_ for _ in ()).throw(
            AssertionError("partial Telegram delivery must not resend")
        ),
    )

    assert partial["delivery_status"] == "outcome_unknown"
    assert replay["delivery_now"] is False
    assert replay["delivery_status"] == "outcome_unknown"
    assert sends["count"] == 1


def test_delivery_reconciliation_is_authorized_and_never_automatically_resends(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_access_approval

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv(
        "EA_AUDIOBOOK_DELIVERY_RECONCILIATION_SECRET",
        "operator-reconciliation-secret",
    )

    def _unknown_delivery(approval_id: str, job: dict[str, object]) -> dict[str, object]:
        return audiobook_access_approval.run_approved_delivery_once(
            approval_id,
            channel="telegram",
            job=job,
            deliverer=lambda: audiobook_access_approval.build_approved_delivery_outcome(
                channel="telegram",
                result=job,
                expected_effect_count=2,
                confirmed_effect_count=1,
                known_no_effect_count=1,
                ambiguous_effect_count=0,
            ),
        )

    completed_id, completed_job = _started_delivery_bound_approval(
        approval_service=audiobook_access_approval,
        tmp_path=tmp_path,
        channel="telegram",
        suffix="reconcile-completed",
    )
    unknown = _unknown_delivery(completed_id, completed_job)
    with pytest.raises(
        RuntimeError,
        match="approval_delivery_reconciliation_unauthorized",
    ):
        audiobook_access_approval.reconcile_approved_delivery(
            completed_id,
            action="verified_completed",
            binding_sha256=str(unknown["binding_sha256"]),
            reconciled_by="operator:42",
            authorization="wrong-secret",
        )
    with pytest.raises(
        RuntimeError,
        match="approval_delivery_reconciliation_binding_mismatch",
    ):
        audiobook_access_approval.reconcile_approved_delivery(
            completed_id,
            action="verified_completed",
            binding_sha256="0" * 64,
            reconciled_by="operator:42",
            authorization="operator-reconciliation-secret",
        )
    reconciled = audiobook_access_approval.reconcile_approved_delivery(
        completed_id,
        action="verified_completed",
        binding_sha256=str(unknown["binding_sha256"]),
        reconciled_by="operator:42",
        authorization="operator-reconciliation-secret",
    )
    replay = audiobook_access_approval.run_approved_delivery_once(
        completed_id,
        channel="telegram",
        job=completed_job,
        deliverer=lambda: (_ for _ in ()).throw(
            AssertionError("verified completed delivery must not resend")
        ),
    )
    assert reconciled["delivery_status"] == "completed"
    assert replay["delivery_now"] is False
    assert replay["delivery_status"] == "completed"

    retry_id, retry_job = _started_delivery_bound_approval(
        approval_service=audiobook_access_approval,
        tmp_path=tmp_path,
        channel="telegram",
        suffix="reconcile-retry",
    )
    retry_unknown = _unknown_delivery(retry_id, retry_job)
    audiobook_access_approval.reconcile_approved_delivery(
        retry_id,
        action="verified_no_effect_retry",
        binding_sha256=str(retry_unknown["binding_sha256"]),
        reconciled_by="operator:42",
        authorization="operator-reconciliation-secret",
    )
    sends = {"count": 0}

    def _verified_retry() -> dict[str, object]:
        sends["count"] += 1
        return audiobook_access_approval.build_approved_delivery_outcome(
            channel="telegram",
            result=retry_job,
            expected_effect_count=1,
            confirmed_effect_count=1,
            known_no_effect_count=0,
            ambiguous_effect_count=0,
        )

    retried = audiobook_access_approval.run_approved_delivery_once(
        retry_id,
        channel="telegram",
        job=retry_job,
        deliverer=_verified_retry,
    )
    assert retried["delivery_status"] == "completed"
    assert sends["count"] == 1
    retained_reconciliation = dict(
        dict(retried["record"]["first_delivery"])["reconciliation"]
    )
    assert retained_reconciliation["contract_name"] == (
        audiobook_access_approval.DELIVERY_RECONCILIATION_CONTRACT_NAME
    )
    assert retained_reconciliation["action"] == "verified_no_effect_retry"


def test_delivery_rejects_tampered_immutable_job_fields_before_send(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_access_approval

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    approval_id, job = _started_delivery_bound_approval(
        approval_service=audiobook_access_approval,
        tmp_path=tmp_path,
        channel="telegram",
        suffix="tamper",
    )
    tampered = json.loads(json.dumps(job))
    tampered["metadata"]["title"] = "Tampered title"
    sends = {"count": 0}

    with pytest.raises(
        RuntimeError,
        match="approval_delivery_immutable_snapshot_mismatch",
    ):
        audiobook_access_approval.run_approved_delivery_once(
            approval_id,
            channel="telegram",
            job=tampered,
            deliverer=lambda: sends.__setitem__("count", sends["count"] + 1),
        )

    assert sends["count"] == 0
    assert "first_delivery" not in audiobook_access_approval.load_request(approval_id)


def test_telegram_audiobook_approval_start_is_atomic_and_replay_safe(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.api.routes import channels

    jobs_root = tmp_path / "jobs"
    source_path = tmp_path / "book.epub"
    source_path.write_bytes(b"telegram approval source")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    record = channels.audiobook_access_approval.create_pending_request(
        channel="telegram",
        principal_id="principal-1",
        filename="book.epub",
        source_path=source_path,
        sender_ref="telegram:requester",
        chat_id="requester",
        message_id="source-message",
    )
    approval_id = str(record["approval_id"])
    monkeypatch.setattr(
        channels.audiobook_access_approval,
        "decode_telegram_approval_callback",
        lambda **_: {"ok": True, "approval_id": approval_id, "action": "approve"},
    )
    monkeypatch.setattr(channels, "_telegram_callback_already_processed", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(channels, "_record_telegram_callback_processed", lambda *_args, **_kwargs: None)

    start_entered = threading.Event()
    release_start = threading.Event()
    counters = {"starts": 0, "deliveries": 0}
    counter_lock = threading.Lock()

    def _start_once(
        *,
        record: dict[str, object],
        deterministic_job_id: str,
        start_identity_sha256: str,
    ) -> dict[str, object]:
        with counter_lock:
            counters["starts"] += 1
        start_entered.set()
        assert release_start.wait(timeout=5)
        job_dir = jobs_root / deterministic_job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        job = {
            "job_id": deterministic_job_id,
            "status": "waiting_voice_selection",
            "source": {
                "intake_idempotency_key_sha256": start_identity_sha256,
                "source_sha256": str(dict(record["source"])["source_sha256"]),
            },
            "storage": {"job_dir": str(job_dir)},
            "metadata": {"title": "Atomic Book"},
        }
        (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")
        return job

    def _deliver_once(**kwargs: object) -> dict[str, object]:
        with counter_lock:
            counters["deliveries"] += 1
        return channels.audiobook_access_approval.build_approved_delivery_outcome(
            channel="telegram",
            result=dict(kwargs["job"]),
            expected_effect_count=1,
            confirmed_effect_count=1,
            known_no_effect_count=0,
            ambiguous_effect_count=0,
        )

    monkeypatch.setattr(channels, "_telegram_start_approved_audiobook_request", _start_once)
    monkeypatch.setattr(channels, "_telegram_deliver_started_audiobook_request", _deliver_once)

    def _callback(message_id: str):
        return channels._telegram_callback_turn_decision(
            SimpleNamespace(
                payload={
                    "kind": "callback_query",
                    "callback_data": "aa|signed-approval",
                    "_bot_config": {"token": "bot-token"},
                },
                chat_id="42",
                container=object(),
                principal_id="principal-1",
                current_message_id=message_id,
            )
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(_callback, "903")
        assert start_entered.wait(timeout=5)
        second = executor.submit(_callback, "904")
        release_start.set()
        decisions = [first.result(timeout=5), second.result(timeout=5)]

    assert counters == {"starts": 1, "deliveries": 1}
    replies = {str(decision.reply_text) for decision in decisions}
    assert any("Approved and started" in reply for reply in replies)
    assert any(
        "reused the existing job" in reply or "Recovered the missing first delivery" in reply
        for reply in replies
    )
    persisted = channels.audiobook_access_approval.load_request(approval_id)
    assert persisted["status"] == "started"
    assert dict(persisted["start"])["attempt_count"] == 1
    delivery = dict(persisted["first_delivery"])
    assert delivery["contract_name"] == channels.audiobook_access_approval.DELIVERY_CONTRACT_NAME
    assert delivery["state"] == "completed"
    assert delivery["channel"] == "telegram"
    assert delivery["attempt_count"] == 1
    assert len(str(delivery["binding_sha256"])) == 64
    serialized_delivery = json.dumps(delivery, sort_keys=True)
    assert str(source_path) not in serialized_delivery
    assert "bot-token" not in serialized_delivery
    assert str(persisted["job_id"]) not in serialized_delivery
    with pytest.raises(RuntimeError, match="approval_status_conflict"):
        channels.audiobook_access_approval.update_status(
            approval_id,
            status="denied",
            expected_statuses=("pending",),
        )


def test_telegram_replay_recovers_crash_after_start_before_first_delivery(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.api.routes import channels

    jobs_root = tmp_path / "jobs"
    source_path = tmp_path / "delivery-gap.epub"
    source_path.write_bytes(b"telegram delivery gap source")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    record = channels.audiobook_access_approval.create_pending_request(
        channel="telegram",
        principal_id="principal-1",
        filename="delivery-gap.epub",
        source_path=source_path,
        sender_ref="telegram:requester",
        chat_id="requester",
        message_id="source-message",
    )
    approval_id = str(record["approval_id"])
    starts = {"count": 0}

    def _starter(
        claimed: dict[str, object],
        job_id: str,
        identity: str,
    ) -> dict[str, object]:
        starts["count"] += 1
        job_dir = jobs_root / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        job = {
            "job_id": job_id,
            "status": "waiting_voice_selection",
            "source": {
                "intake_idempotency_key_sha256": identity,
                "source_sha256": str(dict(claimed["source"])["source_sha256"]),
            },
            "storage": {"job_dir": str(job_dir)},
            "metadata": {"title": "Delivery Gap Book"},
        }
        (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")
        return job

    # The first worker commits the canonical job and then dies before entering
    # the first-delivery boundary.
    started = channels.audiobook_access_approval.run_approved_start_once(
        approval_id,
        approve_pending=True,
        decided_by="telegram:42",
        starter=_starter,
    )
    assert started["started_now"] is True
    assert "first_delivery" not in channels.audiobook_access_approval.load_request(approval_id)

    monkeypatch.setattr(
        channels.audiobook_access_approval,
        "decode_telegram_approval_callback",
        lambda **_: {"ok": True, "approval_id": approval_id, "action": "approve"},
    )
    monkeypatch.setattr(channels, "_telegram_callback_already_processed", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(channels, "_record_telegram_callback_processed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        channels,
        "_telegram_start_approved_audiobook_request",
        lambda **_: (_ for _ in ()).throw(
            AssertionError("delivery recovery must not call the paid starter")
        ),
    )
    deliveries = {"count": 0}

    def _deliver(**kwargs: object) -> dict[str, object]:
        deliveries["count"] += 1
        return channels.audiobook_access_approval.build_approved_delivery_outcome(
            channel="telegram",
            result=dict(kwargs["job"]),
            expected_effect_count=1,
            confirmed_effect_count=1,
            known_no_effect_count=0,
            ambiguous_effect_count=0,
        )

    monkeypatch.setattr(channels, "_telegram_deliver_started_audiobook_request", _deliver)
    ctx = SimpleNamespace(
        payload={
            "kind": "callback_query",
            "callback_data": "aa|signed-approval",
            "_bot_config": {"token": "bot-token"},
        },
        chat_id="42",
        container=object(),
        principal_id="principal-1",
        current_message_id="delivery-gap-callback",
    )

    recovered = channels._telegram_callback_turn_decision(ctx)
    replayed = channels._telegram_callback_turn_decision(ctx)

    assert "Recovered the missing first delivery" in recovered.reply_text
    assert "reused the existing job" in replayed.reply_text
    assert starts["count"] == 1
    assert deliveries["count"] == 1
    persisted = channels.audiobook_access_approval.load_request(approval_id)
    assert dict(persisted["first_delivery"])["state"] == "completed"


def test_telegram_audiobook_approval_crash_recovers_bound_job_without_paid_replay(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.api.routes import channels

    jobs_root = tmp_path / "jobs"
    source_path = tmp_path / "crash-book.epub"
    source_path.write_bytes(b"telegram crash recovery source")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    record = channels.audiobook_access_approval.create_pending_request(
        channel="telegram",
        principal_id="principal-1",
        filename="crash-book.epub",
        source_path=source_path,
        sender_ref="telegram:requester",
        chat_id="requester",
        message_id="source-message",
    )
    approval_id = str(record["approval_id"])
    monkeypatch.setattr(
        channels.audiobook_access_approval,
        "decode_telegram_approval_callback",
        lambda **_: {"ok": True, "approval_id": approval_id, "action": "approve"},
    )
    monkeypatch.setattr(channels, "_telegram_callback_already_processed", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(channels, "_record_telegram_callback_processed", lambda *_args, **_kwargs: None)
    counters = {"paid_starts": 0, "deliveries": 0}

    def _crashing_start(
        *,
        record: dict[str, object],
        deterministic_job_id: str,
        start_identity_sha256: str,
    ) -> dict[str, object]:
        job_dir = jobs_root / deterministic_job_id
        manifest_path = job_dir / "job.json"
        if manifest_path.is_file():
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        counters["paid_starts"] += 1
        job_dir.mkdir(parents=True, exist_ok=True)
        job = {
            "job_id": deterministic_job_id,
            "status": "waiting_voice_selection",
            "source": {
                "intake_idempotency_key_sha256": start_identity_sha256,
                "source_sha256": str(dict(record["source"])["source_sha256"]),
            },
            "storage": {"job_dir": str(job_dir)},
            "metadata": {"title": "Crash Book"},
        }
        manifest_path.write_text(json.dumps(job), encoding="utf-8")
        raise KeyboardInterrupt("simulated worker crash after paid start")

    def _delivery(**kwargs: object) -> dict[str, object]:
        counters["deliveries"] += 1
        return channels.audiobook_access_approval.build_approved_delivery_outcome(
            channel="telegram",
            result=dict(kwargs["job"]),
            expected_effect_count=1,
            confirmed_effect_count=1,
            known_no_effect_count=0,
            ambiguous_effect_count=0,
        )

    monkeypatch.setattr(channels, "_telegram_start_approved_audiobook_request", _crashing_start)
    monkeypatch.setattr(channels, "_telegram_deliver_started_audiobook_request", _delivery)
    ctx = SimpleNamespace(
        payload={
            "kind": "callback_query",
            "callback_data": "aa|signed-approval",
            "_bot_config": {"token": "bot-token"},
        },
        chat_id="42",
        container=object(),
        principal_id="principal-1",
        current_message_id="905",
    )

    with pytest.raises(KeyboardInterrupt, match="simulated worker crash"):
        channels._telegram_callback_turn_decision(ctx)
    crashed = channels.audiobook_access_approval.load_request(approval_id)
    assert crashed["status"] == "starting"

    recovered = channels._telegram_callback_turn_decision(ctx)

    assert "Approved and started" in recovered.reply_text
    assert counters == {"paid_starts": 1, "deliveries": 1}
    persisted = channels.audiobook_access_approval.load_request(approval_id)
    assert persisted["status"] == "started"
    assert dict(persisted["start"])["attempt_count"] == 2
    assert dict(persisted["start"])["recovery_attempt"] is True


def test_epub_deterministic_intake_returns_bound_manifest_before_provider_replay(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    jobs_root = tmp_path / "jobs"
    source_path = tmp_path / "deterministic.epub"
    _write_minimal_epub(source_path, title="Deterministic Intake")
    identity = hashlib.sha256(b"approval-start-identity").hexdigest()
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "0")

    first = pipeline.create_job_from_epub(
        epub_path=source_path,
        original_filename="deterministic.epub",
        principal_id="principal-1",
        deterministic_job_id="approval-audiobook-deterministic",
        intake_idempotency_key_sha256=identity,
    )
    monkeypatch.setattr(
        pipeline,
        "extract_epub_chapters",
        lambda **_: (_ for _ in ()).throw(
            AssertionError("idempotent replay must not repeat extraction/provider planning")
        ),
    )

    replay = pipeline.create_job_from_epub(
        epub_path=source_path,
        original_filename="deterministic.epub",
        principal_id="principal-1",
        deterministic_job_id="approval-audiobook-deterministic",
        intake_idempotency_key_sha256=identity,
    )

    assert replay == first
    assert replay["job_id"] == "approval-audiobook-deterministic"
    assert dict(replay["source"])["intake_idempotency_key_sha256"] == identity


def test_telegram_direct_audiobook_job_failure_is_sanitized_and_hashed(
    monkeypatch,
) -> None:
    from app.api.routes import channels

    secret_error = "permission_denied /private/books/Secret.epub token=private-token"
    observations: list[dict[str, object]] = []
    replies: list[dict[str, object]] = []
    container = SimpleNamespace(
        channel_runtime=SimpleNamespace(
            ingest_observation=lambda **kwargs: observations.append(dict(kwargs))
        )
    )
    monkeypatch.setattr(
        channels,
        "_telegram_hydrate_audiobook_epub_download_url",
        lambda payload, **_: dict(payload),
    )
    monkeypatch.setattr(
        channels,
        "process_telegram_epub_audiobook_job",
        lambda **_: (_ for _ in ()).throw(RuntimeError(secret_error)),
    )
    monkeypatch.setattr(
        channels,
        "_telegram_send_and_record_reply",
        lambda **kwargs: replies.append(dict(kwargs)),
    )

    channels._telegram_async_assistant_reply_worker(
        container=container,
        principal_id="principal-1",
        bot_config={"token": "bot-token"},
        chat_id="42",
        text="Create my audiobook",
        current_message_id="904",
        async_payload={
            "kind": "audiobook_epub_document",
            "source_epub_url": "https://api.telegram.org/file/book.epub",
            "source_epub_filename": "book.epub",
        },
    )

    failure = next(
        row
        for row in observations
        if row.get("event_type") == "telegram.reply_async_failed"
    )
    failure_payload = dict(failure["payload"])
    assert failure_payload["error"] == "audiobook_epub_job_failed"
    assert failure_payload["diagnostic_sha256"] == hashlib.sha256(
        secret_error.encode("utf-8")
    ).hexdigest()
    assert replies[-1]["reply_text"] == (
        "I could not prepare the audiobook source job yet. "
        "Current blocker: audiobook_epub_job_failed."
    )
    rendered = json.dumps(
        {"failure": failure_payload, "reply": replies[-1]},
        sort_keys=True,
        default=str,
    )
    assert secret_error not in rendered
    assert "/private/books/Secret.epub" not in rendered
    assert "private-token" not in rendered


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


def test_resume_due_audiobook_jobs_only_treats_listened_canary_as_completed_terminal(monkeypatch, tmp_path: Path) -> None:
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
                "next_action": "playback_listened_canary_accepted",
                "audiobookshelf_import": {
                    "status": "imported",
                    "public_share": {
                        "status": "public_share_ready",
                        "absolute_url": "https://abs.example.com/share/accepted-book",
                        "telegram_followup_pending": False,
                        "whatsapp_followup_pending": False,
                    },
                },
                "playback_acceptance": {
                    "status": "listened_canary_accepted",
                    "accepted": True,
                    "listened": True,
                    "canary_binding_status": "complete",
                },
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


@pytest.mark.parametrize("playback_status", ["listened_canary_accepted"])
def test_audiobook_completed_terminal_reason_includes_listened_canary_acceptance(
    playback_status: str,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    job = {
        "status": "audiobookshelf_imported",
        "audiobookshelf_import": {
            "public_share": {
                "status": "public_share_ready",
                "telegram_followup_pending": False,
                "whatsapp_followup_pending": False,
            }
        },
        "playback_acceptance": {"status": playback_status, "accepted": True},
    }

    assert pipeline._audiobook_completed_terminal_reason(job) == "playback_accepted"


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
    monkeypatch.setenv("EA_AUDIOBOOK_CINEMATIC_NARRATION", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_PARAGRAPH_PAUSES_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_BATCH_PARAGRAPHS_WITH_NATURAL_PAUSES", "0")
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
    chapter = EpubChapter(index=1, title="Test", source_href="test.xhtml", text_path="001 - Test.txt", audio_filename="001 - Test.wav", char_count=len(text), sha256=pipeline._sha256_bytes(text.encode("utf-8")))
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


def test_unmixr_render_uses_longer_silence_for_scene_breaks(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import EpubChapter, EpubMetadata, render_unmixr_chapter_audio

    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_CINEMATIC_NARRATION", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_PARAGRAPH_PAUSES_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_BATCH_PARAGRAPHS_WITH_NATURAL_PAUSES", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_PARAGRAPH_PAUSE_SECONDS", "0.35")
    monkeypatch.setenv("EA_AUDIOBOOK_SCENE_PAUSE_SECONDS", "1.2")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_MAX_CHARS_PER_REQUEST", "1000")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps([{"voice_id": "voice-1", "label": "Narrator", "language": "en-US", "tags": ["audiobook", "narration"], "default": True}]),
    )
    chapter_dir = tmp_path / "chapters"
    chapter_dir.mkdir()
    text = "Opening paragraph.\n\nFollowing paragraph.\n\n\nNew scene."
    (chapter_dir / "001 - Test.txt").write_text(text, encoding="utf-8")
    chapter = EpubChapter(index=1, title="Test", source_href="test.xhtml", text_path="001 - Test.txt", audio_filename="001 - Test.wav", char_count=len(text), sha256=pipeline._sha256_bytes(text.encode("utf-8")))
    metadata = EpubMetadata(title="Test Book", author="A. Writer", language="en-US", source_filename="book.epub", source_sha256="sha")
    tone = tmp_path / "tone.wav"
    _write_tone_wav(tone)
    pause_durations: list[float] = []

    def fake_synthesize_request(**kwargs):
        return tone.read_bytes(), "audio/wav"

    def fake_write_silence(path, *, seconds, sample_rate=44100):
        pause_durations.append(float(seconds))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(tone.read_bytes())
        return path

    def fake_merge_segments(*, segment_paths, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(Path(segment_paths[0]).read_bytes())
        return True

    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", fake_synthesize_request)
    monkeypatch.setattr(pipeline, "_write_silence_wav", fake_write_silence)
    monkeypatch.setattr(pipeline, "_merge_audio_segments_to_wav", fake_merge_segments)

    result = render_unmixr_chapter_audio(job_dir=tmp_path, chapters=(chapter,), metadata=metadata)

    assert result["status"] == "rendered"
    assert pause_durations == [0.35, 1.2]
    assert result["chapters"][0]["paragraph_pause_count"] == 1
    assert result["chapters"][0]["scene_pause_count"] == 1
    assert result["chapters"][0]["total_pause_count"] == 2
    assert result["chapters"][0]["scene_pause_seconds"] == 1.2


def test_unmixr_render_can_batch_paragraphs_while_retaining_scene_silence(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import EpubChapter, EpubMetadata, render_unmixr_chapter_audio

    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_CINEMATIC_NARRATION", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_PARAGRAPH_PAUSES_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_BATCH_PARAGRAPHS_WITH_NATURAL_PAUSES", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_SCENE_PAUSE_SECONDS", "1.2")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_MAX_CHARS_PER_REQUEST", "1000")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps([{"voice_id": "voice-1", "label": "Narrator", "language": "en-US", "tags": ["audiobook", "narration"], "default": True}]),
    )
    chapter_dir = tmp_path / "chapters"
    chapter_dir.mkdir()
    text = "Opening paragraph.\n\nFollowing paragraph.\n\n\nNew scene."
    (chapter_dir / "001 - Test.txt").write_text(text, encoding="utf-8")
    chapter = EpubChapter(index=1, title="Test", source_href="test.xhtml", text_path="001 - Test.txt", audio_filename="001 - Test.wav", char_count=len(text), sha256=pipeline._sha256_bytes(text.encode("utf-8")))
    metadata = EpubMetadata(title="Test Book", author="A. Writer", language="en-US", source_filename="book.epub", source_sha256="sha")
    tone = tmp_path / "tone.wav"
    _write_tone_wav(tone)
    tts_texts: list[str] = []
    pause_durations: list[float] = []

    def fake_synthesize_request(**kwargs):
        tts_texts.append(str(kwargs["text"]))
        return tone.read_bytes(), "audio/wav"

    def fake_write_silence(path, *, seconds, sample_rate=44100):
        pause_durations.append(float(seconds))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(tone.read_bytes())
        return path

    def fake_merge_segments(*, segment_paths, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(Path(segment_paths[0]).read_bytes())
        return True

    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", fake_synthesize_request)
    monkeypatch.setattr(pipeline, "_write_silence_wav", fake_write_silence)
    monkeypatch.setattr(pipeline, "_merge_audio_segments_to_wav", fake_merge_segments)

    result = render_unmixr_chapter_audio(job_dir=tmp_path, chapters=(chapter,), metadata=metadata)

    assert result["status"] == "rendered"
    assert tts_texts == ["Opening paragraph.\n\nFollowing paragraph.", "New scene."]
    assert pause_durations == [1.2]
    assert result["chapters"][0]["segment_count"] == 2
    assert result["chapters"][0]["paragraph_pause_count"] == 0
    assert result["chapters"][0]["scene_pause_count"] == 1
    assert result["chapters"][0]["total_pause_count"] == 1


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


def test_telegram_epub_turn_decision_routes_top_level_document_metadata(monkeypatch) -> None:
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
            "file_id": "file-1",
            "file_name": "book.epub",
            "mime_type": "application/epub+zip",
            "file_size": 2048,
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
    assert decision.async_payload["telegram_file_id"] == "file-1"


def test_telegram_epub_turn_decision_routes_raw_document_metadata(monkeypatch) -> None:
    from app.api.routes import channels
    from app.services.telegram_session_service import TelegramTurnContext

    monkeypatch.setenv("EA_AUDIOBOOK_INSTANT_SENDER_WHITELIST", "telegram:42")
    ctx = TelegramTurnContext(
        container=object(),
        principal_id="principal-1",
        text="Document",
        payload={
            "kind": "document",
            "message_id": "7",
            "message_metadata": {"file_id": "file-1"},
            "raw": {
                "message": {
                    "caption": "audiobook plz",
                    "document": {
                        "file_name": "book.epub",
                        "mime_type": "application/octet-stream",
                        "file_size": 2048,
                    },
                },
            },
        },
        bot_handle="",
        preferred_onemin_labels=(),
        current_message_id="7",
        chat_id="42",
        normalized="Document",
        lower="document",
        alpha_words=("document",),
        is_completion_cue=False,
    )

    decision = channels._telegram_audiobook_epub_turn_decision(ctx)

    assert decision.schedule_async is True
    assert decision.suppress_async_ack is True
    assert decision.reply_text == ""
    assert decision.async_payload["kind"] == "audiobook_epub_document"
    assert decision.async_payload["source_epub_filename"] == "book.epub"
    assert decision.async_payload["caption"] == "audiobook plz"


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


def test_telegram_epub_turn_decision_trusts_registered_telegram_principal(monkeypatch) -> None:
    from app.api.routes import channels
    from app.services.telegram_session_service import TelegramTurnContext

    monkeypatch.delenv("EA_AUDIOBOOK_INSTANT_SENDER_WHITELIST", raising=False)
    monkeypatch.delenv("EA_AUDIOBOOK_INSTANT_PHONE_WHITELIST", raising=False)
    container = SimpleNamespace(
        tool_runtime=SimpleNamespace(list_connector_bindings_for_connector=lambda *_args, **_kwargs: []),
        onboarding=SimpleNamespace(status=lambda **_kwargs: {"status": "active"}),
    )
    ctx = TelegramTurnContext(
        container=container,
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
        "audio_publication_gate": {"status": "pass", "issues": []},
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

    assert "Latest Audiobookshelf delivery awaiting perceptual attestation: Ready Book" in decision.reply_text
    assert "Tapping attests every check" in decision.reply_text
    assert decision.inline_buttons
    labels = [label for row in decision.inline_buttons for label, _callback in row]
    callbacks = [callback for row in decision.inline_buttons for _label, callback in row]
    assert "Attest all 7 checks pass" in labels
    assert "Problem" in labels
    refreshed = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    current_token = str(
        refreshed["audiobookshelf_import"]["public_share"][
            "playback_acceptance_callback"
        ]["token"]
    )
    refreshed_callback = refreshed["audiobookshelf_import"]["public_share"][
        "playback_acceptance_callback"
    ]
    assert current_token != "callback-token"
    assert refreshed_callback["contract_name"] == (
        "ea.audiobook_playback_attestation_callback.v2"
    )
    assert refreshed_callback["perceptual_attestation_version"] == 1
    assert refreshed_callback["rotated_for_current_artifact"] is True
    assert any(callback.startswith(f"ap2|a|{current_token}|") for callback in callbacks)
    assert any(callback.startswith(f"ap2|r|{current_token}|") for callback in callbacks)


@pytest.mark.parametrize("playback_status", ["accepted", "listened_canary_accepted"])
def test_telegram_audiobook_status_does_not_resend_terminal_playback_buttons(
    monkeypatch,
    tmp_path: Path,
    playback_status: str,
) -> None:
    from app.api.routes import channels

    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-terminal"
    job_dir.mkdir(parents=True)
    (job_dir / "job.json").write_text(
        json.dumps(
            {
                "job_id": "job-terminal",
                "status": "audiobookshelf_imported",
                "updated_at": "2026-07-19T06:00:00Z",
                "metadata": {"title": "Terminal Book"},
                "telegram": {"chat_id": "42"},
                "audiobookshelf_import": {
                    "public_share": {
                        "status": "public_share_ready",
                        "telegram_delivery": {"status": "sent"},
                    }
                },
                "playback_acceptance": {
                    "status": playback_status,
                    "accepted": True,
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))

    title, buttons = channels._telegram_latest_audiobook_playback_buttons_for_chat(
        bot_config={"token": "telegram-token"},
        chat_id="42",
    )

    assert title == ""
    assert buttons == []


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
    monkeypatch.setenv("EA_AUDIOBOOK_JOB_DISCOVERY_ROOTS", str(tmp_path))
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


def test_audiobook_job_receipt_whitelists_voice_and_narration_plan_metadata(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services.audiobook_epub_pipeline import (
        _sha256_bytes,
        build_audiobook_job_receipt,
    )

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path))
    job_dir = tmp_path / "private-receipt-boundary"
    job_dir.mkdir()
    narrator_hash = "a" * 64
    dialogue_hash = "b" * 64
    plan_hash = "c" * 64
    job = {
        "job_id": "private-receipt-boundary",
        "status": "audio_ready",
        "metadata": {"title": "Memorial", "author": "Family", "language": "de"},
        "provider": {
            "voice_selection": {
                "callback_token": "narrator-callback-private-secret",
                "selected_callback_token": "narrator-selected-token-private-secret",
                "voice_id": "narrator-raw-id-private-secret",
                "sample_file": "narrator-private-sample.wav",
                "sample_path": "/private/voice/narrator-private-sample.wav",
                "sample_sha256": "d" * 64,
            },
            "dialogue_voice_selection": {
                "status": "approved",
                "source": "approved_private_dialogue_voice_selection",
                "enabled": True,
                "approved_by_user": True,
                "voice_id_sha256": dialogue_hash,
                "selected_callback_token": "dialogue-provider-token-private-secret",
                "voice_id": "dialogue-provider-raw-id-private-secret",
            },
        },
        "render_result": {
            "status": "rendered",
            "provider": "unmixr",
            "voice_selection": {
                "status": "selected_by_user",
                "source": "voice_audition",
                "selected_voice_id_sha256": narrator_hash,
                "strategy": "narrator-callback-private-secret",
                "selected_candidate": {
                    "voice_id": "nested-narrator-raw-id-private-secret",
                    "callback_token": "nested-narrator-token-private-secret",
                    "sample_path": "/private/voice/nested-narrator.wav",
                },
                "candidate": {
                    "preset_key": "warm_narrator",
                    "label": "Warm narrator",
                    "language": "de",
                    "voice_id_sha256": narrator_hash,
                },
            },
            "dialogue_voice_selection": {
                "selected_callback_token": "dialogue-render-token-private-secret",
                "voice_id": "dialogue-render-raw-id-private-secret",
                "sample_path": "/private/voice/dialogue-private-sample.wav",
            },
            "narration_plan": {
                "path": "/private/plans/narration-plan.private.json",
                "private_path": "/private/plans/narration-plan.private.json",
                "raw_text_exposed": True,
                "raw_voice_ids_exposed": True,
                "passages": [
                    {
                        "text": "PRIVATE MANFRED PASSAGE TEXT",
                        "voice_id": "narration-plan-raw-id-private-secret",
                    }
                ],
            },
            "pacing": {
                "scene_pause_count": 1,
                "total_pause_seconds": 2.5,
                "private_note": "PRIVATE PACING PASSAGE TEXT",
                "voice": {"voice_id": "pacing-raw-id-private-secret"},
            },
        },
        "narration_plan": {
            "contract_name": "ea.audiobook_narration_plan.v1",
            "status": "ready",
            "chapter_count": 1,
            "passage_count": 2,
            "coverage_complete": True,
            "source_integrity_verified": True,
            "private_plan_present": True,
            "plan_sha256": plan_hash,
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")

    receipt = build_audiobook_job_receipt(job_dir=job_dir)
    rendered = json.dumps(receipt, sort_keys=True)

    assert receipt["render"]["voice_selection"] == {
        "status": "selected_by_user",
        "source": "voice_audition",
        "selected_voice_id_sha256": narrator_hash,
        "selected_candidate": {
            "preset_key_sha256": _sha256_bytes(b"warm_narrator"),
            "label": "Warm narrator",
            "language": "de",
            "voice_id_sha256": narrator_hash,
        },
    }
    assert receipt["render"]["dialogue_voice_selection"] == {
        "status": "approved",
        "source": "approved_private_dialogue_voice_selection",
        "approved_by_user": True,
        "voice_id_sha256": dialogue_hash,
        "enabled": True,
    }
    assert receipt["render"]["narration_plan"] == {
        "contract_name": "ea.audiobook_narration_plan.v1",
        "status": "ready",
        "chapter_count": 1,
        "passage_count": 2,
        "coverage_complete": True,
        "source_integrity_verified": True,
        "private_plan_present": True,
        "plan_sha256": plan_hash,
    }
    assert receipt["render"]["pacing"] == {
        "scene_pause_count": 1,
        "total_pause_seconds": 2.5,
    }
    for secret in (
        "narrator-callback-private-secret",
        "narrator-selected-token-private-secret",
        "narrator-raw-id-private-secret",
        "narrator-private-sample.wav",
        "nested-narrator-raw-id-private-secret",
        "nested-narrator-token-private-secret",
        "nested-narrator.wav",
        "dialogue-provider-token-private-secret",
        "dialogue-provider-raw-id-private-secret",
        "dialogue-render-token-private-secret",
        "dialogue-render-raw-id-private-secret",
        "dialogue-private-sample.wav",
        "narration-plan.private.json",
        "PRIVATE MANFRED PASSAGE TEXT",
        "PRIVATE PACING PASSAGE TEXT",
        "pacing-raw-id-private-secret",
        "narration-plan-raw-id-private-secret",
        "d" * 64,
    ):
        assert secret not in rendered
    assert receipt["privacy"]["dialogue_voice_id_exposed"] is False
    assert receipt["privacy"]["voice_audition_callback_token_exposed"] is False
    assert receipt["privacy"]["voice_sample_path_exposed"] is False
    assert receipt["privacy"]["private_narration_plan_path_exposed"] is False
    assert receipt["privacy"]["private_narration_plan_text_exposed"] is False


def test_audiobook_render_lock_reports_retryable_in_progress(monkeypatch, tmp_path: Path) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    monkeypatch.setenv("EA_AUDIOBOOK_RENDER_LOCK_TIMEOUT_SECONDS", "0.1")
    job_dir = tmp_path / "locked-render"

    with pipeline._exclusive_audiobook_render_lock(job_dir):
        result = pipeline.render_unmixr_chapter_audio(
            job_dir=job_dir,
            chapters=(),
            metadata=None,  # Lock acquisition returns before metadata is inspected.
        )

    assert result == {
        "status": "render_in_progress",
        "reason": "audiobook_render_lock_timeout",
        "retryable": True,
    }
    lock_path = job_dir / ".audiobook-render.lock"
    assert lock_path.is_file()
    assert lock_path.stat().st_mode & 0o777 == 0o600


def test_render_sensitive_detail_redacts_narrator_and_dialogue_voice_ids() -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    narrator_voice_id = "narrator-voice-private-id"
    dialogue_voice_id = "dialogue-voice-private-id"
    detail = pipeline._redact_render_sensitive_detail(
        f"provider rejected {narrator_voice_id}; fallback {dialogue_voice_id}",
        narrator_voice_id,
        dialogue_voice_id,
    )

    assert detail == "provider rejected [voice_id_redacted]; fallback [voice_id_redacted]"
    assert narrator_voice_id not in detail
    assert dialogue_voice_id not in detail


def test_exact_narration_passages_block_unsplittable_quoted_provider_overflow() -> None:
    from app.services.audiobook_narration_planner import _passages_from_spans

    max_chars = 1800
    narration = "Narrated clause, " * 150
    dialogue = f"“{'x' * 3600}”"
    closing = "Closing narration."
    source_text = f"{narration}{dialogue}{closing}"
    spans = []
    cursor = 0
    for span_index, (text, kind, speaker_id, speaker_label) in enumerate(
        (
            (narration, "narration", "narrator", "Narrator"),
            (dialogue, "dialogue", "speaker_anna", "Anna"),
            (closing, "narration", "narrator", "Narrator"),
        ),
        start=1,
    ):
        end = cursor + len(text)
        spans.append(
            {
                "span_index": span_index,
                "render": True,
                "source_text": text,
                "kind": kind,
                "speaker_role": "dialogue" if kind == "dialogue" else "narrator",
                "speaker_id": speaker_id,
                "speaker_label": speaker_label,
                "attribution_provenance": "test_source",
                "attribution_confidence": 1.0,
                "traits": {},
                "source_chapter_index": 1,
                "source_href": "chapter.xhtml",
                "source_scene_index": 0,
                "source_paragraph_index": span_index - 1,
                "char_start": cursor,
                "char_end": end,
            }
        )
        cursor = end

    passages, unsafe = _passages_from_spans(
        spans,
        max_chars=max_chars,
        pause_policy={
            "continuation": 0.12,
            "sentence": 0.18,
            "paragraph": 0.45,
            "speaker": 0.22,
            "scene": 1.25,
            "chapter": 1.5,
        },
        batch_paragraphs_with_natural_pauses=True,
    )

    assert unsafe == ["dialogue_span_exceeds_provider_limit:2"]
    assert "".join(str(passage["text"]) for passage in passages) == source_text
    assert [passage["passage_index"] for passage in passages] == list(
        range(1, len(passages) + 1)
    )
    for passage in passages:
        start = int(passage["char_start"])
        end = int(passage["char_end"])
        assert passage["text"] == source_text[start:end]
        assert passage["source_span_indexes"] in ([1], [2], [3])
    dialogue_passages = [
        passage for passage in passages if passage["source_span_indexes"] == [2]
    ]
    assert len(dialogue_passages) == 1
    assert dialogue_passages[0]["text"] == dialogue
    assert dialogue_passages[0]["char_count"] > max_chars
    assert dialogue_passages[0]["unsafe_or_very_short"] is True
    assert all(
        passage["char_count"] <= max_chars
        for passage in passages
        if passage["source_span_indexes"] != [2]
    )
    assert passages[-1]["boundary_kind_after"] == ""
    assert passages[-1]["pause_seconds_after"] == 0.0


def test_cinematic_planning_cannot_exceed_unmixr_short_tts_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_MAX_CHARS_PER_REQUEST", "1800")
    monkeypatch.setenv("EA_AUDIOBOOK_CINEMATIC_MAX_CHARS_PER_REQUEST", "50000")

    assert pipeline._audiobook_unmixr_max_chars_per_request() == 1800
    assert pipeline._audiobook_cinematic_max_chars_per_request() == 1800

    monkeypatch.setenv("EA_AUDIOBOOK_CINEMATIC_MAX_CHARS_PER_REQUEST", "1200")
    assert pipeline._audiobook_cinematic_max_chars_per_request() == 1200


@pytest.mark.parametrize(
    ("sha256", "char_count_delta", "text_path", "expected_reason"),
    (
        ("not-a-sha256", 0, "001.txt", "chapter_text_hash_missing_or_invalid:1"),
        ("actual", 1, "001.txt", "blocked_source_integrity_or_coverage_mismatch"),
        ("actual", 0, "../outside.txt", "chapter_text_path_invalid:1"),
    ),
)
def test_render_blocks_invalid_chapter_authority_before_synthesis(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    sha256: str,
    char_count_delta: int,
    text_path: str,
    expected_reason: str,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import EpubChapter, EpubMetadata

    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_CINEMATIC_NARRATION", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "0")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {
                    "voice_id": "narrator-voice",
                    "label": "Narrator",
                    "language": "en-US",
                    "tags": ["audiobook", "narration"],
                    "default": True,
                }
            ]
        ),
    )
    text = "Manifest authority is required."
    chapter_dir = tmp_path / "chapters"
    chapter_dir.mkdir()
    (chapter_dir / "001.txt").write_text(text, encoding="utf-8")
    (tmp_path / "outside.txt").write_text(text, encoding="utf-8")
    actual_hash = pipeline._sha256_bytes(text.encode("utf-8"))
    chapter = EpubChapter(
        index=1,
        title="Authority",
        source_href="chapter.xhtml",
        text_path=text_path,
        audio_filename="001.wav",
        char_count=len(text) + char_count_delta,
        sha256=actual_hash if sha256 == "actual" else sha256,
    )
    metadata = EpubMetadata(
        title="Authority",
        author="A. Writer",
        language="en-US",
        source_filename="book.epub",
        source_sha256="source-sha",
    )
    synthesis_calls: list[str] = []

    def must_not_synthesize(**kwargs):
        synthesis_calls.append(str(kwargs.get("text") or ""))
        raise AssertionError("invalid source authority reached synthesis")

    monkeypatch.setattr(pipeline, "unmixr_synthesize_request", must_not_synthesize)

    result = pipeline.render_unmixr_chapter_audio(
        job_dir=tmp_path,
        chapters=(chapter,),
        metadata=metadata,
    )

    assert result["status"] == "blocked"
    assert result["reason"] == expected_reason
    assert result["narration_plan"]["source_integrity_verified"] is False
    assert synthesis_calls == []


def test_exact_narration_plan_cache_reuses_only_exact_private_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline
    from app.services.audiobook_epub_pipeline import EpubChapter

    text = "Anna said, “One.” Ben replied, “Two.”"
    chapter = EpubChapter(
        index=1,
        title="Cache",
        source_href="chapter.xhtml",
        text_path="001.txt",
        audio_filename="001.wav",
        char_count=len(text),
        sha256=pipeline._sha256_bytes(text.encode("utf-8")),
    )
    first = pipeline._build_exact_narration_plan(
        chapter_inputs=((chapter, text),),
        render_language="en-US",
        max_chars=1800,
        job_dir=tmp_path,
    )
    assert first["status"] == "ready"
    assert (
        first["receipt_metrics_contract"]
        == pipeline.RECEIPT_METRICS_CONTRACT_NAME
    )
    assert first["planner_cache"]["status"] == "materialized"
    cache_files = tuple((tmp_path / "narration_plans").glob("exact-*.json"))
    assert len(cache_files) == 1
    assert cache_files[0].stat().st_mode & 0o777 == 0o600

    original_plan_narration = pipeline.plan_narration
    planner_calls = {"count": 0}

    def counted_plan(*args, **kwargs):
        planner_calls["count"] += 1
        return original_plan_narration(*args, **kwargs)

    monkeypatch.setattr(pipeline, "plan_narration", counted_plan)
    reused = pipeline._build_exact_narration_plan(
        chapter_inputs=((chapter, text),),
        render_language="en-US",
        max_chars=1800,
        job_dir=tmp_path,
    )
    assert reused["plan_sha256"] == first["plan_sha256"]
    assert reused["planner_cache"]["status"] == "reused"
    assert planner_calls["count"] == 1

    cached_payload = json.loads(cache_files[0].read_text(encoding="utf-8"))
    cached_payload["spans"][0]["source_text"] = "tampered"
    pipeline._write_private_json(cache_files[0], cached_payload)
    planner_calls["count"] = 0
    repaired = pipeline._build_exact_narration_plan(
        chapter_inputs=((chapter, text),),
        render_language="en-US",
        max_chars=1800,
        job_dir=tmp_path,
    )
    assert repaired["status"] == "ready"
    assert repaired["planner_cache"]["status"] == "materialized"
    assert planner_calls["count"] == 2

    stale_metrics_payload = json.loads(
        cache_files[0].read_text(encoding="utf-8")
    )
    stale_metrics_payload.pop("receipt_metrics_contract", None)
    pipeline._write_private_json(cache_files[0], stale_metrics_payload)
    planner_calls["count"] = 0
    refreshed_metrics = pipeline._build_exact_narration_plan(
        chapter_inputs=((chapter, text),),
        render_language="en-US",
        max_chars=1800,
        job_dir=tmp_path,
    )
    assert refreshed_metrics["planner_cache"]["status"] == "materialized"
    assert planner_calls["count"] == 1
    assert (
        refreshed_metrics["receipt_metrics_contract"]
        == pipeline.RECEIPT_METRICS_CONTRACT_NAME
    )


def test_audiobookshelf_lookup_maps_trusted_library_path_namespace_and_skips_missing_duplicate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    import_root = tmp_path / "audiobooks"
    target_path = (
        import_root
        / "Chummer Origin Dossier"
        / "Kestrel - Origin Story"
        / "Kestrel - Origin Story.m4b"
    )
    provider_root = Path("/mnt/pcloud/My Music/Audiobooks")
    provider_item_path = (
        provider_root / "Chummer Origin Dossier" / "Kestrel - Origin Story"
    )
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_IMPORT_ROOT", str(import_root))
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_TRUST_LIBRARY_FOLDER_PATHS", "1")
    monkeypatch.setattr(
        pipeline,
        "_audiobookshelf_library_folders",
        lambda: (provider_root,),
    )
    monkeypatch.setattr(pipeline, "_audiobookshelf_library_id", lambda: "library-1")
    monkeypatch.setattr(
        pipeline,
        "_audiobookshelf_json_request",
        lambda **_kwargs: (
            200,
            {
                "results": [
                    {
                        "id": "missing-item",
                        "path": str(provider_item_path),
                        "mediaType": "book",
                        "isMissing": True,
                        "media": {
                            "id": "missing-media",
                            "metadata": {"title": "Kestrel - Origin Story"},
                            "numAudioFiles": 1,
                        },
                    },
                    {
                        "id": "active-item",
                        "path": str(provider_item_path),
                        "mediaType": "book",
                        "isMissing": False,
                        "media": {
                            "id": "active-media",
                            "metadata": {"title": "Kestrel - Origin Story"},
                            "numAudioFiles": 1,
                        },
                    },
                ]
            },
            "",
        ),
    )
    metadata = pipeline.EpubMetadata(
        title="Kestrel - Origin Story",
        author="Chummer Origin Dossier",
        language="en-US",
        source_filename="origin.txt",
        source_sha256="source-sha",
    )

    result = pipeline._find_audiobookshelf_imported_item(
        target_path=target_path,
        metadata=metadata,
    )

    assert result["status"] == "item_found"
    assert result["library_item_id"] == "active-item"
    assert result["media_item_id"] == "active-media"
    assert result["match_kind"] == "trusted_library_folder_relative_path"


def test_audiobookshelf_absolute_namespace_mismatch_stays_closed_without_trust(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    import_root = tmp_path / "audiobooks"
    target_path = import_root / "Author" / "Title" / "Title.m4b"
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_IMPORT_ROOT", str(import_root))
    metadata = pipeline.EpubMetadata(
        title="Title",
        author="Author",
        language="en-US",
        source_filename="origin.txt",
        source_sha256="source-sha",
    )

    match_kind = pipeline._audiobookshelf_item_import_match_kind(
        row={
            "path": "/mnt/provider/Audiobooks/Author/Title",
            "mediaType": "book",
            "media": {
                "id": "media-1",
                "metadata": {"title": "Title"},
                "numAudioFiles": 1,
            },
        },
        target_path=target_path,
        metadata=metadata,
    )

    assert match_kind == ""


def test_origin_audiobook_telegram_delivery_resolves_principal_binding_without_persisted_chat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    monkeypatch.setattr(
        pipeline,
        "_telegram_delivery_context_for_job",
        lambda _job: ("telegram-test-token", "123456789"),
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {"ok": True, "result": {"message_id": 42}}
            ).encode("utf-8")

    def fake_urlopen(request, timeout=None):
        assert request.full_url.endswith("/bottelegram-test-token/sendMessage")
        return FakeResponse()

    monkeypatch.setattr(pipeline.urllib.request, "urlopen", fake_urlopen)

    receipt = pipeline._send_telegram_audiobook_status(
        job={"principal_id": "principal-1", "telegram": {}},
        text="Your Origin Dossier audiobook is ready.",
    )

    assert receipt["status"] == "sent"
    assert receipt["message_id"] == 42


def test_origin_audiobook_callback_accepts_resolved_principal_binding_without_raw_chat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import audiobook_epub_pipeline as pipeline

    monkeypatch.setattr(
        pipeline,
        "_telegram_delivery_context_for_job",
        lambda _job: ("telegram-test-token", "123456789"),
    )
    monkeypatch.setattr(
        pipeline,
        "_audiobook_publication_gate_reason",
        lambda _job: "",
    )
    monkeypatch.setattr(
        pipeline,
        "_audiobook_canary_receipt_hmac_key",
        lambda _channel: b"test-canary-key",
    )
    job = {
        "principal_id": "principal-1",
        "telegram": {},
        "audiobookshelf_import": {
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://audiobookshelf.example/share/origin",
            }
        },
    }

    reason = pipeline._audiobook_public_share_acceptance_callback_block_reason(
        job
    )

    assert reason == ""
