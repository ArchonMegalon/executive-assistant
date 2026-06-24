from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import openvoice_app


class _FakeRuntime:
    def __init__(self) -> None:
        self.clone_payloads: list[list[tuple[str, bytes]]] = []

    def available_base_voice_variants(self) -> list[str]:
        return ["high", "balanced"]

    def synthesize_base(self, *, text: str, lang: str, base_voice_variant: str = "") -> bytes:
        assert text == "Guten Tag"
        assert lang == "de"
        assert base_voice_variant == "high"
        return b"RIFFbase"

    def synthesize(self, *, voice_id: str, text: str, lang: str, base_voice_variant: str = "") -> bytes:
        assert voice_id == "manfred"
        assert text == "Hallo"
        return b"RIFFclone"

    def clone_voice(self, *, voice_id: str, voice_label: str, source_files: list[tuple[str, bytes]]) -> dict[str, object]:
        self.clone_payloads.append(source_files)
        return {"voice_id": voice_id, "voice_label": voice_label, "sample_count": len(source_files)}


def _client(monkeypatch):
    runtime = _FakeRuntime()
    monkeypatch.setattr(openvoice_app, "get_openvoice_runtime", lambda: runtime)
    monkeypatch.setattr(
        openvoice_app,
        "load_openvoice_service_config",
        lambda: SimpleNamespace(
            base_tts="espeak",
            piper_bin="",
            piper_model="",
            converter_dir=SimpleNamespace(__truediv__=lambda _self, _name: SimpleNamespace(is_file=lambda: False)),
        ),
    )
    return TestClient(openvoice_app.create_app()), runtime


def test_openvoice_synthesize_base_returns_audio(monkeypatch) -> None:
    client, _runtime = _client(monkeypatch)

    response = client.post(
        "/synthesize-base",
        json={"text": "Guten Tag", "lang": "de", "base_voice_variant": "high"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.content == b"RIFFbase"


def test_openvoice_synthesize_returns_clone_audio(monkeypatch) -> None:
    client, _runtime = _client(monkeypatch)

    response = client.post(
        "/synthesize",
        json={"voice_id": "manfred", "text": "Hallo", "lang": "de"},
    )

    assert response.status_code == 200
    assert response.content == b"RIFFclone"


def test_openvoice_clone_accepts_bounded_files(monkeypatch) -> None:
    pytest.importorskip("multipart")
    client, runtime = _client(monkeypatch)

    response = client.post(
        "/clone",
        data={"slug": "manfred", "voice_label": "Manfred", "voice_id": "manfred-openvoice"},
        files=[("files", ("sample.wav", b"audio", "audio/wav"))],
    )

    assert response.status_code == 200
    assert response.json()["voice_id"] == "manfred-openvoice"
    assert runtime.clone_payloads == [[("sample.wav", b"audio")]]


def test_openvoice_synthesize_base_rejects_oversized_text(monkeypatch) -> None:
    monkeypatch.setenv("OPENVOICE_MAX_TTS_TEXT_LEN", "4")
    client, _runtime = _client(monkeypatch)

    response = client.post("/synthesize-base", json={"text": "too long"})

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "text_too_long"
