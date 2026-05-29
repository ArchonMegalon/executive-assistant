from __future__ import annotations

import json

from app.repositories.connector_bindings import InMemoryConnectorBindingRepository
from app.repositories.tool_registry import InMemoryToolRegistryRepository
from app.services.telegram_delivery import _chunk_telegram_text, send_telegram_message_for_principal, send_telegram_video_for_principal
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
