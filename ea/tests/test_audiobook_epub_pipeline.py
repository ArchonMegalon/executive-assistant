from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import struct
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import wave

from fastapi import HTTPException
import pytest

from app.services import audiobook_epub_pipeline


def test_audiobook_cinematic_narration_default_enabled() -> None:
    with patch.dict(os.environ, {}, clear=True):
        assert audiobook_epub_pipeline._audiobook_cinematic_narration() is True


def test_audiobook_cinematic_single_pass_default_disabled() -> None:
    with patch.dict(os.environ, {}, clear=True):
        assert audiobook_epub_pipeline._audiobook_cinematic_single_pass() is False


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

    def _write_job_manifest(
        self,
        *,
        job_dir: Path,
        chapters: tuple[audiobook_epub_pipeline.EpubChapter, ...],
        metadata: audiobook_epub_pipeline.EpubMetadata,
    ) -> None:
        (job_dir / "job.json").write_text(
            json.dumps(
                {
                    "metadata": {
                        "title": metadata.title,
                        "author": metadata.author,
                        "language": metadata.language,
                        "source_filename": metadata.source_filename,
                        "source_sha256": metadata.source_sha256,
                    },
                    "chapters": [chapter.__dict__ for chapter in chapters],
                    "storage": {"job_dir": str(job_dir)},
                }
            ),
            encoding="utf-8",
        )

    def _expected_cinematic_signature(
        self,
        *,
        job_dir: Path,
        chapters: tuple[audiobook_epub_pipeline.EpubChapter, ...],
        metadata: audiobook_epub_pipeline.EpubMetadata,
    ) -> str:
        chapter_inputs = audiobook_epub_pipeline._collect_cinematic_track_input(
            job_dir=job_dir,
            chapters=chapters,
        )
        render_language = audiobook_epub_pipeline._normalize_language(metadata.language)
        exact_plan = audiobook_epub_pipeline._build_exact_narration_plan(
            chapter_inputs=chapter_inputs,
            render_language=render_language,
            max_chars=audiobook_epub_pipeline._audiobook_cinematic_max_chars_per_request(),
        )
        speaker_cast = audiobook_epub_pipeline._resolve_speaker_cast_for_narration_plan(
            job_dir=job_dir,
            narration_plan=exact_plan,
            narrator_voice_id="cinematic-voice-id",
            render_language=render_language,
            default_dialogue_selection={},
        )
        return audiobook_epub_pipeline._cinematic_track_signature(
            chapter_inputs=chapter_inputs,
            narrator_voice_id="cinematic-voice-id",
            render_language=render_language,
            planner_plan_sha256=str(exact_plan["plan_sha256"]),
            cast_map_sha256=str(speaker_cast.get("cast_map_sha256") or ""),
        )

    @contextmanager
    def _base_context(self, chapter_count: int = 1):
        with _chapter_job(chapter_count=chapter_count) as job_context:
            with patch.dict(
                os.environ,
                {
                    "EA_AUDIOBOOK_CINEMATIC_NARRATION": "1",
                    "EA_AUDIOBOOK_CINEMATIC_SINGLE_PASS": "1",
                    "EA_AUDIOBOOK_CINEMATIC_MAX_CHARS_PER_REQUEST": "200000",
                    "EA_AUDIOBOOK_UNMIXR_MAX_CHARS_PER_REQUEST": "100",
                    "EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED": "1",
                    "EA_AUDIOBOOK_UNMIXR_AUTO_RENDER": "1",
                },
            ), patch.object(
                audiobook_epub_pipeline,
                "_normalize_rendered_audio_file",
                side_effect=lambda path: path,
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
            combined_text = "\n\n\n".join(
                (job_dir / "chapters" / chapter.text_path).read_text(encoding="utf-8")
                for chapter in chapters
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
            combined_text = "\n\n\n".join(
                (job_dir / "chapters" / chapter.text_path).read_text(encoding="utf-8")
                for chapter in chapters
            )
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

    def test_render_unmixr_chapter_audio_uses_semantic_scene_passes_when_single_pass_disabled(self) -> None:
        with self._base_context(chapter_count=3) as (job_dir, chapters, metadata):
            chapter_texts = [
                (job_dir / "chapters" / chapter.text_path).read_text(encoding="utf-8")
                for chapter in chapters
            ]
            with (
                patch.dict(os.environ, {"EA_AUDIOBOOK_CINEMATIC_SINGLE_PASS": "0"}),
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
        self.assertEqual(synthesize.call_count, 3)
        self.assertEqual(
            [call.kwargs["text"] for call in synthesize.call_args_list],
            chapter_texts,
        )
        self.assertEqual(result["chapters"][0]["scene_pause_count"], 0)
        self.assertEqual(result["chapters"][0]["chapter_pause_count"], 2)

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
            signature_inputs = audiobook_epub_pipeline._collect_cinematic_track_input(
                job_dir=job_dir,
                chapters=chapters,
            )
            exact_plan = audiobook_epub_pipeline._build_exact_narration_plan(
                chapter_inputs=signature_inputs,
                render_language=audiobook_epub_pipeline._normalize_language("en-US"),
                max_chars=audiobook_epub_pipeline._audiobook_cinematic_max_chars_per_request(),
            )
            expected_signature = audiobook_epub_pipeline._cinematic_track_signature(
                chapter_inputs=signature_inputs,
                narrator_voice_id="cinematic-voice-id",
                render_language="en-US",
                planner_plan_sha256=str(exact_plan["plan_sha256"]),
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
                patch.object(audiobook_epub_pipeline, "_synthesize_unmixr_with_retries", return_value=(b"audio-blob", "audio/wav", [])),
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
        self.assertGreater(result["chapters"][0]["segment_count"], 1)
        self.assertEqual(
            result["narration_plan"]["contract_name"],
            audiobook_epub_pipeline.NARRATION_PLAN_CONTRACT_NAME,
        )

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
        self.assertGreater(result["chapters"][0]["segment_count"], len(segment_calls))
        self.assertEqual(result["chapters"][0]["regenerated_passage_count"], len(segment_calls))
        self.assertGreater(result["chapters"][0]["reused_passage_count"], 0)

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
        self.assertEqual(result["reason"], "unmixr_synthesize_failed")
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
            self._write_job_manifest(job_dir=job_dir, chapters=chapters, metadata=metadata)
            audio_dir = job_dir / "audio"
            audio_dir.mkdir(parents=True, exist_ok=True)
            cinematic_track = audio_dir / "_cinematic_master.wav"
            cinematic_track.write_bytes(b"cinematic-track")
            (audio_dir / "_cinematic_master.mode").write_text(
                audiobook_epub_pipeline._CINEMATIC_MASTER_SINGLE_PASS_MODE,
                encoding="utf-8",
            )
            (audio_dir / "_cinematic_master.signature").write_text(
                self._expected_cinematic_signature(
                    job_dir=job_dir,
                    chapters=chapters,
                    metadata=metadata,
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
                self._voice_context(),
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
        with self._base_context(chapter_count=2) as (job_dir, chapters, metadata):
            self._write_job_manifest(job_dir=job_dir, chapters=chapters, metadata=metadata)
            audio_dir = job_dir / "audio"
            audio_dir.mkdir(parents=True, exist_ok=True)
            cinematic_master = audio_dir / "_cinematic_master.wav"
            cinematic_master.write_bytes(b"legacy-track")
            (audio_dir / "_cinematic_master.mode").write_text(
                audiobook_epub_pipeline._CINEMATIC_MASTER_SINGLE_PASS_MODE,
                encoding="utf-8",
            )
            (audio_dir / "_cinematic_master.signature").write_text(
                self._expected_cinematic_signature(
                    job_dir=job_dir,
                    chapters=chapters,
                    metadata=metadata,
                ),
                encoding="utf-8",
            )

            with self._voice_context():
                cinematic_master_discovered = audiobook_epub_pipeline._discover_or_build_cinematic_master_audio(
                    job_dir=job_dir,
                    chapters=chapters,
                )

            self.assertEqual(cinematic_master_discovered, cinematic_master)
            self.assertEqual(cinematic_master_discovered is not None and cinematic_master_discovered.is_file(), True)

    def test_dialogue_cinematic_master_discovery_keeps_plan_and_cast_signature(self) -> None:
        with self._base_context(chapter_count=1) as (job_dir, chapters, metadata):
            dialogue_text = 'Anna said, “Come now.” The corridor stayed quiet.'
            (job_dir / "chapters" / chapters[0].text_path).write_text(
                dialogue_text,
                encoding="utf-8",
            )
            self._write_job_manifest(job_dir=job_dir, chapters=chapters, metadata=metadata)
            voice_catalog = json.dumps(
                [
                    {
                        "voice_id": "cinematic-voice-id",
                        "label": "Cinematic Prime",
                        "language": "en-US",
                        "tags": ["audiobook", "narration", "warm"],
                        "default": True,
                    },
                    {
                        "voice_id": "anna-voice-id",
                        "label": "Anna Actor",
                        "language": "en-US",
                        "tags": ["audiobook", "dialogue", "female", "warm"],
                    },
                ]
            )
            merged_result = {
                "status": "m4b_ready",
                "provider": "ffmpeg",
                "output_file": str(job_dir / "output" / "book.m4b"),
                "command": ["ffmpeg"],
                "chapter_count": 1,
            }

            with (
                patch.dict(
                    os.environ,
                    {"EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON": voice_catalog},
                ),
                self._voice_context(),
                patch.object(
                    audiobook_epub_pipeline,
                    "_synthesize_unmixr_with_retries",
                    return_value=(b"audio-blob", "audio/wav", []),
                ),
                patch.object(
                    audiobook_epub_pipeline,
                    "_rendered_audio_quality_report",
                    return_value={"status": "pass"},
                ),
                patch.object(
                    audiobook_epub_pipeline,
                    "_write_provider_audio_file",
                    side_effect=self._write_audio_file,
                ),
                patch.object(
                    audiobook_epub_pipeline,
                    "_merge_audio_segments_to_wav",
                    side_effect=self._merge_master,
                ),
                patch.object(
                    audiobook_epub_pipeline,
                    "_merge_m4b_with_ffmpeg",
                    return_value=merged_result,
                ) as merge_m4b,
            ):
                rendered = audiobook_epub_pipeline.render_unmixr_chapter_audio(
                    job_dir=job_dir,
                    chapters=chapters,
                    metadata=metadata,
                )
                discovered = audiobook_epub_pipeline._discover_or_build_cinematic_master_audio(
                    job_dir=job_dir,
                    chapters=chapters,
                )
                merged = audiobook_epub_pipeline._merge_m4b_if_ready(
                    job_dir=job_dir,
                    metadata=metadata,
                    chapters=chapters,
                    cinematic_track_path=discovered,
                )

            self.assertEqual(rendered["status"], "rendered")
            self.assertEqual(
                (job_dir / "audio" / "_cinematic_master.mode").read_text(encoding="utf-8"),
                audiobook_epub_pipeline._CINEMATIC_MASTER_SEMANTIC_PASS_MODE,
            )
            self.assertTrue(str(rendered["speaker_cast"].get("cast_map_sha256") or ""))
            self.assertEqual(discovered, Path(rendered["cinematic_master_audio"]))
            self.assertEqual(merged["status"], "m4b_ready")
            self.assertEqual(merge_m4b.call_args.kwargs["cinematic_track_path"], discovered)

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


def _audiobookshelf_match_metadata() -> audiobook_epub_pipeline.EpubMetadata:
    return audiobook_epub_pipeline.EpubMetadata(
        title="Same Book",
        author="Same Author",
        language="en",
        source_filename="same.epub",
        source_sha256="source-sha",
        cover_image_path="",
        cover_media_type="",
    )


def test_audiobookshelf_item_match_rejects_same_title_wrong_absolute_path(tmp_path: Path) -> None:
    import_root = tmp_path / "import"
    target_path = import_root / "Same Author" / "Same Book" / "Same Book.m4b"
    stale_path = tmp_path / "old-library" / "Same Author" / "Same Book" / "Same Book.m4b"
    row = {
        "media": {"title": "Same Book", "metadata": {"title": "Same Book"}},
        "libraryFiles": [
            {
                "metadata": {
                    "path": str(stale_path),
                    "relPath": "Same Author/Same Book/Same Book.m4b",
                }
            }
        ],
    }
    with patch.dict(os.environ, {"EA_AUDIOBOOKSHELF_IMPORT_ROOT": str(import_root)}, clear=False):
        assert (
            audiobook_epub_pipeline._audiobookshelf_item_matches_import(
                row=row,
                target_path=target_path,
                metadata=_audiobookshelf_match_metadata(),
            )
            is False
        )


def test_audiobookshelf_item_match_accepts_exact_absolute_path(tmp_path: Path) -> None:
    import_root = tmp_path / "import"
    target_path = import_root / "Same Author" / "Same Book" / "Same Book.m4b"
    row = {"libraryFiles": [{"metadata": {"path": str(target_path)}}]}
    with patch.dict(os.environ, {"EA_AUDIOBOOKSHELF_IMPORT_ROOT": str(import_root)}, clear=False):
        assert audiobook_epub_pipeline._audiobookshelf_item_matches_import(
            row=row,
            target_path=target_path,
            metadata=_audiobookshelf_match_metadata(),
        )


def test_audiobookshelf_item_match_accepts_import_root_relative_path(tmp_path: Path) -> None:
    import_root = tmp_path / "import"
    target_path = import_root / "Same Author" / "Same Book" / "Same Book.m4b"
    row = {"libraryFiles": [{"metadata": {"relPath": "Same Author/Same Book/Same Book.m4b"}}]}
    with patch.dict(os.environ, {"EA_AUDIOBOOKSHELF_IMPORT_ROOT": str(import_root)}, clear=False):
        assert audiobook_epub_pipeline._audiobookshelf_item_matches_import(
            row=row,
            target_path=target_path,
            metadata=_audiobookshelf_match_metadata(),
        )


def test_preserve_ready_audiobookshelf_access_rejects_legacy_unbound_share() -> None:
    result = audiobook_epub_pipeline._preserve_ready_audiobookshelf_access(
        import_result={
            "status": "imported",
            "target_path": "/library/new/Same Book.m4b",
            "public_share": {"status": "waiting_for_audiobookshelf_scan"},
        },
        previous_import={
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://example.test/audiobookshelf/share/stale",
            }
        },
    )

    assert result["public_share"]["status"] == "waiting_for_audiobookshelf_scan"


def test_preserve_ready_audiobookshelf_access_keeps_bound_share_after_refresh_failure() -> None:
    target_path = "/library/current/Same Book.m4b"
    target_hash = audiobook_epub_pipeline._sha256_bytes(target_path.encode("utf-8"))
    result = audiobook_epub_pipeline._preserve_ready_audiobookshelf_access(
        import_result={
            "status": "imported",
            "target_path": target_path,
            "public_share": {"status": "waiting_for_audiobookshelf_scan", "reason": "scan_timeout"},
        },
        previous_import={
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://example.test/audiobookshelf/share/current",
                "audiobookshelf_target_path_sha256": target_hash,
                "audiobookshelf_item_match_kind": "exact_absolute_path",
            }
        },
    )

    assert result["public_share"]["status"] == "public_share_ready"
    assert result["public_share"]["preserved_after_refresh_failure"] is True


def test_preserve_ready_audiobookshelf_access_rejects_share_without_match_kind() -> None:
    target_path = "/library/current/Same Book.m4b"
    target_hash = audiobook_epub_pipeline._sha256_bytes(target_path.encode("utf-8"))
    result = audiobook_epub_pipeline._preserve_ready_audiobookshelf_access(
        import_result={
            "status": "imported",
            "target_path": target_path,
            "public_share": {"status": "waiting_for_audiobookshelf_scan"},
        },
        previous_import={
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://example.test/audiobookshelf/share/stale",
                "audiobookshelf_target_path_sha256": target_hash,
            }
        },
    )

    assert result["public_share"]["status"] == "waiting_for_audiobookshelf_scan"


def _speaker_row(
    pipeline,
    label: str,
    *,
    traits: dict[str, object] | None = None,
    chapter_index: int = 1,
) -> dict[str, object]:
    return {
        "text": f"Dialogue spoken by {label}.",
        "speaker_role": "dialogue",
        "speaker_id": pipeline._speaker_id_from_label(label),
        "speaker_label": label,
        "attribution_provenance": "exact_span_planner",
        "attribution_confidence": 0.98,
        "attribution_explicit": True,
        "traits": traits or {},
        "source_chapter_index": chapter_index,
    }


def _approved_casting_trait(
    pipeline,
    value: object,
    *,
    provenance: str = "approved_casting_notes",
    confidence: float = 1.0,
    reviewed_at: datetime | None = None,
    expires_at: datetime | None = None,
    **extra: object,
) -> dict[str, object]:
    reviewed = reviewed_at or (datetime.now(UTC) - timedelta(minutes=1))
    expires = expires_at or (reviewed + timedelta(days=7))
    evidence = {
        "scope": pipeline.REQUIRED_AUDIOBOOK_SPEAKER_CASTING_SCOPE,
        "authority_class": "user",
        "reviewed_at": reviewed.isoformat(),
        "expires_at": expires.isoformat(),
        "value": value,
    }
    return {
        "value": value,
        "provenance": provenance,
        "confidence": confidence,
        "casting_eligible": True,
        "casting_approved": True,
        "casting_review_scope": pipeline.REQUIRED_AUDIOBOOK_SPEAKER_CASTING_SCOPE,
        "casting_review_revoked": False,
        "casting_review_authority_class": "user",
        "casting_review_reviewed_at": reviewed.isoformat(),
        "casting_review_expires_at": expires.isoformat(),
        "casting_review_evidence_sha256": pipeline._speaker_casting_stable_sha256(
            evidence
        ),
        **extra,
    }


def _approved_stored_speaker_profile(
    pipeline,
    label: str,
    traits: dict[str, object],
) -> dict[str, object]:
    speaker_id = pipeline._speaker_id_from_label(label)
    profile_ref = f"profile:{speaker_id}"
    profile: dict[str, object] = {
        "speaker_profile_id": profile_ref,
        "traits": traits,
    }
    raw_traits, trait_claims = pipeline._speaker_profile_trait_claims(profile)
    conflict_rows = pipeline._speaker_profile_conflict_rows(
        raw_traits,
        trait_claims,
    )
    reviewed = datetime.now(UTC) - timedelta(minutes=1)
    expires = reviewed + timedelta(days=7)
    profile["casting_review"] = {
        "status": "approved",
        "scope": [pipeline.REQUIRED_AUDIOBOOK_SPEAKER_CASTING_SCOPE],
        "revoked": False,
        "approved_by_user": True,
        "speaker_id": speaker_id,
        "speaker_traits_sha256": pipeline._speaker_casting_stable_sha256(
            trait_claims
        ),
        "speaker_profile_ref_sha256": pipeline._sha256_bytes(
            profile_ref.encode("utf-8")
        ),
        "reviewed_at": reviewed.isoformat(),
        "expires_at": expires.isoformat(),
        "source_conflict_acknowledged": bool(conflict_rows),
        "reviewed_conflicts_sha256": (
            pipeline._speaker_casting_stable_sha256(conflict_rows)
            if conflict_rows
            else ""
        ),
    }
    return profile


def test_speaker_trait_value_normalizes_approximate_age_aliases() -> None:
    pipeline = audiobook_epub_pipeline
    assert pipeline._speaker_trait_value("approximate_age", "middle-aged") == "mature"
    assert pipeline._speaker_trait_value("approximate_age", "younger adult") == "young_adult"
    assert pipeline._speaker_trait_value("approximate_age", "older adult") == "senior"


def test_private_voice_selection_requires_explicit_current_approval() -> None:
    pipeline = audiobook_epub_pipeline
    now = datetime(2026, 7, 12, 10, 0, tzinfo=UTC)

    assert pipeline._speaker_voice_selection_approved(
        {"status": "approved"},
        now=now,
    ) is False
    assert pipeline._speaker_voice_selection_approved(
        {
            "status": "approved",
            "approved_by_user": True,
            "revoked": True,
        },
        now=now,
    ) is False
    assert pipeline._speaker_voice_selection_approved(
        {
            "status": "approved",
            "approved_by_user": True,
            "revoked": False,
        },
        now=now,
    ) is False
    assert pipeline._speaker_voice_selection_approved(
        {
            "status": "approved",
            "approved_by_user": True,
            "revoked": False,
            "expires_at": "2026-07-12T09:59:59Z",
        },
        now=now,
    ) is False
    assert pipeline._speaker_voice_selection_approved(
        {
            "status": "approved",
            "approved_by_user": True,
            "revoked": False,
            "expires_at": "2026-07-12T10:00:01Z",
        },
        now=now,
    ) is True


@pytest.mark.parametrize(
    "invalid_state",
    [
        "revoked",
        "string_revoked",
        "expired",
        "missing_expiry",
        "missing_approver",
        "multiple_approvers",
        "missing_voice_hash",
    ],
)
def test_configured_dialogue_default_rechecks_exact_current_approval(
    tmp_path: Path,
    invalid_state: str,
) -> None:
    pipeline = audiobook_epub_pipeline
    job_dir = tmp_path / invalid_state
    job_dir.mkdir()
    selection: dict[str, object] = {
        "status": "approved",
        "approved_by_user": True,
        "revoked": False,
        "expires_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
        "selected_callback_token": "approved-dialogue-token",
        "voice_id_sha256": pipeline._sha256_bytes(b"approved-dialogue-id"),
    }
    if invalid_state == "revoked":
        selection["revoked"] = True
    elif invalid_state == "string_revoked":
        selection["revoked"] = "true"
    elif invalid_state == "expired":
        selection["expires_at"] = (
            datetime.now(UTC) - timedelta(minutes=1)
        ).isoformat()
    elif invalid_state == "missing_expiry":
        selection.pop("expires_at")
    elif invalid_state == "missing_approver":
        selection.pop("approved_by_user")
    elif invalid_state == "multiple_approvers":
        selection["approved_by_family"] = True
    else:
        selection.pop("voice_id_sha256")
    candidate: dict[str, object] = {
        "voice_id": "approved-dialogue-id",
        "voice_id_sha256": pipeline._sha256_bytes(
            b"approved-dialogue-id"
        ),
        "public": {"language": "en-US"},
    }
    if invalid_state == "missing_voice_hash":
        candidate.pop("voice_id_sha256")
    pipeline._write_job(
        job_dir,
        {
            "job_id": invalid_state,
            "provider": {"dialogue_voice_selection": selection},
        },
    )
    pipeline._write_private_json(
        job_dir / "voice_audition" / "private.json",
        {
            "contract_name": pipeline.VOICE_AUDITION_CONTRACT_NAME,
            "candidates": {
                "approved-dialogue-token": candidate,
            },
        },
        private_parent=True,
    )

    assert pipeline._configured_dialogue_voice_selection(job_dir) == {}


def test_private_speaker_selection_requires_voice_hash_binding() -> None:
    pipeline = audiobook_epub_pipeline
    now = datetime.now(UTC)
    profile = {
        "profile_provenance": "private_job_profile",
        "voice_selection": {
            "status": "approved",
            "approved_by_user": True,
            "revoked": False,
            "expires_at": (now + timedelta(days=7)).isoformat(),
            "selected_callback_token": "unbound-token",
        },
    }

    assert pipeline._approved_speaker_voice(
        profile=profile,
        private_candidates={
            "unbound-token": {"voice_id": "unbound-private-id"}
        },
        now=now,
    ) == {}


def test_voice_candidate_score_matches_multiword_ethnicity_hint() -> None:
    pipeline = audiobook_epub_pipeline
    profile = {
        "traits": {
            "ethnicity": _approved_casting_trait(
                pipeline,
                "Austrian Nigerian",
                provenance="unit_test",
            )
        },
        "casting_review_validated_by_profile_registry": True,
    }
    preset_match = audiobook_epub_pipeline.VoicePreset(
        preset_key="voice_match",
        voice_id="female-nigerian-id",
        label="Match",
        language="en-US",
        tags=("female", "nigerian", "warm"),
        supported_languages=("en-US",),
        default=False,
        source="unit-test",
    )
    preset_miss = audiobook_epub_pipeline.VoicePreset(
        preset_key="voice_miss",
        voice_id="female-german-id",
        label="Miss",
        language="en-US",
        tags=("female", "slovenian", "warm"),
        supported_languages=("en-US",),
        default=False,
        source="unit-test",
    )

    match_score, match_matched, _ = pipeline._speaker_voice_candidate_score(
        preset=preset_match,
        profile=profile,
        render_language="en-US",
    )
    miss_score, miss_matched, _ = pipeline._speaker_voice_candidate_score(
        preset=preset_miss,
        profile=profile,
        render_language="en-US",
    )
    assert match_score > miss_score
    assert "ethnicity" in match_matched
    assert "ethnicity" not in miss_matched


def test_voice_candidate_score_ignores_ineligible_sensitive_source_hint() -> None:
    pipeline = audiobook_epub_pipeline
    profile = {
        "traits": {
            "ethnicity": {
                "value": "Nigerian",
                "provenance": "explicit_source_phrase",
                "confidence": 0.95,
                "casting_eligible": False,
                "requires_human_approval": True,
            }
        }
    }
    preset = audiobook_epub_pipeline.VoicePreset(
        preset_key="source_hint_must_not_rank",
        voice_id="private-voice-id",
        label="Catalog voice",
        language="en-US",
        tags=("nigerian", "dialogue"),
        supported_languages=("en-US",),
        default=False,
        source="unit-test",
    )

    _score, matched, unmatched = pipeline._speaker_voice_candidate_score(
        preset=preset,
        profile=profile,
        render_language="en-US",
    )

    assert "ethnicity" not in matched
    assert "ethnicity" not in unmatched


def test_generic_approved_status_does_not_authorize_sensitive_casting_hint() -> None:
    pipeline = audiobook_epub_pipeline
    profile = {
        "traits": {
            "ethnicity": {
                "value": "Nigerian",
                "provenance": "explicit_source_phrase",
                "confidence": 0.95,
                "casting_eligible": True,
                "requires_human_approval": True,
                "status": "approved",
            }
        }
    }
    preset = audiobook_epub_pipeline.VoicePreset(
        preset_key="generic_status_must_not_rank",
        voice_id="private-voice-id",
        label="Catalog voice",
        language="en-US",
        tags=("nigerian", "dialogue"),
        supported_languages=("en-US",),
        source="unit-test",
    )

    _score, matched, unmatched = pipeline._speaker_voice_candidate_score(
        preset=preset,
        profile=profile,
        render_language="en-US",
    )

    assert "ethnicity" not in matched
    assert "ethnicity" not in unmatched


def test_unresolved_conflicting_sensitive_evidence_does_not_rank() -> None:
    pipeline = audiobook_epub_pipeline
    profile = {
        "traits": {
            "gender_presentation": _approved_casting_trait(
                pipeline,
                "female",
                conflicting_evidence_present=True,
            )
        }
    }
    preset = audiobook_epub_pipeline.VoicePreset(
        preset_key="unresolved_conflict_must_not_rank",
        voice_id="private-voice-id",
        label="Catalog voice",
        language="en-US",
        tags=("female", "dialogue"),
        supported_languages=("en-US",),
        source="unit-test",
    )

    _score, matched, unmatched = pipeline._speaker_voice_candidate_score(
        preset=preset,
        profile=profile,
        render_language="en-US",
    )

    assert "gender_presentation" not in matched
    assert "gender_presentation" not in unmatched


def test_forged_direct_segment_casting_markers_cannot_affect_ranking(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pipeline = audiobook_epub_pipeline
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "0")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {
                    "voice_id": "narrator-id",
                    "label": "Narrator",
                    "language": "en",
                    "tags": ["narration"],
                },
                {
                    "voice_id": "neutral-id",
                    "label": "Neutral dialogue",
                    "language": "en",
                    "tags": ["neutral", "dialogue"],
                },
                {
                    "voice_id": "female-id",
                    "label": "Female dialogue",
                    "language": "en",
                    "gender": "female",
                    "tags": ["dialogue"],
                },
            ]
        ),
    )
    job_dir = tmp_path / "forged-segment-markers"
    job_dir.mkdir()
    pipeline._write_job(
        job_dir,
        {"job_id": "forged-segment-markers", "metadata": {"source_sha256": "seed"}},
    )
    plain = _speaker_row(pipeline, "Unreviewed speaker")
    forged = _speaker_row(
        pipeline,
        "Unreviewed speaker",
        traits={
            "gender_presentation": _approved_casting_trait(
                pipeline,
                "female",
            )
        },
    )

    baseline = pipeline._resolve_audiobook_speaker_cast(
        job_dir=job_dir,
        segment_rows=(plain,),
        narrator_voice_id="narrator-id",
        render_language="en",
    )
    attempted_forgery = pipeline._resolve_audiobook_speaker_cast(
        job_dir=job_dir,
        segment_rows=(forged,),
        narrator_voice_id="narrator-id",
        render_language="en",
    )

    speaker_id = pipeline._speaker_id_from_label("Unreviewed speaker")
    assert attempted_forgery["cast_map_sha256"] == baseline["cast_map_sha256"]
    assert attempted_forgery["private"][speaker_id]["traits"] == {}
    assert attempted_forgery["private"][speaker_id]["matched_trait_kinds"] == (
        baseline["private"][speaker_id]["matched_trait_kinds"]
    )
    assert attempted_forgery["private"][speaker_id]["unmatched_trait_kinds"] == (
        baseline["private"][speaker_id]["unmatched_trait_kinds"]
    )
    assert "gender_presentation" not in attempted_forgery["private"][speaker_id][
        "matched_trait_kinds"
    ]


