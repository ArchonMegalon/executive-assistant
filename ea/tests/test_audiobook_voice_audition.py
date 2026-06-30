from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
import urllib.parse

from app.services import audiobook_epub_pipeline


def _sample_chapter_text() -> str:
    return (
        "Andreas explains the system in a calm, direct voice. "
        "The text stays technical, but the rhythm should still sound human and steady. "
        "This excerpt is only here to give the audition path a small readable chapter body. "
    )


def _candidate(*, preset_key: str, label: str, gender: str, score: int) -> dict[str, object]:
    voice_id = f"voice-{preset_key}"
    return {
        "preset_key": preset_key,
        "label": label,
        "language": "de-de",
        "supported_languages": ["de-de"],
        "language_match": True,
        "language_score": 24,
        "tags": ["audiobook", "narration", gender, "warm"],
        "score": score,
        "matched_tags": ["warm"],
        "author_gender_match": gender == "male",
        "default": False,
        "blocked_by_user": False,
        "voice_id_sha256": hashlib.sha256(voice_id.encode("utf-8")).hexdigest(),
        "voice_feedback_adjustment": 0,
        "voice_feedback_selected_count": 0,
        "voice_feedback_dismissed_count": 0,
        "same_book_voice_reuse": False,
        "same_book_voice_adjustment": 0,
        "_voice_id": voice_id,
    }


def _write_rendered_audio(*, target_wav: Path, **_: object) -> Path:
    target_wav.parent.mkdir(parents=True, exist_ok=True)
    target_wav.write_bytes(f"audio:{target_wav.name}".encode("utf-8"))
    return target_wav


def _create_job_dir(
    *,
    current_voice_selection: dict[str, object] | None = None,
    author: str = "Knuf, Andreas",
) -> Path:
    tmpdir = Path(tempfile.mkdtemp(prefix="ea-audiobook-voice-audition-"))
    job_dir = tmpdir / "job"
    chapters_dir = job_dir / "chapters"
    chapters_dir.mkdir(parents=True, exist_ok=True)
    chapter_text = _sample_chapter_text()
    text_path = chapters_dir / "001 - Kapitel.txt"
    text_path.write_text(chapter_text + "\n", encoding="utf-8")
    metadata = audiobook_epub_pipeline.EpubMetadata(
        title="Widerstand zwecklos",
        author=author,
        language="de",
        source_filename="widerstand-zwecklos.epub",
        source_sha256="source-sha",
    )
    chapter = audiobook_epub_pipeline.EpubChapter(
        index=1,
        title="Kapitel 1",
        source_href="chapter-001.xhtml",
        text_path=text_path.name,
        audio_filename="001 - Kapitel.wav",
        char_count=len(chapter_text),
        sha256="chapter-sha",
    )
    payload = {
        "contract_name": audiobook_epub_pipeline.CONTRACT_NAME,
        "job_id": "test-job",
        "status": "chapters_extracted",
        "created_at": "2026-06-29T00:00:00Z",
        "updated_at": "2026-06-29T00:00:00Z",
        "principal_id": "test-principal",
        "source": {
            "kind": "epub",
            "source_filename": metadata.source_filename,
            "source_sha256": metadata.source_sha256,
            "source_epub": "",
            "rights_basis": "operator_supplied_epub",
        },
        "telegram": {},
        "storage": {
            "job_dir": str(job_dir),
            "source_epub": "",
            "chapters_dir": str(chapters_dir),
            "audio_dir": str(job_dir / "audio"),
            "output_dir": str(job_dir / "output"),
        },
        "metadata": asdict(metadata),
        "chapters": [asdict(chapter)],
        "totals": {"chapter_count": 1, "char_count": len(chapter_text)},
        "provider": {
            "preferred": "unmixr_ai",
            "external_tts_enabled": True,
            "unmixr_auto_render_enabled": True,
            "raw_book_text_leaves_ea": True,
            "voice_selection": dict(current_voice_selection or {}),
        },
        "eta": {},
        "next_action": "render_chapter_audio",
    }
    audiobook_epub_pipeline._write_job(job_dir, payload)  # noqa: SLF001
    return job_dir


def _private_voice_candidate(job_dir: Path, *, token: str, row: dict[str, object]) -> dict[str, object]:
    sample_dir = audiobook_epub_pipeline._voice_audition_dir(job_dir) / "samples"  # noqa: SLF001
    sample_dir.mkdir(parents=True, exist_ok=True)
    sample_path = sample_dir / f"{token}.wav"
    sample_path.write_bytes(f"audio:{token}".encode("utf-8"))
    public = audiobook_epub_pipeline._safe_public_voice_candidate(dict(row), token=token, sample_path=sample_path)  # noqa: SLF001
    return {
        "candidate_key": str(row.get("preset_key") or ""),
        "voice_id": str(row.get("_voice_id") or ""),
        "voice_id_sha256": str(row.get("voice_id_sha256") or ""),
        "sample_path": str(sample_path),
        "public": public,
    }


def test_prepare_audiobook_voice_audition_keeps_partial_author_gender_matches() -> None:
    job_dir = _create_job_dir()
    ranking = {
        "status": "ranked",
        "profile": {
            "language": "de",
            "title": "Widerstand zwecklos",
            "author": "Knuf, Andreas",
            "author_gender_signal": "male",
            "topic": "technical nonfiction",
            "dialogue_ratio": 0.11,
            "fiction_score": 1,
            "nonfiction_score": 3,
            "recommended_tags": ["nonfiction", "warm", "german"],
            "sample_sha256": "sample-sha",
        },
        "candidate_rows": [
            _candidate(preset_key="female-top", label="Seraphina", gender="female", score=70),
            _candidate(preset_key="male-one", label="Hans", gender="male", score=68),
            _candidate(preset_key="female-second", label="Amala", gender="female", score=67),
            _candidate(preset_key="male-two", label="Jurgen", gender="male", score=66),
        ],
    }
    with (
        patch.dict(os.environ, {"EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED": "1", "EA_AUDIOBOOK_UNMIXR_AUTO_RENDER": "1"}, clear=False),
        patch.object(audiobook_epub_pipeline, "_ranked_unmixr_voice_candidates", return_value=ranking),
        patch.object(audiobook_epub_pipeline, "_voice_sample_text", return_value="Kurzprobe."),
        patch.object(audiobook_epub_pipeline, "_synthesize_unmixr_with_retries", return_value=(b"audio", "audio/wav", [])),
        patch.object(audiobook_epub_pipeline, "_write_provider_audio_file", side_effect=_write_rendered_audio),
        patch.object(audiobook_epub_pipeline, "_write_current_job_receipt_best_effort"),
    ):
        job = audiobook_epub_pipeline.prepare_audiobook_voice_audition(job_dir=job_dir)

    voice_selection = dict(dict(job.get("provider") or {}).get("voice_selection") or {})
    pending_batch = [dict(item) for item in list(voice_selection.get("pending_batch") or []) if isinstance(item, dict)]
    assert [item.get("label") for item in pending_batch] == ["Hans", "Jurgen"]
    assert voice_selection.get("author_gender_preference_used") is True
    assert voice_selection.get("underfilled") is True
    assert voice_selection.get("underfilled_reason") == "voice_catalog_author_gender_underfilled"
    assert dict(voice_selection.get("book_profile") or {}).get("author_gender_signal") == "male"


