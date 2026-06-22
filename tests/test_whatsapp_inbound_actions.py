from __future__ import annotations

import json

from app.services import whatsapp_inbound_actions


FUTURE_EXPIRY = 4102444800


def test_handle_whatsapp_audiobook_voice_callback_applies_selection(monkeypatch) -> None:
    calls: dict[str, object] = {}

    def _fake_apply_audition_action(*, callback_token: str, action: str) -> dict[str, object]:
        calls["callback_token"] = callback_token
        calls["action"] = action
        return {"job_id": "job-voice-1"}

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "voice-secret")
    monkeypatch.setattr(
        whatsapp_inbound_actions.audiobook_epub_pipeline,
        "apply_audiobook_voice_audition_action",
        _fake_apply_audition_action,
    )
    monkeypatch.setattr(
        whatsapp_inbound_actions.audiobook_epub_pipeline,
        "telegram_epub_reply_text",
        lambda job: f"voice applied for {job['job_id']}",
    )

    callback_data = whatsapp_inbound_actions.encode_whatsapp_audiobook_voice_callback(
        action="u",
        token="voice-token-1",
        sender_ref="4368120864006",
        expires_at=FUTURE_EXPIRY,
    )

    result = whatsapp_inbound_actions.handle_whatsapp_inbound_callback(
        callback_data=callback_data,
        sender_ref="4368120864006",
        message_id="wamid.voice.1",
    )

    assert result["status"] == "applied"
    assert result["kind"] == "audiobook_voice"
    assert result["action"] == "use"
    assert result["job"] == {"job_id": "job-voice-1"}
    assert result["reply_text"] == "voice applied for job-voice-1"
    assert calls == {"callback_token": "voice-token-1", "action": "use"}


def test_whatsapp_voice_reply_uses_whatsapp_delivery_state(monkeypatch) -> None:
    def _fake_apply_audition_action(*, callback_token: str, action: str) -> dict[str, object]:
        return {
            "job_id": "job-voice-1",
            "status": "waiting_voice_selection",
            "metadata": {"title": "Book", "language": "de"},
            "totals": {"chapter_count": 2, "char_count": 1000},
            "provider": {
                "voice_selection": {
                    "status": "waiting_user_choice",
                    "book_profile": {"language": "de", "topic": "nonfiction"},
                    "pending_batch": [{"label": "Voice One"}, {"label": "Voice Two"}],
                }
            },
            "telegram": {
                "voice_sample_delivery": {
                    "status": "failed",
                    "expected_count": 2,
                    "sent_count": 0,
                    "reason": "callback_encoding_failed",
                }
            },
            "whatsapp": {
                "voice_sample_delivery": {
                    "status": "sent",
                    "expected_count": 2,
                    "sent_count": 2,
                }
            },
        }

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "voice-secret")
    monkeypatch.setattr(
        whatsapp_inbound_actions.audiobook_epub_pipeline,
        "apply_audiobook_voice_audition_action",
        _fake_apply_audition_action,
    )

    callback_data = whatsapp_inbound_actions.encode_whatsapp_audiobook_voice_callback(
        action="d",
        token="voice-token-1",
        sender_ref="4368120864006",
        expires_at=FUTURE_EXPIRY,
    )
    result = whatsapp_inbound_actions.handle_whatsapp_inbound_callback(
        callback_data=callback_data,
        sender_ref="4368120864006",
        message_id="wamid.voice.1",
    )

    assert result["status"] == "applied"
    assert "I sent 2 short voice samples." in str(result["reply_text"])
    assert "callback_encoding_failed" not in str(result["reply_text"])


def test_handle_whatsapp_audiobook_playback_callback_records_acceptance(monkeypatch) -> None:
    calls: dict[str, object] = {}

    def _fake_record_acceptance(**kwargs: object) -> None:
        calls.update(kwargs)

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "playback-secret")
    monkeypatch.setattr(
        whatsapp_inbound_actions.audiobook_epub_pipeline,
        "record_audiobook_playback_acceptance_by_callback_token",
        _fake_record_acceptance,
    )

    callback_data = whatsapp_inbound_actions.encode_whatsapp_audiobook_playback_callback(
        action="a",
        token="playback-token-1",
        sender_ref="4368120864006",
        expires_at=FUTURE_EXPIRY,
    )

    result = whatsapp_inbound_actions.handle_whatsapp_inbound_callback(
        callback_data=callback_data,
        sender_ref="4368120864006",
        message_id="wamid.playback.1",
    )

    assert result["status"] == "applied"
    assert result["kind"] == "audiobook_playback"
    assert result["action"] == "accepted"
    assert result["reply_text"] == "Marked the audiobook playback as working."
    assert calls == {
        "callback_token": "playback-token-1",
        "accepted": True,
        "source": "whatsapp_button",
        "message_id": "wamid.playback.1",
        "feedback": "whatsapp_button_playback_accepted",
    }