def test_automatic_cast_blocks_when_no_voice_matches_reviewed_sensitive_traits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pipeline = audiobook_epub_pipeline
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "0")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {
                    "voice_id": "narrator-id",
                    "label": "Narrator",
                    "language": "en",
                    "tags": ["narration"],
                },
                {
                    "voice_id": "wrong-young-male-id",
                    "label": "Wrong cast",
                    "language": "en",
                    "tags": ["dialogue", "male", "young_adult"],
                },
                {
                    "voice_id": "untagged-id",
                    "label": "Unverified cast",
                    "language": "en",
                    "tags": ["dialogue"],
                },
            ]
        ),
    )
    job_dir = tmp_path / "no-sensitive-match"
    job_dir.mkdir()
    profile = _approved_stored_speaker_profile(
        pipeline,
        "Maria",
        {
            "gender_presentation": "female",
            "age_band": "senior",
        },
    )
    pipeline._write_job(
        job_dir,
        {
            "job_id": "no-sensitive-match",
            "speaker_profiles": {"Maria": profile},
        },
    )

    result = pipeline._resolve_audiobook_speaker_cast(
        job_dir=job_dir,
        segment_rows=(_speaker_row(pipeline, "Maria"),),
        narrator_voice_id="narrator-id",
        render_language="en",
    )

    assert result["status"] == "blocked"
    assert result["reason"] == (
        "speaker_voice_sensitive_traits_unmatched_or_unverified"
    )
    assert result["public"]["trait_values_exposed"] is False


