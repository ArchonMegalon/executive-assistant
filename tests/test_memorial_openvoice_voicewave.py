from __future__ import annotations

import json
import os
from pathlib import Path
import time
import wave

import pytest
from fastapi import HTTPException

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
    monkeypatch.delenv("EA_AUDIOBOOK_UNMIXR_PRONUNCIATION_DICT_JSON", raising=False)
    for name in list(os.environ):
        if name.startswith("UNMIXR_API_KEY_FALLBACK_"):
            monkeypatch.delenv(name, raising=False)


def _write_wav(path: Path, *, seconds: float = 1.0) -> None:
    sample_rate = 16_000
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\0\0" * int(sample_rate * seconds))


def test_unmixr_clone_requires_one_precomposed_sample_before_provider_call(
    monkeypatch,
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"
    _write_wav(first)
    _write_wav(second)
    provider_called = False

    def fake_request(**kwargs):  # noqa: ANN003
        nonlocal provider_called
        provider_called = True
        return _FakeResponse(payload={"voice_id": "unexpected"})

    monkeypatch.setattr(memorial_openvoice, "_unmixr_request", fake_request)

    with pytest.raises(HTTPException) as caught:
        memorial_openvoice.unmixr_clone_request(
            slug="manfred",
            voice_label="Manfred reviewed",
            sample_paths=[first, second],
        )

    assert caught.value.status_code == 400
    assert caught.value.detail == "voice_profile_requires_single_prepared_sample"
    assert provider_called is False


def test_unmixr_clone_rejects_sample_over_75_seconds_without_truncating(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "too-long.wav"
    _write_wav(source, seconds=75.2)
    provider_called = False

    def fake_request(**kwargs):  # noqa: ANN003
        nonlocal provider_called
        provider_called = True
        return _FakeResponse(payload={"voice_id": "unexpected"})

    monkeypatch.setattr(memorial_openvoice, "_unmixr_request", fake_request)

    with pytest.raises(HTTPException) as caught:
        memorial_openvoice.unmixr_clone_request(
            slug="manfred",
            voice_label="Manfred reviewed",
            sample_paths=[source],
        )

    assert caught.value.status_code == 400
    assert caught.value.detail == "voice_profile_sample_too_long"
    assert provider_called is False


def test_unmixr_clone_rejects_sample_below_provider_minimum(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "too-short.wav"
    _write_wav(source, seconds=29.8)
    provider_called = False

    def fake_request(**kwargs):  # noqa: ANN003
        nonlocal provider_called
        provider_called = True
        return _FakeResponse(payload={"voice_id": "unexpected"})

    monkeypatch.setattr(memorial_openvoice, "_unmixr_request", fake_request)

    with pytest.raises(HTTPException) as caught:
        memorial_openvoice.unmixr_clone_request(
            slug="manfred",
            voice_label="Manfred reviewed",
            sample_paths=[source],
        )

    assert caught.value.status_code == 400
    assert caught.value.detail == "voice_profile_sample_too_short"
    assert provider_called is False


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


def test_unmixr_synthesize_redacts_provider_body_from_exception_and_slot_state(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _clear_unmixr_key_env(monkeypatch)
    state_path = tmp_path / "unmixr-slots.json"
    source_text = "PRIVATE BOOK PASSAGE: Manfred wartet am Fenster."
    voice_id = "raw-provider-voice-id-77"
    provider_detail = f"Rate limit while rendering {source_text} with voice_id={voice_id}"
    monkeypatch.setenv("EA_UNMIXR_SLOT_SELECTOR_STATE_FILE", str(state_path))
    monkeypatch.setenv("UNMIXR_API_KEY", "primary-key")

    def fake_request(method, url, headers=None, **kwargs):  # noqa: ANN001
        return _FakeResponse(status_code=429, payload={"detail": provider_detail})

    monkeypatch.setattr(memorial_openvoice.requests, "request", fake_request)

    with pytest.raises(HTTPException) as caught:
        memorial_openvoice.unmixr_synthesize_request(
            text=source_text,
            voice_id=voice_id,
            lang="de-DE",
        )

    error = caught.value
    assert getattr(error, "status_code", None) == 502
    assert getattr(error, "detail", None) == "unmixr_tts_rate_limited:429"
    assert source_text not in str(error)
    assert voice_id not in str(error)

    state = json.loads(state_path.read_text(encoding="utf-8"))
    slot_state = state["slots"]["UNMIXR_API_KEY"]
    assert slot_state["last_error_code"] == "unmixr_request_rate_limited"
    assert len(slot_state["last_error_body_sha256"]) == 64
    rendered_state = json.dumps(state, sort_keys=True)
    assert "last_error" not in slot_state
    assert source_text not in rendered_state
    assert voice_id not in rendered_state


@pytest.mark.parametrize(
    ("status_code", "provider_prefix", "expected_detail"),
    (
        (200, "Insufficient API balance", "unmixr_tts_balance_exhausted:200"),
        (402, "Insufficient API balance", "unmixr_tts_balance_exhausted:402"),
        (413, "Input too long", "unmixr_tts_input_too_long:413"),
    ),
)
def test_unmixr_synthesize_projects_useful_provider_error_classes_without_raw_body(
    monkeypatch,
    tmp_path: Path,
    status_code: int,
    provider_prefix: str,
    expected_detail: str,
) -> None:
    _clear_unmixr_key_env(monkeypatch)
    source_text = "PRIVATE BOOK PASSAGE: Niemand darf diesen Satz sehen."
    voice_id = "raw-provider-voice-id-88"
    monkeypatch.setenv("EA_UNMIXR_SLOT_SELECTOR_STATE_FILE", str(tmp_path / "unmixr-slots.json"))
    monkeypatch.setenv("UNMIXR_API_KEY", "primary-key")

    def fake_request(method, url, headers=None, **kwargs):  # noqa: ANN001
        return _FakeResponse(
            status_code=status_code,
            payload={"message": f"{provider_prefix}: text={source_text}; voice_id={voice_id}"},
        )

    monkeypatch.setattr(memorial_openvoice.requests, "request", fake_request)

    with pytest.raises(HTTPException) as caught:
        memorial_openvoice.unmixr_synthesize_request(
            text=source_text,
            voice_id=voice_id,
            lang="de-DE",
        )

    assert getattr(caught.value, "detail", None) == expected_detail
    assert source_text not in str(caught.value)
    assert voice_id not in str(caught.value)


def test_unmixr_synthesize_redacts_success_body_when_audio_url_is_missing(monkeypatch, tmp_path: Path) -> None:
    _clear_unmixr_key_env(monkeypatch)
    source_text = "PRIVATE BOOK PASSAGE: Ein stiller Nachmittag."
    voice_id = "raw-provider-voice-id-99"
    monkeypatch.setenv("EA_UNMIXR_SLOT_SELECTOR_STATE_FILE", str(tmp_path / "unmixr-slots.json"))
    monkeypatch.setenv("UNMIXR_API_KEY", "primary-key")

    def fake_request(method, url, headers=None, **kwargs):  # noqa: ANN001
        return _FakeResponse(
            status_code=200,
            payload={"message": f"No audio for text={source_text}; voice_id={voice_id}"},
        )

    monkeypatch.setattr(memorial_openvoice.requests, "request", fake_request)

    with pytest.raises(HTTPException) as caught:
        memorial_openvoice.unmixr_synthesize_request(
            text=source_text,
            voice_id=voice_id,
            lang="de-DE",
        )

    assert getattr(caught.value, "detail", None) == "unmixr_tts_no_audio_url:200"
    assert source_text not in str(caught.value)
    assert voice_id not in str(caught.value)


def test_unmixr_synthesize_includes_validated_pronunciation_dictionary(monkeypatch, tmp_path: Path) -> None:
    _clear_unmixr_key_env(monkeypatch)
    monkeypatch.setenv("EA_UNMIXR_SLOT_SELECTOR_STATE_FILE", str(tmp_path / "unmixr-slots.json"))
    monkeypatch.setenv("UNMIXR_API_KEY", "primary-key")
    seen_payloads: list[dict[str, object]] = []

    def fake_request(method, url, headers=None, **kwargs):  # noqa: ANN001
        seen_payloads.append(dict(kwargs.get("json") or {}))
        return _FakeResponse(status_code=200, payload={"audio_url": "https://audio.example/render.wav"})

    def fake_get(url, **kwargs):  # noqa: ANN001
        return _FakeResponse(status_code=200, content=b"audio-bytes", headers={"Content-Type": "audio/wav"})

    monkeypatch.setattr(memorial_openvoice.requests, "request", fake_request)
    monkeypatch.setattr(memorial_openvoice.requests, "get", fake_get)

    audio, content_type = memorial_openvoice.unmixr_synthesize_request(
        text="The SME uses Chummer.",
        voice_id="voice-1",
        lang="en-US",
        pronunciation_dict={"SME": "Small and Medium Enterprise", "Chummer": "CHUH-mer"},
    )

    assert audio == b"audio-bytes"
    assert content_type == "audio/wav"
    assert seen_payloads == [
        {
            "text": "The SME uses Chummer.",
            "voice_id": "voice-1",
            "language": "en-US",
            "response_type": "url",
            "speaking_rate": "medium",
            "speaking_pitch": "low",
            "speaking_volume": "medium",
            "pronunciation_dict": {"SME": "Small and Medium Enterprise", "Chummer": "CHUH-mer"},
        }
    ]


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


@pytest.mark.parametrize("declared_content_type", ["binary/octet-stream", "application/octet-stream"])
def test_unmixr_synthesize_recognizes_provider_mp3_with_generic_content_type(
    monkeypatch,
    tmp_path: Path,
    declared_content_type: str,
) -> None:
    _clear_unmixr_key_env(monkeypatch)
    monkeypatch.setenv("EA_UNMIXR_SLOT_SELECTOR_STATE_FILE", str(tmp_path / "unmixr-slots.json"))
    monkeypatch.setenv("UNMIXR_API_KEY", "primary-key")
    mp3_payload = b"ID3\x04\x00\x00\x00\x00\x00\x00provider-audio"

    monkeypatch.setattr(
        memorial_openvoice.requests,
        "request",
        lambda **kwargs: _FakeResponse(
            status_code=200,
            payload={"audio_url": "https://audio.example/render.mp3"},
        ),
    )
    monkeypatch.setattr(
        memorial_openvoice.requests,
        "get",
        lambda *args, **kwargs: _FakeResponse(
            status_code=200,
            content=mp3_payload,
            headers={"Content-Type": declared_content_type},
        ),
    )

    audio, content_type = memorial_openvoice.unmixr_synthesize_request(
        text="Guten Morgen.",
        voice_id="voice-1",
        lang="de-AT",
    )

    assert audio == mp3_payload
    assert content_type == "audio/mpeg"


def test_unmixr_language_preserves_provider_locale_casing(monkeypatch) -> None:
    monkeypatch.setenv("UNMIXR_LANGUAGE", "en_US")

    assert memorial_openvoice.unmixr_language("en-us") == "en-US"
    assert memorial_openvoice.unmixr_language("en_US") == "en-US"
    assert memorial_openvoice.unmixr_language("") == "en-US"
    assert memorial_openvoice.unmixr_language("de-DE") == "de-DE"
    assert memorial_openvoice.unmixr_language("de_AT") == "de-AT"
    assert memorial_openvoice.unmixr_language("de-AT") == "de-AT"


def test_unmixr_synthesize_sends_explicit_german_locale_without_changing_voice_id(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _clear_unmixr_key_env(monkeypatch)
    monkeypatch.setenv("EA_UNMIXR_SLOT_SELECTOR_STATE_FILE", str(tmp_path / "unmixr-slots.json"))
    monkeypatch.setenv("UNMIXR_API_KEY", "primary-key")
    seen_payloads: list[dict[str, object]] = []

    def fake_request(method, url, headers=None, **kwargs):  # noqa: ANN001
        seen_payloads.append(dict(kwargs.get("json") or {}))
        return _FakeResponse(status_code=200, payload={"audio_url": "https://audio.example/render.mp3"})

    monkeypatch.setattr(memorial_openvoice.requests, "request", fake_request)
    monkeypatch.setattr(
        memorial_openvoice.requests,
        "get",
        lambda *args, **kwargs: _FakeResponse(
            status_code=200,
            content=b"ID3\x04\x00\x00\x00\x00\x00\x00provider-audio",
            headers={"Content-Type": "audio/mpeg"},
        ),
    )

    audio, content_type = memorial_openvoice.unmixr_synthesize_request(
        text="Ich antworte ruhig auf Deutsch.",
        voice_id="approved-manfred-voice",
        lang="de-AT",
        speaking_rate="0.90",
    )

    assert audio.startswith(b"ID3")
    assert content_type == "audio/mpeg"
    assert seen_payloads[0]["language"] == "de-AT"
    assert seen_payloads[0]["voice_id"] == "approved-manfred-voice"
    assert seen_payloads[0]["speaking_rate"] == "0.90"


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
