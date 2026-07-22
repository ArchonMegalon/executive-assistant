from __future__ import annotations

import errno
import importlib.util
import json
import os
import struct
import sys
import threading
import time
import wave
import zipfile
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "process_whatsapp_web_session_actions.py"
FUTURE_EXPIRY = 4102444800


@pytest.fixture(autouse=True)
def _disable_transcode_quality_gate_for_fake_media(monkeypatch):
    monkeypatch.setenv("EA_WHATSAPP_VOICE_SAMPLE_TRANSCODE_QUALITY_GATE_ENABLED", "0")


@pytest.fixture(autouse=True)
def _disable_audiobook_job_cleanup(monkeypatch):
    monkeypatch.setenv("EA_AUDIOBOOK_JOB_CLEANUP_ENABLED", "0")


def _module():
    spec = importlib.util.spec_from_file_location("process_whatsapp_web_session_actions", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _args(tmp_path: Path, **overrides: object) -> Namespace:
    values: dict[str, object] = {
        "auth_header_name": "Authorization",
        "auth_header_prefix": "Bearer ",
        "dry_run": False,
        "freeform_conversation_fallback_max_age_seconds": 21600,
        "reply_heyy_ai_key": "empathetic_slow_typing_old_lady",
        "reply_heyy_ai_name": "Herta (Heyy Lady)",
        "reply_pre_reply_delay_min_seconds": 180,
        "reply_pre_reply_delay_max_seconds": 1800,
        "reply_quiet_hours_start_hour": 21,
        "reply_quiet_hours_end_hour": 6,
        "reply_typing_delay_ms": 6500,
        "reply_typing_delay_ms_per_character": 8000,
        "reply_typing_status_enabled": True,
        "principal_id": "exec-1",
        "audiobook_resume_due": False,
        "audiobook_resume_due_limit": 1,
        "audiobook_followup_enabled": False,
        "audiobook_followup_limit": 3,
        "public_share_inline_buttons_enabled": False,
        "stale_callback_reply_max_age_seconds": 900,
        "conversation_fallback_noop_cooldown_seconds": 60,
        "conversation_fallback_noop_max_cooldown_seconds": 300,
        "telegram_summary_enabled": False,
        "telegram_summary_every": 5,
        "telegram_summary_chat_id": "",
        "telegram_summary_bot_token": "",
        "telegram_summary_timeout_seconds": 15.0,
        "telegram_summary_heyy_ai_keys": "empathetic_slow_typing_old_lady",
        "telegram_summary_scope_label": "Herta",
        "session_api_base_url": "https://wa-web.test",
        "session_api_token": "session-token",
        "session_ref": "session-1",
        "state_file": str(tmp_path / "wa-actions.json"),
        "take": 100,
        "timeout_seconds": 30.0,
    }
    values.update(overrides)
    return Namespace(**values)


def _write_test_wav(path: Path, *, seconds: float = 0.25, sample_rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"".join(struct.pack("<h", 3200 if i % 2 else -3200) for i in range(max(int(sample_rate * seconds), 1))))


def _voice_specific_test_wav_bytes(tmp_path: Path, voice_ids: list[str]) -> dict[str, bytes]:
    payloads: dict[str, bytes] = {}
    for index, voice_id in enumerate(voice_ids, start=1):
        path = tmp_path / f"voice-sample-{index}.wav"
        _write_test_wav(path, seconds=0.20 + (index * 0.025))
        payloads[voice_id] = path.read_bytes()
    return payloads


def _selected_message(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "direction": "inbound",
        "from_me": False,
        "id": "wamid.inbound.1",
        "selected_button_id": "ab|u|voice-token-1|1v7j5c0|sig",
        "selected_button_id_present": True,
        "selected_button_kind": "audiobook_voice",
        "sender_digits": "4368120864006",
    }
    values.update(overrides)
    return values


def _epub_message(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "chat_ref": "chat-ref-1",
        "direction": "inbound",
        "from_me": False,
        "id": "wamid.epub.1",
        "media_filename": "book.epub",
        "media_mime_type": "application/epub+zip",
        "media_present": True,
        "sender_digits": "4368120864006",
    }
    values.update(overrides)
    return values


def _text_message(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "body_present": True,
        "body_text": "audiobook status",
        "chat_ref": "chat-ref-1",
        "direction": "inbound",
        "from_me": False,
        "id": "wamid.text.1",
        "heyy_ai_key": "empathetic_slow_typing_old_lady",
        "heyy_ai_name": "Herta (Heyy Lady)",
        "media_present": False,
        "selected_button_id": "",
        "selected_button_id_present": False,
        "sender_digits": "4368120864006",
        "type": "chat",
    }
    values.update(overrides)
    return values


def _bound_fake_approved_job(
    module,
    *,
    template: dict[str, object],
    create_kwargs: dict[str, object],
) -> dict[str, object]:
    job_id = str(create_kwargs["deterministic_job_id"])
    identity = str(create_kwargs["intake_idempotency_key_sha256"])
    source_path = Path(str(create_kwargs["epub_path"]))
    job_dir = module.audiobook_epub_pipeline.audiobook_jobs_root() / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    job = {
        **template,
        "job_id": job_id,
        "principal_id": str(create_kwargs.get("principal_id") or ""),
        "source": {
            **dict(template.get("source") or {}),
            "source_sha256": module.audiobook_epub_pipeline._sha256_file(
                source_path
            ),
            "intake_idempotency_key_sha256": identity,
        },
        "storage": {"job_dir": str(job_dir)},
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")
    return job


def test_send_reply_can_delegate_pacing_to_sidecar_route(tmp_path: Path) -> None:
    module = _module()
    calls: list[dict[str, object]] = []

    result = module._send_reply(
        request_json=lambda **kwargs: calls.append(dict(kwargs)) or {"ok": True, "message_id": "wamid.route.1"},
        args=_args(tmp_path, reply_use_sidecar_route_pacing=True),
        recipient_digits="40424366432273",
        text="Route-paced reply.",
        chat_ref="chat-ref-1",
    )

    assert result["ok"] is True
    assert calls[0]["body"] == {
        "to": "40424366432273",
        "text": "Route-paced reply.",
        "chat_ref": "chat-ref-1",
    }
    assert calls[0]["timeout"] == 30.0


def test_save_state_uses_unique_temp_files_under_concurrent_writes(tmp_path: Path, monkeypatch) -> None:
    module = _module()
    state_path = tmp_path / "wa-actions.json"
    original_write_text = Path.write_text
    barrier = threading.Barrier(8)

    def _delayed_write_text(self: Path, *args, **kwargs):
        if self.parent == state_path.parent and self.name.startswith(f".{state_path.name}.") and self.name.endswith(".tmp"):
            barrier.wait(timeout=2)
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", _delayed_write_text)

    def _write(index: int) -> None:
        module._save_state(state_path, {"version": 1, "actions": {f"row-{index}": {"processed_at": "now"}}})

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(_write, range(8)))

    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved["version"] == 1
    assert len(list(tmp_path.glob("*.tmp"))) == 0
    assert len(list(tmp_path.glob(f".{state_path.name}.*.tmp"))) == 0


def test_build_report_serializes_same_epub_action_before_paid_work(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    args = _args(tmp_path, state_lock_timeout_seconds=2.0)
    jobs_root = tmp_path / "jobs"
    first_get_entered = threading.Event()
    release_first_get = threading.Event()
    second_worker_started = threading.Event()
    second_get_entered = threading.Event()
    request_count = 0
    paid_work_count = 0
    count_lock = threading.Lock()

    monkeypatch.setattr(module.audiobook_access_approval, "approval_required", lambda **_: False)
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "audiobook_jobs_root",
        lambda: jobs_root,
    )
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "create_job_from_epub",
        lambda **kwargs: _bound_fake_approved_job(
            module,
            template={"status": "waiting_voice_selection"},
            create_kwargs=dict(kwargs),
        ),
    )

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        nonlocal request_count
        assert kwargs["method"] == "GET"
        with count_lock:
            request_count += 1
            call_number = request_count
        if call_number == 1:
            first_get_entered.set()
            assert release_first_get.wait(timeout=2)
        else:
            second_get_entered.set()
        return {"messages": [_epub_message(id="wamid.concurrent.same")], "ok": True}

    def _fake_process_epub_candidate(**_: object):
        nonlocal paid_work_count
        with count_lock:
            paid_work_count += 1
        return (
            {"job_id": "job-concurrent-same"},
            [{"status": "sent"}],
            {"ok": True, "message_id": "wamid.concurrent.reply"},
        )

    monkeypatch.setattr(module, "_process_epub_candidate", _fake_process_epub_candidate)

    def _second_worker() -> dict[str, object]:
        second_worker_started.set()
        return module.build_report(
            args,
            request_json=_fake_request_json,
            request_bytes=lambda **_: b"concurrent source",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            module.build_report,
            args,
            request_json=_fake_request_json,
            request_bytes=lambda **_: b"concurrent source",
        )
        assert first_get_entered.wait(timeout=1)
        second = pool.submit(_second_worker)
        assert second_worker_started.wait(timeout=1)
        try:
            assert second_get_entered.wait(timeout=0.2) is False
        finally:
            release_first_get.set()
        reports = [first.result(timeout=3), second.result(timeout=3)]

    assert paid_work_count == 1
    assert sorted(int(report["processed"]) for report in reports) == [0, 1]
    assert sorted(int(report["skipped_processed"]) for report in reports) == [0, 1]
    state = json.loads(Path(args.state_file).read_text(encoding="utf-8"))
    assert len(state["actions"]) == 1


def test_build_report_serialization_preserves_distinct_concurrent_state_updates(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    args = _args(tmp_path, state_lock_timeout_seconds=2.0)
    first_get_entered = threading.Event()
    release_first_get = threading.Event()
    second_worker_started = threading.Event()
    second_get_entered = threading.Event()

    monkeypatch.setattr(module.audiobook_access_approval, "approval_required", lambda **_: False)
    monkeypatch.setattr(
        module,
        "_process_epub_candidate",
        lambda **kwargs: (
            {"job_id": f"job-{dict(kwargs['message'])['id']}"},
            [{"status": "sent"}],
            {"ok": True, "message_id": f"reply-{dict(kwargs['message'])['id']}"},
        ),
    )

    def _first_request(**kwargs: object) -> dict[str, object]:
        assert kwargs["method"] == "GET"
        first_get_entered.set()
        assert release_first_get.wait(timeout=2)
        return {"messages": [_epub_message(id="wamid.concurrent.first")], "ok": True}

    def _second_request(**kwargs: object) -> dict[str, object]:
        assert kwargs["method"] == "GET"
        second_get_entered.set()
        return {"messages": [_epub_message(id="wamid.concurrent.second")], "ok": True}

    def _second_worker() -> dict[str, object]:
        second_worker_started.set()
        return module.build_report(args, request_json=_second_request)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(module.build_report, args, request_json=_first_request)
        assert first_get_entered.wait(timeout=1)
        second = pool.submit(_second_worker)
        assert second_worker_started.wait(timeout=1)
        try:
            assert second_get_entered.wait(timeout=0.2) is False
        finally:
            release_first_get.set()
        first_report = first.result(timeout=3)
        second_report = second.result(timeout=3)

    assert first_report["processed"] == 1
    assert second_report["processed"] == 1
    state = json.loads(Path(args.state_file).read_text(encoding="utf-8"))
    assert set(state["actions"]) == {
        module._action_id(
            session_ref="session-1",
            message_id="wamid.concurrent.first",
            callback_data="epub_media",
        ),
        module._action_id(
            session_ref="session-1",
            message_id="wamid.concurrent.second",
            callback_data="epub_media",
        ),
    }


def test_build_report_fails_closed_when_cross_instance_state_lock_times_out(tmp_path: Path) -> None:
    lock_owner = _module()
    contender = _module()
    args = _args(tmp_path, state_lock_timeout_seconds=0.05)
    state_path = Path(args.state_file)
    request_called = False

    def _unexpected_request(**_: object) -> dict[str, object]:
        nonlocal request_called
        request_called = True
        return {"messages": [], "ok": True}

    started = time.monotonic()
    with lock_owner._state_run_lock(state_path, timeout_seconds=1.0):
        with pytest.raises(contender.StateRunLockTimeout, match="whatsapp_state_run_lock_timeout"):
            contender.build_report(args, request_json=_unexpected_request)
    elapsed = time.monotonic() - started

    assert elapsed < 1.0
    assert request_called is False
    assert state_path.exists() is False


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
    <dc:title>WhatsApp Proof Book</dc:title>
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
            "<html><body><h1>Opening</h1><p>Hello from a real WhatsApp EPUB intake proof.</p></body></html>",
        )
        book.writestr(
            "OEBPS/chapters/chapter-2.xhtml",
            "<html><body><h1>Next</h1><p>The generated job should keep WhatsApp delivery metadata.</p></body></html>",
        )


def test_telegram_summary_sends_once_after_five_inbound_whatsapp_messages(tmp_path: Path) -> None:
    module = _module()
    messages = [
        _text_message(
            id=f"wamid.summary.{index}",
            body_text=f"kurze nachricht {index}",
            message_timestamp=f"2026-06-22T08:0{index}:00Z",
            sender_digits=f"43681208640{index:02d}",
        )
        for index in range(5)
    ]
    sent: list[dict[str, object]] = []

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        assert kwargs["method"] == "GET"
        assert str(kwargs["url"]).endswith("/messages?take=100")
        return {"messages": messages, "ok": True}

    def _fake_send_telegram_message(**kwargs: object) -> dict[str, object]:
        sent.append(dict(kwargs))
        return {"status": "sent", "message_id": "77"}

    args = _args(
        tmp_path,
        conversation_fallback_enabled=False,
        telegram_summary_enabled=True,
        telegram_summary_chat_id="12345",
        telegram_summary_bot_token="token",
    )

    first = module.build_report(args, request_json=_fake_request_json, send_telegram_message=_fake_send_telegram_message)
    second = module.build_report(args, request_json=_fake_request_json, send_telegram_message=_fake_send_telegram_message)

    assert first["status"] == "pass"
    assert first["telegram_summary"]["status"] == "sent"
    assert first["telegram_summary"]["sent"] == 1
    assert second["telegram_summary"]["status"] == "idle"
    assert len(sent) == 1
    assert sent[0]["chat_id"] == "12345"
    text = str(sent[0]["text"])
    assert "Herta-Zusammenfassung (5 neue Nachrichten)" in text
    assert "\n" not in text
    assert "\n-" not in text
    assert "- " not in text
    assert "Inhaltlich geht es zusammengefaßt um" in text
    assert "kurze nachricht 4" in text
    assert "...4004" in text
    state_text = (tmp_path / "wa-actions.json").read_text(encoding="utf-8")
    assert "4368120864004" not in state_text
    assert "kurze nachricht" not in state_text
    assert "telegram_summary" in state_text


def test_audiobook_job_roots_skip_disconnected_mounts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    valid_root = tmp_path / "jobs"
    valid_root.mkdir()
    broken_root = Path("/broken-mount")

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_JOBS_ROOTS", f"{broken_root}:{valid_root}")
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: broken_root)

    original_is_dir = Path.is_dir

    def fake_is_dir(path: Path) -> bool:
        if str(path) == str(broken_root):
            raise OSError(107, "Transport endpoint is not connected")
        return original_is_dir(path)

    monkeypatch.setattr(Path, "is_dir", fake_is_dir)

    roots = module._audiobook_job_roots()

    assert roots == [valid_root]


def test_telegram_summary_scope_label_is_configurable(tmp_path: Path) -> None:
    module = _module()
    messages = [
        _text_message(
            id=f"wamid.summary.scope.{index}",
            body_text=f"scope msg {index}",
            heyy_ai_key="custom_project_ai",
            heyy_ai_name="Custom Project AI",
        )
        for index in range(5)
    ]
    sent: list[dict[str, object]] = []

    report = module.build_report(
        _args(
            tmp_path,
            conversation_fallback_enabled=False,
            telegram_summary_enabled=True,
            telegram_summary_chat_id="12345",
            telegram_summary_bot_token="token",
            telegram_summary_heyy_ai_keys="custom_project_ai",
            telegram_summary_scope_label="Runner",
        ),
        request_json=lambda **_: {"messages": messages, "ok": True},
        send_telegram_message=lambda **kwargs: sent.append(dict(kwargs)) or {"status": "sent", "message_id": "81"},
    )

    assert report["status"] == "pass"
    assert report["telegram_summary"]["status"] == "sent"
    assert report["telegram_summary"]["scope_label"] == "Runner"
    assert report["telegram_summary"]["allowed_heyy_ai_keys"] == ["custom_project_ai"]
    assert report["telegram_summary"]["candidate_count"] == 5
    assert len(sent) == 1
    text = str(sent[0]["text"])
    assert "Runner-Zusammenfassung (5 neue Nachrichten)" in text
    assert "Im Runner-Chat sind 5 neue Nachrichten" in text
    assert "Herta" not in text


def test_telegram_summary_scope_label_derives_from_configured_persona_when_unset(tmp_path: Path) -> None:
    module = _module()
    messages = [
        _text_message(
            id=f"wamid.summary.derived.{index}",
            body_text=f"derived msg {index}",
            heyy_ai_key="custom_project_ai",
            heyy_ai_name="Custom Project AI",
        )
        for index in range(5)
    ]
    sent: list[dict[str, object]] = []

    report = module.build_report(
        _args(
            tmp_path,
            conversation_fallback_enabled=False,
            telegram_summary_enabled=True,
            telegram_summary_chat_id="12345",
            telegram_summary_bot_token="token",
            telegram_summary_heyy_ai_keys="custom_project_ai",
            telegram_summary_scope_label="",
        ),
        request_json=lambda **_: {"messages": messages, "ok": True},
        send_telegram_message=lambda **kwargs: sent.append(dict(kwargs)) or {"status": "sent", "message_id": "82"},
    )

    assert report["status"] == "pass"
    assert report["telegram_summary"]["status"] == "sent"
    assert report["telegram_summary"]["scope_label"] == "Custom Project"
    assert report["telegram_summary"]["allowed_heyy_ai_keys"] == ["custom_project_ai"]
    assert len(sent) == 1
    text = str(sent[0]["text"])
    assert "Custom Project-Zusammenfassung (5 neue Nachrichten)" in text
    assert "Im Custom Project-Chat sind 5 neue Nachrichten" in text
    assert "Herta" not in text


def test_telegram_summary_waits_until_five_inbound_messages(tmp_path: Path) -> None:
    module = _module()
    messages = [_text_message(id=f"wamid.summary.wait.{index}", body_text=f"msg {index}") for index in range(4)]
    sent: list[dict[str, object]] = []

    report = module.build_report(
        _args(
            tmp_path,
            conversation_fallback_enabled=False,
            telegram_summary_enabled=True,
            telegram_summary_chat_id="12345",
            telegram_summary_bot_token="token",
        ),
        request_json=lambda **_: {"messages": messages, "ok": True},
        send_telegram_message=lambda **kwargs: sent.append(dict(kwargs)) or {"status": "sent", "message_id": "78"},
    )

    assert report["status"] == "pass"
    assert report["telegram_summary"]["status"] == "waiting"
    assert report["telegram_summary"]["pending_message_count"] == 4
    assert sent == []


def test_telegram_summary_reports_blocked_when_delivery_config_is_missing(tmp_path: Path) -> None:
    module = _module()
    messages = [_text_message(id=f"wamid.summary.blocked.{index}", body_text=f"msg {index}") for index in range(5)]
    sent: list[dict[str, object]] = []

    report = module.build_report(
        _args(
            tmp_path,
            conversation_fallback_enabled=False,
            telegram_summary_enabled=True,
            telegram_summary_chat_id="",
            telegram_summary_bot_token="",
        ),
        request_json=lambda **_: {"messages": messages, "ok": True},
        send_telegram_message=lambda **kwargs: sent.append(dict(kwargs)) or {"status": "sent", "message_id": "79"},
    )

    assert report["status"] == "pass"
    assert report["telegram_summary"]["status"] == "blocked"
    assert report["telegram_summary"]["reason"] == "telegram_summary_not_configured"
    assert report["telegram_summary"]["pending_message_count"] == 5
    assert report["telegram_summary"]["missing_fields"] == [
        "telegram_summary_bot_token",
        "telegram_summary_chat_id",
    ]
    assert sent == []


def test_telegram_summary_reports_blocked_when_delivery_config_is_missing_even_without_pending_batch(tmp_path: Path) -> None:
    module = _module()
    messages = []
    sent: list[dict[str, object]] = []

    report = module.build_report(
        _args(
            tmp_path,
            conversation_fallback_enabled=False,
            telegram_summary_enabled=True,
            telegram_summary_chat_id="",
            telegram_summary_bot_token="",
        ),
        request_json=lambda **_: {"messages": messages, "ok": True},
        send_telegram_message=lambda **kwargs: sent.append(dict(kwargs)) or {"status": "sent", "message_id": "80"},
    )

    assert report["status"] == "pass"
    assert report["telegram_summary"]["status"] == "blocked"
    assert report["telegram_summary"]["reason"] == "telegram_summary_not_configured"
    assert report["telegram_summary"]["pending_message_count"] == 0
    assert report["telegram_summary"]["missing_fields"] == [
        "telegram_summary_bot_token",
        "telegram_summary_chat_id",
    ]
    assert sent == []


def test_telegram_summary_sends_when_pending_messages_leave_current_fetch(tmp_path: Path) -> None:
    module = _module()
    first_messages = [
        _text_message(
            id=f"wamid.summary.rolling.{index}",
            body_text=f"rollende nachricht {index}",
            message_timestamp=f"2026-06-22T08:0{index}:00Z",
            sender_digits=f"43681208641{index:02d}",
        )
        for index in range(4)
    ]
    second_messages = [
        _text_message(
            id="wamid.summary.rolling.4",
            body_text="fuenfte nachricht sichtbar",
            message_timestamp="2026-06-22T08:04:00Z",
            sender_digits="4368120864104",
        )
    ]
    sent: list[dict[str, object]] = []
    calls = {"count": 0}

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        assert kwargs["method"] == "GET"
        calls["count"] += 1
        return {"messages": first_messages if calls["count"] == 1 else second_messages, "ok": True}

    def _fake_send_telegram_message(**kwargs: object) -> dict[str, object]:
        sent.append(dict(kwargs))
        return {"status": "sent", "message_id": "88"}

    args = _args(
        tmp_path,
        conversation_fallback_enabled=False,
        telegram_summary_enabled=True,
        telegram_summary_chat_id="12345",
        telegram_summary_bot_token="token",
    )

    first = module.build_report(args, request_json=_fake_request_json, send_telegram_message=_fake_send_telegram_message)
    second = module.build_report(args, request_json=_fake_request_json, send_telegram_message=_fake_send_telegram_message)

    assert first["telegram_summary"]["status"] == "waiting"
    assert first["telegram_summary"]["pending_message_count"] == 4
    assert second["telegram_summary"]["status"] == "sent"
    assert second["telegram_summary"]["sent"] == 1
    assert len(sent) == 1
    text = str(sent[0]["text"])
    assert "Herta-Zusammenfassung (5 neue Nachrichten)" in text
    assert "Text nicht gespeichert" not in text
    assert "rollende nachricht 0" in text
    assert "fuenfte nachricht sichtbar" in text
    state_text = (tmp_path / "wa-actions.json").read_text(encoding="utf-8")
    assert "4368120864104" not in state_text
    assert "rollende nachricht" not in state_text
    assert "fuenfte nachricht sichtbar" not in state_text


def test_telegram_summary_ignores_out_of_scope_messages(tmp_path: Path) -> None:
    module = _module()
    messages = [
        _text_message(
            id=f"wamid.summary.outofscope.{index}",
            body_text=f"out of scope {index}",
            heyy_ai_key="executive_assistant",
            heyy_ai_name="Executive Assistant",
        )
        for index in range(5)
    ]
    sent: list[dict[str, object]] = []

    report = module.build_report(
        _args(
            tmp_path,
            conversation_fallback_enabled=False,
            telegram_summary_enabled=True,
            telegram_summary_chat_id="12345",
            telegram_summary_bot_token="token",
        ),
        request_json=lambda **_: {"messages": messages, "ok": True},
        send_telegram_message=lambda **kwargs: sent.append(dict(kwargs)) or {"status": "sent", "message_id": "80"},
    )

    assert report["status"] == "pass"
    assert report["telegram_summary"]["status"] == "idle"
    assert report["telegram_summary"]["scope_label"] == "Herta"
    assert report["telegram_summary"]["allowed_heyy_ai_keys"] == ["empathetic_slow_typing_old_lady"]
    assert report["telegram_summary"]["candidate_count"] == 0
    assert report["telegram_summary"]["new_message_count"] == 0
    assert report["telegram_summary"]["pending_message_count"] == 0
    assert sent == []


def test_build_report_replies_to_executive_assistant_freeform_inbox_messages(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module()
    sent: list[dict[str, object]] = []
    monkeypatch.setenv("EA_AUDIOBOOK_JOB_CLEANUP_ENABLED", "1")
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "cleanup_finished_audiobook_jobs",
        lambda force=False: {"status": "not_needed", "cleaned_jobs": 0},
    )

    monkeypatch.setattr(
        module,
        "_executive_assistant_freeform_reply_text",
        lambda **_: "Handled. I checked it.",
    )

    def _request_json(**kwargs):
        if kwargs.get("method") == "POST":
            sent.append(dict(kwargs.get("body") or {}))
            return {"ok": True, "id": "wamid.reply.1"}
        return {
            "messages": [
                _text_message(
                    id="wamid.freeform.1",
                    body_text="worked",
                    heyy_ai_key="executive_assistant",
                    heyy_ai_name="Executive Assistant",
                    sender_digits="40424366432273",
                )
            ],
            "ok": True,
        }

    report = module.build_report(
        _args(tmp_path, conversation_fallback_enabled=False),
        request_json=_request_json,
    )

    assert report["status"] == "pass"
    assert report["inbox_message_count"] == 1
    assert report["inbound_message_count"] == 1
    assert report["candidate_count"] == 0
    assert report["audiobook_source_candidate_count"] == 0
    assert report["voice_text_candidate_count"] == 0
    assert report["status_candidate_count"] == 0
    assert report["freeform_inbox_message_count"] == 1
    assert report["freeform_inbox_by_heyy_ai_key"] == {"executive_assistant": 1}
    assert report["freeform_reply_sent"] == 1
    assert report["reply_sent"] == 1
    assert report["cleanup_summary"]["status"] == "not_needed"
    assert sent == [
        {
            "to": "40424366432273",
            "text": "Handled. I checked it.",
            "chat_ref": "chat-ref-1",
        }
    ]


def test_build_report_skips_executive_assistant_freeform_without_real_reply_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module()
    sent: list[dict[str, object]] = []
    monkeypatch.setenv("EA_AUDIOBOOK_JOB_CLEANUP_ENABLED", "1")
    monkeypatch.delenv("EA_WHATSAPP_WEB_FREEFORM_EXECUTIVE_ASSISTANT_FALLBACK_REPLY", raising=False)
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "cleanup_finished_audiobook_jobs",
        lambda force=False: {"status": "not_needed", "cleaned_jobs": 0},
    )
    monkeypatch.setattr(module, "_executive_assistant_freeform_reply_text", lambda **_: "")

    def _request_json(**kwargs):
        if kwargs.get("method") == "POST":
            sent.append(dict(kwargs.get("body") or {}))
            return {"ok": True, "id": "wamid.reply.1"}
        return {
            "messages": [
                _text_message(
                    id="wamid.freeform.2",
                    body_text="worked",
                    heyy_ai_key="executive_assistant",
                    heyy_ai_name="Executive Assistant",
                    sender_digits="40424366432273",
                )
            ],
            "ok": True,
        }

    report = module.build_report(
        _args(tmp_path, conversation_fallback_enabled=False),
        request_json=_request_json,
    )

    assert report["status"] == "pass"
    assert report["freeform_inbox_message_count"] == 1
    assert report["freeform_reply_sent"] == 0
    assert report["reply_sent"] == 0
    assert sent == []