def test_global_dialogue_default_cannot_override_reviewed_sensitive_traits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pipeline = audiobook_epub_pipeline
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "0")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {
                    "voice_id": "narrator-id",
                    "label": "Narrator",
                    "language": "en",
                    "tags": ["narration"],
                },
                {
                    "voice_id": "wrong-default-id",
                    "label": "Wrong default",
                    "language": "en",
                    "tags": ["dialogue", "male", "young_adult"],
                },
                {
                    "voice_id": "review-compatible-id",
                    "label": "Compatible cast",
                    "language": "en",
                    "tags": ["dialogue", "female", "senior"],
                },
            ]
        ),
    )
    job_dir = tmp_path / "default-cannot-override"
    job_dir.mkdir()
    profile = _approved_stored_speaker_profile(
        pipeline,
        "Maria",
        {
            "gender_presentation": "female",
            "age_band": "senior",
        },
    )
    pipeline._write_job(
        job_dir,
        {
            "job_id": "default-cannot-override",
            "speaker_profiles": {"Maria": profile},
        },
    )

    result = pipeline._resolve_audiobook_speaker_cast(
        job_dir=job_dir,
        segment_rows=(_speaker_row(pipeline, "Maria"),),
        narrator_voice_id="narrator-id",
        render_language="en",
        default_dialogue_selection={
            "voice_id": "wrong-default-id",
            "source": "global_default",
        },
    )

    speaker_id = pipeline._speaker_id_from_label("Maria")
    assert result["status"] == "ready"
    assert result["private"][speaker_id]["voice_id"] == (
        "review-compatible-id"
    )


@pytest.mark.parametrize(
    "approved_voice_id",
    ["explicit-mismatched-id", "explicit-unverified-id"],
)
def test_explicit_speaker_voice_must_match_all_reviewed_sensitive_traits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    approved_voice_id: str,
) -> None:
    pipeline = audiobook_epub_pipeline
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "0")
    presets = [
        {
            "voice_id": "narrator-id",
            "label": "Narrator",
            "language": "en-US",
            "tags": ["narration"],
        },
        {
            "voice_id": "review-compatible-id",
            "label": "Compatible cast",
            "language": "en-US",
            "tags": ["dialogue", "female", "senior"],
        },
    ]
    if approved_voice_id == "explicit-mismatched-id":
        presets.append(
            {
                "voice_id": approved_voice_id,
                "label": "Mismatched cast",
                "language": "en-US",
                "tags": ["dialogue", "male", "young_adult"],
            }
        )
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(presets),
    )
    job_dir = tmp_path / approved_voice_id
    job_dir.mkdir()
    profile = _approved_stored_speaker_profile(
        pipeline,
        "Maria",
        {
            "gender_presentation": "female",
            "age_band": "senior",
        },
    )
    profile["voice_selection"] = {
        "status": "approved",
        "approved_by_user": True,
        "revoked": False,
        "expires_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
        "selected_callback_token": "maria-explicit-token",
        "voice_id_sha256": pipeline._sha256_bytes(
            approved_voice_id.encode("utf-8")
        ),
    }
    pipeline._write_job(
        job_dir,
        {
            "job_id": approved_voice_id,
            "speaker_profiles": {"Maria": profile},
        },
    )
    pipeline._write_private_json(
        job_dir / "voice_audition" / "private.json",
        {
            "contract_name": pipeline.VOICE_AUDITION_CONTRACT_NAME,
            "candidates": {
                "maria-explicit-token": {
                    "voice_id": approved_voice_id,
                    "voice_id_sha256": pipeline._sha256_bytes(
                        approved_voice_id.encode("utf-8")
                    ),
                    "public": {"language": "en-US"},
                }
            },
        },
        private_parent=True,
    )

    result = pipeline._resolve_audiobook_speaker_cast(
        job_dir=job_dir,
        segment_rows=(_speaker_row(pipeline, "Maria"),),
        narrator_voice_id="narrator-id",
        render_language="en-US",
    )

    assert result["status"] == "blocked"
    assert result["reason"] == (
        "speaker_voice_sensitive_traits_unmatched_or_unverified"
    )
    assert approved_voice_id not in json.dumps(result["public"], sort_keys=True)
    assert result["public"]["trait_values_exposed"] is False