def test_prepare_audiobook_voice_audition_refreshes_stale_batch_when_gender_signal_changes() -> None:
    stale_batch = [
        _candidate(preset_key="female-top", label="Seraphina", gender="female", score=70),
        _candidate(preset_key="female-second", label="Amala", gender="female", score=67),
        _candidate(preset_key="female-third", label="Gisela", gender="female", score=64),
    ]
    stale_selection = {
        "status": "waiting_user_choice",
        "book_profile": {"author_gender_signal": ""},
        "pending_candidate_keys": [str(item.get("preset_key") or "") for item in stale_batch],
        "pending_batch": stale_batch,
        "dismissed_candidate_keys": [],
        "dismissed_voice_identity_keys": [],
    }
    job_dir = _create_job_dir(current_voice_selection=stale_selection)
    ranking = {
        "status": "ranked",
        "profile": {
            "language": "de",
            "title": "Widerstand zwecklos",
            "author": "Knuf, Andreas",
            "author_gender_signal": "male",
            "topic": "technical nonfiction",
            "dialogue_ratio": 0.11,
            "fiction_score": 1,
            "nonfiction_score": 3,
            "recommended_tags": ["nonfiction", "warm", "german"],
            "sample_sha256": "sample-sha",
        },
        "candidate_rows": [
            _candidate(preset_key="female-top", label="Seraphina", gender="female", score=70),
            _candidate(preset_key="male-one", label="Hans", gender="male", score=68),
            _candidate(preset_key="female-second", label="Amala", gender="female", score=67),
            _candidate(preset_key="male-two", label="Jurgen", gender="male", score=66),
        ],
    }
    with (
        patch.dict(os.environ, {"EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED": "1", "EA_AUDIOBOOK_UNMIXR_AUTO_RENDER": "1"}, clear=False),
        patch.object(audiobook_epub_pipeline, "_ranked_unmixr_voice_candidates", return_value=ranking),
        patch.object(audiobook_epub_pipeline, "_voice_sample_text", return_value="Kurzprobe."),
        patch.object(audiobook_epub_pipeline, "_synthesize_unmixr_with_retries", return_value=(b"audio", "audio/wav", [])),
        patch.object(audiobook_epub_pipeline, "_write_provider_audio_file", side_effect=_write_rendered_audio),
        patch.object(audiobook_epub_pipeline, "_write_current_job_receipt_best_effort"),
    ):
        job = audiobook_epub_pipeline.prepare_audiobook_voice_audition(job_dir=job_dir)

    voice_selection = dict(dict(job.get("provider") or {}).get("voice_selection") or {})
    pending_batch = [dict(item) for item in list(voice_selection.get("pending_batch") or []) if isinstance(item, dict)]
    assert [item.get("label") for item in pending_batch] == ["Hans", "Jurgen"]
    assert dict(voice_selection.get("book_profile") or {}).get("author_gender_signal") == "male"
    assert voice_selection.get("status") == "waiting_user_choice"
    assert voice_selection.get("underfilled") is True
    assert voice_selection.get("underfilled_reason") == "voice_catalog_author_gender_underfilled"


def test_prepare_audiobook_voice_audition_refreshes_stale_batch_when_pending_rows_conflict_with_author_gender() -> None:
    stale_batch = [
        _candidate(preset_key="female-top", label="Seraphina", gender="female", score=70),
        _candidate(preset_key="female-second", label="Amala", gender="female", score=67),
    ]
    stale_selection = {
        "status": "waiting_user_choice",
        "book_profile": {"author_gender_signal": "male"},
        "pending_candidate_keys": [str(item.get("preset_key") or "") for item in stale_batch],
        "pending_batch": stale_batch,
        "dismissed_candidate_keys": [],
        "dismissed_voice_identity_keys": [],
    }
    job_dir = _create_job_dir(current_voice_selection=stale_selection)
    ranking = {
        "status": "ranked",
        "profile": {
            "language": "de",
            "title": "Widerstand zwecklos",
            "author": "Knuf, Andreas",
            "author_gender_signal": "male",
            "topic": "technical nonfiction",
            "dialogue_ratio": 0.11,
            "fiction_score": 1,
            "nonfiction_score": 3,
            "recommended_tags": ["nonfiction", "warm", "german"],
            "sample_sha256": "sample-sha",
        },
        "candidate_rows": [
            _candidate(preset_key="female-top", label="Seraphina", gender="female", score=70),
            _candidate(preset_key="male-one", label="Hans", gender="male", score=68),
            _candidate(preset_key="female-second", label="Amala", gender="female", score=67),
            _candidate(preset_key="male-two", label="Jurgen", gender="male", score=66),
        ],
    }
    with (
        patch.dict(os.environ, {"EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED": "1", "EA_AUDIOBOOK_UNMIXR_AUTO_RENDER": "1"}, clear=False),
        patch.object(audiobook_epub_pipeline, "_ranked_unmixr_voice_candidates", return_value=ranking),
        patch.object(audiobook_epub_pipeline, "_voice_sample_text", return_value="Kurzprobe."),
        patch.object(audiobook_epub_pipeline, "_synthesize_unmixr_with_retries", return_value=(b"audio", "audio/wav", [])),
        patch.object(audiobook_epub_pipeline, "_write_provider_audio_file", side_effect=_write_rendered_audio),
        patch.object(audiobook_epub_pipeline, "_write_current_job_receipt_best_effort"),
    ):
        job = audiobook_epub_pipeline.prepare_audiobook_voice_audition(job_dir=job_dir)

    voice_selection = dict(dict(job.get("provider") or {}).get("voice_selection") or {})
    pending_batch = [dict(item) for item in list(voice_selection.get("pending_batch") or []) if isinstance(item, dict)]
    assert [item.get("label") for item in pending_batch] == ["Hans", "Jurgen"]
    assert dict(voice_selection.get("book_profile") or {}).get("author_gender_signal") == "male"
    assert voice_selection.get("status") == "waiting_user_choice"
    assert voice_selection.get("underfilled") is True
    assert voice_selection.get("underfilled_reason") == "voice_catalog_author_gender_underfilled"


def test_prepare_audiobook_voice_audition_underfills_instead_of_reusing_duplicate_audio() -> None:
    job_dir = _create_job_dir()
    ranking = {
        "status": "ranked",
        "profile": {
            "language": "de",
            "title": "Widerstand zwecklos",
            "author": "Knuf, Andreas",
            "author_gender_signal": "male",
            "topic": "technical nonfiction",
            "dialogue_ratio": 0.11,
            "fiction_score": 1,
            "nonfiction_score": 3,
            "recommended_tags": ["nonfiction", "warm", "german"],
            "sample_sha256": "sample-sha",
        },
        "candidate_rows": [
            _candidate(preset_key="female-top", label="Seraphina", gender="female", score=70),
            _candidate(preset_key="male-one", label="Hans", gender="male", score=68),
            _candidate(preset_key="male-two", label="Dieter", gender="male", score=66),
        ],
    }

    def _write_audio_bytes(*, audio_bytes: bytes, target_wav: Path, **_: object) -> Path:
        target_wav.parent.mkdir(parents=True, exist_ok=True)
        target_wav.write_bytes(audio_bytes)
        return target_wav

    def _fake_synthesize(*, voice_id: str, **_: object) -> tuple[bytes, str, list[str]]:
        if voice_id in {"voice-male-one", "voice-male-two"}:
            return (b"duplicate-audio", "audio/wav", [])
        raise AssertionError(f"unexpected voice id: {voice_id}")

    with (
        patch.dict(os.environ, {"EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED": "1", "EA_AUDIOBOOK_UNMIXR_AUTO_RENDER": "1"}, clear=False),
        patch.object(audiobook_epub_pipeline, "_ranked_unmixr_voice_candidates", return_value=ranking),
        patch.object(audiobook_epub_pipeline, "_voice_sample_text", return_value="Kurzprobe."),
        patch.object(audiobook_epub_pipeline, "_synthesize_unmixr_with_retries", side_effect=_fake_synthesize),
        patch.object(audiobook_epub_pipeline, "_write_provider_audio_file", side_effect=_write_audio_bytes),
        patch.object(audiobook_epub_pipeline, "_write_current_job_receipt_best_effort"),
    ):
        job = audiobook_epub_pipeline.prepare_audiobook_voice_audition(job_dir=job_dir)

    voice_selection = dict(dict(job.get("provider") or {}).get("voice_selection") or {})
    pending_batch = [dict(item) for item in list(voice_selection.get("pending_batch") or []) if isinstance(item, dict)]
    assert [item.get("label") for item in pending_batch] == ["Hans"]
    assert voice_selection.get("underfilled") is True
    assert voice_selection.get("sample_generation_failed_count") == 1
    assert voice_selection.get("sample_generation_failures") == [
        {
            "preset_key_sha256": hashlib.sha256("male-two".encode("utf-8")).hexdigest(),
            "reason": "duplicate_voice_sample_audio",
        }
    ]


