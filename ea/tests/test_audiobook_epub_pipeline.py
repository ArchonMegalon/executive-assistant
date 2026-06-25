from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.services import audiobook_epub_pipeline


def test_audiobook_cinematic_narration_default_enabled() -> None:
    with patch.dict(os.environ, {}, clear=True):
        assert audiobook_epub_pipeline._audiobook_cinematic_narration() is True


def _chapter_text() -> str:
    return (
        "The long narrator voice begins the scene with a low, deliberate rhythm. "
        "Characters enter the room one by one, each carrying a story, each carrying weight. "
        "Dialogue follows, and the pace must stay calm, cinematic, and continuous. "
        "Paragraphs move like camera cuts: clear, expressive, and uninterrupted. "
    ) * 20


def _voice_selection() -> dict[str, object]:
    return {
        "status": "selected",
        "voice_id": "cinematic-voice-id",
        "public": {
            "status": "selected",
            "selected": {
                "provider": "unmixr",
                "voice_id": "cinematic-voice-id",
                "label": "Cinematic Prime",
                "language": "en",
            },
        },
    }


@contextmanager
def _chapter_job() -> tuple[Path, tuple[audiobook_epub_pipeline.EpubChapter, ...], audiobook_epub_pipeline.EpubMetadata]:
    with tempfile.TemporaryDirectory() as tmpdir:
        job_dir = Path(tmpdir) / "job"
        chapters_dir = job_dir / "chapters"
        chapters_dir.mkdir(parents=True, exist_ok=True)
        chapter_text = _chapter_text()
        (chapters_dir / "chapter-001.txt").write_text(chapter_text, encoding="utf-8")
        chapter = audiobook_epub_pipeline.EpubChapter(
            index=1,
            title="Cinematic Chapter",
            source_href="chapter-001.xhtml",
            text_path="chapter-001.txt",
            audio_filename="001-cinematic.wav",
            char_count=len(chapter_text),
            sha256="dummy-sha-001",
        )
        metadata = audiobook_epub_pipeline.EpubMetadata(
            title="Cinematic Test Book",
            author="EA QA",
            language="en-US",
            source_filename="book.epub",
            source_sha256="source-sha",
        )
        yield job_dir, (chapter,), metadata