@pytest.mark.parametrize("approved_first", [True, False])
def test_divergent_duplicate_speaker_voice_selection_never_resurrects_approval(
    tmp_path: Path,
    approved_first: bool,
) -> None:
    pipeline = audiobook_epub_pipeline
    job_dir = tmp_path / ("approved-first" if approved_first else "revoked-first")
    job_dir.mkdir()
    speaker_id = pipeline._speaker_id_from_label("Anna")
    approved = {
        "speaker_id": speaker_id,
        "voice_selection": {
            "status": "approved",
            "approved_by_user": True,
            "revoked": False,
            "expires_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
            "selected_callback_token": "old-approved-token",
            "voice_id_sha256": pipeline._sha256_bytes(b"old-approved-id"),
        },
    }
    revoked = json.loads(json.dumps(approved))
    revoked["voice_selection"]["revoked"] = True
    rows = [approved, revoked] if approved_first else [revoked, approved]
    pipeline._write_job(
        job_dir,
        {
            "job_id": job_dir.name,
            "provider": {"speaker_voice_selections": rows},
        },
    )

    profiles = pipeline._speaker_profile_rows(job_dir)

    assert len(profiles) == 1
    assert profiles[0]["speaker_id"] == speaker_id
    assert profiles[0]["voice_selection"] == {}
    assert profiles[0]["voice_selection_state_ambiguous"] is True
    assert pipeline._approved_speaker_voice(
        profile=profiles[0],
        private_candidates={
            "old-approved-token": {
                "voice_id": "old-approved-id",
                "voice_id_sha256": pipeline._sha256_bytes(b"old-approved-id"),
            }
        },
        now=datetime.now(UTC),
    ) == {}


def test_speaker_profile_lookup_prioritizes_exact_id_and_fails_alias_collision_closed() -> None:
    pipeline = audiobook_epub_pipeline
    speaker_id = pipeline._speaker_id_from_label("Shared alias")
    alias_first = {
        "speaker_id": "speaker_other_profile",
        "speaker_label": "Wrong alias owner",
        "alias_ids": [speaker_id],
        "traits": {"style": {"value": "wrong"}},
        "voice_selection": {"status": "approved"},
        "profile_provenance": "private_job_profile",
    }
    exact_second = {
        "speaker_id": speaker_id,
        "speaker_label": "Exact owner",
        "alias_ids": [],
        "traits": {"style": {"value": "exact"}},
        "voice_selection": {},
        "profile_provenance": "private_job_profile",
    }

    exact = pipeline._profile_for_speaker(
        (alias_first, exact_second),
        speaker_id=speaker_id,
    )
    ambiguous = pipeline._profile_for_speaker(
        (
            alias_first,
            {
                **exact_second,
                "speaker_id": "speaker_second_alias_owner",
                "alias_ids": [speaker_id],
            },
        ),
        speaker_id=speaker_id,
    )

    assert exact["speaker_label"] == "Exact owner"
    assert ambiguous["profile_provenance"] == (
        "ambiguous_profile_key_neutral_fallback"
    )
    assert ambiguous["traits"] == {}
    assert ambiguous["voice_selection"] == {}
    assert ambiguous["casting_review_state_ambiguous"] is True
    assert ambiguous["voice_selection_state_ambiguous"] is True


def test_profile_conflict_review_is_bound_to_exact_superseded_evidence(
    tmp_path: Path,
) -> None:
    pipeline = audiobook_epub_pipeline
    job_dir = tmp_path / "exact-conflict-review"
    job_dir.mkdir()
    profile = _approved_stored_speaker_profile(
        pipeline,
        "Maria",
        {
            "gender_presentation": {
                "value": "female",
                "provenance": "approved_character_sheet",
                "conflicting_evidence_present": True,
                "superseded_provenance": "source_pronoun_inference",
                "superseded_evidence_sha256": "a" * 64,
            }
        },
    )
    exact_review = dict(profile["casting_review"])
    assert exact_review["source_conflict_acknowledged"] is True
    assert len(str(exact_review["reviewed_conflicts_sha256"])) == 64

    blanket_ack = json.loads(json.dumps(profile))
    blanket_ack["casting_review"].pop("reviewed_conflicts_sha256")
    pipeline._write_job(
        job_dir,
        {
            "job_id": "blanket-conflict-ack",
            "speaker_profiles": {"Maria": blanket_ack},
        },
    )
    assert pipeline._speaker_profile_rows(job_dir)[0]["traits"] == {}

    pipeline._write_job(
        job_dir,
        {
            "job_id": "exact-conflict-ack",
            "speaker_profiles": {"Maria": profile},
        },
    )
    exact_rows = pipeline._speaker_profile_rows(job_dir)
    exact_trait = exact_rows[0]["traits"]["gender_presentation"]
    assert exact_trait["conflict_review_approved"] is True
    assert len(str(exact_trait["conflict_review_evidence_sha256"])) == 64

    changed_evidence = json.loads(json.dumps(profile))
    changed_evidence["traits"]["gender_presentation"][
        "superseded_evidence_sha256"
    ] = "b" * 64
    pipeline._write_job(
        job_dir,
        {
            "job_id": "changed-conflict-evidence",
            "speaker_profiles": {"Maria": changed_evidence},
        },
    )
    assert pipeline._speaker_profile_rows(job_dir)[0]["traits"] == {}


def test_speaker_voice_candidate_score_prefers_audiobook_capability_over_general_voice() -> None:
    pipeline = audiobook_epub_pipeline
    profile = {
        "traits": {
            "gender_presentation": _approved_casting_trait(
                pipeline,
                "masculine",
                provenance="approved_casting_notes",
                confidence=0.9,
            )
        },
        "casting_review_validated_by_profile_registry": True,
    }
    audiobook = audiobook_epub_pipeline.VoicePreset(
        preset_key="audiobook_voice",
        voice_id="audiobook-voice-id",
        label="Audiobook voice",
        language="de-DE",
        tags=("male", "audiobook_voices", "audiobook", "narration", "storytelling"),
        supported_languages=("de-DE",),
        default=False,
        source="unit-test",
    )
    general = audiobook_epub_pipeline.VoicePreset(
        preset_key="general_voice",
        voice_id="general-voice-id",
        label="General voice",
        language="de-DE",
        tags=("male", "general", "speech"),
        supported_languages=("de-DE",),
        default=False,
        source="unit-test",
    )

    audiobook_score, audiobook_matched, _ = pipeline._speaker_voice_candidate_score(
        preset=audiobook,
        profile=profile,
        render_language="de-DE",
    )
    general_score, general_matched, _ = pipeline._speaker_voice_candidate_score(
        preset=general,
        profile=profile,
        render_language="de-DE",
    )

    assert audiobook_score > general_score
    assert audiobook_matched == general_matched == ["gender_presentation"]


def test_speaker_cast_uses_explicit_traits_as_ranking_hints_and_is_stable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pipeline = audiobook_epub_pipeline
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "0")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {
                    "voice_id": "narrator-private-id",
                    "label": "Narrator",
                    "language": "en-US",
                    "tags": ["neutral", "narration"],
                    "default": True,
                },
                {
                    "voice_id": "elder-private-id",
                    "label": "Elder Storyteller",
                    "language": "en-US",
                    "tags": ["female", "senior", "east_asian", "warm"],
                },
                {
                    "voice_id": "young-private-id",
                    "label": "Young Character",
                    "language": "en-US",
                    "tags": ["male", "young_adult", "energetic"],
                },
            ]
        ),
    )
    job_dir = tmp_path / "stable-cast"
    job_dir.mkdir()
    amala_traits = {
        "gender_presentation": {
            "value": "female",
            "provenance": "approved_character_sheet",
        },
        "approximate_age": {
            "value": 74,
            "provenance": "approved_character_sheet",
            "confidence": 0.95,
        },
        "ethnicity": {
            "value": "east_asian",
            "provenance": "author_approved_character_sheet",
        },
    }
    ben_traits = {
        "gender_presentation": {
            "value": "male",
            "provenance": "approved_character_sheet",
        },
        "approximate_age": {
            "value": 25,
            "provenance": "approved_character_sheet",
            "confidence": 0.9,
        },
    }
    pipeline._write_job(
        job_dir,
        {
            "job_id": "stable-cast",
            "metadata": {"source_sha256": "book-seed"},
            "speaker_profiles": {
                "Amala": _approved_stored_speaker_profile(
                    pipeline,
                    "Amala",
                    amala_traits,
                ),
                "Ben": _approved_stored_speaker_profile(
                    pipeline,
                    "Ben",
                    ben_traits,
                ),
            },
        },
    )
    rows = (
        _speaker_row(pipeline, "Ben", chapter_index=1),
        _speaker_row(pipeline, "Amala", chapter_index=1),
        _speaker_row(pipeline, "Amala", chapter_index=8),
    )

    first = pipeline._resolve_audiobook_speaker_cast(
        job_dir=job_dir,
        segment_rows=rows,
        narrator_voice_id="narrator-private-id",
        render_language="en-US",
    )
    second = pipeline._resolve_audiobook_speaker_cast(
        job_dir=job_dir,
        segment_rows=tuple(reversed(rows)),
        narrator_voice_id="narrator-private-id",
        render_language="en-US",
    )

    amala_id = pipeline._speaker_id_from_label("Amala")
    ben_id = pipeline._speaker_id_from_label("Ben")
    assert first["status"] == "ready"
    assert first["private"][amala_id]["voice_id"] == "elder-private-id"
    assert first["private"][ben_id]["voice_id"] == "young-private-id"
    assert first["cast_map_sha256"] == second["cast_map_sha256"]
    assert first["public"]["narrator_voice_excluded"] is True
    assert first["public"]["traits_are_ranking_hints_only"] is True
    public_json = json.dumps(first["public"], sort_keys=True)
    assert "narrator-private-id" not in public_json
    assert "elder-private-id" not in public_json
    assert "young-private-id" not in public_json
    assert "east_asian" not in public_json


def test_speaker_cast_matches_explicit_catalog_demographics_locale_and_accent(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pipeline = audiobook_epub_pipeline
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "0")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {
                    "voice_id": "narrator-id",
                    "label": "Narrator",
                    "language": "en-US",
                    "tags": ["narration"],
                },
                {
                    "voice_id": "explicit-match-id",
                    "label": "Senior Nigerian feminine voice",
                    "locale": "en-NG",
                    "supported_locales": ["en-NG", "en-US"],
                    "gender": "feminine",
                    "age": 72,
                    "accent": "Austrian",
                    "cultural_identity": "Nigerian",
                    "tags": ["dialogue", "warm"],
                },
                {
                    "voice_id": "partial-match-id",
                    "label": "Catalog voice 18",
                    "language": "en-US",
                    "gender": "female",
                    "age_band": "senior",
                    "accent": "Canadian",
                    "cultural_identity": "Irish",
                    "tags": ["dialogue", "warm"],
                },
            ]
        ),
    )
    job_dir = tmp_path / "explicit-catalog-metadata"
    job_dir.mkdir()
    pipeline._write_job(
        job_dir,
        {
            "job_id": "explicit-catalog-metadata",
            "speaker_profiles": {
                "Speaker 17": _approved_stored_speaker_profile(
                    pipeline,
                    "Speaker 17",
                    {
                        "gender_presentation": "feminine",
                        "age_band": "older_adult",
                        "locale": "en-NG",
                        "dialect": "Austrian",
                        "cultural_identity": "Nigerian",
                    },
                )
            },
        },
    )
    row = _speaker_row(pipeline, "Speaker 17")

    result = pipeline._resolve_audiobook_speaker_cast(
        job_dir=job_dir,
        segment_rows=(row,),
        narrator_voice_id="narrator-id",
        render_language="en-US",
    )

    speaker_id = pipeline._speaker_id_from_label("Speaker 17")
    entry = result["private"][speaker_id]
    assert result["status"] == "ready"
    assert entry["voice_id"] == "explicit-match-id"
    assert entry["voice_label"] == "Senior Nigerian feminine voice"
    assert entry["matched_trait_kinds"] == [
        "accent",
        "approximate_age",
        "ethnicity",
        "gender_presentation",
        "language",
    ]
    assert entry["render_language_compatible"] is True
    assert entry["voice_catalog_source"] == "env:EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON"
    assert result["public"]["narrator_voice_excluded"] is True
    assert result["public"]["identity_or_demographics_claimed"] is False
    assert "Senior Nigerian feminine voice" not in json.dumps(
        result["public"], ensure_ascii=False, sort_keys=True
    )


