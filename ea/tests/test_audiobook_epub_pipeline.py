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
def _chapter_job(*, chapter_count: int = 1):
    with tempfile.TemporaryDirectory() as tmpdir:
        job_dir = Path(tmpdir) / "job"
        chapters_dir = job_dir / "chapters"
        chapters_dir.mkdir(parents=True, exist_ok=True)
        chapters: list[audiobook_epub_pipeline.EpubChapter] = []
        for index in range(1, chapter_count + 1):
            chapter_text = f"{_chapter_text()} [part {index}]"
            text_path = f"chapter-{index:03d}.txt"
            (chapters_dir / text_path).write_text(chapter_text, encoding="utf-8")
            chapters.append(
                audiobook_epub_pipeline.EpubChapter(
                    index=index,
                    title=f"Cinematic Chapter {index}",
                    source_href=f"chapter-{index:03d}.xhtml",
                    text_path=text_path,
                    audio_filename=f"{index:03d}-cinematic.wav",
                    char_count=len(chapter_text),
                    sha256=f"dummy-sha-{index:03d}",
                )
            )
        metadata = audiobook_epub_pipeline.EpubMetadata(
            title="Cinematic Test Book",
            author="EA QA",
            language="en-US",
            source_filename="book.epub",
            source_sha256="source-sha",
        )
        yield job_dir, tuple(chapters), metadata


