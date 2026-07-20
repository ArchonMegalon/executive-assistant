from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


def _load_script() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "ea" / "scripts" / "materialize_whatsapp_audiobook_live_voice_selection_shadow.py"
    spec = importlib.util.spec_from_file_location("materialize_whatsapp_audiobook_live_voice_selection_shadow", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_waiting_voice_job(job_dir: Path) -> dict[str, object]:
    from app.services import audiobook_epub_pipeline as pipeline

    job_dir.mkdir(parents=True)
    voice_id = "secret-provider-voice-id"
    voice_sha = pipeline._sha256_bytes(voice_id.encode("utf-8"))
    job = {
        "job_id": "job-wa-shadow-proof",
        "status": "waiting_voice_selection",
        "next_action": "choose_audiobook_voice",
        "metadata": {"title": "Shadow Proof Book", "author": "A. Writer", "language": "de"},
        "storage": {"job_dir": str(job_dir)},
        "provider": {
            "voice_selection": {
                "contract_name": "ea.telegram_epub_audiobook_voice_audition.v1",
                "status": "waiting_user_choice",
                "pending_candidate_keys": ["voice-one"],
                "pending_batch": [
                    {
                        "preset_key": "voice-one",
                        "callback_token": "voice-token-one",
                        "label": "Voice One",
                        "language": "de-DE",
                        "voice_id_sha256": voice_sha,
                        "sample_audio_ready": True,
                        "sample_file": "voice-token-one.wav",
                    }
                ],
                "selected": {},
                "raw_voice_ids_exposed": False,
                "sample_text_exposed": False,
            }
        },
        "whatsapp": {
            "sender_ref": "4368120864006",
            "chat_ref": "chat-ref-1",
            "session_ref": "session-1",
            "voice_sample_delivery": {"status": "sent", "sent_count": 1},
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job, indent=2, sort_keys=True), encoding="utf-8")
    pipeline._write_voice_audition_private(
        job_dir,
        {
            "contract_name": pipeline.VOICE_AUDITION_CONTRACT_NAME,
            "job_id": "job-wa-shadow-proof",
            "candidates": {
                "voice-token-one": {
                    "candidate_key": "voice-one",
                    "voice_id": voice_id,
                    "voice_id_sha256": voice_sha,
                    "public": {
                        "preset_key": "voice-one",
                        "callback_token": "voice-token-one",
                        "label": "Voice One",
                        "language": "de-DE",
                        "voice_id_sha256": voice_sha,
                        "sample_audio_ready": True,
                        "sample_file": "voice-token-one.wav",
                    },
                }
            },
        },
    )
    return job


def test_whatsapp_live_voice_selection_shadow_receipt_passes_without_mutating_source(tmp_path: Path) -> None:
    module = _load_script()
    job_dir = tmp_path / "jobs" / "job-wa-shadow-proof"
    _write_waiting_voice_job(job_dir)
    before = (job_dir / "job.json").read_text(encoding="utf-8")

    receipt = module.build_receipt(
        output_path=tmp_path / "shadow.generated.json",
        job_dir=job_dir,
        generated_at="2026-06-21T12:00:00Z",
    )

    assert receipt["contract_name"] == "ea.whatsapp_audiobook_live_voice_selection_shadow.v1"
    assert receipt["status"] == "pass"
    assert receipt["checks"]["waiting_voice_selection_job_found"] is True
    assert receipt["checks"]["shadow_callback_applied"] is True
    assert receipt["checks"]["shadow_text_fallback_ready"] is True
    assert receipt["checks"]["shadow_reached_render_action"] is True
    assert receipt["checks"]["shadow_pending_batch_cleared"] is True
    assert receipt["checks"]["live_job_unchanged"] is True
    assert receipt["shadow"]["callback_status"] == "applied"
    assert receipt["shadow"]["shadow_status"] == "voice_selected"
    assert receipt["shadow"]["shadow_next_action"] == "render_chapter_audio"
    assert receipt["shadow"]["selected_label_present"] is True
    assert receipt["shadow"]["pending_voice_count_after"] == 0
    assert receipt["text_fallback"]["status"] == "pass"
    assert receipt["text_fallback"]["use_named_action"] == "use_named"
    assert receipt["text_fallback"]["dismiss_named_action"] == "dismiss_named"
    assert receipt["text_fallback"]["dismiss_all_action"] == "dismiss_all"
    assert receipt["text_fallback"]["bare_voice_choice_resolved"] is True
    assert receipt["text_fallback"]["fallback_prompt_mentions_text_commands"] is True
    assert (job_dir / "job.json").read_text(encoding="utf-8") == before

    serialized = json.dumps(receipt, sort_keys=True)
    assert "4368120864006" not in serialized
    assert "voice-token-one" not in serialized
    assert "secret-provider-voice-id" not in serialized
    assert str(job_dir) not in serialized
    assert "Shadow Proof Book" not in serialized


def test_whatsapp_live_voice_selection_shadow_receipt_waits_without_candidate(tmp_path: Path) -> None:
    module = _load_script()

    receipt = module.build_receipt(
        output_path=tmp_path / "shadow.generated.json",
        job_dir=tmp_path / "missing-job",
        generated_at="2026-06-21T12:00:00Z",
    )

    assert receipt["status"] == "waiting"
    assert receipt["reason"] == "waiting_whatsapp_voice_selection_job_not_found"
    assert receipt["checks"]["waiting_voice_selection_job_found"] is False
    assert receipt["checks"]["shadow_text_fallback_ready"] is False