def test_select_unmixr_voice_for_book_prefers_author_gender_match() -> None:
    job_dir = _create_job_dir()
    metadata = audiobook_epub_pipeline.EpubMetadata(
        title="Widerstand zwecklos",
        author="Knuf, Andreas",
        language="de",
        source_filename="widerstand-zwecklos.epub",
        source_sha256="source-sha",
    )
    chapter = audiobook_epub_pipeline.EpubChapter(
        index=1,
        title="Kapitel 1",
        source_href="chapter-001.xhtml",
        text_path="001 - Kapitel.txt",
        audio_filename="001 - Kapitel.wav",
        char_count=100,
        sha256="chapter-sha",
    )
    ranking = {
        "status": "ranked",
        "profile": {
            "language": "de",
            "title": "Widerstand zwecklos",
            "author": "Knuf, Andreas",
            "author_gender_signal": "male",
            "topic": "technical nonfiction",
            "dialogue_ratio": 0.11,
            "fiction_score": 1,
            "nonfiction_score": 3,
            "recommended_tags": ["nonfiction", "warm", "german"],
            "sample_sha256": "sample-sha",
        },
        "candidate_rows": [
            _candidate(preset_key="female-top", label="Seraphina", gender="female", score=70),
            _candidate(preset_key="male-one", label="Hans", gender="male", score=68),
            _candidate(preset_key="female-second", label="Amala", gender="female", score=67),
        ],
    }
    with patch.object(audiobook_epub_pipeline, "_ranked_unmixr_voice_candidates", return_value=ranking):
        selection = audiobook_epub_pipeline.select_unmixr_voice_for_book(
            metadata=metadata,
            chapters=(chapter,),
            job_dir=job_dir,
        )

    public = dict(selection.get("public") or {})
    selected = dict(public.get("selected") or {})
    assert selected.get("label") == "Hans"
    assert public.get("author_gender_preference_used") is True
    assert dict(public.get("book_profile") or {}).get("author_gender_signal") == "male"


def test_select_unmixr_voice_for_book_blocks_author_gender_fallback_by_default() -> None:
    job_dir = _create_job_dir()
    metadata = audiobook_epub_pipeline.EpubMetadata(
        title="Widerstand zwecklos",
        author="Knuf, Andreas",
        language="de",
        source_filename="widerstand-zwecklos.epub",
        source_sha256="source-sha",
    )
    chapter = audiobook_epub_pipeline.EpubChapter(
        index=1,
        title="Kapitel 1",
        source_href="chapter-001.xhtml",
        text_path="001 - Kapitel.txt",
        audio_filename="001 - Kapitel.wav",
        char_count=100,
        sha256="chapter-sha",
    )
    ranking = {
        "status": "ranked",
        "profile": {
            "language": "de",
            "title": "Widerstand zwecklos",
            "author": "Knuf, Andreas",
            "author_gender_signal": "male",
            "topic": "technical nonfiction",
            "dialogue_ratio": 0.11,
            "fiction_score": 1,
            "nonfiction_score": 3,
            "recommended_tags": ["nonfiction", "warm", "german"],
            "sample_sha256": "sample-sha",
        },
        "candidate_rows": [
            _candidate(preset_key="female-top", label="Seraphina", gender="female", score=70),
            _candidate(preset_key="female-second", label="Amala", gender="female", score=67),
        ],
    }

    with (
        patch.dict(os.environ, {"EA_AUDIOBOOK_ALLOW_AUTHOR_GENDER_FALLBACK": "0"}, clear=False),
        patch.object(audiobook_epub_pipeline, "_ranked_unmixr_voice_candidates", return_value=ranking),
    ):
        selection = audiobook_epub_pipeline.select_unmixr_voice_for_book(
            metadata=metadata,
            chapters=(chapter,),
            job_dir=job_dir,
        )

    assert selection["status"] == "blocked"
    assert selection["reason"] == "author_gender_matching_voice_missing"
    assert dict(selection.get("public") or {}).get("author_gender_preference_used") is True


def test_select_unmixr_voice_for_book_can_explicitly_allow_author_gender_fallback() -> None:
    job_dir = _create_job_dir()
    metadata = audiobook_epub_pipeline.EpubMetadata(
        title="Widerstand zwecklos",
        author="Knuf, Andreas",
        language="de",
        source_filename="widerstand-zwecklos.epub",
        source_sha256="source-sha",
    )
    chapter = audiobook_epub_pipeline.EpubChapter(
        index=1,
        title="Kapitel 1",
        source_href="chapter-001.xhtml",
        text_path="001 - Kapitel.txt",
        audio_filename="001 - Kapitel.wav",
        char_count=100,
        sha256="chapter-sha",
    )
    ranking = {
        "status": "ranked",
        "profile": {
            "language": "de",
            "title": "Widerstand zwecklos",
            "author": "Knuf, Andreas",
            "author_gender_signal": "male",
            "topic": "technical nonfiction",
            "dialogue_ratio": 0.11,
            "fiction_score": 1,
            "nonfiction_score": 3,
            "recommended_tags": ["nonfiction", "warm", "german"],
            "sample_sha256": "sample-sha",
        },
        "candidate_rows": [
            _candidate(preset_key="female-top", label="Seraphina", gender="female", score=70),
        ],
    }

    with (
        patch.dict(os.environ, {"EA_AUDIOBOOK_ALLOW_AUTHOR_GENDER_FALLBACK": "1"}, clear=False),
        patch.object(audiobook_epub_pipeline, "_ranked_unmixr_voice_candidates", return_value=ranking),
    ):
        selection = audiobook_epub_pipeline.select_unmixr_voice_for_book(
            metadata=metadata,
            chapters=(chapter,),
            job_dir=job_dir,
        )

    public = dict(selection.get("public") or {})
    selected = dict(public.get("selected") or {})
    assert selection.get("voice_id") == "voice-female-top"
    assert selected.get("label") == "Seraphina"


def test_prepare_audiobook_voice_audition_diversifies_unknown_author_gender_batch() -> None:
    job_dir = _create_job_dir(author="A. B. Example")
    ranking = {
        "status": "ranked",
        "profile": {
            "language": "de",
            "title": "Widerstand zwecklos",
            "author": "A. B. Example",
            "author_gender_signal": "",
            "topic": "technical nonfiction",
            "dialogue_ratio": 0.11,
            "fiction_score": 1,
            "nonfiction_score": 3,
            "recommended_tags": ["nonfiction", "warm", "german"],
            "sample_sha256": "sample-sha",
        },
        "candidate_rows": [
            _candidate(preset_key="female-top", label="Seraphina", gender="female", score=70),
            _candidate(preset_key="female-second", label="Amala", gender="female", score=69),
            _candidate(preset_key="female-third", label="Gisela", gender="female", score=68),
            _candidate(preset_key="male-one", label="Hans", gender="male", score=67),
        ],
    }
    with (
        patch.dict(os.environ, {"EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED": "1", "EA_AUDIOBOOK_UNMIXR_AUTO_RENDER": "1"}, clear=False),
        patch.object(audiobook_epub_pipeline, "_ranked_unmixr_voice_candidates", return_value=ranking),
        patch.object(audiobook_epub_pipeline, "_voice_sample_text", return_value="Kurzprobe."),
        patch.object(audiobook_epub_pipeline, "_synthesize_unmixr_with_retries", return_value=(b"audio", "audio/wav", [])),
        patch.object(audiobook_epub_pipeline, "_write_provider_audio_file", side_effect=_write_rendered_audio),
        patch.object(audiobook_epub_pipeline, "_write_current_job_receipt_best_effort"),
    ):
        job = audiobook_epub_pipeline.prepare_audiobook_voice_audition(job_dir=job_dir)

    voice_selection = dict(dict(job.get("provider") or {}).get("voice_selection") or {})
    pending_batch = [dict(item) for item in list(voice_selection.get("pending_batch") or []) if isinstance(item, dict)]
    assert [item.get("label") for item in pending_batch] == ["Seraphina", "Hans", "Amala"]
    assert voice_selection.get("author_gender_preference_used") is False
    assert dict(voice_selection.get("book_profile") or {}).get("author_gender_signal") == ""


