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


def test_openvoice_ready_reports_tts_disabled_by_policy(monkeypatch) -> None:
    client, _runtime = _client(monkeypatch)

    response = client.get("/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "openvoice"
    assert body["role"] == "stt_only_policy_enforced"
    assert body["tts_allowed"] is False
    assert body["clone_allowed"] is False
    assert body["tts_disabled_reason"] == "openvoice_tts_disabled_by_policy"


def test_openvoice_synthesize_base_is_disabled_by_policy(monkeypatch) -> None:
    client, _runtime = _client(monkeypatch)

    response = client.post(
        "/synthesize-base",
        json={"text": "Guten Tag", "lang": "de", "base_voice_variant": "high"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "openvoice_tts_disabled_by_policy"


def test_openvoice_synthesize_is_disabled_by_policy(monkeypatch) -> None:
    client, _runtime = _client(monkeypatch)

    response = client.post(
        "/synthesize",
        json={"voice_id": "manfred", "text": "Hallo", "lang": "de"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "openvoice_tts_disabled_by_policy"


def test_openvoice_clone_is_disabled_by_policy(monkeypatch) -> None:
    pytest.importorskip("multipart")
    client, runtime = _client(monkeypatch)

    response = client.post(
        "/clone",
        data={"slug": "manfred", "voice_label": "Manfred", "voice_id": "manfred-openvoice"},
        files=[("files", ("sample.wav", b"audio", "audio/wav"))],
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "openvoice_tts_disabled_by_policy"
    assert runtime.clone_payloads == []


def test_openvoice_synthesize_base_rejects_by_policy_before_text_handling(monkeypatch) -> None:
    monkeypatch.setenv("OPENVOICE_MAX_TTS_TEXT_LEN", "4")
    client, _runtime = _client(monkeypatch)

    response = client.post("/synthesize-base", json={"text": "too long"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "openvoice_tts_disabled_by_policy"
