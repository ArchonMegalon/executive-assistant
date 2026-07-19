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


def test_handle_whatsapp_audiobook_voice_callback_uses_automatic_cast(
    monkeypatch,
) -> None:
    calls: dict[str, object] = {}

    def _fake_apply_audition_action(
        *, callback_token: str, action: str
    ) -> dict[str, object]:
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

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "voice-secret")
    monkeypatch.setattr(
        whatsapp_inbound_actions.audiobook_epub_pipeline,
        "apply_audiobook_voice_audition_action",
        _fake_apply_audition_action,
    )
    monkeypatch.setattr(
        whatsapp_inbound_actions.audiobook_epub_pipeline,
        "telegram_epub_reply_text",
        lambda _job: "Automatic narrator and dialogue cast selected.",
    )

    callback_data = whatsapp_inbound_actions.encode_whatsapp_audiobook_voice_callback(
        action="a",
        token="voice-token-auto",
        sender_ref="4368120864006",
        expires_at=FUTURE_EXPIRY,
    )
    result = whatsapp_inbound_actions.handle_whatsapp_inbound_callback(
        callback_data=callback_data,
        sender_ref="4368120864006",
        message_id="wamid.voice.auto",
    )

    assert callback_data.startswith("ab|a|voice-token-auto|")
    assert result["status"] == "applied"
    assert result["kind"] == "audiobook_voice"
    assert result["action"] == "use_automatic_cast"
    assert result["reply_text"] == "Automatic narrator and dialogue cast selected."
    assert calls == {
        "callback_token": "voice-token-auto",
        "action": "use_automatic_cast",
    }


def test_handle_whatsapp_audiobook_voice_callback_sanitizes_apply_error(
    monkeypatch,
) -> None:
    def _fail_apply(**_: object) -> None:
        raise RuntimeError(
            "permission_denied /private/books/Secret.epub voice_id=private-voice"
        )

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "voice-secret")
    monkeypatch.setattr(
        whatsapp_inbound_actions.audiobook_epub_pipeline,
        "apply_audiobook_voice_audition_action",
        _fail_apply,
    )
    callback_data = whatsapp_inbound_actions.encode_whatsapp_audiobook_voice_callback(
        action="u",
        token="voice-token-secret-error",
        sender_ref="4368120864006",
        expires_at=FUTURE_EXPIRY,
    )

    result = whatsapp_inbound_actions.handle_whatsapp_inbound_callback(
        callback_data=callback_data,
        sender_ref="4368120864006",
        message_id="wamid.voice.error",
    )

    assert result == {
        "status": "failed",
        "kind": "audiobook_voice",
        "reason": "audiobook_voice_choice_failed",
        "reply_text": "I could not apply that audiobook voice choice yet.",
    }
    rendered = json.dumps(result, sort_keys=True)
    assert "/private/books/Secret.epub" not in rendered
    assert "private-voice" not in rendered
    assert "permission_denied" not in rendered


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

    def _fake_record_acceptance(**kwargs: object) -> dict[str, object]:
        calls.update(kwargs)
        return {"playback_acceptance": {"listened": True}}

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
    assert callback_data.startswith("ap2|a|playback-token-1|")

    result = whatsapp_inbound_actions.handle_whatsapp_inbound_callback(
        callback_data=callback_data,
        sender_ref="4368120864006",
        message_id="wamid.playback.1",
    )

    assert result["status"] == "applied"
    assert result["kind"] == "audiobook_playback"
    assert result["action"] == "accepted"
    assert result["reply_text"] == "Recorded your all-7 perceptual playback attestation."
    assert calls["callback_token"] == "playback-token-1"
    assert calls["accepted"] is True
    assert calls["source"] == "whatsapp_button"
    assert calls["message_id"] == "wamid.playback.1"
    assert calls["feedback"] == (
        "whatsapp_button_perceptual_attestation_v1_all_checks_passed"
    )
    attestation = calls["perceptual_attestation"]
    assert isinstance(attestation, dict)
    assert attestation["contract_name"] == (
        "ea.audiobook_perceptual_attestation.v1"
    )
    assert attestation["version"] == 1
    assert attestation["all_checks_attested"] is True
    assert all(attestation["checks"].values())
    assert attestation["attestation_sha256"]


def test_legacy_whatsapp_playback_acknowledgement_is_not_structured_attestation(
    monkeypatch,
) -> None:
    calls: dict[str, object] = {}
    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "playback-secret")
    monkeypatch.setattr(
        whatsapp_inbound_actions.audiobook_epub_pipeline,
        "record_audiobook_playback_acceptance_by_callback_token",
        lambda **kwargs: calls.update(kwargs),
    )
    signature = whatsapp_inbound_actions._playback_signature(
        secret="playback-secret",
        action="a",
        token="legacy-token",
        sender_ref="4368120864006",
        expires_at=FUTURE_EXPIRY,
        callback_prefix="ap",
    )
    callback_data = f"ap|a|legacy-token|{FUTURE_EXPIRY}|{signature}"

    result = whatsapp_inbound_actions.handle_whatsapp_inbound_callback(
        callback_data=callback_data,
        sender_ref="4368120864006",
        message_id="wamid.playback.legacy",
    )

    assert result["status"] == "applied"
    assert "does not complete the listened-canary checklist" in result["reply_text"]
    assert calls == {
        "callback_token": "legacy-token",
        "accepted": True,
        "source": "whatsapp_button",
        "message_id": "wamid.playback.legacy",
        "feedback": "whatsapp_button_playback_accepted",
        "perceptual_attestation": None,
    }


def test_handle_whatsapp_audiobook_playback_callback_does_not_recover_stale_token_to_latest_sender_job(monkeypatch, tmp_path) -> None:
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

    assert result["status"] == "stale"
    assert "fresh buttons" in str(result["reply_text"])
    updated = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    assert "playback_acceptance" not in updated


def test_handle_whatsapp_audiobook_playback_callback_does_not_recover_stale_token_after_delivery_progress(monkeypatch, tmp_path) -> None:
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

    assert result["status"] == "stale"
    updated = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    assert "playback_acceptance" not in updated


def test_handle_expired_whatsapp_audiobook_playback_callback_requires_fresh_button(monkeypatch, tmp_path) -> None:
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

    assert result["status"] == "stale"
    assert result["reason"] == "expired"
    updated = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    assert "playback_acceptance" not in updated


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


def test_handle_whatsapp_audiobook_playback_callback_never_recovers_invalid_signature(monkeypatch, tmp_path) -> None:
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

    assert result["status"] == "stale"
    assert result["reason"] == "invalid_signature"
    updated = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    assert "playback_acceptance" not in updated


def test_handle_whatsapp_audiobook_playback_callback_fails_closed_when_token_recording_fails(monkeypatch, tmp_path) -> None:
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
        raise RuntimeError("permission_denied /private/books/Secret.epub voice_id=private-voice")

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

    assert result["status"] == "failed"
    assert result["reason"] == "audiobook_playback_acceptance_failed"
    rendered = json.dumps(result, sort_keys=True)
    assert "/private/books/Secret.epub" not in rendered
    assert "private-voice" not in rendered
    assert "permission_denied" not in rendered
    updated = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    assert "playback_acceptance" not in updated


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