def test_selected_unmixr_voice_for_job_backfills_legacy_author_gender_signal() -> None:
    current_selection = {
        "status": "selected_by_user",
        "selected": {
            "preset_key": "unmixr_seraphina_express_9827708d",
            "label": "Seraphina (Express)",
            "tags": ["audiobook", "narration", "female", "warm"],
        },
        "selected_callback_token": "callback-token-1",
        "book_profile": {"author_gender_signal": ""},
    }
    job_dir = _create_job_dir(current_voice_selection=current_selection)
    stored_job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    stored_job["render_result"] = {
        "status": "blocked",
        "voice_selection": {
            **current_selection,
            "book_profile": {"author_gender_signal": ""},
        },
    }
    (job_dir / "job.json").write_text(json.dumps(stored_job, ensure_ascii=True, indent=2), encoding="utf-8")
    private_payload = {
        "contract_name": audiobook_epub_pipeline.VOICE_AUDITION_CONTRACT_NAME,
        "job_id": "test-job",
        "updated_at": "2026-06-29T00:00:00Z",
        "candidates": {
            "callback-token-1": {
                "candidate_key": "unmixr_seraphina_express_9827708d",
                "voice_id": "voice-seraphina",
                "voice_id_sha256": hashlib.sha256(b"voice-seraphina").hexdigest(),
                "public": {
                    "preset_key": "unmixr_seraphina_express_9827708d",
                    "label": "Seraphina (Express)",
                    "tags": ["audiobook", "narration", "female", "warm"],
                },
            }
        },
    }
    audiobook_epub_pipeline._write_voice_audition_private(job_dir, private_payload)  # noqa: SLF001

    with patch.object(audiobook_epub_pipeline, "_write_current_job_receipt_best_effort") as write_receipt:
        selection = audiobook_epub_pipeline.selected_unmixr_voice_for_job(job_dir)

    public = dict(selection.get("public") or {})
    assert dict(public.get("book_profile") or {}).get("author_gender_signal") == "male"
    write_receipt.assert_called_once_with(job_dir)
    stored_job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    stored_selection = dict(dict(stored_job.get("provider") or {}).get("voice_selection") or {})
    assert dict(stored_selection.get("book_profile") or {}).get("author_gender_signal") == "male"
    render_voice_selection = dict(dict(stored_job.get("render_result") or {}).get("voice_selection") or {})
    assert dict(render_voice_selection.get("book_profile") or {}).get("author_gender_signal") == "male"


def test_selected_unmixr_voice_for_job_syncs_stale_render_result_voice_selection() -> None:
    current_selection = {
        "status": "selected_by_user",
        "selected": {
            "preset_key": "unmixr_hans_12345678",
            "label": "Hans",
            "tags": ["audiobook", "narration", "male", "warm"],
        },
        "selected_callback_token": "callback-token-2",
        "selected_candidate_key": "unmixr_hans_12345678",
        "book_profile": {"author_gender_signal": "male"},
    }
    job_dir = _create_job_dir(current_voice_selection=current_selection)
    stored_job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    stored_job["render_result"] = {
        "status": "blocked",
        "voice_selection": {
            **current_selection,
            "book_profile": {"author_gender_signal": ""},
        },
    }
    (job_dir / "job.json").write_text(json.dumps(stored_job, ensure_ascii=True, indent=2), encoding="utf-8")
    private_payload = {
        "contract_name": audiobook_epub_pipeline.VOICE_AUDITION_CONTRACT_NAME,
        "job_id": "test-job",
        "updated_at": "2026-06-29T00:00:00Z",
        "candidates": {
            "callback-token-2": {
                "candidate_key": "unmixr_hans_12345678",
                "voice_id": "voice-hans",
                "voice_id_sha256": hashlib.sha256(b"voice-hans").hexdigest(),
                "public": {
                    "preset_key": "unmixr_hans_12345678",
                    "label": "Hans",
                    "tags": ["audiobook", "narration", "male", "warm"],
                },
            }
        },
    }
    audiobook_epub_pipeline._write_voice_audition_private(job_dir, private_payload)  # noqa: SLF001

    with patch.object(audiobook_epub_pipeline, "_write_current_job_receipt_best_effort") as write_receipt:
        selection = audiobook_epub_pipeline.selected_unmixr_voice_for_job(job_dir)

    assert selection.get("status") == "selected"
    write_receipt.assert_called_once_with(job_dir)
    stored_job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    render_voice_selection = dict(dict(stored_job.get("render_result") or {}).get("voice_selection") or {})
    assert dict(render_voice_selection.get("book_profile") or {}).get("author_gender_signal") == "male"


def test_selected_unmixr_voice_for_job_keeps_waiting_replacement_choice_pending() -> None:
    current_selection = {
        "status": "waiting_user_choice",
        "reason": "selected_voice_author_gender_mismatch",
        "pending_candidate_keys": ["unmixr_hans_12345678"],
        "pending_batch": [
            {
                "preset_key": "unmixr_hans_12345678",
                "label": "Hans",
                "callback_token": "callback-token-hans",
                "tags": ["audiobook", "narration", "male", "warm"],
            }
        ],
        "book_profile": {"author_gender_signal": "male"},
    }
    job_dir = _create_job_dir(current_voice_selection=current_selection)
    stored_job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    stored_job["render_result"] = {
        "status": "waiting_voice_selection",
        "reason": "selected_voice_author_gender_mismatch",
        "voice_selection": dict(current_selection),
    }
    (job_dir / "job.json").write_text(json.dumps(stored_job, ensure_ascii=True, indent=2), encoding="utf-8")
    private_payload = {
        "contract_name": audiobook_epub_pipeline.VOICE_AUDITION_CONTRACT_NAME,
        "job_id": "test-job",
        "updated_at": "2026-06-29T00:00:00Z",
        "selected_callback_token": "callback-token-seraphina",
        "selected_candidate_key": "unmixr_seraphina_express_9827708d",
        "candidates": {
            "callback-token-seraphina": {
                "candidate_key": "unmixr_seraphina_express_9827708d",
                "voice_id": "voice-seraphina",
                "voice_id_sha256": hashlib.sha256(b"voice-seraphina").hexdigest(),
                "public": {
                    "preset_key": "unmixr_seraphina_express_9827708d",
                    "label": "Seraphina (Express)",
                    "tags": ["audiobook", "narration", "female", "warm"],
                },
            }
        },
    }
    audiobook_epub_pipeline._write_voice_audition_private(job_dir, private_payload)  # noqa: SLF001

    with patch.object(audiobook_epub_pipeline, "_write_current_job_receipt_best_effort") as write_receipt:
        selection = audiobook_epub_pipeline.selected_unmixr_voice_for_job(job_dir)

    assert selection.get("status") == "blocked"
    assert selection.get("reason") == "voice_selection_pending"
    assert selection.get("voice_id") == ""
    public = dict(selection.get("public") or {})
    assert public.get("status") == "waiting_user_choice"
    assert public.get("reason") == "selected_voice_author_gender_mismatch"
    assert [dict(item).get("label") for item in list(public.get("pending_batch") or []) if isinstance(item, dict)] == ["Hans"]
    assert dict(public.get("book_profile") or {}).get("author_gender_signal") == "male"
    assert write_receipt.call_count <= 1