@pytest.mark.parametrize(
    ("speaker_age", "catalog_age", "decoy_age"),
    [
        (8, "child", "adult"),
        (16, "teen", "adult"),
        (26, "young_adult", "senior"),
        (42, "adult", "child"),
        (62, "mature", "young_adult"),
        (78, "senior", "adult"),
    ],
)
def test_speaker_cast_matches_explicit_age_bands(
    monkeypatch,
    tmp_path: Path,
    speaker_age: int,
    catalog_age: str,
    decoy_age: str,
) -> None:
    pipeline = audiobook_epub_pipeline
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "0")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {
                    "voice_id": "narrator-id",
                    "label": "Narrator",
                    "language": "en",
                    "tags": ["narration"],
                },
                {
                    "voice_id": f"age-{catalog_age}",
                    "label": "Explicit age match",
                    "language": "en",
                    "age_band": catalog_age,
                    "tags": ["dialogue"],
                },
                {
                    "voice_id": f"age-{decoy_age}",
                    "label": "Explicit age decoy",
                    "language": "en",
                    "age_band": decoy_age,
                    "tags": ["dialogue"],
                },
            ]
        ),
    )
    job_dir = tmp_path / f"age-{catalog_age}"
    job_dir.mkdir()
    pipeline._write_job(
        job_dir,
        {
            "job_id": f"age-{catalog_age}",
            "speaker_profiles": {
                "Age-coded speaker": _approved_stored_speaker_profile(
                    pipeline,
                    "Age-coded speaker",
                    {"approximate_age": speaker_age},
                )
            },
        },
    )

    result = pipeline._resolve_audiobook_speaker_cast(
        job_dir=job_dir,
        segment_rows=(
            _speaker_row(pipeline, "Age-coded speaker"),
        ),
        narrator_voice_id="narrator-id",
        render_language="en",
    )

    speaker_id = pipeline._speaker_id_from_label("Age-coded speaker")
    assert result["private"][speaker_id]["voice_id"] == f"age-{catalog_age}"
    assert "approximate_age" in result["private"][speaker_id]["matched_trait_kinds"]


def test_speaker_cast_supports_explicit_nonbinary_gender_metadata(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pipeline = audiobook_epub_pipeline
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "0")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {
                    "voice_id": "narrator-id",
                    "label": "Narrator",
                    "language": "en",
                    "tags": ["narration"],
                },
                {
                    "voice_id": "nonbinary-id",
                    "label": "Voice 21",
                    "language": "en",
                    "gender": "non-binary",
                    "tags": ["dialogue"],
                },
                {
                    "voice_id": "male-id",
                    "label": "Voice 22",
                    "language": "en",
                    "gender": "male",
                    "tags": ["dialogue"],
                },
            ]
        ),
    )
    job_dir = tmp_path / "nonbinary-cast"
    job_dir.mkdir()
    pipeline._write_job(
        job_dir,
        {
            "job_id": "nonbinary-cast",
            "speaker_profiles": {
                "Speaker 21": _approved_stored_speaker_profile(
                    pipeline,
                    "Speaker 21",
                    {"gender_presentation": "non_binary"},
                )
            },
        },
    )

    result = pipeline._resolve_audiobook_speaker_cast(
        job_dir=job_dir,
        segment_rows=(
            _speaker_row(pipeline, "Speaker 21"),
        ),
        narrator_voice_id="narrator-id",
        render_language="en",
    )

    speaker_id = pipeline._speaker_id_from_label("Speaker 21")
    assert result["private"][speaker_id]["voice_id"] == "nonbinary-id"
    assert result["private"][speaker_id]["matched_trait_kinds"] == [
        "gender_presentation"
    ]


def test_speaker_cast_direct_sensitive_conflicts_are_ignored_without_kind_leak(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pipeline = audiobook_epub_pipeline
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "0")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {
                    "voice_id": "narrator-id",
                    "label": "Narrator",
                    "language": "en",
                    "tags": ["narration"],
                },
                {
                    "voice_id": "neutral-id",
                    "label": "Neutral dialogue",
                    "language": "en",
                    "tags": ["neutral", "dialogue"],
                },
                {
                    "voice_id": "female-id",
                    "label": "Explicit female",
                    "language": "en",
                    "gender": "female",
                    "tags": ["dialogue"],
                },
                {
                    "voice_id": "male-id",
                    "label": "Explicit male",
                    "language": "en",
                    "gender": "male",
                    "tags": ["dialogue"],
                },
            ]
        ),
    )
    job_dir = tmp_path / "ambiguous-cast"
    job_dir.mkdir()
    female_row = _speaker_row(
        pipeline,
        "Ambiguous speaker",
        traits={
            "gender": _approved_casting_trait(
                pipeline,
                "female",
                confidence=0.9,
            )
        },
    )
    male_row = _speaker_row(
        pipeline,
        "Ambiguous speaker",
        traits={
            "gender_presentation": _approved_casting_trait(
                pipeline,
                "male",
                confidence=0.9,
            )
        },
    )

    first = pipeline._resolve_audiobook_speaker_cast(
        job_dir=job_dir,
        segment_rows=(female_row, male_row),
        narrator_voice_id="narrator-id",
        render_language="en",
    )
    second = pipeline._resolve_audiobook_speaker_cast(
        job_dir=job_dir,
        segment_rows=(male_row, female_row),
        narrator_voice_id="narrator-id",
        render_language="en",
    )

    speaker_id = pipeline._speaker_id_from_label("Ambiguous speaker")
    assert first["private"][speaker_id]["voice_id"] == "neutral-id"
    assert first["private"][speaker_id]["traits"] == {}
    assert first["private"][speaker_id]["ambiguous_trait_kinds"] == []
    assert first["cast_map_sha256"] == second["cast_map_sha256"]
    assert first["public"]["cast"][0]["ambiguous_trait_count"] == 0
    assert "gender_presentation" not in json.dumps(first["public"], sort_keys=True)


def test_speaker_and_voice_names_never_supply_demographic_casting_traits(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pipeline = audiobook_epub_pipeline
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "0")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {
                    "voice_id": "narrator-id",
                    "label": "Narrator",
                    "language": "en",
                    "tags": ["narration"],
                },
                {
                    "voice_id": "named-culture-id",
                    "label": "Anna Okafor",
                    "language": "en",
                    "cultural_identity": "Nigerian",
                    "tags": ["dialogue"],
                },
                {
                    "voice_id": "neutral-id",
                    "label": "Neutral dialogue",
                    "language": "en",
                    "tags": ["neutral", "dialogue"],
                },
            ]
        ),
    )
    presets = pipeline.load_unmixr_voice_presets()
    named_preset = next(preset for preset in presets if preset.voice_id == "named-culture-id")
    assert "female" not in named_preset.tags
    assert "gender_female" not in named_preset.tags
    assert pipeline._infer_author_gender("Anna Okafor") == ""
    assert pipeline._voice_candidate_gender({"label": "Anna Okafor", "tags": []}) == ""

    job_dir = tmp_path / "no-name-inference"
    job_dir.mkdir()
    result = pipeline._resolve_audiobook_speaker_cast(
        job_dir=job_dir,
        segment_rows=(_speaker_row(pipeline, "Amina Okafor"),),
        narrator_voice_id="narrator-id",
        render_language="en",
    )

    speaker_id = pipeline._speaker_id_from_label("Amina Okafor")
    assert result["private"][speaker_id]["voice_id"] == "neutral-id"
    assert result["private"][speaker_id]["traits"] == {}
    assert result["public"]["cast"][0]["unknown_neutral_fallback"] is True


