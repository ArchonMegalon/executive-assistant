from __future__ import annotations

import json

from app.repositories.connector_bindings import InMemoryConnectorBindingRepository
from app.repositories.tool_registry import InMemoryToolRegistryRepository
from app.services.telegram_delivery import (
    _chunk_telegram_text,
    resolve_primary_telegram_binding,
    send_telegram_audio_for_principal,
    send_telegram_document_for_principal,
    send_telegram_message_for_principal,
    send_telegram_video_for_principal,
)
from app.services.tool_runtime import ToolRuntimeService


def _tool_runtime() -> ToolRuntimeService:
    return ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )


def test_chunk_telegram_text_splits_long_messages() -> None:
    text = ("alpha " * 900).strip()
    chunks = _chunk_telegram_text(text)
    assert len(chunks) >= 2
    assert all(len(chunk) <= 4000 for chunk in chunks)


def test_send_telegram_message_for_principal_uses_bound_chat(monkeypatch) -> None:
    runtime = _tool_runtime()
    runtime.upsert_connector_binding(
        principal_id="exec-telegram-send",
        connector_name="telegram_identity",
        external_account_ref="42",
        auth_metadata_json={"default_chat_ref": "42", "bot_key": "default", "bot_handle": "tibor_concierge_bot"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    monkeypatch.setenv(
        "EA_TELEGRAM_BOT_REGISTRY_JSON",
        json.dumps({"default": {"token": "telegram-token", "handle": "tibor_concierge_bot"}}),
    )

    sent: list[dict[str, object]] = []

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"ok": True, "result": {"message_id": 7}}).encode("utf-8")

    def _fake_urlopen(request, timeout=30):
        sent.append(
            {
                "url": request.full_url,
                "payload": json.loads(request.data.decode("utf-8")),
                "timeout": timeout,
            }
        )
        return _FakeResponse()

    monkeypatch.setattr("app.services.telegram_delivery.urllib.request.urlopen", _fake_urlopen)
    receipt = send_telegram_message_for_principal(runtime, principal_id="exec-telegram-send", text="Hello from EA")
    assert receipt.chat_id == "42"
    assert receipt.bot_key == "default"
    assert receipt.message_ids == ("7",)
    assert sent and sent[0]["payload"]["chat_id"] == "42"
    assert sent[0]["payload"]["text"] == "Hello from EA"


def test_send_telegram_message_for_principal_includes_inline_buttons(monkeypatch) -> None:
    runtime = _tool_runtime()
    runtime.upsert_connector_binding(
        principal_id="exec-telegram-buttons",
        connector_name="telegram_identity",
        external_account_ref="42",
        auth_metadata_json={"default_chat_ref": "42", "bot_key": "default", "bot_handle": "tibor_concierge_bot"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    monkeypatch.setenv(
        "EA_TELEGRAM_BOT_REGISTRY_JSON",
        json.dumps({"default": {"token": "telegram-token", "handle": "tibor_concierge_bot"}}),
    )

    sent: list[dict[str, object]] = []

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"ok": True, "result": {"message_id": 8}}).encode("utf-8")

    def _fake_urlopen(request, timeout=30):
        sent.append(json.loads(request.data.decode("utf-8")))
        return _FakeResponse()

    monkeypatch.setattr("app.services.telegram_delivery.urllib.request.urlopen", _fake_urlopen)
    send_telegram_message_for_principal(
        runtime,
        principal_id="exec-telegram-buttons",
        text="Choose one",
        inline_buttons=[[("More like this", "fb|n1|more|42|9999999999|sig")]],
    )
    assert sent
    assert sent[0]["reply_markup"]["inline_keyboard"][0][0]["text"] == "More like this"