def test_reopen_audiobook_voice_selection_for_author_gender_mismatch_stages_matching_replacements() -> None:
    current_selection = {
        "status": "selected_by_user",
        "selected": {
            "preset_key": "unmixr_seraphina_express_9827708d",
            "label": "Seraphina (Express)",
            "language": "de-de",
            "supported_languages": ["de-de"],
            "tags": ["audiobook", "narration", "female", "warm"],
        },
        "selected_callback_token": "callback-token-seraphina",
        "selected_candidate_key": "unmixr_seraphina_express_9827708d",
        "book_profile": {"author_gender_signal": "male"},
        "dismissed_candidate_keys": ["unmixr_jurgen_2ab157a8"],
        "replacement_candidate_keys": ["unmixr_seraphina_express_9827708d"],
    }
    job_dir = _create_job_dir(current_voice_selection=current_selection)
    stored_job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    stored_job["telegram"] = {
        "chat_id": "1354554303",
        "voice_sample_delivery": {
            "status": "sent",
            "expected_count": 1,
            "attempted_count": 1,
            "sent_count": 1,
            "failed_count": 0,
            "skipped_count": 0,
            "reason": "",
            "reasons": [],
            "token_sha256": [hashlib.sha256(b"callback-token-seraphina").hexdigest()],
            "samples": [],
            "updated_at": "2026-06-29T00:00:00Z",
        },
    }
    (job_dir / "job.json").write_text(json.dumps(stored_job, ensure_ascii=True, indent=2), encoding="utf-8")
    private_payload = {
        "contract_name": audiobook_epub_pipeline.VOICE_AUDITION_CONTRACT_NAME,
        "job_id": "test-job",
        "selected_callback_token": "callback-token-seraphina",
        "selected_candidate_key": "unmixr_seraphina_express_9827708d",
        "updated_at": "2026-06-29T00:00:00Z",
        "candidates": {
            "callback-token-seraphina": _private_voice_candidate(
                job_dir,
                token="callback-token-seraphina",
                row=_candidate(
                    preset_key="unmixr_seraphina_express_9827708d",
                    label="Seraphina (Express)",
                    gender="female",
                    score=70,
                ),
            ),
            "callback-token-hans": _private_voice_candidate(
                job_dir,
                token="callback-token-hans",
                row=_candidate(
                    preset_key="unmixr_hans_84ea27fb",
                    label="Hans",
                    gender="male",
                    score=68,
                ),
            ),
            "callback-token-jurgen": _private_voice_candidate(
                job_dir,
                token="callback-token-jurgen",
                row=_candidate(
                    preset_key="unmixr_jurgen_2ab157a8",
                    label="Jurgen",
                    gender="male",
                    score=66,
                ),
            ),
        },
    }
    audiobook_epub_pipeline._write_voice_audition_private(job_dir, private_payload)  # noqa: SLF001

    with patch.object(audiobook_epub_pipeline, "_write_current_job_receipt_best_effort"):
        reopened_job = audiobook_epub_pipeline.reopen_audiobook_voice_selection_for_author_gender_mismatch(job_dir=job_dir)

    voice_selection = dict(dict(reopened_job.get("provider") or {}).get("voice_selection") or {})
    pending_batch = [dict(item) for item in list(voice_selection.get("pending_batch") or []) if isinstance(item, dict)]
    assert reopened_job.get("status") == "waiting_voice_selection"
    assert voice_selection.get("reason") == "selected_voice_author_gender_mismatch"
    assert [item.get("label") for item in pending_batch] == ["Hans"]
    assert voice_selection.get("replacement_candidate_keys") == ["unmixr_hans_84ea27fb"]
    assert voice_selection.get("voice_author_gender_override_by_user") is False
    delivery = dict(reopened_job.get("telegram") or {}).get("voice_sample_delivery") or {}
    assert delivery.get("status") == "not_attempted"
    assert delivery.get("expected_count") == 1
    assert delivery.get("attempted_count") == 0
    assert delivery.get("sent_count") == 0
    private_after = audiobook_epub_pipeline._load_voice_audition_private(job_dir)  # noqa: SLF001
    assert private_after.get("selected_callback_token") == ""
    assert private_after.get("selected_candidate_key") == ""


def test_apply_audiobook_voice_audition_action_marks_explicit_author_gender_override_when_user_keeps_mismatched_voice() -> None:
    current_selection = {
        "status": "selected_by_user",
        "selected": {
            "preset_key": "unmixr_seraphina_express_9827708d",
            "label": "Seraphina (Express)",
            "language": "de-de",
            "supported_languages": ["de-de"],
            "tags": ["audiobook", "narration", "female", "warm"],
        },
        "selected_callback_token": "callback-token-seraphina",
        "selected_candidate_key": "unmixr_seraphina_express_9827708d",
        "book_profile": {"author_gender_signal": "male"},
    }
    job_dir = _create_job_dir(current_voice_selection=current_selection)
    private_payload = {
        "contract_name": audiobook_epub_pipeline.VOICE_AUDITION_CONTRACT_NAME,
        "job_id": "test-job",
        "updated_at": "2026-06-29T00:00:00Z",
        "candidates": {
            "callback-token-seraphina": _private_voice_candidate(
                job_dir,
                token="callback-token-seraphina",
                row=_candidate(
                    preset_key="unmixr_seraphina_express_9827708d",
                    label="Seraphina (Express)",
                    gender="female",
                    score=70,
                ),
            ),
            "callback-token-hans": _private_voice_candidate(
                job_dir,
                token="callback-token-hans",
                row=_candidate(
                    preset_key="unmixr_hans_84ea27fb",
                    label="Hans",
                    gender="male",
                    score=68,
                ),
            ),
        },
    }
    audiobook_epub_pipeline._write_voice_audition_private(job_dir, private_payload)  # noqa: SLF001
    with patch.object(audiobook_epub_pipeline, "_write_current_job_receipt_best_effort"):
        audiobook_epub_pipeline.reopen_audiobook_voice_selection_for_author_gender_mismatch(job_dir=job_dir)

    selected_candidate = dict(private_payload["candidates"]["callback-token-seraphina"])
    with (
        patch.object(audiobook_epub_pipeline, "unmixr_auto_render_enabled", return_value=False),
        patch.object(audiobook_epub_pipeline, "record_audiobook_voice_feedback", return_value={}),
        patch.object(
            audiobook_epub_pipeline,
            "_find_voice_audition_job_by_token",
            return_value=(job_dir, private_payload, selected_candidate),
        ),
    ):
        job = audiobook_epub_pipeline.apply_audiobook_voice_audition_action(
            callback_token="callback-token-seraphina",
            action="use",
        )

    voice_selection = dict(dict(job.get("provider") or {}).get("voice_selection") or {})
    assert voice_selection.get("status") == "selected_by_user"
    assert voice_selection.get("voice_author_gender_override_by_user") is True
    mismatch = audiobook_epub_pipeline._selected_voice_author_gender_mismatch(  # noqa: SLF001
        job_dir=job_dir,
        metadata=audiobook_epub_pipeline._metadata_from_job(job),  # noqa: SLF001
        voice_selection={"public": voice_selection},
    )
    assert mismatch == {}