def test_handle_whatsapp_audiobook_playback_callback_recovers_latest_sender_job(monkeypatch, tmp_path) -> None:
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-1"
    job_dir.mkdir(parents=True)
    job = {
        "job_id": "job-1",
        "status": "public_share_ready",
        "metadata": {"title": "Recovered Book"},
        "whatsapp": {"sender_ref": "4368120864006"},
        "audiobookshelf_import": {
            "target_path": "",
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://audio.example.invalid/share/recovered",
                "playback_acceptance_callback": {
                    "status": "ready",
                    "token": "current-token",
                    "raw_token_exposed": False,
                },
                "whatsapp_delivery": {
                    "status": "sent",
                    "message_id_sha256": "a" * 64,
                    "callback_tokens_exposed": False,
                },
            },
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "playback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    callback_data = whatsapp_inbound_actions.encode_whatsapp_audiobook_playback_callback(
        action="a",
        token="stale-token",
        sender_ref="4368120864006",
        expires_at=FUTURE_EXPIRY,
    )

    result = whatsapp_inbound_actions.handle_whatsapp_inbound_callback(
        callback_data=callback_data,
        sender_ref="4368120864006",
        message_id="wamid.playback.recovered",
    )

    assert result["status"] == "applied"
    assert result["recovered"] is True
    assert result["reply_text"] == "Marked the audiobook playback as working."
    updated = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    playback = updated["playback_acceptance"]
    assert playback["status"] == "accepted"
    assert playback["source"] == "whatsapp_button_recovered"
    assert playback["message_id_sha256"]
    assert playback["whatsapp_public_share_message_id_sha256"] == "a" * 64


def test_handle_whatsapp_audiobook_playback_callback_recovers_latest_sender_job_after_delivery_progress(monkeypatch, tmp_path) -> None:
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-1"
    job_dir.mkdir(parents=True)
    job = {
        "job_id": "job-1",
        "status": "public_share_ready",
        "metadata": {"title": "Recovered Book"},
        "whatsapp": {"sender_ref": "4368120864006"},
        "audiobookshelf_import": {
            "target_path": "",
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://audio.example.invalid/share/recovered",
                "playback_acceptance_callback": {
                    "status": "ready",
                    "token": "current-token",
                    "raw_token_exposed": False,
                },
                "whatsapp_delivery": {
                    "status": "delivered",
                    "message_id_sha256": "d" * 64,
                    "callback_tokens_exposed": False,
                },
            },
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "playback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    callback_data = whatsapp_inbound_actions.encode_whatsapp_audiobook_playback_callback(
        action="a",
        token="stale-token",
        sender_ref="4368120864006",
        expires_at=FUTURE_EXPIRY,
    )

    result = whatsapp_inbound_actions.handle_whatsapp_inbound_callback(
        callback_data=callback_data,
        sender_ref="4368120864006",
        message_id="wamid.playback.delivered",
    )

    assert result["status"] == "applied"
    assert result["recovered"] is True
    updated = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    assert updated["playback_acceptance"]["status"] == "accepted"
    assert updated["playback_acceptance"]["whatsapp_public_share_message_id_sha256"] == "d" * 64


