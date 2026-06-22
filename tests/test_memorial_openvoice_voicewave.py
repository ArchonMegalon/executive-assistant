from __future__ import annotations

import json
import os
from pathlib import Path
import time

from app.services import memorial_openvoice


class _FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        payload: dict[str, object] | None = None,
        content: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.content = content
        self.headers = headers or {}
        self.text = str(self._payload)

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> dict[str, object]:
        return dict(self._payload)


def _clear_unmixr_key_env(monkeypatch) -> None:
    monkeypatch.delenv("UNMIXR_API_KEY", raising=False)
    monkeypatch.delenv("UNMIXR_API_KEYS", raising=False)
    for name in list(os.environ):
        if name.startswith("UNMIXR_API_KEY_FALLBACK_"):
            monkeypatch.delenv(name, raising=False)


def test_unmixr_synthesize_rotates_to_fallback_slot_on_balance_response(monkeypatch, tmp_path: Path) -> None:
    _clear_unmixr_key_env(monkeypatch)
    monkeypatch.setenv("EA_UNMIXR_SLOT_SELECTOR_STATE_FILE", str(tmp_path / "unmixr-slots.json"))
    seen_auth: list[str] = []

    def fake_request(method, url, headers=None, **kwargs):  # noqa: ANN001
        seen_auth.append(str((headers or {}).get("Authorization") or ""))
        if len(seen_auth) == 1:
            return _FakeResponse(
                status_code=402,
                payload={"detail": "Insufficient API balance for prebuilt character"},
            )
        return _FakeResponse(status_code=200, payload={"audio_url": "https://audio.example/render.wav"})

    def fake_get(url, **kwargs):  # noqa: ANN001
        return _FakeResponse(status_code=200, content=b"audio-bytes", headers={"Content-Type": "audio/wav"})

    monkeypatch.setenv("UNMIXR_API_KEY", "primary-key")
    monkeypatch.setenv("UNMIXR_API_KEY_FALLBACK_1", "fallback-key")
    monkeypatch.setattr(memorial_openvoice.requests, "request", fake_request)
    monkeypatch.setattr(memorial_openvoice.requests, "get", fake_get)

    audio, content_type = memorial_openvoice.unmixr_synthesize_request(
        text="Guten Morgen.",
        voice_id="voice-1",
        lang="de-DE",
    )

    assert audio == b"audio-bytes"
    assert content_type == "audio/wav"
    assert seen_auth == ["Bearer primary-key", "Bearer fallback-key"]