class AudiobookCinematicNarrationTests(unittest.TestCase):
    def _write_audio_file(self, **kwargs: object) -> Path:
        target = kwargs["target_wav"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"audio-blob")
        return Path(target)

    @contextmanager
    def _base_context(self):
        with _chapter_job() as job_context:
            with patch.dict(
                os.environ,
                {
                    "EA_AUDIOBOOK_CINEMATIC_NARRATION": "1",
                    "EA_AUDIOBOOK_UNMIXR_MAX_CHARS_PER_REQUEST": "100",
                    "EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED": "1",
                    "EA_AUDIOBOOK_UNMIXR_AUTO_RENDER": "1",
                },
            ):
                yield job_context

    @contextmanager
    def _voice_context(self):
        with (
            patch.object(audiobook_epub_pipeline, "selected_unmixr_voice_for_job", return_value={}),
            patch.object(audiobook_epub_pipeline, "select_unmixr_voice_for_book", return_value=_voice_selection()),
        ):
            yield

    def test_render_unmixr_chapter_audio_prefers_single_cinematic_pass(self) -> None:
        with self._base_context() as (job_dir, chapters, metadata):
            source_text = (job_dir / "chapters" / chapters[0].text_path).read_text(encoding="utf-8")
            with (
                self._voice_context(),
                patch.object(
                    audiobook_epub_pipeline,
                    "_synthesize_unmixr_with_retries",
                    return_value=(b"audio-blob", "audio/wav", []),
                ) as synthesize,
                patch.object(audiobook_epub_pipeline, "_rendered_audio_quality_report", return_value={"status": "pass"}),
                patch.object(audiobook_epub_pipeline, "_write_provider_audio_file", side_effect=self._write_audio_file),
            ):
                result = audiobook_epub_pipeline.render_unmixr_chapter_audio(
                    job_dir=job_dir,
                    chapters=chapters,
                    metadata=metadata,
                )

        self.assertEqual(result["status"], "rendered")
        chapter_result = dict(result["chapters"][0])
        self.assertEqual(chapter_result["status"], "rendered")
        self.assertEqual(chapter_result["segment_count"], 1)
        self.assertEqual(synthesize.call_count, 1)
        self.assertEqual(synthesize.call_args_list[0].kwargs["text"], source_text)

    def test_render_unmixr_chapter_audio_does_not_segment_when_cinematic_enabled(self) -> None:
        with self._base_context() as (job_dir, chapters, metadata):
            with (
                self._voice_context(),
                patch.object(
                    audiobook_epub_pipeline,
                    "_chapter_text_segment_rows",
                    side_effect=AssertionError("segmentation should be bypassed in cinematic mode"),
                ),
                patch.object(audiobook_epub_pipeline, "_synthesize_unmixr_with_retries", return_value=(b"audio-blob", "audio/wav", [])),
                patch.object(audiobook_epub_pipeline, "_rendered_audio_quality_report", return_value={"status": "pass"}),
                patch.object(audiobook_epub_pipeline, "_write_provider_audio_file", side_effect=self._write_audio_file),
            ):
                result = audiobook_epub_pipeline.render_unmixr_chapter_audio(
                    job_dir=job_dir,
                    chapters=chapters,
                    metadata=metadata,
                )

        self.assertEqual(result["status"], "rendered")

    def test_render_unmixr_chapter_audio_reverts_to_segments_when_cinematic_disabled(self) -> None:
        with self._base_context() as (job_dir, chapters, metadata):
            with (
                patch.dict(os.environ, {"EA_AUDIOBOOK_CINEMATIC_NARRATION": "0"}),
                self._voice_context(),
                patch.object(
                    audiobook_epub_pipeline,
                    "_chapter_text_segment_rows",
                    return_value=[{"text": "segment-a", "paragraph_break_after": False}],
                ) as segment_rows,
                patch.object(audiobook_epub_pipeline, "_synthesize_unmixr_with_retries", return_value=(b"audio-blob", "audio/wav", [])),
                patch.object(audiobook_epub_pipeline, "_rendered_audio_quality_report", return_value={"status": "pass"}),
                patch.object(audiobook_epub_pipeline, "_write_provider_audio_file", side_effect=self._write_audio_file),
            ):
                result = audiobook_epub_pipeline.render_unmixr_chapter_audio(
                    job_dir=job_dir,
                    chapters=chapters,
                    metadata=metadata,
                )

        self.assertEqual(result["status"], "rendered")
        self.assertEqual(segment_rows.call_count, 1)

    def test_render_unmixr_chapter_audio_blocks_when_single_pass_fails_in_cinematic_mode(self) -> None:
        with self._base_context() as (job_dir, chapters, metadata):
            source_text = (job_dir / "chapters" / chapters[0].text_path).read_text(encoding="utf-8")

            def synthesize(*, text: str, **kwargs: object) -> tuple[bytes, str, list[str]]:
                if text == source_text:
                    raise RuntimeError("request entity too large")
                return (b"audio-blob", "audio/wav", [])

            with (
                self._voice_context(),
                patch.object(audiobook_epub_pipeline, "_synthesize_unmixr_with_retries", side_effect=synthesize) as synthesize_mock,
                patch.object(audiobook_epub_pipeline, "_rendered_audio_quality_report", return_value={"status": "pass"}),
                patch.object(audiobook_epub_pipeline, "_write_provider_audio_file", side_effect=self._write_audio_file),
            ):
                result = audiobook_epub_pipeline.render_unmixr_chapter_audio(
                    job_dir=job_dir,
                    chapters=chapters,
                    metadata=metadata,
                )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "request entity too large")
        self.assertEqual(synthesize_mock.call_count, 1)


if __name__ == "__main__":
    unittest.main()