def test_build_report_recovers_auto_reply_persona_from_conversation_fallback_chat_history(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module()
    sent: list[dict[str, object]] = []
    monkeypatch.setenv("EA_AUDIOBOOK_JOB_CLEANUP_ENABLED", "1")
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "cleanup_finished_audiobook_jobs",
        lambda force=False: {"status": "not_needed", "cleaned_jobs": 0},
    )

    def _request_json(**kwargs):
        url = str(kwargs.get("url") or "")
        method = str(kwargs.get("method") or "").upper()
        if method == "POST":
            sent.append(dict(kwargs.get("body") or {}))
            return {"ok": True, "id": "wamid.reply.herta.1"}
        if url.endswith("/messages?take=100"):
            return {"messages": [], "ok": True}
        if "heyy-ai-routes?include_details=1" in url:
            return {
                "ok": True,
                "routes": [
                    {
                        "route_key": "default",
                        "ai_key": "empathetic_slow_typing_old_lady",
                        "ai_name": "Herta (Heyy Lady)",
                        "auto_reply_enabled": True,
                        "reply_text": "Na geh... ich bin die Herta. Schreib mir bitte kurz, ich bin beim Tippen langsam.",
                    },
                    {
                        "route_key": "40424366432273",
                        "ai_key": "executive_assistant",
                        "ai_name": "Executive Assistant",
                        "auto_reply_enabled": False,
                        "reply_text": "I am on the Executive Assistant route now.",
                    },
                ],
            }
        if "/conversations?" in url:
            return {
                "conversation_count": 1,
                "conversation_page_complete": False,
                "conversation_total": 1,
                "conversations": [
                    {
                        "chat_ref": "chat-ref-herta",
                        "unread_count": 1,
                        "messages": [
                            _text_message(
                                id="wamid.herta.outbound.1",
                                direction="outbound",
                                from_me=True,
                                body_text="Ach, mein Kind.",
                                heyy_ai_key="empathetic_slow_typing_old_lady",
                                heyy_ai_name="Herta (Heyy Lady)",
                                sender_digits="233385066778814",
                                chat_ref="chat-ref-herta",
                                message_timestamp=module._now_iso(),
                            ),
                            _text_message(
                                id="wamid.herta.inbound.1",
                                body_text="Hallo Mama, neue Nummer.",
                                heyy_ai_key="executive_assistant",
                                heyy_ai_name="Executive Assistant",
                                sender_digits="40424366432273",
                                chat_ref="chat-ref-herta",
                                message_timestamp=module._now_iso(),
                            ),
                        ],
                    }
                ],
                "ok": True,
            }
        raise AssertionError(f"unexpected url {url}")

    report = module.build_report(_args(tmp_path), request_json=_request_json)

    assert report["status"] == "pass"
    assert report["conversation_fallback"]["attempted"] is True
    assert report["inbound_message_count"] == 1
    assert report["freeform_inbox_message_count"] == 1
    assert report["freeform_inbox_by_heyy_ai_key"] == {"executive_assistant": 1}
    assert report["freeform_reply_sent"] == 1
    assert sent[0]["to"] == "40424366432273"
    assert sent[0]["chat_ref"] == "chat-ref-herta"
    assert sent[0]["text"] in {
        "Ach, mein Kind, ich schreib Dir heut vom Handy vom seligen Franz zurück. Bei meinem ist das Display ganz hinüber, ich erkenn ja fast nichts mehr.",
        "Ich hab mein eigenes Handy kaum lesen können, Schatzi, das Display ist kaputt. Darum nehm ich grad noch das alte Telefon vom Franz.",
        "Nicht erschrecken, mein Herz, ich bin schon ich. Mein Bildschirm ist wieder hin, und deshalb schreib ich Dir grad vom Handy vom seligen Franz.",
    }


@pytest.mark.parametrize(
    "cleanup_exc,expected_error,expected_extra",
    [
        (FileNotFoundError("raced"), "FileNotFoundError", {}),
        (
            OSError(errno.ENOTCONN, "Transport endpoint is not connected"),
            "OSError",
            {"errno": errno.ENOTCONN},
        ),
        (
            TypeError("rmtree() got an unexpected keyword argument 'onexc'"),
            "TypeError",
            {},
        ),
    ],
)
def test_cleanup_summary_transient_failures_are_observable_without_partial_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    cleanup_exc: BaseException,
    expected_error: str,
    expected_extra: dict[str, object],
) -> None:
    module = _module()
    monkeypatch.setenv("EA_AUDIOBOOK_JOB_CLEANUP_ENABLED", "1")
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "cleanup_finished_audiobook_jobs",
        lambda force=False: (_ for _ in ()).throw(cleanup_exc),
    )

    def _request_json(**kwargs):
        if kwargs.get("method") == "GET":
            return {"messages": [], "ok": True}
        return {"ok": True}

    report = module.build_report(
        _args(tmp_path, conversation_fallback_enabled=False),
        request_json=_request_json,
    )

    assert report["status"] == "pass"
    assert report["errors"] == 0
    assert report["cleanup_summary"] == {
        "status": "skipped",
        "reason": "transient_cleanup_exception",
        "error": expected_error,
        "non_blocking": True,
        "observability": "cleanup_skipped_transient",
        **expected_extra,
    }
    assert report["external_blockers"] == []


def test_build_report_surfaces_disconnected_audiobook_mount_as_external_blocker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _module()
    monkeypatch.setenv("EA_AUDIOBOOK_JOB_CLEANUP_ENABLED", "1")
    disconnected_probe = {
        "accessible": False,
        "errno": errno.ENOTCONN,
        "error": "OSError",
        "path": "/data/audiobooks/jobs",
        "status": "disconnected_mount",
    }
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "cleanup_finished_audiobook_jobs",
        lambda force=False: {
            "status": "missing",
            "job_root": dict(disconnected_probe),
        },
    )
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "resume_due_audiobook_jobs",
        lambda notify_telegram=False, limit=1: {
            "ran": True,
            "attempted": 0,
            "resumed": 0,
            "errors": 0,
            "reason": "job_root_missing",
            "job_root": dict(disconnected_probe),
        },
    )

    report = module.build_report(
        _args(tmp_path, conversation_fallback_enabled=False, audiobook_resume_due=True),
        request_json=lambda **_: {"messages": [], "ok": True},
    )

    assert report["status"] == "pass"
    assert report["errors"] == 0
    assert report["external_blockers"] == [
        {
            "kind": "audiobook_job_root_unavailable",
            "source": "cleanup_summary",
            "status": "disconnected_mount",
            "path": "/data/audiobooks/jobs",
            "reason": "disconnected_mount",
            "external_dependency": True,
            "errno": errno.ENOTCONN,
            "error": "OSError",
        },
        {
            "kind": "audiobook_job_root_unavailable",
            "source": "resume_summary",
            "status": "disconnected_mount",
            "path": "/data/audiobooks/jobs",
            "reason": "job_root_missing",
            "external_dependency": True,
            "errno": errno.ENOTCONN,
            "error": "OSError",
        },
    ]


def test_build_report_dry_run_skips_cleanup_scan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _module()
    monkeypatch.setenv("EA_AUDIOBOOK_JOB_CLEANUP_ENABLED", "1")
    cleanup_called = {"value": False}

    def _fail_if_called(force: bool = False):
        cleanup_called["value"] = True
        raise AssertionError("cleanup should be skipped during dry-run")

    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "cleanup_finished_audiobook_jobs",
        _fail_if_called,
    )

    report = module.build_report(
        _args(tmp_path, dry_run=True, conversation_fallback_enabled=False),
        request_json=lambda **_: {"messages": [], "ok": True},
    )

    assert cleanup_called["value"] is False
    assert report["cleanup_summary"] == {"status": "dry_run"}


def test_build_report_ignores_voice_selection_text_without_pending_job(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module()
    jobs_root = tmp_path / "jobs"
    jobs_root.mkdir()
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)

    report = module.build_report(
        _args(tmp_path, conversation_fallback_enabled=False),
        request_json=lambda **_: {
            "messages": [
                _text_message(
                    id="wamid.voice.nojob.1",
                    body_text="use Remy!",
                    heyy_ai_key="executive_assistant",
                    heyy_ai_name="Executive Assistant",
                    sender_digits="40424366432273",
                )
            ],
            "ok": True,
        },
    )

    assert report["status"] == "pass"
    assert report["voice_text_candidate_count"] == 0
    assert report["voice_text_processed"] == 0
    assert report["candidate_count"] == 0
    assert report["freeform_inbox_message_count"] == 1