def test_speaker_cast_approved_private_choice_wins_without_public_voice_id(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pipeline = audiobook_epub_pipeline
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "0")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": "narrator-id", "label": "Narrator", "language": "de", "tags": ["narration"]},
                {"voice_id": "auto-female-id", "label": "Auto", "language": "de", "tags": ["female", "adult"]},
                {"voice_id": "approved-id", "label": "Director choice", "language": "de", "tags": ["male", "senior"]},
            ]
        ),
    )
    job_dir = tmp_path / "approved-cast"
    job_dir.mkdir()
    (job_dir / "job.json").write_text(
        json.dumps(
            {
                "speaker_profiles": {
                    "Maria": {
                        "gender_presentation": "female",
                        "approximate_age": "adult",
                        "voice_selection": {
                            "status": "approved",
                            "approved_by_user": True,
                            "revoked": False,
                            "expires_at": (
                                datetime.now(UTC) + timedelta(days=7)
                            ).isoformat(),
                            "selected_callback_token": "maria-approved-token",
                            "voice_id_sha256": audiobook_epub_pipeline._sha256_bytes(
                                b"approved-id"
                            ),
                            "label": "Director choice",
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    pipeline._write_private_json(
        job_dir / "voice_audition" / "private.json",
        {
            "contract_name": pipeline.VOICE_AUDITION_CONTRACT_NAME,
            "candidates": {
                "maria-approved-token": {
                    "voice_id": "approved-id",
                    "voice_id_sha256": pipeline._sha256_bytes(b"approved-id"),
                    "public": {"label": "Director choice"},
                }
            },
        },
        private_parent=True,
    )

    result = pipeline._resolve_audiobook_speaker_cast(
        job_dir=job_dir,
        segment_rows=(_speaker_row(pipeline, "Maria"),),
        narrator_voice_id="narrator-id",
        render_language="de",
    )

    speaker_id = pipeline._speaker_id_from_label("Maria")
    assert result["status"] == "ready"
    assert result["private"][speaker_id]["voice_id"] == "approved-id"
    assert result["private"][speaker_id]["selection_source"] == "approved_private_speaker_selection"
    rendered_public = json.dumps(result["public"], sort_keys=True)
    assert "approved-id" not in rendered_public
    assert "approved-id" not in (job_dir / "job.json").read_text(encoding="utf-8")
    public_entry = result["public"]["cast"][0]
    assert public_entry["speaker_index"] == 1
    assert "voice_id_sha256" not in public_entry
    assert "speaker_id" not in public_entry
    assert "speaker_label_sha256" not in public_entry


def test_public_cast_projection_omits_identifiers_hashes_and_trait_names(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pipeline = audiobook_epub_pipeline
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "0")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {
                    "voice_id": "narrator-private-id",
                    "label": "Narrator",
                    "language": "en-US",
                    "tags": ["narration"],
                },
                {
                    "voice_id": "matched-private-id",
                    "label": "Sensitive catalog label",
                    "language": "en-US",
                    "tags": ["female", "senior", "nigerian", "dialogue"],
                },
                {
                    "voice_id": "neutral-private-id",
                    "label": "Neutral catalog label",
                    "language": "en-US",
                    "tags": ["neutral", "dialogue"],
                },
            ]
        ),
    )
    job_dir = tmp_path / "safe-public-cast"
    job_dir.mkdir()
    label = "Private Maria Label"
    speaker_id = pipeline._speaker_id_from_label(label)
    pipeline._write_job(
        job_dir,
        {
            "job_id": "safe-public-cast",
            "speaker_profiles": {
                label: _approved_stored_speaker_profile(
                    pipeline,
                    label,
                    {
                        "gender_presentation": "female",
                        "age_band": "senior",
                        "cultural_identity": "Nigerian",
                    },
                )
            },
        },
    )

    result = pipeline._resolve_audiobook_speaker_cast(
        job_dir=job_dir,
        segment_rows=(_speaker_row(pipeline, label),),
        narrator_voice_id="narrator-private-id",
        render_language="en-US",
    )

    public_entry = result["public"]["cast"][0]
    public_json = json.dumps(result["public"], sort_keys=True)
    assert public_entry["speaker_index"] == 1
    assert public_entry["matched_trait_count"] == 3
    assert set(public_entry) == {
        "speaker_index",
        "voice_label",
        "selection_source",
        "matched_trait_count",
        "unmatched_trait_count",
        "ambiguous_trait_count",
        "trait_evidence_confidence",
        "unknown_neutral_fallback",
        "raw_voice_id_exposed",
        "identity_asserted",
    }
    assert speaker_id not in public_json
    assert label not in public_json
    assert "matched-private-id" not in public_json
    assert pipeline._sha256_bytes(b"matched-private-id") not in public_json
    assert pipeline._sha256_bytes(label.encode("utf-8")) not in public_json
    assert "gender_presentation" not in public_json
    assert "approximate_age" not in public_json
    assert "ethnicity" not in public_json
    assert "Nigerian" not in public_json


def test_write_job_strips_raw_speaker_voice_ids_and_keeps_private_token(
    tmp_path: Path,
) -> None:
    pipeline = audiobook_epub_pipeline
    payload = {
        "job_id": "speaker-override-sanitizer",
        "provider": {
            "speaker_voice_selections": [
                {
                    "speaker_label": "Maria",
                    "voice_selection": {
                        "status": "approved",
                        "selected_callback_token": "private-token-ref",
                        "voice_id": "raw-private-voice-id",
                        "voice_id_sha256": pipeline._sha256_bytes(
                            b"raw-private-voice-id"
                        ),
                    },
                }
            ]
        },
    }

    pipeline._write_job(tmp_path, payload)

    serialized = (tmp_path / "job.json").read_text(encoding="utf-8")
    stored = json.loads(serialized)
    selection_row = stored["provider"]["speaker_voice_selections"][0]
    selection = selection_row["voice_selection"]
    assert "raw-private-voice-id" not in serialized
    assert selection["selected_callback_token"] == "private-token-ref"
    assert selection["voice_id_sha256"] == pipeline._sha256_bytes(
        b"raw-private-voice-id"
    )
    assert selection_row["raw_voice_id_ignored"] is True
    assert (tmp_path / "job.json").stat().st_mode & 0o777 == 0o600


def test_safe_v2_cast_and_narration_receipts_keep_evidence_without_raw_ids() -> None:
    pipeline = audiobook_epub_pipeline
    cast_hash = "a" * 64
    voice_hash = "b" * 64
    label_hash = "c" * 64
    raw_voice_id = "raw-private-dialogue-voice"
    trait_value = "private-sensitive-trait-value"
    cast = {
        "status": "ready",
        "speaker_count": 1,
        "resolved_speaker_count": 1,
        "distinct_dialogue_voice_count": 1,
        "narrator_voice_excluded": True,
        "cast_map_sha256": cast_hash,
        "traits_are_ranking_hints_only": True,
        "identity_or_demographics_claimed": False,
        "trait_hints_used": True,
        "automatic_voice_cap": 8,
        "automatic_distinct_voice_count": 1,
        "cast": [
            {
                "speaker_id": "speaker_safe",
                "speaker_label_sha256": label_hash,
                "voice_id_sha256": voice_hash,
                "voice_id": raw_voice_id,
                "matched_trait_kinds": ["approximate_age", "ethnicity"],
                "traits": {"ethnicity": trait_value},
                "raw_voice_id_exposed": False,
                "identity_asserted": False,
            }
        ],
    }
    plan = {
        "contract_name": pipeline.NARRATION_PLAN_CONTRACT_NAME,
        "status": "ready",
        "span_count": 7,
        "dialogue_span_count": 2,
        "attributed_dialogue_span_count": 1,
        "uncertain_dialogue_span_count": 1,
        "speaker_count": 1,
        "boundary_policy": pipeline.BOUNDARY_POLICY_NAME,
        "boundary_counts": {"speaker": 2, "scene": 1},
        "total_inserted_pause_seconds": 1.72,
        "speaker_cast": cast,
    }

    safe_cast = pipeline._safe_receipt_speaker_cast(cast)
    safe_plan = pipeline._safe_receipt_narration_plan(plan)
    serialized = json.dumps({"cast": safe_cast, "plan": safe_plan}, sort_keys=True)

    assert safe_cast["cast_map_sha256"] == cast_hash
    assert safe_cast["cast"][0]["voice_id_sha256"] == voice_hash
    assert safe_plan["attributed_dialogue_span_count"] == 1
    assert safe_plan["boundary_counts"] == {"scene": 1, "speaker": 2}
    assert raw_voice_id not in serialized
    assert trait_value not in serialized


def test_continue_job_lock_timeout_returns_retryable_state_without_overwrite(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pipeline = audiobook_epub_pipeline
    monkeypatch.setenv("EA_AUDIOBOOK_JOB_LOCK_TIMEOUT_SECONDS", "0.1")
    original = {
        "job_id": "locked-job",
        "status": "waiting_provider_throttle",
        "next_action": "resume_after_unmixr_throttle",
    }
    pipeline._write_job(tmp_path, original)
    before = (tmp_path / "job.json").read_bytes()

    with pipeline._exclusive_audiobook_job_lock(tmp_path):
        result = pipeline.continue_job(tmp_path)

    assert result["status"] == "render_in_progress"
    assert result["next_action"] == "retry_after_active_audiobook_job_transaction"
    assert result["render_result"] == {
        "status": "render_in_progress",
        "reason": "audiobook_job_lock_timeout",
        "retryable": True,
    }
    assert (tmp_path / "job.json").read_bytes() == before


def test_speaker_cast_unknown_uses_neutral_distinct_voice(monkeypatch, tmp_path: Path) -> None:
    pipeline = audiobook_epub_pipeline
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "0")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": "narrator-id", "label": "Narrator", "language": "en", "tags": ["neutral"]},
                {"voice_id": "neutral-dialogue-id", "label": "Neutral dialogue", "language": "en", "tags": ["neutral", "dialogue"]},
            ]
        ),
    )
    job_dir = tmp_path / "unknown-cast"
    job_dir.mkdir()

    result = pipeline._resolve_audiobook_speaker_cast(
        job_dir=job_dir,
        segment_rows=(
            {
                "text": "Unattributed dialogue.",
                "speaker_role": "dialogue",
                "speaker_id": "speaker_unknown",
                "speaker_label": "",
                "attribution_confidence": 0.0,
                "attribution_provenance": "exact_span_planner",
                "traits": {},
            },
        ),
        narrator_voice_id="narrator-id",
        render_language="en",
    )

    assert result["status"] == "ready"
    assert result["private"]["speaker_unknown"]["voice_id"] == "neutral-dialogue-id"
    assert result["public"]["cast"][0]["unknown_neutral_fallback"] is True
    assert result["public"]["narrator_voice_excluded"] is True


def test_speaker_cast_snapshot_survives_catalog_change_on_resume(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pipeline = audiobook_epub_pipeline
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "0")
    job_dir = tmp_path / "cast-resume"
    job_dir.mkdir()
    speaker_id = pipeline._speaker_id_from_label("Anna")
    plan = {
        "contract_name": pipeline.NARRATION_PLAN_CONTRACT_NAME,
        "plan_sha256": "a" * 64,
        "source_aggregate_sha256": "b" * 64,
        "passages": [
            {
                "speaker_role": "dialogue",
                "speaker_id": speaker_id,
                "speaker_label": "Anna",
                "text": "Hello.",
                "traits": {},
                "attribution_provenance": "explicit_post_attribution",
                "attribution_confidence": 0.98,
            }
        ],
        "speakers": [
            {
                "speaker_role": "dialogue",
                "speaker_id": speaker_id,
                "speaker_label": "Anna",
                "traits": {},
                "attribution_provenance": "explicit_post_attribution",
                "attribution_confidence": 0.98,
            }
        ],
    }

    def set_catalog(
        dialogue_voice_id: str, *, narrator_voice_id: str = "narrator-id"
    ) -> None:
        monkeypatch.setenv(
            "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
            json.dumps(
                [
                    {
                        "voice_id": narrator_voice_id,
                        "label": "Narrator",
                        "language": "en-US",
                        "tags": ["narration"],
                    },
                    {
                        "voice_id": dialogue_voice_id,
                        "label": f"Warm {dialogue_voice_id} profile",
                        "language": "en-US",
                        "tags": ["dialogue", "neutral"],
                    },
                ]
            ),
        )
        pipeline._VOICE_DISCOVERY_CACHE.clear()

    set_catalog("actor-a")
    first = pipeline._resolve_speaker_cast_for_narration_plan(
        job_dir=job_dir,
        narration_plan=plan,
        narrator_voice_id="narrator-id",
        render_language="en-US",
    )
    set_catalog("actor-b")
    resumed = pipeline._resolve_speaker_cast_for_narration_plan(
        job_dir=job_dir,
        narration_plan=plan,
        narrator_voice_id="narrator-id",
        render_language="en-US",
    )

    snapshot = pipeline._speaker_cast_snapshot_path(
        job_dir,
        plan,
        narrator_voice_id="narrator-id",
        render_language="en-US",
    )
    assert first["private"][speaker_id]["voice_id"] == "actor-a"
    assert resumed["private"][speaker_id]["voice_id"] == "actor-a"
    assert resumed["public"]["reused_private_snapshot"] is True
    assert first["cast_map_sha256"] == resumed["cast_map_sha256"]
    assert "actor-a" not in json.dumps(resumed["public"], sort_keys=True)
    assert "actor-a" not in json.dumps(
        pipeline._safe_receipt_speaker_cast(resumed["public"]), sort_keys=True
    )
    assert resumed["public"]["casting_policy"] == pipeline.SPEAKER_CAST_POLICY_NAME
    assert json.loads(snapshot.read_text(encoding="utf-8"))["casting_policy"] == (
        pipeline.SPEAKER_CAST_POLICY_NAME
    )
    assert snapshot.stat().st_mode & 0o777 == 0o600
    assert snapshot.parent.stat().st_mode & 0o777 == 0o700

    set_catalog("actor-b", narrator_voice_id="narrator-new-id")
    reselection = pipeline._resolve_speaker_cast_for_narration_plan(
        job_dir=job_dir,
        narration_plan=plan,
        narrator_voice_id="narrator-new-id",
        render_language="en-US",
    )
    assert reselection["status"] == "ready"
    assert reselection["private"][speaker_id]["voice_id"] == "actor-b"
    assert reselection["public"]["reused_private_snapshot"] is False

    pipeline._write_job(
        job_dir,
        {
            "job_id": "cast-resume",
            "speaker_profiles": {
                "Anna": {
                        "voice_selection": {
                            "status": "approved",
                            "approved_by_user": True,
                            "revoked": False,
                            "expires_at": (
                                datetime.now(UTC) + timedelta(days=7)
                            ).isoformat(),
                            "selected_callback_token": "anna-approved-token",
                    }
                }
            },
        },
    )
    pipeline._write_private_json(
        job_dir / "voice_audition" / "private.json",
        {
            "contract_name": pipeline.VOICE_AUDITION_CONTRACT_NAME,
            "candidates": {
                "anna-approved-token": {
                    "voice_id": "anna-approved-id",
                    "voice_id_sha256": pipeline._sha256_bytes(b"anna-approved-id"),
                    "public": {
                        "label": "Approved Anna",
                        "language": "en-US",
                    },
                }
            },
        },
        private_parent=True,
    )
    overridden = pipeline._resolve_speaker_cast_for_narration_plan(
        job_dir=job_dir,
        narration_plan=plan,
        narrator_voice_id="narrator-id",
        render_language="en-US",
    )
    assert overridden["status"] == "ready"
    assert overridden["private"][speaker_id]["voice_id"] == "anna-approved-id"
    assert overridden["public"]["reused_private_snapshot"] is False
    override_snapshot = pipeline._speaker_cast_snapshot_path(
        job_dir,
        plan,
        narrator_voice_id="narrator-id",
        render_language="en-US",
    )
    assert override_snapshot != snapshot

    corrupted = json.loads(override_snapshot.read_text(encoding="utf-8"))
    corrupted["entries"][speaker_id]["voice_id_sha256"] = "0" * 64
    override_snapshot.write_text(json.dumps(corrupted), encoding="utf-8")
    override_snapshot.chmod(0o600)
    monkeypatch.setattr(
        pipeline,
        "load_unmixr_voice_presets",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("invalid snapshot must fail before catalog discovery")
        ),
    )
    invalid = pipeline._resolve_speaker_cast_for_narration_plan(
        job_dir=job_dir,
        narration_plan=plan,
        narrator_voice_id="narrator-id",
        render_language="en-US",
    )
    assert invalid["status"] == "blocked"
    assert invalid["reason"] == "speaker_cast_snapshot_invalid"