def test_resolve_primary_telegram_binding_falls_back_to_default_principal(monkeypatch) -> None:
    runtime = _tool_runtime()
    runtime.upsert_connector_binding(
        principal_id="local-user",
        connector_name="telegram_identity",
        external_account_ref="1354554303",
        auth_metadata_json={"default_chat_ref": "1354554303", "bot_key": "default"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    monkeypatch.setenv("EA_DEFAULT_PRINCIPAL_ID", "local-user")

    binding = resolve_primary_telegram_binding(runtime, principal_id="cf-email:tibor.girschele@gmail.com")
    assert binding is not None
    assert str(binding.external_account_ref) == "1354554303"


def test_send_telegram_message_for_principal_falls_back_to_default_principal_binding(monkeypatch) -> None:
    runtime = _tool_runtime()
    runtime.upsert_connector_binding(
        principal_id="local-user",
        connector_name="telegram_identity",
        external_account_ref="1354554303",
        auth_metadata_json={"default_chat_ref": "1354554303", "bot_key": "default", "bot_handle": "tibor_concierge_bot"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    monkeypatch.setenv("EA_DEFAULT_PRINCIPAL_ID", "local-user")
    monkeypatch.setenv(
        "EA_TELEGRAM_BOT_REGISTRY_JSON",
        json.dumps({"default": {"token": "telegram-token", "handle": "tibor_concierge_bot"}}),
    )

    sent: list[dict[str, object]] = []

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"ok": True, "result": {"message_id": 17}}).encode("utf-8")

    def _fake_urlopen(request, timeout=30):
        sent.append(
            {
                "url": request.full_url,
                "payload": json.loads(request.data.decode("utf-8")),
                "timeout": timeout,
            }
        )
        return _FakeResponse()

    monkeypatch.setattr("app.services.telegram_delivery.urllib.request.urlopen", _fake_urlopen)
    receipt = send_telegram_message_for_principal(
        runtime,
        principal_id="cf-email:tibor.girschele@gmail.com",
        text="Fallback from local-user binding",
    )
    assert receipt.chat_id == "1354554303"
    assert receipt.message_ids == ("17",)
    assert sent and sent[0]["payload"]["chat_id"] == "1354554303"


def test_send_telegram_video_for_principal_uses_bound_chat_and_sendvideo(monkeypatch) -> None:
    runtime = _tool_runtime()
    runtime.upsert_connector_binding(
        principal_id="exec-telegram-video",
        connector_name="telegram_identity",
        external_account_ref="42",
        auth_metadata_json={"default_chat_ref": "42", "bot_key": "default", "bot_handle": "tibor_concierge_bot"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    monkeypatch.setenv(
        "EA_TELEGRAM_BOT_REGISTRY_JSON",
        json.dumps({"default": {"token": "telegram-token", "handle": "tibor_concierge_bot"}}),
    )
    monkeypatch.setattr("app.services.telegram_delivery._telegram_video_has_audio", lambda value: value.endswith(".mp4"))
    monkeypatch.setattr("app.services.telegram_delivery._telegram_remote_ref_reachable", lambda value: True)

    sent: list[dict[str, object]] = []

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"ok": True, "result": {"message_id": 9}}).encode("utf-8")

    def _fake_urlopen(request, timeout=30):
        sent.append(
            {
                "url": request.full_url,
                "payload": json.loads(request.data.decode("utf-8")),
                "timeout": timeout,
            }
        )
        return _FakeResponse()

    monkeypatch.setattr("app.services.telegram_delivery.urllib.request.urlopen", _fake_urlopen)
    receipt = send_telegram_video_for_principal(
        runtime,
        principal_id="exec-telegram-video",
        video_ref="https://cdn.example/render/final.mp4",
        caption="Brigittenau teaser",
    )
    assert receipt.chat_id == "42"
    assert receipt.message_ids == ("9",)
    assert sent and sent[0]["url"] == "https://api.telegram.org/bottelegram-token/sendVideo"
    assert sent[0]["payload"]["video"] == "https://cdn.example/render/final.mp4"
    assert sent[0]["payload"]["caption"] == "Brigittenau teaser"


def test_send_telegram_video_for_principal_uploads_local_file(monkeypatch, tmp_path) -> None:
    runtime = _tool_runtime()
    runtime.upsert_connector_binding(
        principal_id="exec-telegram-video-local",
        connector_name="telegram_identity",
        external_account_ref="42",
        auth_metadata_json={"default_chat_ref": "42", "bot_key": "default", "bot_handle": "tibor_concierge_bot"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    monkeypatch.setenv(
        "EA_TELEGRAM_BOT_REGISTRY_JSON",
        json.dumps({"default": {"token": "telegram-token", "handle": "tibor_concierge_bot"}}),
    )
    video_path = tmp_path / "render.mp4"
    video_path.write_bytes(b"fake-video-bytes")
    monkeypatch.setattr("app.services.telegram_delivery._telegram_video_has_audio", lambda value: value.endswith(".mp4"))

    seen: dict[str, object] = {}

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"ok": True, "result": {"message_id": 11}}).encode("utf-8")

    def _fake_urlopen(request, timeout=30):
        seen["url"] = request.full_url
        seen["content_type"] = request.headers.get("Content-type") or request.headers.get("Content-Type")
        seen["body"] = request.data
        seen["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr("app.services.telegram_delivery.urllib.request.urlopen", _fake_urlopen)
    receipt = send_telegram_video_for_principal(
        runtime,
        principal_id="exec-telegram-video-local",
        video_ref=str(video_path),
        caption="Local upload",
    )
    assert receipt.chat_id == "42"
    assert receipt.message_ids == ("11",)
    assert seen["url"] == "https://api.telegram.org/bottelegram-token/sendVideo"
    assert "multipart/form-data" in str(seen["content_type"])
    assert b'filename="render.mp4"' in bytes(seen["body"])
    assert b"Local upload" in bytes(seen["body"])


def test_send_telegram_video_for_principal_falls_back_to_document_for_silent_local_file(monkeypatch, tmp_path) -> None:
    runtime = _tool_runtime()
    runtime.upsert_connector_binding(
        principal_id="exec-telegram-video-silent",
        connector_name="telegram_identity",
        external_account_ref="42",
        auth_metadata_json={"default_chat_ref": "42", "bot_key": "default", "bot_handle": "tibor_concierge_bot"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    monkeypatch.setenv(
        "EA_TELEGRAM_BOT_REGISTRY_JSON",
        json.dumps({"default": {"token": "telegram-token", "handle": "tibor_concierge_bot"}}),
    )
    video_path = tmp_path / "silent.mp4"
    video_path.write_bytes(b"fake-video-bytes")
    monkeypatch.setattr("app.services.telegram_delivery._telegram_video_has_audio", lambda value: False)

    seen: dict[str, object] = {}

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"ok": True, "result": {"message_id": 12}}).encode("utf-8")

    def _fake_urlopen(request, timeout=30):
        seen["url"] = request.full_url
        seen["body"] = request.data
        return _FakeResponse()

    monkeypatch.setattr("app.services.telegram_delivery.urllib.request.urlopen", _fake_urlopen)
    receipt = send_telegram_video_for_principal(
        runtime,
        principal_id="exec-telegram-video-silent",
        video_ref=str(video_path),
        caption="Silent local upload",
    )
    assert receipt.message_ids == ("12",)
    assert seen["url"] == "https://api.telegram.org/bottelegram-token/sendDocument"
    assert b'name="document"' in bytes(seen["body"])


def test_send_telegram_video_for_principal_rejects_video_without_audio(monkeypatch) -> None:
    runtime = _tool_runtime()
    runtime.upsert_connector_binding(
        principal_id="exec-telegram-video-fail",
        connector_name="telegram_identity",
        external_account_ref="42",
        auth_metadata_json={"default_chat_ref": "42", "bot_key": "default"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    monkeypatch.setenv(
        "EA_TELEGRAM_BOT_REGISTRY_JSON",
        json.dumps({"default": {"token": "telegram-token"}}),
    )
    monkeypatch.setattr("app.services.telegram_delivery._telegram_video_has_audio", lambda value: False)

    try:
        send_telegram_video_for_principal(
            runtime,
            principal_id="exec-telegram-video-fail",
            video_ref="https://cdn.example/render/silent.mp4",
        )
    except RuntimeError as exc:
        assert str(exc) == "telegram_video_audio_missing"
    else:
        raise AssertionError("expected telegram_video_audio_missing")


def test_send_telegram_audio_for_principal_uploads_local_file(monkeypatch, tmp_path) -> None:
    runtime = _tool_runtime()
    runtime.upsert_connector_binding(
        principal_id="exec-telegram-audio-local",
        connector_name="telegram_identity",
        external_account_ref="42",
        auth_metadata_json={"default_chat_ref": "42", "bot_key": "default", "bot_handle": "tibor_concierge_bot"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    monkeypatch.setenv(
        "EA_TELEGRAM_BOT_REGISTRY_JSON",
        json.dumps({"default": {"token": "telegram-token", "handle": "tibor_concierge_bot"}}),
    )
    audio_path = tmp_path / "meeting.mp3"
    audio_path.write_bytes(b"fake-audio-bytes")
    seen: dict[str, object] = {}

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"ok": True, "result": {"message_id": 13}}).encode("utf-8")

    def _fake_urlopen(request, timeout=30):
        seen["url"] = request.full_url
        seen["content_type"] = request.headers.get("Content-type") or request.headers.get("Content-Type")
        seen["body"] = request.data
        return _FakeResponse()

    monkeypatch.setattr("app.services.telegram_delivery.urllib.request.urlopen", _fake_urlopen)
    receipt = send_telegram_audio_for_principal(
        runtime,
        principal_id="exec-telegram-audio-local",
        audio_ref=str(audio_path),
        caption="Meeting audio",
    )
    assert receipt.message_ids == ("13",)
    assert seen["url"] == "https://api.telegram.org/bottelegram-token/sendAudio"
    assert "multipart/form-data" in str(seen["content_type"])
    assert b'filename="meeting.mp3"' in bytes(seen["body"])
    assert b"Content-Type: audio/mpeg" in bytes(seen["body"])
    assert b"Meeting audio" in bytes(seen["body"])


def test_send_telegram_document_for_principal_uses_bound_chat(monkeypatch) -> None:
    runtime = _tool_runtime()
    runtime.upsert_connector_binding(
        principal_id="exec-telegram-document",
        connector_name="telegram_identity",
        external_account_ref="42",
        auth_metadata_json={"default_chat_ref": "42", "bot_key": "default", "bot_handle": "tibor_concierge_bot"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    monkeypatch.setenv(
        "EA_TELEGRAM_BOT_REGISTRY_JSON",
        json.dumps({"default": {"token": "telegram-token", "handle": "tibor_concierge_bot"}}),
    )
    monkeypatch.setattr("app.services.telegram_delivery._telegram_remote_ref_reachable", lambda value: True)
    sent: list[dict[str, object]] = []

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"ok": True, "result": {"message_id": 14}}).encode("utf-8")

    def _fake_urlopen(request, timeout=30):
        sent.append(
            {
                "url": request.full_url,
                "payload": json.loads(request.data.decode("utf-8")),
                "timeout": timeout,
            }
        )
        return _FakeResponse()

    monkeypatch.setattr("app.services.telegram_delivery.urllib.request.urlopen", _fake_urlopen)
    receipt = send_telegram_document_for_principal(
        runtime,
        principal_id="exec-telegram-document",
        document_ref="https://cdn.example/documents/report.pdf",
        caption="Hospital report",
    )
    assert receipt.chat_id == "42"
    assert receipt.message_ids == ("14",)
    assert sent and sent[0]["url"] == "https://api.telegram.org/bottelegram-token/sendDocument"
    assert sent[0]["payload"]["document"] == "https://cdn.example/documents/report.pdf"
    assert sent[0]["payload"]["caption"] == "Hospital report"


def test_send_telegram_message_retries_transient_failure(monkeypatch) -> None:
    runtime = _tool_runtime()
    runtime.upsert_connector_binding(
        principal_id="exec-telegram-retry",
        connector_name="telegram_identity",
        external_account_ref="42",
        auth_metadata_json={"default_chat_ref": "42", "bot_key": "default"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    monkeypatch.setenv("EA_TELEGRAM_BOT_REGISTRY_JSON", json.dumps({"default": {"token": "telegram-token"}}))
    monkeypatch.setenv("EA_TELEGRAM_DELIVERY_MAX_ATTEMPTS", "2")
    monkeypatch.setattr("app.services.telegram_delivery.time.sleep", lambda *_args, **_kwargs: None)
    attempts = {"count": 0}

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"ok": True, "result": {"message_id": 15}}).encode("utf-8")

    def _fake_urlopen(request, timeout=30):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("temporary")
        return _FakeResponse()

    monkeypatch.setattr("app.services.telegram_delivery.urllib.request.urlopen", _fake_urlopen)
    receipt = send_telegram_message_for_principal(runtime, principal_id="exec-telegram-retry", text="Retry me")
    assert receipt.message_ids == ("15",)
    assert attempts["count"] == 2


def test_send_telegram_audio_rejects_unreachable_remote_ref(monkeypatch) -> None:
    runtime = _tool_runtime()
    runtime.upsert_connector_binding(
        principal_id="exec-telegram-audio-unreachable",
        connector_name="telegram_identity",
        external_account_ref="42",
        auth_metadata_json={"default_chat_ref": "42", "bot_key": "default"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    monkeypatch.setenv("EA_TELEGRAM_BOT_REGISTRY_JSON", json.dumps({"default": {"token": "telegram-token"}}))
    monkeypatch.setattr("app.services.telegram_delivery._telegram_remote_ref_reachable", lambda value: False)

    try:
        send_telegram_audio_for_principal(
            runtime,
            principal_id="exec-telegram-audio-unreachable",
            audio_ref="https://cdn.example.com/missing.mp3",
        )
    except RuntimeError as exc:
        assert str(exc) == "telegram_audio_unreachable"
    else:
        raise AssertionError("expected telegram_audio_unreachable")


def test_send_telegram_document_rejects_oversized_local_upload(monkeypatch, tmp_path) -> None:
    runtime = _tool_runtime()
    runtime.upsert_connector_binding(
        principal_id="exec-telegram-document-large",
        connector_name="telegram_identity",
        external_account_ref="42",
        auth_metadata_json={"default_chat_ref": "42", "bot_key": "default"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    monkeypatch.setenv("EA_TELEGRAM_BOT_REGISTRY_JSON", json.dumps({"default": {"token": "telegram-token"}}))
    monkeypatch.setenv("EA_TELEGRAM_UPLOAD_MAX_BYTES", "4")
    document_path = tmp_path / "report.pdf"
    document_path.write_bytes(b"12345")

    try:
        send_telegram_document_for_principal(
            runtime,
            principal_id="exec-telegram-document-large",
            document_ref=str(document_path),
        )
    except RuntimeError as exc:
        assert str(exc) == "telegram_upload_too_large"
    else:
        raise AssertionError("expected telegram_upload_too_large")