def test_handle_expired_whatsapp_audiobook_playback_callback_recovers_latest_sender_job(monkeypatch, tmp_path) -> None:
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-1"
    job_dir.mkdir(parents=True)
    job = {
        "job_id": "job-1",
        "status": "public_share_ready",
        "metadata": {"title": "Recovered Book"},
        "whatsapp": {"sender_ref": "4368120864006"},
        "audiobookshelf_import": {
            "target_path": "",
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://audio.example.invalid/share/recovered",
                "playback_acceptance_callback": {
                    "status": "ready",
                    "token": "current-token",
                    "raw_token_exposed": False,
                },
                "whatsapp_delivery": {
                    "status": "sent",
                    "message_id_sha256": "a" * 64,
                    "callback_tokens_exposed": False,
                },
            },
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "playback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    callback_data = whatsapp_inbound_actions.encode_whatsapp_audiobook_playback_callback(
        action="a",
        token="expired-token",
        sender_ref="4368120864006",
        expires_at=1,
    )

    result = whatsapp_inbound_actions.handle_whatsapp_inbound_callback(
        callback_data=callback_data,
        sender_ref="4368120864006",
        message_id="wamid.playback.expired",
    )

    assert result["status"] == "applied"
    assert result["recovered"] is True
    updated = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    assert updated["playback_acceptance"]["status"] == "accepted"
    assert updated["playback_acceptance"]["source"] == "whatsapp_button_recovered"


def test_handle_whatsapp_audiobook_playback_callback_reports_stale_without_sender_job(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "playback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    callback_data = whatsapp_inbound_actions.encode_whatsapp_audiobook_playback_callback(
        action="a",
        token="missing-token",
        sender_ref="4368120864006",
        expires_at=FUTURE_EXPIRY,
    )

    result = whatsapp_inbound_actions.handle_whatsapp_inbound_callback(
        callback_data=callback_data,
        sender_ref="4368120864006",
        message_id="wamid.playback.stale",
    )

    assert result["status"] == "stale"
    assert result["kind"] == "audiobook_playback"
    assert "fresh buttons" in str(result["reply_text"])


def test_handle_whatsapp_audiobook_playback_callback_reports_stale_for_tampered_signature_without_sender_job(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "playback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(tmp_path / "jobs"))
    callback_data = whatsapp_inbound_actions.encode_whatsapp_audiobook_playback_callback(
        action="a",
        token="missing-token",
        sender_ref="4368120864006",
        expires_at=FUTURE_EXPIRY,
    )
    tampered = f"{callback_data[:-1]}x"

    result = whatsapp_inbound_actions.handle_whatsapp_inbound_callback(
        callback_data=tampered,
        sender_ref="4368120864006",
        message_id="wamid.playback.tampered",
    )

    assert result["status"] == "stale"
    assert result["kind"] == "audiobook_playback"
    assert result["reason"] == "invalid_signature"
    assert "fresh buttons" in str(result["reply_text"])


def test_handle_whatsapp_audiobook_playback_callback_recovers_from_invalid_signature(monkeypatch, tmp_path) -> None:
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-1"
    job_dir.mkdir(parents=True)
    job = {
        "job_id": "job-1",
        "status": "public_share_ready",
        "metadata": {"title": "Recovered Book"},
        "whatsapp": {
            "sender_ref": "4368120864006",
            "public_share_delivery": {
                "status": "sent",
                "message_id_sha256": "b" * 64,
                "callback_tokens_exposed": False,
            },
        },
        "audiobookshelf_import": {
            "target_path": "",
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://audio.example.invalid/share/recovered",
                "playback_acceptance_callback": {
                    "status": "ready",
                    "token": "current-token",
                    "raw_token_exposed": False,
                },
            },
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "playback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    callback_data = whatsapp_inbound_actions.encode_whatsapp_audiobook_playback_callback(
        action="a",
        token="stale-token",
        sender_ref="4368120864006",
        expires_at=FUTURE_EXPIRY,
    )
    tampered = f"{callback_data[:-1]}x"

    result = whatsapp_inbound_actions.handle_whatsapp_inbound_callback(
        callback_data=tampered,
        sender_ref="4368120864006",
        message_id="wamid.playback.invalidsig",
    )

    assert result["status"] == "applied"
    assert result["recovered"] is True
    assert result["reply_text"] == "Marked the audiobook playback as working."
    updated = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    assert updated["playback_acceptance"]["status"] == "accepted"
    assert updated["playback_acceptance"]["source"] == "whatsapp_button_recovered"
    assert updated["playback_acceptance"]["whatsapp_public_share_message_id_sha256"] == "b" * 64


def test_handle_whatsapp_audiobook_playback_callback_recovers_when_token_recording_fails(monkeypatch, tmp_path) -> None:
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-1"
    job_dir.mkdir(parents=True)
    job = {
        "job_id": "job-1",
        "status": "public_share_ready",
        "metadata": {"title": "Recovered Book"},
        "whatsapp": {"sender_ref": "4368120864006"},
        "audiobookshelf_import": {
            "target_path": "",
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://audio.example.invalid/share/recovered",
                "playback_acceptance_callback": {
                    "status": "ready",
                    "token": "current-token",
                    "raw_token_exposed": False,
                },
                "whatsapp_delivery": {
                    "status": "sent",
                    "message_id_sha256": "c" * 64,
                    "callback_tokens_exposed": False,
                },
            },
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _fail_record(**_: object) -> None:
        raise RuntimeError("permission_denied")

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "playback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(
        whatsapp_inbound_actions.audiobook_epub_pipeline,
        "record_audiobook_playback_acceptance_by_callback_token",
        _fail_record,
    )
    callback_data = whatsapp_inbound_actions.encode_whatsapp_audiobook_playback_callback(
        action="a",
        token="playback-token-1",
        sender_ref="4368120864006",
        expires_at=FUTURE_EXPIRY,
    )

    result = whatsapp_inbound_actions.handle_whatsapp_inbound_callback(
        callback_data=callback_data,
        sender_ref="4368120864006",
        message_id="wamid.playback.recovery-fallback",
    )

    assert result["status"] == "applied"
    assert result["recovered"] is True
    updated = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    assert updated["playback_acceptance"]["status"] == "accepted"
    assert updated["playback_acceptance"]["source"] == "whatsapp_button_recovered"


def test_whatsapp_playback_callback_default_ttl_is_long_lived(monkeypatch) -> None:
    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "playback-secret")
    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_PLAYBACK_CALLBACK_TTL_SECONDS", "2592000")

    callback_data = whatsapp_inbound_actions.encode_whatsapp_audiobook_playback_callback(
        action="a",
        token="playback-token-ttl",
        sender_ref="4368120864006",
    )
    parts = callback_data.split("|")
    assert len(parts) == 5
    expires_at = int(parts[3])
    assert expires_at - 2592000 <= __import__("time").time() <= expires_at