@pytest.mark.parametrize("invalid_selection", ["revoked", "expired"])
def test_invalid_exact_voice_selection_changes_snapshot_and_is_not_reused(
    monkeypatch,
    tmp_path: Path,
    invalid_selection: str,
) -> None:
    pipeline = audiobook_epub_pipeline
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "0")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {
                    "voice_id": "narrator-id",
                    "label": "Narrator",
                    "language": "en-US",
                    "tags": ["narration"],
                },
                {
                    "voice_id": "approved-id",
                    "label": "Approved actor",
                    "language": "en-US",
                    "tags": ["dialogue"],
                },
                {
                    "voice_id": "neutral-id",
                    "label": "Neutral actor",
                    "language": "en-US",
                    "tags": ["neutral", "dialogue"],
                },
            ]
        ),
    )
    job_dir = tmp_path / f"selection-{invalid_selection}"
    job_dir.mkdir()
    speaker_id = pipeline._speaker_id_from_label("Anna")
    selection = {
        "status": "approved",
        "approved_by_user": True,
        "revoked": False,
        "expires_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
        "selected_callback_token": "anna-approved-token",
        "voice_id_sha256": pipeline._sha256_bytes(b"approved-id"),
    }
    pipeline._write_job(
        job_dir,
        {
            "job_id": f"selection-{invalid_selection}",
            "speaker_profiles": {
                "Anna": {"voice_selection": selection},
            },
        },
    )
    pipeline._write_private_json(
        job_dir / "voice_audition" / "private.json",
        {
            "contract_name": pipeline.VOICE_AUDITION_CONTRACT_NAME,
            "candidates": {
                "anna-approved-token": {
                    "voice_id": "approved-id",
                    "voice_id_sha256": pipeline._sha256_bytes(b"approved-id"),
                    "public": {
                        "label": "Approved actor",
                        "language": "en-US",
                    },
                }
            },
        },
        private_parent=True,
    )
    plan = {
        "contract_name": pipeline.NARRATION_PLAN_CONTRACT_NAME,
        "plan_sha256": "c" * 64,
        "source_aggregate_sha256": "d" * 64,
        "passages": [
            {
                "speaker_role": "dialogue",
                "speaker_id": speaker_id,
                "speaker_label": "Anna",
                "text": "Hello.",
                "traits": {},
                "attribution_provenance": "explicit_post_attribution",
                "attribution_confidence": 0.98,
            }
        ],
        "speakers": [
            {
                "speaker_role": "dialogue",
                "speaker_id": speaker_id,
                "speaker_label": "Anna",
                "traits": {},
                "attribution_provenance": "explicit_post_attribution",
                "attribution_confidence": 0.98,
            }
        ],
    }
    effective_before = pipeline._speaker_cast_effective_inputs_sha256(job_dir)
    first = pipeline._resolve_speaker_cast_for_narration_plan(
        job_dir=job_dir,
        narration_plan=plan,
        narrator_voice_id="narrator-id",
        render_language="en-US",
    )
    snapshot_before = pipeline._speaker_cast_snapshot_path(
        job_dir,
        plan,
        narrator_voice_id="narrator-id",
        render_language="en-US",
    )
    assert first["private"][speaker_id]["selection_source"] == (
        "approved_private_speaker_selection"
    )
    assert snapshot_before.is_file()

    stored = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    invalid = stored["speaker_profiles"]["Anna"]["voice_selection"]
    if invalid_selection == "revoked":
        invalid["revoked"] = True
    else:
        invalid["expires_at"] = (
            datetime.now(UTC) - timedelta(minutes=1)
        ).isoformat()
    pipeline._write_job(job_dir, stored)

    effective_after = pipeline._speaker_cast_effective_inputs_sha256(job_dir)
    snapshot_after = pipeline._speaker_cast_snapshot_path(
        job_dir,
        plan,
        narrator_voice_id="narrator-id",
        render_language="en-US",
    )
    resumed = pipeline._resolve_speaker_cast_for_narration_plan(
        job_dir=job_dir,
        narration_plan=plan,
        narrator_voice_id="narrator-id",
        render_language="en-US",
    )

    assert effective_after != effective_before
    assert snapshot_after != snapshot_before
    assert resumed["public"]["reused_private_snapshot"] is False
    assert resumed["private"][speaker_id]["selection_source"] != (
        "approved_private_speaker_selection"
    )


def test_automatic_speaker_cast_cap_uses_deterministic_neutral_sharing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pipeline = audiobook_epub_pipeline
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_MAX_AUTOMATIC_SPEAKER_VOICES", "2")
    presets = [
        {
            "voice_id": "narrator-id",
            "label": "Narrator",
            "language": "en-US",
            "tags": ["narration"],
        },
        {
            "voice_id": "neutral-id",
            "label": "Neutral",
            "language": "en-US",
            "tags": ["dialogue", "neutral"],
        },
    ]
    presets.extend(
        {
            "voice_id": f"special-{index}",
            "label": f"Special {index}",
            "language": "en-US",
            "tags": ["dialogue", f"role_{index}"],
        }
        for index in range(1, 6)
    )
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON", json.dumps(presets))
    job_dir = tmp_path / "bounded-cast"
    job_dir.mkdir()
    rows = tuple(
        _speaker_row(
            pipeline,
            f"Speaker {index}",
            traits={
                "role": {
                    "value": str(index),
                    "provenance": "approved_casting_notes",
                    "confidence": 1.0,
                }
            },
        )
        for index in range(1, 6)
    )

    first = pipeline._resolve_audiobook_speaker_cast(
        job_dir=job_dir,
        segment_rows=rows,
        narrator_voice_id="narrator-id",
        render_language="en-US",
    )
    second = pipeline._resolve_audiobook_speaker_cast(
        job_dir=job_dir,
        segment_rows=tuple(reversed(rows)),
        narrator_voice_id="narrator-id",
        render_language="en-US",
    )

    automatic_ids = {
        str(entry["voice_id"])
        for entry in first["private"].values()
        if str(entry.get("selection_source") or "").startswith("deterministic_")
    }
    assert first["status"] == "ready"
    assert first["cast_map_sha256"] == second["cast_map_sha256"]
    assert len(automatic_ids) <= 2
    assert first["public"]["automatic_voice_cap"] == 2
    assert first["public"]["automatic_sharing_used"] is True
    assert first["public"]["automatic_shared_speaker_count"] >= 3


def test_speaker_cast_one_voice_catalog_fails_honestly(monkeypatch, tmp_path: Path) -> None:
    pipeline = audiobook_epub_pipeline
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "0")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": "only-private-id", "label": "Only voice", "language": "en", "tags": ["neutral"]},
            ]
        ),
    )
    job_dir = tmp_path / "one-voice-cast"
    job_dir.mkdir()

    result = pipeline._resolve_audiobook_speaker_cast(
        job_dir=job_dir,
        segment_rows=(_speaker_row(pipeline, "Maria"),),
        narrator_voice_id="only-private-id",
        render_language="en",
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "speaker_voice_catalog_requires_distinct_language_compatible_voice"
    public_json = json.dumps(result["public"], sort_keys=True)
    assert "only-private-id" not in public_json
    assert result["public"]["raw_voice_ids_exposed"] is False


def test_unknown_approved_dialogue_voice_blocks_when_language_is_unverified(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pipeline = audiobook_epub_pipeline
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "0")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {
                    "voice_id": "narrator-id",
                    "label": "Narrator",
                    "language": "de",
                    "tags": ["narration"],
                },
                {
                    "voice_id": "known-dialogue-id",
                    "label": "Known dialogue",
                    "language": "de",
                    "tags": ["dialogue"],
                },
            ]
        ),
    )
    job_dir = tmp_path / "unverified-approved-language"
    job_dir.mkdir()

    result = pipeline._resolve_audiobook_speaker_cast(
        job_dir=job_dir,
        segment_rows=(_speaker_row(pipeline, "Maria"),),
        narrator_voice_id="narrator-id",
        render_language="de",
        default_dialogue_selection={
            "voice_id": "unknown-private-id",
            "source": "explicit_operator_environment",
            "revoked": False,
        },
    )

    assert result["status"] == "blocked"
    assert (
        result["reason"]
        == "speaker_approved_voice_language_incompatible_or_unverified"
    )
    assert "unknown-private-id" not in json.dumps(result["public"], sort_keys=True)


def test_stored_speaker_demographics_require_explicit_approval(tmp_path: Path) -> None:
    pipeline = audiobook_epub_pipeline
    job_dir = tmp_path / "profile-approval"
    job_dir.mkdir()
    unapproved = {
        "job_id": "profile-approval",
        "speaker_profiles": {
            "Maria": {
                "traits": {
                    "gender_presentation": "female",
                    "age_band": "senior",
                    "cultural_identity": "private-background",
                    "locale": "de-AT",
                    "dialect": "Viennese",
                }
            }
        },
    }
    pipeline._write_job(job_dir, unapproved)

    rows = pipeline._speaker_profile_rows(job_dir)

    assert len(rows) == 1
    assert rows[0]["traits"] == {}

    generic_approval = json.loads(
        (job_dir / "job.json").read_text(encoding="utf-8")
    )
    generic_approval["speaker_profiles"]["Maria"][
        "traits_approved_by_user"
    ] = True
    pipeline._write_job(job_dir, generic_approval)
    assert pipeline._speaker_profile_rows(job_dir)[0]["traits"] == {}

    approved = {
        "job_id": "profile-approval",
        "speaker_profiles": {
            "Maria": _approved_stored_speaker_profile(
                pipeline,
                "Maria",
                {
                    "gender_presentation": "female",
                    "age_band": "senior",
                    "cultural_identity": "private-background",
                    "locale": "de-AT",
                    "dialect": "Viennese",
                },
            )
        },
    }
    pipeline._write_job(job_dir, approved)
    approved_rows = pipeline._speaker_profile_rows(job_dir)
    assert set(approved_rows[0]["traits"]) == {
        "gender_presentation",
        "approximate_age",
        "ethnicity",
        "language",
        "accent",
    }


@pytest.mark.parametrize(
    "invalid_review",
    [
        "revoked",
        "expired",
        "trait_hash_mismatch",
        "profile_ref_missing",
        "profile_ref_hash_mismatch",
    ],
)
def test_stored_speaker_demographics_reject_invalid_casting_review(
    tmp_path: Path,
    invalid_review: str,
) -> None:
    pipeline = audiobook_epub_pipeline
    job_dir = tmp_path / invalid_review
    job_dir.mkdir()
    profile = _approved_stored_speaker_profile(
        pipeline,
        "Maria",
        {
            "gender_presentation": "female",
            "age_band": "senior",
            "cultural_identity": "private-background",
        },
    )
    review = dict(profile["casting_review"])
    if invalid_review == "revoked":
        review["revoked"] = True
    elif invalid_review == "expired":
        review["reviewed_at"] = (datetime.now(UTC) - timedelta(days=2)).isoformat()
        review["expires_at"] = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    elif invalid_review == "profile_ref_missing":
        profile.pop("speaker_profile_id")
    elif invalid_review == "profile_ref_hash_mismatch":
        review["speaker_profile_ref_sha256"] = "1" * 64
    else:
        review["speaker_traits_sha256"] = "0" * 64
    profile["casting_review"] = review
    pipeline._write_job(
        job_dir,
        {
            "job_id": invalid_review,
            "speaker_profiles": {"Maria": profile},
        },
    )

    rows = pipeline._speaker_profile_rows(job_dir)

    assert len(rows) == 1
    assert rows[0]["traits"] == {}