class AudiobookCinematicNarrationTests(unittest.TestCase):
    def _write_audio_file(self, **kwargs: object) -> Path:
        target = kwargs["target_wav"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"audio-blob")
        return Path(target)

    def _merge_master(self, segment_paths: tuple[Path, ...], target: Path) -> bool:
        target.write_bytes(b"audio-blob")
        return True

    @contextmanager
    def _base_context(self, chapter_count: int = 1):
        with _chapter_job(chapter_count=chapter_count) as job_context:
            with patch.dict(
                os.environ,
                {
                    "EA_AUDIOBOOK_CINEMATIC_NARRATION": "1",
                    "EA_AUDIOBOOK_CINEMATIC_MAX_CHARS_PER_REQUEST": "200000",
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
                patch.object(audiobook_epub_pipeline, "_merge_audio_segments_to_wav", side_effect=self._merge_master),
            ):
                result = audiobook_epub_pipeline.render_unmixr_chapter_audio(
                    job_dir=job_dir,
                    chapters=chapters,
                    metadata=metadata,
                )

        self.assertEqual(result["status"], "rendered")
        self.assertIn("cinematic_master_audio", result)
        chapter_result = dict(result["chapters"][0])
        self.assertEqual(chapter_result["status"], "rendered")
        self.assertEqual(chapter_result["segment_count"], 1)
        self.assertEqual(synthesize.call_count, 1)
        self.assertEqual(synthesize.call_args_list[0].kwargs["text"], source_text)

    def test_render_unmixr_chapter_audio_prefers_cinematic_continuity(self) -> None:
        with self._base_context(chapter_count=3) as (job_dir, chapters, metadata):
            combined_text = " ".join((job_dir / "chapters" / chapter.text_path).read_text(encoding="utf-8") for chapter in chapters)
            with (
                self._voice_context(),
                patch.object(
                    audiobook_epub_pipeline,
                    "_synthesize_unmixr_with_retries",
                    return_value=(b"audio-blob", "audio/wav", []),
                ) as synthesize,
                patch.object(audiobook_epub_pipeline, "_rendered_audio_quality_report", return_value={"status": "pass"}),
                patch.object(audiobook_epub_pipeline, "_write_provider_audio_file", side_effect=self._write_audio_file),
                patch.object(audiobook_epub_pipeline, "_merge_audio_segments_to_wav", side_effect=self._merge_master),
            ):
                result = audiobook_epub_pipeline.render_unmixr_chapter_audio(
                    job_dir=job_dir,
                    chapters=chapters,
                    metadata=metadata,
                )

                self.assertEqual(result["status"], "rendered")
                self.assertEqual(len(result["chapters"]), 3)
                self.assertTrue(all(chapter["status"] == "rendered" for chapter in result["chapters"]))
                self.assertEqual(synthesize.call_count, 1)
                self.assertEqual(synthesize.call_args_list[0].kwargs["text"], combined_text)

    def test_render_unmixr_chapter_audio_continuous_single_pass_ignores_cinematic_split_cap(self) -> None:
        with self._base_context(chapter_count=3) as (job_dir, chapters, metadata):
            combined_text = " ".join((job_dir / "chapters" / chapter.text_path).read_text(encoding="utf-8") for chapter in chapters)
            with (
                patch.dict(os.environ, {"EA_AUDIOBOOK_CINEMATIC_MAX_CHARS_PER_REQUEST": "10"}),
                self._voice_context(),
                patch.object(
                    audiobook_epub_pipeline,
                    "_chapter_text_segments",
                    side_effect=AssertionError("should not segment in cinematic single-pass mode"),
                ),
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
        self.assertEqual(synthesize.call_count, 1)
        self.assertEqual(synthesize.call_args_list[0].kwargs["text"], combined_text)

    def test_render_unmixr_chapter_audio_stays_single_pass_when_forced(self) -> None:
        with self._base_context(chapter_count=3) as (job_dir, chapters, metadata):
            combined_text = " ".join((job_dir / "chapters" / chapter.text_path).read_text(encoding="utf-8") for chapter in chapters)
            with (
                patch.dict(os.environ, {"EA_AUDIOBOOK_CINEMATIC_SINGLE_PASS": "0"}),
                self._voice_context(),
                patch.object(
                    audiobook_epub_pipeline,
                    "_chapter_text_segments",
                    side_effect=AssertionError("legacy cinematic chunking must remain disabled"),
                ) as segment_split,
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
        self.assertEqual(synthesize.call_count, 1)
        self.assertEqual(synthesize.call_args_list[0].kwargs["text"], combined_text)
        self.assertEqual(segment_split.call_count, 0)

    def test_render_unmixr_chapter_audio_regenerates_legacy_cinematic_master(self) -> None:
        with self._base_context(chapter_count=1) as (job_dir, chapters, metadata):
            audio_dir = job_dir / "audio"
            audio_dir.mkdir(parents=True, exist_ok=True)
            legacy_master = audio_dir / "_cinematic_master.wav"
            legacy_master.write_bytes(b"legacy-track")
            (audio_dir / "_cinematic_master.mode").write_text("legacy_merge", encoding="utf-8")
            combined_text = (job_dir / "chapters" / chapters[0].text_path).read_text(encoding="utf-8")
            mode_path = audio_dir / "_cinematic_master.mode"

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
                self.assertEqual(synthesize.call_count, 1)
                self.assertEqual(synthesize.call_args_list[0].kwargs["text"], combined_text)
                self.assertEqual(mode_path.read_text(encoding="utf-8").strip(), audiobook_epub_pipeline._CINEMATIC_MASTER_SINGLE_PASS_MODE)

    def test_render_unmixr_chapter_audio_regenerates_when_cinematic_signature_changes(self) -> None:
        with self._base_context(chapter_count=1) as (job_dir, chapters, metadata):
            audio_dir = job_dir / "audio"
            audio_dir.mkdir(parents=True, exist_ok=True)
            cinematic_master = audio_dir / "_cinematic_master.wav"
            cinematic_master.write_bytes(b"cached-track")
            signature_path = audio_dir / "_cinematic_master.signature"
            signature_path.write_text("stale-signature", encoding="utf-8")
            (audio_dir / "_cinematic_master.mode").write_text(audiobook_epub_pipeline._CINEMATIC_MASTER_SINGLE_PASS_MODE, encoding="utf-8")
            combined_text = (job_dir / "chapters" / chapters[0].text_path).read_text(encoding="utf-8")
            expected_signature = audiobook_epub_pipeline._cinematic_track_signature(
                chapter_inputs=audiobook_epub_pipeline._collect_cinematic_track_input(job_dir=job_dir, chapters=chapters),
            )

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
                self.assertEqual(synthesize.call_count, 1)
                self.assertEqual(synthesize.call_args_list[0].kwargs["text"], combined_text)
                self.assertEqual(signature_path.read_text(encoding="utf-8").strip(), expected_signature)

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

    def test_render_unmixr_chapter_audio_falls_back_to_segmented_cinematic_pass_when_provider_input_is_too_long(self) -> None:
        with self._base_context() as (job_dir, chapters, metadata):
            source_text = (job_dir / "chapters" / chapters[0].text_path).read_text(encoding="utf-8")
            segment_calls: list[str] = []

            def synthesize(*, text: str, **kwargs: object) -> tuple[bytes, str, list[str]]:
                if text == source_text:
                    raise RuntimeError("Input too long. Please limit your input to under 2000 characters.")
                segment_calls.append(text)
                return (b"audio-blob", "audio/wav", [])

            with (
                self._voice_context(),
                patch.object(audiobook_epub_pipeline, "_synthesize_unmixr_with_retries", side_effect=synthesize) as synthesize_mock,
                patch.object(audiobook_epub_pipeline, "_rendered_audio_quality_report", return_value={"status": "pass"}),
                patch.object(audiobook_epub_pipeline, "_write_provider_audio_file", side_effect=self._write_audio_file),
                patch.object(audiobook_epub_pipeline, "_merge_audio_segments_to_wav", side_effect=self._merge_master),
            ):
                result = audiobook_epub_pipeline.render_unmixr_chapter_audio(
                    job_dir=job_dir,
                    chapters=chapters,
                    metadata=metadata,
                )

        self.assertEqual(result["status"], "rendered")
        self.assertGreater(synthesize_mock.call_count, 1)
        self.assertEqual(synthesize_mock.call_args_list[0].kwargs["text"], source_text)
        self.assertTrue(all(len(text) < len(source_text) for text in segment_calls))
        self.assertEqual(result["chapters"][0]["segment_count"], len(segment_calls))

    def test_render_unmixr_chapter_audio_blocks_when_single_pass_fails_in_cinematic_mode(self) -> None:
        with self._base_context() as (job_dir, chapters, metadata):
            source_text = (job_dir / "chapters" / chapters[0].text_path).read_text(encoding="utf-8")

            def synthesize(*, text: str, **kwargs: object) -> tuple[bytes, str, list[str]]:
                if text == source_text:
                    raise RuntimeError("provider internal failure")
                return (b"audio-blob", "audio/wav", [])

            with (
                self._voice_context(),
                patch.object(audiobook_epub_pipeline, "_synthesize_unmixr_with_retries", side_effect=synthesize) as synthesize_mock,
                patch.object(audiobook_epub_pipeline, "_rendered_audio_quality_report", return_value={"status": "pass"}),
                patch.object(audiobook_epub_pipeline, "_write_provider_audio_file", side_effect=self._write_audio_file),
                patch.object(audiobook_epub_pipeline, "_merge_audio_segments_to_wav", side_effect=self._merge_master),
            ):
                result = audiobook_epub_pipeline.render_unmixr_chapter_audio(
                    job_dir=job_dir,
                    chapters=chapters,
                    metadata=metadata,
                )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "provider internal failure")
        self.assertEqual(synthesize_mock.call_count, 1)

    def test_render_unmixr_chapter_audio_blocks_for_selected_voice_author_gender_mismatch(self) -> None:
        with self._base_context() as (job_dir, chapters, metadata):
            voice_selection = {
                "status": "selected",
                "voice_id": "cinematic-voice-id",
                "public": {
                    "status": "selected_by_user",
                    "selected": {
                        "provider": "unmixr",
                        "voice_id": "cinematic-voice-id",
                        "label": "Seraphina",
                        "language": "de-de",
                        "supported_languages": ["de-de"],
                        "tags": ["audiobook", "narration", "female", "warm"],
                    },
                    "book_profile": {"author_gender_signal": "male"},
                },
            }
            with (
                patch.object(audiobook_epub_pipeline, "selected_unmixr_voice_for_job", return_value=voice_selection),
                patch.object(audiobook_epub_pipeline, "select_unmixr_voice_for_book", return_value=voice_selection),
                patch.object(audiobook_epub_pipeline, "_selected_voice_language_mismatch", return_value={}),
                patch.object(
                    audiobook_epub_pipeline,
                    "_selected_voice_author_gender_mismatch",
                    return_value={
                        "author_gender_signal": "male",
                        "selected_gender": "female",
                        "replacement_candidate_count": 2,
                    },
                ),
            ):
                result = audiobook_epub_pipeline.render_unmixr_chapter_audio(
                    job_dir=job_dir,
                    chapters=chapters,
                    metadata=metadata,
                )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "selected_voice_author_gender_mismatch")
        self.assertEqual(result["voice_author_gender_mismatch"]["author_gender_signal"], "male")

    def test_merge_m4b_if_ready_rebuilds_continuous_cinematic_track(self) -> None:
        with self._base_context(chapter_count=4) as (job_dir, chapters, metadata):
            audio_dir = job_dir / "audio"
            audio_dir.mkdir(parents=True, exist_ok=True)
            cinematic_track = audio_dir / "_cinematic_master.wav"
            cinematic_track.write_bytes(b"cinematic-track")
            (audio_dir / "_cinematic_master.mode").write_text(
                audiobook_epub_pipeline._CINEMATIC_MASTER_SINGLE_PASS_MODE,
                encoding="utf-8",
            )
            (audio_dir / "_cinematic_master.signature").write_text(
                audiobook_epub_pipeline._cinematic_track_signature(
                    chapter_inputs=audiobook_epub_pipeline._collect_cinematic_track_input(job_dir=job_dir, chapters=chapters),
                ),
                encoding="utf-8",
            )
            for chapter in chapters:
                (audio_dir / chapter.audio_filename).write_bytes(f"legacy-{chapter.index}".encode("utf-8"))
            output_file = (job_dir / "output" / "Cinematic Test Book.m4b").resolve()
            merged_result = {
                "status": "m4b_ready",
                "provider": "ffmpeg",
                "output_file": str(output_file),
                "command": ["ffmpeg", "-hide_banner"],
                "chapter_count": 1,
                "cover_embedded": False,
                "normalized_audio_count": 1,
            }

            with (
                patch.object(
                    audiobook_epub_pipeline,
                    "_merge_audio_segments_to_wav",
                    side_effect=self._merge_master,
                ) as merge_segments,
                patch.object(
                    audiobook_epub_pipeline,
                    "_merge_m4b_with_ffmpeg",
                    return_value=merged_result,
                ) as merge_m4b,
            ):
                result = audiobook_epub_pipeline._merge_m4b_if_ready(
                    job_dir=job_dir,
                    metadata=metadata,
                    chapters=chapters,
                    cinematic_track_path=cinematic_track,
                )

        self.assertEqual(result["status"], "m4b_ready")
        self.assertEqual(merge_segments.call_count, 0)
        self.assertEqual(merge_m4b.call_count, 1)
        self.assertEqual(merge_m4b.call_args.kwargs["cinematic_track_path"], cinematic_track)

    def test_merge_m4b_if_ready_rejects_invalid_cinematic_track_path(self) -> None:
        with self._base_context(chapter_count=4) as (job_dir, chapters, metadata):
            audio_dir = job_dir / "audio"
            audio_dir.mkdir(parents=True, exist_ok=True)
            cinematic_track = audio_dir / "_cinematic_master.wav"
            cinematic_track.write_bytes(b"legacy-track")
            for chapter in chapters:
                (audio_dir / chapter.audio_filename).write_bytes(f"legacy-{chapter.index}".encode("utf-8"))
            output_file = (job_dir / "output" / "Cinematic Test Book.m4b").resolve()
            merged_result = {
                "status": "m4b_ready",
                "provider": "ffmpeg",
                "output_file": str(output_file),
                "command": ["ffmpeg", "-hide_banner"],
                "chapter_count": len(chapters),
                "cover_embedded": False,
                "normalized_audio_count": len(chapters),
            }

            with patch.object(
                audiobook_epub_pipeline,
                "_merge_m4b_with_ffmpeg",
                return_value=merged_result,
            ) as merge_m4b:
                result = audiobook_epub_pipeline._merge_m4b_if_ready(
                    job_dir=job_dir,
                    metadata=metadata,
                    chapters=chapters,
                    cinematic_track_path=cinematic_track,
                )

        self.assertEqual(result["status"], "waiting_for_unmixr_export")
        self.assertEqual(result["reason"], "cinematic_master_track_missing")
        self.assertEqual(merge_m4b.call_count, 0)

    def test_discover_or_build_cinematic_master_audio(self) -> None:
        with self._base_context(chapter_count=2) as (job_dir, chapters, _metadata):
            audio_dir = job_dir / "audio"
            audio_dir.mkdir(parents=True, exist_ok=True)
            cinematic_master = audio_dir / "_cinematic_master.wav"
            cinematic_master.write_bytes(b"legacy-track")
            (audio_dir / "_cinematic_master.mode").write_text(
                audiobook_epub_pipeline._CINEMATIC_MASTER_SINGLE_PASS_MODE,
                encoding="utf-8",
            )
            (audio_dir / "_cinematic_master.signature").write_text(
                audiobook_epub_pipeline._cinematic_track_signature(
                    chapter_inputs=audiobook_epub_pipeline._collect_cinematic_track_input(job_dir=job_dir, chapters=chapters),
                ),
                encoding="utf-8",
            )

            cinematic_master_discovered = audiobook_epub_pipeline._discover_or_build_cinematic_master_audio(
                job_dir=job_dir,
                chapters=chapters,
            )

            self.assertEqual(cinematic_master_discovered, cinematic_master)
            self.assertEqual(cinematic_master_discovered is not None and cinematic_master_discovered.is_file(), True)

    def test_discover_or_build_cinematic_master_audio_refuses_legacy_merge(self) -> None:
        with self._base_context(chapter_count=2) as (job_dir, chapters, _metadata):
            audio_dir = job_dir / "audio"
            audio_dir.mkdir(parents=True, exist_ok=True)
            for chapter in chapters:
                (audio_dir / chapter.audio_filename).write_bytes(f"legacy-{chapter.index}".encode("utf-8"))

            with patch.object(
                audiobook_epub_pipeline,
                "_merge_audio_segments_to_wav",
                side_effect=self._merge_master,
            ) as merge_master:
                cinematic_master = audiobook_epub_pipeline._discover_or_build_cinematic_master_audio(
                    job_dir=job_dir,
                    chapters=chapters,
                )

            self.assertIsNone(cinematic_master)
            self.assertEqual(merge_master.call_count, 0)

    def test_merge_m4b_if_ready_waits_for_cinematic_master_when_cinematic_mode_enabled(self) -> None:
        with self._base_context(chapter_count=4) as (job_dir, chapters, metadata):
            audio_dir = job_dir / "audio"
            audio_dir.mkdir(parents=True, exist_ok=True)
            for chapter in chapters:
                (audio_dir / chapter.audio_filename).write_bytes(f"legacy-{chapter.index}".encode("utf-8"))
            output_file = (job_dir / "output" / "Cinematic Test Book.m4b").resolve()
            merged_result = {
                "status": "m4b_ready",
                "provider": "ffmpeg",
                "output_file": str(output_file),
                "command": ["ffmpeg", "-hide_banner"],
                "chapter_count": len(chapters),
                "cover_embedded": False,
                "normalized_audio_count": len(chapters),
            }

            with patch.object(
                audiobook_epub_pipeline,
                "_merge_m4b_with_ffmpeg",
                return_value=merged_result,
            ) as merge_m4b:
                result = audiobook_epub_pipeline._merge_m4b_if_ready(
                    job_dir=job_dir,
                    metadata=metadata,
                    chapters=chapters,
                    cinematic_track_path=None,
                )

        self.assertEqual(result["status"], "waiting_for_unmixr_export")
        self.assertEqual(result["reason"], "cinematic_master_track_missing")
        self.assertEqual(merge_m4b.call_count, 0)

if __name__ == "__main__":
    unittest.main()