def test_unmixr_smart_selector_discovers_dynamic_fallback_slots_and_cools_throttled_slot(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _clear_unmixr_key_env(monkeypatch)
    state_path = tmp_path / "unmixr-slots.json"
    monkeypatch.setenv("EA_UNMIXR_SLOT_SELECTOR_STATE_FILE", str(state_path))
    monkeypatch.setenv("UNMIXR_API_KEY", "primary-key")
    monkeypatch.setenv("UNMIXR_API_KEY_FALLBACK_12", "fallback-12-key")
    monkeypatch.setenv("UNMIXR_API_KEYS", "pool-key")
    seen_auth: list[str] = []

    def fake_request(method, url, headers=None, **kwargs):  # noqa: ANN001
        seen_auth.append(str((headers or {}).get("Authorization") or ""))
        if len(seen_auth) == 1:
            return _FakeResponse(
                status_code=429,
                payload={"detail": "Request was throttled. Expected available in 3600 seconds."},
            )
        return _FakeResponse(status_code=200, payload={"audio_url": "https://audio.example/render.wav"})

    def fake_get(url, **kwargs):  # noqa: ANN001
        return _FakeResponse(status_code=200, content=b"audio-bytes", headers={"Content-Type": "audio/wav"})

    monkeypatch.setattr(memorial_openvoice.requests, "request", fake_request)
    monkeypatch.setattr(memorial_openvoice.requests, "get", fake_get)

    audio, content_type = memorial_openvoice.unmixr_synthesize_request(
        text="Guten Morgen.",
        voice_id="voice-1",
        lang="de-DE",
    )

    assert audio == b"audio-bytes"
    assert content_type == "audio/wav"
    assert seen_auth == ["Bearer primary-key", "Bearer fallback-12-key"]
    assert memorial_openvoice.unmixr_api_key_slot_count() == 3

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["last_slot_name"] == "UNMIXR_API_KEY_FALLBACK_12"
    assert state["slots"]["UNMIXR_API_KEY"]["cooldown_until_epoch"] > time.time()
    rendered = json.dumps(state, sort_keys=True)
    assert "primary-key" not in rendered
    assert "fallback-12-key" not in rendered
    assert "pool-key" not in rendered


def test_unmixr_smart_selector_skips_cooled_down_slot(monkeypatch, tmp_path: Path) -> None:
    _clear_unmixr_key_env(monkeypatch)
    state_path = tmp_path / "unmixr-slots.json"
    cooldown_until = time.time() + 900
    state_path.write_text(
        json.dumps(
            {
                "slots": {
                    "UNMIXR_API_KEY": {
                        "cooldown_until_epoch": cooldown_until,
                        "cooldown_until": "2099-01-01T00:00:00Z",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_UNMIXR_SLOT_SELECTOR_STATE_FILE", str(state_path))
    monkeypatch.setenv("UNMIXR_API_KEY", "primary-key")
    monkeypatch.setenv("UNMIXR_API_KEY_FALLBACK_12", "fallback-12-key")
    seen_auth: list[str] = []

    def fake_request(method, url, headers=None, **kwargs):  # noqa: ANN001
        seen_auth.append(str((headers or {}).get("Authorization") or ""))
        return _FakeResponse(status_code=200, payload={"audio_url": "https://audio.example/render.wav"})

    def fake_get(url, **kwargs):  # noqa: ANN001
        return _FakeResponse(status_code=200, content=b"audio-bytes", headers={"Content-Type": "audio/wav"})

    monkeypatch.setattr(memorial_openvoice.requests, "request", fake_request)
    monkeypatch.setattr(memorial_openvoice.requests, "get", fake_get)

    audio, content_type = memorial_openvoice.unmixr_synthesize_request(
        text="Guten Morgen.",
        voice_id="voice-1",
        lang="de-DE",
    )

    assert audio == b"audio-bytes"
    assert content_type == "audio/wav"
    assert seen_auth == ["Bearer fallback-12-key"]


def test_unmixr_smart_selector_rotates_on_successful_response_without_audio_url_balance_error(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _clear_unmixr_key_env(monkeypatch)
    monkeypatch.setenv("EA_UNMIXR_SLOT_SELECTOR_STATE_FILE", str(tmp_path / "unmixr-slots.json"))
    monkeypatch.setenv("UNMIXR_API_KEY", "primary-key")
    monkeypatch.setenv("UNMIXR_API_KEY_FALLBACK_1", "fallback-key")
    seen_auth: list[str] = []

    def fake_request(method, url, headers=None, **kwargs):  # noqa: ANN001
        seen_auth.append(str((headers or {}).get("Authorization") or ""))
        if len(seen_auth) == 1:
            return _FakeResponse(
                status_code=200,
                payload={"message": "Insufficient API balance (prebuilt characters) to full-fill the request"},
            )
        return _FakeResponse(status_code=200, payload={"audio_url": "https://audio.example/render.wav"})

    def fake_get(url, **kwargs):  # noqa: ANN001
        return _FakeResponse(status_code=200, content=b"audio-bytes", headers={"Content-Type": "audio/wav"})

    monkeypatch.setattr(memorial_openvoice.requests, "request", fake_request)
    monkeypatch.setattr(memorial_openvoice.requests, "get", fake_get)

    audio, content_type = memorial_openvoice.unmixr_synthesize_request(
        text="Guten Morgen.",
        voice_id="voice-1",
        lang="de-DE",
    )

    assert audio == b"audio-bytes"
    assert content_type == "audio/wav"
    assert seen_auth == ["Bearer primary-key", "Bearer fallback-key"]


def test_unmixr_smart_selector_accepts_successful_audio_url_with_credit_usage(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _clear_unmixr_key_env(monkeypatch)
    state_path = tmp_path / "unmixr-slots.json"
    monkeypatch.setenv("EA_UNMIXR_SLOT_SELECTOR_STATE_FILE", str(state_path))
    monkeypatch.setenv("UNMIXR_API_KEY", "primary-key")
    seen_auth: list[str] = []

    def fake_request(*, method, url, headers, json=None, files=None, data=None, timeout=None):
        seen_auth.append(str(headers.get("Authorization") or ""))
        return _FakeResponse(
            status_code=200,
            payload={
                "success": True,
                "code": 200,
                "credit_usage": {"prebuilt": 213, "voice_cloning": 0},
                "audio_url": "https://audio.example/render.wav",
            },
        )

    def fake_get(url, timeout=None):
        return _FakeResponse(status_code=200, content=b"RIFF....WAVE", headers={"Content-Type": "audio/wav"})

    monkeypatch.setattr(memorial_openvoice.requests, "request", fake_request)
    monkeypatch.setattr(memorial_openvoice.requests, "get", fake_get)

    audio, content_type = memorial_openvoice.unmixr_synthesize_request(text="Hello", voice_id="voice-1", lang="en-US")

    assert audio == b"RIFF....WAVE"
    assert content_type == "audio/wav"
    assert seen_auth == ["Bearer primary-key"]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["slots"]["UNMIXR_API_KEY"]["last_status"] == "ok"


def test_voicewave_runtime_script_path_prefers_existing_container_path(monkeypatch) -> None:
    first_path = Path("/workspace/ea/scripts/voicewave_memorial_voice.py")
    container_path = Path("/app/scripts/voicewave_memorial_voice.py")

    monkeypatch.setattr(
        memorial_openvoice,
        "_VOICEWAVE_SCRIPT_CANDIDATES",
        (first_path, container_path),
    )
    monkeypatch.setattr(Path, "is_file", lambda self: self == container_path)

    assert memorial_openvoice.voicewave_runtime_script_path() == container_path


def test_voicewave_runtime_script_path_prefers_configured_path(monkeypatch, tmp_path: Path) -> None:
    configured = tmp_path / "voicewave_memorial_voice.py"
    monkeypatch.setenv("VOICEWAVE_SCRIPT_PATH", str(configured))

    assert memorial_openvoice.voicewave_runtime_script_path() == configured


def test_voicewave_runtime_script_path_falls_back_to_first_candidate(monkeypatch) -> None:
    first_path = Path("/workspace/ea/scripts/voicewave_memorial_voice.py")
    second_path = Path("/app/scripts/voicewave_memorial_voice.py")

    monkeypatch.setattr(
        memorial_openvoice,
        "_VOICEWAVE_SCRIPT_CANDIDATES",
        (first_path, second_path),
    )
    monkeypatch.setattr(Path, "is_file", lambda self: False)

    assert memorial_openvoice.voicewave_runtime_script_path() == first_path


def test_voicewave_synthesize_request_uses_cached_audio(monkeypatch, tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    audio_path = cache_root / "cached.wav"
    meta_path = cache_root / "cached.json"
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(b"cached-audio")
    meta_path.write_text("{}", encoding="utf-8")

    monkeypatch.setenv("VOICEWAVE_LOGIN_EMAIL", "voicewave@example.com")
    monkeypatch.setenv("VOICEWAVE_LOGIN_PASSWORD", "secret")
    monkeypatch.setattr(memorial_openvoice, "_VOICEWAVE_CACHE_ROOT_CANDIDATES", (cache_root,))
    monkeypatch.setattr(
        memorial_openvoice,
        "_voicewave_cache_paths",
        lambda **kwargs: (audio_path, meta_path),
    )
    monkeypatch.setattr(
        memorial_openvoice,
        "voicewave_runtime_script_path",
        lambda: Path("/missing/script.py"),
    )

    payload, content_type = memorial_openvoice.voicewave_synthesize_request(
        text="Ich bin da.",
        voice_label="Manfred Hoza Memorial",
    )

    assert payload == b"cached-audio"
    assert content_type == "audio/wav"