def test_handle_whatsapp_audiobook_management_callback_decodes_action(monkeypatch) -> None:
    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "manage-secret")

    callback_data = whatsapp_inbound_actions.encode_whatsapp_audiobook_management_callback(
        action="r",
        token="job-control-token",
        sender_ref="4368120864006",
        expires_at=FUTURE_EXPIRY,
    )

    result = whatsapp_inbound_actions.handle_whatsapp_inbound_callback(
        callback_data=callback_data,
        sender_ref="4368120864006",
        message_id="wamid.manage.1",
    )

    assert result == {
        "status": "applied",
        "kind": "audiobook_voice_management",
        "action": "restore_language",
        "token": "job-control-token",
        "reply_text": "",
    }


def test_handle_whatsapp_inbound_callback_rejects_tampered_signature(monkeypatch) -> None:
    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "tamper-secret")
    callback_data = whatsapp_inbound_actions.encode_whatsapp_audiobook_voice_callback(
        action="d",
        token="voice-token-2",
        sender_ref="4368120864006",
        expires_at=FUTURE_EXPIRY,
    )
    tampered = f"{callback_data[:-1]}{'0' if callback_data[-1] != '0' else '1'}"

    result = whatsapp_inbound_actions.handle_whatsapp_inbound_callback(
        callback_data=tampered,
        sender_ref="4368120864006",
    )

    assert result["status"] == "ignored"
    assert result["reason"] == "invalid_signature"


def test_whatsapp_audiobook_callback_secret_can_be_loaded_from_file(monkeypatch, tmp_path) -> None:
    secret_file = tmp_path / "whatsapp_audiobook_callback_secret"
    secret_file.write_text("file-secret\n", encoding="utf-8")
    for key in (
        "EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET",
        "EA_WHATSAPP_CALLBACK_SECRET",
        "EA_TELEGRAM_CALLBACK_SECRET",
        "EA_WHATSAPP_WEB_SESSION_API_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET_FILE", str(secret_file))

    callback_data = whatsapp_inbound_actions.encode_whatsapp_audiobook_voice_callback(
        action="u",
        token="voice-token-from-file",
        sender_ref="4368120864006",
        expires_at=FUTURE_EXPIRY,
    )
    decoded = whatsapp_inbound_actions.decode_whatsapp_inbound_callback(
        callback_data=callback_data,
        sender_ref="4368120864006",
    )

    assert callback_data.startswith("ab|u|voice-token-from-file|")
    assert decoded["ok"] is True
    assert decoded["token"] == "voice-token-from-file"