def test_recover_audiobook_job_without_external_side_effects_reopens_stale_author_gender_mismatch() -> None:
    current_selection = {
        "status": "selected_by_user",
        "selected": {
            "preset_key": "unmixr_seraphina_express_9827708d",
            "label": "Seraphina (Express)",
            "language": "de-de",
            "supported_languages": ["de-de"],
            "tags": ["audiobook", "narration", "female", "warm"],
        },
        "selected_callback_token": "callback-token-seraphina",
        "selected_candidate_key": "unmixr_seraphina_express_9827708d",
        "book_profile": {"author_gender_signal": "male"},
    }
    job_dir = _create_job_dir(current_voice_selection=current_selection)
    stored_job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    stored_job["status"] = "blocked_external_tts"
    stored_job["render_result"] = {
        "status": "blocked",
        "reason": "Input too long. Please limit your input to under 2000 characters.",
        "voice_selection": dict(current_selection),
    }
    (job_dir / "job.json").write_text(json.dumps(stored_job, ensure_ascii=True, indent=2), encoding="utf-8")
    private_payload = {
        "contract_name": audiobook_epub_pipeline.VOICE_AUDITION_CONTRACT_NAME,
        "job_id": "test-job",
        "updated_at": "2026-06-29T00:00:00Z",
        "candidates": {
            "callback-token-seraphina": _private_voice_candidate(
                job_dir,
                token="callback-token-seraphina",
                row=_candidate(
                    preset_key="unmixr_seraphina_express_9827708d",
                    label="Seraphina (Express)",
                    gender="female",
                    score=70,
                ),
            ),
            "callback-token-hans": _private_voice_candidate(
                job_dir,
                token="callback-token-hans",
                row=_candidate(
                    preset_key="unmixr_hans_84ea27fb",
                    label="Hans",
                    gender="male",
                    score=68,
                ),
            ),
        },
    }
    audiobook_epub_pipeline._write_voice_audition_private(job_dir, private_payload)  # noqa: SLF001

    with patch.object(audiobook_epub_pipeline, "_write_current_job_receipt_best_effort"):
        recovery = audiobook_epub_pipeline.recover_audiobook_job_without_external_side_effects(job_dir)

    recovered_job = dict(recovery.get("job") or {})
    voice_selection = dict(dict(recovered_job.get("provider") or {}).get("voice_selection") or {})
    pending_batch = [dict(item) for item in list(voice_selection.get("pending_batch") or []) if isinstance(item, dict)]
    assert recovery.get("recovered") is True
    assert recovery.get("reason") == "selected_voice_author_gender_mismatch"
    assert recovered_job.get("status") == "waiting_voice_selection"
    assert recovered_job.get("next_action") == "choose_audiobook_voice"
    assert voice_selection.get("reason") == "selected_voice_author_gender_mismatch"
    assert [item.get("label") for item in pending_batch] == ["Hans"]


def test_resume_due_audiobook_jobs_counts_safe_recovery_before_skip() -> None:
    current_selection = {
        "status": "selected_by_user",
        "selected": {
            "preset_key": "unmixr_seraphina_express_9827708d",
            "label": "Seraphina (Express)",
            "language": "de-de",
            "supported_languages": ["de-de"],
            "tags": ["audiobook", "narration", "female", "warm"],
        },
        "selected_callback_token": "callback-token-seraphina",
        "selected_candidate_key": "unmixr_seraphina_express_9827708d",
        "book_profile": {"author_gender_signal": "male"},
    }
    job_dir = _create_job_dir(current_voice_selection=current_selection)
    root_dir = job_dir.parent
    stored_job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    stored_job["status"] = "blocked_external_tts"
    stored_job["render_result"] = {
        "status": "blocked",
        "reason": "Input too long. Please limit your input to under 2000 characters.",
        "voice_selection": dict(current_selection),
    }
    stored_job["updated_at"] = "2026-06-29T00:00:00Z"
    (job_dir / "job.json").write_text(json.dumps(stored_job, ensure_ascii=True, indent=2), encoding="utf-8")
    private_payload = {
        "contract_name": audiobook_epub_pipeline.VOICE_AUDITION_CONTRACT_NAME,
        "job_id": "test-job",
        "updated_at": "2026-06-29T00:00:00Z",
        "candidates": {
            "callback-token-seraphina": _private_voice_candidate(
                job_dir,
                token="callback-token-seraphina",
                row=_candidate(
                    preset_key="unmixr_seraphina_express_9827708d",
                    label="Seraphina (Express)",
                    gender="female",
                    score=70,
                ),
            ),
            "callback-token-hans": _private_voice_candidate(
                job_dir,
                token="callback-token-hans",
                row=_candidate(
                    preset_key="unmixr_hans_84ea27fb",
                    label="Hans",
                    gender="male",
                    score=68,
                ),
            ),
        },
    }
    audiobook_epub_pipeline._write_voice_audition_private(job_dir, private_payload)  # noqa: SLF001

    with (
        patch.dict(
            os.environ,
            {
                "EA_AUDIOBOOK_JOBS_ROOT": str(root_dir),
                "EA_AUDIOBOOK_JOB_DISCOVERY_ROOTS": str(root_dir),
            },
            clear=False,
        ),
        patch.object(audiobook_epub_pipeline, "_write_current_job_receipt_best_effort"),
    ):
        result = audiobook_epub_pipeline.resume_due_audiobook_jobs(notify_telegram=False, limit=1)

    assert result["safe_recovered"] == 1
    assert result["safe_recovery_reasons"] == {"selected_voice_author_gender_mismatch": 1}
    assert result["attempted"] == 0
    assert result["skip_reasons"]["waiting_voice_selection"] == 1


def test_resume_due_audiobook_jobs_notifies_waiting_voice_selection_when_sample_delivery_is_pending() -> None:
    current_selection = {
        "status": "selected_by_user",
        "selected": {
            "preset_key": "unmixr_seraphina_express_9827708d",
            "label": "Seraphina (Express)",
            "language": "de-de",
            "supported_languages": ["de-de"],
            "tags": ["audiobook", "narration", "female", "warm"],
        },
        "selected_callback_token": "callback-token-seraphina",
        "selected_candidate_key": "unmixr_seraphina_express_9827708d",
        "book_profile": {"author_gender_signal": "male"},
    }
    job_dir = _create_job_dir(current_voice_selection=current_selection)
    root_dir = job_dir.parent
    stored_job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    stored_job["status"] = "waiting_voice_selection"
    stored_job["telegram"] = {
        "chat_id": "42",
        "message_id": "99",
        "voice_sample_delivery": {"status": "not_attempted", "expected_count": 2, "sent_count": 0},
    }
    stored_job["provider"]["voice_selection"] = {
        "status": "waiting_user_choice",
        "reason": "selected_voice_author_gender_mismatch",
        "book_profile": {"author_gender_signal": "male"},
        "pending_candidate_keys": ["unmixr_hans_84ea27fb", "unmixr_dieter_7f88185d"],
        "pending_batch": [
            {
                **_private_voice_candidate(
                    job_dir,
                    token="callback-token-hans",
                    row=_candidate(
                        preset_key="unmixr_hans_84ea27fb",
                        label="Hans",
                        gender="male",
                        score=68,
                    ),
                )["public"],
            },
            {
                **_private_voice_candidate(
                    job_dir,
                    token="callback-token-dieter",
                    row=_candidate(
                        preset_key="unmixr_dieter_7f88185d",
                        label="Dieter",
                        gender="male",
                        score=67,
                    ),
                )["public"],
            },
        ],
    }
    (job_dir / "job.json").write_text(json.dumps(stored_job, ensure_ascii=True, indent=2), encoding="utf-8")

    sent: list[dict[str, object]] = []

    def _fake_send(*, job: dict[str, object], text: str) -> dict[str, object]:
        sent.append({"job_id": str(job.get("job_id") or ""), "text": text})
        return {"status": "sent", "message_id": 77}

    with (
        patch.dict(
            os.environ,
            {
                "EA_AUDIOBOOK_JOBS_ROOT": str(root_dir),
                "EA_AUDIOBOOK_JOB_DISCOVERY_ROOTS": str(root_dir),
            },
            clear=False,
        ),
        patch.object(audiobook_epub_pipeline, "_send_telegram_audiobook_status", side_effect=_fake_send),
        patch.object(audiobook_epub_pipeline, "_write_current_job_receipt_best_effort"),
    ):
        result = audiobook_epub_pipeline.resume_due_audiobook_jobs(notify_telegram=True, limit=1)

    assert sent and sent[0]["job_id"] == "test-job"
    assert result["attempted"] == 0
    assert result["skip_reasons"]["waiting_voice_selection"] == 1
    assert result["notifications"][0]["job_id"] == "test-job"
    assert result["notifications"][0]["notification"]["status"] == "sent"


