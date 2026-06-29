from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

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


def _create_job_dir(*, current_voice_selection: dict[str, object] | None = None) -> Path:
    tmpdir = Path(tempfile.mkdtemp(prefix="ea-audiobook-voice-audition-"))
    job_dir = tmpdir / "job"
    chapters_dir = job_dir / "chapters"
    chapters_dir.mkdir(parents=True, exist_ok=True)
    chapter_text = _sample_chapter_text()
    text_path = chapters_dir / "001 - Kapitel.txt"
    text_path.write_text(chapter_text + "\n", encoding="utf-8")
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
    assert [item.get("label") for item in pending_batch] == ["Hans", "Jurgen", "Seraphina"]
    assert voice_selection.get("author_gender_preference_used") is True
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
    assert [item.get("label") for item in pending_batch] == ["Hans", "Jurgen", "Seraphina"]
    assert dict(voice_selection.get("book_profile") or {}).get("author_gender_signal") == "male"
    assert voice_selection.get("status") == "waiting_user_choice"


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