@pytest.mark.parametrize(
    "invalid_review",
    ["revoked", "expired", "trait_hash_mismatch"],
)
def test_duplicate_invalid_profile_clears_prior_valid_traits(
    tmp_path: Path,
    invalid_review: str,
) -> None:
    pipeline = audiobook_epub_pipeline
    job_dir = tmp_path / f"duplicate-{invalid_review}"
    job_dir.mkdir()
    valid = _approved_stored_speaker_profile(
        pipeline,
        "Maria",
        {
            "gender_presentation": "female",
            "age_band": "senior",
        },
    )
    invalid = json.loads(json.dumps(valid))
    review = invalid["casting_review"]
    if invalid_review == "revoked":
        review["revoked"] = True
    elif invalid_review == "expired":
        review["reviewed_at"] = (
            datetime.now(UTC) - timedelta(days=2)
        ).isoformat()
        review["expires_at"] = (
            datetime.now(UTC) - timedelta(days=1)
        ).isoformat()
    else:
        review["speaker_traits_sha256"] = "0" * 64
    pipeline._write_job(
        job_dir,
        {
            "job_id": f"duplicate-{invalid_review}",
            "speaker_profiles": {"Maria": valid},
            "narration": {"speaker_profiles": {"Maria": invalid}},
        },
    )

    rows = pipeline._speaker_profile_rows(job_dir)

    assert len(rows) == 1
    assert rows[0]["traits"] == {}
    assert rows[0]["casting_review_validated_by_profile_registry"] is False
    assert rows[0]["casting_review_state_ambiguous"] is True


@pytest.mark.parametrize(
    "error_class",
    [
        "authentication_failed",
        "access_denied",
        "invalid_request",
        "balance_exhausted",
        "input_too_long",
    ],
)
def test_classified_provider_failures_are_not_retried(error_class: str) -> None:
    exc = HTTPException(
        status_code=502,
        detail=f"unmixr_synthesize_{error_class}",
    )

    assert audiobook_epub_pipeline._unmixr_retryable_error(exc) is False


def test_unexpected_provider_exception_never_publishes_source_text() -> None:
    private_passage = "PRIVATE BOOK PASSAGE token-voice-secret"
    exc = RuntimeError(f"adapter failed text={private_passage}")

    reason = audiobook_epub_pipeline._public_unmixr_error_reason(exc)

    assert reason == "unmixr_synthesize_failed"
    assert private_passage not in reason
    assert "token-voice-secret" not in reason


def test_provider_edge_trim_preserves_soft_onset_and_controlled_padding(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pipeline = audiobook_epub_pipeline
    monkeypatch.setenv("EA_AUDIOBOOK_SEGMENT_EDGE_TRIM_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_SEGMENT_EDGE_TRIM_AUDIBLE_THRESHOLD", "0.0015")
    monkeypatch.setenv("EA_AUDIOBOOK_SEGMENT_EDGE_TRIM_MIN_SILENCE_SECONDS", "0.18")
    monkeypatch.setenv("EA_AUDIOBOOK_SEGMENT_EDGE_TRIM_PRESERVE_HEAD_SECONDS", "0.08")
    monkeypatch.setenv("EA_AUDIOBOOK_SEGMENT_EDGE_TRIM_PRESERVE_TAIL_SECONDS", "0.12")
    sample_rate = 1000
    leading = [0] * 300
    soft_onset = [80] * 20
    speech = [1200] * 400
    trailing = [0] * 300
    audio_path = tmp_path / "provider.wav"
    with wave.open(str(audio_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(
            b"".join(struct.pack("<h", value) for value in leading + soft_onset + speech + trailing)
        )

    original_contract = pipeline._audiobook_segment_edge_trim_contract()
    pipeline._trim_provider_wav_edge_silence(audio_path)

    with wave.open(str(audio_path), "rb") as wav_file:
        output_frames = wav_file.getnframes()
        output_payload = wav_file.readframes(output_frames)
    stats = pipeline._pcm_window_stats(
        payload=output_payload,
        sample_width=2,
        channels=1,
        audible_threshold=0.0015,
    )
    assert 610 <= output_frames <= 630
    assert 75 <= int(stats["first_audible_frame"]) <= 85
    monkeypatch.setenv("EA_AUDIOBOOK_SEGMENT_EDGE_TRIM_PRESERVE_HEAD_SECONDS", "0.12")
    assert pipeline._audiobook_segment_edge_trim_contract() != original_contract


def test_provider_edge_trim_handles_speech_at_frame_zero(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pipeline = audiobook_epub_pipeline
    monkeypatch.setenv("EA_AUDIOBOOK_SEGMENT_EDGE_TRIM_ENABLED", "1")
    sample_rate = 1000
    audio_path = tmp_path / "frame-zero.wav"
    with wave.open(str(audio_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(
            b"".join(struct.pack("<h", value) for value in ([1000] * 400 + [0] * 400))
        )

    pipeline._trim_provider_wav_edge_silence(audio_path)

    with wave.open(str(audio_path), "rb") as wav_file:
        assert 515 <= wav_file.getnframes() <= 525


def test_external_tts_resume_consent_is_process_serialized_and_forced_off(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pipeline = audiobook_epub_pipeline
    consented = tmp_path / "consented"
    unconsented = tmp_path / "unconsented"
    pipeline._write_job(
        consented,
        {
            "job_id": "consented",
            "provider": {
                "preferred": "unmixr_ai",
                "raw_book_text_leaves_ea": True,
            },
        },
    )
    pipeline._write_job(
        unconsented,
        {
            "job_id": "unconsented",
            "provider": {
                "preferred": "unmixr_ai",
                "raw_book_text_leaves_ea": False,
            },
        },
    )
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    first_entered = threading.Event()
    release_first = threading.Event()
    observations: dict[str, tuple[str, str]] = {}

    def fake_continue(job_dir: Path) -> dict[str, object]:
        observations[job_dir.name] = (
            str(os.environ.get("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED")),
            str(os.environ.get("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER")),
        )
        if job_dir.name == "consented":
            first_entered.set()
            assert release_first.wait(timeout=3)
        return {"job_id": job_dir.name, "status": "observed"}

    monkeypatch.setattr(pipeline, "continue_job", fake_continue)
    first = threading.Thread(
        target=pipeline._resume_due_job_with_external_tts_consent,
        args=(consented,),
    )
    second = threading.Thread(
        target=pipeline._resume_due_job_with_external_tts_consent,
        args=(unconsented,),
    )
    first.start()
    assert first_entered.wait(timeout=3)
    second.start()
    time.sleep(0.1)
    assert "unconsented" not in observations
    release_first.set()
    first.join(timeout=3)
    second.join(timeout=3)

    assert observations == {
        "consented": ("1", "1"),
        "unconsented": ("0", "0"),
    }
    assert os.environ["EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED"] == "1"
    assert os.environ["EA_AUDIOBOOK_UNMIXR_AUTO_RENDER"] == "1"


def test_direct_continue_cannot_observe_another_jobs_temporary_consent(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pipeline = audiobook_epub_pipeline
    consented = tmp_path / "consented-resume"
    direct = tmp_path / "direct-continue"
    pipeline._write_job(
        consented,
        {
            "job_id": "consented-resume",
            "provider": {
                "preferred": "unmixr_ai",
                "raw_book_text_leaves_ea": True,
            },
        },
    )
    pipeline._write_job(direct, {"job_id": "direct-continue"})
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "0")
    first_entered = threading.Event()
    release_first = threading.Event()
    observations: dict[str, tuple[str, str]] = {}

    def fake_continue_locked(job_dir: Path) -> dict[str, object]:
        observations[job_dir.name] = (
            str(os.environ.get("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED")),
            str(os.environ.get("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER")),
        )
        if job_dir.name == "consented-resume":
            first_entered.set()
            assert release_first.wait(timeout=3)
        return {"job_id": job_dir.name, "status": "observed"}

    monkeypatch.setattr(pipeline, "_continue_job_locked", fake_continue_locked)
    first = threading.Thread(
        target=pipeline._resume_due_job_with_external_tts_consent,
        args=(consented,),
    )
    second = threading.Thread(target=pipeline.continue_job, args=(direct,))
    first.start()
    assert first_entered.wait(timeout=3)
    second.start()
    time.sleep(0.1)
    assert "direct-continue" not in observations
    release_first.set()
    first.join(timeout=3)
    second.join(timeout=3)

    assert observations == {
        "consented-resume": ("1", "1"),
        "direct-continue": ("0", "0"),
    }


def test_inner_timeout_is_not_misreported_as_job_lock_contention(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pipeline = audiobook_epub_pipeline
    pipeline._write_job(tmp_path, {"job_id": "inner-timeout"})

    def raise_inner_timeout(_job_dir: Path) -> dict[str, object]:
        raise TimeoutError("provider_operation_timeout")

    monkeypatch.setattr(pipeline, "_continue_job_locked", raise_inner_timeout)
    with pytest.raises(TimeoutError, match="provider_operation_timeout"):
        pipeline.continue_job(tmp_path)


def test_inner_timeout_is_not_misreported_as_render_lock_contention(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pipeline = audiobook_epub_pipeline

    def raise_inner_timeout(**_kwargs: object) -> dict[str, object]:
        raise TimeoutError("audio_convert_timeout")

    monkeypatch.setattr(
        pipeline,
        "_render_unmixr_chapter_audio_locked",
        raise_inner_timeout,
    )
    with pytest.raises(TimeoutError, match="audio_convert_timeout"):
        pipeline.render_unmixr_chapter_audio(
            job_dir=tmp_path,
            chapters=(),
            metadata=pipeline.EpubMetadata(
                title="Timeout",
                author="",
                language="en",
                source_filename="timeout.epub",
                source_sha256="a" * 64,
            ),
        )


def test_voice_audition_action_respects_job_transaction_lock(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pipeline = audiobook_epub_pipeline
    monkeypatch.setenv("EA_AUDIOBOOK_JOB_LOCK_TIMEOUT_SECONDS", "0.1")
    pipeline._write_job(
        tmp_path,
        {"job_id": "audition-locked", "status": "waiting_voice_selection"},
    )
    private_payload = {
        "contract_name": pipeline.VOICE_AUDITION_CONTRACT_NAME,
        "candidates": {
            "callback-token": {
                "candidate_key": "candidate-a",
                "voice_id": "private-id",
                "public": {"preset_key": "candidate-a"},
            }
        },
    }
    pipeline._write_private_json(
        tmp_path / "voice_audition" / "private.json",
        private_payload,
        private_parent=True,
    )
    monkeypatch.setattr(
        pipeline,
        "_find_voice_audition_job_by_token",
        lambda _token: (
            tmp_path,
            private_payload,
            private_payload["candidates"]["callback-token"],
        ),
    )
    before_job = (tmp_path / "job.json").read_bytes()
    before_private = (tmp_path / "voice_audition" / "private.json").read_bytes()

    with pipeline._exclusive_audiobook_job_lock(tmp_path):
        result = pipeline.apply_audiobook_voice_audition_action(
            callback_token="callback-token",
            action="use",
        )

    assert result["status"] == "voice_selection_in_progress"
    assert result["voice_selection_action"]["retryable"] is True
    assert (tmp_path / "job.json").read_bytes() == before_job
    assert (tmp_path / "voice_audition" / "private.json").read_bytes() == before_private


def test_automatic_cast_receipt_counts_natural_voice_reuse() -> None:
    pipeline = audiobook_epub_pipeline
    reused_voice = "shared-private-voice"
    result = pipeline._speaker_cast_result_from_private_entries(
        {
            "speaker_a": {
                "speaker_id": "speaker_a",
                "voice_id": reused_voice,
                "voice_label": "Shared voice",
                "selection_source": "deterministic_evidence_ranked_catalog",
            },
            "speaker_b": {
                "speaker_id": "speaker_b",
                "voice_id": reused_voice,
                "voice_label": "Shared voice",
                "selection_source": "deterministic_evidence_ranked_catalog",
            },
        },
        narrator_voice_id="narrator-private-voice",
        reused_private_snapshot=False,
    )

    assert result["public"]["automatic_distinct_voice_count"] == 1
    assert result["public"]["automatic_shared_speaker_count"] == 1
    assert result["public"]["automatic_sharing_used"] is True


if __name__ == "__main__":
    unittest.main()