def test_telegram_status_needs_voice_sample_delivery_when_current_pending_tokens_changed() -> None:
    job_dir = _create_job_dir()
    stale_public = _private_voice_candidate(
        job_dir,
        token="callback-token-seraphina",
        row=_candidate(
            preset_key="unmixr_seraphina_express_9827708d",
            label="Seraphina (Express)",
            gender="female",
            score=70,
        ),
    )["public"]
    replacement_public = _private_voice_candidate(
        job_dir,
        token="callback-token-dieter",
        row=_candidate(
            preset_key="unmixr_dieter_7f88185d",
            label="Dieter",
            gender="male",
            score=67,
        ),
    )["public"]
    stored_job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    stored_job["status"] = "waiting_voice_selection"
    stored_job["telegram"] = {
        "chat_id": "42",
        "voice_sample_delivery": {
            "status": "sent",
            "expected_count": 1,
            "attempted_count": 1,
            "sent_count": 1,
            "failed_count": 0,
            "skipped_count": 0,
            "reason": "",
            "reasons": [],
            "token_sha256": [hashlib.sha256(b"callback-token-seraphina").hexdigest()],
            "samples": [
                {
                    "token_sha256": hashlib.sha256(b"callback-token-seraphina").hexdigest(),
                    "status": "sent",
                    "media_message_id_sha256": "",
                    "button_message_id_sha256": "",
                    "button_count": 2,
                    "buttons_fallback": False,
                    "control_kind": "inline_keyboard",
                }
            ],
        },
    }
    stored_job["provider"]["voice_selection"] = {
        "status": "waiting_user_choice",
        "reason": "selected_voice_author_gender_mismatch",
        "book_profile": {"author_gender_signal": "male"},
        "pending_candidate_keys": ["unmixr_dieter_7f88185d"],
        "pending_batch": [replacement_public],
    }
    (job_dir / "job.json").write_text(json.dumps(stored_job, ensure_ascii=True, indent=2), encoding="utf-8")

    current_job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    assert audiobook_epub_pipeline._telegram_status_needs_voice_sample_delivery(current_job) is True  # noqa: SLF001


def test_record_audiobook_voice_sample_delivery_merges_current_pending_coverage() -> None:
    job_dir = _create_job_dir()
    hans_public = _private_voice_candidate(
        job_dir,
        token="callback-token-hans",
        row=_candidate(
            preset_key="unmixr_hans_84ea27fb",
            label="Hans",
            gender="male",
            score=68,
        ),
    )["public"]
    dieter_public = _private_voice_candidate(
        job_dir,
        token="callback-token-dieter",
        row=_candidate(
            preset_key="unmixr_dieter_7f88185d",
            label="Dieter",
            gender="male",
            score=67,
        ),
    )["public"]
    stored_job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    stored_job["status"] = "waiting_voice_selection"
    stored_job["telegram"] = {
        "chat_id": "42",
        "voice_sample_delivery": {
            "status": "sent",
            "expected_count": 2,
            "attempted_count": 1,
            "sent_count": 1,
            "failed_count": 0,
            "skipped_count": 0,
            "reason": "",
            "reasons": [],
            "token_sha256": [hashlib.sha256(b"callback-token-hans").hexdigest()],
            "samples": [
                {
                    "token_sha256": hashlib.sha256(b"callback-token-hans").hexdigest(),
                    "status": "sent",
                    "media_message_id_sha256": "",
                    "button_message_id_sha256": "",
                    "button_count": 2,
                    "buttons_fallback": False,
                    "control_kind": "inline_keyboard",
                }
            ],
        },
    }
    stored_job["provider"]["voice_selection"] = {
        "status": "waiting_user_choice",
        "reason": "selected_voice_author_gender_mismatch",
        "book_profile": {"author_gender_signal": "male"},
        "pending_candidate_keys": ["unmixr_hans_84ea27fb", "unmixr_dieter_7f88185d"],
        "pending_batch": [hans_public, dieter_public],
    }
    (job_dir / "job.json").write_text(json.dumps(stored_job, ensure_ascii=True, indent=2), encoding="utf-8")

    with patch.object(audiobook_epub_pipeline, "_write_current_job_receipt_best_effort"):
        updated_job = audiobook_epub_pipeline.record_audiobook_voice_sample_delivery(
            job=stored_job,
            sample_receipts=[
                {
                    "token": "callback-token-dieter",
                    "status": "sent",
                    "reason": "",
                    "media_message_id_sha256": "message-dieter",
                    "button_message_id_sha256": "",
                    "button_count": 2,
                    "buttons_fallback": False,
                    "control_kind": "inline_keyboard",
                }
            ],
        )

    delivery = dict(dict(updated_job.get("telegram") or {}).get("voice_sample_delivery") or {})
    assert delivery["status"] == "sent"
    assert delivery["expected_count"] == 2
    assert delivery["sent_count"] == 2
    assert set(delivery["token_sha256"]) == {
        hashlib.sha256(b"callback-token-hans").hexdigest(),
        hashlib.sha256(b"callback-token-dieter").hexdigest(),
    }