def test_telegram_summary_ignores_empty_placeholder_messages_and_clears_stale_pending_record(tmp_path: Path) -> None:
    module = _module()
    state_file = tmp_path / "wa-actions.json"
    state_file.write_text(
        json.dumps(
            {
                "version": 1,
                "actions": {},
                "telegram_summary": {
                    "seen_message_hashes": ["placeholder-hash"],
                    "pending_message_hashes": ["placeholder-hash"],
                    "pending_message_records": [
                        {
                            "message_hash": "placeholder-hash",
                            "message_timestamp": "2026-06-22T13:13:08Z",
                            "summary_sender_mask": "...1132",
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    messages = [
        _text_message(
            id="wamid.summary.placeholder.1",
            body_present=False,
            body_text="",
            media_present=False,
            media_filename="",
            media_mime_type="",
            sender_digits="227775403311132",
            type="biz_content_placeholder",
        )
    ]

    report = module.build_report(
        _args(
            tmp_path,
            conversation_fallback_enabled=False,
            telegram_summary_enabled=True,
            telegram_summary_chat_id="12345",
            telegram_summary_bot_token="token",
        ),
        request_json=lambda **_: {"messages": messages, "ok": True},
        send_telegram_message=lambda **_: {"status": "sent", "message_id": "81"},
    )

    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert report["status"] == "pass"
    assert report["telegram_summary"]["status"] == "idle"
    assert report["telegram_summary"]["new_message_count"] == 0
    assert report["telegram_summary"]["pending_message_count"] == 0
    assert state["telegram_summary"]["pending_message_hashes"] == []
    assert state["telegram_summary"]["pending_message_records"] == []


def test_telegram_summary_ignores_historical_conversation_fallback_messages(tmp_path: Path) -> None:
    module = _module()
    fallback_messages = [
        _text_message(id=f"wamid.history.summary.{index}", body_text=f"old msg {index}")
        for index in range(5)
    ]
    sent: list[dict[str, object]] = []

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        url = str(kwargs["url"])
        if url.endswith("/messages?take=100"):
            return {"messages": [], "ok": True}
        if "/conversations?" in url:
            return {
                "conversation_count": 1,
                "conversation_page_complete": True,
                "conversation_total": 1,
                "conversations": [{"message_count": len(fallback_messages), "messages": fallback_messages}],
                "ok": True,
            }
        return {"ok": True}

    report = module.build_report(
        _args(
            tmp_path,
            telegram_summary_enabled=True,
            telegram_summary_chat_id="12345",
            telegram_summary_bot_token="token",
        ),
        request_json=_fake_request_json,
        send_telegram_message=lambda **kwargs: sent.append(dict(kwargs)) or {"status": "sent", "message_id": "79"},
    )

    assert report["conversation_fallback"]["status"] == "pass"
    assert report["message_count"] == 5
    assert report["telegram_summary"]["status"] == "idle"
    assert report["telegram_summary"]["new_message_count"] == 0
    assert report["telegram_summary"]["pending_message_count"] == 0
    assert sent == []


def test_telegram_summary_drops_pending_records_that_are_now_out_of_scope(tmp_path: Path) -> None:
    module = _module()
    state_file = tmp_path / "wa-actions.json"
    state_file.write_text(
        json.dumps(
            {
                "version": 1,
                "actions": {},
                "telegram_summary": {
                    "seen_message_hashes": ["old-scope-hash"],
                    "pending_message_hashes": ["old-scope-hash"],
                    "pending_message_records": [
                        {
                            "message_hash": "old-scope-hash",
                            "heyy_ai_key": "executive_assistant",
                            "message_timestamp": "2026-06-23T10:00:00Z",
                            "summary_text": "old executive assistant message",
                            "summary_sender_mask": "...4006",
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    report = module.build_report(
        _args(
            tmp_path,
            telegram_summary_enabled=True,
            telegram_summary_chat_id="12345",
            telegram_summary_bot_token="token",
            telegram_summary_heyy_ai_keys="empathetic_slow_typing_old_lady",
        ),
        request_json=lambda **_kwargs: {"messages": [], "ok": True},
        send_telegram_message=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("out-of-scope pending records must not send")),
    )

    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert report["telegram_summary"]["status"] == "idle"
    assert report["telegram_summary"]["candidate_count"] == 0
    assert report["telegram_summary"]["new_message_count"] == 0
    assert report["telegram_summary"]["pending_message_count"] == 0
    assert state["telegram_summary"]["pending_message_hashes"] == []
    assert state["telegram_summary"]["pending_message_records"] == []


def test_conversation_fallback_records_noop_cooldown_after_only_processed_candidates(tmp_path: Path) -> None:
    module = _module()
    message = _selected_message(id="wamid.fallback.processed.1")
    callback_data = module._message_callback_data(message)
    action_id = module._action_id(session_ref="session-1", message_id="wamid.fallback.processed.1", callback_data=callback_data)
    state_file = tmp_path / "wa-actions.json"
    state_file.write_text(
        json.dumps({"version": 1, "actions": {action_id: {"status": "applied"}}}),
        encoding="utf-8",
    )

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        url = str(kwargs["url"])
        if url.endswith("/messages?take=100"):
            return {"messages": [], "ok": True}
        if "/conversations?" in url:
            return {
                "conversation_count": 1,
                "conversation_page_complete": False,
                "conversation_total": 160,
                "conversations": [{"message_count": 1, "messages": [message]}],
                "ok": True,
            }
        return {"ok": True}

    report = module.build_report(
        _args(
            tmp_path,
            conversation_fallback_noop_cooldown_seconds=0,
            conversation_fallback_noop_max_cooldown_seconds=0,
        ),
        request_json=_fake_request_json,
    )

    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert report["conversation_fallback"]["status"] == "pass"
    assert report["candidate_count"] == 1
    assert report["processed"] == 0
    assert report["skipped_processed"] == 1
    assert state["conversation_fallback"]["last_status"] == "pass"
    assert state["conversation_fallback"]["last_message_count"] == 1
    assert state["conversation_fallback"]["last_noop_at"]
    assert state["conversation_fallback"]["consecutive_noop_count"] == 1


def test_conversation_fallback_does_not_record_noop_for_empty_placeholder_noise(tmp_path: Path) -> None:
    module = _module()
    placeholder = _text_message(
        id="wamid.fallback.placeholder.1",
        body_present=False,
        body_text="",
        media_present=False,
        media_filename="",
        media_mime_type="",
        sender_digits="227775403311132",
        type="biz_content_placeholder",
    )
    state_file = tmp_path / "wa-actions.json"
    state_file.write_text(
        json.dumps(
            {
                "version": 1,
                "actions": {},
                "conversation_fallback": {
                    "last_noop_at": module._now_iso(),
                    "consecutive_noop_count": 4,
                },
            }
        ),
        encoding="utf-8",
    )

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        url = str(kwargs["url"])
        if url.endswith("/messages?take=100"):
            return {"messages": [], "ok": True}
        if "/conversations?" in url:
            return {
                "conversation_count": 1,
                "conversation_page_complete": True,
                "conversation_total": 1,
                "conversations": [{"message_count": 1, "messages": [placeholder]}],
                "ok": True,
            }
        return {"ok": True}

    report = module.build_report(
        _args(
            tmp_path,
            conversation_fallback_noop_cooldown_seconds=0,
            conversation_fallback_noop_max_cooldown_seconds=0,
        ),
        request_json=_fake_request_json,
    )

    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert report["conversation_fallback"]["status"] == "pass"
    assert report["conversation_fallback"]["message_count"] == 1
    assert report["conversation_fallback"]["meaningful_message_count"] == 0
    assert "last_noop_at" not in state["conversation_fallback"]
    assert "consecutive_noop_count" not in state["conversation_fallback"]


def test_conversation_fallback_recent_noop_cooldown_skips_conversation_fetch(tmp_path: Path) -> None:
    module = _module()
    state_file = tmp_path / "wa-actions.json"
    state_file.write_text(
        json.dumps(
            {
                "version": 1,
                "actions": {},
                "conversation_fallback": {"last_noop_at": module._now_iso()},
            }
        ),
        encoding="utf-8",
    )
    requested_urls: list[str] = []

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        url = str(kwargs["url"])
        requested_urls.append(url)
        if "/conversations?" in url:
            raise AssertionError("conversation fallback should be in cooldown")
        return {"messages": [], "ok": True}

    report = module.build_report(_args(tmp_path), request_json=_fake_request_json)

    assert len(requested_urls) == 1
    assert requested_urls[0].endswith("/messages?take=100")
    assert report["conversation_fallback"]["status"] == "cooldown"
    assert report["conversation_fallback"]["reason"] == "recent_noop"
    assert report["conversation_fallback"]["attempted"] is False


def test_conversation_fallback_recent_noop_cooldown_is_bypassed_when_direct_inbox_is_sparse(tmp_path: Path) -> None:
    module = _module()
    state_file = tmp_path / "wa-actions.json"
    state_file.write_text(
        json.dumps(
            {
                "version": 1,
                "actions": {},
                "conversation_fallback": {
                    "last_noop_at": module._now_iso(),
                    "consecutive_noop_count": 4,
                    "last_message_count": 311,
                },
            }
        ),
        encoding="utf-8",
    )

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        url = str(kwargs["url"])
        if url.endswith("/messages?take=100"):
            return {
                "messages": [
                    _text_message(
                        id="wamid.freeform.sparse.1",
                        body_text="worked",
                        heyy_ai_key="executive_assistant",
                        heyy_ai_name="Executive Assistant",
                        sender_digits="40424366432273",
                    )
                ],
                "inbox_count": 1,
                "ok": True,
            }
        if "/conversations?" in url:
            return {
                "conversation_count": 1,
                "conversation_page_complete": False,
                "conversation_total": 160,
                "conversations": [{"message_count": 1, "messages": [_epub_message(id="wamid.epub.sparse.1")]}],
                "ok": True,
            }
        raise AssertionError(f"unexpected url {url}")

    report = module.build_report(_args(tmp_path), request_json=_fake_request_json)

    assert report["conversation_fallback"]["attempted"] is True
    assert report["conversation_fallback"]["status"] == "pass"
    assert report["freeform_inbox_message_count"] == 1
    assert report["audiobook_source_candidate_count"] == 1
    assert report["epub_candidate_count"] == 1


def test_conversation_fallback_freeform_ignores_historical_unread_messages_older_than_age_window(tmp_path: Path) -> None:
    module = _module()

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        url = str(kwargs["url"])
        if url.endswith("/messages?take=100"):
            return {"messages": [], "ok": True}
        if "heyy-ai-routes?include_details=1" in url:
            return {
                "ok": True,
                "routes": [
                    {
                        "route_key": "default",
                        "ai_key": "empathetic_slow_typing_old_lady",
                        "ai_name": "Herta (Heyy Lady)",
                        "auto_reply_enabled": True,
                        "reply_text": "Na geh... ich bin die Herta. Schreib mir bitte kurz, ich bin beim Tippen langsam.",
                    }
                ],
            }
        if "/conversations?" in url:
            return {
                "conversation_count": 1,
                "conversation_page_complete": False,
                "conversation_total": 1,
                "conversations": [
                    {
                        "chat_ref": "chat-ref-old",
                        "is_group": False,
                        "unread_count": 2,
                        "messages": [
                            _text_message(
                                id="wamid.old.1",
                                body_text="Hallo Mama, neue Nummer.",
                                heyy_ai_key="empathetic_slow_typing_old_lady",
                                heyy_ai_name="Herta (Heyy Lady)",
                                sender_digits="40424366432273",
                                chat_ref="chat-ref-old",
                                message_timestamp="2026-06-20T12:03:33Z",
                            )
                        ],
                    }
                ],
                "ok": True,
            }
        raise AssertionError(f"unexpected url {url}")

    report = module.build_report(
        _args(tmp_path, freeform_conversation_fallback_max_age_seconds=3600),
        request_json=_fake_request_json,
    )

    assert report["status"] == "pass"
    assert report["conversation_fallback"]["attempted"] is True
    assert report["inbound_message_count"] == 1
    assert report["freeform_inbox_message_count"] == 0
    assert report["freeform_reply_sent"] == 0


def test_load_conversation_fallback_messages_treats_session_not_ready_as_waiting(tmp_path: Path) -> None:
    module = _module()

    def _fake_request_json(**_kwargs: object) -> dict[str, object]:
        raise RuntimeError('http_409:{"ok":false,"reason":"session_not_ready","status":"authenticated"}')

    messages, summary = module._load_conversation_fallback_messages(
        request_json=_fake_request_json,
        args=_args(tmp_path),
        base_url="https://wa-web.test",
        session_ref="session-1",
    )

    assert messages == []
    assert summary["attempted"] is True
    assert summary["status"] == "waiting"
    assert summary["reason"] == "session_not_ready"


def test_load_conversation_fallback_messages_treats_name_resolution_failure_as_waiting(tmp_path: Path) -> None:
    module = _module()

    def _fake_request_json(**_kwargs: object) -> dict[str, object]:
        raise RuntimeError("url_error:[Errno -3] Temporary failure in name resolution")

    messages, summary = module._load_conversation_fallback_messages(
        request_json=_fake_request_json,
        args=_args(tmp_path),
        base_url="https://wa-web.test",
        session_ref="session-1",
    )

    assert messages == []
    assert summary["attempted"] is True
    assert summary["status"] == "waiting"
    assert summary["reason"] == "session_api_name_resolution_failed"


def test_freeform_state_prunes_stale_terminal_entries(tmp_path: Path) -> None:
    module = _module()
    state = {
        "version": 1,
        "freeform": {
            "old-failed": {"processed_at": "2026-01-01T00:00:00Z", "reply_sent": False, "status": "failed"},
            "old-replied": {"processed_at": "2026-01-01T00:00:00Z", "reply_sent": True, "status": "replied"},
            "fresh-failed": {"processed_at": "2099-01-01T00:00:00Z", "reply_sent": False, "status": "failed"},
        },
    }
    args = _args(tmp_path, freeform_state_stale_seconds=60, freeform_state_max_entries=10)

    changed = module._prune_freeform_state(state, args=args)

    assert changed is True
    assert "old-failed" not in state["freeform"]
    assert "old-replied" not in state["freeform"]
    assert "fresh-failed" in state["freeform"]


def test_build_report_returns_waiting_when_messages_endpoint_name_resolution_fails(tmp_path: Path) -> None:
    module = _module()

    def _fake_request_json(**_kwargs: object) -> dict[str, object]:
        raise RuntimeError("url_error:[Errno -3] Temporary failure in name resolution")

    report = module.build_report(_args(tmp_path), request_json=_fake_request_json)

    assert report["status"] == "waiting"
    assert report["conversation_fallback"]["status"] == "waiting"
    assert report["conversation_fallback"]["reason"] == "session_api_name_resolution_failed"
    assert report["message_count"] == 0
    assert report["errors"] == 0


def test_main_returns_zero_for_waiting_report(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _module()
    args = _args(tmp_path)

    def _fake_request_json(**_kwargs: object) -> dict[str, object]:
        raise RuntimeError("url_error:[Errno -3] Temporary failure in name resolution")

    monkeypatch.setattr(module, "parse_args", lambda: args)
    monkeypatch.setattr(module, "_request_json", _fake_request_json)

    exit_code = module.main()

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["status"] == "waiting"
    assert payload["conversation_fallback"]["reason"] == "session_api_name_resolution_failed"
    state = json.loads((tmp_path / "wa-actions.json").read_text(encoding="utf-8"))
    assert state["session_ref"] == "session-1"
    assert state["last_run"]["status"] == "waiting"
    assert state["last_run"]["reason"] == "session_api_name_resolution_failed"


def test_build_report_persists_waiting_state_for_session_not_ready(monkeypatch, tmp_path: Path) -> None:
    module = _module()

    def _fake_request_json(**_kwargs: object) -> dict[str, object]:
        raise RuntimeError('http_409:{"ok":false,"reason":"session_not_ready","status":"authenticated"}')

    report = module.build_report(_args(tmp_path), request_json=_fake_request_json)

    assert report["status"] == "waiting"
    assert report["conversation_fallback"]["reason"] == "session_not_ready"
    state = json.loads((tmp_path / "wa-actions.json").read_text(encoding="utf-8"))
    assert state["session_ref"] == "session-1"
    assert state["last_run"]["status"] == "waiting"
    assert state["last_run"]["reason"] == "session_not_ready"


def test_build_report_marks_unresolved_freeform_sender_as_ignored(monkeypatch, tmp_path: Path) -> None:
    module = _module()

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        if kwargs["method"] == "GET":
            return {
                "messages": [
                    _text_message(
                        id="wamid.freeform.unresolved.1",
                        body_text="Hallo?",
                        sender_digits="",
                        sender_ref="",
                        chat_ref="",
                        heyy_ai_key="executive_assistant",
                        chat_id="false_0@c.us",
                    )
                ],
                "ok": True,
            }
        raise AssertionError("unexpected POST for unresolved sender")

    monkeypatch.setattr(module, "_load_heyy_ai_routes", lambda **_: [])

    report = module.build_report(_args(tmp_path), request_json=_fake_request_json)

    assert report["status"] == "pass"
    state = json.loads((tmp_path / "wa-actions.json").read_text(encoding="utf-8"))
    assert state["freeform"]["wamid.freeform.unresolved.1"]["status"] == "ignored"
    assert state["freeform"]["wamid.freeform.unresolved.1"]["reason"] == "sender_ref_unresolved"


def test_build_report_skips_terminal_freeform_state_entries(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    state_path = tmp_path / "wa-actions.json"
    state_path.write_text(
        json.dumps(
            {
                "version": 1,
                "freeform": {
                    "wamid.freeform.terminal.1": {
                        "processed_at": "2099-01-01T00:00:00Z",
                        "reply_sent": False,
                        "status": "ignored",
                        "reason": "sender_ref_unresolved",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        if kwargs["method"] == "GET":
            return {
                "messages": [
                    _text_message(
                        id="wamid.freeform.terminal.1",
                        body_text="Hallo?",
                        sender_digits="",
                        sender_ref="",
                        chat_ref="",
                        heyy_ai_key="executive_assistant",
                        chat_id="false_0@c.us",
                    )
                ],
                "ok": True,
            }
        raise AssertionError("unexpected POST for terminal freeform entry")

    monkeypatch.setattr(module, "_load_heyy_ai_routes", lambda **_: [])

    report = module.build_report(_args(tmp_path), request_json=_fake_request_json)

    assert report["status"] == "pass"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["freeform"]["wamid.freeform.terminal.1"]["status"] == "ignored"


def test_conversation_fallback_noop_cooldown_backs_off_and_resets_on_work(tmp_path: Path) -> None:
    module = _module()
    args = _args(
        tmp_path,
        conversation_fallback_noop_cooldown_seconds=60,
        conversation_fallback_noop_max_cooldown_seconds=300,
    )
    state = {"conversation_fallback": {"last_noop_at": module._now_iso(), "consecutive_noop_count": 3}}

    summary = module._conversation_fallback_cooldown_summary(args=args, state=state)

    assert summary is not None
    assert summary["status"] == "cooldown"
    assert summary["cooldown_seconds"] == 240
    assert summary["consecutive_noop_count"] == 3

    module._record_conversation_fallback_run(
        args=args,
        state=state,
        conversation_fallback={"attempted": True, "status": "pass", "message_count": 1},
        processed=1,
        epub_processed=0,
        voice_text_processed=0,
        status_processed=0,
        reply_sent=0,
        share_link_sent=0,
        voice_sample_sent=0,
    )

    assert "last_noop_at" not in state["conversation_fallback"]
    assert "consecutive_noop_count" not in state["conversation_fallback"]


def test_audiobook_access_approval_callback_secret_file(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    secret_path = tmp_path / "approval-callback-secret"
    secret_path.write_text("approval-secret-from-file\n", encoding="utf-8")
    monkeypatch.delenv("EA_AUDIOBOOK_ACCESS_APPROVAL_CALLBACK_SECRET", raising=False)
    monkeypatch.delenv("EA_TELEGRAM_CALLBACK_SECRET", raising=False)
    monkeypatch.delenv("EA_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("EA_AUDIOBOOK_ACCESS_APPROVAL_CALLBACK_SECRET_FILE", str(secret_path))

    callback = module.audiobook_access_approval.encode_telegram_approval_callback(
        action="a",
        approval_id="apr20260621T000000Z1234567890",
        approver_chat_id="42",
        expires_at=FUTURE_EXPIRY,
    )
    decoded = module.audiobook_access_approval.decode_telegram_approval_callback(
        callback_data=callback,
        approver_chat_id="42",
    )

    assert callback.startswith("aa|a|")
    assert decoded["ok"] is True
    assert decoded["action"] == "approve"
    assert decoded["approval_id"] == "apr20260621T000000Z1234567890"


def test_build_report_processes_selected_button_and_sends_reply(tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    handled: list[dict[str, object]] = []

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {"messages": [_selected_message()], "ok": True}
        return {"ok": True, "message_id": "wamid.reply.1"}

    def _fake_handle_callback(**kwargs: object) -> dict[str, object]:
        handled.append(dict(kwargs))
        return {
            "status": "applied",
            "kind": "audiobook_voice",
            "action": "use",
            "reply_text": "Voice selected.",
        }

    report = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
        handle_callback=_fake_handle_callback,
    )

    assert report["status"] == "pass"
    assert report["candidate_count"] == 1
    assert report["processed"] == 1
    assert report["reply_sent"] == 1
    assert handled == [
        {
            "callback_data": "ab|u|voice-token-1|1v7j5c0|sig",
            "sender_ref": "4368120864006",
            "message_id": "wamid.inbound.1",
        }
    ]
    post_request = requests[1]
    assert post_request["url"] == "https://wa-web.test/sessions/session-1/messages"
    assert post_request["body"] == {
        "to": "4368120864006",
        "text": "Voice selected.",
        "heyy_ai_key": "empathetic_slow_typing_old_lady",
        "heyy_ai_name": "Herta (Heyy Lady)",
        "pre_reply_delay_max_seconds": 1800,
        "pre_reply_delay_min_seconds": 180,
        "quiet_hours_end_hour": 6,
        "quiet_hours_start_hour": 21,
        "typing_delay_ms": 6500,
        "typing_delay_ms_per_character": 8000,
        "typing_status_enabled": True,
    }
    assert post_request["timeout"] >= 921.5

    state = json.loads((tmp_path / "wa-actions.json").read_text(encoding="utf-8"))
    action = next(iter(state["actions"].values()))
    serialized_state = json.dumps(state)
    assert action["status"] == "applied"
    assert action["reply_sent"] is True
    assert "4368120864006" not in serialized_state
    assert "voice-token-1" not in serialized_state


def test_build_report_restores_language_matched_voice_batch_from_management_button(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-wa-restore"
    sample_dir = job_dir / "voice_audition" / "samples"
    sample_dir.mkdir(parents=True)
    _write_test_wav(sample_dir / "german-token.wav")
    job = {
        "job_id": "job-wa-restore",
        "status": "waiting_voice_selection",
        "metadata": {"title": "German Book", "language": "de"},
        "storage": {"job_dir": str(job_dir)},
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "reason": "voice_catalog_language_relaxed_after_dismissals",
                "language_relaxed_after_dismissals": True,
                "dismissed_candidate_keys": ["voice-german"],
                "pending_candidate_keys": ["voice-italian"],
                "pending_batch": [
                    {
                        "preset_key": "voice-italian",
                        "callback_token": "italian-token",
                        "label": "Italian",
                        "language": "it-it",
                    }
                ],
            }
        },
                        "whatsapp": {
            "chat_ref": "chat-ref-1",
            "sender_ref": "4368120864006",
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")
    (job_dir / "voice_audition" / "private.json").write_text(
        json.dumps(
            {
                "candidates": {
                    "german-token": {
                        "candidate_key": "voice-german",
                        "voice_id": "secret-german-voice",
                        "public": {
                            "callback_token": "german-token",
                            "label": "Florian",
                            "language": "de-de",
                            "preset_key": "voice-german",
                            "sample_audio_ready": True,
                            "sample_file": "german-token.wav",
                            "score": 12,
                            "supported_languages": ["de-de"],
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(module, "_whatsapp_voice_sample_media_path", lambda path: path)
    control_token = module._whatsapp_audiobook_management_token(job)
    callback_data = module.whatsapp_inbound_actions.encode_whatsapp_audiobook_management_callback(
        action="r",
        token=control_token,
        sender_ref="4368120864006",
        expires_at=FUTURE_EXPIRY,
    )

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {
                "messages": [
                    _selected_message(
                        chat_ref="chat-ref-1",
                        selected_button_id=callback_data,
                        selected_button_kind="audiobook_voice_management",
                    )
                ],
                "ok": True,
            }
        return {"ok": True, "message_id": f"wamid.out.{len(requests)}", "button_count": 2}

    report = module.build_report(_args(tmp_path), request_json=_fake_request_json)

    assert report["status"] == "pass"
    assert report["candidate_count"] == 1
    assert report["processed"] == 1
    assert report["voice_sample_sent"] == 1
    assert report["reply_sent"] == 1
    posts = [row for row in requests if row["method"] == "POST"]
    assert any(dict(row["body"]).get("media_filename") == "german-token.wav" for row in posts)
    assert any("Restored the best language-matched voices" in str(dict(row["body"]).get("text") or "") for row in posts)
    restored_job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    selection = restored_job["provider"]["voice_selection"]
    assert selection["reason"] == "language_matched_voice_restored"
    assert selection["pending_candidate_keys"] == ["voice-german"]
    assert "voice-german" not in selection["dismissed_candidate_keys"]


def test_restore_language_matched_whatsapp_voice_samples_prefers_author_gender_match(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-restore-author-gender"
    sample_dir = job_dir / "voice_audition" / "samples"
    sample_dir.mkdir(parents=True)
    _write_test_wav(sample_dir / "female-token.wav")
    _write_test_wav(sample_dir / "male-token.wav")
    job = {
        "job_id": "job-restore-author-gender",
        "status": "waiting_voice_selection",
        "storage": {"job_dir": str(job_dir)},
        "metadata": {"author": "Knuf, Andreas", "language": "de", "title": "Widerstand zwecklos"},
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "book_profile": {
                    "author_gender_signal": "male",
                    "author_gender_signal_provenance": "explicit_approved_metadata",
                },
                "dismissed_candidate_keys": ["voice-female", "voice-male"],
            }
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")
    (job_dir / "voice_audition" / "private.json").write_text(
        json.dumps(
            {
                "candidates": {
                    "female-token": {
                        "candidate_key": "voice-female",
                        "voice_id": "secret-female-voice",
                        "public": {
                            "callback_token": "female-token",
                            "label": "Seraphina",
                            "language": "de-de",
                            "preset_key": "voice-female",
                            "sample_audio_ready": True,
                            "sample_file": "female-token.wav",
                            "sample_sha256": "sha-female",
                            "score": 99,
                            "supported_languages": ["de-de"],
                            "tags": ["female"],
                            "author_gender_match": False,
                        },
                    },
                    "male-token": {
                        "candidate_key": "voice-male",
                        "voice_id": "secret-male-voice",
                        "public": {
                            "callback_token": "male-token",
                            "label": "Florian",
                            "language": "de-de",
                            "preset_key": "voice-male",
                            "sample_audio_ready": True,
                            "sample_file": "male-token.wav",
                            "sample_sha256": "sha-male",
                            "score": 12,
                            "supported_languages": ["de-de"],
                            "tags": ["male"],
                            "author_gender_match": True,
                        },
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    def _write_job(payload: dict[str, object]) -> dict[str, object]:
        (job_dir / "job.json").write_text(json.dumps(payload), encoding="utf-8")
        return payload

    monkeypatch.setattr(module, "_write_job_to_disk", _write_job)

    restored, restored_count = module._restore_language_matched_whatsapp_voice_samples(job)

    assert restored_count == 1
    selection = restored["provider"]["voice_selection"]
    assert selection["pending_candidate_keys"] == ["voice-male"]
    assert selection["pending_batch"][0]["label"] == "Florian"
    assert "voice-male" not in selection["dismissed_candidate_keys"]


def test_use_best_current_whatsapp_voice_sample_prefers_author_gender_match(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    job_dir = tmp_path / "job-best-current-author-gender"
    job_dir.mkdir(parents=True)
    job = {
        "job_id": "job-best-current-author-gender",
        "status": "waiting_voice_selection",
        "storage": {"job_dir": str(job_dir)},
        "metadata": {"author": "Knuf, Andreas", "language": "de", "title": "Widerstand zwecklos"},
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "book_profile": {
                    "author_gender_signal": "male",
                    "author_gender_signal_provenance": "explicit_approved_metadata",
                },
                "pending_batch": [
                    {
                        "callback_token": "female-token",
                        "label": "Seraphina",
                        "score": 99,
                        "tags": ["female"],
                    },
                    {
                        "callback_token": "male-token",
                        "label": "Florian",
                        "score": 12,
                        "tags": ["male"],
                    },
                ],
            }
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")
    selected: list[dict[str, object]] = []

    def _fake_apply_audition_action(*, callback_token: str, action: str) -> dict[str, object]:
        selected.append({"callback_token": callback_token, "action": action})
        return {"status": "selected", "callback_token": callback_token, "action": action}

    monkeypatch.setattr(module.audiobook_epub_pipeline, "apply_audiobook_voice_audition_action", _fake_apply_audition_action)

    result = module._use_best_current_whatsapp_voice_sample(job)

    assert result["callback_token"] == "male-token"
    assert selected == [{"callback_token": "male-token", "action": "use"}]


def test_build_report_recovers_sender_ref_for_chat_ref_only_voice_button(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    handled: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-chat-ref-button"
    job_dir.mkdir(parents=True)
    job = {
        "job_id": "job-chat-ref-button",
        "status": "waiting_voice_selection",
        "storage": {"job_dir": str(job_dir)},
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "pending_batch": [
                    {
                        "preset_key": "voice-1",
                        "callback_token": "voice-token-1",
                    }
                ],
            }
        },
        "whatsapp": {
            "chat_ref": "chat-ref-1",
            "sender_ref": "4368120864006",
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {
                "messages": [
                    _selected_message(
                        chat_ref="chat-ref-1",
                        sender_digits="",
                    )
                ],
                "ok": True,
            }
        return {"ok": True, "message_id": "wamid.reply.1"}

    def _fake_handle_callback(**kwargs: object) -> dict[str, object]:
        handled.append(dict(kwargs))
        return {
            "status": "applied",
            "kind": "audiobook_voice",
            "action": "use",
            "reply_text": "Voice selected.",
        }

    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)

    report = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
        handle_callback=_fake_handle_callback,
    )

    assert report["status"] == "pass"
    assert report["candidate_count"] == 1
    assert report["processed"] == 1
    assert report["reply_sent"] == 1
    assert handled == [
        {
            "callback_data": "ab|u|voice-token-1|1v7j5c0|sig",
            "sender_ref": "4368120864006",
            "message_id": "wamid.inbound.1",
        }
    ]
    post_request = requests[1]
    assert post_request["body"]["to"] == "4368120864006"
    assert post_request["body"]["chat_ref"] == "chat-ref-1"


def test_build_report_recovers_sender_ref_for_chat_ref_only_stale_voice_button(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    handled: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-stale-chat-ref-button"
    private_dir = job_dir / "voice_audition"
    private_dir.mkdir(parents=True)
    job = {
        "job_id": "job-stale-chat-ref-button",
        "status": "waiting_voice_selection",
        "storage": {"job_dir": str(job_dir)},
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "pending_batch": [
                    {
                        "preset_key": "voice-current",
                        "callback_token": "voice-token-current",
                    }
                ],
            }
        },
        "whatsapp": {
            "chat_ref": "chat-ref-1",
            "sender_ref": "4368120864006",
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")
    (private_dir / "private.json").write_text(
        json.dumps(
            {
                "candidates": {
                    "voice-token-old": {
                        "candidate_key": "voice-old",
                        "public": {"label": "Old Voice"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {
                "messages": [
                    _selected_message(
                        chat_ref="chat-ref-1",
                        selected_button_id="ab|u|voice-token-old|1v7j5c0|sig",
                        sender_digits="",
                    )
                ],
                "ok": True,
            }
        return {"ok": True, "message_id": "wamid.reply.1"}

    def _fake_handle_callback(**kwargs: object) -> dict[str, object]:
        handled.append(dict(kwargs))
        return {
            "status": "stale",
            "kind": "audiobook_voice",
            "reason": "stale_candidate_ignored",
            "reply_text": "That audiobook voice button is stale, so I ignored it. Use the latest voice sample buttons, or reply with the voice name or 'dismiss all'.",
        }

    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)

    report = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
        handle_callback=_fake_handle_callback,
    )

    assert report["status"] == "pass"
    assert report["processed"] == 1
    assert report["reply_sent"] == 1
    assert handled == [
        {
            "callback_data": "ab|u|voice-token-old|1v7j5c0|sig",
            "sender_ref": "4368120864006",
            "message_id": "wamid.inbound.1",
        }
    ]
    post_request = requests[1]
    assert post_request["body"]["to"] == "4368120864006"
    assert post_request["body"]["chat_ref"] == "chat-ref-1"
    assert "stale" in str(post_request["body"]["text"])


def test_latest_waiting_whatsapp_voice_selection_job_prefers_matching_chat_ref(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    jobs_root = tmp_path / "jobs"

    def _write_job(job_dir: Path, *, job_id: str, chat_ref: str) -> None:
        job_dir.mkdir(parents=True)
        (job_dir / "job.json").write_text(
            json.dumps(
                {
                    "job_id": job_id,
                    "status": "waiting_voice_selection",
                    "storage": {"job_dir": str(job_dir)},
                    "provider": {
                        "voice_selection": {
                            "status": "waiting_user_choice",
                            "pending_batch": [{"label": "Remy", "callback_token": f"{job_id}-token"}],
                        }
                    },
                    "whatsapp": {"sender_ref": "4368120864006", "chat_ref": chat_ref},
                }
            ),
            encoding="utf-8",
        )

    target_dir = jobs_root / "job-a-target"
    other_dir = jobs_root / "job-z-other"
    _write_job(target_dir, job_id="target-chat-job", chat_ref="chat-ref-1")
    _write_job(other_dir, job_id="other-chat-job", chat_ref="chat-ref-2")

    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)

    job = module._latest_waiting_whatsapp_voice_selection_job(
        sender_digits="4368120864006",
        chat_ref="chat-ref-1",
    )

    assert job["job_id"] == "target-chat-job"


def test_build_report_processes_whatsapp_epub_media_and_sends_voice_samples(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    downloads: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"
    sample_path = tmp_path / "voice-sample.mp3"
    sample_path.write_bytes(b"ID3sample")

    job: dict[str, object] = {
        "job_id": "job-wa-epub-1",
        "status": "waiting_voice_selection",
        "metadata": {"title": "Book", "language": "en"},
        "storage": {"job_dir": str(tmp_path / "job-wa-epub-1")},
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "pending_batch": [{"preset_key": "voice-1", "callback_token": "sample-token-1"}],
            }
        },
    }
    (tmp_path / "job-wa-epub-1").mkdir()
    (tmp_path / "job-wa-epub-1" / "job.json").write_text(json.dumps(job), encoding="utf-8")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {"messages": [_epub_message()], "ok": True}
        return {"ok": True, "message_id": f"wamid.out.{len(requests)}", "button_count": 2, "buttons_fallback": True}

    def _fake_request_bytes(**kwargs: object) -> bytes:
        downloads.append(dict(kwargs))
        return b"fake epub"

    def _fake_create_job_from_epub(**kwargs: object) -> dict[str, object]:
        assert kwargs["original_filename"] == "book.epub"
        assert Path(str(kwargs["epub_path"])).read_bytes() == b"fake epub"
        assert kwargs["principal_id"] == "exec-1"
        return _bound_fake_approved_job(
            module,
            template=job,
            create_kwargs=dict(kwargs),
        )

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_INSTANT_PHONE_WHITELIST", "4368120864006")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(module.audiobook_epub_pipeline, "create_job_from_epub", _fake_create_job_from_epub)
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "audiobook_voice_audition_sample_messages",
        lambda _job: [{"token": "sample-token-1", "label": "Narrator One", "matched_tags": ["clear"], "audio_path": str(sample_path)}],
    )
    monkeypatch.setattr(module, "_whatsapp_voice_sample_media_path", lambda path: path)
    monkeypatch.setattr(module.audiobook_epub_pipeline, "record_audiobook_voice_sample_delivery", lambda *, job, sample_receipts: job)
    monkeypatch.setattr(module.audiobook_epub_pipeline, "telegram_epub_reply_text", lambda _job: "I sent samples in Telegram.")

    report = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
        request_bytes=_fake_request_bytes,
    )

    assert report["status"] == "pass"
    assert report["audiobook_source_candidate_count"] == 1
    assert report["epub_candidate_count"] == 1
    assert report["epub_processed"] == 1
    assert report["voice_sample_sent"] == 1
    assert report["reply_sent"] == 1
    assert downloads[0]["url"] == "https://wa-web.test/sessions/session-1/messages/wamid.epub.1/media"
    media_post = [row for row in requests if row["method"] == "POST" and dict(row["body"]).get("media_base64")]
    button_post = [row for row in requests if row["method"] == "POST" and dict(row["body"]).get("buttons")]
    text_post = [row for row in requests if row["method"] == "POST" and dict(row["body"]).get("text") == "I sent samples in WhatsApp."]
    assert len(media_post) == 1
    assert dict(media_post[0]["body"])["media_mimetype"] == "audio/mpeg"
    assert dict(media_post[0]["body"])["chat_ref"] == "chat-ref-1"
    assert len(button_post) == 1
    assert dict(button_post[0]["body"])["chat_ref"] == "chat-ref-1"
    buttons = dict(button_post[0]["body"])["buttons"]
    assert buttons[0][0][0] == "Use Narrator One"
    assert buttons[0][1][0] == "Dismiss Narrator One"
    assert buttons[0][2][0] == "Use automatic cast"
    assert str(buttons[0][0][1]).startswith("ab|u|sample-token-1|")
    assert str(buttons[0][1][1]).startswith("ab|d|sample-token-1|")
    assert str(buttons[0][2][1]).startswith("ab|a|sample-token-1|")
    assert "preview is optional" in str(dict(button_post[0]["body"])["text"]).lower()
    assert "use automatic cast" in str(dict(button_post[0]["body"])["text"]).lower()
    assert len(text_post) == 1
    assert dict(text_post[0]["body"])["chat_ref"] == "chat-ref-1"


def test_build_report_processes_whatsapp_azw3_media_as_audiobook_source(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    downloads: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"
    sample_path = tmp_path / "voice-sample.mp3"
    sample_path.write_bytes(b"ID3sample")

    job: dict[str, object] = {
        "job_id": "job-wa-azw3-1",
        "status": "waiting_voice_selection",
        "metadata": {"title": "Kindle Book", "language": "en"},
        "storage": {"job_dir": str(tmp_path / "job-wa-azw3-1")},
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "pending_batch": [{"preset_key": "voice-1", "callback_token": "sample-token-1"}],
            }
        },
    }
    (tmp_path / "job-wa-azw3-1").mkdir()
    (tmp_path / "job-wa-azw3-1" / "job.json").write_text(json.dumps(job), encoding="utf-8")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {
                "messages": [
                    _epub_message(
                        id="wamid.azw3.1",
                        media_filename="kindle-book.azw3",
                        media_mime_type="application/vnd.amazon.ebook",
                    )
                ],
                "ok": True,
            }
        return {"ok": True, "message_id": f"wamid.azw3.out.{len(requests)}", "button_count": 2}

    def _fake_request_bytes(**kwargs: object) -> bytes:
        downloads.append(dict(kwargs))
        return b"fake kindle bytes"

    def _fake_create_job_from_epub(**kwargs: object) -> dict[str, object]:
        assert kwargs["original_filename"] == "kindle-book.azw3"
        assert Path(str(kwargs["epub_path"])).suffix == ".azw3"
        assert Path(str(kwargs["epub_path"])).read_bytes() == b"fake kindle bytes"
        return _bound_fake_approved_job(
            module,
            template=job,
            create_kwargs=dict(kwargs),
        )

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_INSTANT_PHONE_WHITELIST", "4368120864006")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(module.audiobook_epub_pipeline, "create_job_from_epub", _fake_create_job_from_epub)
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "audiobook_voice_audition_sample_messages",
        lambda _job: [{"token": "sample-token-1", "label": "Narrator One", "matched_tags": ["clear"], "audio_path": str(sample_path)}],
    )
    monkeypatch.setattr(module, "_whatsapp_voice_sample_media_path", lambda path: path)
    monkeypatch.setattr(module.audiobook_epub_pipeline, "record_audiobook_voice_sample_delivery", lambda *, job, sample_receipts: job)
    monkeypatch.setattr(module.audiobook_epub_pipeline, "telegram_epub_reply_text", lambda _job: "I sent samples in Telegram.")

    report = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
        request_bytes=_fake_request_bytes,
    )

    assert report["status"] == "pass"
    assert report["audiobook_source_candidate_count"] == 1
    assert report["epub_candidate_count"] == 1
    assert report["epub_processed"] == 1
    assert report["voice_sample_sent"] == 1
    assert downloads[0]["url"] == "https://wa-web.test/sessions/session-1/messages/wamid.azw3.1/media"
    button_post = [row for row in requests if row["method"] == "POST" and dict(row["body"]).get("buttons")]
    assert len(button_post) == 1
    buttons = dict(button_post[0]["body"])["buttons"][0]
    assert buttons[0][0] == "Use Narrator One"
    assert buttons[1][0] == "Dismiss Narrator One"


def test_build_report_processes_whatsapp_epub_for_phone_whitelist_file(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"
    whitelist_path = tmp_path / "instant-whatsapp-numbers.txt"
    whitelist_path.write_text("+43 681 208 640 06\n", encoding="utf-8")
    sample_path = tmp_path / "voice-sample.mp3"
    sample_path.write_bytes(b"ID3sample")
    job: dict[str, object] = {
        "job_id": "job-wa-epub-whitelist-file",
        "status": "waiting_voice_selection",
        "metadata": {"title": "Whitelist File Book", "language": "en"},
        "storage": {"job_dir": str(tmp_path / "job-wa-epub-whitelist-file")},
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "pending_batch": [{"preset_key": "voice-1", "callback_token": "sample-token-1"}],
            }
        },
    }
    Path(str(job["storage"]["job_dir"])).mkdir()
    (Path(str(job["storage"]["job_dir"])) / "job.json").write_text(json.dumps(job), encoding="utf-8")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {"messages": [_epub_message()], "ok": True}
        return {"ok": True, "message_id": f"wamid.whitelist-file.{len(requests)}", "button_count": 2}

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.delenv("EA_AUDIOBOOK_INSTANT_PHONE_WHITELIST", raising=False)
    monkeypatch.setenv("EA_AUDIOBOOK_INSTANT_PHONE_WHITELIST_FILE", str(whitelist_path))
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "create_job_from_epub",
        lambda **kwargs: _bound_fake_approved_job(
            module,
            template=job,
            create_kwargs=dict(kwargs),
        ),
    )
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "audiobook_voice_audition_sample_messages",
        lambda _job: [{"token": "sample-token-1", "label": "Narrator One", "matched_tags": ["clear"], "audio_path": str(sample_path)}],
    )
    monkeypatch.setattr(module, "_whatsapp_voice_sample_media_path", lambda path: path)
    monkeypatch.setattr(module.audiobook_epub_pipeline, "record_audiobook_voice_sample_delivery", lambda *, job, sample_receipts: job)
    monkeypatch.setattr(module.audiobook_epub_pipeline, "telegram_epub_reply_text", lambda _job: "I sent samples in Telegram.")

    report = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
        request_bytes=lambda **_: b"fake epub",
    )

    assert report["status"] == "pass"
    assert report["epub_processed"] == 1
    assert report["voice_sample_sent"] == 1
    assert report["reply_sent"] == 1
    approval_root = jobs_root / "_access_approvals"
    approvals = list(approval_root.glob("*.json"))
    assert len(approvals) == 1
    trusted_approval = json.loads(approvals[0].read_text(encoding="utf-8"))
    assert trusted_approval["decided_by"] == "whatsapp_trusted_sender_policy"
    assert trusted_approval["status"] == "started"
    button_post = [row for row in requests if row["method"] == "POST" and dict(row["body"]).get("buttons")]
    assert len(button_post) == 1
    state = json.loads((tmp_path / "wa-actions.json").read_text(encoding="utf-8"))
    serialized_state = json.dumps(state)
    assert "4368120864006" not in serialized_state
    assert str(whitelist_path) not in serialized_state


def test_build_report_retries_failed_whatsapp_epub_without_reply(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"
    sample_path = tmp_path / "voice-sample.mp3"
    sample_path.write_bytes(b"ID3sample")
    message = _epub_message()
    action_id = module._action_id(
        session_ref="session-1",
        message_id=str(message["id"]),
        callback_data="epub_media",
    )
    state_path = tmp_path / "wa-actions.json"
    state_path.write_text(
        json.dumps(
            {
                "actions": {
                    action_id: {
                        "callback_hash": module._sha("epub_media"),
                        "kind": "audiobook_epub",
                        "message_hash": module._sha(message["id"]),
                        "processed_at": "2026-06-22T05:20:37Z",
                        "reason": "RuntimeError",
                        "reply_sent": False,
                        "status": "failed",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    job: dict[str, object] = {
        "job_id": "job-wa-epub-retry",
        "status": "waiting_voice_selection",
        "metadata": {"title": "Retry Book", "language": "en"},
        "storage": {"job_dir": str(tmp_path / "job-wa-epub-retry")},
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "pending_batch": [{"preset_key": "voice-1", "callback_token": "sample-token-1"}],
            }
        },
    }
    Path(str(job["storage"]["job_dir"])).mkdir()
    (Path(str(job["storage"]["job_dir"])) / "job.json").write_text(json.dumps(job), encoding="utf-8")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {"messages": [message], "ok": True}
        return {"ok": True, "message_id": f"wamid.retry.out.{len(requests)}", "button_count": 2}

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_INSTANT_PHONE_WHITELIST", "4368120864006")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "create_job_from_epub",
        lambda **kwargs: _bound_fake_approved_job(
            module,
            template=job,
            create_kwargs=dict(kwargs),
        ),
    )
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "audiobook_voice_audition_sample_messages",
        lambda _job: [{"token": "sample-token-1", "label": "Narrator One", "matched_tags": ["clear"], "audio_path": str(sample_path)}],
    )
    monkeypatch.setattr(module, "_whatsapp_voice_sample_media_path", lambda path: path)
    monkeypatch.setattr(module.audiobook_epub_pipeline, "record_audiobook_voice_sample_delivery", lambda *, job, sample_receipts: job)
    monkeypatch.setattr(module.audiobook_epub_pipeline, "telegram_epub_reply_text", lambda _job: "I sent samples in Telegram.")

    report = module.build_report(
        _args(tmp_path, state_file=str(state_path)),
        request_json=_fake_request_json,
        request_bytes=lambda **_: b"fake epub",
    )

    assert report["status"] == "pass"
    assert report["skipped_processed"] == 0
    assert report["epub_processed"] == 1
    assert report["voice_sample_sent"] == 1
    state = json.loads(state_path.read_text(encoding="utf-8"))
    action = state["actions"][action_id]
    assert action["status"] == "applied"
    assert action["retry_reason"] == "RuntimeError"
    assert action["reply_sent"] is True


def test_build_report_retries_zero_sample_whatsapp_epub_once(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"
    sample_path = tmp_path / "voice-sample.mp3"
    sample_path.write_bytes(b"ID3sample")
    message = _epub_message()
    action_id = module._action_id(
        session_ref="session-1",
        message_id=str(message["id"]),
        callback_data="epub_media",
    )
    state_path = tmp_path / "wa-actions.json"
    state_path.write_text(
        json.dumps(
            {
                "actions": {
                    action_id: {
                        "callback_hash": module._sha("epub_media"),
                        "kind": "audiobook_epub",
                        "message_hash": module._sha(message["id"]),
                        "processed_at": "2026-06-22T05:20:37Z",
                        "reply_sent": True,
                        "sample_sent": 0,
                        "status": "applied",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    job: dict[str, object] = {
        "job_id": "job-wa-epub-zero-sample-retry",
        "status": "waiting_voice_selection",
        "metadata": {"title": "Retry Book", "language": "en"},
        "storage": {"job_dir": str(tmp_path / "job-wa-epub-zero-sample-retry")},
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "pending_batch": [{"preset_key": "voice-1", "callback_token": "sample-token-1"}],
            }
        },
    }
    Path(str(job["storage"]["job_dir"])).mkdir()
    (Path(str(job["storage"]["job_dir"])) / "job.json").write_text(json.dumps(job), encoding="utf-8")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {"messages": [message], "ok": True}
        return {"ok": True, "message_id": f"wamid.zero.out.{len(requests)}", "button_count": 2}

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_INSTANT_PHONE_WHITELIST", "4368120864006")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "create_job_from_epub",
        lambda **kwargs: _bound_fake_approved_job(
            module,
            template=job,
            create_kwargs=dict(kwargs),
        ),
    )
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "audiobook_voice_audition_sample_messages",
        lambda _job: [{"token": "sample-token-1", "label": "Narrator One", "matched_tags": ["clear"], "audio_path": str(sample_path)}],
    )
    monkeypatch.setattr(module, "_whatsapp_voice_sample_media_path", lambda path: path)
    monkeypatch.setattr(module.audiobook_epub_pipeline, "record_audiobook_voice_sample_delivery", lambda *, job, sample_receipts: job)
    monkeypatch.setattr(module.audiobook_epub_pipeline, "telegram_epub_reply_text", lambda _job: "I sent samples in Telegram.")

    report = module.build_report(
        _args(tmp_path, state_file=str(state_path)),
        request_json=_fake_request_json,
        request_bytes=lambda **_: b"fake epub",
    )

    assert report["status"] == "pass"
    assert report["skipped_processed"] == 0
    assert report["epub_processed"] == 1
    assert report["voice_sample_sent"] == 1
    state = json.loads(state_path.read_text(encoding="utf-8"))
    action = state["actions"][action_id]
    assert action["status"] == "applied"
    assert action["sample_sent"] == 1
    assert action["retry_reason"] == "zero_voice_samples"
    assert action["zero_sample_retry_count"] == 1
    assert action["zero_sample_previous_status"] == "applied"


def test_send_whatsapp_voice_samples_rejects_clipped_audio_before_upload(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    sample_path = tmp_path / "clipped.wav"
    sample_rate = 16000
    with wave.open(str(sample_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"".join(struct.pack("<h", 32767 if i % 2 else -32768) for i in range(sample_rate // 4)))
    job = {
        "job_id": "job-clipped-sample",
        "metadata": {"title": "Clipped Sample"},
        "whatsapp": {"chat_ref": "chat-ref-1"},
        "provider": {"voice_selection": {"pending_batch": []}},
    }
    posts: list[dict[str, object]] = []

    def _request_json(**kwargs: object) -> dict[str, object]:
        posts.append(dict(kwargs))
        return {"ok": True, "message_id": "wamid.should-not-send"}

    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_SAMPLE_AUDIO_QUALITY_GATE_ENABLED", "1")
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "audiobook_voice_audition_sample_messages",
        lambda _job: [
            {
                "token": "sample-token-1",
                "label": "Clipped",
                "matched_tags": ["test"],
                "audio_path": str(sample_path),
            }
        ],
    )

    receipts = module._send_whatsapp_voice_samples(
        request_json=_request_json,
        args=_args(tmp_path),
        recipient_digits="4368120864006",
        job=job,
    )

    assert posts == []
    assert receipts == [
        {
            "token": "sample-token-1",
            "status": "failed",
            "reason": "voice_sample_audio_quality_failed:clipping",
            "audio_quality_status": "failed",
            "audio_quality_issues": ["clipping"],
            "expected_effect_count": 2,
            "confirmed_effect_count": 0,
            "known_no_effect_count": 2,
            "ambiguous_effect_count": 0,
        }
    ]


def test_build_report_blocks_whatsapp_epub_when_voice_sample_quality_fails(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"
    job_dir = tmp_path / "job-clipped-epub"
    job_dir.mkdir()
    sample_path = tmp_path / "clipped.wav"
    with wave.open(str(sample_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"".join(struct.pack("<h", 32767 if i % 2 else -32768) for i in range(16000 // 4)))
    job = {
        "job_id": "job-clipped-epub",
        "status": "waiting_voice_selection",
        "metadata": {"title": "Clipped EPUB", "language": "en"},
        "storage": {"job_dir": str(job_dir)},
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "pending_batch": [{"preset_key": "voice-1", "callback_token": "sample-token-1"}],
            }
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {"messages": [_epub_message()], "ok": True}
        return {"ok": True, "message_id": f"wamid.quality.out.{len(requests)}", "button_count": 0}

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_INSTANT_PHONE_WHITELIST", "4368120864006")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_SAMPLE_AUDIO_QUALITY_GATE_ENABLED", "1")
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "create_job_from_epub",
        lambda **kwargs: _bound_fake_approved_job(
            module,
            template=job,
            create_kwargs=dict(kwargs),
        ),
    )
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "audiobook_voice_audition_sample_messages",
        lambda _job: [
            {
                "token": "sample-token-1",
                "label": "Clipped",
                "matched_tags": ["test"],
                "audio_path": str(sample_path),
            }
        ],
    )

    report = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
        request_bytes=lambda **_: b"fake epub",
    )

    assert report["status"] == "partial"
    assert report["epub_processed"] == 1
    assert report["voice_sample_sent"] == 0
    media_posts = [row for row in requests if row["method"] == "POST" and dict(row["body"]).get("media_base64")]
    button_posts = [row for row in requests if row["method"] == "POST" and dict(row["body"]).get("buttons")]
    reply_posts = [row for row in requests if row["method"] == "POST" and dict(row["body"]).get("text")]
    assert media_posts == []
    assert button_posts == []
    assert any("could not deliver" in str(dict(row["body"]).get("text") or "") for row in reply_posts)
    state = json.loads((tmp_path / "wa-actions.json").read_text(encoding="utf-8"))
    action = next(iter(dict(state["actions"]).values()))
    assert action["status"] == "delivery_outcome_unknown"
    assert action["delivery_status"] == "outcome_unknown"
    assert action["sample_sent"] == 0


def test_whatsapp_voice_sample_media_validation_rejects_wrong_sample_rate(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    media_path = tmp_path / "sample.mp3"
    media_path.write_bytes(b"fake mp3 bytes")
    monkeypatch.setenv("EA_WHATSAPP_VOICE_SAMPLE_TRANSCODE_QUALITY_GATE_ENABLED", "1")
    monkeypatch.setattr(
        module,
        "_ffprobe_audio_stream",
        lambda _path: {
            "stream": {"codec_name": "mp3", "sample_rate": "48000", "channels": 1},
            "format": {"duration": "1.5"},
        },
    )

    with pytest.raises(RuntimeError, match="whatsapp_sample_media_sample_rate_invalid"):
        module._validate_whatsapp_voice_sample_media(media_path)


def test_build_report_gates_unknown_whatsapp_epub_until_telegram_approval(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"
    sample_path = tmp_path / "voice-sample.mp3"
    sample_path.write_bytes(b"ID3sample")
    job_dir = tmp_path / "job-approved"
    job_dir.mkdir()
    job: dict[str, object] = {
        "job_id": "job-approved",
        "status": "waiting_voice_selection",
        "metadata": {"title": "Approved Book", "language": "en"},
        "storage": {"job_dir": str(job_dir)},
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "pending_batch": [{"preset_key": "voice-1", "callback_token": "sample-token-1"}],
            }
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {"messages": [_epub_message()], "ok": True}
        return {"ok": True, "message_id": f"wamid.out.{len(requests)}", "button_count": 2}

    downloads = {"count": 0}

    def _request_bytes_once(**_: object) -> bytes:
        downloads["count"] += 1
        return b"fake epub"

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(
        module.audiobook_access_approval,
        "send_telegram_approval_request",
        lambda *, record: {"status": "sent", "message_id": "tg.approval.1"},
    )
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "create_job_from_epub",
        lambda **_: (_ for _ in ()).throw(AssertionError("job must not start before approval")),
    )

    first = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
        request_bytes=_request_bytes_once,
    )

    assert first["status"] == "pass"
    assert first["processed"] == 1
    assert first["epub_processed"] == 0
    assert first["status_counts"]["pending_approval"] == 1
    assert downloads["count"] == 1
    assert not [path for path in jobs_root.glob("*/job.json") if path.parent.name != "_incoming_whatsapp"]
    state = json.loads((tmp_path / "wa-actions.json").read_text(encoding="utf-8"))
    action = next(iter(dict(state["actions"]).values()))
    assert action["status"] == "pending_approval"
    approval_id = str(action["approval_id"])
    record = module.audiobook_access_approval.load_request(approval_id)
    assert record["status"] == "pending"
    assert record["phone_number"] == "4368120864006"
    assert Path(str(dict(record["source"])["source_path"])).is_file()
    assert any("operator approval" in str(dict(row["body"]).get("text") or "") for row in requests if row["method"] == "POST")

    module.audiobook_access_approval.update_status(approval_id, status="approved", decided_by="telegram:42")

    start_calls = {"count": 0}

    def _fake_create_job_from_epub(**kwargs: object) -> dict[str, object]:
        start_calls["count"] += 1
        assert Path(str(kwargs["epub_path"])).read_bytes() == b"fake epub"
        assert kwargs["original_filename"] == "book.epub"
        deterministic_job_id = str(kwargs["deterministic_job_id"])
        identity = str(kwargs["intake_idempotency_key_sha256"])
        deterministic_job_dir = jobs_root / deterministic_job_id
        deterministic_job_dir.mkdir(parents=True, exist_ok=True)
        started_job = {
            **job,
            "job_id": deterministic_job_id,
            "source": {
                "intake_idempotency_key_sha256": identity,
                "source_sha256": module.audiobook_epub_pipeline._sha256_file(
                    Path(str(kwargs["epub_path"]))
                ),
            },
            "storage": {"job_dir": str(deterministic_job_dir)},
        }
        (deterministic_job_dir / "job.json").write_text(
            json.dumps(started_job), encoding="utf-8"
        )
        return started_job

    monkeypatch.setattr(module.audiobook_epub_pipeline, "create_job_from_epub", _fake_create_job_from_epub)
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "audiobook_voice_audition_sample_messages",
        lambda _job: [{"token": "sample-token-1", "label": "Narrator One", "matched_tags": ["clear"], "audio_path": str(sample_path)}],
    )
    monkeypatch.setattr(module.audiobook_epub_pipeline, "record_audiobook_voice_sample_delivery", lambda *, job, sample_receipts: job)
    monkeypatch.setattr(module.audiobook_epub_pipeline, "telegram_epub_reply_text", lambda _job: "I sent samples in Telegram.")

    # Simulate a worker that committed the canonical start and then crashed
    # before entering the requester-delivery boundary.
    prestarted = module.audiobook_access_approval.run_approved_start_once(
        approval_id,
        starter=lambda claimed, job_id, identity: module._start_approved_whatsapp_audiobook_request(
            args=_args(tmp_path),
            message=_epub_message(),
            record=claimed,
            deterministic_job_id=job_id,
            start_identity_sha256=identity,
        ),
    )
    assert prestarted["started_now"] is True
    assert "first_delivery" not in module.audiobook_access_approval.load_request(approval_id)

    second = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
        request_bytes=lambda **_: (_ for _ in ()).throw(AssertionError("approved request should use staged source")),
    )

    assert second["status"] == "pass"
    assert second["epub_processed"] == 1
    assert second["voice_sample_sent"] == 1
    assert downloads["count"] == 1
    assert start_calls["count"] == 1
    started_record = module.audiobook_access_approval.load_request(approval_id)
    assert started_record["status"] == "started"
    assert str(started_record["job_id"]).startswith("approval-audiobook-")
    first_delivery = dict(started_record["first_delivery"])
    assert first_delivery["state"] == "completed"
    assert first_delivery["channel"] == "whatsapp"
    assert first_delivery["attempt_count"] == 1
    second_state = json.loads((tmp_path / "wa-actions.json").read_text(encoding="utf-8"))
    second_action = next(iter(dict(second_state["actions"]).values()))
    assert second_action["first_delivery_recovered"] is True
    assert second_action["delivery_status"] == "completed"

    # A later local-state replay must observe the durable delivery receipt and
    # must not repeat job/provider/sample sends.
    state_path = tmp_path / "wa-actions.json"
    replay_state = json.loads(state_path.read_text(encoding="utf-8"))
    replay_action = next(iter(dict(replay_state["actions"]).values()))
    replay_action["status"] = "pending_approval"
    replay_action["reply_sent"] = False
    state_path.write_text(json.dumps(replay_state), encoding="utf-8")
    post_count_before_replay = sum(1 for row in requests if row["method"] == "POST")

    replay = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
        request_bytes=lambda **_: (_ for _ in ()).throw(
            AssertionError("approval replay must use the existing job")
        ),
    )

    assert replay["status"] == "pass"
    assert replay["status_counts"]["started_reused"] == 1
    assert start_calls["count"] == 1
    assert sum(1 for row in requests if row["method"] == "POST") == post_count_before_replay
    replay_state = json.loads(state_path.read_text(encoding="utf-8"))
    replay_action = next(iter(dict(replay_state["actions"]).values()))
    assert replay_action["status"] == "started_reused"
    assert replay_action["start_replayed"] is True


def test_whatsapp_approved_start_is_concurrent_and_crash_recoverable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _module()
    jobs_root = tmp_path / "jobs"
    source_path = tmp_path / "book.epub"
    source_path.write_bytes(b"whatsapp approval source")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)
    args = _args(tmp_path)
    message = _epub_message()

    def _approved_request(message_id: str) -> dict[str, object]:
        request = module.audiobook_access_approval.create_pending_request(
            channel="whatsapp",
            principal_id="principal-1",
            filename="book.epub",
            source_path=source_path,
            phone_number="4368120864006",
            sender_ref="whatsapp:4368120864006",
            session_ref="session-1",
            chat_ref="chat-ref-1",
            message_id=message_id,
        )
        return module.audiobook_access_approval.update_status(
            str(request["approval_id"]),
            status="approved",
            decided_by="telegram:42",
            expected_statuses=("pending",),
        )

    concurrent_request = _approved_request("wamid.concurrent")
    concurrent_id = str(concurrent_request["approval_id"])
    start_entered = threading.Event()
    release_start = threading.Event()
    start_calls = {"count": 0}
    counter_lock = threading.Lock()

    def _concurrent_create(**kwargs: object) -> dict[str, object]:
        with counter_lock:
            start_calls["count"] += 1
        start_entered.set()
        assert release_start.wait(timeout=5)
        job_id = str(kwargs["deterministic_job_id"])
        identity = str(kwargs["intake_idempotency_key_sha256"])
        job_dir = jobs_root / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        job = {
            "job_id": job_id,
            "status": "waiting_voice_selection",
            "source": {
                "intake_idempotency_key_sha256": identity,
                "source_sha256": module.audiobook_epub_pipeline._sha256_file(
                    Path(str(kwargs["epub_path"]))
                ),
            },
            "storage": {"job_dir": str(job_dir)},
            "metadata": {"title": "Concurrent WhatsApp Book"},
        }
        (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")
        return job

    monkeypatch.setattr(module.audiobook_epub_pipeline, "create_job_from_epub", _concurrent_create)

    def _run_start(approval_id: str) -> dict[str, object]:
        bound_record = module.audiobook_access_approval.load_request(approval_id)
        bound_message_id = str(
            dict(bound_record.get("whatsapp") or {}).get("message_id") or ""
        ).strip()
        return module.audiobook_access_approval.run_approved_start_once(
            approval_id,
            starter=lambda claimed, job_id, identity: module._start_approved_whatsapp_audiobook_request(
                args=args,
                message=_epub_message(id=bound_message_id),
                record=claimed,
                deterministic_job_id=job_id,
                start_identity_sha256=identity,
            ),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(_run_start, concurrent_id)
        assert start_entered.wait(timeout=5)
        second = executor.submit(_run_start, concurrent_id)
        release_start.set()
        results = [first.result(timeout=5), second.result(timeout=5)]

    assert start_calls["count"] == 1
    assert sorted(bool(result["started_now"]) for result in results) == [False, True]
    concurrent_persisted = module.audiobook_access_approval.load_request(concurrent_id)
    assert concurrent_persisted["status"] == "started"
    concurrent_job = dict(results[0]["job"])
    delivery_entered = threading.Event()
    release_delivery = threading.Event()
    delivery_calls = {"count": 0}

    def _deliver_once() -> dict[str, object]:
        with counter_lock:
            delivery_calls["count"] += 1
        delivery_entered.set()
        assert release_delivery.wait(timeout=5)
        return module.audiobook_access_approval.build_approved_delivery_outcome(
            channel="whatsapp",
            result=(
                concurrent_job,
                [],
                {"ok": True, "message_id": "private-message-id"},
            ),
            expected_effect_count=1,
            confirmed_effect_count=1,
            known_no_effect_count=0,
            ambiguous_effect_count=0,
        )

    def _run_delivery() -> dict[str, object]:
        return module.audiobook_access_approval.run_approved_delivery_once(
            concurrent_id,
            channel="whatsapp",
            job=concurrent_job,
            deliverer=_deliver_once,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_delivery = executor.submit(_run_delivery)
        assert delivery_entered.wait(timeout=5)
        second_delivery = executor.submit(_run_delivery)
        release_delivery.set()
        delivery_results = [
            first_delivery.result(timeout=5),
            second_delivery.result(timeout=5),
        ]

    assert delivery_calls["count"] == 1
    assert sorted(bool(result["delivery_now"]) for result in delivery_results) == [False, True]
    concurrent_persisted = module.audiobook_access_approval.load_request(concurrent_id)
    delivery_receipt = dict(concurrent_persisted["first_delivery"])
    assert delivery_receipt["state"] == "completed"
    serialized_delivery = json.dumps(delivery_receipt, sort_keys=True)
    assert str(source_path) not in serialized_delivery
    assert "private-message-id" not in serialized_delivery
    assert str(concurrent_persisted["job_id"]) not in serialized_delivery

    crash_request = _approved_request("wamid.crash")
    crash_id = str(crash_request["approval_id"])
    paid_calls = {"count": 0}

    def _crashing_create(**kwargs: object) -> dict[str, object]:
        job_id = str(kwargs["deterministic_job_id"])
        identity = str(kwargs["intake_idempotency_key_sha256"])
        job_dir = jobs_root / job_id
        manifest_path = job_dir / "job.json"
        if manifest_path.is_file():
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        paid_calls["count"] += 1
        job_dir.mkdir(parents=True, exist_ok=True)
        job = {
            "job_id": job_id,
            "status": "waiting_voice_selection",
            "source": {
                "intake_idempotency_key_sha256": identity,
                "source_sha256": module.audiobook_epub_pipeline._sha256_file(
                    Path(str(kwargs["epub_path"]))
                ),
            },
            "storage": {"job_dir": str(job_dir)},
            "metadata": {"title": "Crash WhatsApp Book"},
        }
        manifest_path.write_text(json.dumps(job), encoding="utf-8")
        raise KeyboardInterrupt("simulated WhatsApp worker crash")

    monkeypatch.setattr(module.audiobook_epub_pipeline, "create_job_from_epub", _crashing_create)
    with pytest.raises(KeyboardInterrupt, match="simulated WhatsApp worker crash"):
        _run_start(crash_id)
    assert module.audiobook_access_approval.load_request(crash_id)["status"] == "starting"

    recovered = _run_start(crash_id)

    assert recovered["started_now"] is True
    assert recovered["replayed"] is True
    assert paid_calls["count"] == 1
    crash_persisted = module.audiobook_access_approval.load_request(crash_id)
    assert crash_persisted["status"] == "started"
    assert dict(crash_persisted["start"])["attempt_count"] == 2

    transport_calls = {"count": 0}

    def _crash_during_delivery() -> object:
        transport_calls["count"] += 1
        raise KeyboardInterrupt("simulated ambiguous transport crash")

    with pytest.raises(KeyboardInterrupt, match="ambiguous transport crash"):
        module.audiobook_access_approval.run_approved_delivery_once(
            crash_id,
            channel="whatsapp",
            job=dict(recovered["job"]),
            deliverer=_crash_during_delivery,
        )
    ambiguous = module.audiobook_access_approval.run_approved_delivery_once(
        crash_id,
        channel="whatsapp",
        job=dict(recovered["job"]),
        deliverer=lambda: (_ for _ in ()).throw(
            AssertionError("ambiguous delivery replay must not send twice")
        ),
    )

    assert ambiguous["delivery_now"] is False
    assert ambiguous["delivery_status"] == "outcome_unknown"
    assert transport_calls["count"] == 1


def test_whatsapp_delivery_clean_failure_retries_but_partial_never_auto_resends(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _module()
    jobs_root = tmp_path / "jobs"
    source_path = tmp_path / "delivery.epub"
    source_path.write_bytes(b"whatsapp delivery source")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "audiobook_jobs_root",
        lambda: jobs_root,
    )

    def _started(suffix: str) -> tuple[str, dict[str, object]]:
        record = module.audiobook_access_approval.create_pending_request(
            channel="whatsapp",
            principal_id="principal-1",
            filename="delivery.epub",
            source_path=source_path,
            phone_number="4368120864006",
            sender_ref="whatsapp:4368120864006",
            session_ref="session-1",
            chat_ref="chat-ref-1",
            message_id=f"wamid.{suffix}",
        )
        approved = module.audiobook_access_approval.update_status(
            str(record["approval_id"]),
            status="approved",
            decided_by="telegram:42",
            expected_statuses=("pending",),
        )

        def _starter(
            claimed: dict[str, object],
            job_id: str,
            identity: str,
        ) -> dict[str, object]:
            job_dir = jobs_root / job_id
            job_dir.mkdir(parents=True, exist_ok=True)
            job: dict[str, object] = {
                "job_id": job_id,
                "principal_id": "principal-1",
                "status": "waiting_voice_selection",
                "source": {
                    "source_sha256": str(dict(claimed["source"])["source_sha256"]),
                    "intake_idempotency_key_sha256": identity,
                },
                "metadata": {"title": f"WhatsApp {suffix}"},
                "provider": {"voice_selection": {"strategy": "ranked"}},
                "storage": {"job_dir": str(job_dir)},
            }
            (job_dir / "job.json").write_text(
                json.dumps(job), encoding="utf-8"
            )
            return job

        started = module.audiobook_access_approval.run_approved_start_once(
            str(approved["approval_id"]),
            starter=_starter,
        )
        return str(approved["approval_id"]), dict(started["job"])

    approval_id, job = _started("clean")
    attempts = {"count": 0}

    def _clean_then_success() -> dict[str, object]:
        attempts["count"] += 1
        confirmed = 1 if attempts["count"] == 2 else 0
        return module.audiobook_access_approval.build_approved_delivery_outcome(
            channel="whatsapp",
            result=(job, [], {"ok": bool(confirmed)}),
            expected_effect_count=1,
            confirmed_effect_count=confirmed,
            known_no_effect_count=1 - confirmed,
            ambiguous_effect_count=0,
        )

    failed = module.audiobook_access_approval.run_approved_delivery_once(
        approval_id,
        channel="whatsapp",
        job=job,
        deliverer=_clean_then_success,
    )
    succeeded = module.audiobook_access_approval.run_approved_delivery_once(
        approval_id,
        channel="whatsapp",
        job=job,
        deliverer=_clean_then_success,
    )
    assert failed["delivery_status"] == "failed_before_effect"
    assert succeeded["delivery_status"] == "completed"
    assert attempts["count"] == 2

    partial_id, partial_job = _started("partial")
    partial_calls = {"count": 0}

    def _partial() -> dict[str, object]:
        partial_calls["count"] += 1
        return module.audiobook_access_approval.build_approved_delivery_outcome(
            channel="whatsapp",
            result=(partial_job, [{"status": "sent"}], {"ok": False}),
            expected_effect_count=2,
            confirmed_effect_count=1,
            known_no_effect_count=1,
            ambiguous_effect_count=0,
        )

    partial = module.audiobook_access_approval.run_approved_delivery_once(
        partial_id,
        channel="whatsapp",
        job=partial_job,
        deliverer=_partial,
    )
    replay = module.audiobook_access_approval.run_approved_delivery_once(
        partial_id,
        channel="whatsapp",
        job=partial_job,
        deliverer=lambda: (_ for _ in ()).throw(
            AssertionError("partial WhatsApp delivery must not resend")
        ),
    )
    assert partial["delivery_status"] == "outcome_unknown"
    assert replay["delivery_now"] is False
    assert replay["delivery_status"] == "outcome_unknown"
    assert partial_calls["count"] == 1


def test_whatsapp_approved_delivery_rejects_a_to_b_rehydration_before_send(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _module()
    jobs_root = tmp_path / "jobs"
    source_path = tmp_path / "bound-target.epub"
    source_path.write_bytes(b"bound WhatsApp target")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "audiobook_jobs_root",
        lambda: jobs_root,
    )
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "create_job_from_epub",
        lambda **kwargs: _bound_fake_approved_job(
            module,
            template={
                "contract_name": "ea.audiobook_job.v1",
                "status": "waiting_voice_selection",
                "metadata": {"title": "Bound Target"},
                "provider": {"voice_selection": {"strategy": "ranked"}},
                "chapters": [],
                "totals": {"chapter_count": 0},
            },
            create_kwargs=dict(kwargs),
        ),
    )
    record = module.audiobook_access_approval.create_pending_request(
        channel="whatsapp",
        principal_id="principal-1",
        filename=source_path.name,
        source_path=source_path,
        phone_number="4368120864006",
        sender_ref="whatsapp:4368120864006",
        session_ref="session-1",
        chat_ref="chat-ref-a",
        message_id="wamid.target.a",
    )
    approved = module.audiobook_access_approval.update_status(
        str(record["approval_id"]),
        status="approved",
        decided_by="telegram:42",
        expected_statuses=("pending",),
    )
    args = _args(tmp_path, session_ref="session-1")
    message_a = _epub_message(
        id="wamid.target.a",
        sender_digits="4368120864006",
        chat_ref="chat-ref-a",
    )
    started = module.audiobook_access_approval.run_approved_start_once(
        str(approved["approval_id"]),
        starter=lambda claimed, job_id, identity: module._start_approved_whatsapp_audiobook_request(
            args=args,
            message=message_a,
            record=claimed,
            deterministic_job_id=job_id,
            start_identity_sha256=identity,
        ),
    )
    snapshot = dict(dict(started["record"]["start"])["immutable_snapshot"])
    target_snapshot = dict(snapshot["approved_target"])
    assert target_snapshot["phone_number_sha256"] == module.hashlib.sha256(
        b"4368120864006"
    ).hexdigest()
    assert target_snapshot["session_ref_sha256"] == module.hashlib.sha256(
        b"session-1"
    ).hexdigest()
    assert target_snapshot["chat_ref_sha256"] == module.hashlib.sha256(
        b"chat-ref-a"
    ).hexdigest()
    assert target_snapshot["message_id_sha256"] == module.hashlib.sha256(
        b"wamid.target.a"
    ).hexdigest()
    assert "4368120864006" not in json.dumps(target_snapshot, sort_keys=True)
    transport_calls: list[dict[str, object]] = []
    message_b = _epub_message(
        id="wamid.target.b",
        sender_digits="4368999999999",
        chat_ref="chat-ref-b",
    )

    with pytest.raises(RuntimeError, match="approval_channel_target_mismatch"):
        module._approved_whatsapp_delivery_attempt(
            request_json=lambda **kwargs: transport_calls.append(dict(kwargs))
            or {"ok": True, "message_id": "must-not-send"},
            request_bytes=lambda **_: (_ for _ in ()).throw(
                AssertionError("bound source must not be downloaded again")
            ),
            args=args,
            message=message_b,
            approved_request=dict(started["record"]),
            started_job=dict(started["job"]),
        )

    assert transport_calls == []


@pytest.mark.parametrize(
    "missing_field",
    ["phone_number", "sender_ref", "session_ref", "message_id"],
)
def test_whatsapp_incomplete_approved_target_never_starts_or_delivers(
    monkeypatch,
    tmp_path: Path,
    missing_field: str,
) -> None:
    module = _module()
    jobs_root = tmp_path / "jobs"
    source_path = tmp_path / f"incomplete-{missing_field}.epub"
    source_path.write_bytes(b"incomplete WhatsApp target")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "audiobook_jobs_root",
        lambda: jobs_root,
    )

    def _new_record(suffix: str) -> dict[str, object]:
        return module.audiobook_access_approval.create_pending_request(
            channel="whatsapp",
            principal_id="principal-1",
            filename=source_path.name,
            source_path=source_path,
            phone_number="4368120864006",
            sender_ref="whatsapp:4368120864006",
            session_ref="session-1",
            chat_ref="",
            message_id=f"wamid.{missing_field}.{suffix}",
        )

    def _remove_target_field(record: dict[str, object]) -> dict[str, object]:
        changed = dict(record)
        if missing_field in {"phone_number", "sender_ref"}:
            changed[missing_field] = ""
        else:
            whatsapp = dict(changed.get("whatsapp") or {})
            whatsapp[missing_field] = ""
            changed["whatsapp"] = whatsapp
        return module.audiobook_access_approval._write_request(changed)

    incomplete = _remove_target_field(_new_record("initial"))
    incomplete = module.audiobook_access_approval.update_status(
        str(incomplete["approval_id"]),
        status="approved",
        decided_by="telegram:42",
        expected_statuses=("pending",),
    )
    callbacks = {"starter": 0, "deliverer": 0}

    def _must_not_start(*_: object) -> dict[str, object]:
        callbacks["starter"] += 1
        raise AssertionError("incomplete target must not invoke starter")

    with pytest.raises(RuntimeError, match="approval_channel_target_incomplete"):
        module.audiobook_access_approval.run_approved_start_once(
            str(incomplete["approval_id"]),
            starter=_must_not_start,
        )
    rejected = module.audiobook_access_approval.load_request(
        str(incomplete["approval_id"])
    )
    assert rejected["status"] == "approved"
    assert "start" not in rejected

    valid = module.audiobook_access_approval.update_status(
        str(_new_record("replay")["approval_id"]),
        status="approved",
        decided_by="telegram:42",
        expected_statuses=("pending",),
    )

    def _valid_start(
        claimed: dict[str, object],
        job_id: str,
        identity: str,
    ) -> dict[str, object]:
        job_dir = jobs_root / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        job = {
            "job_id": job_id,
            "principal_id": "principal-1",
            "status": "waiting_voice_selection",
            "source": {
                "source_sha256": str(dict(claimed["source"])["source_sha256"]),
                "intake_idempotency_key_sha256": identity,
            },
            "metadata": {"title": "Completeness Replay"},
            "provider": {"voice_selection": {"strategy": "ranked"}},
            "storage": {"job_dir": str(job_dir)},
        }
        (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")
        return job

    started = module.audiobook_access_approval.run_approved_start_once(
        str(valid["approval_id"]),
        starter=_valid_start,
    )
    _remove_target_field(dict(started["record"]))
    with pytest.raises(RuntimeError, match="approval_channel_target_incomplete"):
        module.audiobook_access_approval.run_approved_start_once(
            str(valid["approval_id"]),
            starter=_must_not_start,
        )

    def _must_not_deliver() -> object:
        callbacks["deliverer"] += 1
        raise AssertionError("incomplete target must not invoke deliverer")

    with pytest.raises(RuntimeError, match="approval_channel_target_incomplete"):
        module.audiobook_access_approval.run_approved_delivery_once(
            str(valid["approval_id"]),
            channel="whatsapp",
            job=dict(started["job"]),
            deliverer=_must_not_deliver,
        )
    assert callbacks == {"starter": 0, "deliverer": 0}


def test_whatsapp_ok_without_durable_message_ids_is_never_completed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _module()
    assert module._whatsapp_transport_effect(
        {"ok": True, "message_id": {"malformed": "id"}}
    ) == ("ambiguous", "")
    assert module._whatsapp_transport_effect(
        {"ok": 1, "message_id": "wamid.truthy-is-not-literal"}
    ) == ("ambiguous", "")
    sample_path = tmp_path / "sample.mp3"
    sample_path.write_bytes(b"ID3 sample")
    monkeypatch.setenv(
        "EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET",
        "callback-secret",
    )
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "audiobook_voice_audition_sample_messages",
        lambda _job: [
            {
                "token": "sample-token",
                "label": "Narrator",
                "audio_path": str(sample_path),
            }
        ],
    )
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "audiobook_voice_sample_audio_quality_gate",
        lambda _path: {"ok": True},
    )
    monkeypatch.setattr(module, "_whatsapp_voice_sample_media_path", lambda path: path)
    receipts = module._send_whatsapp_voice_samples(
        request_json=lambda **_: {"ok": True},
        args=_args(tmp_path),
        recipient_digits="4368120864006",
        job={"whatsapp": {"chat_ref": "chat-ref-1"}},
    )

    assert len(receipts) == 1
    assert receipts[0]["status"] == "skipped"
    assert receipts[0]["confirmed_effect_count"] == 0
    assert receipts[0]["ambiguous_effect_count"] == 2
    assert receipts[0]["media_message_id_sha256"] == ""
    assert receipts[0]["button_message_id_sha256"] == ""

    payload = ({"whatsapp": {}}, receipts, {"ok": True})
    monkeypatch.setattr(module, "_process_epub_candidate", lambda **_: payload)
    outcome = module._approved_whatsapp_delivery_attempt(
        request_json=lambda **_: {"ok": True},
        request_bytes=lambda **_: b"",
        args=_args(tmp_path),
        message=_epub_message(),
        approved_request={},
        started_job={},
    )
    assert outcome["classification"] == "outcome_unknown"
    assert outcome["expected_effect_count"] == 3
    assert outcome["confirmed_effect_count"] == 0
    assert outcome["ambiguous_effect_count"] == 3


def test_trusted_whatsapp_crash_reuses_internal_approval_job_and_delivery_claim(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _module()
    jobs_root = tmp_path / "jobs"
    args = _args(tmp_path)
    message = _epub_message(id="wamid.trusted.crash")
    starts = {"count": 0}
    sends = {"count": 0}
    downloads = {"count": 0}

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setenv("EA_AUDIOBOOK_INSTANT_PHONE_WHITELIST", "4368120864006")
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "audiobook_jobs_root",
        lambda: jobs_root,
    )

    def _request_json(**kwargs: object) -> dict[str, object]:
        if kwargs["method"] == "GET":
            return {"messages": [message], "ok": True}
        return {"ok": True, "message_id": "unexpected-send"}

    def _request_bytes(**_: object) -> bytes:
        downloads["count"] += 1
        return b"trusted source"

    def _create(**kwargs: object) -> dict[str, object]:
        starts["count"] += 1
        job_id = str(kwargs["deterministic_job_id"])
        identity = str(kwargs["intake_idempotency_key_sha256"])
        source = Path(str(kwargs["epub_path"]))
        job_dir = jobs_root / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        job: dict[str, object] = {
            "job_id": job_id,
            "principal_id": str(kwargs["principal_id"]),
            "status": "waiting_voice_selection",
            "source": {
                "source_sha256": module.audiobook_epub_pipeline._sha256_file(source),
                "intake_idempotency_key_sha256": identity,
            },
            "metadata": {"title": "Trusted Crash Book"},
            "provider": {"voice_selection": {"strategy": "ranked"}},
            "storage": {"job_dir": str(job_dir)},
        }
        (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")
        return job

    def _crash_after_ambiguous_send(**_: object) -> dict[str, object]:
        sends["count"] += 1
        raise KeyboardInterrupt("simulated process kill after WhatsApp send")

    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "create_job_from_epub",
        _create,
    )
    monkeypatch.setattr(
        module,
        "_approved_whatsapp_delivery_attempt",
        _crash_after_ambiguous_send,
    )

    real_save_state = module._save_state
    crash_before_action_save = {"armed": True}

    def _crashing_save(path: Path, state: dict[str, object]) -> None:
        action_rows = [
            dict(row)
            for row in dict(state.get("actions") or {}).values()
            if isinstance(row, dict)
        ]
        if crash_before_action_save["armed"] and any(
            row.get("status") == "approved"
            and row.get("trusted_auto_approved") is True
            for row in action_rows
        ):
            crash_before_action_save["armed"] = False
            raise KeyboardInterrupt("simulated kill before action-state save")
        real_save_state(path, state)

    monkeypatch.setattr(module, "_save_state", _crashing_save)
    with pytest.raises(KeyboardInterrupt, match="before action-state save"):
        module.build_report(
            args,
            request_json=_request_json,
            request_bytes=_request_bytes,
        )
    reusable = module.audiobook_access_approval.find_request_for_source(
        channel="whatsapp",
        message_id="wamid.trusted.crash",
        session_ref="session-1",
        sender_ref="whatsapp:4368120864006",
    )
    assert reusable["status"] == "approved"
    assert starts["count"] == 0

    monkeypatch.setattr(module, "_save_state", real_save_state)
    with pytest.raises(KeyboardInterrupt, match="after WhatsApp send"):
        module.build_report(
            args,
            request_json=_request_json,
            request_bytes=_request_bytes,
        )

    restarted = module.build_report(
        args,
        request_json=_request_json,
        request_bytes=_request_bytes,
    )

    assert restarted["status"] == "partial"
    assert restarted["status_counts"] == {"delivery_outcome_unknown": 1}
    assert downloads["count"] == 1
    assert starts["count"] == 1
    assert sends["count"] == 1
    persisted = module.audiobook_access_approval.find_request_for_source(
        channel="whatsapp",
        message_id="wamid.trusted.crash",
        session_ref="session-1",
        sender_ref="whatsapp:4368120864006",
    )
    assert dict(persisted["first_delivery"])["state"] == "outcome_unknown"


def test_build_report_discovers_whatsapp_epub_from_conversation_fallback(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    downloads: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"
    sample_path = tmp_path / "voice-sample.mp3"
    sample_path.write_bytes(b"ID3sample")

    job: dict[str, object] = {
        "job_id": "job-wa-epub-fallback",
        "status": "waiting_voice_selection",
        "metadata": {"title": "Recovered Book", "language": "en"},
        "storage": {"job_dir": str(tmp_path / "job-wa-epub-fallback")},
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "pending_batch": [{"preset_key": "voice-1", "callback_token": "sample-token-1"}],
            }
        },
    }
    (tmp_path / "job-wa-epub-fallback").mkdir()
    (tmp_path / "job-wa-epub-fallback" / "job.json").write_text(json.dumps(job), encoding="utf-8")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET" and str(kwargs["url"]).endswith("/messages?take=100"):
            return {"messages": [], "ok": True}
        if kwargs["method"] == "GET" and "/conversations?" in str(kwargs["url"]):
            return {
                "conversation_count": 1,
                "conversation_page_complete": True,
                "conversation_total": 1,
                "conversations": [{"message_count": 1, "messages": [_epub_message(id="wamid.history.epub.1")]}],
                "ok": True,
            }
        return {"ok": True, "message_id": f"wamid.out.{len(requests)}"}

    def _fake_request_bytes(**kwargs: object) -> bytes:
        downloads.append(dict(kwargs))
        return b"fake epub"

    def _fake_create_job_from_epub(**kwargs: object) -> dict[str, object]:
        assert kwargs["original_filename"] == "book.epub"
        assert Path(str(kwargs["epub_path"])).read_bytes() == b"fake epub"
        assert kwargs["message_id"] == ""
        deterministic_job_id = str(kwargs["deterministic_job_id"])
        job_dir = jobs_root / deterministic_job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        bound_job = {
            **job,
            "job_id": deterministic_job_id,
            "source": {
                "source_sha256": module.audiobook_epub_pipeline._sha256_file(
                    Path(str(kwargs["epub_path"]))
                ),
                "intake_idempotency_key_sha256": str(
                    kwargs["intake_idempotency_key_sha256"]
                ),
            },
            "storage": {"job_dir": str(job_dir)},
        }
        (job_dir / "job.json").write_text(
            json.dumps(bound_job), encoding="utf-8"
        )
        return bound_job

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_INSTANT_PHONE_WHITELIST", "4368120864006")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(module.audiobook_epub_pipeline, "create_job_from_epub", _fake_create_job_from_epub)
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "audiobook_voice_audition_sample_messages",
        lambda _job: [{"token": "sample-token-1", "label": "Narrator One", "matched_tags": ["clear"], "audio_path": str(sample_path)}],
    )
    monkeypatch.setattr(module.audiobook_epub_pipeline, "record_audiobook_voice_sample_delivery", lambda *, job, sample_receipts: job)
    monkeypatch.setattr(module.audiobook_epub_pipeline, "telegram_epub_reply_text", lambda _job: "I sent samples in Telegram.")

    report = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
        request_bytes=_fake_request_bytes,
    )

    assert report["status"] == "pass"
    assert report["inbox_message_count"] == 0
    assert report["message_count"] == 1
    assert report["audiobook_source_candidate_count"] == 1
    assert report["epub_candidate_count"] == 1
    assert report["epub_processed"] == 1
    assert report["voice_sample_sent"] == 1
    fallback = dict(report["conversation_fallback"])
    assert fallback["attempted"] is True
    assert fallback["status"] == "pass"
    assert fallback["message_count"] == 1
    assert fallback["audiobook_source_candidate_count"] == 1
    assert fallback["epub_candidate_count"] == 1
    assert fallback["conversation_count"] == 1
    assert fallback["conversation_page_complete"] is True
    assert downloads[0]["url"] == "https://wa-web.test/sessions/session-1/messages/wamid.history.epub.1/media"
    posts = [row for row in requests if row["method"] == "POST"]
    assert posts
    assert all(dict(row["body"]).get("chat_ref") == "chat-ref-1" for row in posts)


def test_build_report_processes_real_whatsapp_epub_into_bound_voice_choice_job(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"
    source_epub = tmp_path / "real-book.epub"
    _write_minimal_epub(source_epub)

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {"messages": [_epub_message(id="wamid.real.epub.1", media_filename="real-book.epub")], "ok": True}
        return {"ok": True, "message_id": f"wamid.real.out.{len(requests)}"}

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_INSTANT_PHONE_WHITELIST", "4368120864006")
    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", "0")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_RETRY_COUNT", "1")
    monkeypatch.setenv("EA_M4B_TOOL_BIN", "definitely-missing-m4b-tool")
    monkeypatch.setenv("EA_AUDIOBOOKSHELF_AUTO_IMPORT", "0")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {
                    "voice_id": "voice-clear",
                    "label": "Clear narrator",
                    "language": "en-US",
                    "tags": ["audiobook", "narration", "clear", "nonfiction"],
                },
                {
                    "voice_id": "voice-warm",
                    "label": "Warm narrator",
                    "language": "en-US",
                    "tags": ["audiobook", "narration", "warm", "memoir"],
                },
                {
                    "voice_id": "voice-story",
                    "label": "Story narrator",
                    "language": "en-US",
                    "tags": ["audiobook", "narration", "fiction", "dialogue"],
                },
            ]
        ),
    )
    voice_audio = _voice_specific_test_wav_bytes(
        tmp_path,
        ["voice-clear", "voice-warm", "voice-story"],
    )
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "unmixr_synthesize_request",
        lambda **kwargs: (voice_audio[str(kwargs["voice_id"])], "audio/wav"),
    )
    monkeypatch.setattr(module.audiobook_epub_pipeline, "_normalize_rendered_audio_file", lambda path: path)
    monkeypatch.setattr(module, "_whatsapp_voice_sample_media_path", lambda path: path)

    report = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
        request_bytes=lambda **_: source_epub.read_bytes(),
    )

    assert report["status"] == "pass"
    assert report["epub_processed"] == 1
    assert report["voice_sample_sent"] == 3
    assert report["reply_sent"] == 1
    media_posts = [row for row in requests if row["method"] == "POST" and dict(row["body"]).get("media_base64")]
    button_posts = [row for row in requests if row["method"] == "POST" and dict(row["body"]).get("buttons")]
    assert len(media_posts) == 3
    assert len(button_posts) == 3

    manifests = [path for path in jobs_root.glob("*/job.json") if path.parent.name != "_incoming_whatsapp"]
    assert len(manifests) == 1
    job = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert job["status"] == "waiting_voice_selection"
    assert job["metadata"]["title"] == "WhatsApp Proof Book"
    assert job["metadata"]["language"] == "en-US"
    assert len(job["chapters"]) == 2
    voice_selection = job["provider"]["voice_selection"]
    assert voice_selection["status"] == "waiting_user_choice"
    assert len(voice_selection["pending_batch"]) == 3
    assert job["whatsapp"]["sender_ref"] == "4368120864006"
    assert job["whatsapp"]["session_ref"] == "session-1"
    assert job["whatsapp"]["source"] == "whatsapp_web_session"
    assert job["whatsapp"]["voice_sample_delivery"]["status"] == "sent"
    assert job["whatsapp"]["voice_sample_delivery"]["sent_count"] == 3

    receipt = module.audiobook_epub_pipeline.build_audiobook_job_receipt(job_dir=manifests[0].parent)
    assert receipt["whatsapp"]["sender_bound"] is True
    assert receipt["whatsapp"]["session_bound"] is True
    assert receipt["whatsapp"]["message_hash_present"] is True
    assert receipt["whatsapp"]["voice_sample_delivery_status"] == "sent"
    assert receipt["whatsapp"]["voice_sample_delivery_sent_count"] == 3
    rendered_receipt = json.dumps(receipt, sort_keys=True)
    assert "4368120864006" not in rendered_receipt
    assert "voice-clear" not in rendered_receipt
    assert "voice-warm" not in rendered_receipt
    assert "voice-story" not in rendered_receipt


def test_build_report_skips_already_processed_action(tmp_path: Path) -> None:
    module = _module()
    calls = {"handle": 0, "send": 0}

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        if kwargs["method"] == "POST":
            calls["send"] += 1
            return {"ok": True, "message_id": "wamid.reply.1"}
        return {"messages": [_selected_message()], "ok": True}

    def _fake_handle_callback(**kwargs: object) -> dict[str, object]:
        calls["handle"] += 1
        return {"status": "applied", "kind": "audiobook_voice", "reply_text": "Voice selected."}

    args = _args(tmp_path)
    first = module.build_report(args, request_json=_fake_request_json, handle_callback=_fake_handle_callback)
    second = module.build_report(args, request_json=_fake_request_json, handle_callback=_fake_handle_callback)

    assert first["processed"] == 1
    assert second["processed"] == 0
    assert second["skipped_processed"] == 1
    assert calls == {"handle": 1, "send": 1}


def test_build_report_dismiss_callback_sends_replacement_voice_immediately(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    sample_path = tmp_path / "replacement.mp3"
    sample_path.write_bytes(b"ID3replacement")
    job_dir = tmp_path / "job-dismiss"
    job_dir.mkdir()
    job = {
        "job_id": "job-dismiss",
        "status": "waiting_voice_selection",
        "storage": {"job_dir": str(job_dir)},
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "last_action": {
                    "action": "dismiss",
                    "status": "replacement_ready",
                    "replacement_candidate_keys": ["voice-new"],
                },
                "pending_batch": [
                    {
                        "preset_key": "voice-new",
                        "callback_token": "sample-token-new",
                        "sample_file": "sample-token-new.mp3",
                    }
                ],
            }
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {"messages": [_selected_message(chat_ref="chat-ref-1", selected_button_id="ab|d|old-token|1v7j5c0|sig")], "ok": True}
        return {"ok": True, "message_id": f"wamid.out.{len(requests)}"}

    def _fake_handle_callback(**_: object) -> dict[str, object]:
        return {
            "status": "applied",
            "kind": "audiobook_voice",
            "action": "dismiss",
            "job": job,
            "reply_text": "Dismissed.",
        }

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "audiobook_voice_audition_sample_messages",
        lambda _job: [
            {
                "token": "sample-token-new",
                "label": "Narrator New",
                "matched_tags": ["warm"],
                "audio_path": str(sample_path),
            }
        ],
    )
    monkeypatch.setattr(module.audiobook_epub_pipeline, "record_audiobook_voice_sample_delivery", lambda *, job, sample_receipts: job)

    report = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
        handle_callback=_fake_handle_callback,
    )

    assert report["status"] == "pass"
    assert report["processed"] == 1
    assert report["voice_sample_sent"] == 1
    media_post = [row for row in requests if row["method"] == "POST" and dict(row["body"]).get("media_base64")]
    button_post = [row for row in requests if row["method"] == "POST" and dict(row["body"]).get("buttons")]
    final_reply = [
        row
        for row in requests
        if row["method"] == "POST" and dict(row["body"]).get("text") == "Dismissed. I sent 1 replacement audiobook voice sample."
    ]
    assert len(media_post) == 1
    assert dict(media_post[0]["body"])["chat_ref"] == "chat-ref-1"
    assert len(button_post) == 1
    assert dict(button_post[0]["body"])["chat_ref"] == "chat-ref-1"
    assert len(final_reply) == 1
    assert dict(final_reply[0]["body"])["chat_ref"] == "chat-ref-1"


def test_build_report_real_whatsapp_dismiss_callback_applies_and_sends_replacement(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"
    epub = tmp_path / "book.epub"
    _write_minimal_epub(epub)
    voice_audio = _voice_specific_test_wav_bytes(
        tmp_path,
        [f"voice-{index}" for index in range(1, 7)],
    )

    monkeypatch.setenv("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setenv("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", "1")
    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv(
        "EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON",
        json.dumps(
            [
                {"voice_id": f"voice-{index}", "label": f"Voice {index}", "language": "en-US", "tags": ["audiobook", "narration"]}
                for index in range(1, 7)
            ]
        ),
    )
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "unmixr_synthesize_request",
        lambda **kwargs: (voice_audio[str(kwargs["voice_id"])], "audio/wav"),
    )
    monkeypatch.setattr(module.audiobook_epub_pipeline, "_normalize_rendered_audio_file", lambda path: path)

    job = module.audiobook_epub_pipeline.create_job_from_epub(
        epub_path=epub,
        original_filename="book.epub",
        principal_id="exec-1",
    )
    first_token = str(job["provider"]["voice_selection"]["pending_batch"][0]["callback_token"])
    callback_data = module.whatsapp_inbound_actions.encode_whatsapp_audiobook_voice_callback(
        action="d",
        token=first_token,
        sender_ref="4368120864006",
        expires_at=FUTURE_EXPIRY,
    )

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {
                "messages": [
                    _selected_message(
                        chat_ref="chat-ref-1",
                        selected_button_id=callback_data,
                        selected_button_kind="audiobook_voice",
                    )
                ],
                "ok": True,
            }
        body = dict(kwargs.get("body") or {})
        return {
            "ok": True,
            "message_id": f"wamid.real-dismiss.{len(requests)}",
            "button_count": 2 if body.get("buttons") else 0,
            "buttons_fallback": False,
            "control_kind": "poll" if body.get("buttons") else "",
        }

    report = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
    )

    assert report["status"] == "pass"
    assert report["processed"] == 1
    assert report["voice_sample_sent"] == 1
    media_post = [row for row in requests if row["method"] == "POST" and dict(row["body"]).get("media_base64")]
    button_post = [row for row in requests if row["method"] == "POST" and dict(row["body"]).get("buttons")]
    final_reply = [
        row
        for row in requests
        if row["method"] == "POST"
        and dict(row["body"]).get("text") == "Dismissed. I sent 1 replacement audiobook voice sample."
    ]
    assert len(media_post) == 1
    assert dict(media_post[0]["body"])["chat_ref"] == "chat-ref-1"
    assert len(button_post) == 1
    assert dict(button_post[0]["body"])["chat_ref"] == "chat-ref-1"
    replacement_buttons = dict(button_post[0]["body"])["buttons"][0]
    assert replacement_buttons[0][0] == "Use Voice 4"
    assert str(replacement_buttons[0][1]).startswith("ab|u|")
    assert replacement_buttons[1][0] == "Dismiss Voice 4"
    assert str(replacement_buttons[1][1]).startswith("ab|d|")
    assert len(final_reply) == 1

    updated_job = json.loads(next(jobs_root.glob("*/job.json")).read_text(encoding="utf-8"))
    labels = [row["label"] for row in updated_job["provider"]["voice_selection"]["pending_batch"]]
    assert labels == ["Voice 2", "Voice 3", "Voice 4"]
    assert updated_job["whatsapp"]["voice_sample_delivery"]["sent_count"] == 1
    state = json.loads((tmp_path / "wa-actions.json").read_text(encoding="utf-8"))
    action = next(iter(state["actions"].values()))
    assert action["replacement_sample_sent"] == 1
    assert action["replacement_sample_delivery_status"] == "sent"
    assert action["replacement_sample_attempted"] == 1
    assert action["replacement_sample_failed"] == 0
    serialized_state = json.dumps(state)
    assert "4368120864006" not in serialized_state
    assert first_token not in serialized_state


def test_build_report_recovers_poll_vote_label_without_callback_payload(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    handled: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-poll-label"
    job_dir.mkdir(parents=True)
    job = {
        "job_id": "job-poll-label",
        "status": "waiting_voice_selection",
        "storage": {"job_dir": str(job_dir)},
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "pending_candidate_keys": ["voice-one"],
                "pending_batch": [
                    {
                        "label": "Narrator One",
                        "preset_key": "voice-one",
                        "callback_token": "sample-token-1",
                    }
                ],
            }
        },
        "whatsapp": {
            "chat_ref": "chat-ref-1",
            "sender_ref": "4368120864006",
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {
                "messages": [
                    {
                        "chat_ref": "chat-ref-1",
                        "direction": "inbound",
                        "from_me": False,
                        "id": "pollvote:outbound-poll-1:1",
                        "media_present": False,
                        "selected_button_id_present": False,
                        "selected_button_label": "Dismiss Narrator One",
                        "sender_digits": "4368120864006",
                        "type": "poll_vote",
                    }
                ],
                "ok": True,
            }
        return {"ok": True, "message_id": f"wamid.out.{len(requests)}"}

    def _fake_handle_callback(**kwargs: object) -> dict[str, object]:
        handled.append(dict(kwargs))
        assert str(kwargs["callback_data"]).startswith("ab|d|sample-token-1|")
        return {
            "status": "applied",
            "kind": "audiobook_voice",
            "action": "dismiss",
            "job": job,
            "reply_text": "Dismissed.",
        }

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)

    report = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
        handle_callback=_fake_handle_callback,
    )

    assert report["status"] == "pass"
    assert report["candidate_count"] == 1
    assert report["processed"] == 1
    assert report["reply_sent"] == 1
    assert handled[0]["sender_ref"] == "4368120864006"
    post = [row for row in requests if row["method"] == "POST"]
    assert len(post) == 1
    assert dict(post[0]["body"])["chat_ref"] == "chat-ref-1"
    assert dict(post[0]["body"])["text"] == "Dismissed."


def test_build_report_recovers_generic_poll_vote_label_for_single_pending_sample(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    handled: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-poll-generic-label"
    job_dir.mkdir(parents=True)
    job = {
        "job_id": "job-poll-generic-label",
        "status": "waiting_voice_selection",
        "storage": {"job_dir": str(job_dir)},
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "pending_candidate_keys": ["voice-one"],
                "pending_batch": [
                    {
                        "label": "Narrator One",
                        "preset_key": "voice-one",
                        "callback_token": "sample-token-1",
                    }
                ],
            }
        },
        "whatsapp": {
            "chat_ref": "chat-ref-1",
            "sender_ref": "4368120864006",
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {
                "messages": [
                    {
                        "chat_ref": "chat-ref-1",
                        "direction": "inbound",
                        "from_me": False,
                        "id": "pollvote:outbound-poll-generic:1",
                        "media_present": False,
                        "selected_button_id_present": False,
                        "selected_button_label": "Dismiss",
                        "sender_digits": "4368120864006",
                        "type": "poll_vote",
                    }
                ],
                "ok": True,
            }
        return {"ok": True, "message_id": f"wamid.out.{len(requests)}"}

    def _fake_handle_callback(**kwargs: object) -> dict[str, object]:
        handled.append(dict(kwargs))
        assert str(kwargs["callback_data"]).startswith("ab|d|sample-token-1|")
        return {
            "status": "applied",
            "kind": "audiobook_voice",
            "action": "dismiss",
            "job": job,
            "reply_text": "Dismissed.",
        }

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)

    report = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
        handle_callback=_fake_handle_callback,
    )

    assert report["status"] == "pass"
    assert report["candidate_count"] == 1
    assert report["processed"] == 1
    assert report["reply_sent"] == 1
    assert handled[0]["sender_ref"] == "4368120864006"
    post = [row for row in requests if row["method"] == "POST"]
    assert len(post) == 1
    assert dict(post[0]["body"])["chat_ref"] == "chat-ref-1"
    assert dict(post[0]["body"])["text"] == "Dismissed."


def test_build_report_recovers_automatic_cast_poll_label_without_callback_payload(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    handled: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-poll-automatic-cast"
    job_dir.mkdir(parents=True)
    job = {
        "job_id": "job-poll-automatic-cast",
        "status": "waiting_voice_selection",
        "storage": {"job_dir": str(job_dir)},
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "pending_candidate_keys": ["voice-one", "voice-two"],
                "pending_batch": [
                    {
                        "label": "Narrator One",
                        "preset_key": "voice-one",
                        "callback_token": "ranked-sample-token",
                    },
                    {
                        "label": "Narrator Two",
                        "preset_key": "voice-two",
                        "callback_token": "second-sample-token",
                    },
                ],
            }
        },
        "whatsapp": {
            "chat_ref": "chat-ref-1",
            "sender_ref": "4368120864006",
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {
                "messages": [
                    {
                        "chat_ref": "chat-ref-1",
                        "direction": "inbound",
                        "from_me": False,
                        "id": "pollvote:automatic-cast:1",
                        "media_present": False,
                        "selected_button_id_present": False,
                        "selected_button_label": "Use automatic cast",
                        "sender_digits": "4368120864006",
                        "type": "poll_vote",
                    }
                ],
                "ok": True,
            }
        return {"ok": True, "message_id": f"wamid.out.{len(requests)}"}

    def _fake_handle_callback(**kwargs: object) -> dict[str, object]:
        handled.append(dict(kwargs))
        assert str(kwargs["callback_data"]).startswith(
            "ab|a|ranked-sample-token|"
        )
        return {
            "status": "applied",
            "kind": "audiobook_voice",
            "action": "use_automatic_cast",
            "job": job,
            "reply_text": "Automatic cast selected.",
        }

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "audiobook_jobs_root",
        lambda: jobs_root,
    )

    report = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
        handle_callback=_fake_handle_callback,
    )

    assert report["status"] == "pass"
    assert report["candidate_count"] == 1
    assert report["processed"] == 1
    assert handled[0]["sender_ref"] == "4368120864006"
    post = [row for row in requests if row["method"] == "POST"]
    assert len(post) == 1
    assert dict(post[0]["body"])["text"] == "Automatic cast selected."


def test_build_report_recovers_generic_poll_vote_label_by_button_message_id(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    handled: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-poll-generic-context"
    job_dir.mkdir(parents=True)
    target_token = "sample-token-2"
    job = {
        "job_id": "job-poll-generic-context",
        "status": "waiting_voice_selection",
        "storage": {"job_dir": str(job_dir)},
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "pending_candidate_keys": ["voice-one", "voice-two"],
                "pending_batch": [
                    {"label": "Narrator One", "preset_key": "voice-one", "callback_token": "sample-token-1"},
                    {"label": "Narrator Two", "preset_key": "voice-two", "callback_token": target_token},
                ],
            }
        },
        "whatsapp": {
            "chat_ref": "chat-ref-1",
            "sender_ref": "4368120864006",
            "voice_sample_delivery": {
                "status": "sent",
                "samples": [
                    {
                        "token_sha256": module.hashlib.sha256(b"sample-token-1").hexdigest(),
                        "button_message_id_sha256": module._sha("wamid.buttons.1"),
                    },
                    {
                        "token_sha256": module.hashlib.sha256(target_token.encode("utf-8")).hexdigest(),
                        "button_message_id_sha256": module._sha("wamid.buttons.2"),
                    },
                ],
            },
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        if kwargs["method"] == "GET":
            return {
                "messages": [
                    {
                        "chat_ref": "chat-ref-1",
                        "context_message_id": "wamid.buttons.2",
                        "direction": "inbound",
                        "from_me": False,
                        "id": "pollvote:outbound-poll-context:1",
                        "media_present": False,
                        "selected_button_id_present": False,
                        "selected_button_label": "Dismiss",
                        "sender_digits": "4368120864006",
                        "type": "poll_vote",
                    }
                ],
                "ok": True,
            }
        return {"ok": True, "message_id": "wamid.reply.1"}

    def _fake_handle_callback(**kwargs: object) -> dict[str, object]:
        handled.append(dict(kwargs))
        assert str(kwargs["callback_data"]).startswith(f"ab|d|{target_token}|")
        return {
            "status": "applied",
            "kind": "audiobook_voice",
            "action": "dismiss",
            "job": job,
            "reply_text": "Dismissed.",
        }

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)

    report = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
        handle_callback=_fake_handle_callback,
    )

    assert report["status"] == "pass"
    assert report["candidate_count"] == 1
    assert report["processed"] == 1
    assert handled[0]["sender_ref"] == "4368120864006"


def test_build_report_recovers_generic_poll_vote_label_by_media_message_id(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    handled: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-poll-generic-media-context"
    job_dir.mkdir(parents=True)
    target_token = "sample-token-2"
    job = {
        "job_id": "job-poll-generic-media-context",
        "status": "waiting_voice_selection",
        "storage": {"job_dir": str(job_dir)},
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "pending_candidate_keys": ["voice-one", "voice-two"],
                "pending_batch": [
                    {"label": "Narrator One", "preset_key": "voice-one", "callback_token": "sample-token-1"},
                    {"label": "Narrator Two", "preset_key": "voice-two", "callback_token": target_token},
                ],
            }
        },
        "whatsapp": {
            "chat_ref": "chat-ref-1",
            "sender_ref": "4368120864006",
            "voice_sample_delivery": {
                "status": "sent",
                "samples": [
                    {
                        "token_sha256": module.hashlib.sha256(b"sample-token-1").hexdigest(),
                        "media_message_id_sha256": module._sha("wamid.media.1"),
                    },
                    {
                        "token_sha256": module.hashlib.sha256(target_token.encode("utf-8")).hexdigest(),
                        "media_message_id_sha256": module._sha("wamid.media.2"),
                    },
                ],
            },
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        if kwargs["method"] == "GET":
            return {
                "messages": [
                    {
                        "chat_ref": "chat-ref-1",
                        "context_message_id": "wamid.media.2",
                        "direction": "inbound",
                        "from_me": False,
                        "id": "pollvote:outbound-poll-media-context:1",
                        "media_present": False,
                        "selected_button_id_present": False,
                        "selected_button_label": "Use",
                        "sender_digits": "4368120864006",
                        "type": "poll_vote",
                    }
                ],
                "ok": True,
            }
        return {"ok": True, "message_id": "wamid.reply.1"}

    def _fake_handle_callback(**kwargs: object) -> dict[str, object]:
        handled.append(dict(kwargs))
        assert str(kwargs["callback_data"]).startswith(f"ab|u|{target_token}|")
        return {
            "status": "applied",
            "kind": "audiobook_voice",
            "action": "use",
            "reply_text": "Voice selected.",
        }

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)

    report = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
        handle_callback=_fake_handle_callback,
    )

    assert report["status"] == "pass"
    assert report["candidate_count"] == 1
    assert report["processed"] == 1
    assert handled[0]["sender_ref"] == "4368120864006"


def test_build_report_uses_named_voice_from_private_manifest(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-named-voice"
    private_dir = job_dir / "voice_audition"
    private_dir.mkdir(parents=True)
    job = {
        "job_id": "job-named-voice",
        "status": "waiting_voice_selection",
        "next_action": "choose_audiobook_voice",
        "storage": {"job_dir": str(job_dir)},
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "pending_candidate_keys": ["voice-one"],
                "pending_batch": [
                    {
                        "label": "Narrator One",
                        "preset_key": "voice-one",
                        "callback_token": "sample-token-1",
                    }
                ],
                "dismissed_candidate_keys": ["unmixr_remy_d4477bcd"],
            }
        },
        "whatsapp": {
            "chat_ref": "chat-ref-1",
            "sender_ref": "4368120864006",
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")
    (private_dir / "private.json").write_text(
        json.dumps(
            {
                "contract_name": module.audiobook_epub_pipeline.VOICE_AUDITION_CONTRACT_NAME,
                "candidates": {
                    "remy-token": {
                        "candidate_key": "unmixr_remy_d4477bcd",
                        "voice_id": "remy-secret",
                        "public": {
                            "callback_token": "remy-token",
                            "label": "Remy",
                            "language": "fr-fr",
                            "preset_key": "unmixr_remy_d4477bcd",
                            "provider": "unmixr",
                            "score": -12,
                            "supported_languages": ["fr-fr", "en-us"],
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {"messages": [_text_message(body_text="use remy", id="wamid.use-remy")], "ok": True}
        return {"ok": True, "message_id": f"wamid.out.{len(requests)}"}

    def _fake_apply(*, callback_token: str, action: str) -> dict[str, object]:
        assert callback_token == "remy-token"
        assert action == "use"
        activated = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
        selection = activated["provider"]["voice_selection"]
        assert selection["pending_candidate_keys"] == ["unmixr_remy_d4477bcd"]
        assert selection["pending_batch"][0]["label"] == "Remy"
        assert selection["pending_batch"][0]["voice_language_override_by_user"] is True
        assert "unmixr_remy_d4477bcd" not in selection["dismissed_candidate_keys"]
        selection.update(
            {
                "status": "selected_by_user",
                "selected": {
                    "label": "Remy",
                    "language": "fr-fr",
                    "voice_language_override_by_user": True,
                },
                "selected_candidate_key": "unmixr_remy_d4477bcd",
                "selected_callback_token": "remy-token",
                "pending_candidate_keys": [],
                "pending_batch": [],
                "voice_language_override_by_user": True,
            }
        )
        activated["status"] = "rendering_chapter_audio"
        activated["next_action"] = "render_chapter_audio"
        (job_dir / "job.json").write_text(json.dumps(activated), encoding="utf-8")
        return activated

    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(module.audiobook_epub_pipeline, "apply_audiobook_voice_audition_action", _fake_apply)

    report = module.build_report(_args(tmp_path), request_json=_fake_request_json)

    assert report["processed"] == 1
    assert report["status_counts"]["applied"] == 1
    replies = [dict(row["body"]).get("text") for row in requests if row["method"] == "POST"]
    assert replies == ["Selected Remy. I am rendering the audiobook with that voice now."]


def test_build_report_sends_reply_for_ignored_callback(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {
                "messages": [
                    _selected_message(
                        chat_ref="chat-ref-1",
                        selected_button_id="ab|d|bad-token|1v7j5c0|sig",
                    )
                ],
                "ok": True,
            }
        return {"ok": True, "message_id": f"wamid.out.{len(requests)}"}

    def _fake_handle_callback(**_: object) -> dict[str, object]:
        return {
            "status": "ignored",
            "kind": "audiobook_voice",
            "reason": "invalid_signature",
            "reply_text": "That WhatsApp action is no longer valid. Send the request again if needed.",
        }

    report = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
        handle_callback=_fake_handle_callback,
    )

    assert report["processed"] == 1
    assert report["reply_sent"] == 1
    post = [row for row in requests if row["method"] == "POST"]
    assert len(post) == 1
    assert dict(post[0]["body"])["chat_ref"] == "chat-ref-1"
    assert dict(post[0]["body"])["text"] == "That WhatsApp action is no longer valid. Send the request again if needed."
    state = json.loads((tmp_path / "wa-actions.json").read_text(encoding="utf-8"))
    action = next(iter(dict(state["actions"]).values()))
    assert action["status"] == "ignored"
    assert action["reason"] == "invalid_signature"
    assert action["reply_sent"] is True
    assert report["stale_callback_summary"] == {
        "action_count": 1,
        "stale_count": 0,
        "ignored_count": 1,
        "reply_sent": 1,
        "suppressed": 0,
        "suppressed_by_age": 0,
        "suppressed_duplicate": 0,
        "reasons": {"invalid_signature": 1},
        "suppressed_reasons": {},
    }
    assert state["last_run"]["stale_callback_summary"]["ignored_count"] == 1


def test_build_report_counts_final_stale_management_callback_status(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {
                "messages": [
                    _selected_message(
                        chat_ref="chat-ref-1",
                        selected_button_id="am|n|missing-management-token|1v7j5c0|sig",
                        selected_button_kind="audiobook_voice_management",
                    )
                ],
                "ok": True,
            }
        return {"ok": True, "message_id": "wamid.stale.management.reply"}

    def _fake_handle_callback(**_: object) -> dict[str, object]:
        return {
            "status": "applied",
            "kind": "audiobook_voice_management",
            "action": "next_batch",
            "token": "missing-management-token",
        }

    report = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
        handle_callback=_fake_handle_callback,
    )

    assert report["processed"] == 1
    assert report["status_counts"] == {"stale": 1}
    assert report["stale_callback_summary"]["stale_count"] == 1
    state = json.loads((tmp_path / "wa-actions.json").read_text(encoding="utf-8"))
    action = next(iter(dict(state["actions"]).values()))
    assert action["status"] == "stale"
    post = [row for row in requests if row["method"] == "POST"]
    assert dict(post[0]["body"])["text"] == "That audiobook control is stale. Use the latest voice sample controls."


def test_build_report_recovers_sender_for_stale_playback_callback_from_chat_ref(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-1"
    job_dir.mkdir(parents=True)
    (job_dir / "job.json").write_text(
        json.dumps(
            {
                "job_id": "job-1",
                "status": "audiobookshelf_imported",
                "whatsapp": {
                    "sender_ref": "4368120864006",
                    "chat_ref": "chat-ref-1",
                },
                "audiobookshelf_import": {
                    "public_share": {
                        "status": "public_share_ready",
                        "absolute_url": "https://abs.example.com/share/ready-book",
                        "playback_acceptance_callback": {
                            "status": "ready",
                            "token": "current-playback-token",
                            "raw_token_exposed": False,
                        },
                        "whatsapp_delivery": {"status": "sent", "message_id": "wamid.share.1"},
                    }
                },
                "playback_acceptance": {"status": "not_recorded", "accepted": False},
            }
        ),
        encoding="utf-8",
    )

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {
                "messages": [
                    _selected_message(
                        id="wamid.playback.stale.1",
                        chat_ref="chat-ref-1",
                        sender_digits="",
                        selected_button_kind="audiobook_playback",
                        selected_button_id="ap|a|stale-playback-token|4102444800|sig",
                    )
                ],
                "ok": True,
            }
        return {"ok": True, "message_id": "wamid.playback.stale.reply"}

    def _fake_handle_callback(**kwargs: object) -> dict[str, object]:
        assert kwargs["sender_ref"] == "4368120864006"
        return {
            "status": "stale",
            "kind": "audiobook_playback",
            "reason": "invalid_signature",
            "reply_text": "That audiobook playback button is stale. Send 'audiobook playback' and I will send fresh buttons for the latest audiobook.",
        }

    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))

    report = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
        handle_callback=_fake_handle_callback,
    )

    assert report["processed"] == 1
    assert report["status_counts"] == {"stale": 1}
    post = [row for row in requests if row["method"] == "POST"]
    assert len(post) == 1
    assert dict(post[0]["body"])["chat_ref"] == "chat-ref-1"
    assert (
        dict(post[0]["body"])["text"]
        == "That audiobook playback button is stale. Send 'audiobook playback' and I will send fresh buttons for the latest audiobook."
    )


def test_build_report_suppresses_old_stale_callback_replies(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {
                "messages": [
                    _selected_message(
                        id="wamid.old.stale.1",
                        chat_ref="chat-ref-1",
                        message_timestamp="2026-01-01T00:00:00Z",
                        selected_button_id="ab|d|old-token-1|1v7j5c0|sig",
                    ),
                    _selected_message(
                        id="wamid.old.stale.2",
                        chat_ref="chat-ref-1",
                        message_timestamp="2026-01-01T00:00:10Z",
                        selected_button_id="ab|d|old-token-2|1v7j5c0|sig",
                    ),
                ],
                "ok": True,
            }
        return {"ok": True, "message_id": f"wamid.out.{len(requests)}"}

    def _fake_handle_callback(**_: object) -> dict[str, object]:
        return {
            "status": "stale",
            "kind": "audiobook_voice",
            "reason": "stale_candidate_ignored",
            "reply_text": "That audiobook voice button is stale, so I ignored it. Use the latest voice sample buttons, or reply with the voice name or 'dismiss all'.",
        }

    report = module.build_report(
        _args(tmp_path, stale_callback_reply_max_age_seconds=900),
        request_json=_fake_request_json,
        handle_callback=_fake_handle_callback,
    )

    assert report["processed"] == 2
    assert report["reply_sent"] == 0
    assert [row for row in requests if row["method"] == "POST"] == []
    state = json.loads((tmp_path / "wa-actions.json").read_text(encoding="utf-8"))
    actions = list(dict(state["actions"]).values())
    assert len(actions) == 2
    assert {action["reply_suppressed_reason"] for action in actions} == {"callback_reply_too_old"}
    assert report["stale_callback_summary"] == {
        "action_count": 2,
        "stale_count": 2,
        "ignored_count": 0,
        "reply_sent": 0,
        "suppressed": 2,
        "suppressed_by_age": 2,
        "suppressed_duplicate": 0,
        "reasons": {"stale_candidate_ignored": 2},
        "suppressed_reasons": {"callback_reply_too_old": 2},
    }


def test_build_report_sends_only_one_recent_stale_callback_reply(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {
                "messages": [
                    _selected_message(
                        id="wamid.recent.stale.1",
                        chat_ref="chat-ref-1",
                        message_timestamp="2030-01-01T00:00:00Z",
                        selected_button_id="ab|d|recent-token-1|1v7j5c0|sig",
                    ),
                    _selected_message(
                        id="wamid.recent.stale.2",
                        chat_ref="chat-ref-1",
                        message_timestamp="2030-01-01T00:00:10Z",
                        selected_button_id="ab|d|recent-token-2|1v7j5c0|sig",
                    ),
                ],
                "ok": True,
            }
        return {"ok": True, "message_id": f"wamid.out.{len(requests)}"}

    def _fake_handle_callback(**_: object) -> dict[str, object]:
        return {
            "status": "stale",
            "kind": "audiobook_voice",
            "reason": "stale_candidate_ignored",
            "reply_text": "That audiobook voice button is stale, so I ignored it. Use the latest voice sample buttons, or reply with the voice name or 'dismiss all'.",
        }

    report = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
        handle_callback=_fake_handle_callback,
    )

    assert report["processed"] == 2
    assert report["reply_sent"] == 1
    posts = [row for row in requests if row["method"] == "POST"]
    assert len(posts) == 1
    state = json.loads((tmp_path / "wa-actions.json").read_text(encoding="utf-8"))
    suppressed = [action for action in dict(state["actions"]).values() if action.get("reply_suppressed")]
    assert len(suppressed) == 1
    assert suppressed[0]["reply_suppressed_reason"] == "duplicate_stale_callback_notice"
    assert report["stale_callback_summary"] == {
        "action_count": 2,
        "stale_count": 2,
        "ignored_count": 0,
        "reply_sent": 1,
        "suppressed": 1,
        "suppressed_by_age": 0,
        "suppressed_duplicate": 1,
        "reasons": {"stale_candidate_ignored": 2},
        "suppressed_reasons": {"duplicate_stale_callback_notice": 1},
    }


def test_build_report_dedupes_duplicate_callback_data_across_message_ids(tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    handled: list[dict[str, object]] = []
    first = _selected_message(id="wamid.inbound.1", selected_button_id="ab|d|voice-token-1|1v7j5c0|sig")
    second = _selected_message(id="wamid.inbound.2", selected_button_id="ab|d|voice-token-1|1v7j5c0|sig")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {"messages": [first, second], "ok": True}
        return {"ok": True, "message_id": f"wamid.out.{len(requests)}"}

    def _fake_handle_callback(**kwargs: object) -> dict[str, object]:
        handled.append(dict(kwargs))
        return {
            "status": "applied",
            "kind": "audiobook_voice",
            "action": "dismiss",
            "reply_text": "Dismissed. I sent 1 replacement audiobook voice sample.",
        }

    report = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
        handle_callback=_fake_handle_callback,
    )

    first_action_id = module._action_id(
        session_ref="session-1",
        message_id=str(first["id"]),
        callback_data=str(first["selected_button_id"]),
    )
    second_action_id = module._action_id(
        session_ref="session-1",
        message_id=str(second["id"]),
        callback_data=str(second["selected_button_id"]),
    )

    assert report["processed"] == 1
    assert report["skipped_processed"] == 1
    assert report["reply_sent"] == 1
    assert len(handled) == 1
    posts = [row for row in requests if row["method"] == "POST"]
    assert len(posts) == 1
    state = json.loads((tmp_path / "wa-actions.json").read_text(encoding="utf-8"))
    assert state["actions"][first_action_id]["status"] == "applied"
    assert state["actions"][second_action_id]["status"] == "duplicate"
    assert state["actions"][second_action_id]["reason"] == "duplicate_callback_data"
    assert state["actions"][second_action_id]["duplicate_of_action_id"] == first_action_id


def test_build_report_retries_ignored_missing_secret_callback(tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    handled: list[dict[str, object]] = []
    state_path = tmp_path / "wa-actions.json"
    message = _selected_message(
        chat_ref="chat-ref-1",
        selected_button_id="ab|u|voice-token-1|1v7j5c0|sig",
    )
    action_id = module._action_id(
        session_ref="session-1",
        message_id=str(message["id"]),
        callback_data=str(message["selected_button_id"]),
    )
    state_path.write_text(
        json.dumps(
            {
                "version": 1,
                "actions": {
                    action_id: {
                        "callback_hash": "old",
                        "kind": "audiobook_voice",
                        "message_hash": "old",
                        "processed_at": "2026-06-21T00:00:00Z",
                        "reason": "missing_secret",
                        "reply_sent": False,
                        "status": "ignored",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {"messages": [message], "ok": True}
        return {"ok": True, "message_id": f"wamid.out.{len(requests)}"}

    def _fake_handle_callback(**kwargs: object) -> dict[str, object]:
        handled.append(dict(kwargs))
        return {
            "status": "applied",
            "kind": "audiobook_voice",
            "action": "use",
            "reply_text": "Voice selected.",
        }

    report = module.build_report(
        _args(tmp_path, state_file=str(state_path)),
        request_json=_fake_request_json,
        handle_callback=_fake_handle_callback,
    )

    assert report["processed"] == 1
    assert report["skipped_processed"] == 0
    assert report["reply_sent"] == 1
    assert handled
    updated = json.loads(state_path.read_text(encoding="utf-8"))
    assert updated["actions"][action_id]["status"] == "applied"
    assert updated["actions"][action_id]["reply_sent"] is True


def test_build_report_dismiss_all_text_sends_replacement_voice_batch(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-dismiss-all"
    job_dir.mkdir(parents=True)
    sample_path = tmp_path / "replacement.mp3"
    sample_path.write_bytes(b"ID3replacement")
    original_job = {
        "job_id": "job-dismiss-all",
        "status": "waiting_voice_selection",
        "updated_at": "2026-06-21T05:00:00Z",
        "storage": {"job_dir": str(job_dir)},
        "whatsapp": {"sender_ref": "4368120864006", "session_ref": "session-1", "chat_ref": "chat-ref-1"},
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "pending_batch": [
                    {"label": "Old One", "preset_key": "old-1", "callback_token": "old-token-1", "sample_file": "old-1.mp3"},
                    {"label": "Old Two", "preset_key": "old-2", "callback_token": "old-token-2", "sample_file": "old-2.mp3"},
                    {"label": "Old Three", "preset_key": "old-3", "callback_token": "old-token-3", "sample_file": "old-3.mp3"},
                ],
            }
        },
    }
    replacement_job = {
        **original_job,
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "replacement_candidate_keys": ["new-1"],
                "pending_batch": [
                    {
                        "label": "Narrator New",
                        "preset_key": "new-1",
                        "callback_token": "sample-token-new",
                        "sample_file": "sample-token-new.mp3",
                    }
                ],
            }
        },
    }
    (job_dir / "job.json").write_text(json.dumps(original_job), encoding="utf-8")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {"messages": [_text_message(body_text="dismiss all")], "ok": True}
        return {"ok": True, "message_id": f"wamid.out.{len(requests)}", "button_count": 2, "buttons_fallback": True}

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(
        module,
        "_dismiss_all_pending_whatsapp_voice_samples",
        lambda _job: (replacement_job, 3),
    )
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "audiobook_voice_audition_sample_messages",
        lambda _job: [
            {
                "token": "sample-token-new",
                "label": "Narrator New",
                "matched_tags": ["warm"],
                "audio_path": str(sample_path),
            }
        ],
    )
    monkeypatch.setattr(module.audiobook_epub_pipeline, "record_audiobook_voice_sample_delivery", lambda *, job, sample_receipts: job)

    report = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
    )

    assert report["status"] == "pass"
    assert report["voice_text_candidate_count"] == 1
    assert report["voice_text_processed"] == 1
    assert report["voice_sample_sent"] == 1
    media_post = [row for row in requests if row["method"] == "POST" and dict(row["body"]).get("media_base64")]
    button_post = [row for row in requests if row["method"] == "POST" and dict(row["body"]).get("buttons")]
    final_reply = [
        row
        for row in requests
        if row["method"] == "POST"
        and dict(row["body"]).get("text") == "Dismissed all 3 current voices. I sent 1 replacement audiobook voice sample."
    ]
    assert len(media_post) == 1
    assert dict(media_post[0]["body"])["chat_ref"] == "chat-ref-1"
    assert len(button_post) == 1
    assert dict(button_post[0]["body"])["chat_ref"] == "chat-ref-1"
    assert "reply 'use Narrator New', 'use automatic cast', or 'dismiss all'" in str(
        dict(button_post[0]["body"]).get("text") or ""
    )
    assert dict(button_post[0]["body"])["buttons"][0][0][0] == "Use Narrator New"
    assert len(final_reply) == 1
    state = json.loads((tmp_path / "wa-actions.json").read_text(encoding="utf-8"))
    serialized_state = json.dumps(state)
    assert "4368120864006" not in serialized_state
    assert "sample-token-new" not in serialized_state


def test_build_report_bare_voice_name_text_selects_pending_sample(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-bare-name"
    job_dir.mkdir(parents=True)
    (job_dir / "voice_audition").mkdir(parents=True)
    job = {
        "job_id": "job-bare-name",
        "status": "waiting_voice_selection",
        "storage": {"job_dir": str(job_dir)},
        "whatsapp": {"sender_ref": "4368120864006", "session_ref": "session-1", "chat_ref": "chat-ref-1"},
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "pending_batch": [
                    {"label": "Florian", "preset_key": "voice-florian", "callback_token": "sample-token-florian"},
                    {"label": "Seraphina", "preset_key": "voice-seraphina", "callback_token": "sample-token-seraphina"},
                ],
            }
        },
    }
    private_payload = {
        "candidates": {
            "sample-token-florian": {
                "candidate_key": "voice-florian",
                "public": {
                    "label": "Florian",
                    "preset_key": "voice-florian",
                    "callback_token": "sample-token-florian",
                    "score": 80,
                    "tags": ["audiobook", "narration"],
                },
            },
            "sample-token-seraphina": {
                "candidate_key": "voice-seraphina",
                "public": {
                    "label": "Seraphina",
                    "preset_key": "voice-seraphina",
                    "callback_token": "sample-token-seraphina",
                    "score": 90,
                    "tags": ["audiobook", "narration"],
                },
            },
        }
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")
    (job_dir / "voice_audition" / "private.json").write_text(json.dumps(private_payload), encoding="utf-8")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {"messages": [_text_message(body_text="Florian")], "ok": True}
        return {"ok": True, "message_id": f"wamid.out.{len(requests)}"}

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(module, "_send_public_share_if_ready", lambda **_: {"status": "not_ready"})

    report = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
    )

    assert report["status"] == "pass"
    assert report["voice_text_candidate_count"] == 1
    assert report["voice_text_processed"] == 1
    post = [row for row in requests if row["method"] == "POST"]
    assert len(post) == 1
    assert dict(post[0]["body"])["chat_ref"] == "chat-ref-1"
    assert dict(post[0]["body"])["text"] == "Selected Florian. I am rendering the audiobook with that voice now."
    updated_job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    selection = dict(dict(updated_job.get("provider") or {}).get("voice_selection") or {})
    assert selection["selected"]["label"] == "Florian"
    assert selection["selected_candidate_key"] == "voice-florian"


def test_build_report_use_automatic_cast_text_skips_optional_preview(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    selected: list[dict[str, str]] = []
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-automatic-cast-text"
    job_dir.mkdir(parents=True)
    job = {
        "job_id": "job-automatic-cast-text",
        "status": "waiting_voice_selection",
        "storage": {"job_dir": str(job_dir)},
        "whatsapp": {
            "sender_ref": "4368120864006",
            "session_ref": "session-1",
            "chat_ref": "chat-ref-1",
        },
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "pending_candidate_keys": ["voice-ranked", "voice-second"],
                "pending_batch": [
                    {
                        "label": "Ranked Narrator",
                        "preset_key": "voice-ranked",
                        "callback_token": "ranked-token",
                    },
                    {
                        "label": "Second Narrator",
                        "preset_key": "voice-second",
                        "callback_token": "second-token",
                    },
                ],
            }
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {"messages": [_text_message(body_text="use automatic cast")], "ok": True}
        return {"ok": True, "message_id": f"wamid.out.{len(requests)}"}

    def _fake_apply(*, callback_token: str, action: str) -> dict[str, object]:
        selected.append({"callback_token": callback_token, "action": action})
        return {
            **job,
            "status": "rendering",
            "provider": {
                "voice_selection": {
                    "status": "selected_by_user",
                    "selected": {"label": "Ranked Narrator", "preset_key": "voice-ranked"},
                    "selected_candidate_key": "voice-ranked",
                    "automatic_cast_approved_by_user": True,
                    "optional_preview_skipped": True,
                    "pending_candidate_keys": [],
                    "pending_batch": [],
                }
            },
        }

    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "apply_audiobook_voice_audition_action",
        _fake_apply,
    )
    monkeypatch.setattr(module, "_send_public_share_if_ready", lambda **_: {"status": "not_ready"})

    report = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
    )

    assert report["status"] == "pass"
    assert report["voice_text_candidate_count"] == 1
    assert report["voice_text_processed"] == 1
    assert selected == [{"callback_token": "ranked-token", "action": "use_automatic_cast"}]
    post = [row for row in requests if row["method"] == "POST"]
    assert len(post) == 1
    assert dict(post[0]["body"])["text"] == "Automatic cast selected. I am rendering the audiobook now."
    state = json.loads((tmp_path / "wa-actions.json").read_text(encoding="utf-8"))
    action = next(iter(state["actions"].values()))
    assert action["automatic_cast_approved_by_user"] is True
    assert action["optional_preview_skipped"] is True
    serialized_state = json.dumps(state)
    assert "4368120864006" not in serialized_state
    assert "ranked-token" not in serialized_state
    assert "second-token" not in serialized_state


def test_build_report_dismiss_named_text_sends_replacement_voice(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    sample_path = tmp_path / "replacement-named.mp3"
    sample_path.write_bytes(b"ID3replacement")
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-dismiss-named"
    job_dir.mkdir(parents=True)
    job = {
        "job_id": "job-dismiss-named",
        "status": "waiting_voice_selection",
        "storage": {"job_dir": str(job_dir)},
        "whatsapp": {"chat_ref": "chat-ref-1", "sender_ref": "4368120864006"},
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "pending_batch": [
                    {"label": "Florian", "preset_key": "voice-florian", "callback_token": "sample-token-florian"},
                    {"label": "Seraphina", "preset_key": "voice-seraphina", "callback_token": "sample-token-seraphina"},
                ],
                "last_action": {
                    "action": "dismiss",
                    "status": "replacement_ready",
                    "replacement_candidate_keys": ["voice-new"],
                },
            }
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {"messages": [_text_message(body_text="dismiss Florian")], "ok": True}
        return {"ok": True, "message_id": f"wamid.out.{len(requests)}"}

    def _fake_apply(*, callback_token: str, action: str) -> dict[str, object]:
        assert callback_token == "sample-token-florian"
        assert action == "dismiss"
        return {
            **job,
            "provider": {
                "voice_selection": {
                    "status": "waiting_user_choice",
                    "last_action": {
                        "action": "dismiss",
                        "status": "replacement_ready",
                        "replacement_candidate_keys": ["voice-new"],
                    },
                    "pending_batch": [
                        {
                            "label": "Narrator New",
                            "preset_key": "voice-new",
                            "callback_token": "sample-token-new",
                            "sample_file": "sample-token-new.mp3",
                        }
                    ],
                }
            },
        }

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(module.audiobook_epub_pipeline, "apply_audiobook_voice_audition_action", _fake_apply)
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "audiobook_voice_audition_sample_messages",
        lambda _job: [
            {
                "token": "sample-token-new",
                "label": "Narrator New",
                "matched_tags": ["warm"],
                "audio_path": str(sample_path),
            }
            ],
    )
    monkeypatch.setattr(module.audiobook_epub_pipeline, "record_audiobook_voice_sample_delivery", lambda *, job, sample_receipts: job)
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_voice_sample_audio_quality_gate", lambda _path: {"ok": True})
    monkeypatch.setattr(module, "_whatsapp_voice_sample_media_path", lambda path: path)

    report = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
    )

    assert report["status"] == "pass"
    assert report["voice_text_candidate_count"] == 1
    assert report["voice_text_processed"] == 1
    assert report["voice_sample_sent"] == 1
    media_post = [row for row in requests if row["method"] == "POST" and dict(row["body"]).get("media_base64")]
    button_post = [row for row in requests if row["method"] == "POST" and dict(row["body"]).get("buttons")]
    reply_post = [
        row for row in requests if row["method"] == "POST" and dict(row["body"]).get("text") == "Dismissed Florian. I sent 1 replacement audiobook voice sample."
    ]
    assert len(media_post) == 1
    assert len(button_post) == 1
    assert len(reply_post) == 1
    assert dict(reply_post[0]["body"])["chat_ref"] == "chat-ref-1"


def test_iter_audiobook_voice_text_candidates_caches_waiting_job_by_sender_and_chat(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    sender_calls: list[str] = []
    chat_calls: list[str] = []

    def _fake_latest_job(*, sender_digits: str, predicate) -> dict[str, object]:
        sender_calls.append(sender_digits)
        return {
            "status": "waiting_voice_selection",
            "provider": {
                "voice_selection": {
                    "status": "waiting_user_choice",
                    "pending_batch": [
                        {"label": "Florian", "preset_key": "voice-florian", "callback_token": "sample-token-florian"},
                    ],
                }
            },
        }

    def _fake_latest_job_for_chat_ref(*, chat_ref: str, predicate) -> dict[str, object]:
        chat_calls.append(chat_ref)
        return {}

    monkeypatch.setattr(module, "_latest_whatsapp_audiobook_job", _fake_latest_job)
    monkeypatch.setattr(module, "_latest_whatsapp_audiobook_job_for_chat_ref", _fake_latest_job_for_chat_ref)

    candidates = module._iter_audiobook_voice_text_candidates(
        [
            _text_message(id="wamid.voice.cache.1", body_text="Florian"),
            _text_message(id="wamid.voice.cache.2", body_text="dismiss all"),
            _text_message(id="wamid.voice.cache.3", body_text="Florian"),
        ]
    )

    assert len(candidates) == 3
    assert sender_calls == ["4368120864006"]
    assert chat_calls == []


def test_dismiss_all_pending_whatsapp_voice_samples_records_feedback_for_each_voice(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    recorded: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-dismiss-all-feedback"
    job_dir.mkdir(parents=True)
    job = {
        "job_id": "job-dismiss-all-feedback",
        "status": "waiting_voice_selection",
        "storage": {"job_dir": str(job_dir)},
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "pending_candidate_keys": ["old-1", "old-2", "old-3"],
                "pending_batch": [
                    {"label": "Old One", "preset_key": "old-1", "callback_token": "old-token-1"},
                    {"label": "Old Two", "preset_key": "old-2", "callback_token": "old-token-2"},
                    {"label": "Old Three", "preset_key": "old-3", "callback_token": "old-token-3"},
                ],
            }
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")

    def fake_record_feedback(**kwargs: object) -> dict[str, object]:
        recorded.append(dict(kwargs))
        return {"status": "recorded"}

    def fake_prepare(*, job_dir: Path, refill_pending: bool) -> dict[str, object]:
        prepared = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
        selection = dict(dict(prepared["provider"])["voice_selection"])
        selection.update(
            {
                "status": "waiting_user_choice",
                "replacement_candidate_keys": ["new-1"],
                "pending_batch": [{"label": "New One", "preset_key": "new-1", "callback_token": "new-token-1"}],
            }
        )
        prepared["provider"]["voice_selection"] = selection
        (job_dir / "job.json").write_text(json.dumps(prepared), encoding="utf-8")
        return prepared

    monkeypatch.setattr(module.audiobook_epub_pipeline, "record_audiobook_voice_feedback", fake_record_feedback)
    monkeypatch.setattr(module.audiobook_epub_pipeline, "prepare_audiobook_voice_audition", fake_prepare)

    updated, dismissed_count = module._dismiss_all_pending_whatsapp_voice_samples(job)

    assert dismissed_count == 3
    assert [row["action"] for row in recorded] == ["dismiss_all", "dismiss_all", "dismiss_all"]
    assert [dict(row["candidate"])["preset_key"] for row in recorded] == ["old-1", "old-2", "old-3"]
    selection = updated["provider"]["voice_selection"]
    assert selection["dismissed_candidate_keys"] == ["old-1", "old-2", "old-3"]
    assert selection["last_action"]["replacement_count"] == 1


def test_build_report_use_callback_sends_replacement_voice_when_selected_provider_blocked(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    sample_path = tmp_path / "replacement.mp3"
    sample_path.write_bytes(b"ID3replacement")
    job_dir = tmp_path / "job-use-provider-blocked"
    job_dir.mkdir()
    job = {
        "job_id": "job-use-provider-blocked",
        "status": "waiting_voice_selection",
        "metadata": {"title": "Blocked Voice Book"},
        "storage": {"job_dir": str(job_dir)},
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "reason": "selected_voice_provider_balance_blocked",
                "last_action": {
                    "action": "offer_replacement",
                    "status": "replacement_ready",
                    "replacement_candidate_keys": ["voice-replacement"],
                },
                "pending_batch": [
                    {
                        "preset_key": "voice-replacement",
                        "callback_token": "replacement-token",
                        "sample_file": "replacement.mp3",
                        "label": "Replacement Narrator",
                    }
                ],
            }
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {"messages": [_selected_message(chat_ref="chat-ref-1")], "ok": True}
        return {"ok": True, "message_id": f"wamid.out.{len(requests)}"}

    def _fake_handle_callback(**_: object) -> dict[str, object]:
        return {
            "status": "applied",
            "kind": "audiobook_voice",
            "action": "use",
            "job": job,
            "reply_text": "Voice selected.",
        }

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "audiobook_voice_audition_sample_messages",
        lambda _job: [
            {
                "token": "replacement-token",
                "label": "Replacement Narrator",
                "matched_tags": ["explicit replacement"],
                "audio_path": str(sample_path),
            }
        ],
    )
    monkeypatch.setattr(module.audiobook_epub_pipeline, "record_audiobook_voice_sample_delivery", lambda *, job, sample_receipts: job)

    report = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
        handle_callback=_fake_handle_callback,
    )

    assert report["status"] == "pass"
    assert report["processed"] == 1
    assert report["voice_sample_sent"] == 1
    assert report["share_link_sent"] == 0
    media_post = [row for row in requests if row["method"] == "POST" and dict(row["body"]).get("media_base64")]
    button_post = [row for row in requests if row["method"] == "POST" and dict(row["body"]).get("buttons")]
    final_reply = [
        row
        for row in requests
        if row["method"] == "POST" and "selected audiobook voice is blocked" in str(dict(row["body"]).get("text") or "")
    ]
    assert len(media_post) == 1
    assert dict(media_post[0]["body"])["chat_ref"] == "chat-ref-1"
    assert len(button_post) == 1
    assert dict(button_post[0]["body"])["chat_ref"] == "chat-ref-1"
    assert str(dict(button_post[0]["body"])["buttons"][0][0][1]).startswith("ab|u|replacement-token|")
    assert len(final_reply) == 1
    assert dict(final_reply[0]["body"])["chat_ref"] == "chat-ref-1"
    state = json.loads((tmp_path / "wa-actions.json").read_text(encoding="utf-8"))
    action = next(iter(state["actions"].values()))
    assert action["replacement_sample_sent"] == 1
    assert action["replacement_sample_delivery_status"] == "sent"
    assert action["replacement_sample_attempted"] == 1
    assert action["replacement_sample_failed"] == 0
    serialized_state = json.dumps(state)
    assert "4368120864006" not in serialized_state
    assert "replacement-token" not in serialized_state


def test_build_report_use_callback_records_skipped_replacement_delivery(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    sample_path = tmp_path / "replacement-skipped.mp3"
    sample_path.write_bytes(b"ID3replacement")
    job_dir = tmp_path / "job-use-provider-blocked-skipped"
    job_dir.mkdir()
    job = {
        "job_id": "job-use-provider-blocked-skipped",
        "status": "waiting_voice_selection",
        "metadata": {"title": "Blocked Voice Book"},
        "storage": {"job_dir": str(job_dir)},
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "reason": "selected_voice_provider_balance_blocked",
                "last_action": {
                    "action": "offer_replacement",
                    "status": "replacement_ready",
                    "replacement_candidate_keys": ["voice-replacement"],
                },
                "pending_batch": [
                    {
                        "preset_key": "voice-replacement",
                        "callback_token": "replacement-token",
                        "sample_file": "replacement.mp3",
                        "label": "Replacement Narrator",
                    }
                ],
            }
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {"messages": [_selected_message(chat_ref="chat-ref-1")], "ok": True}
        body = dict(kwargs.get("body") or {})
        if body.get("buttons"):
            return {"ok": False, "message_id": "wamid.buttons.failed", "reason": "poll_send_failed"}
        return {"ok": True, "message_id": f"wamid.out.{len(requests)}"}

    def _fake_handle_callback(**_: object) -> dict[str, object]:
        return {
            "status": "applied",
            "kind": "audiobook_voice",
            "action": "use",
            "job": job,
            "reply_text": "Voice selected.",
        }

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "audiobook_voice_audition_sample_messages",
        lambda _job: [
            {
                "token": "replacement-token",
                "label": "Replacement Narrator",
                "matched_tags": ["explicit replacement"],
                "audio_path": str(sample_path),
            }
        ],
    )
    monkeypatch.setattr(module.audiobook_epub_pipeline, "record_audiobook_voice_sample_delivery", lambda *, job, sample_receipts: job)

    report = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
        handle_callback=_fake_handle_callback,
    )

    assert report["status"] == "pass"
    assert report["voice_sample_sent"] == 0
    reply_post = [
        row
        for row in requests
        if row["method"] == "POST" and "could not deliver" in str(dict(row["body"]).get("text") or "")
    ]
    assert len(reply_post) == 1
    state = json.loads((tmp_path / "wa-actions.json").read_text(encoding="utf-8"))
    action = next(iter(state["actions"].values()))
    assert action["replacement_sample_delivery_status"] == "skipped"
    assert action["replacement_sample_attempted"] == 1
    assert action["replacement_sample_sent"] == 0
    assert action["replacement_sample_skipped"] == 1
    assert action["replacement_sample_delivery_reason"] == "whatsapp_voice_sample_send_skipped"


def test_build_report_use_callback_continues_selected_job_and_sends_public_share(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-use-continue-share"
    job_dir.mkdir(parents=True)
    selected_job = {
        "job_id": "job-use-continue-share",
        "status": "voice_selected",
        "metadata": {"title": "Selected Share Book", "author": "Writer", "language": "en-US"},
        "storage": {"job_dir": str(job_dir)},
        "whatsapp": {"sender_ref": "4368120864006", "session_ref": "session-1", "chat_ref": "chat-ref-1"},
        "provider": {
            "voice_selection": {
                "status": "selected_by_user",
                "selected_candidate_key": "voice-selected",
                "selected_callback_token": "selected-token",
                "selected": {"label": "Selected Voice"},
            }
        },
        "audiobookshelf_import": {
            "status": "waiting_for_m4b",
            "public_share": {"status": "waiting_for_render"},
        },
    }
    (job_dir / "job.json").write_text(json.dumps(selected_job, indent=2, sort_keys=True), encoding="utf-8")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {"messages": [_selected_message(chat_ref="chat-ref-1")], "ok": True}
        return {"ok": True, "message_id": f"wamid.use-share.{len(requests)}"}

    def _fake_handle_callback(**_: object) -> dict[str, object]:
        return {
            "status": "applied",
            "kind": "audiobook_voice",
            "action": "use",
            "job": selected_job,
            "reply_text": "Voice selected.",
        }

    def _fake_continue(job_path: Path) -> dict[str, object]:
        assert job_path == job_dir
        resumed = {
            **selected_job,
            "status": "audiobookshelf_imported",
            "audio_publication_gate": {"status": "pass", "issues": []},
            "audiobookshelf_import": {
                "status": "imported",
                "target_path": str(tmp_path / "Selected Share Book.m4b"),
                "public_share": {
                    "status": "public_share_ready",
                    "absolute_url": "https://abs.example.com/share/selected-share-book",
                    "token_exposed": False,
                    "raw_library_path_exposed": False,
                },
            },
        }
        (job_dir / "job.json").write_text(json.dumps(resumed, indent=2, sort_keys=True), encoding="utf-8")
        return resumed

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(module.audiobook_epub_pipeline, "continue_job", _fake_continue)

    report = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
        handle_callback=_fake_handle_callback,
    )

    assert report["status"] == "pass"
    assert report["processed"] == 1
    assert report["share_link_sent"] == 1
    share_posts = [row for row in requests if row["method"] == "POST"]
    assert len(share_posts) == 1
    payload = dict(share_posts[0]["body"])
    assert payload["to"] == "4368120864006"
    assert payload["chat_ref"] == "chat-ref-1"
    assert payload["heyy_ai_name"] == "Selected Voice"
    assert payload["heyy_ai_key"] == "audiobook_voice_voice_selected"
    assert "https://abs.example.com/share/selected-share-book" in str(payload["text"])
    assert "buttons" not in payload
    updated = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    assert updated["whatsapp"]["public_share_delivery"]["status"] == "sent"
    assert updated["audiobookshelf_import"]["public_share"]["whatsapp_delivery"]["status"] == "sent"
    state = json.loads((tmp_path / "wa-actions.json").read_text(encoding="utf-8"))
    action = next(iter(state["actions"].values()))
    assert action["public_share_sent"] is True
    assert action["post_voice_selection_continue_status"] == "audiobookshelf_imported"
    serialized_state = json.dumps(state)
    assert "4368120864006" not in serialized_state
    assert "selected-token" not in serialized_state


def test_build_report_recovers_sender_ref_for_chat_ref_only_voice_sample_resend(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    sample_path = tmp_path / "resend.mp3"
    sample_path.write_bytes(b"ID3resend")
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-resend"
    job_dir.mkdir(parents=True)
    job = {
        "job_id": "job-resend",
        "status": "waiting_voice_selection",
        "metadata": {"title": "Resend Book", "language": "en"},
        "storage": {"job_dir": str(job_dir)},
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "pending_batch": [
                    {
                        "preset_key": "voice-1",
                        "callback_token": "sample-token-1",
                    }
                ],
            }
        },
        "totals": {"chapter_count": 1, "char_count": 100},
        "whatsapp": {
            "chat_ref": "chat-ref-1",
            "sender_ref": "4368120864006",
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {
                "messages": [
                    _text_message(
                        body_text="please resend the voice samples",
                        sender_digits="",
                    )
                ],
                "ok": True,
            }
        return {"ok": True, "message_id": f"wamid.out.{len(requests)}"}

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "audiobook_voice_audition_sample_messages",
        lambda _job: [
            {
                "token": "sample-token-1",
                "label": "Narrator One",
                "matched_tags": ["clear"],
                "audio_path": str(sample_path),
            }
        ],
    )
    monkeypatch.setattr(module.audiobook_epub_pipeline, "record_audiobook_voice_sample_delivery", lambda *, job, sample_receipts: job)

    report = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
    )

    assert report["status"] == "pass"
    assert report["status_processed"] == 1
    assert report["voice_sample_sent"] == 1
    media_post = [row for row in requests if row["method"] == "POST" and dict(row["body"]).get("media_base64")]
    button_post = [row for row in requests if row["method"] == "POST" and dict(row["body"]).get("buttons")]
    reply_post = [
        row
        for row in requests
        if row["method"] == "POST" and "I resent 1 audiobook voice sample." in str(dict(row["body"]).get("text") or "")
    ]
    assert len(media_post) == 1
    assert dict(media_post[0]["body"])["to"] == "4368120864006"
    assert dict(media_post[0]["body"])["chat_ref"] == "chat-ref-1"
    assert len(button_post) == 1
    assert dict(button_post[0]["body"])["to"] == "4368120864006"
    assert dict(button_post[0]["body"])["chat_ref"] == "chat-ref-1"
    assert len(reply_post) == 1
    assert dict(reply_post[0]["body"])["chat_ref"] == "chat-ref-1"


def test_build_report_recovers_sender_ref_for_chat_ref_only_voice_sample_resend_when_newest_chat_job_lacks_sender_ref(
    monkeypatch, tmp_path: Path
) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    sample_path = tmp_path / "resend.mp3"
    sample_path.write_bytes(b"ID3resend")
    jobs_root = tmp_path / "jobs"

    older_dir = jobs_root / "job-resend-older"
    older_dir.mkdir(parents=True)
    older_job = {
        "job_id": "job-resend-older",
        "status": "waiting_voice_selection",
        "updated_at": "2026-06-21T05:00:00Z",
        "metadata": {"title": "Resend Book Older", "language": "en"},
        "storage": {"job_dir": str(older_dir)},
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "pending_batch": [{"preset_key": "voice-1", "callback_token": "sample-token-1"}],
            }
        },
        "whatsapp": {"chat_ref": "chat-ref-1", "sender_ref": "4368120864006"},
    }
    (older_dir / "job.json").write_text(json.dumps(older_job), encoding="utf-8")

    newer_dir = jobs_root / "job-resend-newer"
    newer_dir.mkdir(parents=True)
    newer_job = {
        "job_id": "job-resend-newer",
        "status": "waiting_voice_selection",
        "updated_at": "2026-06-21T06:00:00Z",
        "metadata": {"title": "Resend Book Newer", "language": "en"},
        "storage": {"job_dir": str(newer_dir)},
        "provider": {
            "voice_selection": {
                "status": "waiting_user_choice",
                "pending_batch": [{"preset_key": "voice-2", "callback_token": "sample-token-2"}],
            }
        },
        "whatsapp": {"chat_ref": "chat-ref-1", "sender_ref": ""},
    }
    (newer_dir / "job.json").write_text(json.dumps(newer_job), encoding="utf-8")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {
                "messages": [
                    _text_message(
                        body_text="please resend the voice samples",
                        sender_digits="",
                    )
                ],
                "ok": True,
            }
        return {"ok": True, "message_id": f"wamid.out.{len(requests)}"}

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "audiobook_voice_audition_sample_messages",
        lambda _job: [
            {
                "token": "sample-token-1",
                "label": "Narrator One",
                "matched_tags": ["clear"],
                "audio_path": str(sample_path),
            }
        ],
    )
    monkeypatch.setattr(module.audiobook_epub_pipeline, "record_audiobook_voice_sample_delivery", lambda *, job, sample_receipts: job)

    report = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
    )

    assert report["status"] == "pass"
    assert report["status_processed"] == 1
    assert report["voice_sample_sent"] == 1
    media_post = [row for row in requests if row["method"] == "POST" and dict(row["body"]).get("media_base64")]
    assert len(media_post) == 1
    assert dict(media_post[0]["body"])["to"] == "4368120864006"
    assert dict(media_post[0]["body"])["chat_ref"] == "chat-ref-1"


def test_build_report_ignores_inbound_without_callback_payload(tmp_path: Path) -> None:
    module = _module()

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        assert kwargs["method"] == "GET"
        return {
            "messages": [
                _selected_message(selected_button_id="", selected_button_id_present=False),
                _selected_message(direction="outbound"),
            ],
            "ok": True,
        }

    report = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
        handle_callback=lambda **_: (_ for _ in ()).throw(AssertionError("should not handle")),
    )

    assert report["status"] == "pass"
    assert report["candidate_count"] == 0
    assert report["processed"] == 0


def test_build_report_sends_ready_whatsapp_audiobookshelf_share_followup(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-share"
    job_dir.mkdir(parents=True)
    job = {
        "job_id": "job-share",
        "status": "audiobookshelf_imported",
        "metadata": {"title": "Shared Book", "author": "Writer", "language": "en-US"},
        "storage": {"job_dir": str(job_dir)},
        "audio_publication_gate": {"status": "pass", "issues": []},
        "whatsapp": {"sender_ref": "4368120864006", "session_ref": "session-1", "chat_ref": "chat-ref-1"},
        "audiobookshelf_import": {
            "status": "imported",
            "target_path": str(tmp_path / "Shared Book.m4b"),
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://abs.example.com/share/shared-book",
                "token_exposed": False,
                "raw_library_path_exposed": False,
            },
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {"messages": [], "ok": True}
        return {"ok": True, "message_id": "wamid.share.1"}

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)

    report = module.build_report(
        _args(tmp_path, audiobook_followup_enabled=True),
        request_json=_fake_request_json,
    )

    assert report["status"] == "pass"
    assert report["share_link_sent"] == 1
    assert report["followup_summary"] == {"attempted": 1, "sent": 1, "errors": 0, "blocked": 0, "blocked_reasons": {}}
    share_posts = [row for row in requests if row["method"] == "POST"]
    assert len(share_posts) == 1
    payload = dict(share_posts[0]["body"])
    assert payload["to"] == "4368120864006"
    assert payload["chat_ref"] == "chat-ref-1"
    assert "Audiobookshelf finished scanning Shared Book" in str(payload["text"])
    assert "https://abs.example.com/share/shared-book" in str(payload["text"])
    assert "buttons" not in payload
    updated = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    assert updated["whatsapp"]["public_share_delivery"]["status"] == "sent"
    assert updated["audiobookshelf_import"]["public_share"]["whatsapp_delivery"]["status"] == "sent"

    receipt = module.audiobook_epub_pipeline.build_audiobook_job_receipt(job_dir=job_dir)
    receipt_import = receipt["audiobookshelf_import"]
    share_delivery = updated["audiobookshelf_import"]["public_share"]["whatsapp_delivery"]
    assert receipt_import["public_share_whatsapp_delivery_status"] == "sent"
    assert receipt_import["public_share_whatsapp_message_id_present"] is True
    assert receipt_import["public_share_whatsapp_message_id_sha256"] == share_delivery["message_id_sha256"]
    assert receipt_import["public_share_whatsapp_callback_tokens_exposed"] is False
    assert receipt_import["public_share_whatsapp_audiobookshelf_token_exposed"] is False
    assert receipt["whatsapp"]["sender_bound"] is True
    assert receipt["whatsapp"]["session_bound"] is True

    playback_job = module.audiobook_epub_pipeline.record_audiobook_playback_acceptance(
        job_dir=job_dir,
        accepted=True,
        source="whatsapp_button",
        message_id="wamid.playback.1",
        feedback="whatsapp_button_playback_accepted",
    )
    assert playback_job["playback_acceptance"]["source"] == "whatsapp_button"
    playback_receipt = module.audiobook_epub_pipeline.build_audiobook_job_receipt(job_dir=job_dir)
    playback = playback_receipt["playback_acceptance"]
    assert playback["status"] == "accepted"
    assert playback["source"] == "whatsapp_button"
    assert playback["message_id_sha256"]
    assert playback["whatsapp_public_share_message_id_sha256"] == share_delivery["message_id_sha256"]
    rendered = json.dumps(playback_receipt, sort_keys=True)
    assert "4368120864006" not in rendered
    assert "wamid.share.1" not in rendered
    assert "wamid.playback.1" not in rendered


def test_build_report_sends_share_followup_from_extra_audiobook_job_root(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    primary_root = tmp_path / "primary-jobs"
    extra_root = tmp_path / "extra-jobs"
    job_dir = extra_root / "job-extra-share"
    job_dir.mkdir(parents=True)
    primary_root.mkdir(parents=True)
    job = {
        "job_id": "job-extra-share",
        "status": "audiobookshelf_imported",
        "metadata": {"title": "Extra Root Book", "author": "Writer", "language": "en-US"},
        "storage": {"job_dir": str(job_dir)},
        "audio_publication_gate": {"status": "pass", "issues": []},
        "whatsapp": {"sender_ref": "4368120864006", "session_ref": "session-1", "chat_ref": "chat-ref-1"},
        "audiobookshelf_import": {
            "status": "imported",
            "target_path": str(tmp_path / "Extra Root Book.m4b"),
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://abs.example.com/share/extra-root-book",
                "token_exposed": False,
                "raw_library_path_exposed": False,
            },
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {"messages": [], "ok": True}
        return {"ok": True, "message_id": "wamid.extra.share.1"}

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(primary_root))
    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_JOBS_ROOTS", str(extra_root))
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: primary_root)

    report = module.build_report(
        _args(tmp_path, audiobook_followup_enabled=True),
        request_json=_fake_request_json,
    )

    assert report["status"] == "pass"
    assert report["share_link_sent"] == 1
    assert report["followup_summary"] == {"attempted": 1, "sent": 1, "errors": 0, "blocked": 0, "blocked_reasons": {}}
    posts = [row for row in requests if row["method"] == "POST"]
    assert len(posts) == 1
    assert "https://abs.example.com/share/extra-root-book" in str(dict(posts[0]["body"])["text"])
    updated = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    assert updated["whatsapp"]["public_share_delivery"]["status"] == "sent"


def test_build_report_does_not_resend_whatsapp_share_when_nested_delivery_is_sent(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-nested-share-sent"
    job_dir.mkdir(parents=True)
    job = {
        "job_id": "job-nested-share-sent",
        "status": "audiobookshelf_imported",
        "metadata": {"title": "Already Shared Book", "author": "Writer", "language": "en-US"},
        "storage": {"job_dir": str(job_dir)},
        "whatsapp": {"sender_ref": "4368120864006", "session_ref": "session-1", "chat_ref": "chat-ref-1"},
        "audiobookshelf_import": {
            "status": "imported",
            "target_path": str(tmp_path / "Already Shared Book.m4b"),
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://abs.example.com/share/already-shared-book",
                "token_exposed": False,
                "raw_library_path_exposed": False,
                "whatsapp_delivery": {
                    "status": "sent",
                    "message_id_sha256": "a" * 24,
                    "callback_tokens_exposed": False,
                    "audiobookshelf_token_exposed": False,
                },
            },
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {"messages": [], "ok": True}
        raise AssertionError("public share should not be resent when nested delivery is already sent")

    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)

    report = module.build_report(
        _args(tmp_path, audiobook_followup_enabled=True),
        request_json=_fake_request_json,
    )

    assert report["status"] == "pass"
    assert report["share_link_sent"] == 0
    assert report["followup_summary"] == {"attempted": 0, "sent": 0, "errors": 0, "blocked": 0, "blocked_reasons": {}}
    assert all(row["method"] == "GET" for row in requests)


def test_build_report_dedupes_whatsapp_share_followups_across_duplicate_jobs(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"
    older_dir = jobs_root / "job-share-older"
    newer_dir = jobs_root / "job-share-newer"
    older_dir.mkdir(parents=True)
    newer_dir.mkdir(parents=True)
    share_url = "https://abs.example.com/share/shared-book"

    older_job = {
        "job_id": "job-share-older",
        "status": "audiobookshelf_imported",
        "metadata": {"title": "Shared Book", "author": "Writer", "language": "en-US"},
        "storage": {"job_dir": str(older_dir)},
        "audio_publication_gate": {"status": "pass", "issues": []},
        "whatsapp": {"sender_ref": "4368120864006", "session_ref": "session-1", "chat_ref": "chat-ref-1"},
        "audiobookshelf_import": {
            "status": "imported",
            "target_path": str(tmp_path / "Shared Book Older.m4b"),
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": share_url,
                "token_exposed": False,
                "raw_library_path_exposed": False,
            },
        },
    }
    newer_job = {
        "job_id": "job-share-newer",
        "status": "audiobookshelf_imported",
        "metadata": {"title": "Shared Book", "author": "Writer", "language": "en-US"},
        "storage": {"job_dir": str(newer_dir)},
        "audio_publication_gate": {"status": "pass", "issues": []},
        "whatsapp": {"sender_ref": "4368120864006", "session_ref": "session-1", "chat_ref": "chat-ref-1"},
        "audiobookshelf_import": {
            "status": "imported",
            "target_path": str(tmp_path / "Shared Book Newer.m4b"),
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": share_url,
                "token_exposed": False,
                "raw_library_path_exposed": False,
            },
        },
    }
    (older_dir / "job.json").write_text(json.dumps(older_job), encoding="utf-8")
    (newer_dir / "job.json").write_text(json.dumps(newer_job), encoding="utf-8")
    older_time = 1_700_000_000
    newer_time = older_time + 60
    os.utime(older_dir / "job.json", (older_time, older_time))
    os.utime(newer_dir / "job.json", (newer_time, newer_time))

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {"messages": [], "ok": True}
        return {"ok": True, "message_id": "wamid.share.newest"}

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)

    report = module.build_report(
        _args(tmp_path, audiobook_followup_enabled=True, audiobook_followup_limit=5),
        request_json=_fake_request_json,
    )

    assert report["status"] == "pass"
    assert report["share_link_sent"] == 1
    assert report["followup_summary"] == {"attempted": 1, "sent": 1, "errors": 0, "blocked": 0, "blocked_reasons": {}}
    posts = [row for row in requests if row["method"] == "POST"]
    assert len(posts) == 1
    older_updated = json.loads((older_dir / "job.json").read_text(encoding="utf-8"))
    newer_updated = json.loads((newer_dir / "job.json").read_text(encoding="utf-8"))
    assert "public_share_delivery" not in older_updated.get("whatsapp", {})
    assert newer_updated["whatsapp"]["public_share_delivery"]["status"] == "sent"
    assert newer_updated["audiobookshelf_import"]["public_share"]["whatsapp_delivery"]["status"] == "sent"


def test_build_report_resume_due_then_sends_whatsapp_public_share_followup(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-resume-share"
    job_dir.mkdir(parents=True)
    job = {
        "job_id": "job-resume-share",
        "status": "waiting_provider_throttle",
        "metadata": {"title": "Resume Share Book", "author": "Writer", "language": "en-US"},
        "storage": {"job_dir": str(job_dir)},
        "whatsapp": {"sender_ref": "4368120864006", "session_ref": "session-1", "chat_ref": "chat-ref-1"},
        "audiobookshelf_import": {
            "status": "waiting_for_m4b",
            "public_share": {"status": "waiting_for_audiobookshelf_scan"},
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job, indent=2, sort_keys=True), encoding="utf-8")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {"messages": [], "ok": True}
        return {"ok": True, "message_id": "wamid.share.after.resume"}

    def _fake_resume_due(**_: object) -> dict[str, object]:
        resumed = {
            **job,
            "status": "audiobookshelf_imported",
            "audio_publication_gate": {"status": "pass", "issues": []},
            "audiobookshelf_import": {
                "status": "imported",
                "target_path": str(tmp_path / "Resume Share Book.m4b"),
                "public_share": {
                    "status": "public_share_ready",
                    "absolute_url": "https://abs.example.com/share/resume-share-book",
                    "token_exposed": False,
                    "raw_library_path_exposed": False,
                },
            },
        }
        (job_dir / "job.json").write_text(json.dumps(resumed, indent=2, sort_keys=True), encoding="utf-8")
        return {"ran": True, "attempted": 1, "resumed": 1, "errors": 0}

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(module.audiobook_epub_pipeline, "resume_due_audiobook_jobs", _fake_resume_due)

    report = module.build_report(
        _args(tmp_path, audiobook_resume_due=True, audiobook_followup_enabled=True),
        request_json=_fake_request_json,
    )

    assert report["status"] == "pass"
    assert report["resume_summary"] == {"ran": True, "attempted": 1, "resumed": 1, "errors": 0}
    assert report["followup_summary"] == {"attempted": 1, "sent": 1, "errors": 0, "blocked": 0, "blocked_reasons": {}}
    assert report["share_link_sent"] == 1
    share_posts = [row for row in requests if row["method"] == "POST"]
    assert len(share_posts) == 1
    payload = dict(share_posts[0]["body"])
    assert payload["to"] == "4368120864006"
    assert payload["chat_ref"] == "chat-ref-1"
    assert "https://abs.example.com/share/resume-share-book" in str(payload["text"])
    assert "buttons" not in payload
    assert payload["heyy_ai_name"] == "Herta (Heyy Lady)"
    updated = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    assert updated["whatsapp"]["public_share_delivery"]["status"] == "sent"
    assert updated["audiobookshelf_import"]["public_share"]["whatsapp_delivery"]["status"] == "sent"


def test_public_share_persona_payload_uses_selected_voice_label(tmp_path: Path) -> None:
    module = _module()

    payload = module._public_share_persona_payload(
        {
            "provider": {
                "voice_selection": {
                    "selected_candidate_key": "unmixr_remy_d4477bcd",
                    "selected": {"label": "Remy"},
                }
            }
        }
    )

    assert payload == {
        "heyy_ai_key": "audiobook_voice_unmixr_remy_d4477bcd",
        "heyy_ai_name": "Remy",
    }


def test_build_report_blocks_whatsapp_share_followup_without_chat_ref(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-share-missing-chat-ref"
    job_dir.mkdir(parents=True)
    job = {
        "job_id": "job-share-missing-chat-ref",
        "status": "audiobookshelf_imported",
        "metadata": {"title": "Blocked Share Book", "author": "Writer", "language": "en-US"},
        "storage": {"job_dir": str(job_dir)},
        "audio_publication_gate": {"status": "pass", "issues": []},
        "whatsapp": {"sender_ref": "4368120864006", "session_ref": "session-1"},
        "audiobookshelf_import": {
            "status": "imported",
            "target_path": str(tmp_path / "Blocked Share Book.m4b"),
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://abs.example.com/share/blocked-share-book",
                "token_exposed": False,
                "raw_library_path_exposed": False,
            },
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {"messages": [], "ok": True}
        raise AssertionError("public share follow-up must not send without a pinned chat_ref")

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)

    report = module.build_report(
        _args(tmp_path, audiobook_followup_enabled=True),
        request_json=_fake_request_json,
    )

    assert report["status"] == "pass"
    assert report["share_link_sent"] == 0
    assert report["followup_summary"] == {
        "attempted": 0,
        "sent": 0,
        "errors": 0,
        "blocked": 1,
        "blocked_reasons": {"missing_chat_ref": 1},
    }
    assert all(row["method"] == "GET" for row in requests)
    updated = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    assert "public_share_delivery" not in dict(updated.get("whatsapp") or {})


def test_build_report_blocks_whatsapp_share_followup_for_session_mismatch(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-share-session-mismatch"
    job_dir.mkdir(parents=True)
    job = {
        "job_id": "job-share-session-mismatch",
        "status": "audiobookshelf_imported",
        "metadata": {"title": "Session Mismatch Book", "author": "Writer", "language": "en-US"},
        "storage": {"job_dir": str(job_dir)},
        "audio_publication_gate": {"status": "pass", "issues": []},
        "whatsapp": {"sender_ref": "4368120864006", "session_ref": "other-session", "chat_ref": "chat-ref-1"},
        "audiobookshelf_import": {
            "status": "imported",
            "target_path": str(tmp_path / "Session Mismatch Book.m4b"),
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://abs.example.com/share/session-mismatch-book",
                "token_exposed": False,
                "raw_library_path_exposed": False,
            },
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {"messages": [], "ok": True}
        raise AssertionError("public share follow-up must not send across mismatched sessions")

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)

    report = module.build_report(
        _args(tmp_path, audiobook_followup_enabled=True),
        request_json=_fake_request_json,
    )

    assert report["status"] == "pass"
    assert report["share_link_sent"] == 0
    assert report["followup_summary"] == {
        "attempted": 0,
        "sent": 0,
        "errors": 0,
        "blocked": 1,
        "blocked_reasons": {"session_ref_mismatch": 1},
    }
    assert all(row["method"] == "GET" for row in requests)


def test_build_report_skips_superseded_duplicate_whatsapp_share_followup(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-share-superseded"
    job_dir.mkdir(parents=True)
    job = {
        "job_id": "job-share-superseded",
        "status": "superseded_duplicate",
        "next_action": "none",
        "metadata": {"title": "Superseded Share Book", "author": "Writer", "language": "en-US"},
        "storage": {"job_dir": str(job_dir)},
        "audio_publication_gate": {"status": "pass", "issues": []},
        "whatsapp": {"sender_ref": "", "session_ref": "", "chat_ref": ""},
        "audiobookshelf_import": {
            "status": "imported",
            "target_path": str(tmp_path / "Superseded Share Book.m4b"),
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://abs.example.com/share/superseded-share-book",
                "token_exposed": False,
                "raw_library_path_exposed": False,
            },
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {"messages": [], "ok": True}
        raise AssertionError("superseded duplicate must not enter share follow-up delivery")

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)

    report = module.build_report(
        _args(tmp_path, audiobook_followup_enabled=True),
        request_json=_fake_request_json,
    )

    assert report["status"] == "pass"
    assert report["share_link_sent"] == 0
    assert report["followup_summary"] == {
        "attempted": 0,
        "sent": 0,
        "errors": 0,
        "blocked": 0,
        "blocked_reasons": {},
    }
    assert all(row["method"] == "GET" for row in requests)


def test_build_report_resends_whatsapp_voice_samples_from_status_text(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-replacement-choice"
    job_dir.mkdir(parents=True)
    sample_path = tmp_path / "replacement.mp3"
    sample_path.write_bytes(b"ID3replacement")
    job = {
        "job_id": "job-replacement-choice",
        "status": "waiting_voice_selection",
        "updated_at": "2026-06-21T05:00:00Z",
        "metadata": {"title": "Test Book", "source_filename": "book.epub"},
        "storage": {"job_dir": str(job_dir)},
        "whatsapp": {
            "sender_ref": "4368120864006",
            "session_ref": "session-1",
            "voice_sample_delivery": {"status": "sent", "sent_count": 1},
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
                        "callback_token": "replacement-token",
                        "sample_file": "replacement.mp3",
                        "sample_audio_ready": True,
                    }
                ],
            }
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job, indent=2, sort_keys=True), encoding="utf-8")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {"messages": [_text_message(body_text="why do i not get the voice samples?")], "ok": True}
        return {"ok": True, "message_id": f"wamid.out.{len(requests)}"}

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "audiobook_voice_audition_sample_messages",
        lambda _job: [
            {
                "token": "replacement-token",
                "label": "Piper German Thorsten high",
                "matched_tags": ["warm"],
                "audio_path": str(sample_path),
            }
        ],
    )
    monkeypatch.setattr(module.audiobook_epub_pipeline, "record_audiobook_voice_sample_delivery", lambda *, job, sample_receipts: job)

    report = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
    )

    assert report["status"] == "pass"
    assert report["status_candidate_count"] == 1
    assert report["status_processed"] == 1
    assert report["voice_sample_sent"] == 1
    media_post = [row for row in requests if row["method"] == "POST" and dict(row["body"]).get("media_base64")]
    button_post = [row for row in requests if row["method"] == "POST" and dict(row["body"]).get("buttons")]
    final_reply = [
        row
        for row in requests
        if row["method"] == "POST" and "I resent 1 audiobook voice sample." in str(dict(row["body"]).get("text") or "")
    ]
    assert len(media_post) == 1
    assert dict(media_post[0]["body"])["chat_ref"] == "chat-ref-1"
    assert len(button_post) == 1
    assert dict(button_post[0]["body"])["chat_ref"] == "chat-ref-1"
    assert len(final_reply) == 1
    assert dict(final_reply[0]["body"])["chat_ref"] == "chat-ref-1"
    assert "waiting for your explicit voice choice" in str(dict(final_reply[0]["body"])["text"])
    state = json.loads((tmp_path / "wa-actions.json").read_text(encoding="utf-8"))
    serialized_state = json.dumps(state)
    assert "4368120864006" not in serialized_state
    assert "replacement-token" not in serialized_state


def test_build_report_resends_whatsapp_voice_samples_for_matching_chat_ref(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"
    sample_path = tmp_path / "replacement.mp3"
    sample_path.write_bytes(b"ID3replacement")

    def _write_job(job_dir: Path, *, title: str, chat_ref: str, token: str) -> None:
        job_dir.mkdir(parents=True)
        (job_dir / "job.json").write_text(
            json.dumps(
                {
                    "job_id": job_dir.name,
                    "status": "waiting_voice_selection",
                    "updated_at": "2026-06-21T05:00:00Z",
                    "metadata": {"title": title, "source_filename": f"{title}.epub"},
                    "storage": {"job_dir": str(job_dir)},
                    "whatsapp": {
                        "sender_ref": "4368120864006",
                        "session_ref": "session-1",
                        "chat_ref": chat_ref,
                        "voice_sample_delivery": {"status": "sent", "sent_count": 1},
                    },
                    "provider": {
                        "voice_selection": {
                            "status": "waiting_user_choice",
                            "reason": "selected_voice_provider_balance_blocked",
                            "selected": {"label": "Seraphina"},
                            "pending_batch": [
                                {
                                    "label": f"{title} Voice",
                                    "preset_key": f"{job_dir.name}-preset",
                                    "callback_token": token,
                                    "sample_file": "replacement.mp3",
                                    "sample_audio_ready": True,
                                }
                            ],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

    _write_job(jobs_root / "job-a-correct", title="Correct Chat Book", chat_ref="chat-ref-1", token="correct-token")
    _write_job(jobs_root / "job-z-other", title="Other Chat Book", chat_ref="chat-ref-2", token="other-token")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {"messages": [_text_message(body_text="please resend the voice samples", chat_ref="chat-ref-1")], "ok": True}
        return {"ok": True, "message_id": f"wamid.out.{len(requests)}"}

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "audiobook_voice_audition_sample_messages",
        lambda _job: [
            {
                "token": str(dict(dict(_job.get("provider") or {}).get("voice_selection") or {}).get("pending_batch")[0]["callback_token"]),
                "label": str(dict(dict(_job.get("provider") or {}).get("voice_selection") or {}).get("pending_batch")[0]["label"]),
                "matched_tags": ["warm"],
                "audio_path": str(sample_path),
            }
        ],
    )
    monkeypatch.setattr(module.audiobook_epub_pipeline, "record_audiobook_voice_sample_delivery", lambda *, job, sample_receipts: job)

    report = module.build_report(_args(tmp_path), request_json=_fake_request_json)

    assert report["status"] == "pass"
    posts = [row for row in requests if row["method"] == "POST"]
    payload_text = "\n".join(str(dict(row["body"]).get("text") or "") for row in posts)
    assert "Correct Chat Book" in payload_text
    assert "Other Chat Book" not in payload_text
    button_posts = [row for row in posts if dict(row["body"]).get("buttons")]
    assert len(button_posts) == 1
    assert str(dict(button_posts[0]["body"])["buttons"][0][0][1]).startswith("ab|u|correct-token|")


def test_build_report_resends_whatsapp_playback_buttons_from_status_text(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-ready"
    job_dir.mkdir(parents=True)
    job = {
        "job_id": "job-ready",
        "status": "audiobookshelf_imported",
        "updated_at": "2026-06-21T05:30:00Z",
        "metadata": {"title": "Ready Book", "author": "A. Writer", "language": "en-US"},
        "storage": {"job_dir": str(job_dir)},
        "whatsapp": {"sender_ref": "4368120864006", "session_ref": "session-1"},
        "audio_publication_gate": {"status": "pass", "issues": []},
        "audiobookshelf_import": {
            "status": "imported",
            "target_path": str(tmp_path / "Ready Book.m4b"),
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://abs.example.com/share/ready-book",
                "whatsapp_delivery": {"status": "sent", "message_id": "wamid.share.1"},
                "playback_acceptance_callback": {
                    "status": "ready",
                    "token": "callback-token",
                    "raw_token_exposed": False,
                },
            },
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job, indent=2, sort_keys=True), encoding="utf-8")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {"messages": [_text_message(body_text="audiobook status")], "ok": True}
        return {"ok": True, "message_id": "wamid.status.reply"}

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "audiobook_runtime_preflight",
        lambda: {
            "provider": {"voice_catalog_count": 3, "voice_audition_min_candidates": 3, "api_key_slot_count": 1},
            "access": {"audiobookshelf_public_share_enabled": True},
            "failed_checks": [],
            "warned_checks": [],
        },
    )

    report = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
    )

    assert report["status"] == "pass"
    assert report["status_candidate_count"] == 1
    assert report["status_processed"] == 1
    posts = [row for row in requests if row["method"] == "POST"]
    assert len(posts) == 1
    payload = dict(posts[0]["body"])
    assert payload["chat_ref"] == "chat-ref-1"
    assert "Audiobook intake and voice samples are ready." in str(payload["text"])
    assert "reply with the voice name" in str(payload["text"])
    assert "'dismiss <voice>', or 'dismiss all'" in str(payload["text"])
    assert "Latest Audiobookshelf delivery awaiting perceptual attestation: Ready Book." in str(payload["text"])
    assert "Tapping attests every check" in str(payload["text"])
    assert payload["buttons"][0][0][0] == "Attest all 7 checks pass"
    assert payload["buttons"][0][1][0] == "Problem"
    accepted_parts = str(payload["buttons"][0][0][1]).split("|")
    problem_parts = str(payload["buttons"][0][1][1]).split("|")
    assert accepted_parts[:2] == ["ap2", "a"]
    assert problem_parts[:2] == ["ap2", "r"]
    assert accepted_parts[2] == problem_parts[2]
    assert len(accepted_parts[2]) == 32
    assert accepted_parts[2] != "callback-token"
    state = json.loads((tmp_path / "wa-actions.json").read_text(encoding="utf-8"))
    serialized_state = json.dumps(state)
    assert "4368120864006" not in serialized_state
    assert "callback-token" not in serialized_state


def test_build_report_resends_playback_buttons_for_matching_chat_ref(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"

    def _write_job(job_dir: Path, *, title: str, chat_ref: str, token: str) -> None:
        job_dir.mkdir(parents=True)
        (job_dir / "job.json").write_text(
            json.dumps(
                {
                    "job_id": job_dir.name,
                    "status": "audiobookshelf_imported",
                    "updated_at": "2026-06-21T05:30:00Z",
                    "metadata": {"title": title, "author": "A. Writer", "language": "en-US"},
                    "storage": {"job_dir": str(job_dir)},
                    "whatsapp": {
                        "sender_ref": "4368120864006",
                        "session_ref": "session-1",
                            "chat_ref": chat_ref,
                        },
                        "audio_publication_gate": {"status": "pass", "issues": []},
                        "audiobookshelf_import": {
                        "status": "imported",
                        "target_path": str(tmp_path / f"{title}.m4b"),
                        "public_share": {
                            "status": "public_share_ready",
                            "absolute_url": f"https://abs.example.com/share/{job_dir.name}",
                            "whatsapp_delivery": {"status": "sent", "message_id": f"wamid.share.{job_dir.name}"},
                            "playback_acceptance_callback": {
                                "status": "ready",
                                "token": token,
                                "raw_token_exposed": False,
                            },
                        },
                    },
                }
            ),
            encoding="utf-8",
        )

    _write_job(jobs_root / "job-a-correct", title="Correct Chat Book", chat_ref="chat-ref-1", token="correct-token")
    _write_job(jobs_root / "job-z-other", title="Other Chat Book", chat_ref="chat-ref-2", token="other-token")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {"messages": [_text_message(body_text="audiobook playback", chat_ref="chat-ref-1")], "ok": True}
        return {"ok": True, "message_id": "wamid.playback.reply"}

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "audiobook_runtime_preflight",
        lambda: {
            "provider": {"voice_catalog_count": 3, "voice_audition_min_candidates": 3, "api_key_slot_count": 1},
            "access": {"audiobookshelf_public_share_enabled": True},
            "failed_checks": [],
            "warned_checks": [],
        },
    )

    report = module.build_report(_args(tmp_path), request_json=_fake_request_json)

    assert report["status"] == "pass"
    payload = dict([row for row in requests if row["method"] == "POST"][0]["body"])
    assert "Correct Chat Book" in str(payload["text"])
    assert "Other Chat Book" not in str(payload["text"])
    accepted_parts = str(payload["buttons"][0][0][1]).split("|")
    assert accepted_parts[:2] == ["ap2", "a"]
    assert len(accepted_parts[2]) == 32
    assert accepted_parts[2] not in {"correct-token", "other-token"}


def test_whatsapp_audiobook_status_reply_prefers_matching_chat_ref(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    jobs_root = tmp_path / "jobs"

    def _write_job(job_dir: Path, *, title: str, chat_ref: str) -> None:
        job_dir.mkdir(parents=True)
        (job_dir / "job.json").write_text(
            json.dumps(
                {
                    "job_id": job_dir.name,
                    "status": "waiting_voice_selection",
                    "updated_at": "2026-06-21T05:00:00Z",
                    "metadata": {"title": title, "source_filename": f"{title}.epub"},
                    "storage": {"job_dir": str(job_dir)},
                    "whatsapp": {"sender_ref": "4368120864006", "session_ref": "session-1", "chat_ref": chat_ref},
                    "provider": {
                        "voice_selection": {
                            "status": "waiting_user_choice",
                            "reason": "selected_voice_provider_balance_blocked",
                            "selected": {"label": "Seraphina"},
                            "pending_batch": [{"label": f"{title} Voice"}],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

    _write_job(jobs_root / "job-a-correct", title="Correct Chat Book", chat_ref="chat-ref-1")
    _write_job(jobs_root / "job-z-other", title="Other Chat Book", chat_ref="chat-ref-2")

    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)

    reply = module._whatsapp_audiobook_runtime_status_reply_text(
        "audiobook status",
        sender_digits="4368120864006",
        chat_ref="chat-ref-1",
    )

    assert "Correct Chat Book" in reply
    assert "Other Chat Book" not in reply


def test_build_report_resends_whatsapp_playback_buttons_from_playback_text(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-ready"
    job_dir.mkdir(parents=True)
    job = {
        "job_id": "job-ready",
        "status": "audiobookshelf_imported",
        "updated_at": "2026-06-21T05:30:00Z",
        "metadata": {"title": "Ready Book", "author": "A. Writer", "language": "en-US"},
        "storage": {"job_dir": str(job_dir)},
        "whatsapp": {"sender_ref": "4368120864006", "session_ref": "session-1"},
        "audio_publication_gate": {"status": "pass", "issues": []},
        "audiobookshelf_import": {
            "status": "imported",
            "target_path": str(tmp_path / "Ready Book.m4b"),
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://abs.example.com/share/ready-book",
                "whatsapp_delivery": {"status": "sent", "message_id": "wamid.share.1"},
                "playback_acceptance_callback": {
                    "status": "ready",
                    "token": "callback-token",
                    "raw_token_exposed": False,
                },
            },
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job, indent=2, sort_keys=True), encoding="utf-8")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {"messages": [_text_message(body_text="audiobook playback")], "ok": True}
        return {"ok": True, "message_id": "wamid.playback.reply"}

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "audiobook_runtime_preflight",
        lambda: {
            "provider": {"voice_catalog_count": 3, "voice_audition_min_candidates": 3, "api_key_slot_count": 1},
            "access": {"audiobookshelf_public_share_enabled": True},
            "failed_checks": [],
            "warned_checks": [],
        },
    )

    report = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
    )

    assert report["status"] == "pass"
    assert report["status_candidate_count"] == 1
    assert report["status_processed"] == 1
    posts = [row for row in requests if row["method"] == "POST"]
    assert len(posts) == 1
    payload = dict(posts[0]["body"])
    assert payload["chat_ref"] == "chat-ref-1"
    assert "Latest Audiobookshelf delivery awaiting perceptual attestation: Ready Book." in str(payload["text"])
    assert "Tapping attests every check" in str(payload["text"])
    assert payload["buttons"][0][0][0] == "Attest all 7 checks pass"
    assert payload["buttons"][0][1][0] == "Problem"
    accepted_parts = str(payload["buttons"][0][0][1]).split("|")
    problem_parts = str(payload["buttons"][0][1][1]).split("|")
    assert accepted_parts[:2] == ["ap2", "a"]
    assert problem_parts[:2] == ["ap2", "r"]
    assert accepted_parts[2] == problem_parts[2]
    assert len(accepted_parts[2]) == 32
    state = json.loads((tmp_path / "wa-actions.json").read_text(encoding="utf-8"))
    serialized_state = json.dumps(state)
    assert "4368120864006" not in serialized_state
    assert "callback-token" not in serialized_state


def test_build_report_does_not_resend_playback_buttons_after_problem_recorded(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-ready"
    job_dir.mkdir(parents=True)
    job = {
        "job_id": "job-ready",
        "status": "audiobookshelf_imported",
        "updated_at": "2026-06-21T05:30:00Z",
        "metadata": {"title": "Ready Book", "author": "A. Writer", "language": "en-US"},
        "storage": {"job_dir": str(job_dir)},
        "whatsapp": {"sender_ref": "4368120864006", "session_ref": "session-1"},
        "audiobookshelf_import": {
            "status": "imported",
            "target_path": str(tmp_path / "Ready Book.m4b"),
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://abs.example.com/share/ready-book",
                "whatsapp_delivery": {"status": "sent", "message_id": "wamid.share.1"},
                "playback_acceptance_callback": {
                    "status": "ready",
                    "token": "callback-token",
                    "raw_token_exposed": False,
                },
            },
        },
        "playback_acceptance": {
            "status": "rejected",
            "accepted": False,
            "source": "whatsapp_button_recovered",
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job, indent=2, sort_keys=True), encoding="utf-8")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {"messages": [_text_message(body_text="audiobook playback")], "ok": True}
        return {"ok": True, "message_id": "wamid.playback.reply"}

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "audiobook_runtime_preflight",
        lambda: {
            "provider": {"voice_catalog_count": 3, "voice_audition_min_candidates": 3, "api_key_slot_count": 1},
            "access": {"audiobookshelf_public_share_enabled": True},
            "failed_checks": [],
            "warned_checks": [],
        },
    )

    report = module.build_report(
        _args(tmp_path),
        request_json=_fake_request_json,
    )

    assert report["status"] == "pass"
    posts = [row for row in requests if row["method"] == "POST"]
    assert len(posts) == 1
    payload = dict(posts[0]["body"])
    assert "Ready Book" in str(payload["text"])
    assert "playback problem" in str(payload["text"]).lower()
    assert "awaiting perceptual attestation" not in str(payload["text"])
    assert payload.get("buttons") in (None, [])


def test_build_report_resends_playback_buttons_when_delivery_progressed_to_delivered(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    requests: list[dict[str, object]] = []
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-ready"
    job_dir.mkdir(parents=True)
    job = {
        "job_id": "job-ready",
        "status": "audiobookshelf_imported",
        "updated_at": "2026-06-21T05:30:00Z",
        "metadata": {"title": "Ready Book", "author": "A. Writer", "language": "en-US"},
        "storage": {"job_dir": str(job_dir)},
        "whatsapp": {"sender_ref": "4368120864006", "session_ref": "session-1"},
        "audio_publication_gate": {"status": "pass", "issues": []},
        "audiobookshelf_import": {
            "status": "imported",
            "target_path": str(tmp_path / "Ready Book.m4b"),
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://abs.example.com/share/ready-book",
                "whatsapp_delivery": {"status": "delivered", "message_id": "wamid.share.1"},
                "playback_acceptance_callback": {
                    "status": "ready",
                    "token": "callback-token",
                    "raw_token_exposed": False,
                },
            },
        },
    }
    (job_dir / "job.json").write_text(json.dumps(job, indent=2, sort_keys=True), encoding="utf-8")

    def _fake_request_json(**kwargs: object) -> dict[str, object]:
        requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return {"messages": [_text_message(body_text="audiobook playback")], "ok": True}
        return {"ok": True, "message_id": "wamid.playback.reply"}

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "audiobook_runtime_preflight",
        lambda: {
            "provider": {"voice_catalog_count": 3, "voice_audition_min_candidates": 3, "api_key_slot_count": 1},
            "access": {"audiobookshelf_public_share_enabled": True},
            "failed_checks": [],
            "warned_checks": [],
        },
    )

    report = module.build_report(_args(tmp_path), request_json=_fake_request_json)

    assert report["status"] == "pass"
    payload = dict([row for row in requests if row["method"] == "POST"][0]["body"])
    assert "awaiting perceptual attestation: Ready Book." in str(payload["text"])
    assert "Tapping attests every check" in str(payload["text"])
    assert payload["buttons"][0][0][0] == "Attest all 7 checks pass"
    accepted_parts = str(payload["buttons"][0][0][1]).split("|")
    assert accepted_parts[:2] == ["ap2", "a"]
    assert len(accepted_parts[2]) == 32


def test_whatsapp_playback_problem_note_survives_delivered_status(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job-ready"
    job_dir.mkdir(parents=True)
    job = {
        "job_id": "job-ready",
        "status": "audiobookshelf_imported",
        "updated_at": "2026-06-21T05:30:00Z",
        "metadata": {"title": "Ready Book"},
        "storage": {"job_dir": str(job_dir)},
        "whatsapp": {"sender_ref": "4368120864006", "session_ref": "session-1", "chat_ref": "chat-ref-1"},
        "audiobookshelf_import": {
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://abs.example.com/share/ready-book",
                "whatsapp_delivery": {"status": "read", "message_id": "wamid.share.1"},
            }
        },
        "playback_acceptance": {"status": "rejected", "accepted": False, "source": "whatsapp_button_recovered"},
    }
    (job_dir / "job.json").write_text(json.dumps(job, indent=2, sort_keys=True), encoding="utf-8")

    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)

    note = module._latest_whatsapp_audiobook_playback_problem_note_for_sender(
        "4368120864006",
        chat_ref="chat-ref-1",
    )

    assert "Ready Book" in note
    assert "playback problem" in note.lower()


def test_whatsapp_playback_buttons_ignore_newer_superseded_duplicate(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    jobs_root = tmp_path / "jobs"
    active_dir = jobs_root / "job-ready-active"
    superseded_dir = jobs_root / "job-ready-superseded"
    active_dir.mkdir(parents=True)
    superseded_dir.mkdir(parents=True)
    active_job = {
        "job_id": "job-ready-active",
        "status": "audiobookshelf_imported",
        "updated_at": "2026-06-23T09:00:00Z",
        "metadata": {"title": "Active Book", "author": "A. Writer", "language": "en-US"},
            "storage": {"job_dir": str(active_dir)},
            "whatsapp": {"sender_ref": "4368120864006", "session_ref": "session-1", "chat_ref": "chat-ref-1"},
            "audio_publication_gate": {"status": "pass", "issues": []},
            "audiobookshelf_import": {
            "status": "imported",
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://abs.example.com/share/active-book",
                "whatsapp_delivery": {"status": "delivered", "message_id": "wamid.active.1"},
                "playback_acceptance_callback": {"status": "ready", "token": "active-token"},
            }
        },
        "playback_acceptance": {"status": "not_recorded", "accepted": False},
    }
    superseded_job = {
        "job_id": "job-ready-superseded",
        "status": "superseded_duplicate",
        "updated_at": "2026-06-23T09:10:00Z",
        "metadata": {"title": "Superseded Book", "author": "A. Writer", "language": "en-US"},
        "storage": {"job_dir": str(superseded_dir)},
        "whatsapp": {"sender_ref": "4368120864006", "session_ref": "session-1", "chat_ref": "chat-ref-1"},
        "audiobookshelf_import": {
            "status": "imported",
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://abs.example.com/share/superseded-book",
                "whatsapp_delivery": {"status": "read", "message_id": "wamid.superseded.1"},
                "playback_acceptance_callback": {"status": "ready", "token": "superseded-token"},
            }
        },
        "playback_acceptance": {"status": "not_recorded", "accepted": False},
    }
    (active_dir / "job.json").write_text(json.dumps(active_job, indent=2, sort_keys=True), encoding="utf-8")
    (superseded_dir / "job.json").write_text(json.dumps(superseded_job, indent=2, sort_keys=True), encoding="utf-8")

    monkeypatch.setenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)

    title, buttons = module._latest_whatsapp_audiobook_playback_buttons_for_sender(
        "4368120864006",
        chat_ref="chat-ref-1",
    )

    assert title == "Active Book"
    assert buttons
    accepted_parts = str(buttons[0][0][1]).split("|")
    assert accepted_parts[:2] == ["ap2", "a"]
    assert len(accepted_parts[2]) == 32
    assert accepted_parts[2] not in {"active-token", "superseded-token"}


def test_whatsapp_playback_problem_note_ignores_newer_superseded_duplicate(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    jobs_root = tmp_path / "jobs"
    active_dir = jobs_root / "job-problem-active"
    superseded_dir = jobs_root / "job-problem-superseded"
    active_dir.mkdir(parents=True)
    superseded_dir.mkdir(parents=True)
    active_job = {
        "job_id": "job-problem-active",
        "status": "audiobookshelf_imported",
        "updated_at": "2026-06-23T09:00:00Z",
        "metadata": {"title": "Problem Book"},
        "storage": {"job_dir": str(active_dir)},
        "whatsapp": {"sender_ref": "4368120864006", "session_ref": "session-1", "chat_ref": "chat-ref-1"},
        "audiobookshelf_import": {
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://abs.example.com/share/problem-book",
                "whatsapp_delivery": {"status": "read", "message_id": "wamid.problem.1"},
            }
        },
        "playback_acceptance": {"status": "rejected", "accepted": False, "source": "whatsapp_button"},
    }
    superseded_job = {
        "job_id": "job-problem-superseded",
        "status": "superseded_duplicate",
        "updated_at": "2026-06-23T09:10:00Z",
        "metadata": {"title": "Superseded Problem Book"},
        "storage": {"job_dir": str(superseded_dir)},
        "whatsapp": {"sender_ref": "4368120864006", "session_ref": "session-1", "chat_ref": "chat-ref-1"},
        "audiobookshelf_import": {
            "public_share": {
                "status": "public_share_ready",
                "absolute_url": "https://abs.example.com/share/superseded-problem-book",
                "whatsapp_delivery": {"status": "read", "message_id": "wamid.superseded.problem.1"},
            }
        },
        "playback_acceptance": {"status": "rejected", "accepted": False, "source": "whatsapp_button"},
    }
    (active_dir / "job.json").write_text(json.dumps(active_job, indent=2, sort_keys=True), encoding="utf-8")
    (superseded_dir / "job.json").write_text(json.dumps(superseded_job, indent=2, sort_keys=True), encoding="utf-8")

    monkeypatch.setenv("EA_AUDIOBOOK_JOBS_ROOT", str(jobs_root))
    monkeypatch.setattr(module.audiobook_epub_pipeline, "audiobook_jobs_root", lambda: jobs_root)

    note = module._latest_whatsapp_audiobook_playback_problem_note_for_sender(
        "4368120864006",
        chat_ref="chat-ref-1",
    )

    assert "Problem Book" in note
    assert "Superseded Problem Book" not in note
    assert "playback problem" in note.lower()


def test_whatsapp_audiobook_runtime_status_ignores_optional_player_scope_warnings(tmp_path: Path, monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(
        module.audiobook_epub_pipeline,
        "audiobook_runtime_preflight",
        lambda: {
            "provider": {
                "voice_catalog_count": 3,
                "voice_audition_min_candidates": 3,
                "api_key_slot_count": 1,
            },
            "access": {"audiobookshelf_public_share_enabled": True},
            "failed_checks": [],
            "warned_checks": [
                "player_access_signing_secret_present",
                "player_access_base_url_present",
            ],
        },
    )
    monkeypatch.setattr(module, "_latest_active_whatsapp_audiobook_job", lambda _sender_digits: {})
    monkeypatch.setattr(module, "_latest_active_whatsapp_audiobook_job_for_chat_ref", lambda _chat_ref: {})
    monkeypatch.setattr(module, "_latest_active_whatsapp_audiobook_job_for_sender", lambda **_kwargs: {})
    monkeypatch.setattr(module, "_latest_whatsapp_audiobook_playback_problem_note_for_sender", lambda *_args, **_kwargs: "")

    reply = module._whatsapp_audiobook_runtime_status_reply_text(
        "audiobook status",
        sender_digits="4368120864006",
        chat_ref="chat-ref-1",
    )

    assert "Audiobook intake and voice samples are ready." in reply
    assert "full delivery is not complete-ready yet" not in reply
    assert "player-scoped playback base URL is not configured" not in reply
