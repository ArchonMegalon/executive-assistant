from __future__ import annotations

import io
import json
from urllib.error import HTTPError

from app.repositories.connector_bindings import InMemoryConnectorBindingRepository
from app.repositories.tool_registry import InMemoryToolRegistryRepository
from app.services.telegram_delivery import (
    _chunk_telegram_text,
    _telegram_video_with_fallback_audio,
    resolve_primary_telegram_binding,
    send_telegram_chat_action_for_principal,
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
        auth_metadata_json={"default_chat_ref": "42", "bot_key": "default", "bot_handle": "ea_concierge_bot"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    monkeypatch.setenv(
        "EA_TELEGRAM_BOT_REGISTRY_JSON",
        json.dumps({"default": {"token": "telegram-token", "handle": "ea_concierge_bot"}}),
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
    assert "disable_web_page_preview" not in sent[0]["payload"]


def test_send_telegram_chat_action_accepts_boolean_result(monkeypatch) -> None:
    runtime = _tool_runtime()
    runtime.upsert_connector_binding(
        principal_id="exec-telegram-action",
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
    sent: list[dict[str, object]] = []

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"ok": True, "result": True}).encode("utf-8")

    def _fake_urlopen(request, timeout=30):
        sent.append(json.loads(request.data.decode("utf-8")))
        return _FakeResponse()

    monkeypatch.setattr("app.services.telegram_delivery.urllib.request.urlopen", _fake_urlopen)
    receipt = send_telegram_chat_action_for_principal(
        runtime,
        principal_id="exec-telegram-action",
        action="upload_video",
    )

    assert receipt.message_ids == ()
    assert sent == [{"chat_id": "42", "action": "upload_video"}]


def test_send_telegram_message_for_principal_can_disable_web_page_preview(monkeypatch) -> None:
    runtime = _tool_runtime()
    runtime.upsert_connector_binding(
        principal_id="exec-telegram-link",
        connector_name="telegram_identity",
        external_account_ref="42",
        auth_metadata_json={"default_chat_ref": "42", "bot_key": "default", "bot_handle": "ea_concierge_bot"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    monkeypatch.setenv(
        "EA_TELEGRAM_BOT_REGISTRY_JSON",
        json.dumps({"default": {"token": "telegram-token", "handle": "ea_concierge_bot"}}),
    )

    sent: list[dict[str, object]] = []

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"ok": True, "result": {"message_id": 77}}).encode("utf-8")

    def _fake_urlopen(request, timeout=30):
        sent.append(json.loads(request.data.decode("utf-8")))
        return _FakeResponse()

    monkeypatch.setattr("app.services.telegram_delivery.urllib.request.urlopen", _fake_urlopen)
    receipt = send_telegram_message_for_principal(
        runtime,
        principal_id="exec-telegram-link",
        text="Open https://console.cloud.google.com/auth/audience?project=propertyquarry-498318",
        disable_web_page_preview=True,
    )

    assert receipt.message_ids == ("77",)
    assert sent
    assert sent[0]["disable_web_page_preview"] is True


def test_send_telegram_message_for_principal_includes_inline_buttons(monkeypatch) -> None:
    runtime = _tool_runtime()
    runtime.upsert_connector_binding(
        principal_id="exec-telegram-buttons",
        connector_name="telegram_identity",
        external_account_ref="42",
        auth_metadata_json={"default_chat_ref": "42", "bot_key": "default", "bot_handle": "ea_concierge_bot"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    monkeypatch.setenv(
        "EA_TELEGRAM_BOT_REGISTRY_JSON",
        json.dumps({"default": {"token": "telegram-token", "handle": "ea_concierge_bot"}}),
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
        principal_id="principal-default",
        connector_name="telegram_identity",
        external_account_ref="1354554303",
        auth_metadata_json={"default_chat_ref": "1354554303", "bot_key": "default"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    monkeypatch.setenv("EA_DEFAULT_PRINCIPAL_ID", "principal-default")

    binding = resolve_primary_telegram_binding(runtime, principal_id="cf-email:principal@example.test")
    assert binding is not None
    assert str(binding.external_account_ref) == "1354554303"


def test_send_telegram_message_for_principal_falls_back_to_default_principal_binding(monkeypatch) -> None:
    runtime = _tool_runtime()
    runtime.upsert_connector_binding(
        principal_id="principal-default",
        connector_name="telegram_identity",
        external_account_ref="1354554303",
        auth_metadata_json={"default_chat_ref": "1354554303", "bot_key": "default", "bot_handle": "ea_concierge_bot"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    monkeypatch.setenv("EA_DEFAULT_PRINCIPAL_ID", "principal-default")
    monkeypatch.setenv(
        "EA_TELEGRAM_BOT_REGISTRY_JSON",
        json.dumps({"default": {"token": "telegram-token", "handle": "ea_concierge_bot"}}),
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
        principal_id="cf-email:principal@example.test",
        text="Fallback from principal-default binding",
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
        auth_metadata_json={"default_chat_ref": "42", "bot_key": "default", "bot_handle": "ea_concierge_bot"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    monkeypatch.setenv(
        "EA_TELEGRAM_BOT_REGISTRY_JSON",
        json.dumps({"default": {"token": "telegram-token", "handle": "ea_concierge_bot"}}),
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
        auth_metadata_json={"default_chat_ref": "42", "bot_key": "default", "bot_handle": "ea_concierge_bot"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    monkeypatch.setenv(
        "EA_TELEGRAM_BOT_REGISTRY_JSON",
        json.dumps({"default": {"token": "telegram-token", "handle": "ea_concierge_bot"}}),
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


def test_send_telegram_video_for_principal_normalizes_silent_local_file_to_sendvideo(monkeypatch, tmp_path) -> None:
    runtime = _tool_runtime()
    runtime.upsert_connector_binding(
        principal_id="exec-telegram-video-silent",
        connector_name="telegram_identity",
        external_account_ref="42",
        auth_metadata_json={"default_chat_ref": "42", "bot_key": "default", "bot_handle": "ea_concierge_bot"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    monkeypatch.setenv(
        "EA_TELEGRAM_BOT_REGISTRY_JSON",
        json.dumps({"default": {"token": "telegram-token", "handle": "ea_concierge_bot"}}),
    )
    video_path = tmp_path / "silent.mp4"
    video_path.write_bytes(b"fake-video-bytes")
    fixed_silent_with_audio = tmp_path / "silent.with-audio.mp4"
    fixed_silent_with_audio.write_bytes(b"fake-video-with-audio-bytes")
    monkeypatch.setattr(
        "app.services.telegram_delivery._telegram_video_has_audio",
        lambda value: str(value).endswith(".with-audio.mp4"),
    )
    monkeypatch.setattr(
        "app.services.telegram_delivery._telegram_video_with_fallback_audio",
        lambda value, audio_ref="", fallback_audio_text="", fallback_audio_language="": (
            str(fixed_silent_with_audio),
            fixed_silent_with_audio,
        ),
    )

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
    assert seen["url"] == "https://api.telegram.org/bottelegram-token/sendVideo"
    assert b'name="video"' in bytes(seen["body"])


def test_send_telegram_video_for_principal_rejects_local_file_when_audio_normalization_still_has_no_audio(
    monkeypatch,
    tmp_path,
) -> None:
    runtime = _tool_runtime()
    runtime.upsert_connector_binding(
        principal_id="exec-telegram-video-local-audio-fail",
        connector_name="telegram_identity",
        external_account_ref="42",
        auth_metadata_json={"default_chat_ref": "42", "bot_key": "default"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    monkeypatch.setenv("EA_TELEGRAM_BOT_REGISTRY_JSON", json.dumps({"default": {"token": "telegram-token"}}))
    video_path = tmp_path / "silent.mp4"
    video_path.write_bytes(b"fake-video-bytes")
    normalized_path = tmp_path / "silent.with-audio.mp4"
    normalized_path.write_bytes(b"fake-video-still-without-audio")
    monkeypatch.setattr("app.services.telegram_delivery._telegram_video_has_audio", lambda value: False)
    monkeypatch.setattr(
        "app.services.telegram_delivery._telegram_video_with_fallback_audio",
        lambda value, audio_ref="", fallback_audio_text="", fallback_audio_language="": (
            str(normalized_path),
            normalized_path,
        ),
    )

    try:
        send_telegram_video_for_principal(
            runtime,
            principal_id="exec-telegram-video-local-audio-fail",
            video_ref=str(video_path),
            caption="Silent local upload",
        )
    except RuntimeError as exc:
        assert str(exc) == "telegram_video_audio_missing"
    else:
        raise AssertionError("expected telegram_video_audio_missing")


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
    def _fallback_raise(
        video_ref: str,
        audio_ref: str = "",
        fallback_audio_text: str = "",
        fallback_audio_language: str = "",
    ) -> tuple[str, object]:
        raise RuntimeError("telegram_video_add_audio_failed")

    monkeypatch.setattr("app.services.telegram_delivery._telegram_video_with_fallback_audio", _fallback_raise)

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


def test_send_telegram_video_for_principal_fits_audio_probe_for_silent_local_video(monkeypatch, tmp_path) -> None:
    runtime = _tool_runtime()
    runtime.upsert_connector_binding(
        principal_id="exec-telegram-video-probe",
        connector_name="telegram_identity",
        external_account_ref="42",
        auth_metadata_json={"default_chat_ref": "42", "bot_key": "default", "bot_handle": "ea_concierge_bot"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    monkeypatch.setenv(
        "EA_TELEGRAM_BOT_REGISTRY_JSON",
        json.dumps({"default": {"token": "telegram-token", "handle": "ea_concierge_bot"}}),
    )
    video_path = tmp_path / "silent-with-probe.webm"
    video_path.write_bytes(b"fake-video-bytes")
    audio_probe = tmp_path / "speech-track.wav"
    audio_probe.write_bytes(b"fake-audio-bytes")
    normalised = []

    def _fake_video_has_audio(value: str) -> bool:
        normalized = str(value or "").strip()
        if normalized.endswith(".with-audio.webm"):
            return True
        if normalized.endswith(".webm"):
            return False
        if normalized.endswith(".wav"):
            return True
        return False

    monkeypatch.setattr("app.services.telegram_delivery._telegram_video_has_audio", _fake_video_has_audio)
    monkeypatch.setattr(
        "app.services.telegram_delivery._telegram_video_with_fallback_audio",
        lambda video_ref, audio_ref="", fallback_audio_text="", fallback_audio_language="": (
            normalised.append((str(video_ref), str(audio_ref), str(fallback_audio_text)))
            or (
                str(video_path.with_name("silent-with-probe.with-audio.webm")),
                video_path.with_name("silent-with-probe.with-audio.webm"),
            )
        ),
    )

    sent: list[dict[str, object]] = []

    def _fake_send_multipart(*, token, method, fields, file_field, file_path, content_type="application/octet-stream", timeout=120):  # noqa: ANN001
        sent.append(
            {
                "token": token,
                "method": method,
                "fields": dict(fields),
                "file_field": file_field,
                "file_path": file_path,
                "content_type": content_type,
                "timeout": timeout,
            }
        )
        return {"message_id": 13}

    monkeypatch.setattr("app.services.telegram_delivery._telegram_send_multipart", _fake_send_multipart)
    normalized_video = video_path.with_name("silent-with-probe.with-audio.webm")
    normalized_video.write_bytes(b"fake-video-with-audio")

    receipt = send_telegram_video_for_principal(
        runtime,
        principal_id="exec-telegram-video-probe",
        video_ref=str(video_path),
        audio_probe_ref=str(audio_probe),
    )
    assert receipt.message_ids == ("13",)
    assert sent and sent[0]["method"] == "sendVideo"
    assert sent[0]["file_path"] == str(video_path.with_name("silent-with-probe.with-audio.webm"))
    assert normalised == [(str(video_path), str(audio_probe), "")]


def test_telegram_video_with_fallback_audio_synthesizes_text_before_silent(monkeypatch, tmp_path) -> None:
    video_path = tmp_path / "silent.mp4"
    audio_path = tmp_path / "narration.wav"
    target_path = tmp_path / "silent.with-audio.mp4"
    video_path.write_bytes(b"fake-video")
    audio_path.write_bytes(b"fake-audio")
    target_path.write_bytes(b"fake-video-with-audio")
    calls: list[tuple[str, str]] = []

    def _fake_render_fallback_audio_path(*, source_path, text, language):  # noqa: ANN001
        calls.append((str(text), str(language)))
        return audio_path

    def _fake_attach(source_path, rendered_audio_path):  # noqa: ANN001
        assert source_path == video_path
        assert rendered_audio_path == audio_path
        return str(target_path), target_path

    def _fake_silent(source_path):  # noqa: ANN001
        raise AssertionError("silent fallback should not be used when narration synthesis succeeds")

    monkeypatch.setattr(
        "app.services.telegram_delivery._telegram_video_render_fallback_audio_path",
        _fake_render_fallback_audio_path,
    )
    monkeypatch.setattr("app.services.telegram_delivery._telegram_video_with_attached_audio", _fake_attach)
    monkeypatch.setattr("app.services.telegram_delivery._telegram_video_with_silent_audio", _fake_silent)

    normalized_ref, temporary_path = _telegram_video_with_fallback_audio(
        str(video_path),
        fallback_audio_text="They call me Kestrel. That was not my first name.",
        fallback_audio_language="en",
    )

    assert normalized_ref == str(target_path)
    assert temporary_path == target_path
    assert calls == [("They call me Kestrel. That was not my first name.", "en")]
    assert not audio_path.exists()


def test_send_telegram_audio_for_principal_uploads_local_file(monkeypatch, tmp_path) -> None:
    runtime = _tool_runtime()
    runtime.upsert_connector_binding(
        principal_id="exec-telegram-audio-local",
        connector_name="telegram_identity",
        external_account_ref="42",
        auth_metadata_json={"default_chat_ref": "42", "bot_key": "default", "bot_handle": "ea_concierge_bot"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    monkeypatch.setenv(
        "EA_TELEGRAM_BOT_REGISTRY_JSON",
        json.dumps({"default": {"token": "telegram-token", "handle": "ea_concierge_bot"}}),
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
        auth_metadata_json={"default_chat_ref": "42", "bot_key": "default", "bot_handle": "ea_concierge_bot"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    monkeypatch.setenv(
        "EA_TELEGRAM_BOT_REGISTRY_JSON",
        json.dumps({"default": {"token": "telegram-token", "handle": "ea_concierge_bot"}}),
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


def test_send_telegram_message_for_principal_surfaces_http_error_detail(monkeypatch) -> None:
    runtime = _tool_runtime()
    runtime.upsert_connector_binding(
        principal_id="exec-telegram-http-error",
        connector_name="telegram_identity",
        external_account_ref="42",
        auth_metadata_json={"default_chat_ref": "42", "bot_key": "default"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    monkeypatch.setenv("EA_TELEGRAM_BOT_REGISTRY_JSON", json.dumps({"default": {"token": "telegram-token"}}))
    monkeypatch.setenv("EA_TELEGRAM_DELIVERY_MAX_ATTEMPTS", "2")
    monkeypatch.setattr("app.services.telegram_delivery.time.sleep", lambda *_args, **_kwargs: None)

    def _fake_urlopen(request, timeout=30):
        raise HTTPError(
            request.full_url,
            403,
            "Forbidden",
            hdrs=None,
            fp=io.BytesIO(
                json.dumps(
                    {
                        "ok": False,
                        "error_code": 403,
                        "description": "Forbidden: bot was blocked by the user",
                    }
                ).encode("utf-8")
            ),
        )

    monkeypatch.setattr("app.services.telegram_delivery.urllib.request.urlopen", _fake_urlopen)

    try:
        send_telegram_message_for_principal(runtime, principal_id="exec-telegram-http-error", text="Hello")
    except RuntimeError as exc:
        assert str(exc) == "telegram_sendmessage_http_403:bot_was_blocked_by_the_user"
    else:
        raise AssertionError("expected telegram_sendmessage_http_403:bot_was_blocked_by_the_user")


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