def test_send_telegram_audiobook_status_only_delivers_uncovered_voice_samples() -> None:
    job_dir = _create_job_dir()
    hans_public = _private_voice_candidate(
        job_dir,
        token="callback-token-hans",
        row=_candidate(
            preset_key="unmixr_hans_84ea27fb",
            label="Hans",
            gender="male",
            score=68,
        ),
    )["public"]
    dieter_public = _private_voice_candidate(
        job_dir,
        token="callback-token-dieter",
        row=_candidate(
            preset_key="unmixr_dieter_7f88185d",
            label="Dieter",
            gender="male",
            score=67,
        ),
    )["public"]
    stored_job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    stored_job["status"] = "waiting_voice_selection"
    stored_job["telegram"] = {
        "chat_id": "42",
        "message_id": "99",
        "voice_sample_delivery": {
            "status": "partial",
            "expected_count": 2,
            "attempted_count": 1,
            "sent_count": 1,
            "failed_count": 0,
            "skipped_count": 0,
            "reason": "",
            "reasons": [],
            "token_sha256": [hashlib.sha256(b"callback-token-hans").hexdigest()],
            "samples": [
                {
                    "token_sha256": hashlib.sha256(b"callback-token-hans").hexdigest(),
                    "status": "sent",
                    "media_message_id_sha256": "",
                    "button_message_id_sha256": "",
                    "button_count": 2,
                    "buttons_fallback": False,
                    "control_kind": "inline_keyboard",
                }
            ],
        },
    }
    stored_job["provider"]["voice_selection"] = {
        "status": "waiting_user_choice",
        "reason": "selected_voice_author_gender_mismatch",
        "book_profile": {"author_gender_signal": "male"},
        "pending_candidate_keys": ["unmixr_hans_84ea27fb", "unmixr_dieter_7f88185d"],
        "pending_batch": [hans_public, dieter_public],
    }
    (job_dir / "job.json").write_text(json.dumps(stored_job, ensure_ascii=True, indent=2), encoding="utf-8")

    requests_seen: list[str] = []

    class _FakeResponse:
        def __init__(self, payload: dict[str, object]) -> None:
            self._payload = payload

        def read(self) -> bytes:
            return json.dumps(self._payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    def _fake_urlopen(request, timeout=0):  # noqa: ANN001
        requests_seen.append(request.full_url)
        if request.full_url.endswith("/sendAudio"):
            audio_count = sum(1 for url in requests_seen if url.endswith("/sendAudio"))
            return _FakeResponse({"ok": True, "result": {"message_id": 100 + audio_count}})
        if request.full_url.endswith("/sendMessage"):
            return _FakeResponse({"ok": True, "result": {"message_id": 999}})
        raise AssertionError(request.full_url)

    with (
        patch.dict(
            os.environ,
            {
                "EA_TELEGRAM_BOT_TOKEN": "test-bot-token",
                "EA_TELEGRAM_CALLBACK_SECRET": "test-callback-secret",
            },
            clear=False,
        ),
        patch.object(audiobook_epub_pipeline.urllib.request, "urlopen", side_effect=_fake_urlopen),
        patch.object(audiobook_epub_pipeline, "_write_current_job_receipt_best_effort"),
    ):
        notification = audiobook_epub_pipeline._send_telegram_audiobook_status(  # noqa: SLF001
            job=stored_job,
            text=audiobook_epub_pipeline.telegram_epub_reply_text(stored_job),
        )

    assert [url.rsplit("/", 1)[-1] for url in requests_seen].count("sendAudio") == 1
    assert notification["status"] == "sent"
    delivery = dict(notification.get("voice_sample_delivery") or {})
    assert delivery["status"] == "sent"
    assert delivery["expected_count"] == 2
    assert delivery["sent_count"] == 2
    assert set(delivery["token_sha256"]) == {
        hashlib.sha256(b"callback-token-hans").hexdigest(),
        hashlib.sha256(b"callback-token-dieter").hexdigest(),
    }


def test_send_telegram_audiobook_status_delivers_reopened_replacement_samples() -> None:
    current_selection = {
        "status": "selected_by_user",
        "selected": {
            "preset_key": "unmixr_seraphina_express_9827708d",
            "label": "Seraphina (Express)",
            "language": "de-de",
            "supported_languages": ["de-de"],
            "tags": ["audiobook", "narration", "female", "warm"],
        },
        "selected_callback_token": "callback-token-seraphina",
        "selected_candidate_key": "unmixr_seraphina_express_9827708d",
        "book_profile": {"author_gender_signal": "male"},
    }
    job_dir = _create_job_dir(current_voice_selection=current_selection)
    stored_job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    stored_job["status"] = "blocked_external_tts"
    stored_job["telegram"] = {"chat_id": "42", "message_id": "99"}
    stored_job["render_result"] = {
        "status": "blocked",
        "reason": "Input too long. Please limit your input to under 2000 characters.",
        "voice_selection": dict(current_selection),
    }
    stored_job["updated_at"] = "2026-06-29T00:00:00Z"
    (job_dir / "job.json").write_text(json.dumps(stored_job, ensure_ascii=True, indent=2), encoding="utf-8")
    private_payload = {
        "contract_name": audiobook_epub_pipeline.VOICE_AUDITION_CONTRACT_NAME,
        "job_id": "test-job",
        "updated_at": "2026-06-29T00:00:00Z",
        "candidates": {
            "callback-token-seraphina": _private_voice_candidate(
                job_dir,
                token="callback-token-seraphina",
                row=_candidate(
                    preset_key="unmixr_seraphina_express_9827708d",
                    label="Seraphina (Express)",
                    gender="female",
                    score=70,
                ),
            ),
            "callback-token-hans": _private_voice_candidate(
                job_dir,
                token="callback-token-hans",
                row=_candidate(
                    preset_key="unmixr_hans_84ea27fb",
                    label="Hans",
                    gender="male",
                    score=68,
                ),
            ),
            "callback-token-dieter": _private_voice_candidate(
                job_dir,
                token="callback-token-dieter",
                row=_candidate(
                    preset_key="unmixr_dieter_7f88185d",
                    label="Dieter",
                    gender="male",
                    score=67,
                ),
            ),
        },
    }
    audiobook_epub_pipeline._write_voice_audition_private(job_dir, private_payload)  # noqa: SLF001

    with patch.object(audiobook_epub_pipeline, "_write_current_job_receipt_best_effort"):
        recovery = audiobook_epub_pipeline.recover_audiobook_job_without_external_side_effects(job_dir)

    recovered_job = dict(recovery.get("job") or {})
    assert recovery.get("recovered") is True
    assert recovery.get("reason") == "selected_voice_author_gender_mismatch"
    expected_sample_count = len(audiobook_epub_pipeline.audiobook_voice_audition_sample_messages(recovered_job))

    requests_seen: list[tuple[str, bytes]] = []

    class _FakeResponse:
        def __init__(self, payload: dict[str, object]) -> None:
            self._payload = payload

        def read(self) -> bytes:
            return json.dumps(self._payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    def _fake_urlopen(request, timeout=0):  # noqa: ANN001
        requests_seen.append((request.full_url, bytes(request.data or b"")))
        if request.full_url.endswith("/sendAudio"):
            audio_count = sum(1 for url, _ in requests_seen if url.endswith("/sendAudio"))
            return _FakeResponse({"ok": True, "result": {"message_id": 100 + audio_count}})
        if request.full_url.endswith("/sendMessage"):
            return _FakeResponse({"ok": True, "result": {"message_id": 999}})
        raise AssertionError(request.full_url)

    with (
        patch.dict(
            os.environ,
            {
                "EA_TELEGRAM_BOT_TOKEN": "test-bot-token",
                "EA_TELEGRAM_CALLBACK_SECRET": "test-callback-secret",
            },
            clear=False,
        ),
        patch.object(audiobook_epub_pipeline.urllib.request, "urlopen", side_effect=_fake_urlopen),
    ):
        notification = audiobook_epub_pipeline._send_telegram_audiobook_status(  # noqa: SLF001
            job=recovered_job,
            text=audiobook_epub_pipeline.telegram_epub_reply_text(recovered_job),
        )

    request_kinds = [url.rsplit("/", 1)[-1] for url, _ in requests_seen]
    assert request_kinds[:-1] == ["sendAudio"] * expected_sample_count
    assert request_kinds[-1] == "sendMessage"
    assert notification["status"] == "sent"
    delivery = dict(notification.get("voice_sample_delivery") or {})
    assert delivery["status"] == "sent"
    assert delivery["sent_count"] == expected_sample_count
    message_body = urllib.parse.parse_qs(requests_seen[-1][1].decode("utf-8"))
    assert message_body["chat_id"] == ["42"]
    updated_job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    updated_delivery = dict(dict(updated_job.get("telegram") or {}).get("voice_sample_delivery") or {})
    assert updated_delivery["status"] == "sent"
    assert updated_delivery["expected_count"] == expected_sample_count
    assert updated_delivery["sent_count"] == expected_sample_count


def test_infer_author_gender_handles_common_english_and_international_names() -> None:
    assert audiobook_epub_pipeline._infer_author_gender("Stephen King") == "male"  # noqa: SLF001
    assert audiobook_epub_pipeline._infer_author_gender("James Clear") == "male"  # noqa: SLF001
    assert audiobook_epub_pipeline._infer_author_gender("Yuval Noah Harari") == "male"  # noqa: SLF001
    assert audiobook_epub_pipeline._infer_author_gender("Le Guin, Ursula") == "female"  # noqa: SLF001
    assert audiobook_epub_pipeline._infer_author_gender("Meyer, Hans-Peter") == "male"  # noqa: SLF001


def test_voice_preset_from_unmixr_row_infers_gender_from_character_name_when_missing() -> None:
    male = audiobook_epub_pipeline._voice_preset_from_unmixr_row(  # noqa: SLF001
        {
            "uuid": "voice-hans",
            "character": "Hans",
            "language": "de-DE",
            "supported_locales": ["de-DE"],
            "description": "Warm audiobook voice",
        },
        use_case="audiobook-voices",
        index=1,
    )
    female = audiobook_epub_pipeline._voice_preset_from_unmixr_row(  # noqa: SLF001
        {
            "uuid": "voice-seraphina",
            "character": "Seraphina",
            "language": "en-US",
            "supported_locales": ["en-US"],
            "description": "Warm storytelling voice",
        },
        use_case="audiobook-voices",
        index=2,
    )

    assert male is not None
    assert female is not None
    assert "male" in male.tags
    assert "female" in female.tags


def test_load_voice_presets_from_value_infers_gender_from_label_without_explicit_tags() -> None:
    presets = audiobook_epub_pipeline._load_voice_presets_from_value(  # noqa: SLF001
        [
            {
                "voice_id": "voice-robert",
                "label": "Robert",
                "language": "en-US",
                "tags": ["audiobook", "narration", "warm"],
            }
        ],
        source="test",
    )

    assert len(presets) == 1
    assert "male" in presets[0].tags
