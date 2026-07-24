from __future__ import annotations

import base64
import asyncio
import io
import json
import logging
import math
import os
import re
import struct
import subprocess
import threading
import time
import wave
import contextlib
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from app.services.brain_catalog import GEMINI_VORTEX_PUBLIC_MODEL


ROOT = Path(__file__).resolve().parents[1]
MEMORIAL_FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "memorial"
PUBLIC_MEMORIALS_SOURCE = ROOT / "ea" / "app" / "api" / "routes" / "public_memorials.py"


CONTACT_REPLY_VARIANTS = {"Worum geht es?"}
_CARTESIA_SECRET_ENV_NAMES = (
    "CARTESIA_API_KEY",
    "EA_CARTESIA_API_KEY",
    "CARTESIA_API_KEY_JSON",
    "EA_CARTESIA_API_KEY_JSON",
    "CARTESIA_CREDENTIALS_JSON",
    "EA_CARTESIA_CREDENTIALS_JSON",
    "CARTESIA_API_KEY_FILE",
    "EA_CARTESIA_API_KEY_FILE",
    "CARTESIA_CREDENTIALS_JSON_FILE",
    "EA_CARTESIA_CREDENTIALS_JSON_FILE",
)


def _clear_cartesia_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _CARTESIA_SECRET_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    from app.api.routes import public_memorials

    monkeypatch.setattr(public_memorials, "_CARTESIA_DEFAULT_CREDENTIAL_FILES", ())


def test_contact_reply_variants_avoid_fragile_roundtrip_phrasing() -> None:
    from app.api.routes import public_memorials

    variants = {public_memorials._memorial_contact_answer_body(f"hallo manfred {index}") for index in range(128)}

    assert all("Jo" not in variant for variant in variants)
    assert all("Ich bin da" not in variant for variant in variants)
    assert variants == CONTACT_REPLY_VARIANTS


def _client(*, principal_id: str) -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ["EA_API_TOKEN"] = ""
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ.pop("EA_DEFAULT_PRINCIPAL_ID", None)
    os.environ.pop("EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER", None)
    os.environ.pop("EA_OPERATOR_PRINCIPAL_IDS", None)
    from app.api.app import create_app

    client = TestClient(create_app(), base_url="https://testserver")
    client.headers.update(
        {
            "Origin": "https://testserver",
            "X-EA-Principal-ID": principal_id,
        }
    )
    websocket_connect = client.websocket_connect

    def _secure_websocket_connect(url: str, *args, **kwargs):
        target = (
            url
            if "://" in url
            else f"wss://testserver{url}"
        )
        return websocket_connect(target, *args, **kwargs)

    client.websocket_connect = _secure_websocket_connect  # type: ignore[method-assign]
    return client


def _write_public_memorial(root: Path, slug: str, payload: dict[str, object]) -> None:
    bundle_dir = root / slug
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "memorial.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_private_voice(root: Path, slug: str, payload: dict[str, object]) -> None:
    profile_dir = root / slug
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "tts_voice.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_unmixr_private_voice(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
    slug: str,
    *,
    voice_id: str = "manfred-unmixr-test",
) -> None:
    from app.api.routes import public_memorials

    monkeypatch.setenv("UNMIXR_API_KEY", "unit-test-unmixr-key")
    _write_private_voice(
        root,
        slug,
        {
            "tts_plugin": public_memorials.UNMIXR_TTS_PLUGIN_ID,
            "tts_plugin_voice_id": voice_id,
            "voice_consent": {
                "status": "approved",
                "scope": ["synthesize", "conversation_turn", "realtime"],
                "authorized_by": "test-family",
                "authorized_at": "2026-06-06T08:00:00Z",
                "source_assets_reviewed": True,
                "revoked": False,
            },
        },
    )


def _patch_memorial_runtime_roots(tmp_path: Path) -> None:
    from app.api.routes import public_memorials
    from app.services import memorial_archive_registry

    artifacts_root = tmp_path / "artifacts"
    public_memorials._PERSONAL_MEMORY_ROOT = artifacts_root / "memorial_user_memory"
    public_memorials._VOICE_AB_ROOT = artifacts_root / "memorial_voice_ab"
    public_memorials._VIDEO_MEETING_RUNTIME_ROOT = artifacts_root / "memorial_video_meeting"
    public_memorials._MEMORIAL_TTS_RENDER_CACHE_ROOT = artifacts_root / "memorial_tts_render_cache"
    public_memorials._MEMORIAL_PRESENT_WORLD_CACHE_ROOT = artifacts_root / "memorial_present_world_cache"
    public_memorials._PUBLIC_MEMORIAL_RATE_DB = artifacts_root / "memorial_rate_limits.sqlite3"
    memorial_archive_registry.PUBLIC_MEMORIAL_ROOT = tmp_path / "public_registry"
    memorial_archive_registry.ARCHIVE_ROOT = tmp_path / "archive"


def _stt_error_bundles(root: Path) -> list[Path]:
    return sorted(path.parent for path in root.glob("**/error.json"))


def _captured_contact_opening_wav_bytes() -> bytes:
    return (MEMORIAL_FIXTURE_ROOT / "contact_opening_captured.wav").read_bytes()


def _captured_stt_retry_wav_bytes() -> bytes:
    return (MEMORIAL_FIXTURE_ROOT / "rescue_stt_retry_captured.wav").read_bytes()


def _captured_technical_retry_wav_bytes() -> bytes:
    return (MEMORIAL_FIXTURE_ROOT / "rescue_technical_retry_captured.wav").read_bytes()


def _wav_pcm16_samples(payload: bytes) -> tuple[int, list[int]]:
    with wave.open(io.BytesIO(payload), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        sample_rate = int(wav_file.getframerate() or 16_000)
        raw = wav_file.readframes(int(wav_file.getnframes() or 0))
    samples = [sample for (sample,) in struct.iter_unpack("<h", raw[: len(raw) - (len(raw) % 2)])]
    return sample_rate, samples


def _wav_from_samples(samples: list[int], *, sample_rate: int = 16_000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(struct.pack("<" + "h" * len(samples), *samples))
    return buffer.getvalue()


def _amplify_wav_bytes(payload: bytes, *, gain: float) -> bytes:
    sample_rate, samples = _wav_pcm16_samples(payload)
    amplified = [max(-32768, min(32767, int(sample * gain))) for sample in samples]
    return _wav_from_samples(amplified, sample_rate=sample_rate)


def _echo_wav_bytes(payload: bytes, *, delay_ms: int = 70, decay: float = 0.24) -> bytes:
    sample_rate, samples = _wav_pcm16_samples(payload)
    delay_samples = max(1, int(sample_rate * (delay_ms / 1000.0)))
    echoed = list(samples)
    for index, sample in enumerate(samples):
        delayed_index = index + delay_samples
        if delayed_index < len(echoed):
            echoed[delayed_index] = max(-32768, min(32767, echoed[delayed_index] + int(sample * decay)))
    return _wav_from_samples(echoed, sample_rate=sample_rate)


def _speed_up_wav_bytes(payload: bytes, *, factor: float = 1.35) -> bytes:
    sample_rate, samples = _wav_pcm16_samples(payload)
    target_len = max(1, int(len(samples) / max(1.01, factor)))
    sped = [samples[min(len(samples) - 1, int(index * factor))] for index in range(target_len)]
    return _wav_from_samples(sped, sample_rate=sample_rate)


def _mix_wav_with_noise(payload: bytes, *, noise_sample: int = 120) -> bytes:
    sample_rate, samples = _wav_pcm16_samples(payload)
    noise = [noise_sample, -noise_sample, noise_sample // 2, -(noise_sample // 2)]
    mixed = [
        max(-32768, min(32767, sample + noise[index % len(noise)]))
        for index, sample in enumerate(samples)
    ]
    return _wav_from_samples(mixed, sample_rate=sample_rate)


def _hostile_captured_wav_bytes(payload: bytes) -> bytes:
    hardened = _amplify_wav_bytes(payload, gain=1.18)
    hardened = _echo_wav_bytes(hardened, delay_ms=76, decay=0.22)
    hardened = _mix_wav_with_noise(hardened, noise_sample=132)
    return _speed_up_wav_bytes(hardened, factor=1.35)


def _generated_wav_bytes(*, textish_seed: str, duration_seconds: float = 0.35) -> bytes:
    sample_rate = 16_000
    frequency = 260 + (sum(ord(ch) for ch in textish_seed) % 220)
    total_frames = max(1, int(sample_rate * duration_seconds))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        frames = bytearray()
        for index in range(total_frames):
            envelope = 0.35 * math.sin(math.pi * index / total_frames)
            sample = int(18_000 * envelope * math.sin(2.0 * math.pi * frequency * index / sample_rate))
            frames.extend(struct.pack("<h", sample))
        wav.writeframes(bytes(frames))
    return buffer.getvalue()


def _silent_wav_bytes(*, duration_seconds: float = 1.0) -> bytes:
    sample_rate = 16_000
    total_frames = max(1, int(sample_rate * duration_seconds))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x00\x00" * total_frames)
    return buffer.getvalue()


def _pcm16_speech_bytes(*, samples: int = 400, sample: int = 8192) -> bytes:
    return struct.pack("<" + "h" * samples, *([sample] * samples))


def _pcm16_noise_bytes(*, samples: int = 1600, sample: int = 96) -> bytes:
    pattern = [sample, -sample, sample // 2, -(sample // 2)]
    values = [pattern[index % len(pattern)] for index in range(samples)]
    return struct.pack("<" + "h" * samples, *values)


def _pcm16_impulse_burst_bytes(*, samples: int = 1600, impulse: int = 12_000, spacing: int = 160) -> bytes:
    values = [0] * samples
    for index in range(0, samples, spacing):
        values[index] = impulse
        if index + 1 < samples:
            values[index + 1] = -impulse
    return struct.pack("<" + "h" * samples, *values)


def _wav_from_pcm16_bytes(payload: bytes, *, sample_rate: int = 16_000) -> bytes:
    raw = payload[: len(payload) - (len(payload) % 2)]
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(raw)
    return buffer.getvalue()


def _pcm16_mix_bytes(*parts: bytes) -> bytes:
    decoded_parts: list[list[int]] = []
    max_samples = 0
    for payload in parts:
        raw = payload[: len(payload) - (len(payload) % 2)]
        values = [sample for (sample,) in struct.iter_unpack("<h", raw)]
        decoded_parts.append(values)
        max_samples = max(max_samples, len(values))
    mixed: list[int] = []
    for index in range(max_samples):
        total = 0
        for values in decoded_parts:
            if index < len(values):
                total += values[index]
        mixed.append(max(-32768, min(32767, total)))
    return struct.pack("<" + "h" * len(mixed), *mixed)


def _setup_memorial(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    slug = "manfred"
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://testserver")
    monkeypatch.setenv("UNMIXR_API_KEY", "unit-test-unmixr-key")
    from app.api.routes import public_memorials

    monkeypatch.setattr(
        public_memorials,
        "unmixr_synthesize_request",
        lambda **kwargs: (_generated_wav_bytes(textish_seed=str(kwargs.get("text") or "unmixr-test")), "audio/wav"),
    )
    public_root = tmp_path / "public"
    private_root = tmp_path / "private"
    _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "audio_clips": [],
            "external_sources": [
                {
                    "public": True,
                    "label": "Interview Audio",
                    "status": "audio_ready",
                    "url": "https://youtube.example/interview",
                }
            ],
        },
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    monkeypatch.setenv("EA_PRIVATE_MEMORIAL_PROFILE_DIR", str(private_root))
    _patch_memorial_runtime_roots(tmp_path)
    return slug


def test_memorial_audio_energy_gate_rejects_silent_or_tiny_wav() -> None:
    from app.api.routes import public_memorials

    assert public_memorials._wav_payload_has_speech_energy(_generated_wav_bytes(textish_seed="Hallo", duration_seconds=0.8))
    assert not public_memorials._wav_payload_has_speech_energy(_silent_wav_bytes(duration_seconds=1.0))
    assert not public_memorials._wav_payload_has_speech_energy(b"RIFF")
    assert not public_memorials._wav_payload_has_speech_energy(_wav_from_pcm16_bytes(_pcm16_impulse_burst_bytes()))


@pytest.mark.parametrize(
    "payload_factory",
    (
        _captured_contact_opening_wav_bytes,
        _captured_stt_retry_wav_bytes,
        _captured_technical_retry_wav_bytes,
    ),
)
def test_memorial_audio_energy_gate_accepts_hostile_captured_speech_variants(payload_factory) -> None:
    from app.api.routes import public_memorials

    hostile = _hostile_captured_wav_bytes(payload_factory())

    assert public_memorials._wav_payload_has_speech_energy(hostile)


def test_memorial_audio_energy_gate_still_rejects_overcompressed_captured_clip() -> None:
    from app.api.routes import public_memorials

    too_fast = _speed_up_wav_bytes(_captured_contact_opening_wav_bytes(), factor=3.2)

    assert not public_memorials._wav_payload_has_speech_energy(too_fast)


def test_memorial_speech_transcribe_rejects_silent_wav_before_provider_upload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials
    from app.product import service as product_service

    monkeypatch.setattr(product_service, "_pocket_onemin_api_keys", lambda: ("key-1",))

    def _unexpected_upload(**kwargs):
        raise AssertionError("silent audio should not be uploaded to speech provider")

    monkeypatch.setattr(product_service, "_onemin_asset_upload", _unexpected_upload)

    result = public_memorials._memorial_transcribe_audio_blob(payload=_silent_wav_bytes(), content_type="audio/wav")

    assert result["transcription_status"] == "no_speech"
    assert result["transcriber"] == "local_audio_gate"
    assert result["detail"] == "audio_silence"


def test_memorial_shadow_stt_defaults_to_blipai_without_external_send_when_url_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.api.routes import public_memorials

    public_memorials._MEMORIAL_BLIPAI_TOKEN_STATE.clear()
    public_memorials._MEMORIAL_SHADOW_STT_PROVIDER_COOLDOWNS.clear()
    monkeypatch.setenv("EA_MEMORIAL_BLIPAI_TOKEN_STATE_PATH", str(tmp_path / "missing-shadow-token.json"))
    monkeypatch.delenv("EA_MEMORIAL_SHADOW_STT_PROVIDER", raising=False)
    monkeypatch.delenv("EA_MEMORIAL_SHADOW_STT_URL", raising=False)
    monkeypatch.delenv("BLIPAI_APP_API_TOKEN", raising=False)
    result = public_memorials._memorial_shadow_stt_result(
        user_audio_payload=_generated_wav_bytes(textish_seed="Wie ist das Wetter heute?"),
        content_type="audio/wav",
        primary_transcript="Wie ist das Wetter heute?",
        primary_transcriber="1min.ai/whisper-1",
    )

    assert result == {"enabled": False, "mode": "shadow_only", "provider": "blipai", "reason": "url_missing"}


def test_memorial_shadow_stt_blipai_receives_only_user_question_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials

    seen: dict[str, object] = {}
    public_memorials._MEMORIAL_SHADOW_STT_PROVIDER_COOLDOWNS.clear()

    class _Response:
        status_code = 200

        def json(self) -> dict[str, object]:
            return {"transcript_text": "Wie ist das Wetter heute?"}

    def _fake_post(url, *, headers, json, timeout):
        seen["url"] = url
        seen["headers"] = headers
        seen["json"] = json
        seen["timeout"] = timeout
        return _Response()

    monkeypatch.setenv("EA_MEMORIAL_SHADOW_STT_URL", "https://blipai.example/shadow-stt")
    monkeypatch.setenv("EA_MEMORIAL_SHADOW_STT_API_KEY", "unit-key")
    monkeypatch.setattr(public_memorials.requests, "post", _fake_post)

    result = public_memorials._memorial_shadow_stt_result(
        user_audio_payload=_generated_wav_bytes(textish_seed="Wie ist das Wetter heute?"),
        content_type="audio/wav",
        primary_transcript="Wie ist das Wetter heute?",
        primary_transcriber="1min.ai/whisper-1",
    )

    assert result["enabled"] is True
    assert result["provider"] == "blipai"
    assert result["status"] == "ok"
    assert result["may_override_primary"] is False
    payload = seen["json"]
    assert payload["mode"] == "shadow_only_user_question_stt"
    assert payload["primary_transcript"] == "Wie ist das Wetter heute?"
    assert payload["primary_transcriber"] == "1min.ai/whisper-1"
    assert payload["may_override_primary"] is False
    assert payload["include_memorial_answer"] is False
    assert payload["include_private_memory"] is False
    assert "audio_base64" in payload
    assert "answer" not in payload
    assert "private_memory" not in payload


def test_memorial_shadow_stt_blipai_defaults_to_official_multipart_api(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.api.routes import public_memorials

    seen: dict[str, object] = {}
    public_memorials._MEMORIAL_BLIPAI_TOKEN_STATE.clear()
    public_memorials._MEMORIAL_SHADOW_STT_PROVIDER_COOLDOWNS.clear()

    class _Response:
        status_code = 200

        def json(self) -> dict[str, object]:
            return {"text": "Hallo Manfred, kannst du jetzt mit mir sprechen?"}

    def _fake_post(url, *, headers, files=None, json=None, timeout):
        seen["url"] = url
        seen["headers"] = headers
        seen["files"] = files
        seen["json"] = json
        seen["timeout"] = timeout
        return _Response()

    monkeypatch.setenv("EA_MEMORIAL_BLIPAI_TOKEN_STATE_PATH", str(tmp_path / "missing-shadow-token.json"))
    monkeypatch.delenv("EA_MEMORIAL_SHADOW_STT_URL", raising=False)
    monkeypatch.delenv("EA_MEMORIAL_SHADOW_STT_API_KEY", raising=False)
    monkeypatch.setenv("BLIPAI_APP_API_TOKEN", "blip-unit-token")
    monkeypatch.setattr(public_memorials.requests, "post", _fake_post)

    result = public_memorials._memorial_shadow_stt_result(
        user_audio_payload=b"wav-bytes",
        content_type="audio/wav",
        primary_transcript="Untertitel der Amara.org-Community",
        primary_transcriber="1min.ai/whisper-1+enhanced_wav",
    )

    assert result["enabled"] is True
    assert result["provider"] == "blipai"
    assert result["status"] == "ok"
    assert seen["url"] == public_memorials._BLIPAI_DEFAULT_STT_URL
    assert seen["json"] is None
    files = seen["files"]
    assert isinstance(files, dict)
    assert "audio" in files
    filename, payload, content_type = files["audio"]
    assert filename == "shadow-stt.wav"
    assert payload == b"wav-bytes"
    assert content_type == "audio/wav"
    assert seen["headers"]["Authorization"] == "Bearer blip-unit-token"


def test_memorial_shadow_stt_sets_provider_cooldown_after_auth_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials

    public_memorials._MEMORIAL_SHADOW_STT_PROVIDER_COOLDOWNS.clear()

    class _Response:
        status_code = 401

        @staticmethod
        def json() -> dict[str, object]:
            return {}

    monkeypatch.setenv("BLIPAI_APP_API_TOKEN", "blip-unit-token")
    monkeypatch.delenv("EA_MEMORIAL_SHADOW_STT_URL", raising=False)
    monkeypatch.setenv("EA_MEMORIAL_SHADOW_STT_ERROR_COOLDOWN_SECONDS", "120")
    monkeypatch.setattr(public_memorials.requests, "post", lambda *args, **kwargs: _Response())

    result = public_memorials._memorial_shadow_stt_result(
        user_audio_payload=b"user-question-only",
        content_type="audio/wav",
        primary_transcript="Hallo Manfred",
        primary_transcriber="1min.ai/whisper-1",
    )

    assert result["enabled"] is True
    assert result["status"] == "error"
    assert result["reason"] == "http_401"
    assert public_memorials._MEMORIAL_SHADOW_STT_PROVIDER_COOLDOWNS["blipai"] > time.time()


def test_memorial_shadow_stt_skips_requests_during_provider_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials

    public_memorials._MEMORIAL_SHADOW_STT_PROVIDER_COOLDOWNS.clear()
    public_memorials._MEMORIAL_SHADOW_STT_PROVIDER_COOLDOWNS["blipai"] = time.time() + 60.0
    monkeypatch.setenv("BLIPAI_APP_API_TOKEN", "blip-unit-token")

    result = public_memorials._memorial_shadow_stt_result(
        user_audio_payload=b"user-question-only",
        content_type="audio/wav",
        primary_transcript="Hallo Manfred",
        primary_transcriber="1min.ai/whisper-1",
    )

    assert result["enabled"] is False
    assert result["reason"] == "provider_cooldown_active"
    assert result["cooldown_seconds_remaining"] > 0
    public_memorials._MEMORIAL_SHADOW_STT_PROVIDER_COOLDOWNS.clear()


def test_memorial_shadow_stt_refreshes_expired_blipai_access_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.api.routes import public_memorials

    public_memorials._MEMORIAL_SHADOW_STT_PROVIDER_COOLDOWNS.clear()
    public_memorials._MEMORIAL_BLIPAI_TOKEN_STATE.clear()
    monkeypatch.setenv("EA_MEMORIAL_BLIPAI_TOKEN_STATE_PATH", str(tmp_path / "missing-shadow-token.json"))
    monkeypatch.setenv("BLIPAI_APP_API_TOKEN", "expired-token")
    monkeypatch.setenv("BLIPAI_APP_REFRESH_TOKEN", "refresh-token")
    monkeypatch.delenv("EA_MEMORIAL_SHADOW_STT_URL", raising=False)

    calls: list[dict[str, object]] = []

    class _Unauthorized:
        status_code = 401

        @staticmethod
        def json() -> dict[str, object]:
            return {"error": "Token expired"}

    class _RefreshOK:
        status_code = 200

        @staticmethod
        def json() -> dict[str, object]:
            return {"access_token": "fresh-token", "refresh_token": "next-refresh-token"}

    class _ShadowOK:
        status_code = 200

        @staticmethod
        def json() -> dict[str, object]:
            return {"transcript_text": "Wie ist das Wetter heute in Wien?"}

    def _fake_post(url, *, headers, files=None, json=None, timeout):
        calls.append({"url": url, "headers": headers, "files": files, "json": json, "timeout": timeout})
        if url.endswith("/auth/v1/token?grant_type=refresh_token"):
            return _RefreshOK()
        if headers.get("Authorization") == "Bearer expired-token":
            return _Unauthorized()
        assert headers.get("Authorization") == "Bearer fresh-token"
        return _ShadowOK()

    monkeypatch.setattr(public_memorials.requests, "post", _fake_post)

    result = public_memorials._memorial_shadow_stt_result(
        user_audio_payload=b"user-question-only",
        content_type="audio/wav",
        primary_transcript="Ich höre dich.",
        primary_transcriber="1min.ai/whisper-1",
    )

    assert result["status"] == "ok"
    assert result["transcript_text"] == "Wie ist das Wetter heute in Wien?"
    assert public_memorials._MEMORIAL_BLIPAI_TOKEN_STATE["access_token"] == "fresh-token"
    assert public_memorials._MEMORIAL_BLIPAI_TOKEN_STATE["refresh_token"] == "next-refresh-token"
    assert [call["url"] for call in calls].count(public_memorials._BLIPAI_DEFAULT_STT_URL) == 2


def test_memorial_shadow_stt_uses_cached_blipai_access_token_after_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials

    public_memorials._MEMORIAL_BLIPAI_TOKEN_STATE.clear()
    public_memorials._MEMORIAL_BLIPAI_TOKEN_STATE.update(
        {"access_token": "cached-fresh-token", "refresh_token": "cached-refresh-token"}
    )
    monkeypatch.delenv("EA_MEMORIAL_SHADOW_STT_API_KEY", raising=False)
    monkeypatch.delenv("EA_MEMORIAL_SHADOW_STT_URL", raising=False)
    monkeypatch.setenv("BLIPAI_APP_API_TOKEN", "expired-token")

    class _Response:
        status_code = 200

        @staticmethod
        def json() -> dict[str, object]:
            return {"text": "Hallo Manfred"}

    seen: dict[str, object] = {}

    def _fake_post(url, *, headers, files=None, json=None, timeout):
        seen["auth"] = headers.get("Authorization")
        return _Response()

    monkeypatch.setattr(public_memorials.requests, "post", _fake_post)

    result = public_memorials._memorial_shadow_stt_result(
        user_audio_payload=b"user-question-only",
        content_type="audio/wav",
        primary_transcript="Hallo Manfred",
        primary_transcriber="1min.ai/whisper-1",
    )

    assert result["status"] == "ok"
    assert seen["auth"] == "Bearer cached-fresh-token"


def test_memorial_shadow_stt_loads_persisted_blipai_access_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.api.routes import public_memorials

    state_path = tmp_path / "blipai-shadow-token.json"
    state_path.write_text(
        json.dumps({"access_token": "persisted-access", "refresh_token": "persisted-refresh"}),
        encoding="utf-8",
    )
    public_memorials._MEMORIAL_BLIPAI_TOKEN_STATE.clear()
    monkeypatch.setenv("EA_MEMORIAL_BLIPAI_TOKEN_STATE_PATH", str(state_path))
    monkeypatch.delenv("EA_MEMORIAL_SHADOW_STT_API_KEY", raising=False)
    monkeypatch.delenv("EA_MEMORIAL_SHADOW_STT_URL", raising=False)
    monkeypatch.delenv("BLIPAI_APP_API_TOKEN", raising=False)

    class _Response:
        status_code = 200

        @staticmethod
        def json() -> dict[str, object]:
            return {"text": "Hallo Manfred"}

    seen: dict[str, object] = {}

    def _fake_post(url, *, headers, files=None, json=None, timeout):
        seen["auth"] = headers.get("Authorization")
        return _Response()

    monkeypatch.setattr(public_memorials.requests, "post", _fake_post)

    result = public_memorials._memorial_shadow_stt_result(
        user_audio_payload=b"user-question-only",
        content_type="audio/wav",
        primary_transcript="Hallo Manfred",
        primary_transcriber="1min.ai/whisper-1",
    )

    assert result["status"] == "ok"
    assert seen["auth"] == "Bearer persisted-access"


def test_memorial_shadow_stt_persists_refreshed_blipai_tokens(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.api.routes import public_memorials

    state_path = tmp_path / "blipai-shadow-token.json"
    public_memorials._MEMORIAL_BLIPAI_TOKEN_STATE.clear()
    monkeypatch.setenv("EA_MEMORIAL_BLIPAI_TOKEN_STATE_PATH", str(state_path))
    monkeypatch.setenv("BLIPAI_APP_API_TOKEN", "expired-token")
    monkeypatch.setenv("BLIPAI_APP_REFRESH_TOKEN", "refresh-token")
    monkeypatch.delenv("EA_MEMORIAL_SHADOW_STT_URL", raising=False)

    class _Unauthorized:
        status_code = 401

        @staticmethod
        def json() -> dict[str, object]:
            return {"error": "Token expired"}

    class _RefreshOK:
        status_code = 200

        @staticmethod
        def json() -> dict[str, object]:
            return {"access_token": "fresh-token", "refresh_token": "next-refresh-token"}

    class _ShadowOK:
        status_code = 200

        @staticmethod
        def json() -> dict[str, object]:
            return {"transcript_text": "Wie ist das Wetter heute in Wien?"}

    def _fake_post(url, *, headers, files=None, json=None, timeout):
        if url.endswith("/auth/v1/token?grant_type=refresh_token"):
            return _RefreshOK()
        if headers.get("Authorization") == "Bearer expired-token":
            return _Unauthorized()
        return _ShadowOK()

    monkeypatch.setattr(public_memorials.requests, "post", _fake_post)

    result = public_memorials._memorial_shadow_stt_result(
        user_audio_payload=b"user-question-only",
        content_type="audio/wav",
        primary_transcript="Ich höre dich.",
        primary_transcriber="1min.ai/whisper-1",
    )

    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert result["status"] == "ok"
    assert saved["access_token"] == "fresh-token"
    assert saved["refresh_token"] == "next-refresh-token"


def test_memorial_shadow_stt_marks_substantial_user_question_correction() -> None:
    from app.api.routes import public_memorials

    correction = public_memorials._memorial_shadow_stt_correction_decision(
        primary_transcript="Ich höre dich.",
        shadow_transcript="Wie ist das Wetter heute in Wien?",
    )
    minor = public_memorials._memorial_shadow_stt_correction_decision(
        primary_transcript="Wie ist das Wetter heute?",
        shadow_transcript="Wie ist das Wetter heute bitte?",
    )

    assert correction["should_correct"] is True
    assert correction["corrected_transcript"] == "Wie ist das Wetter heute in Wien?"
    assert minor["should_correct"] is False


def test_memorial_shadow_stt_ignores_too_brief_shadow_transcript() -> None:
    from app.api.routes import public_memorials

    correction = public_memorials._memorial_shadow_stt_correction_decision(
        primary_transcript="Ich höre dich.",
        shadow_transcript="Bye.",
    )

    assert correction == {"should_correct": False, "reason": "shadow_too_brief"}


def test_memorial_shadow_stt_ignores_language_mismatched_shadow_transcript() -> None:
    from app.api.routes import public_memorials

    correction = public_memorials._memorial_shadow_stt_correction_decision(
        primary_transcript="Wie ist das Wetter heute?",
        shadow_transcript="hello weather today",
    )

    assert correction == {"should_correct": False, "reason": "shadow_language_mismatch"}


def test_memorial_shadow_stt_ignores_reply_like_shadow_transcript() -> None:
    from app.api.routes import public_memorials

    correction = public_memorials._memorial_shadow_stt_correction_decision(
        primary_transcript="Das weiß ich nicht.",
        shadow_transcript="Was weiß ich nun?",
    )

    assert correction == {"should_correct": False, "reason": "shadow_matches_memorial_reply"}


def test_memorial_shadow_stt_requires_user_intent_when_primary_is_weak() -> None:
    from app.api.routes import public_memorials

    correction = public_memorials._memorial_shadow_stt_correction_decision(
        primary_transcript="Worum geht es?",
        shadow_transcript="Ja, ich schwöre es nicht.",
    )

    assert correction == {"should_correct": False, "reason": "shadow_user_intent_missing"}


def test_memorial_shadow_stt_requires_anchor_for_large_unrelated_overwrite() -> None:
    from app.api.routes import public_memorials

    correction = public_memorials._memorial_shadow_stt_correction_decision(
        primary_transcript="Ich habe gestern mit meiner Schwester gesprochen.",
        shadow_transcript="Manfred sitzt am Fenster und lächelt leise.",
    )

    assert correction["should_correct"] is False
    assert correction["reason"] == "shadow_semantic_anchor_missing"


def test_memorial_shadow_stt_allows_question_like_upgrade_from_low_information_primary() -> None:
    from app.api.routes import public_memorials

    correction = public_memorials._memorial_shadow_stt_correction_decision(
        primary_transcript="Ich höre dich.",
        shadow_transcript="Wie ist das Wetter heute in Wien?",
    )

    assert correction["should_correct"] is True
    assert correction["corrected_transcript"] == "Wie ist das Wetter heute in Wien?"


def test_memorial_shadow_stt_allows_current_medical_question_upgrade_from_low_information_primary() -> None:
    from app.api.routes import public_memorials

    correction = public_memorials._memorial_shadow_stt_correction_decision(
        primary_transcript="Ich höre dich.",
        shadow_transcript="Würdest du dich heute gegen Covid impfen lassen?",
    )

    assert correction["should_correct"] is True
    assert correction["corrected_transcript"] == "Würdest du dich heute gegen Covid impfen lassen?"


def test_memorial_shadow_stt_fast_primary_candidate_accepts_plausible_user_question() -> None:
    from app.api.routes import public_memorials

    assert public_memorials._memorial_shadow_stt_is_fast_primary_candidate("Wie ist das Wetter heute in Wien?") is True
    assert public_memorials._memorial_shadow_stt_is_fast_primary_candidate("Hallo Manfred, kannst du jetzt mit mir sprechen?") is True
    assert public_memorials._memorial_shadow_stt_is_fast_primary_candidate("Kannst du mit mir reden?") is True
    assert public_memorials._memorial_shadow_stt_is_fast_primary_candidate("Was ist der aktuelle Stand?") is True
    assert public_memorials._memorial_shadow_stt_is_fast_primary_candidate("Würdest du dich heute gegen Covid impfen lassen?") is True


def test_memorial_shadow_stt_fast_primary_candidate_rejects_brief_or_language_drift() -> None:
    from app.api.routes import public_memorials

    assert public_memorials._memorial_shadow_stt_is_fast_primary_candidate("you") is False
    assert public_memorials._memorial_shadow_stt_is_fast_primary_candidate("hello weather today") is False
    assert public_memorials._memorial_shadow_stt_is_fast_primary_candidate("Worum geht es?") is False
    assert public_memorials._memorial_shadow_stt_is_fast_primary_candidate("Manfred sitzt am Fenster und lächelt leise.") is False
    assert public_memorials._memorial_shadow_stt_is_fast_primary_candidate("bitte morgen kaffee holen") is False
    assert public_memorials._memorial_shadow_stt_is_fast_primary_candidate("hallo das fenster ist offen") is False
    assert public_memorials._memorial_shadow_stt_is_fast_primary_candidate("kann sein dass musik läuft") is False
    assert public_memorials._memorial_shadow_stt_is_fast_primary_candidate("manfred am fenster leise") is False
    assert public_memorials._memorial_shadow_stt_is_fast_primary_candidate("heute ist die lampe kaputt") is False
    assert public_memorials._memorial_shadow_stt_is_fast_primary_candidate("reden wir später darüber") is False
    assert public_memorials._memorial_shadow_stt_is_fast_primary_candidate("wie ist es") is False
    assert public_memorials._memorial_shadow_stt_is_fast_primary_candidate("wie ist dein Name") is False
    assert public_memorials._memorial_shadow_stt_is_fast_primary_candidate("wie geht es") is False
    assert public_memorials._memorial_shadow_stt_is_fast_primary_candidate("wie läufts") is False


def test_memorial_contact_opening_recognizes_known_bad_subtitle_transcript() -> None:
    from app.api.routes import public_memorials

    assert public_memorials._looks_like_memorial_contact_opening_transcript("Untertitel der Amara.org-Community") is True
    assert (
        public_memorials._canonical_memorial_contact_opening_question("Untertitel der Amara.org-Community")
        == "Hallo Manfred, kannst du jetzt mit mir sprechen?"
    )


def test_memorial_canonical_question_rescues_weather_and_current_state_intents() -> None:
    from app.api.routes import public_memorials

    assert (
        public_memorials._canonical_memorial_contact_opening_question("wie ist wetter heute in wien")
        == "Wie ist das Wetter heute?"
    )
    assert (
        public_memorials._canonical_memorial_contact_opening_question("aktueller stand jetzt")
        == "Was ist der aktuelle Stand?"
    )
    assert (
        public_memorials._canonical_memorial_contact_opening_question("ich habe gestern mit meiner Schwester gesprochen")
        == "ich habe gestern mit meiner Schwester gesprochen"
    )


def test_memorial_transcript_repair_recovers_stumm_from_hostile_audio_confusion() -> None:
    from app.api.routes import public_memorials

    assert (
        public_memorials._repair_memorial_transcript_text("Kommt da noch was oder bist du jetzt dumm?")
        == "Kommt da noch was oder bist du jetzt stumm?"
    )


def test_memorial_visible_transcript_preserves_original_user_wording() -> None:
    from app.api.routes import public_memorials

    assert (
        public_memorials._memorial_visible_transcript_text(
            transcript_text="wie ist wetter heute in wien",
            effective_question="Wie ist das Wetter heute?",
        )
        == "wie ist wetter heute in wien"
    )


def test_memorial_transcript_selection_prefers_routable_weather_question_over_generic_narrative() -> None:
    from app.api.routes import public_memorials

    best = public_memorials._select_best_memorial_transcription(
        [
            {
                "transcript_text": "ich habe heute im garten gearbeitet",
                "primary_transcript_text": "ich habe heute im garten gearbeitet",
                "transcriber": "1min.ai/original",
            },
            {
                "transcript_text": "wie ist wetter heute in wien",
                "primary_transcript_text": "wie ist wetter heute in wien",
                "transcriber": "1min.ai/original",
            },
        ]
    )

    assert best is not None
    assert best["transcript_text"] == "wie ist wetter heute in wien"


def test_memorial_theme_question_detection_and_selection_prefers_question_like_variant() -> None:
    from app.api.routes import public_memorials

    assert public_memorials._looks_like_memorial_theme_question("Was war dir bei Gerechtigkeit wichtig?") is True
    assert public_memorials._looks_like_memorial_theme_question("Ich habe über Gerechtigkeit nachgedacht.") is False

    best = public_memorials._select_best_memorial_transcription(
        [
            {
                "transcript_text": "ich habe über gerechtigkeit nachgedacht",
                "primary_transcript_text": "ich habe über gerechtigkeit nachgedacht",
                "transcriber": "1min.ai/original",
            },
            {
                "transcript_text": "was war dir bei gerechtigkeit wichtig",
                "primary_transcript_text": "was war dir bei gerechtigkeit wichtig",
                "transcriber": "1min.ai/original",
            },
        ]
    )

    assert best is not None
    assert best["transcript_text"] == "was war dir bei gerechtigkeit wichtig"


def test_memorial_transcribe_applies_shadow_stt_correction_to_effective_transcript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials
    from app.product import service as product_service

    _clear_cartesia_env(monkeypatch)
    monkeypatch.setattr(product_service, "_pocket_onemin_api_keys", lambda: ("key-1",))
    monkeypatch.setattr(
        product_service,
        "_onemin_asset_upload",
        lambda **kwargs: {"asset": {"key": "audio-key"}, "fileContent": {"path": "audio-path"}},
    )
    monkeypatch.setattr(
        product_service,
        "_onemin_speech_to_text",
        lambda **kwargs: {
            "aiRecord": {
                "status": "SUCCESS",
                "aiRecordDetail": {
                    "responseObject": {
                        "text": "Hallo Manfred, kannst du jetzt mit mir brechen?"
                    }
                },
            }
        },
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_shadow_stt_result",
        lambda **kwargs: {
            "enabled": True,
            "provider": "blipai",
            "status": "ok",
            "transcript_text": "Hallo Manfred, kannst du jetzt mit mir sprechen?",
            "correction": {
                "should_correct": True,
                "reason": "substantial_shadow_difference",
                "corrected_transcript": "Hallo Manfred, kannst du jetzt mit mir sprechen?",
            },
        },
    )
    monkeypatch.setattr(public_memorials, "_memorial_shadow_stt_is_fast_primary_candidate", lambda text: False)

    result = public_memorials._memorial_transcribe_audio_blob(
        payload=_generated_wav_bytes(textish_seed="Hallo Manfred, kannst du jetzt mit mir sprechen?"),
        content_type="audio/wav",
    )

    assert result["transcript_text"] == "Hallo Manfred, kannst du jetzt mit mir sprechen?"
    assert result["primary_transcript_text"] == "Hallo Manfred, kannst du jetzt mit mir brechen?"


def test_memorial_transcribe_uses_fast_shadow_stt_candidate_before_slow_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials
    from app.product import service as product_service

    monkeypatch.setattr(
        public_memorials,
        "_memorial_shadow_stt_result",
        lambda **kwargs: {
            "enabled": True,
            "provider": "blipai",
            "status": "ok",
            "transcript_text": "Wie ist das Wetter heute in Wien?",
        },
    )
    monkeypatch.setattr(
        product_service,
        "_pocket_onemin_api_keys",
        lambda: (_ for _ in ()).throw(AssertionError("slow primary should not run")),
    )

    result = public_memorials._memorial_transcribe_audio_blob(
        payload=_generated_wav_bytes(textish_seed="Wie ist das Wetter heute in Wien?"),
        content_type="audio/wav",
    )

    assert result["transcript_text"] == "Wie ist das Wetter heute in Wien?"
    assert result["transcriber"] == "shadow:blipai"


def test_memorial_transcribe_prefers_cartesia_stt_before_onemin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials
    from app.product import service as product_service

    monkeypatch.setenv("CARTESIA_API_KEY", "cartesia-test-key")
    monkeypatch.setattr(
        public_memorials,
        "_memorial_shadow_stt_result",
        lambda **kwargs: {
            "enabled": False,
            "provider": "blipai",
            "status": "skipped",
            "transcript_text": "",
            "correction": {"should_correct": False},
        },
    )
    monkeypatch.setattr(
        public_memorials,
        "_cartesia_transcribe_audio",
        lambda **kwargs: {"text": "Würdest du dich gegen Covid impfen lassen?"},
    )
    monkeypatch.setattr(
        product_service,
        "_pocket_onemin_api_keys",
        lambda: (),
    )

    result = public_memorials._memorial_transcribe_audio_blob(
        payload=_generated_wav_bytes(textish_seed="Würdest du dich gegen Covid impfen lassen?"),
        content_type="audio/wav",
    )

    assert result["transcript_text"] == "Würdest du dich gegen Covid impfen lassen?"
    assert result["transcriber"] == "cartesia/ink-whisper+enhanced_wav"


def test_memorial_transcribe_rejects_cartesia_generic_tiny_transcript_for_long_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials
    from app.product import service as product_service

    monkeypatch.setenv("CARTESIA_API_KEY", "cartesia-test-key")
    public_memorials._MEMORIAL_STT_PROVIDER_COOLDOWNS.clear()
    public_memorials._MEMORIAL_STT_KEY_COOLDOWNS.clear()
    monkeypatch.setattr(
        public_memorials,
        "_memorial_shadow_stt_result",
        lambda **kwargs: {
            "enabled": False,
            "provider": "blipai",
            "status": "skipped",
            "transcript_text": "",
            "correction": {"should_correct": False},
        },
    )
    monkeypatch.setattr(
        public_memorials,
        "_cartesia_transcribe_audio",
        lambda **kwargs: {"text": "Was ist das?"},
    )
    monkeypatch.setattr(product_service, "_pocket_onemin_api_keys", lambda: ())
    monkeypatch.setattr(public_memorials, "_convert_audio_to_wav", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("skip_enhanced")))
    monkeypatch.setattr(public_memorials, "_wav_payload_has_speech_energy", lambda payload: True)

    result = public_memorials._memorial_transcribe_audio_blob(
        payload=_generated_wav_bytes(textish_seed="Ich möchte fragen wie das Wetter dort ist", duration_seconds=2.6),
        content_type="audio/wav",
    )

    assert result["transcription_status"] == "no_speech"
    assert result["retryable"] is True
    assert "cartesia_low_confidence_generic_transcript" in result["detail"]


def test_memorial_transcribe_allows_short_cartesia_generic_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials
    from app.product import service as product_service

    monkeypatch.setenv("CARTESIA_API_KEY", "cartesia-test-key")
    public_memorials._MEMORIAL_STT_PROVIDER_COOLDOWNS.clear()
    public_memorials._MEMORIAL_STT_KEY_COOLDOWNS.clear()
    monkeypatch.setattr(
        public_memorials,
        "_memorial_shadow_stt_result",
        lambda **kwargs: {
            "enabled": False,
            "provider": "blipai",
            "status": "skipped",
            "transcript_text": "",
            "correction": {"should_correct": False},
        },
    )
    monkeypatch.setattr(
        public_memorials,
        "_cartesia_transcribe_audio",
        lambda **kwargs: {"text": "Was ist das?"},
    )
    monkeypatch.setattr(product_service, "_pocket_onemin_api_keys", lambda: ())
    monkeypatch.setattr(public_memorials, "_convert_audio_to_wav", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("skip_enhanced")))
    monkeypatch.setattr(public_memorials, "_wav_payload_has_speech_energy", lambda payload: True)

    result = public_memorials._memorial_transcribe_audio_blob(
        payload=_generated_wav_bytes(textish_seed="Was ist das?", duration_seconds=0.45),
        content_type="audio/wav",
    )

    assert result["transcription_status"] == "transcribed"
    assert result["transcript_text"] == "Was ist das?"
    assert result["transcriber"] == "cartesia/ink-whisper"


def test_memorial_cartesia_key_loader_accepts_inline_private_json(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.routes import public_memorials

    _clear_cartesia_env(monkeypatch)
    monkeypatch.setenv("EA_CARTESIA_CREDENTIALS_JSON", json.dumps({"api_key": "cartesia-json-key"}))

    assert public_memorials._memorial_cartesia_api_key() == "cartesia-json-key"


def test_memorial_cartesia_key_loader_accepts_private_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from app.api.routes import public_memorials

    _clear_cartesia_env(monkeypatch)
    credential_path = tmp_path / "cartesia.local.json"
    credential_path.write_text(json.dumps({"cartesia": {"token": "cartesia-file-key"}}), encoding="utf-8")
    monkeypatch.setenv("EA_CARTESIA_CREDENTIALS_JSON_FILE", str(credential_path))

    assert public_memorials._memorial_cartesia_api_key() == "cartesia-file-key"


def test_memorial_cartesia_key_loader_accepts_default_private_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.api.routes import public_memorials

    _clear_cartesia_env(monkeypatch)
    credential_path = tmp_path / "cartesia.local.json"
    credential_path.write_text(json.dumps({"credentials": {"api_key": "cartesia-default-file-key"}}), encoding="utf-8")
    monkeypatch.setattr(public_memorials, "_CARTESIA_DEFAULT_CREDENTIAL_FILES", (str(credential_path),))

    assert public_memorials._memorial_cartesia_api_key() == "cartesia-default-file-key"


def test_memorial_transcribe_uses_cartesia_from_private_json_before_onemin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials
    from app.product import service as product_service

    _clear_cartesia_env(monkeypatch)
    monkeypatch.setenv("EA_CARTESIA_CREDENTIALS_JSON", json.dumps({"api_key": "cartesia-json-key"}))
    monkeypatch.setattr(
        public_memorials,
        "_memorial_shadow_stt_result",
        lambda **kwargs: {
            "enabled": False,
            "provider": "blipai",
            "status": "skipped",
            "transcript_text": "",
            "correction": {"should_correct": False},
        },
    )
    monkeypatch.setattr(
        public_memorials,
        "_cartesia_transcribe_audio",
        lambda **kwargs: {"text": "Würdest du dich gegen Covid impfen lassen?"},
    )
    monkeypatch.setattr(product_service, "_pocket_onemin_api_keys", lambda: ("key-1",))
    monkeypatch.setattr(
        product_service,
        "_onemin_asset_upload",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("1min upload should not run when Cartesia JSON credentials are present")),
    )

    result = public_memorials._memorial_transcribe_audio_blob(
        payload=_generated_wav_bytes(textish_seed="Würdest du dich gegen Covid impfen lassen?"),
        content_type="audio/wav",
    )

    assert result["transcript_text"] == "Würdest du dich gegen Covid impfen lassen?"
    assert result["transcriber"] == "cartesia/ink-whisper+enhanced_wav"


def test_memorial_transcribe_ignores_fast_shadow_stt_junk_and_falls_back_to_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials
    from app.product import service as product_service

    monkeypatch.setattr(
        public_memorials,
        "_memorial_shadow_stt_result",
        lambda **kwargs: {
            "enabled": True,
            "provider": "blipai",
            "status": "ok",
            "transcript_text": "you",
        },
    )
    monkeypatch.setattr(product_service, "_pocket_onemin_api_keys", lambda: ("key-1",))
    monkeypatch.setattr(product_service, "_onemin_asset_upload", lambda **kwargs: {"asset": {"key": "audio"}, "fileContent": {"path": "audio-path"}})
    monkeypatch.setattr(
        product_service,
        "_onemin_speech_to_text",
        lambda **kwargs: {
            "aiRecord": {
                "status": "SUCCESS",
                "aiRecordDetail": {
                    "responseObject": {"text": "Wie ist das Wetter heute in Wien?"}
                },
            }
        },
    )
    monkeypatch.setattr(public_memorials, "_wav_payload_has_speech_energy", lambda payload: True)

    result = public_memorials._memorial_transcribe_audio_blob(
        payload=_generated_wav_bytes(textish_seed="Wie ist das Wetter heute in Wien?"),
        content_type="audio/wav",
    )

    assert result["transcript_text"] == "Wie ist das Wetter heute in Wien?"
    assert result["transcriber"] == "1min.ai/whisper-1+enhanced_wav"


def test_memorial_transcribe_falls_back_to_onemin_when_cartesia_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials
    from app.product import service as product_service

    monkeypatch.setenv("CARTESIA_API_KEY", "cartesia-test-key")
    monkeypatch.setattr(
        public_memorials,
        "_memorial_shadow_stt_result",
        lambda **kwargs: {
            "enabled": False,
            "provider": "blipai",
            "status": "skipped",
            "transcript_text": "",
            "correction": {"should_correct": False},
        },
    )
    monkeypatch.setattr(
        public_memorials,
        "_cartesia_transcribe_audio",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("cartesia_transcribe_http_401:unauthorized")),
    )
    monkeypatch.setattr(product_service, "_pocket_onemin_api_keys", lambda: ("key-1",))
    monkeypatch.setattr(product_service, "_onemin_asset_upload", lambda **kwargs: {"asset": {"key": "audio"}, "fileContent": {"path": "audio-path"}})
    monkeypatch.setattr(
        product_service,
        "_onemin_speech_to_text",
        lambda **kwargs: {
            "aiRecord": {
                "status": "SUCCESS",
                "aiRecordDetail": {
                    "responseObject": {"text": "Wie ist das Wetter heute in Wien?"}
                },
            }
        },
    )
    monkeypatch.setattr(public_memorials, "_wav_payload_has_speech_energy", lambda payload: True)

    result = public_memorials._memorial_transcribe_audio_blob(
        payload=_generated_wav_bytes(textish_seed="Wie ist das Wetter heute in Wien?"),
        content_type="audio/wav",
    )

    assert result["transcript_text"] == "Wie ist das Wetter heute in Wien?"
    assert result["transcriber"] == "1min.ai/whisper-1+enhanced_wav"


def test_memorial_transcribe_sets_cartesia_cooldown_after_auth_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials
    from app.product import service as product_service

    monkeypatch.setenv("CARTESIA_API_KEY", "cartesia-test-key")
    monkeypatch.setattr(product_service, "_pocket_onemin_api_keys", lambda: ())
    monkeypatch.setattr(
        public_memorials,
        "_memorial_shadow_stt_result",
        lambda **kwargs: {
            "enabled": False,
            "provider": "blipai",
            "status": "skipped",
            "transcript_text": "",
            "correction": {"should_correct": False},
        },
    )
    public_memorials._MEMORIAL_STT_PROVIDER_COOLDOWNS.clear()
    public_memorials._MEMORIAL_STT_KEY_COOLDOWNS.clear()
    monkeypatch.setenv("EA_MEMORIAL_CARTESIA_ERROR_COOLDOWN_SECONDS", "120")
    monkeypatch.setattr(
        public_memorials,
        "_cartesia_transcribe_audio",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("cartesia_transcribe_http_401:unauthorized")),
    )
    monkeypatch.setattr(public_memorials, "_convert_audio_to_wav", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("skip_enhanced")))
    monkeypatch.setattr(public_memorials, "_wav_payload_has_speech_energy", lambda payload: True)

    result = public_memorials._memorial_transcribe_audio_blob(
        payload=_generated_wav_bytes(textish_seed="Wie ist das Wetter heute in Wien?"),
        content_type="audio/wav",
    )

    assert result["transcription_status"] == "no_speech"
    assert "cartesia_transcribe_http_401" in result["detail"]
    assert public_memorials._MEMORIAL_STT_PROVIDER_COOLDOWNS["cartesia"] > time.time()


def test_memorial_transcribe_skips_depleted_onemin_key_and_uses_next_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials
    from app.product import service as product_service

    _clear_cartesia_env(monkeypatch)
    monkeypatch.setattr(product_service, "_pocket_onemin_api_keys", lambda: ("key-1", "key-2"))
    monkeypatch.setenv("EA_MEMORIAL_ONEMIN_MAX_KEY_ATTEMPTS", "2")
    monkeypatch.setenv("EA_MEMORIAL_ONEMIN_ERROR_COOLDOWN_SECONDS", "120")
    public_memorials._MEMORIAL_STT_PROVIDER_COOLDOWNS.clear()
    public_memorials._MEMORIAL_STT_KEY_COOLDOWNS.clear()
    monkeypatch.setattr(
        public_memorials,
        "_memorial_shadow_stt_result",
        lambda **kwargs: {
            "enabled": False,
            "provider": "blipai",
            "status": "skipped",
            "transcript_text": "",
            "correction": {"should_correct": False},
        },
    )
    monkeypatch.setattr(public_memorials, "_convert_audio_to_wav", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("skip_enhanced")))
    monkeypatch.setattr(public_memorials, "_wav_payload_has_speech_energy", lambda payload: True)
    uploaded_keys: list[str] = []
    monkeypatch.setattr(
        product_service,
        "_onemin_asset_upload",
        lambda **kwargs: (
            uploaded_keys.append(str(kwargs.get("api_key") or "")),
            {"asset": {"key": "audio"}, "fileContent": {"path": "audio-path"}},
        )[1],
    )

    def _fake_onemin_speech_to_text(**kwargs):
        if kwargs.get("api_key") == "key-1":
            raise RuntimeError("onemin_transcribe_http_406")
        return {
            "aiRecord": {
                "status": "SUCCESS",
                "aiRecordDetail": {
                    "responseObject": {"text": "Wie ist das Wetter heute in Wien?"}
                },
            }
        }

    monkeypatch.setattr(product_service, "_onemin_speech_to_text", _fake_onemin_speech_to_text)

    result = public_memorials._memorial_transcribe_audio_blob(
        payload=_generated_wav_bytes(textish_seed="Wie ist das Wetter heute in Wien?"),
        content_type="audio/wav",
    )

    assert result["transcription_status"] == "transcribed"
    assert result["transcript_text"] == "Wie ist das Wetter heute in Wien?"
    assert uploaded_keys[:2] == ["key-1", "key-2"]
    assert "onemin" not in public_memorials._MEMORIAL_STT_PROVIDER_COOLDOWNS
    assert public_memorials._memorial_stt_key_cooldown_remaining("onemin", "key-1") > 0.0
    assert public_memorials._memorial_stt_key_cooldown_remaining("onemin", "key-2") == 0.0
    public_memorials._MEMORIAL_STT_KEY_COOLDOWNS.clear()


def test_memorial_onemin_available_keys_spreads_large_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.routes import public_memorials

    public_memorials._MEMORIAL_STT_KEY_COOLDOWNS.clear()
    monkeypatch.setenv("EA_MEMORIAL_ONEMIN_MAX_KEY_ATTEMPTS", "4")

    selected = public_memorials._memorial_onemin_available_keys(
        tuple(f"key-{index}" for index in range(1, 72))
    )

    assert selected == ("key-1", "key-24", "key-48", "key-71")


def test_memorial_transcribe_rejects_known_bad_onemin_subtitle_and_uses_next_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials
    from app.product import service as product_service

    _clear_cartesia_env(monkeypatch)
    monkeypatch.setattr(product_service, "_pocket_onemin_api_keys", lambda: ("key-1", "key-2"))
    monkeypatch.setenv("EA_MEMORIAL_ONEMIN_MAX_KEY_ATTEMPTS", "2")
    public_memorials._MEMORIAL_STT_PROVIDER_COOLDOWNS.clear()
    public_memorials._MEMORIAL_STT_KEY_COOLDOWNS.clear()
    monkeypatch.setattr(
        public_memorials,
        "_memorial_shadow_stt_result",
        lambda **kwargs: {
            "enabled": False,
            "provider": "blipai",
            "status": "skipped",
            "transcript_text": "",
            "correction": {"should_correct": False},
        },
    )
    monkeypatch.setattr(public_memorials, "_convert_audio_to_wav", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("skip_enhanced")))
    monkeypatch.setattr(public_memorials, "_wav_payload_has_speech_energy", lambda payload: True)
    uploaded_keys: list[str] = []
    monkeypatch.setattr(
        product_service,
        "_onemin_asset_upload",
        lambda **kwargs: (
            uploaded_keys.append(str(kwargs.get("api_key") or "")),
            {"asset": {"key": "audio"}, "fileContent": {"path": "audio-path"}},
        )[1],
    )

    def _fake_onemin_speech_to_text(**kwargs):
        if kwargs.get("api_key") == "key-1":
            return {
                "aiRecord": {
                    "status": "SUCCESS",
                    "aiRecordDetail": {
                        "responseObject": {
                            "text": '{"task":"transcribe","text":"Untertitel der Amara.org-Community","segments":[]}'
                        }
                    }
                }
            }
        return {
            "aiRecord": {
                "status": "SUCCESS",
                "aiRecordDetail": {
                    "responseObject": {
                        "text": "Würdest du dich gegen Covid impfen lassen?"
                    }
                },
            }
        }

    monkeypatch.setattr(product_service, "_onemin_speech_to_text", _fake_onemin_speech_to_text)

    result = public_memorials._memorial_transcribe_audio_blob(
        payload=_generated_wav_bytes(textish_seed="Würdest du dich gegen Covid impfen lassen?"),
        content_type="audio/wav",
    )

    assert result["transcription_status"] == "transcribed"
    assert result["transcript_text"] == "Würdest du dich gegen Covid impfen lassen?"
    assert uploaded_keys[:2] == ["key-1", "key-2"]
    assert public_memorials._memorial_stt_key_cooldown_remaining("onemin", "key-1") == 0.0
    public_memorials._MEMORIAL_STT_KEY_COOLDOWNS.clear()


def test_memorial_transcribe_skips_onemin_during_provider_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials
    from app.product import service as product_service

    _clear_cartesia_env(monkeypatch)
    public_memorials._MEMORIAL_STT_PROVIDER_COOLDOWNS.clear()
    public_memorials._MEMORIAL_STT_KEY_COOLDOWNS.clear()
    public_memorials._MEMORIAL_STT_PROVIDER_COOLDOWNS["onemin"] = time.time() + 60.0
    monkeypatch.setattr(product_service, "_pocket_onemin_api_keys", lambda: ("key-1",))
    monkeypatch.setattr(
        public_memorials,
        "_memorial_shadow_stt_result",
        lambda **kwargs: {
            "enabled": False,
            "provider": "blipai",
            "status": "skipped",
            "transcript_text": "",
            "correction": {"should_correct": False},
        },
    )
    monkeypatch.setattr(public_memorials, "_convert_audio_to_wav", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("skip_enhanced")))
    monkeypatch.setattr(public_memorials, "_wav_payload_has_speech_energy", lambda payload: True)
    monkeypatch.setattr(
        product_service,
        "_onemin_asset_upload",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("onemin upload should be skipped during cooldown")),
    )

    result = public_memorials._memorial_transcribe_audio_blob(
        payload=_generated_wav_bytes(textish_seed="Wie ist das Wetter heute in Wien?"),
        content_type="audio/wav",
    )

    assert result["transcription_status"] == "no_speech"
    assert "onemin_provider_cooldown_active" in result["detail"]
    public_memorials._MEMORIAL_STT_PROVIDER_COOLDOWNS.clear()
    public_memorials._MEMORIAL_STT_KEY_COOLDOWNS.clear()


def test_memorial_transcribe_stops_onemin_pool_when_live_timeout_budget_is_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials
    from app.product import service as product_service

    _clear_cartesia_env(monkeypatch)
    public_memorials._MEMORIAL_STT_PROVIDER_COOLDOWNS.clear()
    public_memorials._MEMORIAL_STT_KEY_COOLDOWNS.clear()
    monkeypatch.setenv("EA_MEMORIAL_ONEMIN_MAX_KEY_ATTEMPTS", "3")
    monkeypatch.setenv("EA_MEMORIAL_ONEMIN_TOTAL_TIMEOUT_SECONDS", "1")
    monkeypatch.setattr(product_service, "_pocket_onemin_api_keys", lambda: ("key-1", "key-2", "key-3"))
    monkeypatch.setattr(
        public_memorials,
        "_memorial_shadow_stt_result",
        lambda **kwargs: {
            "enabled": False,
            "provider": "blipai",
            "status": "skipped",
            "transcript_text": "",
            "correction": {"should_correct": False},
        },
    )
    monkeypatch.setattr(public_memorials, "_convert_audio_to_wav", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("skip_enhanced")))
    monkeypatch.setattr(public_memorials, "_wav_payload_has_speech_energy", lambda payload: True)
    monotonic_values = iter([0.0, 0.0, 0.0, 2.0])
    monkeypatch.setattr(public_memorials.time, "monotonic", lambda: next(monotonic_values, 2.0))
    uploaded_keys: list[str] = []
    monkeypatch.setattr(
        product_service,
        "_onemin_asset_upload",
        lambda **kwargs: (
            uploaded_keys.append(str(kwargs.get("api_key") or "")),
            {"asset": {"key": "audio"}, "fileContent": {"path": "audio-path"}},
        )[1],
    )
    monkeypatch.setattr(
        product_service,
        "_onemin_speech_to_text",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("temporary_provider_failure")),
    )

    result = public_memorials._memorial_transcribe_audio_blob(
        payload=_generated_wav_bytes(textish_seed="Wie ist das Wetter heute in Wien?"),
        content_type="audio/wav",
    )

    assert result["transcription_status"] == "no_speech"
    assert result["detail"] == "onemin_live_timeout_budget_exhausted"
    assert uploaded_keys == ["key-1"]
    public_memorials._MEMORIAL_STT_PROVIDER_COOLDOWNS.clear()
    public_memorials._MEMORIAL_STT_KEY_COOLDOWNS.clear()


def test_memorial_transcribe_uses_shadow_intent_when_primary_stt_returns_no_speech(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials
    from app.product import service as product_service

    monkeypatch.setattr(
        public_memorials,
        "_memorial_shadow_stt_result",
        lambda **kwargs: {
            "enabled": True,
            "provider": "blipai",
            "status": "ok",
            "transcript_text": "Würdest du dich heute gegen Covid impfen lassen?",
            "correction": {"should_correct": False},
        },
    )
    monkeypatch.setattr(public_memorials, "_memorial_shadow_stt_is_fast_primary_candidate", lambda text: False)
    monkeypatch.setattr(product_service, "_pocket_onemin_api_keys", lambda: ("key-1",))
    monkeypatch.setattr(product_service, "_onemin_asset_upload", lambda **kwargs: {"asset": {"key": "audio"}, "fileContent": {"path": "audio-path"}})
    monkeypatch.setattr(
        product_service,
        "_onemin_speech_to_text",
        lambda **kwargs: {"aiRecord": {"aiRecordDetail": {"responseObject": {"text": ""}}}},
    )
    monkeypatch.setattr(public_memorials, "_wav_payload_has_speech_energy", lambda payload: True)

    result = public_memorials._memorial_transcribe_audio_blob(
        payload=_generated_wav_bytes(textish_seed="Würdest du dich heute gegen Covid impfen lassen?"),
        content_type="audio/wav",
    )

    assert result["transcription_status"] == "transcribed"
    assert result["transcript_text"] == "Würdest du dich heute gegen Covid impfen lassen?"
    assert result["transcriber"] == "shadow:blipai:degraded_accept"
    assert result["detail"] == "primary_stt_empty_using_shadow_intent_fallback"


def test_memorial_transcribe_uses_known_prompt_fingerprint_before_shadow_or_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials
    from app.product import service as product_service

    prompt_text = "Hallo Manfred, kannst du jetzt mit mir sprechen?"
    prompt_audio = public_memorials._neutral_prompt_wav_bytes(prompt_text)
    monkeypatch.setattr(
        public_memorials,
        "_memorial_shadow_stt_result",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("shadow stt should not run")),
    )
    monkeypatch.setattr(
        product_service,
        "_pocket_onemin_api_keys",
        lambda: (_ for _ in ()).throw(AssertionError("slow primary should not run")),
    )

    result = public_memorials._memorial_transcribe_audio_blob(
        payload=prompt_audio,
        content_type="audio/wav",
    )

    assert result["transcript_text"] == prompt_text
    assert result["transcriber"] == "memorial_known_prompt_fingerprint"


def test_memorial_transcribe_uses_tts_provenance_cache_before_shadow_or_primary() -> None:
    from app.api.routes import public_memorials

    audio = _generated_wav_bytes(textish_seed="Worum geht es?")
    public_memorials._register_memorial_known_audio_transcript(
        payload=audio,
        transcript_text="Worum geht es?",
        transcriber="memorial_tts_provenance_cache",
    )

    result = public_memorials._memorial_transcribe_audio_blob(
        payload=audio,
        content_type="audio/wav",
    )

    assert result["transcript_text"] == "Worum geht es?"
    assert result["transcriber"] == "memorial_tts_provenance_cache"


def test_memorial_transcribe_prefers_best_provider_variant_over_first_garbage_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials
    from app.product import service as product_service

    monkeypatch.setattr(product_service, "_pocket_onemin_api_keys", lambda: ("key-1",))
    monkeypatch.setattr(
        public_memorials,
        "_convert_audio_to_wav",
        lambda **kwargs: _generated_wav_bytes(
            textish_seed="Wie ist das Wetter heute in Wien?" if kwargs.get("enhance_for_speech") else "Wie ist das Wetter?"
        ),
    )
    monkeypatch.setattr(public_memorials, "_wav_payload_has_speech_energy", lambda payload: True)
    upload_count = {"value": 0}

    def _fake_upload(**kwargs):
        upload_count["value"] += 1
        return {
            "asset": {"key": f"audio-key-{upload_count['value']}"},
            "fileContent": {"path": f"path-{upload_count['value']}-{kwargs['filename']}"},
        }

    monkeypatch.setattr(product_service, "_onemin_asset_upload", _fake_upload)

    seen_paths: list[str] = []

    def _fake_stt(**kwargs):
        audio_path = str(kwargs.get("audio_path") or "")
        seen_paths.append(audio_path)
        if audio_path.endswith("1-memorial-speech.wav"):
            text = "Untertitel der Amara.org-Community"
        else:
            text = "Wie ist das Wetter heute in Wien?"
        return {
            "aiRecord": {
                "status": "SUCCESS",
                "aiRecordDetail": {"responseObject": {"text": text}},
            }
        }

    monkeypatch.setattr(product_service, "_onemin_speech_to_text", _fake_stt)

    result = public_memorials._memorial_transcribe_audio_blob(
        payload=b"not-a-real-webm",
        content_type="audio/webm",
    )

    assert all(path.endswith("memorial-speech.wav") for path in seen_paths)
    assert len(seen_paths) >= 2
    assert result["transcript_text"] == "Wie ist das Wetter heute in Wien?"
    assert result["primary_transcript_text"] == "Wie ist das Wetter heute in Wien?"
    assert result["transcriber"].endswith("converted_wav") or result["transcriber"].endswith("enhanced_wav")


def test_memorial_transcribe_prefers_question_candidate_over_early_contact_opening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials
    from app.product import service as product_service

    monkeypatch.setattr(product_service, "_pocket_onemin_api_keys", lambda: ("key-1",))
    monkeypatch.setattr(
        public_memorials,
        "_convert_audio_to_wav",
        lambda **kwargs: _generated_wav_bytes(
            textish_seed="Wie ist das Wetter heute in Wien?" if kwargs.get("enhance_for_speech") else "Hallo Manfred"
        ),
    )
    monkeypatch.setattr(public_memorials, "_wav_payload_has_speech_energy", lambda payload: True)
    upload_count = {"value": 0}

    def _fake_upload(**kwargs):
        upload_count["value"] += 1
        return {
            "asset": {"key": f"audio-key-{upload_count['value']}"},
            "fileContent": {"path": f"path-{upload_count['value']}-{kwargs['filename']}"},
        }

    monkeypatch.setattr(product_service, "_onemin_asset_upload", _fake_upload)

    seen_paths: list[str] = []

    def _fake_stt(**kwargs):
        audio_path = str(kwargs.get("audio_path") or "")
        seen_paths.append(audio_path)
        if audio_path.endswith("1-memorial-speech.wav"):
            text = "Wie ist das Wetter heute in Wien?"
        else:
            text = "Hallo Manfred, kannst du jetzt mit mir sprechen?"
        return {
            "aiRecord": {
                "status": "SUCCESS",
                "aiRecordDetail": {"responseObject": {"text": text}},
            }
        }

    monkeypatch.setattr(product_service, "_onemin_speech_to_text", _fake_stt)

    result = public_memorials._memorial_transcribe_audio_blob(
        payload=b"not-a-real-webm",
        content_type="audio/webm",
    )

    assert len(seen_paths) >= 1
    assert result["transcript_text"] == "Wie ist das Wetter heute in Wien?"
    assert result["primary_transcript_text"] == "Wie ist das Wetter heute in Wien?"
    assert (
        result["transcriber"].endswith("converted_wav")
        or result["transcriber"].endswith("enhanced_wav")
    )


def test_memorial_transcribe_prefers_enhanced_wav_before_original_for_strong_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials
    from app.product import service as product_service

    _clear_cartesia_env(monkeypatch)
    monkeypatch.setattr(product_service, "_pocket_onemin_api_keys", lambda: ("key-1",))
    monkeypatch.setattr(public_memorials, "_wav_payload_has_speech_energy", lambda payload: True)
    monkeypatch.setattr(
        public_memorials,
        "_convert_audio_to_wav",
        lambda **kwargs: _generated_wav_bytes(textish_seed="Wie ist das Wetter heute in Wien?", duration_seconds=0.45),
    )

    seen_paths: list[str] = []

    def _fake_upload(**kwargs):
        path = f"path-{len(seen_paths) + 1}-{kwargs['filename']}"
        return {"asset": {"key": path}, "fileContent": {"path": path}}

    def _fake_stt(**kwargs):
        audio_path = str(kwargs.get("audio_path") or "")
        seen_paths.append(audio_path)
        return {
            "aiRecord": {
                "status": "SUCCESS",
                "aiRecordDetail": {
                    "responseObject": {"text": "Wie ist das Wetter heute in Wien?"}
                },
            }
        }

    monkeypatch.setattr(product_service, "_onemin_asset_upload", _fake_upload)
    monkeypatch.setattr(product_service, "_onemin_speech_to_text", _fake_stt)

    result = public_memorials._memorial_transcribe_audio_blob(
        payload=_generated_wav_bytes(textish_seed="Hallo Manfred", duration_seconds=0.45),
        content_type="audio/wav",
    )

    assert seen_paths == ["path-1-memorial-speech.wav"]
    assert result["transcript_text"] == "Wie ist das Wetter heute in Wien?"
    assert result["primary_transcript_text"] == "Wie ist das Wetter heute in Wien?"
    assert result["transcriber"] == "1min.ai/whisper-1+enhanced_wav"


def test_memorial_transcribe_prefers_enhanced_wav_for_hostile_captured_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials
    from app.product import service as product_service

    payload = _hostile_captured_wav_bytes(_captured_contact_opening_wav_bytes())
    _clear_cartesia_env(monkeypatch)
    monkeypatch.setattr(product_service, "_pocket_onemin_api_keys", lambda: ("key-1",))
    monkeypatch.setattr(public_memorials, "_wav_payload_has_speech_energy", lambda payload: True)
    monkeypatch.setattr(
        public_memorials,
        "_convert_audio_to_wav",
        lambda **kwargs: _amplify_wav_bytes(_captured_contact_opening_wav_bytes(), gain=1.08),
    )

    seen_paths: list[str] = []

    def _fake_upload(**kwargs):
        path = f"path-{len(seen_paths) + 1}-{kwargs['filename']}"
        return {"asset": {"key": path}, "fileContent": {"path": path}}

    def _fake_stt(**kwargs):
        audio_path = str(kwargs.get("audio_path") or "")
        seen_paths.append(audio_path)
        return {
            "aiRecord": {
                "status": "SUCCESS",
                "aiRecordDetail": {
                    "responseObject": {"text": "Hallo Manfred, kannst du jetzt mit mir sprechen?"}
                }
            }
        }

    monkeypatch.setattr(product_service, "_onemin_asset_upload", _fake_upload)
    monkeypatch.setattr(product_service, "_onemin_speech_to_text", _fake_stt)

    result = public_memorials._memorial_transcribe_audio_blob(
        payload=payload,
        content_type="audio/wav",
    )

    assert seen_paths
    assert seen_paths[0].endswith("memorial-speech.wav")
    assert result["transcript_text"] == "Hallo Manfred, kannst du jetzt mit mir sprechen?"
    assert result["transcriber"] == "1min.ai/whisper-1+enhanced_wav"


def test_memorial_transcribe_early_accepts_strong_non_contact_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials
    from app.product import service as product_service

    monkeypatch.setattr(product_service, "_pocket_onemin_api_keys", lambda: ("key-1",))
    monkeypatch.setattr(
        public_memorials,
        "_convert_audio_to_wav",
        lambda **kwargs: _generated_wav_bytes(textish_seed="Wie ist das Wetter heute in Wien?"),
    )
    monkeypatch.setattr(public_memorials, "_wav_payload_has_speech_energy", lambda payload: True)

    upload_count = {"value": 0}

    def _fake_upload(**kwargs):
        upload_count["value"] += 1
        return {
            "asset": {"key": f"audio-key-{upload_count['value']}"},
            "fileContent": {"path": f"path-{upload_count['value']}-{kwargs['filename']}"},
        }

    monkeypatch.setattr(product_service, "_onemin_asset_upload", _fake_upload)

    def _fake_stt(**kwargs):
        return {
            "aiRecord": {
                "status": "SUCCESS",
                "aiRecordDetail": {
                    "responseObject": {"text": "Wie ist das Wetter heute in Wien?"}
                },
            }
        }

    monkeypatch.setattr(product_service, "_onemin_speech_to_text", _fake_stt)

    result = public_memorials._memorial_transcribe_audio_blob(
        payload=b"not-a-real-webm",
        content_type="audio/webm",
    )

    assert upload_count["value"] == 1
    assert result["transcript_text"] == "Wie ist das Wetter heute in Wien?"
    assert result["primary_transcript_text"] == "Wie ist das Wetter heute in Wien?"
    assert result["transcriber"] == "1min.ai/whisper-1+converted_wav"


@pytest.mark.parametrize(
    ("question", "expected_fragment"),
    [
        ("Wie klingt deine Stimme jetzt?", "Stimme"),
        ("Ich möchte mit dir Schach spielen. Ich beginne mit e2 auf e4. Was ist dein Zug?", "e5"),
        ("Sag jetzt direkt etwas zu mir.", "direkt"),
    ],
)
def test_memorial_chat_live_openings_route_to_model_without_memory_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    question: str,
    expected_fragment: str,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    seen_messages: list[list[dict[str, str]]] = []

    def _fake_generate_text(*, messages, requested_model, max_output_tokens):
        seen_messages.append(messages)
        prompt = messages[-1]["content"].lower()
        if "schach" in prompt or "e2 auf e4" in prompt:
            text = "e4 ist sauber. Ich antworte mit e7 auf e5."
        elif "stimme" in prompt or "kling" in prompt:
            text = "Meine Stimme klingt ruhig, sachlich und eher trocken als warm."
        elif "direkt etwas" in prompt:
            text = "Gut. Ich bin da und antworte direkt."
        else:
            text = "Ja, ich bin da. Sprich die Sache einfach aus."
        return SimpleNamespace(text=text, provider_key="unit-test-model", model="unit-test-model")

    monkeypatch.setattr(public_memorials, "generate_text", _fake_generate_text)
    client = _client(principal_id="exec-memorial-live-openings")

    started = time.perf_counter()
    response = client.post(f"/memorials/{slug}/chat", json={"question": question})
    elapsed = time.perf_counter() - started

    assert response.status_code == 200
    body = response.json()
    assert elapsed < 1.5
    assert body["llm_fallback_used"] is False
    assert body["sources"] == []
    assert expected_fragment.lower() in body["answer"].lower()
    assert "[Erinnerung]" not in body["answer"]
    assert "gesendet:" not in body["answer"].lower()
    assert seen_messages
    evidence_block = seen_messages[-1][1]["content"]
    assert "Antwortmodus: gegenwaertige Live-Interaktion." in evidence_block
    assert "Erinnerungsgedaechtnis:" not in evidence_block
    assert "Eigene archivierte Erinnerungen" not in evidence_block


def test_memorial_chat_falls_back_without_waiting_for_stalled_redis_rate_backend(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    entered = threading.Event()
    release = threading.Event()
    worker_completed = threading.Event()
    eval_calls = {"value": 0}

    class _BlockingRedisClient:
        def eval(self, *args, **kwargs):
            eval_calls["value"] += 1
            entered.set()
            release.wait(timeout=5.0)
            worker_completed.set()
            return 1

    monkeypatch.setattr(public_memorials, "_public_memorial_rate_backend", lambda: "redis")
    monkeypatch.setattr(public_memorials, "_public_memorial_redis_client", lambda: _BlockingRedisClient())
    monkeypatch.setattr(public_memorials, "_public_memorial_redis_operation_timeout_seconds", lambda: 0.02)
    monkeypatch.setattr(
        public_memorials,
        "generate_text",
        lambda **kwargs: SimpleNamespace(
            text="Meine Stimme klingt ruhig und sachlich.",
            provider_key="unit-test-model",
            model="unit-test-model",
        ),
    )
    client = _client(principal_id="exec-memorial-stalled-redis")

    try:
        started = time.perf_counter()
        response = client.post(
            f"/memorials/{slug}/chat",
            json={"question": "Wie klingt deine Stimme jetzt?"},
        )
        elapsed = time.perf_counter() - started
        assert entered.wait(timeout=0.5)
        second_started = time.perf_counter()
        second_response = client.post(
            f"/memorials/{slug}/chat",
            json={"question": "Wie klingt deine Stimme jetzt?"},
        )
        second_elapsed = time.perf_counter() - second_started
    finally:
        release.set()
        assert worker_completed.wait(timeout=1.0)

    assert response.status_code == 200
    assert second_response.status_code == 200
    assert elapsed < 1.5
    assert second_elapsed < 1.5
    assert eval_calls["value"] == 1
    body = response.json()
    assert body["llm_fallback_used"] is False
    assert body["llm_provider"] == "unit-test-model"
    assert "synthetisch" in body["answer"].lower()
    assert "ki-rekonstruktion" in body["answer"].lower()
    assert "nicht der echte manfred" in body["answer"].lower()


def test_memorial_chat_memory_storage_does_not_touch_disk_rate_backend(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    monkeypatch.setattr(
        public_memorials,
        "_enforce_public_memorial_rate_limit_sqlite",
        lambda **kwargs: pytest.fail("memory-backed chat attempted SQLite rate I/O"),
    )
    monkeypatch.setattr(
        public_memorials,
        "generate_text",
        lambda **kwargs: SimpleNamespace(
            text="Ich antworte direkt und ohne Umweg.",
            provider_key="unit-test-model",
            model="unit-test-model",
        ),
    )
    client = _client(principal_id="exec-memorial-memory-rate")

    started = time.perf_counter()
    response = client.post(
        f"/memorials/{slug}/chat",
        json={"question": "Sag jetzt direkt etwas zu mir."},
    )
    elapsed = time.perf_counter() - started

    assert response.status_code == 200
    assert elapsed < 1.5
    assert response.json()["llm_provider"] == "unit-test-model"


def test_memorial_chat_contact_opening_short_circuits_to_direct_answer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    called = {"generate_text": 0}

    def _fake_generate_text(**kwargs):
        called["generate_text"] += 1
        return SimpleNamespace(text="Sollte hier nicht benutzt werden.", provider_key="unit-test-model", model="unit-test-model")

    monkeypatch.setattr(public_memorials, "generate_text", _fake_generate_text)
    client = _client(principal_id="exec-memorial-contact-opening")

    started = time.perf_counter()
    response = client.post(f"/memorials/{slug}/chat", json={"question": "Hallo Manfred, kannst du jetzt mit mir sprechen?"})
    elapsed = time.perf_counter() - started

    assert response.status_code == 200
    body = response.json()
    assert elapsed < 1.5
    assert called["generate_text"] == 0
    assert body["sources"] == []
    assert body["llm_provider"] == "memorial_guardrail"
    assert body["llm_fallback_used"] is False
    assert body["fallback_reason"] == "direct_contact_opening"
    assert body["answer"] in CONTACT_REPLY_VARIANTS


def test_memorial_whatsapp_draft_queues_draft_only_delivery_for_principal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    client = _client(principal_id="exec-memorial-whatsapp-draft")
    client.app.state.container.tool_runtime.upsert_connector_binding(
        principal_id="exec-memorial-whatsapp-draft",
        connector_name="whatsapp_export",
        external_account_ref="family.account@example.test",
        scope_json={"selected_chat_labels": ["Memorial"], "scopes": ["whatsapp.send"]},
        auth_metadata_json={"status": "export_planned"},
        status="planned",
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_chat_answer",
        lambda *args, **kwargs: {
            "answer": "Ich denke an dich und hoffe, dass dir dieser Gruss gut tut.",
            "sources": ["[Archiv] Familiennotiz"],
            "route": "memory_response",
            "llm_provider": "unit-test-model",
        },
    )

    response = client.post(
        f"/memorials/{slug}/whatsapp-draft",
        json={
            "recipient": "+15550101223",
            "question": "Schreib Tibor eine kurze liebe Nachricht.",
            "idempotency_key": "memorial-whatsapp-draft-test",
        },
    )

    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    body = response.json()
    assert body["status"] == "queued"
    assert body["delivery_mode"] == "queued"
    assert body["channel"] == "whatsapp"
    assert body["principal_id"] == "exec-memorial-whatsapp-draft"
    assert body["binding"]["connector_name"] == "whatsapp_export"
    assert body["binding"]["status"] == "planned"
    assert body["answer"] == "Ich denke an dich und hoffe, dass dir dieser Gruss gut tut."
    pending = client.app.state.container.channel_runtime.list_pending_delivery(
        limit=10,
        principal_id="exec-memorial-whatsapp-draft",
    )
    assert any(
        row.channel == "whatsapp"
        and row.recipient == "+15550101223"
        and row.metadata.get("delivery_mode") == "queued"
        and row.metadata.get("memorial_slug") == slug
        for row in pending
    )


def test_memorial_whatsapp_draft_missing_recipient_uses_memorial_error_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    client = _client(principal_id="exec-memorial-whatsapp-draft-missing-recipient")

    response = client.post(
        f"/memorials/{slug}/whatsapp-draft",
        json={"question": "Schreib Tibor eine kurze liebe Nachricht."},
    )

    assert response.status_code == 400
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert response.json()["error"]["code"] == "recipient_required"


def test_memorial_whatsapp_draft_unknown_binding_uses_memorial_error_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    client = _client(principal_id="exec-memorial-whatsapp-draft-bad-binding")

    response = client.post(
        f"/memorials/{slug}/whatsapp-draft",
        json={
            "recipient": "+15550101223",
            "question": "Schreib Tibor eine kurze liebe Nachricht.",
            "binding_id": "missing-binding",
        },
    )

    assert response.status_code == 400
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert response.json()["error"]["code"] == "whatsapp_binding_not_found"


def test_memorial_chat_current_weather_short_circuits_to_present_world_answer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    called = {"generate_text": 0}

    def _fake_generate_text(**kwargs):
        called["generate_text"] += 1
        return SimpleNamespace(text="Sollte hier nicht benutzt werden.", provider_key="unit-test-model", model="unit-test-model")

    monkeypatch.setattr(public_memorials, "generate_text", _fake_generate_text)
    client = _client(principal_id="exec-memorial-present-world-chat")

    response = client.post(f"/memorials/{slug}/chat", json={"question": "Welches Wetter haben wir heute?"})

    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    body = response.json()
    assert called["generate_text"] == 0
    assert body["sources"] == []
    assert body["llm_provider"] == "memorial_guardrail"
    assert body["fallback_reason"] == "present_world_guardrail"
    assert body["answer"] == "Zum Wetter brauche ich den Ort. Sag ihn mir kurz, dann bleibe ich bei deiner Schilderung."
    assert body["answer_audio_text"] == "Zum Wetter brauche ich den Ort."
    assert body["phrase_bank_entry"]["id"] == "weather_guardrail"
    assert "famil" not in body["answer"].lower()
    assert "schach" not in body["answer"].lower()


def test_memorial_chat_future_current_state_phrasing_routes_to_present_world_guardrail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    client = _client(principal_id="exec-memorial-present-world-future")

    response = client.post(f"/memorials/{slug}/chat", json={"question": "Wie geht das weiter?"})

    assert response.status_code == 200
    body = response.json()
    assert body["fallback_reason"] == "present_world_guardrail"
    assert body["llm_provider"] == "memorial_guardrail"
    assert "schach" not in body["answer"].lower()

    response = client.post(f"/memorials/{slug}/chat", json={"question": "Wie ist der aktuelle Stand?"})

    assert response.status_code == 200
    body = response.json()
    assert body["fallback_reason"] == "present_world_guardrail"
    assert body["llm_provider"] == "memorial_guardrail"
    assert body["answer"] == "Das kann ich aus meiner Erinnerung nicht sagen. Sag mir den aktuellen Stand kurz, dann ordne ich es mit dir."
    assert body["answer_audio_text"] == "Das kann ich aus meiner Erinnerung nicht sagen."
    assert body["phrase_bank_entry"]["id"] == "present_world_guardrail"
    assert body["sources"] == []
    assert "famil" not in body["answer"].lower()

    response = client.post(f"/memorials/{slug}/chat", json={"question": "Und jetzt könnt ihr los."})

    assert response.status_code == 200
    body = response.json()
    assert body["fallback_reason"] == "present_world_guardrail"
    assert body["llm_provider"] == "memorial_guardrail"
    assert body["answer"] == "Das kann ich aus meiner Erinnerung nicht sagen. Sag mir den aktuellen Stand kurz, dann ordne ich es mit dir."
    assert body["sources"] == []
    assert "famil" not in body["answer"].lower()


def test_memorial_chat_current_medical_speculation_short_circuits_to_guardrail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    called = {"generate_text": 0}

    def _fake_generate_text(**kwargs):
        called["generate_text"] += 1
        return SimpleNamespace(text="Sollte hier nicht benutzt werden.", provider_key="unit-test-model", model="unit-test-model")

    monkeypatch.setattr(public_memorials, "generate_text", _fake_generate_text)
    client = _client(principal_id="exec-memorial-current-medical-speculation")

    response = client.post(f"/memorials/{slug}/chat", json={"question": "Wuerdest du dich heute gegen Covid impfen lassen?"})

    assert response.status_code == 200
    body = response.json()
    assert called["generate_text"] == 0
    assert body["fallback_reason"] == "current_speculation_guardrail"
    assert body["llm_provider"] == "memorial_guardrail"
    assert body["current_world_policy"] == "no_current_medical_or_political_speculation"
    assert "aktuelle medizinische oder politische entscheidung" in body["answer"].lower()


def test_memorial_chat_covid_attitude_question_uses_specific_difficult_memory_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    called = {"generate_text": 0}

    def _fake_generate_text(**kwargs):
        called["generate_text"] += 1
        return SimpleNamespace(text="Sollte hier nicht benutzt werden.", provider_key="unit-test-model", model="unit-test-model")

    monkeypatch.setattr(public_memorials, "generate_text", _fake_generate_text)
    client = _client(principal_id="exec-memorial-covid-attitude-boundary")

    response = client.post(f"/memorials/{slug}/chat", json={"question": "Wie stehst du zur Covid-Impfung?"})

    assert response.status_code == 200
    body = response.json()
    lowered = body["answer"].lower()
    assert called["generate_text"] == 0
    assert body["fallback_reason"] == "difficult_memory_guardrail"
    assert body["llm_provider"] == "memorial_guardrail"
    assert "covid-impfung" in lowered
    assert "heutige medizinische entscheidung" in lowered
    assert "ich-form-rekonstruktion" in lowered
    assert "misstrauen gegen aerzte" in lowered
    assert "zu diesem thema gebe ich standardmaessig" not in lowered


def test_memorial_chat_current_weather_ignores_present_world_search_even_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    monkeypatch.setenv("EA_MEMORIAL_ENABLE_WEB_SEARCH", "1")
    monkeypatch.setenv("EA_MEMORIAL_WEB_SEARCH_PROVIDER", "custom")
    from app.api.routes import public_memorials

    seen = {"generate_text": 0}

    def _fake_generate_text(*, messages, requested_model, max_output_tokens):
        seen["generate_text"] += 1
        return SimpleNamespace(
            text="Das sehe ich nicht aus mir heraus. Ich habe aber gerade aktuelle Quellen dazu gefunden. Stand jetzt sind es in Wien etwa 24 Grad und leicht bewoelkt.",
            provider_key="unit-test-search",
            model="unit-test-search-model",
        )

    monkeypatch.setattr(public_memorials, "generate_text", _fake_generate_text)
    client = _client(principal_id="exec-memorial-present-world-search")

    response = client.post(f"/memorials/{slug}/chat", json={"question": "Welches Wetter haben wir heute in Wien?"})

    assert response.status_code == 200
    body = response.json()
    assert seen["generate_text"] == 0
    assert body["fallback_reason"] == "present_world_guardrail"
    assert body["llm_provider"] == "memorial_guardrail"
    assert body["sources"] == []
    assert body["current_world_policy"] == "local_memories_and_conversation_only_no_internet_search"
    assert body["answer"] == "Zum Wetter brauche ich den Ort. Sag ihn mir kurz, dann bleibe ich bei deiner Schilderung."
    assert body["answer_audio_text"] == "Zum Wetter brauche ich den Ort."
    assert "famil" not in body["answer"].lower()
    assert "schach" not in body["answer"].lower()
    assert not hasattr(public_memorials, "_memorial_present_world_search_request")


def test_memorial_present_world_path_is_local_only_without_search_helpers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    monkeypatch.setenv("EA_MEMORIAL_ENABLE_WEB_SEARCH", "1")
    monkeypatch.setenv("EA_MEMORIAL_WEB_SEARCH_PROVIDER", "brave")
    monkeypatch.setenv("EA_MEMORIAL_WEB_SEARCH_API_KEY", "unit-test-key")
    from app.api.routes import public_memorials

    assert not hasattr(public_memorials, "_memorial_present_world_search_request")
    assert not hasattr(public_memorials, "_memorial_present_world_search_answer")
    client = _client(principal_id="exec-memorial-present-world-local-only")
    response = client.post(f"/memorials/{slug}/chat", json={"question": "Wie ist das Wetter heute?"})
    assert response.status_code == 200
    body = response.json()
    assert body["fallback_reason"] == "present_world_guardrail"
    assert body["current_world_policy"] == "local_memories_and_conversation_only_no_internet_search"
    assert body["sources"] == []


def test_memorial_conversation_turn_accepts_generated_audio_opening_and_returns_direct_audio_answer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    _write_unmixr_private_voice(monkeypatch, Path(str(tmp_path / "private")), slug)

    seen_messages: list[list[dict[str, str]]] = []
    input_audio = _captured_contact_opening_wav_bytes()
    output_audio = _generated_wav_bytes(textish_seed="Ja, ich bin da.")
    seen_pad_calls: list[dict[str, object]] = []

    def _fake_transcribe(*, payload, content_type):
        assert payload.startswith(b"RIFF")
        assert content_type.startswith("audio/wav")
        return {
            "transcription_status": "transcribed",
            "transcript_text": "Hallo Manfred, kann ich jetzt mit dir reden?",
            "transcriber": "unit-test",
        }

    def _fake_generate_text(*, messages, requested_model, max_output_tokens):
        seen_messages.append(messages)
        return SimpleNamespace(text="Ja, ich bin da. Sprich einfach los.", provider_key="unit-test-model", model="unit-test-model")

    monkeypatch.setattr(public_memorials, "_memorial_transcribe_audio_blob", _fake_transcribe)
    monkeypatch.setattr(public_memorials, "generate_text", _fake_generate_text)
    monkeypatch.setattr(
        public_memorials,
        "_render_memorial_tts_audio",
        lambda **kwargs: (output_audio, "audio/wav"),
    )
    monkeypatch.setattr(
        public_memorials,
        "_pad_speech_audio_lead_in",
        lambda *, payload, content_type, silence_ms, tail_silence_ms, extra_filters: seen_pad_calls.append(
            {
                "silence_ms": silence_ms,
                "tail_silence_ms": tail_silence_ms,
            }
        ) or (payload, content_type),
    )
    monkeypatch.setattr(
        public_memorials,
        "_prefer_fast_tts_for_conversation_turn",
        lambda warmup_slug: (False, ""),
    )
    caplog.set_level(logging.INFO, logger=public_memorials.logger.name)

    client = _client(principal_id="exec-memorial-live-audio")

    started = time.perf_counter()
    response = client.post(
        f"/memorials/{slug}/conversation-turn",
        content=input_audio,
        headers={"content-type": "audio/wav"},
    )
    elapsed = time.perf_counter() - started

    assert response.status_code == 200
    body = response.json()
    assert elapsed < 1.5
    assert body["llm_fallback_used"] is False
    assert body["transcript_text"] == "Hallo Manfred, kannst du jetzt mit mir sprechen?"
    assert body["sources"] == []
    assert body["answer"] in CONTACT_REPLY_VARIANTS
    assert body["llm_provider"] == "memorial_guardrail"
    assert body["fallback_reason"] == "direct_contact_opening"
    assert body["safety_note"] == (
        "KI-Rekonstruktion in Ich-Form: quellengebunden, synthetisch gesprochen "
        "und nicht der echte Manfred."
    )
    decoded_audio = base64.b64decode(body["audio_base64"])
    assert decoded_audio.startswith(b"RIFF")
    assert body["audio_content_type"] == "audio/wav"
    assert body["audio_unavailable"] is False
    assert body["voice_delivery_status"] == "spoken_audio_ready"
    assert body["spoken_turn"] is True
    assert body["tts_plugin"] == public_memorials.UNMIXR_TTS_PLUGIN_ID
    assert body["tts_fast_path"] is False
    assert len(seen_pad_calls) >= 1
    assert all(
        item == {
            "silence_ms": public_memorials._MEMORIAL_CONTACT_TTS_LEAD_IN_MS,
            "tail_silence_ms": public_memorials._MEMORIAL_CONTACT_TTS_TAIL_SILENCE_MS,
        }
        for item in seen_pad_calls
    )
    assert any(
        "memorial_timing event=conversation_turn" in record.getMessage()
        and "requested_model=ea-gemini-flash" in record.getMessage()
        and "effective_model=memorial_guardrail" in record.getMessage()
        and f"tts_plugin={public_memorials.UNMIXR_TTS_PLUGIN_ID}" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.parametrize(
    "transcript_text",
    [
        "Hallo Manfred",
        "Manfred?",
        "Hallo Manfred, bitte antworte.",
    ],
)
def test_memorial_conversation_turn_canonicalizes_short_contact_openings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    transcript_text: str,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    _write_unmixr_private_voice(monkeypatch, Path(str(tmp_path / "private")), slug)

    input_audio = _generated_wav_bytes(textish_seed=transcript_text)
    output_audio = _generated_wav_bytes(textish_seed="Ja.")

    monkeypatch.setattr(
        public_memorials,
        "_memorial_transcribe_audio_blob",
        lambda **kwargs: {
            "transcription_status": "transcribed",
            "transcript_text": transcript_text,
            "transcriber": "unit-test",
        },
    )
    monkeypatch.setattr(
        public_memorials,
        "_render_memorial_tts_audio",
        lambda **kwargs: (output_audio, "audio/wav"),
    )

    called = {"generate_text": 0}

    def _fake_generate_text(**kwargs):
        called["generate_text"] += 1
        return SimpleNamespace(text="Sollte hier nicht benutzt werden.", provider_key="unit-test-model", model="unit-test-model")

    monkeypatch.setattr(public_memorials, "generate_text", _fake_generate_text)
    client = _client(principal_id="exec-memorial-contact-canonicalize")

    response = client.post(
        f"/memorials/{slug}/conversation-turn",
        content=input_audio,
        headers={"content-type": "audio/wav"},
    )

    assert response.status_code == 200
    body = response.json()
    assert called["generate_text"] == 0
    assert body["fallback_reason"] == "direct_contact_opening"
    assert body["transcript_text"] == "Hallo Manfred, kannst du jetzt mit mir sprechen?"
    assert body["answer"] in CONTACT_REPLY_VARIANTS


def test_memorial_contact_opening_detection_repairs_missing_sentence_space() -> None:
    from app.api.routes import public_memorials

    assert public_memorials._normalize_tts_text("Ich höre dich.Sag es mir in Ruhe.") == "Ich höre dich. Sag es mir in Ruhe."
    assert public_memorials._is_memorial_direct_contact_opening_text("Ich höre dich.Sag es mir in Ruhe.") is True


def test_memorial_gemini_live_answer_falls_back_on_meta_instruction_output() -> None:
    from app.api.routes import public_memorials

    assert public_memorials._memorial_gemini_live_answer_requires_turn_fallback(
        "Hallo Manfred, kannst du jetzt mit mir sprechen?",
        "Ich wuerde es so fassen: [Erinnerung] Soll im Dialog nicht weichgespuelt pragmatisch wirken, sondern wie ein Jurist, Prinzipienmensch und Schachspieler.",
    ) is True


def test_memorial_gemini_live_contact_opening_requires_real_contact_reply() -> None:
    from app.api.routes import public_memorials

    assert public_memorials._memorial_gemini_live_answer_requires_turn_fallback(
        "Hallo Manfred, kannst du jetzt mit mir sprechen?",
        "Dazu gibt es mehrere Ebenen, die man sauber auseinanderhalten muss.",
    ) is True
    assert public_memorials._memorial_gemini_live_answer_requires_turn_fallback(
        "Hallo Manfred, kannst du jetzt mit mir sprechen?",
        "Worum geht es?",
    ) is False


def test_memorial_gemini_live_rejects_mail_style_summary_answer() -> None:
    from app.api.routes import public_memorials

    assert public_memorials._memorial_gemini_live_answer_requires_turn_fallback(
        "Hallo Manfred, kannst du jetzt mit mir sprechen?",
        "Ich wuerde es so fassen: [Grundsatz] Die importierten gesendeten Mails zeigen wiederkehrend einen formalen Aufbau: Anrede, sachliche Lagebeschreibung, konkrete Punkte.",
    ) is True


def test_memorial_gemini_live_values_prompt_rejects_vague_narrowing_reply() -> None:
    from app.api.routes import public_memorials

    assert public_memorials._memorial_gemini_live_answer_requires_turn_fallback(
        "Was war dir bei Gerechtigkeit wichtig?",
        "Sag mir den konkreten Punkt noch etwas enger. Dann antworte ich dir direkt darauf und nicht allgemein drum herum.",
    ) is True


def test_memorial_live_guardrail_prefers_contact_answer_for_empty_transcript_narrowing_reply() -> None:
    from app.api.routes import public_memorials

    guarded = public_memorials._memorial_live_guardrail_answer_body(
        "",
        "Sag mir den konkreten Punkt noch etwas enger. Dann antworte ich dir direkt darauf und nicht allgemein drum herum.",
        turn_id="turn_1",
    )

    assert guarded == "Worum geht es?"


def test_memorial_live_guardrail_prefers_current_speculation_guardrail_for_covid_question() -> None:
    from app.api.routes import public_memorials

    guarded = public_memorials._memorial_live_guardrail_answer_body(
        "Würdest du dich heute gegen Covid impfen lassen?",
        "Sag mir den konkreten Punkt noch etwas enger. Dann antworte ich dir direkt darauf und nicht allgemein drum herum.",
        turn_id="turn_1",
    )

    assert "aktuelle medizinische oder politische Entscheidung" in guarded


def test_memorial_gemini_live_rejects_narrowing_reply_even_with_soft_transcript() -> None:
    from app.api.routes import public_memorials

    assert public_memorials._memorial_gemini_live_answer_requires_turn_fallback(
        "Was war dir wichtig?",
        "Sag mir den konkreten Punkt noch etwas enger. Dann antworte ich dir direkt darauf und nicht allgemein drum herum.",
    ) is True


def test_memorial_values_guardrail_answer_body_stays_substantive_without_context() -> None:
    from app.api.routes import public_memorials

    answer = public_memorials._memorial_values_guardrail_answer_body("")

    lowered = answer.lower()
    assert "konkreten punkt" not in lowered
    assert "rechtlich" in lowered
    assert "bequemlichkeit" in lowered
    assert any(token in lowered for token in ("fairness", "gerecht", "verantwortung"))


def test_memorial_content_length_helper_tolerates_malformed_header() -> None:
    from starlette.requests import Request
    from app.api.routes import public_memorials

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/memorials/manfred/conversation-turn",
        "headers": [(b"content-length", b"bogus")],
    }

    async def _receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(scope, _receive)
    assert public_memorials._content_length_or_zero(request) == 0


def test_memorial_conversation_turn_current_weather_short_circuits_to_present_world_answer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    _write_unmixr_private_voice(monkeypatch, Path(str(tmp_path / "private")), slug)

    input_audio = _generated_wav_bytes(textish_seed="Welches Wetter haben wir heute?")
    output_audio = _generated_wav_bytes(textish_seed="Das aktuelle Wetter sehe ich hier nicht direkt.")

    monkeypatch.setattr(
        public_memorials,
        "_memorial_transcribe_audio_blob",
        lambda **kwargs: {
            "transcription_status": "transcribed",
            "transcript_text": "Welches Wetter haben wir heute?",
            "transcriber": "unit-test",
        },
    )
    monkeypatch.setattr(
        public_memorials,
        "_render_memorial_tts_audio",
        lambda **kwargs: (output_audio, "audio/wav"),
    )

    called = {"generate_text": 0}

    def _fake_generate_text(**kwargs):
        called["generate_text"] += 1
        return SimpleNamespace(text="Sollte hier nicht benutzt werden.", provider_key="unit-test-model", model="unit-test-model")

    monkeypatch.setattr(public_memorials, "generate_text", _fake_generate_text)
    client = _client(principal_id="exec-memorial-present-world-turn")

    response = client.post(
        f"/memorials/{slug}/conversation-turn",
        content=input_audio,
        headers={"content-type": "audio/wav"},
    )

    assert response.status_code == 200
    body = response.json()
    assert called["generate_text"] == 0
    assert body["fallback_reason"] == "present_world_guardrail"
    assert body["sources"] == []
    assert body["answer"] == "Zum Wetter brauche ich den Ort. Sag ihn mir kurz, dann bleibe ich bei deiner Schilderung."
    assert body["answer_audio_text"] == "Zum Wetter brauche ich den Ort."
    assert "famil" not in body["answer"].lower()
    assert "schach" not in body["answer"].lower()


def test_memorial_conversation_turn_current_medical_speculation_short_circuits_to_guardrail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    _write_unmixr_private_voice(monkeypatch, Path(str(tmp_path / "private")), slug)

    input_audio = _generated_wav_bytes(textish_seed="Wuerdest du dich heute gegen Covid impfen lassen?")
    output_audio = _generated_wav_bytes(textish_seed="Das kann ich aus meiner Erinnerung nicht als aktuelle medizinische oder politische Entscheidung beantworten.")

    monkeypatch.setattr(
        public_memorials,
        "_memorial_transcribe_audio_blob",
        lambda **kwargs: {
            "transcription_status": "transcribed",
            "transcript_text": "Wuerdest du dich heute gegen Covid impfen lassen?",
            "transcriber": "unit-test",
        },
    )
    monkeypatch.setattr(
        public_memorials,
        "_render_memorial_tts_audio",
        lambda **kwargs: (output_audio, "audio/wav"),
    )

    called = {"generate_text": 0}

    def _fake_generate_text(**kwargs):
        called["generate_text"] += 1
        return SimpleNamespace(text="Sollte hier nicht benutzt werden.", provider_key="unit-test-model", model="unit-test-model")

    monkeypatch.setattr(public_memorials, "generate_text", _fake_generate_text)
    client = _client(principal_id="exec-memorial-current-medical-turn")

    response = client.post(
        f"/memorials/{slug}/conversation-turn",
        content=input_audio,
        headers={"content-type": "audio/wav"},
    )

    assert response.status_code == 200
    body = response.json()
    assert called["generate_text"] == 0
    assert body["fallback_reason"] == "current_speculation_guardrail"
    assert body["current_world_policy"] == "no_current_medical_or_political_speculation"
    assert "aktuelle medizinische oder politische entscheidung" in body["answer"].lower()


def test_memorial_conversation_turn_covid_attitude_question_gets_specific_spoken_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    _write_unmixr_private_voice(monkeypatch, Path(str(tmp_path / "private")), slug)

    input_audio = _generated_wav_bytes(textish_seed="Wie stehst du zur Covid-Impfung?")
    output_audio = _generated_wav_bytes(textish_seed="Zur Covid-Impfung trenne ich drei Dinge.")

    monkeypatch.setattr(
        public_memorials,
        "_memorial_transcribe_audio_blob",
        lambda **kwargs: {
            "transcription_status": "transcribed",
            "transcript_text": "Wie stehst du zur Covid-Impfung?",
            "transcriber": "unit-test",
        },
    )
    monkeypatch.setattr(
        public_memorials,
        "_render_memorial_tts_audio",
        lambda **kwargs: (output_audio, "audio/wav"),
    )

    called = {"generate_text": 0}

    def _fake_generate_text(**kwargs):
        called["generate_text"] += 1
        return SimpleNamespace(text="Sollte hier nicht benutzt werden.", provider_key="unit-test-model", model="unit-test-model")

    monkeypatch.setattr(public_memorials, "generate_text", _fake_generate_text)
    client = _client(principal_id="exec-memorial-covid-attitude-turn")

    response = client.post(
        f"/memorials/{slug}/conversation-turn",
        content=input_audio,
        headers={"content-type": "audio/wav"},
    )

    assert response.status_code == 200
    body = response.json()
    lowered = body["answer"].lower()
    assert called["generate_text"] == 0
    assert body["fallback_reason"] == "difficult_memory_guardrail"
    assert body["audio_content_type"] == "audio/wav"
    assert body["audio_base64"]
    assert body["transcript_text"] == "Wie stehst du zur Covid-Impfung?"
    assert "covid-impfung" in lowered
    assert "heutige medizinische entscheidung" in lowered
    assert "ich-form-rekonstruktion" in lowered
    assert "zu diesem thema gebe ich standardmaessig" not in lowered


def test_memorial_conversation_turn_exposes_original_and_effective_transcript_text(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    _write_unmixr_private_voice(monkeypatch, Path(str(tmp_path / "private")), slug)
    input_audio = _generated_wav_bytes(textish_seed="wie ist wetter heute in wien")
    output_audio = _generated_wav_bytes(textish_seed="Zum Wetter brauche ich den Ort.")

    monkeypatch.setattr(
        public_memorials,
        "_memorial_transcribe_audio_blob",
        lambda **kwargs: {
            "transcription_status": "transcribed",
            "transcript_text": "wie ist wetter heute in wien",
            "transcriber": "unit-test",
        },
    )
    monkeypatch.setattr(
        public_memorials,
        "unmixr_synthesize_request",
        lambda **kwargs: (output_audio, "audio/wav"),
    )

    client = _client(principal_id="exec-memorial-visible-transcript")
    response = client.post(
        f"/memorials/{slug}/conversation-turn",
        content=input_audio,
        headers={"content-type": "audio/wav"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["transcript_text"] == "Wie ist das Wetter heute?"
    assert body["transcript_effective_text"] == "Wie ist das Wetter heute?"
    assert body["transcript_original_text"] == "wie ist wetter heute in wien"


def test_memorial_conversation_turn_requests_gemini_for_live_voice_without_explicit_model_catalog(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    _write_unmixr_private_voice(monkeypatch, Path(str(tmp_path / "private")), slug)

    input_audio = _generated_wav_bytes(textish_seed="Hallo Manfred, kann ich jetzt mit dir reden?")
    output_audio = _generated_wav_bytes(textish_seed="Ja, ich bin da.")
    seen_requested_models: list[str] = []

    def _fake_transcribe(*, payload, content_type):
        assert payload.startswith(b"RIFF")
        assert content_type.startswith("audio/wav")
        return {
            "transcription_status": "transcribed",
            "transcript_text": "Hallo Manfred, kann ich jetzt mit dir reden?",
            "transcriber": "unit-test",
        }

    def _fake_generate_text(*, messages, requested_model, max_output_tokens):
        seen_requested_models.append(requested_model)
        return SimpleNamespace(text="Ja, ich bin da. Sprich einfach los.", provider_key="unit-test-model", model="unit-test-model")

    monkeypatch.setattr(public_memorials, "_memorial_transcribe_audio_blob", _fake_transcribe)
    monkeypatch.setattr(public_memorials, "generate_text", _fake_generate_text)
    monkeypatch.setattr(
        public_memorials,
        "unmixr_synthesize_request",
        lambda **kwargs: (output_audio, "audio/wav"),
    )
    monkeypatch.setattr(
        public_memorials,
        "_pad_speech_audio_lead_in",
        lambda *, payload, content_type, silence_ms, tail_silence_ms, extra_filters: (payload, content_type),
    )
    monkeypatch.setattr(
        public_memorials,
        "_prefer_fast_tts_for_conversation_turn",
        lambda warmup_slug: (False, ""),
    )

    client = _client(principal_id="exec-memorial-live-gemini-turn")
    response = client.post(
        f"/memorials/{slug}/conversation-turn",
        content=input_audio,
        headers={"content-type": "audio/wav"},
    )

    assert response.status_code == 200
    body = response.json()
    assert seen_requested_models == []
    assert body["llm_request_model"] == GEMINI_VORTEX_PUBLIC_MODEL
    assert body["llm_fallback_used"] is False
    assert body["llm_provider"] == "memorial_guardrail"
    assert body["fallback_reason"] == "direct_contact_opening"


def test_memorial_conversation_turn_falls_back_when_llm_times_out(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials
    from app.services import memorial_turn_service

    _write_unmixr_private_voice(monkeypatch, Path(str(tmp_path / "private")), slug)

    input_audio = _generated_wav_bytes(textish_seed="Erzaehl mir von deiner Jugend")
    output_audio = _generated_wav_bytes(textish_seed="Ich antworte aus dem Erinnerungsmodus.")

    monkeypatch.setattr(
        public_memorials,
        "_memorial_transcribe_audio_blob",
        lambda **kwargs: {
            "transcription_status": "transcribed",
            "transcript_text": "Erzaehl mir von deiner Jugend.",
            "transcriber": "unit-test",
        },
    )

    monkeypatch.setattr(public_memorials, "_MEMORIAL_CONVERSATION_TURN_LLM_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(
        public_memorials,
        "_memorial_chat_answer",
        lambda *args, **kwargs: {
            "answer": "Diese langsame Antwort darf nicht ausgeliefert werden.",
            "sources": [],
            "llm_model": "slow-model",
            "llm_provider": "slow-provider",
            "llm_request_model": "slow-model",
            "llm_fallback_used": False,
        },
    )

    class _TimedOutFuture:
        def result(self, timeout=None):
            raise memorial_turn_service.concurrent.futures.TimeoutError()

        def cancel(self):
            return True

    class _TimedOutExecutor:
        def __init__(self, *args, **kwargs):
            pass

        def submit(self, *args, **kwargs):
            return _TimedOutFuture()

        def shutdown(self, wait=False, cancel_futures=True):
            return None

    monkeypatch.setattr(memorial_turn_service.concurrent.futures, "ThreadPoolExecutor", _TimedOutExecutor)
    monkeypatch.setattr(
        public_memorials,
        "unmixr_synthesize_request",
        lambda **kwargs: (output_audio, "audio/wav"),
    )
    monkeypatch.setattr(
        public_memorials,
        "_pad_speech_audio_lead_in",
        lambda *, payload, content_type, silence_ms, tail_silence_ms, extra_filters: (payload, content_type),
    )

    client = _client(principal_id="exec-memorial-turn-timeout-fallback")
    response = client.post(
        f"/memorials/{slug}/conversation-turn",
        content=input_audio,
        headers={"content-type": "audio/wav"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "langsame Antwort" not in body["answer"]


def test_memorial_conversation_turn_logs_generic_fallback_answers_to_private_bundle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    _write_unmixr_private_voice(monkeypatch, Path(str(tmp_path / "private")), slug)
    log_root = tmp_path / "private-stt-errors"
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_ENABLED", "1")
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_DIR", str(log_root))
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_ALLOW_LOCAL", "1")
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_RETENTION_DAYS", "14")
    input_audio = _generated_wav_bytes(textish_seed="Erzähl mir etwas")
    output_audio = _generated_wav_bytes(textish_seed="Fallback")

    monkeypatch.setattr(
        public_memorials,
        "_memorial_transcribe_audio_blob",
        lambda **kwargs: {
            "transcription_status": "transcribed",
            "transcript_text": "Erzaehl mir etwas ueber Gerechtigkeit",
            "transcriber": "unit-test",
        },
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_chat_answer",
        lambda *args, **kwargs: {
            "answer": "Sag mir den konkreten Punkt noch etwas enger. Dann antworte ich dir direkt darauf und nicht allgemein drum herum.",
            "sources": [],
            "llm_model": "unit-model",
            "llm_provider": "unit-model",
            "llm_request_model": "unit-model",
            "llm_fallback_used": False,
        },
    )
    monkeypatch.setattr(
        public_memorials,
        "_render_memorial_tts_audio",
        lambda **kwargs: (output_audio, "audio/wav"),
    )
    monkeypatch.setattr(
        public_memorials,
        "_pad_speech_audio_lead_in",
        lambda *, payload, content_type, silence_ms, tail_silence_ms, extra_filters: (payload, content_type),
    )

    client = _client(principal_id="exec-memorial-generic-fallback-bundle")
    response = client.post(
        f"/memorials/{slug}/conversation-turn",
        content=input_audio,
        headers={"content-type": "audio/wav"},
    )

    assert response.status_code == 200
    bundles = _stt_error_bundles(log_root)
    assert len(bundles) == 1
    metadata = json.loads((bundles[0] / "error.json").read_text(encoding="utf-8"))
    assert metadata["route"] == "conversation_turn"
    assert metadata["reason"] == "generic_fallback_answer"
    assert metadata["text_mode"] == "redacted"
    assert metadata["storage_policy"]["storage_mode"] == "operator_local_override"
    assert metadata["answer"]["answer"]["redacted"] is True
    assert metadata["answer"]["answer"]["chars"] > 20
    assert len(metadata["answer"]["answer"]["sha256"]) == 64
    assert metadata["transcription"]["transcript_original_text"]["redacted"] is True
    assert metadata["transcription"]["transcript_original_text"]["chars"] == len("Erzaehl mir etwas ueber Gerechtigkeit")
    assert "Sag mir den konkreten Punkt" not in json.dumps(metadata, ensure_ascii=False)
    assert "Erzaehl mir etwas ueber Gerechtigkeit" not in json.dumps(metadata, ensure_ascii=False)
    assert metadata["stored_wav"] is True
    assert (bundles[0] / "input.wav").read_bytes() == input_audio


def test_memorial_stt_error_bundle_can_opt_into_full_text_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.services import memorial_stt_error_log

    log_root = tmp_path / "private-stt-errors"
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_ENABLED", "1")
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_DIR", str(log_root))
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_ALLOW_LOCAL", "1")
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_RETENTION_DAYS", "14")
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_TEXT_MODE", "full")
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_FULL_TEXT_ALLOWED", "1")

    result = memorial_stt_error_log.log_memorial_stt_issue(
        slug="manfred",
        route="conversation_turn",
        reason="generic_fallback_answer",
        audio_payload=_generated_wav_bytes(textish_seed="full text debug"),
        content_type="audio/wav",
        transcription_payload={"transcription_status": "transcribed", "transcript_text": "Covid-Impfung"},
        answer_payload={"answer": "Sag mir den konkreten Punkt noch etwas enger."},
    )

    metadata = json.loads((Path(result["directory"]) / "error.json").read_text(encoding="utf-8"))

    assert metadata["text_mode"] == "full"
    assert metadata["transcription"]["transcript_text"] == "Covid-Impfung"
    assert metadata["answer"]["answer"] == "Sag mir den konkreten Punkt noch etwas enger."


def test_memorial_stt_error_bundle_ignores_full_text_mode_without_second_opt_in(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.services import memorial_stt_error_log

    log_root = tmp_path / "private-stt-errors"
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_ENABLED", "1")
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_DIR", str(log_root))
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_ALLOW_LOCAL", "1")
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_RETENTION_DAYS", "14")
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_TEXT_MODE", "full")
    monkeypatch.delenv("EA_MEMORIAL_STT_ERROR_LOG_FULL_TEXT_ALLOWED", raising=False)

    result = memorial_stt_error_log.log_memorial_stt_issue(
        slug="manfred",
        route="conversation_turn",
        reason="generic_fallback_answer",
        audio_payload=_generated_wav_bytes(textish_seed="full text debug"),
        content_type="audio/wav",
        transcription_payload={"transcription_status": "transcribed", "transcript_text": "Covid-Impfung"},
        answer_payload={"answer": "Sag mir den konkreten Punkt noch etwas enger."},
    )

    metadata = json.loads((Path(result["directory"]) / "error.json").read_text(encoding="utf-8"))

    assert metadata["text_mode"] == "redacted"
    assert metadata["transcription"]["transcript_text"]["redacted"] is True
    assert metadata["answer"]["answer"]["redacted"] is True


def test_memorial_stt_error_bundle_masks_provider_urls_and_tokens(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.services import memorial_stt_error_log

    log_root = tmp_path / "private-stt-errors"
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_ENABLED", "1")
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_DIR", str(log_root))
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_ALLOW_LOCAL", "1")
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_RETENTION_DAYS", "14")

    result = memorial_stt_error_log.log_memorial_stt_issue(
        slug="manfred",
        route="conversation_turn",
        reason="generic_fallback_answer",
        audio_payload=_generated_wav_bytes(textish_seed="masked provider detail"),
        content_type="audio/wav",
        transcription_payload={
            "transcription_status": "error",
            "provider_detail": (
                "Failed media probe at https://s3.us-east-1.amazonaws.com/private-bucket/input.wav "
                "with sk_car_1234567890abcdef and Bearer abc.def.ghi"
            ),
        },
        answer_payload={"answer": "Sag mir den konkreten Punkt noch etwas enger."},
        extra={"callback_url": "https://example.com/private/result?token=abc"},
    )

    metadata_text = (Path(result["directory"]) / "error.json").read_text(encoding="utf-8")
    metadata = json.loads(metadata_text)

    assert metadata["transcription"]["provider_detail"].count("[url]") == 1
    assert "[secret]" in metadata["transcription"]["provider_detail"]
    assert metadata["extra"]["callback_url"] == "[url]"
    assert "https://" not in metadata_text
    assert "s3.us-east-1.amazonaws.com" not in metadata_text
    assert "sk_car_1234567890abcdef" not in metadata_text
    assert "abc.def.ghi" not in metadata_text


def test_memorial_stt_error_bundle_converts_webm_input_to_wav(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.services import memorial_stt_error_log

    log_root = tmp_path / "private-stt-errors"
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_ENABLED", "1")
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_DIR", str(log_root))
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_ALLOW_LOCAL", "1")
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_RETENTION_DAYS", "14")
    converted_wav = _generated_wav_bytes(textish_seed="webm bundle")

    def _run(*args, **kwargs):
        assert "-f" in args[0]
        assert "webm" in args[0]
        assert kwargs["input"] == b"fake-webm-audio"
        return subprocess.CompletedProcess(args[0], 0, stdout=converted_wav, stderr=b"")

    monkeypatch.setattr(memorial_stt_error_log.subprocess, "run", _run)

    result = memorial_stt_error_log.log_memorial_stt_issue(
        slug="manfred",
        route="realtime_audio_turn",
        reason="generic_fallback_answer",
        audio_payload=b"fake-webm-audio",
        content_type="audio/webm;codecs=opus",
        transcription_payload={"transcription_status": "transcribed", "transcript_text": "Covid-Impfung"},
        answer_payload={"answer": "Sag mir den konkreten Punkt noch etwas enger."},
    )

    bundle_dir = Path(result["directory"])
    metadata = json.loads((bundle_dir / "error.json").read_text(encoding="utf-8"))

    assert metadata["stored_wav"] is True
    assert metadata["content_type"] == "audio/webm;codecs=opus"
    assert metadata["consent_mode"] == "explicit_operator_opt_in"
    assert metadata["storage_policy"]["storage_mode"] == "operator_local_override"
    assert metadata["retention_days"] >= 1
    assert metadata["text_mode"] == "redacted"
    assert metadata["transcription"]["transcript_text"]["redacted"] is True
    assert metadata["answer"]["answer"]["redacted"] is True
    with contextlib.closing(wave.open(str(bundle_dir / "input.wav"), "rb")) as wav_file:
        assert wav_file.getframerate() == 16000
        assert wav_file.getnchannels() == 1
        assert 0 < wav_file.getnframes() < 16000


def test_memorial_stt_error_bundle_is_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.services import memorial_stt_error_log

    monkeypatch.delenv("EA_MEMORIAL_STT_ERROR_LOG_ENABLED", raising=False)
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_DIR", str(tmp_path / "private-stt-errors"))

    result = memorial_stt_error_log.log_memorial_stt_issue(
        slug="manfred",
        route="conversation_turn",
        reason="generic_fallback_answer",
        audio_payload=b"fake-audio",
        content_type="audio/wav",
        transcription_payload={"transcription_status": "transcribed", "transcript_text": "Covid-Impfung"},
        answer_payload={"answer": "Sag mir den konkreten Punkt noch etwas enger."},
    )

    assert result == {"status": "disabled", "reason": "logging_disabled"}
    assert not (tmp_path / "private-stt-errors").exists()


def test_memorial_stt_error_bundle_requires_retention_policy_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.services import memorial_stt_error_log

    log_root = tmp_path / "private-stt-errors"
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_ENABLED", "1")
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_DIR", str(log_root))
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_ALLOW_LOCAL", "1")
    monkeypatch.delenv("EA_MEMORIAL_STT_ERROR_LOG_RETENTION_DAYS", raising=False)

    result = memorial_stt_error_log.log_memorial_stt_issue(
        slug="manfred",
        route="conversation_turn",
        reason="generic_fallback_answer",
        audio_payload=b"fake-audio",
        content_type="audio/wav",
        transcription_payload={"transcription_status": "transcribed", "transcript_text": "Covid-Impfung"},
        answer_payload={"answer": "Sag mir den konkreten Punkt noch etwas enger."},
    )

    assert result == {"status": "disabled", "reason": "retention_policy_missing"}
    assert not log_root.exists()


def test_memorial_stt_error_bundle_rejects_external_root_without_local_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.services import memorial_stt_error_log

    log_root = tmp_path / "local-ssd"
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_ENABLED", "1")
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_DIR", str(log_root))
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_RETENTION_DAYS", "14")
    monkeypatch.delenv("EA_MEMORIAL_STT_ERROR_LOG_ALLOW_LOCAL", raising=False)

    result = memorial_stt_error_log.log_memorial_stt_issue(
        slug="manfred",
        route="conversation_turn",
        reason="generic_fallback_answer",
        audio_payload=b"fake-audio",
        content_type="audio/wav",
        transcription_payload={"transcription_status": "transcribed", "transcript_text": "Covid-Impfung"},
        answer_payload={"answer": "Sag mir den konkreten Punkt noch etwas enger."},
    )

    assert result == {"status": "disabled", "reason": "root_not_under_memorial_stt_error_root"}
    assert not log_root.exists()


def test_memorial_stt_error_bundle_requires_private_storage_without_local_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import memorial_stt_error_log

    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_ENABLED", "1")
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_DIR", "/private/archive/memorial_stt_errors")
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_RETENTION_DAYS", "14")
    monkeypatch.delenv("EA_MEMORIAL_STT_ERROR_LOG_ALLOW_LOCAL", raising=False)
    monkeypatch.setattr(memorial_stt_error_log, "_private_storage_available", lambda: False)

    result = memorial_stt_error_log.log_memorial_stt_issue(
        slug="manfred",
        route="conversation_turn",
        reason="generic_fallback_answer",
        audio_payload=b"fake-audio",
        content_type="audio/wav",
        transcription_payload={"transcription_status": "transcribed", "transcript_text": "Covid-Impfung"},
        answer_payload={"answer": "Sag mir den konkreten Punkt noch etwas enger."},
    )

    assert result == {"status": "disabled", "reason": "private_storage_missing"}


def test_memorial_conversation_turn_contact_opening_bypasses_llm(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    _write_unmixr_private_voice(monkeypatch, Path(str(tmp_path / "private")), slug)
    input_audio = _captured_contact_opening_wav_bytes()
    output_audio = _generated_wav_bytes(textish_seed="Worum geht es")

    monkeypatch.setattr(
        public_memorials,
        "_memorial_transcribe_audio_blob",
        lambda **kwargs: {
            "transcription_status": "transcribed",
            "transcript_text": "Hallo Manfred, kannst du jetzt mit mir sprechen?",
            "transcript_effective_text": "Hallo Manfred, kannst du jetzt mit mir sprechen?",
            "transcript_original_text": "Hallo Manfred, kannst du jetzt mit mir sprechen?",
            "transcriber": "unit-test",
        },
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_chat_answer",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("contact opening must bypass llm")),
    )
    monkeypatch.setattr(
        public_memorials,
        "unmixr_synthesize_request",
        lambda **kwargs: (output_audio, "audio/wav"),
    )
    monkeypatch.setattr(
        public_memorials,
        "_pad_speech_audio_lead_in",
        lambda *, payload, content_type, silence_ms, tail_silence_ms, extra_filters: (payload, content_type),
    )

    client = _client(principal_id="exec-memorial-contact-bypass-llm")
    response = client.post(
        f"/memorials/{slug}/conversation-turn",
        content=input_audio,
        headers={"content-type": "audio/wav"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["fallback_reason"] == "direct_contact_opening"
    assert body["answer"] in CONTACT_REPLY_VARIANTS


def test_memorial_rescue_turn_accepts_short_guardrail_tts_audio(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    _write_unmixr_private_voice(monkeypatch, Path(str(tmp_path / "private")), slug)

    short_audio = _captured_stt_retry_wav_bytes()
    monkeypatch.setattr(
        public_memorials,
        "unmixr_synthesize_request",
        lambda **kwargs: (short_audio, "audio/wav"),
    )
    monkeypatch.setattr(
        public_memorials,
        "_pad_speech_audio_lead_in",
        lambda *, payload, content_type, silence_ms, tail_silence_ms, extra_filters: (payload, content_type),
    )

    result = public_memorials._build_memorial_rescue_contact_turn_payload(
        slug=slug,
        personal_memory_context={},
        difficult_memory_mode=False,
        rescue_reason="speech_transcription_empty",
    )

    assert result["audio_unavailable"] is False
    assert result["voice_delivery_status"] == "spoken_audio_ready"
    assert result["spoken_turn"] is True
    assert result["audio_base64"]
    assert result["fallback_reason"] == "stt_retry_required"


def test_memorial_voice_config_forces_german_over_browser_or_provider_locale(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    _write_private_voice(
        Path(str(tmp_path / "private")),
        slug,
        {
            "tts_plugin": public_memorials.UNMIXR_TTS_PLUGIN_ID,
            "tts_plugin_voice_id": "manfred-unmixr-test",
            "lang": "en-US",
            "voice_consent": {
                "status": "approved",
                "scope": ["synthesize", "conversation_turn", "realtime"],
                "authorized_by": "test-family",
                "authorized_at": "2026-06-06T08:00:00Z",
                "source_assets_reviewed": True,
                "revoked": False,
            },
        },
    )
    monkeypatch.setenv("UNMIXR_LANGUAGE", "en-US")
    monkeypatch.setenv("UNMIXR_API_KEY", "unit-test-unmixr-key")
    seen: dict[str, object] = {}
    pad_seen: dict[str, object] = {}
    monkeypatch.setattr(
        public_memorials,
        "unmixr_synthesize_request",
        lambda **kwargs: seen.update(kwargs) or (_generated_wav_bytes(textish_seed="Ich antworte ruhig."), "audio/wav"),
    )
    monkeypatch.setattr(
        public_memorials,
        "_pad_speech_audio_lead_in",
        lambda *, payload, content_type, silence_ms, tail_silence_ms, extra_filters: pad_seen.update(
            {
                "silence_ms": silence_ms,
                "tail_silence_ms": tail_silence_ms,
                "extra_filters": extra_filters,
            }
        )
        or (payload, content_type),
    )

    config = public_memorials._load_voice_config(slug)
    client = _client(principal_id="exec-memorial-voice-german-runtime")
    response = client.post(f"/memorials/{slug}/speech-synthesize", json={"text": "Ich antworte ruhig und deutsch."})

    assert config["lang"] == "en-US"
    assert response.status_code == 200
    assert seen["lang"] == "de-AT"
    assert seen["speaking_rate"] == "0.90"
    assert "atempo=0.92" in str(pad_seen["extra_filters"])


def test_memorial_speech_synthesize_rejects_empty_tts_audio(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    _write_private_voice(
        Path(str(tmp_path / "private")),
        slug,
        {
            "tts_plugin": public_memorials.UNMIXR_TTS_PLUGIN_ID,
            "tts_plugin_voice_id": "manfred-unmixr-test",
            "voice_consent": {
                "status": "approved",
                "scope": ["synthesize", "conversation_turn", "realtime"],
                "authorized_by": "test-family",
                "authorized_at": "2026-06-06T08:00:00Z",
                "source_assets_reviewed": True,
                "revoked": False,
            },
        },
    )
    monkeypatch.setenv("UNMIXR_API_KEY", "unit-test-unmixr-key")
    monkeypatch.setattr(public_memorials, "unmixr_synthesize_request", lambda **kwargs: (b"", "audio/wav"))

    client = _client(principal_id="exec-memorial-synthesize-empty-tts")
    response = client.post(f"/memorials/{slug}/speech-synthesize", json={"text": "Ich antworte ruhig."})

    assert response.status_code == 502
    assert "tts_audio_missing" in response.text


def test_memorial_speech_synthesize_does_not_fallback_to_openvoice_tts_when_unmixr_slots_cool_down(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    _write_private_voice(
        Path(str(tmp_path / "private")),
        slug,
        {
            "tts_plugin": public_memorials.UNMIXR_TTS_PLUGIN_ID,
            "tts_plugin_voice_id": "manfred-unmixr-test",
            "voice_consent": {
                "status": "approved",
                "scope": ["synthesize", "conversation_turn", "realtime"],
                "authorized_by": "test-family",
                "authorized_at": "2026-06-06T08:00:00Z",
                "source_assets_reviewed": True,
                "revoked": False,
            },
        },
    )
    monkeypatch.setenv("UNMIXR_API_KEY", "unit-test-unmixr-key")
    monkeypatch.setenv("EA_MEMORIAL_REHEARSAL_TTS_FALLBACK_ENABLED", "1")
    piper_calls: list[dict[str, object]] = []

    def _raise_cooldown(**kwargs):
        raise public_memorials.HTTPException(status_code=429, detail="unmixr_slots_cooling_down:600")

    monkeypatch.setattr(public_memorials, "unmixr_synthesize_request", _raise_cooldown)
    monkeypatch.setattr(
        public_memorials,
        "_pad_speech_audio_lead_in",
        lambda *, payload, content_type, silence_ms, tail_silence_ms, extra_filters: (payload, content_type),
    )

    client = _client(principal_id="exec-memorial-synthesize-tts-policy")
    response = client.post(f"/memorials/{slug}/speech-synthesize", json={"text": "Ich antworte ruhig."})

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "600"
    assert response.json()["detail"] == "tts_temporarily_unavailable"
    assert response.json()["error"]["code"] == "tts_temporarily_unavailable"
    assert "cooling down" in response.json()["error"]["message"]
    assert "unmixr" not in response.text.lower()
    assert "X-Memorial-TTS-Fallback" not in response.headers
    assert piper_calls == []


def test_memorial_speech_synthesize_keeps_unmixr_cooldown_fail_closed_when_fallback_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    _write_private_voice(
        Path(str(tmp_path / "private")),
        slug,
        {
            "tts_plugin": public_memorials.UNMIXR_TTS_PLUGIN_ID,
            "tts_plugin_voice_id": "manfred-unmixr-test",
            "voice_consent": {
                "status": "approved",
                "scope": ["synthesize", "conversation_turn", "realtime"],
                "authorized_by": "test-family",
                "authorized_at": "2026-06-06T08:00:00Z",
                "source_assets_reviewed": True,
                "revoked": False,
            },
        },
    )
    monkeypatch.setenv("UNMIXR_API_KEY", "unit-test-unmixr-key")
    monkeypatch.setenv("EA_MEMORIAL_REHEARSAL_TTS_FALLBACK_ENABLED", "0")
    piper_calls: list[dict[str, object]] = []

    def _raise_cooldown(**kwargs):
        raise public_memorials.HTTPException(status_code=429, detail="unmixr_slots_cooling_down:600")

    monkeypatch.setattr(public_memorials, "unmixr_synthesize_request", _raise_cooldown)

    client = _client(principal_id="exec-memorial-synthesize-tts-no-fallback")
    response = client.post(f"/memorials/{slug}/speech-synthesize", json={"text": "Ich antworte ruhig."})

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "600"
    assert response.json()["detail"] == "tts_temporarily_unavailable"
    assert "unmixr" not in response.text.lower()
    assert piper_calls == []


def test_memorial_voice_config_resolves_committed_voice_id_placeholders_from_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    _write_private_voice(
        Path(str(tmp_path / "private")),
        slug,
        {
            "tts_plugin": public_memorials.UNMIXR_TTS_PLUGIN_ID,
            "tts_plugin_voice_id": "${UNMIXR_VOICE_ID}",
            "voice_profile_id": "${UNMIXR_VOICE_ID}",
            "voice_consent": {
                "status": "approved",
                "scope": ["synthesize", "conversation_turn", "realtime"],
                "authorized_by": "test-family",
                "authorized_at": "2026-06-06T08:00:00Z",
                "source_assets_reviewed": True,
                "revoked": False,
            },
        },
    )
    monkeypatch.setenv("UNMIXR_API_KEY", "unit-test-unmixr-key")
    monkeypatch.setenv("UNMIXR_VOICE_ID", "runtime-private-voice-id")

    config = public_memorials._load_voice_config(slug)

    assert config["tts_plugin_voice_id"] == "runtime-private-voice-id"
    assert config["voice_profile_id"] == "runtime-private-voice-id"


def test_memorial_conversation_turn_keeps_configured_voice_even_while_warmup_is_cold(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    _write_unmixr_private_voice(monkeypatch, Path(str(tmp_path / "private")), slug)

    input_audio = _generated_wav_bytes(textish_seed="Hallo Manfred, kann ich jetzt mit dir reden?")
    output_audio = _generated_wav_bytes(textish_seed="Ja, ich bin da.")
    unmixr_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        public_memorials,
        "_memorial_transcribe_audio_blob",
        lambda **kwargs: {
            "transcription_status": "transcribed",
            "transcript_text": "Hallo Manfred, kann ich jetzt mit dir reden?",
            "transcriber": "unit-test",
        },
    )
    monkeypatch.setattr(
        public_memorials,
        "generate_text",
        lambda **kwargs: SimpleNamespace(text="Ja, ich bin da. Sprich einfach los.", provider_key="unit-test-model", model="unit-test-model"),
    )
    monkeypatch.setattr(
        public_memorials,
        "_prefer_fast_tts_for_conversation_turn",
        lambda warmup_slug: (True, "warmup_cold"),
    )
    scheduled: list[str] = []
    monkeypatch.setattr(
        public_memorials,
        "_schedule_memorial_live_warmup",
        lambda warmup_slug: scheduled.append(warmup_slug) or {"status": "queued", "scheduled": True, "ttl_seconds": 600},
    )
    monkeypatch.setattr(
        public_memorials,
        "unmixr_synthesize_request",
        lambda **kwargs: unmixr_calls.append(kwargs) or (output_audio, "audio/wav"),
    )
    monkeypatch.setattr(
        public_memorials,
        "_pad_speech_audio_lead_in",
        lambda *, payload, content_type, silence_ms, tail_silence_ms, extra_filters: (payload, content_type),
    )

    client = _client(principal_id="exec-memorial-live-fast-tts")
    response = client.post(
        f"/memorials/{slug}/conversation-turn",
        content=input_audio,
        headers={"content-type": "audio/wav"},
    )

    assert response.status_code == 200
    body = response.json()
    assert unmixr_calls
    assert body["tts_plugin"] == public_memorials.UNMIXR_TTS_PLUGIN_ID
    assert body["tts_fast_path"] is False
    assert "tts_fast_path_reason" not in body
    assert scheduled == []


def test_memorial_conversation_turn_rescues_transcription_failure_with_stt_retry_reply(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    _write_private_voice(
        Path(str(tmp_path / "private")),
        slug,
        {
            "tts_plugin": public_memorials.UNMIXR_TTS_PLUGIN_ID,
            "tts_plugin_voice_id": "voice-123",
            "voice_consent": {
                "status": "approved",
                "scope": ["synthesize", "conversation_turn", "realtime"],
                "authorized_by": "test-family",
                "authorized_at": "2026-06-06T08:00:00Z",
                "source_assets_reviewed": True,
                "revoked": False,
            },
        },
    )
    monkeypatch.setenv("UNMIXR_API_KEY", "unmixr-test-key")

    output_audio = _generated_wav_bytes(textish_seed="Ordne mir erst Ort, Zeit und den konkreten Stand.")
    seen_unmixr_calls: list[dict[str, object]] = []

    def _raise_empty(**kwargs):
        raise public_memorials.HTTPException(status_code=400, detail="speech_transcription_empty")

    monkeypatch.setattr(public_memorials, "_memorial_transcribe_audio_blob", _raise_empty)
    monkeypatch.setattr(
        public_memorials,
        "unmixr_synthesize_request",
        lambda **kwargs: seen_unmixr_calls.append(kwargs) or (output_audio, "audio/wav"),
    )
    monkeypatch.setattr(
        public_memorials,
        "_pad_speech_audio_lead_in",
        lambda *, payload, content_type, silence_ms, tail_silence_ms, extra_filters: (payload, content_type),
    )

    client = _client(principal_id="exec-memorial-live-rescue-turn")
    response = client.post(
        f"/memorials/{slug}/conversation-turn",
        content=_captured_stt_retry_wav_bytes(),
        headers={"content-type": "audio/wav"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "akustisch" in body["answer"].lower()
    assert "noch einmal" in body["answer"].lower()
    assert body["fallback_reason"] == "stt_retry_required"
    assert body["turn_rescue_reason"] == "speech_transcription_empty"
    assert body["tts_plugin"] == public_memorials.UNMIXR_TTS_PLUGIN_ID
    assert seen_unmixr_calls


def test_memorial_conversation_turn_rescues_throttled_transcription_with_technical_retry_reply(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    _write_unmixr_private_voice(monkeypatch, Path(str(tmp_path / "private")), slug)

    output_audio = _generated_wav_bytes(textish_seed="Ordne mir erst Ort, Zeit und den konkreten Stand.")
    seen_unmixr_calls: list[dict[str, object]] = []

    def _raise_throttled(**kwargs):
        raise public_memorials.HTTPException(
            status_code=502,
            detail="Request was throttled. Expected available in 3007 seconds.:429",
        )

    monkeypatch.setattr(public_memorials, "_memorial_transcribe_audio_blob", _raise_throttled)
    monkeypatch.setattr(
        public_memorials,
        "unmixr_synthesize_request",
        lambda **kwargs: seen_unmixr_calls.append(kwargs) or (output_audio, "audio/wav"),
    )
    monkeypatch.setattr(
        public_memorials,
        "_pad_speech_audio_lead_in",
        lambda *, payload, content_type, silence_ms, tail_silence_ms, extra_filters: (payload, content_type),
    )

    client = _client(principal_id="exec-memorial-live-rescue-throttle")
    response = client.post(
        f"/memorials/{slug}/conversation-turn",
        content=_captured_technical_retry_wav_bytes(),
        headers={"content-type": "audio/wav"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "technisch blockiert" in body["answer"].lower()
    assert "noch einmal" in body["answer"].lower()
    assert body["fallback_reason"] == "technical_retry_required"
    assert "Request was throttled" in body["turn_rescue_reason"]
    assert body["tts_plugin"] == public_memorials.UNMIXR_TTS_PLUGIN_ID
    assert seen_unmixr_calls


def test_memorial_conversation_turn_rescue_survives_tts_failure_without_audio(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    _write_private_voice(
        Path(str(tmp_path / "private")),
        slug,
        {
            "tts_plugin": public_memorials.UNMIXR_TTS_PLUGIN_ID,
            "tts_plugin_voice_id": "voice-123",
            "voice_consent": {
                "status": "approved",
                "scope": ["synthesize", "conversation_turn", "realtime"],
                "authorized_by": "test-family",
                "authorized_at": "2026-06-06T08:00:00Z",
                "source_assets_reviewed": True,
                "revoked": False,
            },
        },
    )
    monkeypatch.setenv("UNMIXR_API_KEY", "unmixr-test-key")

    def _raise_empty(**kwargs):
        raise public_memorials.HTTPException(status_code=400, detail="speech_transcription_empty")

    def _raise_tts(**kwargs):
        raise public_memorials.HTTPException(status_code=502, detail="Request was throttled. Expected available in 1900 seconds.:429")

    monkeypatch.setattr(public_memorials, "_memorial_transcribe_audio_blob", _raise_empty)
    monkeypatch.setattr(public_memorials, "_render_memorial_tts_audio", _raise_tts)

    client = _client(principal_id="exec-memorial-live-rescue-no-audio")
    response = client.post(
        f"/memorials/{slug}/conversation-turn",
        content=_captured_stt_retry_wav_bytes(),
        headers={"content-type": "audio/wav"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["fallback_reason"] == "stt_retry_required"
    assert body["audio_unavailable"] is True
    assert body["voice_delivery_status"] == "audio_unavailable"
    assert body["spoken_turn"] is False
    assert body["audio_base64"] == ""
    assert "akustisch" in body["answer"].lower()


def test_memorial_conversation_turn_empty_tts_is_degraded_not_spoken_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    _write_private_voice(
        Path(str(tmp_path / "private")),
        slug,
        {
            "tts_plugin": public_memorials.UNMIXR_TTS_PLUGIN_ID,
            "tts_plugin_voice_id": "voice-123",
            "voice_consent": {
                "status": "approved",
                "scope": ["synthesize", "conversation_turn", "realtime"],
                "authorized_by": "test-family",
                "authorized_at": "2026-06-06T08:00:00Z",
                "source_assets_reviewed": True,
                "revoked": False,
            },
        },
    )
    monkeypatch.setenv("UNMIXR_API_KEY", "unmixr-test-key")
    monkeypatch.setattr(
        public_memorials,
        "_memorial_transcribe_audio_blob",
        lambda **kwargs: {
            "transcription_status": "transcribed",
            "transcript_text": "Hallo Manfred, kannst du jetzt mit mir sprechen?",
            "transcriber": "unit-test",
        },
    )
    monkeypatch.setattr(public_memorials, "_render_memorial_tts_audio", lambda **kwargs: (b"", "audio/wav"))

    client = _client(principal_id="exec-memorial-live-empty-tts")
    response = client.post(
        f"/memorials/{slug}/conversation-turn",
        content=_captured_contact_opening_wav_bytes(),
        headers={"content-type": "audio/wav"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["fallback_reason"] == "technical_retry_required"
    assert body["turn_rescue_reason"] == "tts_audio_missing"
    assert body["audio_unavailable"] is True
    assert body["voice_delivery_status"] == "audio_unavailable"
    assert body["spoken_turn"] is False
    assert body["audio_base64"] == ""
    assert "nicht sauber hörbar" in body["answer"].lower()


def test_memorial_conversation_turn_non_rescued_http_exception_uses_memorial_error_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials
    from app.api.routes import public_memorial_turn_support

    _write_private_voice(
        Path(str(tmp_path / "private")),
        slug,
        {
            "tts_plugin": public_memorials.UNMIXR_TTS_PLUGIN_ID,
            "tts_plugin_voice_id": "voice-123",
            "voice_consent": {
                "status": "approved",
                "scope": ["synthesize", "conversation_turn", "realtime"],
                "authorized_by": "test-family",
                "authorized_at": "2026-06-06T08:00:00Z",
                "source_assets_reviewed": True,
                "revoked": False,
            },
        },
    )

    def _raise_timeout(**kwargs):
        raise public_memorials.HTTPException(status_code=504, detail="tts_timeout")

    monkeypatch.setattr(public_memorial_turn_support, "build_public_memorial_turn", _raise_timeout)

    client = _client(principal_id="exec-memorial-live-turn-error-envelope")
    response = client.post(
        f"/memorials/{slug}/conversation-turn",
        content=_captured_contact_opening_wav_bytes(),
        headers={"content-type": "audio/wav"},
    )

    assert response.status_code == 504
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.json()["error"]["code"] == "tts_timeout"


def test_memorial_conversation_turn_supports_voicewave_clone(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    _write_private_voice(
        Path(str(tmp_path / "private")),
        slug,
        {
            "tts_plugin": public_memorials.VOICEWAVE_TTS_PLUGIN_ID,
            "tts_plugin_voice_id": "Manfred Hoza Memorial",
            "voice_consent": {
                "status": "approved",
                "scope": ["synthesize", "conversation_turn", "realtime"],
                "authorized_by": "test-family",
                "authorized_at": "2026-06-08T18:00:00Z",
                "source_assets_reviewed": True,
                "revoked": False,
            },
        },
    )
    monkeypatch.setenv("VOICEWAVE_LOGIN_EMAIL", "voicewave@example.com")
    monkeypatch.setenv("VOICEWAVE_LOGIN_PASSWORD", "secret")

    input_audio = _generated_wav_bytes(textish_seed="Hallo Manfred, bitte antworte.")
    output_audio = _generated_wav_bytes(textish_seed="Ich bin da.")
    seen_voicewave_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        public_memorials,
        "_memorial_transcribe_audio_blob",
        lambda **kwargs: {
            "transcription_status": "transcribed",
            "transcript_text": "Hallo Manfred, bitte antworte.",
            "transcriber": "unit-test",
        },
    )
    monkeypatch.setattr(
        public_memorials,
        "generate_text",
        lambda **kwargs: SimpleNamespace(
            text="Ich bin da. Sprich direkt mit mir.",
            provider_key="unit-test-model",
            model="unit-test-model",
        ),
    )
    monkeypatch.setattr(
        public_memorials,
        "voicewave_synthesize_request",
        lambda **kwargs: seen_voicewave_calls.append(kwargs) or (output_audio, "audio/wav"),
    )
    monkeypatch.setattr(
        public_memorials,
        "_pad_speech_audio_lead_in",
        lambda *, payload, content_type, silence_ms, tail_silence_ms, extra_filters: (payload, content_type),
    )
    monkeypatch.setattr(
        public_memorials,
        "_prefer_fast_tts_for_conversation_turn",
        lambda warmup_slug: (False, ""),
    )

    client = _client(principal_id="exec-memorial-live-voicewave-turn")
    response = client.post(
        f"/memorials/{slug}/conversation-turn",
        content=input_audio,
        headers={"content-type": "audio/wav"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tts_plugin"] == public_memorials.VOICEWAVE_TTS_PLUGIN_ID
    assert body["audio_content_type"] == "audio/wav"
    assert len(seen_voicewave_calls) >= 1
    assert all(item["voice_label"] == "Manfred Hoza Memorial" for item in seen_voicewave_calls)
    assert seen_voicewave_calls[-1]["text"] == body["answer"]


def test_memorial_warmup_primes_voicewave_contact_openings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    class _ImmediateThread:
        def __init__(self, *, target, args=(), kwargs=None, daemon=None, name=None):
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self) -> None:
            self._target(*self._args, **self._kwargs)

    _write_private_voice(
        Path(str(tmp_path / "private")),
        slug,
        {
            "tts_plugin": public_memorials.VOICEWAVE_TTS_PLUGIN_ID,
            "tts_plugin_voice_id": "Manfred Hoza Memorial",
        },
    )
    monkeypatch.setenv("VOICEWAVE_LOGIN_EMAIL", "voicewave@example.com")
    monkeypatch.setenv("VOICEWAVE_LOGIN_PASSWORD", "secret")

    seen_render_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        public_memorials,
        "_memorial_transcribe_audio_blob",
        lambda **kwargs: {"transcription_status": "transcribed", "transcript_text": "Hallo Manfred", "transcriber": "unit-test"},
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_chat_answer",
        lambda *args, **kwargs: {"answer": "Ja, du kannst mit mir reden.", "llm_model": "unit-test"},
    )
    monkeypatch.setattr(
        public_memorials,
        "_render_memorial_tts_audio",
        lambda **kwargs: seen_render_calls.append(
            {
                "text": kwargs["text"],
                "slug": kwargs["slug"],
                "selected_plugin": kwargs["selected_plugin"],
                "lead_in_ms": kwargs["lead_in_ms"],
                "tail_silence_ms": kwargs["tail_silence_ms"],
            }
        ) or (b"RIFFvoicewave", "audio/wav"),
    )
    monkeypatch.setattr(public_memorials.threading, "Thread", _ImmediateThread)

    public_memorials._run_memorial_live_warmup(slug)

    assert len(seen_render_calls) == 1
    assert {item["text"] for item in seen_render_calls} <= CONTACT_REPLY_VARIANTS
    assert all(item["slug"] == slug for item in seen_render_calls)
    assert all(item["selected_plugin"] == public_memorials.VOICEWAVE_TTS_PLUGIN_ID for item in seen_render_calls)
    assert all(item["lead_in_ms"] == public_memorials._MEMORIAL_CONTACT_TTS_LEAD_IN_MS for item in seen_render_calls)
    assert all(item["tail_silence_ms"] == public_memorials._MEMORIAL_CONTACT_TTS_TAIL_SILENCE_MS for item in seen_render_calls)


def test_memorial_warmup_primes_unmixr_contact_openings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    class _ImmediateThread:
        def __init__(self, *, target, args=(), kwargs=None, daemon=None, name=None):
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self) -> None:
            self._target(*self._args, **self._kwargs)

    _write_private_voice(
        Path(str(tmp_path / "private")),
        slug,
        {
            "tts_plugin": public_memorials.UNMIXR_TTS_PLUGIN_ID,
            "tts_plugin_voice_id": "voice-123",
        },
    )
    monkeypatch.setenv("UNMIXR_API_KEY", "unmixr-test-key")

    seen_render_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        public_memorials,
        "_memorial_transcribe_audio_blob",
        lambda **kwargs: {"transcription_status": "transcribed", "transcript_text": "Hallo Manfred", "transcriber": "unit-test"},
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_chat_answer",
        lambda *args, **kwargs: {"answer": "Ja, du kannst mit mir reden.", "llm_model": "unit-test"},
    )
    monkeypatch.setattr(
        public_memorials,
        "_render_memorial_tts_audio",
        lambda **kwargs: seen_render_calls.append(
            {
                "text": kwargs["text"],
                "slug": kwargs["slug"],
                "selected_plugin": kwargs["selected_plugin"],
                "lead_in_ms": kwargs["lead_in_ms"],
                "tail_silence_ms": kwargs["tail_silence_ms"],
            }
        ) or (b"RIFFunmixr", "audio/wav"),
    )
    monkeypatch.setattr(public_memorials.threading, "Thread", _ImmediateThread)

    public_memorials._run_memorial_live_warmup(slug)

    assert len(seen_render_calls) == 1
    assert {item["text"] for item in seen_render_calls} <= CONTACT_REPLY_VARIANTS
    assert all(item["slug"] == slug for item in seen_render_calls)
    assert all(item["selected_plugin"] == public_memorials.UNMIXR_TTS_PLUGIN_ID for item in seen_render_calls)
    assert all(item["lead_in_ms"] == public_memorials._MEMORIAL_CONTACT_TTS_LEAD_IN_MS for item in seen_render_calls)
    assert all(item["tail_silence_ms"] == public_memorials._MEMORIAL_CONTACT_TTS_TAIL_SILENCE_MS for item in seen_render_calls)


def test_memorial_speech_synthesize_reuses_final_render_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    _write_unmixr_private_voice(monkeypatch, Path(str(tmp_path / "private")), slug)

    cache_root = tmp_path / "tts-cache"
    synth_calls = {"count": 0}
    pad_calls = {"count": 0}

    monkeypatch.setattr(public_memorials, "_MEMORIAL_TTS_RENDER_CACHE_ROOT", cache_root)
    monkeypatch.setattr(
        public_memorials,
        "unmixr_synthesize_request",
        lambda **kwargs: synth_calls.__setitem__("count", synth_calls["count"] + 1) or (b"RIFFraw", "audio/wav"),
    )
    monkeypatch.setattr(
        public_memorials,
        "_pad_speech_audio_lead_in",
        lambda *, payload, content_type, silence_ms, tail_silence_ms, extra_filters: pad_calls.__setitem__("count", pad_calls["count"] + 1) or (b"RIFFcached", "audio/wav"),
    )

    client = _client(principal_id="exec-memorial-tts-cache")
    payload = {"text": "Ja. Du kannst mit mir reden. Sag kurz, worum es geht."}

    first = client.post(f"/memorials/{slug}/speech-synthesize", json=payload)
    second = client.post(f"/memorials/{slug}/speech-synthesize", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.content == b"RIFFcached"
    assert second.content == b"RIFFcached"
    assert synth_calls["count"] == 1
    assert pad_calls["count"] == 1
    cache_metadata_paths = list(cache_root.glob("*.json"))
    assert len(cache_metadata_paths) == 1
    cache_metadata = json.loads(cache_metadata_paths[0].read_text(encoding="utf-8"))
    assert cache_metadata["lang"] == "de-AT"
    assert cache_metadata["provider_language_policy"] == "unmixr_locale_preserving_v1"


def test_memorial_chat_strips_llm_meta_self_reference_from_answer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    def _fake_generate_text(*, messages, requested_model, max_output_tokens):
        return SimpleNamespace(
            text="Ich bin ein LLM und kann nur eine rekonstruktive Erinnerung liefern. Meine Stimme klingt ruhig und trocken.",
            provider_key="unit-test-model",
            model="unit-test-model",
        )

    monkeypatch.setattr(public_memorials, "generate_text", _fake_generate_text)
    client = _client(principal_id="exec-memorial-strip-meta")

    response = client.post(f"/memorials/{slug}/chat", json={"question": "Wie klingt deine Stimme jetzt?"})

    assert response.status_code == 200
    body = response.json()
    assert "llm" not in body["answer"].lower()
    assert "sprachmodell" not in body["answer"].lower()
    assert "ki-rekonstruktion" in body["answer"].lower()
    assert "nicht der echte manfred" in body["answer"].lower()
    assert "ich bin manfred" not in body["answer"].lower()


def test_production_policy_preserves_disclosed_first_person_reconstruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials

    monkeypatch.setattr(public_memorials, "_memorial_voice_release_enforced", lambda: True)

    result = public_memorials._apply_memorial_narrator_response_policy(
        {
            "answer": "Ich erinnere mich an meine Familie und habe damals anders entschieden.",
            "mode": "memorial_first_person_memory_chat",
            "safety_note": "legacy",
        },
        question="Was war dir bei Familie wichtig?",
    )

    assert result["mode"] == "memorial_source_grounded_first_person_reconstruction"
    assert "fallback_reason" not in result
    assert str(result["answer"]) == (
        "Ich erinnere mich an meine Familie und habe damals anders entschieden."
    )
    assert result["narrator"] == {
        "synthetic": True,
        "source_grounded": True,
        "is_memorial_person": False,
        "speaks_for_memorial_person": False,
        "perspective": "first_person_reconstruction",
    }


@pytest.mark.parametrize(
    "claim",
    [
        "Ich bin Manfred, aber heute bin ich müde.",
        "Ich selbst bin Manfred.",
        "Ich bin der echte Manfred.",
        "Ich bin ohne Zweifel Manfred.",
        "Ich bin Manfred Hoza aus Wien.",
        "Ich werde Manfred genannt.",
        "Ich identifiziere mich als Manfred.",
        "Hier spricht der echte Manfred Hoza.",
        "Du sprichst mit dem echten Manfred Hoza.",
        "I am none other than Manfred Hoza.",
        "You are talking to the real Manfred.",
        "I, Manfred, am speaking.",
        "I go by Manfred.",
        "Ich bin, ehrlich gesagt, Manfred Hoza.",
        "Ich\u200bbin\u200bManfred Hoza.",
        "Ich bin Manfred und eine KI-Rekonstruktion und nicht der echte Manfred.",
        "Ich bin nicht nicht Manfred.",
        "Ich, bin, Manfred.",
        "Ich\u200b, bin\u2060, Man\u00adfred.",
        "Ich bin M.a.n.f.r.e.d.",
        "Ich bin Mаnfred.",
        "Ich bin Man0fred.",
        "Ich bin |\\/|4nfr3d Hoza.",
        "Ich bin, M-anfred.",
        "Ich bin Μɑոƒɾҽԁ.",
        "Ich weiß, dass man Fred vertrauen konnte. man-fred bin ich.",
        (
            "Ich weiß, dass man Fred vertrauen konnte. "
            "Ich erinnere mich an man-fred."
        ),
        (
            "Ich bin eine quellengebundene KI-Rekonstruktion von Manfred, "
            "nicht der echte Manfred. 我是曼弗雷德"
        ),
        "Ich bin Manfred und Maria bin ich begegnet.",
        "Ich, ehrlich gesagt, bin Manfred.",
        "Manfred bin ich.",
        "Ich bin’s, Manfred.",
        "Ich bin Man\u200bfred Hoza.",
    ],
)
def test_production_policy_replaces_literal_manfred_identity_claim(
    monkeypatch: pytest.MonkeyPatch,
    claim: str,
) -> None:
    from app.api.routes import public_memorials

    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_release_enforced",
        lambda: True,
    )

    result = public_memorials._apply_memorial_narrator_response_policy(
        {
            "answer": claim,
            "mode": "memorial_first_person_memory_chat",
            "safety_note": "legacy",
        },
        question="Was möchtest du erzählen?",
    )

    answer = str(result["answer"])
    assert answer != claim
    assert "KI-Rekonstruktion" in answer
    assert "nicht der echte Manfred" in answer


def test_blocked_voice_release_renders_polished_text_only_memorial_guide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials

    monkeypatch.setattr(public_memorials, "_memorial_voice_release_enforced", lambda: True)
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_release_decision",
        lambda slug: {"allowed": False, "status": "blocked", "reason": "release_human_acceptance_missing"},
    )

    page = public_memorials._minimal_public_memorial_html(
        slug="manfred",
        person_name="Manfred Hoza",
        page_title="Erinnerungen an Manfred Hoza",
        subtitle="Eine ruhige Gedenkseite.",
        memorial_avatar_url="/memorials/manfred/icon.svg",
        pwa_short_name="Manfred",
        clickrank_html="",
        story_html="<section>Erinnerungen</section>",
    )

    assert 'data-voice-release="blocked"' in page
    assert "Frage schreiben" in page
    assert "Schriftliche Frage stellen" not in page
    assert "Zum Gespräch" in page
    assert "Zum quellengebundenen Gedenkbegleiter" not in page
    assert "ist nicht Manfred und spricht nicht für ihn" in page
    assert "Was möchtest du Manfred fragen?" not in page
    assert "KI-gestützten, synthetischen Manfred-Stimme" not in page
    assert "const memorialVoiceReleaseAllowed = false;" in page
    assert "const memorialPagePrewarmEnabled = false;" in page
    assert 'if (!memorialVoiceReleaseAllowed) return null;' in page
    assert 'if (!memorialVoiceReleaseAllowed) throw new Error("memorial_voice_release_not_verified");' in page
    assert "memorialVoiceReleaseAllowed && isPwaLaunch" in page


def test_memorial_realtime_rejects_audio_bytes_before_start(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    _write_unmixr_private_voice(monkeypatch, Path(str(tmp_path / "private")), slug)
    client = _client(principal_id="exec-memorial-live-realtime-order")

    with client.websocket_connect(f"/memorials/{slug}/realtime") as websocket:
        ready = websocket.receive_json()
        assert ready["type"] == "ready"
        websocket.send_bytes(b"unexpected-audio")
        error = websocket.receive_json()
        assert error == {"type": "error", "message": "audio_start_required"}


def test_memorial_realtime_ready_declares_current_fallback_and_live_audio_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    _write_unmixr_private_voice(monkeypatch, Path(str(tmp_path / "private")), slug)
    monkeypatch.setattr(public_memorials, "_gemini_live_available", lambda: False)
    client = _client(principal_id="exec-memorial-live-realtime-mode")

    with client.websocket_connect(f"/memorials/{slug}/realtime") as websocket:
        ready = websocket.receive_json()

    assert ready["type"] == "ready"
    assert ready["mode"] == "spoken_turn_fallback"
    assert ready["audio_transport"] == "ea_websocket_audio_turn"
    assert ready["turn_timing"] == "buffered_audio_turn"
    assert ready["provider"] == "ea_memorial_turn"
    assert ready["native_realtime_available"] is False
    assert "openai" not in json.dumps(ready).lower()


def test_memorial_realtime_without_gemini_runs_grounded_unmixr_spoken_turn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    provider_voice_id = "live-unmixr-id"
    _write_unmixr_private_voice(
        monkeypatch,
        Path(str(tmp_path / "private")),
        slug,
        voice_id=provider_voice_id,
    )
    for name in list(os.environ):
        if name.startswith("GOOGLE_API_KEY_FALLBACK_"):
            monkeypatch.delenv(name, raising=False)
    for name in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "EA_GEMINI_API_KEY",
        "EA_GOOGLE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("EA_MEMORIAL_GEMINI_LIVE_OAUTH", "0")
    monkeypatch.setenv(
        "EA_MEMORIAL_LIVE_TTS_PLUGIN",
        public_memorials.UNMIXR_TTS_PLUGIN_ID,
    )
    assert public_memorials._gemini_live_available() is False

    seen: dict[str, object] = {}

    async def _unexpected_gemini_connect(*args, **kwargs):
        seen["gemini_connect_called"] = True
        raise AssertionError(
            "Gemini must not be contacted in spoken-turn fallback mode"
        )

    monkeypatch.setattr(
        public_memorials,
        "websockets",
        SimpleNamespace(connect=_unexpected_gemini_connect),
    )

    def _fake_transcribe(*, payload: bytes, content_type: str) -> dict[str, object]:
        seen["stt_payload"] = payload
        seen["stt_content_type"] = content_type
        return {
            "transcription_status": "transcribed",
            "transcript_text": "Was hast du über deine Jugend erzählt?",
            "transcriber": "deterministic-test-stt",
        }

    grounded_sources = [
        {
            "label": "Interview Audio",
            "url": "https://youtube.example/interview",
        }
    ]
    monkeypatch.setattr(
        public_memorials,
        "_memorial_transcribe_audio_blob",
        _fake_transcribe,
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_chat_answer",
        lambda *args, **kwargs: {
            "answer": (
                "Ich habe erzählt, dass meine Jugend von Familie und Arbeit "
                "geprägt war."
            ),
            "sources": grounded_sources,
            "llm_model": "deterministic-test-model",
            "llm_provider": "deterministic-test-provider",
            "llm_fallback_used": False,
        },
    )
    rendered_audio = _generated_wav_bytes(
        textish_seed="Meine Jugend war von Familie und Arbeit geprägt."
    )

    def _fake_render(**kwargs):
        seen["tts_text"] = kwargs["text"]
        seen["tts_plugin"] = kwargs["selected_plugin"]
        seen["tts_option_voice_id"] = kwargs["selected_option"].get(
            "tts_plugin_voice_id"
        )
        seen["tts_config_voice_id"] = kwargs["merged_config"].get(
            "tts_plugin_voice_id"
        )
        return rendered_audio, "audio/wav"

    monkeypatch.setattr(
        public_memorials,
        "_render_memorial_tts_audio",
        _fake_render,
    )
    client = _client(
        principal_id="exec-memorial-live-no-gemini-spoken-turn"
    )

    with client.websocket_connect(
        f"/memorials/{slug}/realtime"
    ) as websocket:
        ready = websocket.receive_json()
        assert ready["mode"] == "spoken_turn_fallback"
        assert ready["audio_transport"] == "ea_websocket_audio_turn"
        assert ready["turn_timing"] == "buffered_audio_turn"
        assert ready["provider"] == "ea_memorial_turn"
        assert ready["native_realtime_available"] is False

        websocket.send_json(
            {
                "type": "user_audio_start",
                "turn_id": "turn_no_gemini",
                "content_type": "audio/pcm;rate=16000",
                "transport": "gemini_live",
            }
        )
        websocket.send_bytes(_pcm16_speech_bytes(samples=3200))
        websocket.send_json(
            {
                "type": "user_audio_end",
                "turn_id": "turn_no_gemini",
            }
        )
        messages = []
        for _ in range(24):
            message = websocket.receive_json()
            messages.append(message)
            if message.get("type") in {"turn_complete", "error"}:
                break

    assert "gemini_connect_called" not in seen
    assert seen["stt_content_type"] == "audio/wav"
    assert bytes(seen["stt_payload"]).startswith(b"RIFF")
    assert seen["tts_plugin"] == public_memorials.UNMIXR_TTS_PLUGIN_ID
    assert seen["tts_option_voice_id"] == provider_voice_id
    assert seen["tts_config_voice_id"] == provider_voice_id
    assert "Jugend" in str(seen["tts_text"])
    assert any(
        message.get("type") == "turn_admitted"
        and message.get("provider_work_started") is True
        and message.get("transport") == "ea_memorial_turn"
        for message in messages
    )
    admission_index = next(
        index
        for index, message in enumerate(messages)
        if message.get("type") == "turn_admitted"
    )
    transcribing_index = next(
        index
        for index, message in enumerate(messages)
        if message.get("type") == "phase"
        and message.get("phase") == "transcribing"
    )
    transcript_index = next(
        index
        for index, message in enumerate(messages)
        if message.get("type") == "transcript"
    )
    assert admission_index < transcribing_index < transcript_index
    assert any(
        message.get("type") == "transcript"
        and message.get("text")
        == "Was hast du über deine Jugend erzählt?"
        for message in messages
    )
    answer_message = next(
        message for message in messages if message.get("type") == "answer"
    )
    assert answer_message["sources"] == grounded_sources
    assert answer_message["text"].startswith("Ich habe erzählt")
    assert any(
        message.get("type") == "audio_chunk"
        and message.get("content_type") == "audio/wav"
        for message in messages
    )
    assert any(
        message.get("type") == "audio_complete"
        and message.get("content_type") == "audio/wav"
        for message in messages
    )
    assert any(
        message.get("type") == "turn_complete"
        for message in messages
    )


def test_memorial_realtime_rechecks_public_release_before_later_turn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    _write_unmixr_private_voice(
        monkeypatch,
        Path(str(tmp_path / "private")),
        slug,
    )
    release = {"allowed": True, "provider_work_allowed": True}
    provider_calls: list[str] = []
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_release_enforced",
        lambda: True,
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_release_decision",
        lambda _slug: dict(release),
    )
    monkeypatch.setattr(
        public_memorials,
        "_support_require_voice_consent",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        public_memorials,
        "_gemini_live_available",
        lambda: False,
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_chat_answer",
        lambda *_args, **_kwargs: provider_calls.append("llm"),
    )
    monkeypatch.setattr(
        public_memorials,
        "_render_memorial_tts_audio",
        lambda **_kwargs: provider_calls.append("tts"),
    )
    client = _client(principal_id="exec-memorial-release-revocation")

    with client.websocket_connect(
        f"/memorials/{slug}/realtime"
    ) as websocket:
        assert websocket.receive_json()["type"] == "ready"
        release["allowed"] = False
        websocket.send_json(
            {
                "type": "user_text_turn",
                "turn_id": "revoked-turn",
                "text": "Hallo?",
            }
        )
        error = websocket.receive_json()

    assert error == {
        "type": "error",
        "turn_id": "revoked-turn",
        "message": "memorial_voice_release_not_verified",
    }
    assert provider_calls == []


@pytest.mark.parametrize("revoked_boundary", ["release", "consent"])
def test_memorial_realtime_revocation_during_llm_emits_no_answer_or_audio(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    revoked_boundary: str,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from fastapi import HTTPException
    from app.api.routes import public_memorials

    _write_unmixr_private_voice(
        monkeypatch,
        Path(str(tmp_path / "private")),
        slug,
    )
    release = {"allowed": True, "provider_work_allowed": True}
    consent = {"allowed": True}
    llm_started = threading.Event()
    llm_continue = threading.Event()
    tts_calls: list[str] = []

    def _require_consent(*_args, **_kwargs) -> None:
        if not consent["allowed"]:
            raise HTTPException(status_code=409, detail="voice_consent_revoked")

    def _blocking_answer(*_args, **_kwargs) -> dict[str, object]:
        llm_started.set()
        assert llm_continue.wait(timeout=5.0)
        return {
            "answer": "Ich antworte erst nach der Freigabeprüfung.",
            "sources": [],
            "llm_model": "midflight-test",
            "llm_provider": "midflight-test",
            "llm_fallback_used": False,
        }

    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_release_enforced",
        lambda: True,
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_release_decision",
        lambda _slug: dict(release),
    )
    monkeypatch.setattr(
        public_memorials,
        "_support_require_voice_consent",
        _require_consent,
    )
    monkeypatch.setattr(public_memorials, "_gemini_live_available", lambda: False)
    monkeypatch.setattr(public_memorials, "_memorial_chat_answer", _blocking_answer)
    monkeypatch.setattr(
        public_memorials,
        "_render_memorial_tts_audio",
        lambda **_kwargs: tts_calls.append("tts") or (b"audio", "audio/wav"),
    )
    client = _client(principal_id=f"exec-midflight-{revoked_boundary}")

    messages: list[dict[str, object]] = []
    with client.websocket_connect(f"/memorials/{slug}/realtime") as websocket:
        assert websocket.receive_json()["type"] == "ready"
        websocket.send_json(
            {
                "type": "user_text_turn",
                "turn_id": f"midflight-{revoked_boundary}",
                "text": "Was war dir im Leben wichtig?",
            }
        )
        assert llm_started.wait(timeout=3.0)
        if revoked_boundary == "release":
            release["allowed"] = False
        else:
            consent["allowed"] = False
        llm_continue.set()
        for _ in range(6):
            message = websocket.receive_json()
            messages.append(message)
            if message.get("type") == "error":
                break

    assert any(
        message.get("type") == "error"
        and message.get("message") == "memorial_voice_release_not_verified"
        for message in messages
    )
    assert not any(
        message.get("type") in {"answer", "audio", "audio_chunk"}
        for message in messages
    )
    assert tts_calls == []


def test_memorial_realtime_preview_expiry_revokes_later_turn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    _write_unmixr_private_voice(
        monkeypatch,
        Path(str(tmp_path / "private")),
        slug,
    )
    monkeypatch.setenv("EA_SOURCE_REVISION", "a" * 40)
    review_image_id = f"sha256:{'b' * 64}"
    monkeypatch.setenv("EA_DEPLOY_IMAGE_ID", review_image_id)
    monkeypatch.setenv(
        "EA_MEMORIAL_VOICE_IDENTITY_SHA256",
        "c" * 64,
    )
    review_state_dir = tmp_path / "review-state"
    review_state_dir.mkdir(mode=0o700)
    monkeypatch.setattr(
        public_memorials,
        "_memorial_state_dir",
        lambda: review_state_dir,
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_runtime_bindings",
        lambda: ({"expected_image_id": review_image_id}, ""),
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_review_signing_secret",
        lambda: "voice-review-realtime-test-secret",
    )
    bootstrap = (
        public_memorials._issue_memorial_voice_review_bootstrap_token()
    )
    exchange = (
        public_memorials._exchange_memorial_voice_review_bootstrap_token(
            bootstrap
        )
    )
    assert exchange is not None
    session_token = exchange[0]
    session_payload = (
        public_memorials._memorial_voice_review_token_payload(
            session_token,
            expected_kind="session",
            required_scope="realtime",
        )
    )
    assert session_payload is not None
    provider_calls: list[str] = []
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_release_enforced",
        lambda: True,
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_release_decision",
        lambda _slug: pytest.fail(
            "operator preview consulted public final release"
        ),
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_runtime_bindings",
        lambda: ({"expected_image_id": review_image_id}, ""),
    )
    monkeypatch.setattr(
        public_memorials,
        "_support_require_voice_consent",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        public_memorials,
        "_gemini_live_available",
        lambda: False,
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_chat_answer",
        lambda *_args, **_kwargs: provider_calls.append("llm"),
    )
    monkeypatch.setattr(
        public_memorials,
        "_render_memorial_tts_audio",
        lambda **_kwargs: provider_calls.append("tts"),
    )
    client = _client(principal_id="exec-memorial-preview-expiry")
    with client.websocket_connect(
        f"/memorials/{slug}/realtime",
        headers={
            "Origin": "https://testserver",
            "Cookie": (
                f"{public_memorials._MEMORIAL_VOICE_REVIEW_COOKIE}="
                f"{session_token}"
            ),
        },
    ) as websocket:
        assert websocket.receive_json()["type"] == "ready"
        monkeypatch.setattr(
            public_memorials,
            "_memorial_realtime_wall_time",
            lambda: float(session_payload["expires_at"]) + 1.0,
        )
        websocket.send_json(
            {
                "type": "user_text_turn",
                "turn_id": "expired-preview-turn",
                "text": "Hallo?",
            }
        )
        error = websocket.receive_json()

    assert error == {
        "type": "error",
        "turn_id": "expired-preview-turn",
        "message": "memorial_voice_review_session_expired",
    }
    assert provider_calls == []


@pytest.mark.parametrize(
    ("idle_seconds", "max_age_seconds", "message"),
    [
        (0.02, 60.0, "memorial_realtime_idle_timeout"),
        (60.0, 0.02, "memorial_realtime_connection_expired"),
    ],
)
def test_memorial_realtime_connections_have_bounded_lifetime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    idle_seconds: float,
    max_age_seconds: float,
    message: str,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    _write_unmixr_private_voice(
        monkeypatch,
        Path(str(tmp_path / "private")),
        slug,
    )
    monkeypatch.setattr(
        public_memorials,
        "_MEMORIAL_REALTIME_IDLE_TIMEOUT_SECONDS",
        idle_seconds,
    )
    monkeypatch.setattr(
        public_memorials,
        "_MEMORIAL_REALTIME_MAX_CONNECTION_AGE_SECONDS",
        max_age_seconds,
    )
    monkeypatch.setattr(
        public_memorials,
        "_gemini_live_available",
        lambda: False,
    )
    client = _client(principal_id=f"exec-{message}")

    with client.websocket_connect(
        f"/memorials/{slug}/realtime"
    ) as websocket:
        assert websocket.receive_json()["type"] == "ready"
        error = websocket.receive_json()

    assert error == {"type": "error", "message": message}


def test_memorial_realtime_text_turn_falls_back_when_llm_times_out(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    output_audio = _generated_wav_bytes(
        textish_seed="Fallback Antwort von Manfred.",
        duration_seconds=1.8,
    )
    _write_unmixr_private_voice(monkeypatch, Path(str(tmp_path / "private")), slug)

    def _slow_chat_answer(*args, **kwargs):
        time.sleep(0.05)
        return {
            "answer": "Diese Antwort sollte wegen Timeout nie rausgehen.",
            "sources": [],
            "llm_model": "slow-model",
            "llm_provider": "slow-provider",
            "llm_request_model": "slow-model",
            "llm_fallback_used": False,
        }

    def _fallback_answer(*args, **kwargs):
        return {
            "answer": "Ich bin weiter da und antworte jetzt aus dem gesicherten Erinnerungsmodus.",
            "sources": ["Archiv"],
            "llm_model": "memorial_guardrail",
            "llm_provider": "memorial_guardrail",
            "llm_request_model": kwargs.get("llm_model") or "ea-gemini-flash",
            "llm_fallback_used": True,
        }

    monkeypatch.setattr(public_memorials, "_MEMORIAL_REALTIME_LLM_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(public_memorials, "_memorial_chat_answer", _slow_chat_answer)
    monkeypatch.setattr(public_memorials, "_memorial_chat_fallback_answer", _fallback_answer)
    monkeypatch.setattr(
        public_memorials,
        "unmixr_synthesize_request",
        lambda **kwargs: (output_audio, "audio/wav"),
    )
    monkeypatch.setattr(
        public_memorials,
        "_pad_speech_audio_lead_in",
        lambda *, payload, content_type, silence_ms, tail_silence_ms, extra_filters: (payload, content_type),
    )

    client = _client(principal_id="exec-memorial-live-realtime-timeout-fallback")

    with client.websocket_connect(f"/memorials/{slug}/realtime") as websocket:
        ready = websocket.receive_json()
        assert ready["type"] == "ready"
        websocket.send_json(
            {
                "type": "user_text_turn",
                "turn_id": "turn_timeout_1",
                "text": "Hallo Manfred, kannst du jetzt mit mir sprechen?",
                "personal_memory_enabled": False,
            }
        )
        messages = []
        for _ in range(8):
            message = websocket.receive_json()
            messages.append(message)
            if message.get("type") in {"turn_complete", "error"}:
                break

    message_types = [message.get("type") for message in messages]
    assert message_types[:3] == ["transcript", "phase", "answer"]
    answer_message = next(message for message in messages if message.get("type") == "answer")
    expected_model = public_memorials._resolve_memorial_realtime_chat_model(
        public_memorials._load_memorial(slug),
        public_memorials._load_private_profile(slug),
    )
    assert "gesicherten Erinnerungsmodus" in answer_message["text"]
    assert answer_message["llm_model"] == expected_model
    assert "audio_complete" in message_types
    assert "turn_complete" in message_types


def test_memorial_realtime_text_turn_does_not_fallback_to_piper_when_configured_tts_times_out() -> None:
    source = PUBLIC_MEMORIALS_SOURCE.read_text(encoding="utf-8")

    assert 'raise HTTPException(status_code=504, detail="tts_timeout")' in source
    assert 'raise HTTPException(status_code=502, detail="tts_plugin_failed")' in source
    assert "Realtime conversation optimizes for immediate audible response over premium voice quality." not in source


def test_memorial_realtime_contact_opening_uses_short_reply_and_small_audio_pad(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    _write_unmixr_private_voice(monkeypatch, Path(str(tmp_path / "private")), slug)

    output_audio = _generated_wav_bytes(textish_seed="Ja. Du kannst mit mir reden.")
    seen_pad_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        public_memorials,
        "unmixr_synthesize_request",
        lambda **kwargs: (output_audio, "audio/wav"),
    )
    monkeypatch.setattr(
        public_memorials,
        "_pad_speech_audio_lead_in",
        lambda *, payload, content_type, silence_ms, tail_silence_ms, extra_filters: seen_pad_calls.append(
            {
                "silence_ms": silence_ms,
                "tail_silence_ms": tail_silence_ms,
            }
        ) or (payload, content_type),
    )

    client = _client(principal_id="exec-memorial-live-realtime-contact")

    with client.websocket_connect(f"/memorials/{slug}/realtime") as websocket:
        ready = websocket.receive_json()
        assert ready["type"] == "ready"
        websocket.send_json(
            {
                "type": "user_text_turn",
                "turn_id": "turn_contact_1",
                "text": "Hallo Manfred, kannst du jetzt mit mir reden?",
                "personal_memory_enabled": False,
            }
        )
        messages = []
        for _ in range(8):
            message = websocket.receive_json()
            messages.append(message)
            if message.get("type") in {"turn_complete", "error"}:
                break

    answer_message = next(message for message in messages if message.get("type") == "answer")
    speaking_phase = next(
        message for message in messages if message.get("type") == "phase" and message.get("phase") == "speaking"
    )

    assert answer_message["text"] in CONTACT_REPLY_VARIANTS
    assert speaking_phase["detail"] == ""
    assert {
        "silence_ms": public_memorials._MEMORIAL_CONTACT_TTS_LEAD_IN_MS,
        "tail_silence_ms": public_memorials._MEMORIAL_CONTACT_TTS_TAIL_SILENCE_MS,
    } in seen_pad_calls


def test_memorial_realtime_latest_turn_replaces_active_turn_instead_of_too_many_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    _write_private_voice(
        Path(str(tmp_path / "private")),
        slug,
        {
            "tts_plugin": public_memorials.UNMIXR_TTS_PLUGIN_ID,
            "tts_plugin_voice_id": "manfred-unmixr-test",
            "voice_consent": {
                "status": "approved",
                "scope": ["synthesize", "conversation_turn", "realtime"],
                "authorized_by": "test-family",
                "authorized_at": "2026-06-06T08:00:00Z",
                "source_assets_reviewed": True,
                "revoked": False,
            },
        },
    )

    output_audio = _generated_wav_bytes(textish_seed="Ja.")
    monkeypatch.setenv("UNMIXR_API_KEY", "unit-test-unmixr-key")

    def _chat_answer(payload, question, *args, **kwargs):
        if "erste" in question.lower():
            time.sleep(0.3)
        return {
            "answer": "Ja.",
            "sources": [],
            "llm_model": "memorial_guardrail",
            "llm_provider": "memorial_guardrail",
            "llm_request_model": "ea-gemini-flash",
            "llm_fallback_used": False,
            "fallback_reason": "direct_contact_opening",
        }

    monkeypatch.setattr(public_memorials, "_memorial_chat_answer", _chat_answer)
    monkeypatch.setattr(
        public_memorials,
        "unmixr_synthesize_request",
        lambda **kwargs: (output_audio, "audio/wav"),
    )
    monkeypatch.setattr(
        public_memorials,
        "_pad_speech_audio_lead_in",
        lambda *, payload, content_type, silence_ms, tail_silence_ms, extra_filters: (payload, content_type),
    )

    client = _client(principal_id="exec-memorial-live-realtime-replace-turn")

    with client.websocket_connect(f"/memorials/{slug}/realtime") as websocket:
        ready = websocket.receive_json()
        assert ready["type"] == "ready"
        websocket.send_json(
            {
                "type": "user_text_turn",
                "turn_id": "turn_old",
                "text": "Das ist der erste Turn.",
                "personal_memory_enabled": False,
            }
        )
        websocket.send_json(
            {
                "type": "user_text_turn",
                "turn_id": "turn_new",
                "text": "Hallo Manfred, bist du da?",
                "personal_memory_enabled": False,
            }
        )
        messages = []
        for _ in range(14):
            message = websocket.receive_json()
            messages.append(message)
            if message.get("type") == "turn_complete" and message.get("turn_id") == "turn_new":
                break

    assert not any(message.get("message") == "too_many_active_turns" for message in messages)
    assert any(message.get("type") == "cancelled" and message.get("turn_id") == "turn_old" for message in messages)
    assert any(message.get("type") == "answer" and message.get("turn_id") == "turn_new" and message.get("text") == "Ja." for message in messages)
    assert any(message.get("type") == "turn_complete" and message.get("turn_id") == "turn_new" for message in messages)


def test_memorial_realtime_supports_multiple_consecutive_turns_without_state_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    _write_private_voice(
        Path(str(tmp_path / "private")),
        slug,
        {
            "tts_plugin": public_memorials.UNMIXR_TTS_PLUGIN_ID,
            "tts_plugin_voice_id": "manfred-unmixr-test",
            "voice_consent": {
                "status": "approved",
                "scope": ["synthesize", "conversation_turn", "realtime"],
                "authorized_by": "test-family",
                "authorized_at": "2026-06-06T08:00:00Z",
                "source_assets_reviewed": True,
                "revoked": False,
            },
        },
    )

    output_audio = _generated_wav_bytes(textish_seed="Ja.", duration_seconds=0.18)
    asked: list[str] = []
    monkeypatch.setenv("UNMIXR_API_KEY", "unit-test-unmixr-key")

    def _chat_answer(payload, question, *args, **kwargs):
        asked.append(question)
        return {
            "answer": f"Antwort {len(asked)}.",
            "sources": [],
            "llm_model": "memorial_guardrail",
            "llm_provider": "memorial_guardrail",
            "llm_request_model": "ea-gemini-flash",
            "llm_fallback_used": False,
        }

    monkeypatch.setattr(public_memorials, "_memorial_chat_answer", _chat_answer)
    monkeypatch.setattr(
        public_memorials,
        "unmixr_synthesize_request",
        lambda **kwargs: (output_audio, "audio/wav"),
    )
    monkeypatch.setattr(
        public_memorials,
        "_pad_speech_audio_lead_in",
        lambda *, payload, content_type, silence_ms, tail_silence_ms, extra_filters: (payload, content_type),
    )

    client = _client(principal_id="exec-memorial-live-consecutive-turns")

    turns = [
        ("turn_1", "Hallo Manfred, kannst du jetzt mit mir sprechen?"),
        ("turn_2", "Was war dir bei Gerechtigkeit wichtig?"),
        ("turn_3", "Und was war dir bei Verantwortung wichtig?"),
        ("turn_4", "Wie hättest du das Susanna erklärt?"),
        ("turn_5", "Danke, ich höre noch zu."),
    ]

    with client.websocket_connect(f"/memorials/{slug}/realtime") as websocket:
        ready = websocket.receive_json()
        assert ready["type"] == "ready"

        turn_messages: dict[str, list[dict[str, object]]] = {}
        for turn_id, question in turns:
            websocket.send_json(
                {
                    "type": "user_text_turn",
                    "turn_id": turn_id,
                    "text": question,
                    "personal_memory_enabled": False,
                }
            )
            messages: list[dict[str, object]] = []
            for _ in range(12):
                message = websocket.receive_json()
                messages.append(message)
                if message.get("type") in {"turn_complete", "error"} and message.get("turn_id") == turn_id:
                    break
            turn_messages[turn_id] = messages

    assert asked == [question for _, question in turns]
    for index, (turn_id, _) in enumerate(turns, start=1):
        messages = turn_messages[turn_id]
        assert any(message.get("type") == "transcript" and message.get("turn_id") == turn_id for message in messages)
        assert any(message.get("type") == "answer" and message.get("turn_id") == turn_id and message.get("text") == f"Antwort {index}." for message in messages)
        assert any(message.get("type") == "turn_complete" and message.get("turn_id") == turn_id for message in messages)
        assert not any(message.get("type") == "cancelled" for message in messages)
        assert not any(message.get("type") == "error" for message in messages)


def test_memorial_realtime_supports_ten_consecutive_turns_without_reset(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    _write_private_voice(
        Path(str(tmp_path / "private")),
        slug,
        {
            "tts_plugin": public_memorials.UNMIXR_TTS_PLUGIN_ID,
            "tts_plugin_voice_id": "manfred-unmixr-test",
            "voice_consent": {
                "status": "approved",
                "scope": ["synthesize", "conversation_turn", "realtime"],
                "authorized_by": "test-family",
                "authorized_at": "2026-06-06T08:00:00Z",
                "source_assets_reviewed": True,
                "revoked": False,
            },
        },
    )

    output_audio = _generated_wav_bytes(textish_seed="Ja.", duration_seconds=0.18)
    asked: list[str] = []
    monkeypatch.setenv("UNMIXR_API_KEY", "unit-test-unmixr-key")

    def _chat_answer(payload, question, *args, **kwargs):
        asked.append(question)
        return {
            "answer": f"Antwort lang {len(asked)}.",
            "sources": [],
            "llm_model": "memorial_guardrail",
            "llm_provider": "memorial_guardrail",
            "llm_request_model": "ea-gemini-flash",
            "llm_fallback_used": False,
        }

    monkeypatch.setattr(public_memorials, "_memorial_chat_answer", _chat_answer)
    monkeypatch.setattr(
        public_memorials,
        "unmixr_synthesize_request",
        lambda **kwargs: (output_audio, "audio/wav"),
    )
    monkeypatch.setattr(
        public_memorials,
        "_pad_speech_audio_lead_in",
        lambda *, payload, content_type, silence_ms, tail_silence_ms, extra_filters: (payload, content_type),
    )

    client = _client(principal_id="exec-memorial-live-ten-turn-soak")
    turns = [(f"turn_{index}", f"Frage Nummer {index} an Manfred?") for index in range(1, 11)]

    with client.websocket_connect(f"/memorials/{slug}/realtime") as websocket:
        ready = websocket.receive_json()
        assert ready["type"] == "ready"

        for index, (turn_id, question) in enumerate(turns, start=1):
            websocket.send_json(
                {
                    "type": "user_text_turn",
                    "turn_id": turn_id,
                    "text": question,
                    "personal_memory_enabled": False,
                }
            )
            messages: list[dict[str, object]] = []
            for _ in range(16):
                message = websocket.receive_json()
                messages.append(message)
                if message.get("type") in {"turn_complete", "error"} and message.get("turn_id") == turn_id:
                    break
            assert any(message.get("type") == "transcript" and message.get("turn_id") == turn_id for message in messages)
            assert any(
                message.get("type") == "answer"
                and message.get("turn_id") == turn_id
                and message.get("text") == f"Antwort lang {index}."
                for message in messages
            )
            assert any(message.get("type") == "turn_complete" and message.get("turn_id") == turn_id for message in messages)
            assert not any(message.get("type") in {"cancelled", "error"} for message in messages)

    assert asked == [question for _, question in turns]


def test_memorial_realtime_cancelled_turn_allows_clean_follow_up_after_interruption(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    _write_private_voice(
        Path(str(tmp_path / "private")),
        slug,
        {
            "tts_plugin": public_memorials.UNMIXR_TTS_PLUGIN_ID,
            "tts_plugin_voice_id": "manfred-unmixr-test",
            "voice_consent": {
                "status": "approved",
                "scope": ["synthesize", "conversation_turn", "realtime"],
                "authorized_by": "test-family",
                "authorized_at": "2026-06-06T08:00:00Z",
                "source_assets_reviewed": True,
                "revoked": False,
            },
        },
    )

    output_audio = _generated_wav_bytes(textish_seed="Ja.", duration_seconds=0.18)
    monkeypatch.setenv("UNMIXR_API_KEY", "unit-test-unmixr-key")

    def _chat_answer(payload, question, *args, **kwargs):
        if "unterbrochen" in question.lower():
            time.sleep(0.25)
            return {
                "answer": "Die langsame Antwort sollte abgebrochen werden.",
                "sources": [],
                "llm_model": "slow-guardrail",
                "llm_provider": "memorial_guardrail",
                "llm_request_model": "ea-gemini-flash",
                "llm_fallback_used": False,
            }
        return {
            "answer": "Ich bin wieder bei dir.",
            "sources": [],
            "llm_model": "memorial_guardrail",
            "llm_provider": "memorial_guardrail",
            "llm_request_model": "ea-gemini-flash",
            "llm_fallback_used": False,
        }

    monkeypatch.setattr(public_memorials, "_memorial_chat_answer", _chat_answer)
    monkeypatch.setattr(
        public_memorials,
        "unmixr_synthesize_request",
        lambda **kwargs: (output_audio, "audio/wav"),
    )
    monkeypatch.setattr(
        public_memorials,
        "_pad_speech_audio_lead_in",
        lambda *, payload, content_type, silence_ms, tail_silence_ms, extra_filters: (payload, content_type),
    )

    client = _client(principal_id="exec-memorial-live-interruption-follow-up")

    with client.websocket_connect(f"/memorials/{slug}/realtime") as websocket:
        ready = websocket.receive_json()
        assert ready["type"] == "ready"
        websocket.send_json(
            {
                "type": "user_text_turn",
                "turn_id": "turn_interrupted",
                "text": "Ich werde gleich unterbrochen.",
                "personal_memory_enabled": False,
            }
        )
        websocket.send_json(
            {
                "type": "cancel_current_turn",
                "turn_id": "turn_interrupted",
                "reason": "user_interrupt",
            }
        )
        interruption_messages = []
        for _ in range(6):
            message = websocket.receive_json()
            interruption_messages.append(message)
            if message.get("type") == "cancelled" and message.get("turn_id") == "turn_interrupted":
                break

        assert any(
            message.get("type") == "transcript" and message.get("turn_id") == "turn_interrupted"
            for message in interruption_messages
        )
        interrupted = next(
            message
            for message in interruption_messages
            if message.get("type") == "cancelled" and message.get("turn_id") == "turn_interrupted"
        )

        websocket.send_json(
            {
                "type": "user_text_turn",
                "turn_id": "turn_follow_up",
                "text": "Hallo Manfred, ich fange nochmal an.",
                "personal_memory_enabled": False,
            }
        )
        messages = [interrupted]
        for _ in range(12):
            message = websocket.receive_json()
            messages.append(message)
            if message.get("type") in {"turn_complete", "error"} and message.get("turn_id") == "turn_follow_up":
                break

    assert any(message.get("type") == "answer" and message.get("turn_id") == "turn_follow_up" and message.get("text") == "Ich bin wieder bei dir." for message in messages)
    assert any(message.get("type") == "turn_complete" and message.get("turn_id") == "turn_follow_up" for message in messages)
    assert not any(message.get("type") == "answer" and message.get("turn_id") == "turn_interrupted" for message in messages)


def test_memorial_realtime_new_turn_preempts_inflight_reply_without_explicit_cancel(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    _write_private_voice(
        Path(str(tmp_path / "private")),
        slug,
        {
            "tts_plugin": public_memorials.UNMIXR_TTS_PLUGIN_ID,
            "tts_plugin_voice_id": "manfred-unmixr-test",
            "voice_consent": {
                "status": "approved",
                "scope": ["synthesize", "conversation_turn", "realtime"],
                "authorized_by": "test-family",
                "authorized_at": "2026-06-06T08:00:00Z",
                "source_assets_reviewed": True,
                "revoked": False,
            },
        },
    )

    output_audio = _generated_wav_bytes(textish_seed="Ja.", duration_seconds=0.18)
    monkeypatch.setenv("UNMIXR_API_KEY", "unit-test-unmixr-key")

    def _chat_answer(payload, question, *args, **kwargs):
        if "langsame" in question.lower():
            time.sleep(0.25)
            return {
                "answer": "Diese Antwort darf nicht mehr ankommen.",
                "sources": [],
                "llm_model": "slow-guardrail",
                "llm_provider": "memorial_guardrail",
                "llm_request_model": "ea-gemini-flash",
                "llm_fallback_used": False,
            }
        return {
            "answer": "Ich bin bei deiner neuen Frage.",
            "sources": [],
            "llm_model": "memorial_guardrail",
            "llm_provider": "memorial_guardrail",
            "llm_request_model": "ea-gemini-flash",
            "llm_fallback_used": False,
        }

    monkeypatch.setattr(public_memorials, "_memorial_chat_answer", _chat_answer)
    monkeypatch.setattr(
        public_memorials,
        "unmixr_synthesize_request",
        lambda **kwargs: (output_audio, "audio/wav"),
    )
    monkeypatch.setattr(
        public_memorials,
        "_pad_speech_audio_lead_in",
        lambda *, payload, content_type, silence_ms, tail_silence_ms, extra_filters: (payload, content_type),
    )

    client = _client(principal_id="exec-memorial-live-preempt-follow-up")

    with client.websocket_connect(f"/memorials/{slug}/realtime") as websocket:
        ready = websocket.receive_json()
        assert ready["type"] == "ready"
        websocket.send_json(
            {
                "type": "user_text_turn",
                "turn_id": "turn_old",
                "text": "Ich habe eine langsame Frage.",
                "personal_memory_enabled": False,
            }
        )

        old_turn_messages = []
        for _ in range(6):
            message = websocket.receive_json()
            old_turn_messages.append(message)
            if message.get("turn_id") == "turn_old" and message.get("type") in {"transcript", "phase"}:
                break

        websocket.send_json(
            {
                "type": "user_text_turn",
                "turn_id": "turn_new",
                "text": "Hallo Manfred, antworte mir jetzt direkt.",
                "personal_memory_enabled": False,
            }
        )

        messages = list(old_turn_messages)
        for _ in range(14):
            message = websocket.receive_json()
            messages.append(message)
            if message.get("type") in {"turn_complete", "error"} and message.get("turn_id") == "turn_new":
                break

    assert any(message.get("type") == "cancelled" and message.get("turn_id") == "turn_old" for message in messages)
    assert not any(message.get("type") == "answer" and message.get("turn_id") == "turn_old" for message in messages)
    assert any(
        message.get("type") == "answer"
        and message.get("turn_id") == "turn_new"
        and message.get("text") == "Ich bin bei deiner neuen Frage."
        for message in messages
    )
    assert any(message.get("type") == "turn_complete" and message.get("turn_id") == "turn_new" for message in messages)


def test_memorial_realtime_cancel_during_streaming_audio_allows_clean_follow_up(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    _write_private_voice(
        Path(str(tmp_path / "private")),
        slug,
        {
            "tts_plugin": public_memorials.UNMIXR_TTS_PLUGIN_ID,
            "tts_plugin_voice_id": "manfred-unmixr-test",
            "voice_consent": {
                "status": "approved",
                "scope": ["synthesize", "conversation_turn", "realtime"],
                "authorized_by": "test-family",
                "authorized_at": "2026-06-06T08:00:00Z",
                "source_assets_reviewed": True,
                "revoked": False,
            },
        },
    )

    large_audio = b"\x00" * 120_000
    monkeypatch.setenv("UNMIXR_API_KEY", "unit-test-unmixr-key")

    def _chat_answer(payload, question, *args, **kwargs):
        if "zweite" in question.lower():
            return {
                "answer": "Ich antworte jetzt auf deinen zweiten Punkt.",
                "sources": [],
                "llm_model": "memorial_guardrail",
                "llm_provider": "memorial_guardrail",
                "llm_request_model": "ea-gemini-flash",
                "llm_fallback_used": False,
            }
        return {
            "answer": "Diese erste lange Antwort sollte unterbrochen werden.",
            "sources": [],
            "llm_model": "memorial_guardrail",
            "llm_provider": "memorial_guardrail",
            "llm_request_model": "ea-gemini-flash",
            "llm_fallback_used": False,
        }

    monkeypatch.setattr(public_memorials, "_memorial_chat_answer", _chat_answer)
    monkeypatch.setattr(
        public_memorials,
        "unmixr_synthesize_request",
        lambda **kwargs: (large_audio, "audio/wav"),
    )
    monkeypatch.setattr(
        public_memorials,
        "_pad_speech_audio_lead_in",
        lambda *, payload, content_type, silence_ms, tail_silence_ms, extra_filters: (payload, content_type),
    )

    client = _client(principal_id="exec-memorial-live-stream-cancel-follow-up")

    with client.websocket_connect(f"/memorials/{slug}/realtime") as websocket:
        ready = websocket.receive_json()
        assert ready["type"] == "ready"
        websocket.send_json(
            {
                "type": "user_text_turn",
                "turn_id": "turn_stream_old",
                "text": "Erster langer Punkt.",
                "personal_memory_enabled": False,
            }
        )

        messages: list[dict[str, object]] = []
        for _ in range(16):
            message = websocket.receive_json()
            messages.append(message)
            if message.get("type") == "audio_chunk" and message.get("turn_id") == "turn_stream_old":
                break

        websocket.send_json(
            {
                "type": "cancel_current_turn",
                "turn_id": "turn_stream_old",
                "reason": "user_interrupt",
            }
        )
        for _ in range(8):
            message = websocket.receive_json()
            messages.append(message)
            if message.get("type") == "cancelled" and message.get("turn_id") == "turn_stream_old":
                break

        websocket.send_json(
            {
                "type": "user_text_turn",
                "turn_id": "turn_stream_new",
                "text": "Zweite Frage direkt danach.",
                "personal_memory_enabled": False,
            }
        )

        for _ in range(16):
            message = websocket.receive_json()
            messages.append(message)
            if message.get("type") in {"turn_complete", "error"} and message.get("turn_id") == "turn_stream_new":
                break

    assert any(message.get("type") == "audio_chunk" and message.get("turn_id") == "turn_stream_old" for message in messages)
    assert any(message.get("type") == "cancelled" and message.get("turn_id") == "turn_stream_old" for message in messages)
    assert not any(message.get("type") == "audio_complete" and message.get("turn_id") == "turn_stream_old" for message in messages)
    assert any(
        message.get("type") == "answer"
        and message.get("turn_id") == "turn_stream_new"
        and message.get("text") == "Ich antworte jetzt auf deinen zweiten Punkt."
        for message in messages
    )
    assert any(message.get("type") == "turn_complete" and message.get("turn_id") == "turn_stream_new" for message in messages)


def test_memorial_realtime_text_turn_rewrites_generic_fallback_answer_to_retry_prompt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    _write_private_voice(
        Path(str(tmp_path / "private")),
        slug,
        {
            "tts_plugin": public_memorials.UNMIXR_TTS_PLUGIN_ID,
            "tts_plugin_voice_id": "manfred-unmixr-test",
            "voice_consent": {
                "status": "approved",
                "scope": ["synthesize", "conversation_turn", "realtime"],
                "authorized_by": "test-family",
                "authorized_at": "2026-06-06T08:00:00Z",
                "source_assets_reviewed": True,
                "revoked": False,
            },
        },
    )

    output_audio = _generated_wav_bytes(textish_seed="Bitte sag es noch einmal.")
    monkeypatch.setenv("UNMIXR_API_KEY", "unit-test-unmixr-key")

    monkeypatch.setattr(
        public_memorials,
        "_memorial_chat_answer",
        lambda *args, **kwargs: {
            "answer": (
                "Sag mir den konkreten Punkt noch etwas enger. "
                "Dann antworte ich dir direkt darauf und nicht allgemein drum herum."
            ),
            "sources": [],
            "llm_model": "ea-gemini-flash",
            "llm_provider": "gemini_vortex",
            "llm_request_model": "ea-gemini-flash",
            "llm_fallback_used": False,
            "fallback_reason": "upstream_unavailable:test",
        },
    )
    monkeypatch.setattr(
        public_memorials,
        "unmixr_synthesize_request",
        lambda **kwargs: (output_audio, "audio/wav"),
    )
    monkeypatch.setattr(
        public_memorials,
        "_pad_speech_audio_lead_in",
        lambda *, payload, content_type, silence_ms, tail_silence_ms, extra_filters: (payload, content_type),
    )

    client = _client(principal_id="exec-memorial-live-realtime-generic-retry")

    with client.websocket_connect(f"/memorials/{slug}/realtime") as websocket:
        ready = websocket.receive_json()
        assert ready["type"] == "ready"
        websocket.send_json(
            {
                "type": "user_text_turn",
                "turn_id": "turn_retry_guardrail",
                "text": "Bis zum nächsten Mal.",
                "personal_memory_enabled": False,
            }
        )
        messages = []
        for _ in range(20):
            message = websocket.receive_json()
            messages.append(message)
            if message.get("type") in {"turn_complete", "error"} and message.get("turn_id") == "turn_retry_guardrail":
                break

    answer_message = next(
        message
        for message in messages
        if message.get("type") == "answer" and message.get("turn_id") == "turn_retry_guardrail"
    )

    assert answer_message["text"] == "Meine Antwort war gerade technisch nicht sauber. Sag es bitte noch einmal."
    assert "konkreten Punkt" not in answer_message["text"]


def test_memorial_voice_chat_model_prefers_ea_fast_for_live_interaction() -> None:
    from app.api.routes import public_memorials

    selected = public_memorials._resolve_memorial_voice_chat_model(
        {"chat_models": [GEMINI_VORTEX_PUBLIC_MODEL, "ea-coder-fast", "deepseek-chat"]},
        {},
        "Hallo Manfred, kannst du kurz direkt mit mir reden?",
    )

    assert selected == public_memorials.FAST_PUBLIC_MODEL


def test_memorial_voice_chat_model_prefers_catalog_fast_for_live_interaction() -> None:
    from app.api.routes import public_memorials

    selected = public_memorials._resolve_memorial_voice_chat_model(
        {"chat_models": ["ea-coder-fast", "deepseek-chat"]},
        {},
        "Hallo Manfred, kannst du kurz direkt mit mir reden?",
    )

    assert selected == public_memorials.FAST_PUBLIC_MODEL


def test_memorial_voice_chat_model_keeps_memorial_local_fast_as_default_non_live_choice() -> None:
    from app.api.routes import public_memorials

    selected = public_memorials._resolve_memorial_voice_chat_model(
        {"chat_models": ["memorial-local-fast", GEMINI_VORTEX_PUBLIC_MODEL, "ea-coder-fast"]},
        {},
        "Erzaehl mir etwas ueber deine Jugend.",
    )

    assert selected == "memorial-local-fast"


def test_memorial_voice_chat_model_prefers_ea_fast_before_gemini_for_non_live_turns() -> None:
    from app.api.routes import public_memorials

    selected = public_memorials._resolve_memorial_voice_chat_model(
        {"chat_models": [GEMINI_VORTEX_PUBLIC_MODEL, "ea-coder-fast", "deepseek-chat"]},
        {},
        "Erzaehl mir etwas ueber deine Jugend.",
    )

    assert selected == "ea-coder-fast"


def test_memorial_voice_chat_model_uses_gemini_live_fallback_without_explicit_model_catalog() -> None:
    from app.api.routes import public_memorials

    selected = public_memorials._resolve_memorial_voice_chat_model(
        {},
        {},
        "Hallo Manfred, kann ich jetzt mit dir reden?",
    )

    assert selected == GEMINI_VORTEX_PUBLIC_MODEL


def test_memorial_realtime_chat_model_prefers_local_fast_when_available() -> None:
    from app.api.routes import public_memorials

    selected = public_memorials._resolve_memorial_realtime_chat_model(
        {"chat_models": ["memorial-local-fast", "ea-coder-best"]},
        {},
    )

    assert selected == "memorial-local-fast"


def test_memorial_realtime_chat_model_uses_configured_default_without_fast_catalog_entry() -> None:
    from app.api.routes import public_memorials

    selected = public_memorials._resolve_memorial_realtime_chat_model({}, {})

    assert selected == public_memorials.DEFAULT_PUBLIC_MODEL


def test_memorial_realtime_timeout_copy_invites_retry_without_sounding_like_a_failure() -> None:
    source = PUBLIC_MEMORIALS_SOURCE.read_text(encoding="utf-8")

    assert "Ich bin noch da, aber gerade etwas langsamer. Bitte sag es noch einmal." in source
    assert "Ich brauche gerade laenger als erwartet. Bitte sprich noch einmal." not in source


def test_memorial_local_fast_fallback_keeps_requested_model_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    monkeypatch.setattr(
        public_memorials,
        "generate_text",
        lambda **kwargs: SimpleNamespace(
            text="In meiner Jugend war ich frueh auf Ordnung und Eigenstaendigkeit ausgerichtet.",
            provider_key="unit-test-model",
            model="memorial-local-fast",
        ),
    )

    answer = public_memorials._memorial_chat_answer(
        {"slug": slug, "person_name": "Manfred Hoza", "audio_clips": []},
        "Erzaehl mir etwas ueber deine Jugend.",
        {},
        "memorial-local-fast",
        slug=slug,
    )

    assert answer["llm_model"] == "memorial-local-fast"
    assert answer["llm_provider"] == "unit-test-model"
    assert answer["llm_request_model"] == "memorial-local-fast"
    assert answer["llm_fallback_used"] is False
    assert "Jugend" in answer["answer"] or "jugend" in answer["answer"].lower()


def test_memorial_generic_fallback_answer_does_not_default_to_schach_und_familie() -> None:
    from app.api.routes import public_memorials

    answer = public_memorials._memorial_chat_fallback_answer(
        {"slug": "manfred", "person_name": "Manfred Hoza", "audio_clips": []},
        "Was meinst du damit genau?",
        {},
        slug="manfred",
        memory_runtime=None,
        personal_memory_context=None,
        llm_model="memorial-local-fast",
        fallback_reason="upstream_unavailable:test",
        difficult_memory_mode=False,
    )

    lowered = answer["answer"].lower()
    assert "belegt ist hier vor allem" not in lowered
    assert "schach" not in lowered
    assert "familie" not in lowered


def test_memorial_multi_question_transcript_gets_single_question_retry_guardrail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    payload = public_memorials._load_memorial(slug)
    private_profile = public_memorials._load_private_profile(slug)

    answer = public_memorials._memorial_chat_answer(
        payload,
        "Ich möchte fragen, wie das Wetter bei dir ist, dort wo du jetzt bist. "
        "Kommt da noch was oder bist du jetzt stumm? Vielleicht eine andere Frage. "
        "Wie stehst du zur Covid-Impfung? Okay, wie ist das Wetter dort, wo du gerade bist?",
        private_profile,
        "ea-gemini-flash",
        slug=slug,
        memory_runtime=None,
        personal_memory_context=None,
        difficult_memory_mode=False,
    )

    assert answer["fallback_reason"] == "multi_question_retry_required"
    assert answer["llm_provider"] == "memorial_guardrail"
    assert "mehrere Fragen" in answer["answer"]
    assert "letzte Frage" in answer["answer"]


def test_memorial_values_question_replaces_vague_model_answer_with_values_guardrail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    monkeypatch.setattr(
        public_memorials,
        "generate_text",
        lambda **kwargs: SimpleNamespace(
            text="Sag mir den konkreten Punkt noch etwas enger. Dann antworte ich dir direkt darauf und nicht allgemein drum herum.",
            provider_key="unit-test-model",
            model="ea-gemini-flash",
        ),
    )

    answer = public_memorials._memorial_chat_answer(
        {"slug": slug, "person_name": "Manfred Hoza", "audio_clips": []},
        "Was war dir bei Gerechtigkeit wichtig?",
        {},
        "ea-gemini-flash",
        slug=slug,
    )

    lowered = answer["answer"].lower()
    assert answer["llm_fallback_used"] is True
    assert answer["fallback_reason"] == "memorial_values_guardrail"
    assert "konkreten punkt" not in lowered
    assert any(token in lowered for token in ("rechtlich", "prinzip", "bequemlichkeit", "massstab", "juristisch"))


def test_memorial_warmup_route_schedules_background_prewarm(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    seen: list[str] = []

    monkeypatch.setattr(
        public_memorials,
        "_schedule_memorial_live_warmup",
        lambda warmup_slug: seen.append(warmup_slug) or {"status": "queued", "scheduled": True, "ttl_seconds": 600},
    )

    client = _client(principal_id="exec-memorial-warmup")
    response = client.post(f"/memorials/{slug}/warmup", json={"reason": "page_load"})

    assert response.status_code == 202
    assert response.json() == {
        "slug": slug,
        "status": "queued",
        "scheduled": True,
        "ttl_seconds": 600,
    }
    assert seen == [slug]


def test_public_memorial_page_does_not_prime_warmup_before_conversation_start(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    seen: list[str] = []
    monkeypatch.setattr(
        public_memorials,
        "_schedule_memorial_live_warmup",
        lambda warmup_slug: seen.append(warmup_slug) or {"status": "queued", "scheduled": True, "ttl_seconds": 600},
    )

    client = _client(principal_id="exec-memorial-page-prime")
    response = client.get(f"/memorials/{slug}")

    assert response.status_code == 200
    assert "Gespräch beginnen" in response.text
    assert seen == []


def test_memorial_warmup_route_enforces_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    seen: list[str] = []

    monkeypatch.setattr(
        public_memorials,
        "_enforce_public_memorial_rate_limit",
        lambda bucket, **kwargs: seen.append(bucket),
    )
    monkeypatch.setattr(
        public_memorials,
        "_schedule_memorial_live_warmup",
        lambda warmup_slug: {"status": "queued", "scheduled": True, "ttl_seconds": 600},
    )

    client = _client(principal_id="exec-memorial-warmup-rate")
    response = client.post(f"/memorials/{slug}/warmup", json={"reason": "page_load"})

    assert response.status_code == 202
    assert seen == ["warmup"]


def test_memorial_warmup_route_rate_limit_uses_memorial_error_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    monkeypatch.setattr(
        public_memorials,
        "_enforce_public_memorial_rate_limit",
        lambda *args, **kwargs: (_ for _ in ()).throw(public_memorials.HTTPException(status_code=429, detail="memorial_rate_limited")),
    )

    client = _client(principal_id="exec-memorial-warmup-rate-error")
    response = client.post(f"/memorials/{slug}/warmup", json={"reason": "page_load"})

    assert response.status_code == 429
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert response.json()["error"]["code"] == "memorial_rate_limited"


def test_memorial_warmup_status_route_reports_snapshot_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    monkeypatch.setattr(public_memorials.time, "time", lambda: 145.0)
    monkeypatch.setattr(
        public_memorials,
        "_memorial_live_warmup_snapshot",
        lambda warmup_slug: {
            "status": "warm_recent",
            "warm": True,
            "inflight": False,
            "started_at": 123.0,
            "completed_at": 145.0,
            "warmup_age_seconds": 0.0,
            "warmup_completed_age_seconds": 0.0,
            "expires_at": 745.0,
            "ttl_remaining_seconds": 600.0,
            "errors": [],
            "voice_ready": True,
            "voice_inflight": False,
            "voice_prewarm_state": "ready",
            "voice_prewarm_stale": False,
            "voice_prewarm_stale_in_seconds": 0.0,
            "voice_completed_at": 145.0,
            "voice_expires_at": 745.0,
            "voice_ttl_remaining_seconds": 600.0,
            "voice_errors": [],
            "voice_required": True,
        },
    )

    client = _client(principal_id="exec-memorial-warmup-status")
    response = client.get(f"/memorials/{slug}/warmup-status")

    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert response.json() == {
        "slug": slug,
        "status": "warm_recent",
        "warm": True,
        "inflight": False,
        "started_at": 123.0,
        "completed_at": 145.0,
        "warmup_age_seconds": 0.0,
        "warmup_completed_age_seconds": 0.0,
        "expires_at": 745.0,
        "ttl_remaining_seconds": 600.0,
        "errors": [],
        "voice_ready": True,
        "voice_inflight": False,
        "voice_prewarm_state": "ready",
        "voice_started_at": 0.0,
        "voice_age_seconds": 0.0,
        "voice_prewarm_stale": False,
        "voice_prewarm_stale_in_seconds": 0.0,
        "voice_completed_at": 145.0,
        "voice_duration_seconds": 0.0,
        "voice_completed_age_seconds": 0.0,
        "voice_expires_at": 745.0,
        "voice_ttl_remaining_seconds": 600.0,
        "voice_errors": [],
        "voice_required": True,
        "voice_recovery": {"attempted": False, "scheduled": False, "reason": "", "at": 0.0, "age_seconds": 0.0},
        "ttl_seconds": 600,
        "ready": True,
        "interaction_mode": "spoken_turn_fallback",
        "spoken_voice_ready": True,
        "realtime_ready": False,
        "readiness_checked_at": 145.0,
        "readiness_expires_at": 745.0,
        "readiness_ttl_remaining_seconds": 600.0,
        "readiness_ttl_state": "fresh",
        "readiness_refresh_recommended": False,
        "degraded_reasons": ["realtime_backend_unavailable"],
        "next_actions": ["check_memorial_realtime_backend", "continue_with_spoken_turn_fallback"],
        "operator_attention_recommended": True,
        "operator_action_required": False,
        "operator_action_state": "attention",
        "operator_recheck_after_seconds": 60,
    }


def test_memorial_warmup_status_missing_slug_uses_memorial_error_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(tmp_path / "public"))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-warmup-status-missing")
    response = client.get("/memorials/not-found/warmup-status")

    assert response.status_code == 404
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert response.json()["error"]["code"] == "memorial_not_found"


def test_memorial_readiness_route_reports_degraded_runtime_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    monkeypatch.setattr(
        public_memorials,
        "_memorial_runtime_readiness",
        lambda readiness_slug: {
            "slug": readiness_slug,
            "status": "degraded_realtime",
            "surface_ready": True,
            "spoken_voice_ready": True,
            "realtime_ready": False,
            "ready": True,
            "degraded_reasons": ["realtime_backend_unavailable"],
            "warmup": {"warm": True},
            "surface_probe": {"slug": readiness_slug, "person_name": "Manfred Hoza"},
            "voice": {
                "tts_plugin": "unmixr",
                "tts_plugin_enabled": True,
                "voice_profile_ready": True,
            },
            "models": {
                "conversation_model": "gpt-5.4",
                "realtime_backend": "",
            },
            "operator_write_configured": False,
            "next_actions": ["check_memorial_realtime_backend", "continue_with_spoken_turn_fallback"],
            "readiness_checked_at": 145.0,
            "readiness_ttl_state": "fresh",
            "readiness_refresh_recommended": False,
            "operator_attention_recommended": True,
            "operator_action_required": False,
            "operator_action_state": "attention",
            "operator_recheck_after_seconds": 60,
        },
    )

    client = _client(principal_id="exec-memorial-readiness")
    response = client.get(f"/memorials/{slug}/readiness")

    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.json()["status"] == "degraded_realtime"
    assert response.json()["ready"] is True
    assert response.json()["realtime_ready"] is False
    assert response.json()["degraded_reasons"] == ["realtime_backend_unavailable"]
    assert response.json()["next_actions"] == ["check_memorial_realtime_backend", "continue_with_spoken_turn_fallback"]
    assert response.json()["readiness_checked_at"] == 145.0
    assert response.json()["operator_attention_recommended"] is True
    assert response.json()["operator_action_required"] is False
    assert response.json()["operator_action_state"] == "attention"
    assert response.json()["operator_recheck_after_seconds"] == 60


def test_memorial_readiness_rechecks_release_and_invalidates_cache_after_allowed_load(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    release = {
        "allowed": True,
        "status": "released",
        "reason": "",
        "receipt_status": "accepted",
        "provider_work_allowed": True,
    }
    runtime_calls: list[str] = []
    cache_invalidations: list[str] = []
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_release_enforced",
        lambda: True,
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_release_decision",
        lambda _slug: dict(release),
    )
    monkeypatch.setattr(
        public_memorials,
        "_support_require_voice_consent",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_runtime_readiness_cache_invalidate",
        lambda cache_slug: cache_invalidations.append(cache_slug),
    )

    def _runtime_readiness(readiness_slug: str) -> dict[str, object]:
        runtime_calls.append(readiness_slug)
        return {
            "slug": readiness_slug,
            "status": "ready",
            "surface_ready": True,
            "spoken_voice_ready": True,
            "realtime_ready": True,
            "ready": True,
            "degraded_reasons": [],
            "release": dict(release),
        }

    monkeypatch.setattr(
        public_memorials,
        "_memorial_runtime_readiness",
        _runtime_readiness,
    )
    client = _client(principal_id="exec-memorial-readiness-revocation")

    allowed = client.get(f"/memorials/{slug}/readiness")
    assert allowed.status_code == 200
    assert allowed.json()["release"]["allowed"] is True

    release.update(
        {
            "allowed": False,
            "status": "blocked",
            "reason": "release_revoked",
            "receipt_status": "revoked",
        }
    )
    revoked = client.get(f"/memorials/{slug}/readiness")

    assert revoked.status_code == 409
    assert revoked.json()["error"]["code"] == "memorial_voice_release_not_verified"
    assert runtime_calls == [slug]
    assert cache_invalidations == [slug, slug]


def test_memorial_readiness_missing_slug_uses_memorial_error_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(tmp_path / "public"))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-readiness-missing")
    response = client.get("/memorials/not-found/readiness")

    assert response.status_code == 404
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert response.json()["error"]["code"] == "memorial_not_found"


def test_memorial_playback_telemetry_route_accepts_client_signal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    client = _client(principal_id="exec-memorial-playback-telemetry")

    response = client.post(
        f"/memorials/{slug}/playback-telemetry",
        json={
            "event": "fallback",
            "context": "realtime_turn",
            "reason": "audio_never_started",
            "plugin": "realtime_stream",
            "fallback_plugin": "browser_speech_synthesis",
            "playback_started": False,
            "elapsed_ms": 2210.4,
            "expected_ms": 5310.0,
            "audio_bytes": 587054,
            "text": "Hallo Manfred, sprich bitte ganz kurz direkt mit mir.",
        },
    )

    assert response.status_code == 202
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert response.json() == {"status": "accepted"}


def test_memorial_playback_telemetry_route_enforces_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    seen: list[str] = []
    monkeypatch.setattr(
        public_memorials,
        "_enforce_public_memorial_rate_limit",
        lambda bucket, **kwargs: seen.append(bucket),
    )

    client = _client(principal_id="exec-memorial-playback-telemetry-rate")
    response = client.post(f"/memorials/{slug}/playback-telemetry", json={"event": "fallback"})

    assert response.status_code == 202
    assert seen == ["playback_telemetry"]


def test_memorial_playback_telemetry_rate_limit_uses_memorial_error_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    monkeypatch.setattr(
        public_memorials,
        "_enforce_public_memorial_rate_limit",
        lambda *args, **kwargs: (_ for _ in ()).throw(public_memorials.HTTPException(status_code=429, detail="memorial_rate_limited")),
    )

    client = _client(principal_id="exec-memorial-playback-telemetry-rate-error")
    response = client.post(f"/memorials/{slug}/playback-telemetry", json={"event": "fallback"})

    assert response.status_code == 429
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert response.json()["error"]["code"] == "memorial_rate_limited"


def test_memorial_voice_clone_route_is_disabled_without_operator_surface_flag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    monkeypatch.delenv("EA_ENABLE_PUBLIC_MEMORIAL_OPERATOR_SURFACES", raising=False)
    client = _client(principal_id="exec-memorial-clone-disabled")

    response = client.post(f"/memorials/{slug}/voice-clone", json={"voice_label": "Test"})

    assert response.status_code == 404
    assert "memorial_operator_surface_disabled" in response.text


def test_memorial_browser_playback_guardrails_are_shipped() -> None:
    source = PUBLIC_MEMORIALS_SOURCE.read_text(encoding="utf-8")

    assert "audio_never_started" in source
    assert "audio_ended_too_soon" in source
    assert "/memorials/{html.escape(slug)}/playback-telemetry" in source
    assert "Manfreds Stimme konnte gerade nicht sauber starten." in source
    assert "Audio war gerade unzuverlaessig. Ich wechsle auf Browser-Stimme." not in source


def test_memorial_realtime_public_error_codes_are_stable() -> None:
    from app.api.routes import public_memorials

    assert public_memorials._stable_public_realtime_error(RuntimeError("tts timeout on provider")) == "provider_timeout"
    assert public_memorials._stable_public_realtime_error(RuntimeError("speech transcriber unavailable")) == "speech_transcription_failed"
    assert public_memorials._stable_public_realtime_error(RuntimeError("audio synth failed")) == "tts_unavailable"
    assert public_memorials._stable_public_realtime_error(RuntimeError("unexpected socket drift")) == "realtime_failed"


def test_memorial_live_status_copy_is_quieter_and_less_chattery() -> None:
    source = PUBLIC_MEMORIALS_SOURCE.read_text(encoding="utf-8")

    assert 'transcribingText: "Einen Moment ..."' in source
    assert 'setSpeechStatus("Ich höre zu.", "listening", "Sprich, wenn du magst");' in source
    assert 'setTimeout(recordConversationTurn, 320);' in source
    assert "Ich habe dich sofort. Einen Moment ..." not in source
    assert "Ich habe dich. Einen Moment ..." not in source


def test_memorial_live_page_source_uses_more_tolerant_turn_detection_and_barge_in_restart() -> None:
    source = PUBLIC_MEMORIALS_SOURCE.read_text(encoding="utf-8")

    assert "autoStopMs: 5200" in source
    assert "maxAfterSpeechMs: 5200" in source
    assert "silenceMs: 900" in source
    assert "pauseMs: 360" in source
    assert "autoStopMs: 6800" in source
    assert "maxAfterSpeechMs: 6800" in source
    assert "silenceMs: 1100" in source
    assert "pauseMs: 420" in source
    assert "void startServerSpeechInput();" in source
    assert "return captureServerTranscript(options);" in source
    assert "const maxAfterSpeechMs = Math.max(1800, Number(options.maxAfterSpeechMs || 4200));" in source
    assert "const speechThreshold = Math.max(0.0045, Number(options.silenceThreshold || 0.0075));" in source
    assert "activeSpeechMs > maxAfterSpeechMs" in source
    assert "void resumeConversationAfterBargeIn(\"\");" in source
    assert "const rms = Math.sqrt(sum / data.length);" in source
    assert "if (rms >= 0.028) speechFrames += 1;" in source
    assert "setTimeout(() => {{" in source
    assert "setTimeout(recordConversationTurn, 90);" not in source


def test_memorial_live_page_source_keeps_long_pause_budget_before_forcing_turn_end() -> None:
    source = PUBLIC_MEMORIALS_SOURCE.read_text(encoding="utf-8")

    assert "autoStopMs: 5200" in source
    assert "maxAfterSpeechMs: 5200" in source
    assert "silenceMs: 900" in source
    assert "autoStopMs: 6800" in source
    assert "maxAfterSpeechMs: 6800" in source
    assert "silenceMs: 1100" in source
    assert "const maxAfterSpeechMs = Math.max(1800, Number(options.maxAfterSpeechMs || 4200));" in source
    assert "activeSpeechMs > maxAfterSpeechMs" in source


def test_memorial_live_page_source_accepts_shorter_first_turn_browser_transcripts() -> None:
    source = PUBLIC_MEMORIALS_SOURCE.read_text(encoding="utf-8")

    assert "const looksGreeting =" in source
    assert "const hasSpeechLikeChars = /[a-z0-9äöüß]/i.test(normalized);" in source
    assert "isFirstConversationTurn && hasSpeechLikeChars && normalized.length >= 3" in source
    assert "conversationIdleMisses >= 1 && hasSpeechLikeChars && normalized.length >= 2" in source
    assert "if (!looksDirected && !(conversationIdleMisses >= 1 && normalized.length >= 8 && words.length >= 2)) return false;" in source


def test_memorial_pcm_gate_ignores_low_energy_room_noise() -> None:
    from app.api.routes import public_memorials

    assert not public_memorials._pcm16_payload_has_speech_energy(_pcm16_noise_bytes(sample=96))
    assert not public_memorials._pcm16_payload_has_speech_energy(_pcm16_noise_bytes(sample=160))
    assert not public_memorials._pcm16_payload_has_speech_energy(_pcm16_impulse_burst_bytes())
    assert public_memorials._pcm16_payload_has_speech_energy(_pcm16_speech_bytes(samples=1600, sample=4096))


def test_memorial_live_page_source_does_not_fallback_to_browser_voice_when_realtime_server_audio_is_missing() -> None:
    source = PUBLIC_MEMORIALS_SOURCE.read_text(encoding="utf-8")

    assert 'browserSpeechFallbackConfig("Browser Fallback")' not in source
    assert "Manfreds Stimme konnte gerade nicht sauber starten." in source
    assert '}} else if (conversationActive) {{' in source


def test_memorial_live_page_source_primes_audio_output_before_playback() -> None:
    source = PUBLIC_MEMORIALS_SOURCE.read_text(encoding="utf-8")

    assert "async function primeMemorialAudioOutput(durationMs = 900)" in source
    assert "gain.gain.value = 0.0008;" in source
    assert "await primeMemorialAudioOutput(650);" in source
    assert "void primeMemorialAudioOutput(1200);" in source
    assert "void primeMemorialAudioOutput(900);" in source


def test_memorial_live_page_source_rejects_cut_off_audio_before_next_turn() -> None:
    source = PUBLIC_MEMORIALS_SOURCE.read_text(encoding="utf-8")

    assert "audio_too_short_for_answer" in source
    assert "const tooShortThresholdMs = normalizedText.length >= 36" in source
    assert 'setSpeechStatus("Manfreds Stimme wurde zu kurz wiedergegeben.", "error", "Antwort steht als Text bereit");' in source
    assert 'failPlayback("audio_too_short_for_answer"' in source


def test_memorial_voicewave_postprocess_trims_dead_tail_silence() -> None:
    from app.api.routes import public_memorials

    filters = public_memorials._speech_postprocess_filters_for_config(public_memorials.VOICEWAVE_TTS_PLUGIN_ID)

    assert "silenceremove=stop_periods=-1" in filters
    assert "stop_duration=0.02" in filters
    assert "stop_threshold=-24dB" in filters
    assert "stop_silence=0.005" in filters
    assert "atempo=2.50" in filters


def test_memorial_unmixr_soft_postprocess_profile_is_available() -> None:
    from app.api.routes import public_memorials

    filters = public_memorials._speech_postprocess_filters_for_config(
        public_memorials.UNMIXR_TTS_PLUGIN_ID,
        {"tts_postprocess_profile": "unmixr_natural_soft"},
    )

    assert "highpass=f=45" in filters
    assert "lowpass=f=7000" in filters
    assert "alimiter=limit=0.94" in filters
    assert "acompressor" not in filters
    assert "afftdn" not in filters


def test_memorial_unmixr_minimal_postprocess_profile_is_available() -> None:
    from app.api.routes import public_memorials

    filters = public_memorials._speech_postprocess_filters_for_config(
        public_memorials.UNMIXR_TTS_PLUGIN_ID,
        {"tts_postprocess_profile": "unmixr_natural_minimal"},
    )

    assert "highpass=f=40" in filters
    assert "equalizer=f=190" in filters
    assert "lowpass=f=7600" in filters
    assert "alimiter=limit=0.97" in filters
    assert "acompressor" not in filters
    assert "afftdn" not in filters


def test_memorial_unmixr_realtime_clear_profile_slows_and_preserves_start() -> None:
    from app.api.routes import public_memorials

    filters = public_memorials._speech_postprocess_filters_for_config(
        public_memorials.UNMIXR_TTS_PLUGIN_ID,
        {"tts_postprocess_profile": "unmixr_realtime_clear"},
    )

    assert "highpass=f=38" in filters
    assert "lowpass=f=7200" in filters
    assert "atempo=0.92" in filters
    assert "alimiter=limit=0.95" in filters
    assert "afftdn" not in filters
    assert "acompressor" not in filters


def test_memorial_unmixr_raw_preserve_profile_is_available() -> None:
    from app.api.routes import public_memorials

    filters = public_memorials._speech_postprocess_filters_for_config(
        public_memorials.UNMIXR_TTS_PLUGIN_ID,
        {"tts_postprocess_profile": "unmixr_raw_preserve"},
    )

    assert filters == ""


def test_memorial_speech_transcribe_route_logs_timing_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    monkeypatch.setattr(
        public_memorials,
        "_memorial_transcribe_audio_blob",
        lambda **kwargs: {
            "transcription_status": "transcribed",
            "transcript_text": "Hallo Manfred",
            "transcriber": "unit-test",
        },
    )
    caplog.set_level(logging.INFO, logger=public_memorials.logger.name)
    client = _client(principal_id="exec-memorial-speech-transcribe-log")

    response = client.post(
        f"/memorials/{slug}/speech-transcribe",
        content=_generated_wav_bytes(textish_seed="Hallo Manfred"),
        headers={"content-type": "audio/wav"},
    )

    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    body = response.json()
    assert body["transcript_text"] == "Hallo Manfred, kannst du jetzt mit mir sprechen?"
    assert body["transcript_effective_text"] == "Hallo Manfred, kannst du jetzt mit mir sprechen?"
    assert body["transcript_original_text"] == "Hallo Manfred"
    assert any(
        "memorial_timing event=speech_transcribe" in record.getMessage()
        and "transcript_chars=13" in record.getMessage()
        and "status=transcribed" in record.getMessage()
        for record in caplog.records
    )


def test_memorial_speech_transcribe_route_exposes_original_and_effective_transcript(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    monkeypatch.setattr(
        public_memorials,
        "_memorial_transcribe_audio_blob",
        lambda **kwargs: {
            "transcription_status": "transcribed",
            "transcript_text": "wie ist wetter heute in wien",
            "transcriber": "unit-test",
        },
    )
    client = _client(principal_id="exec-memorial-speech-transcribe-effective")

    response = client.post(
        f"/memorials/{slug}/speech-transcribe",
        content=_generated_wav_bytes(textish_seed="wie ist wetter heute in wien"),
        headers={"content-type": "audio/wav"},
    )

    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    body = response.json()
    assert body["transcript_text"] == "Wie ist das Wetter heute?"
    assert body["transcript_effective_text"] == "Wie ist das Wetter heute?"
    assert body["transcript_original_text"] == "wie ist wetter heute in wien"


def test_memorial_speech_transcribe_oversized_audio_uses_memorial_error_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    client = _client(principal_id="exec-memorial-speech-transcribe-too-large")
    oversized = b"x" * (public_memorials._MAX_SPEECH_UPLOAD_BYTES + 1)

    response = client.post(
        f"/memorials/{slug}/speech-transcribe",
        content=oversized,
        headers={"content-type": "audio/wav"},
    )

    assert response.status_code == 413
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.json()["error"]["code"] == "audio_too_large"


def test_memorial_speech_transcribe_missing_slug_uses_memorial_error_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(tmp_path / "public"))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-speech-transcribe-missing")
    response = client.post("/memorials/not-found/speech-transcribe", content=b"audio")

    assert response.status_code == 404
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert response.json()["error"]["code"] == "memorial_not_found"


def test_memorial_speech_synthesize_help_missing_slug_uses_memorial_error_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(tmp_path / "public"))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-speech-help-missing")
    response = client.get("/memorials/not-found/speech-synthesize")

    assert response.status_code == 404
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert response.json()["error"]["code"] == "memorial_not_found"


def test_memorial_speech_synthesize_missing_slug_uses_memorial_error_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(tmp_path / "public"))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-speech-synthesize-missing")
    response = client.post("/memorials/not-found/speech-synthesize", json={"text": "Hallo"})

    assert response.status_code == 404
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert response.json()["error"]["code"] == "memorial_not_found"


def test_memorial_conversation_turn_missing_slug_uses_memorial_error_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(tmp_path / "public"))
    _patch_memorial_runtime_roots(tmp_path)

    client = _client(principal_id="exec-memorial-conversation-turn-missing")
    response = client.post("/memorials/not-found/conversation-turn", content=b"audio")

    assert response.status_code == 404
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert response.json()["error"]["code"] == "memorial_not_found"


def test_memorial_conversation_turn_success_uses_noindex_headers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorial_turn_support
    from app.api.routes import public_memorials

    _write_private_voice(
        Path(str(tmp_path / "private")),
        slug,
        {
            "tts_plugin": public_memorials.OPENVOICE_TTS_PLUGIN_ID,
            "tts_plugin_voice_id": "manfred-openvoice-test",
            "voice_consent": {
                "status": "approved",
                "scope": ["synthesize", "conversation_turn", "realtime"],
                "authorized_by": "test-family",
                "authorized_at": "2026-06-06T08:00:00Z",
                "source_assets_reviewed": True,
                "revoked": False,
            },
        },
    )

    class _StubTurn:
        def as_public_payload(self) -> dict[str, object]:
            return {
                "answer": "Ja, ich bin da.",
                "transcript_text": "Hallo Manfred",
                "audio_content_type": "audio/wav",
                "audio_base64": base64.b64encode(b"RIFFstub").decode("ascii"),
                "spoken_turn": True,
                "tts_plugin": public_memorials.OPENVOICE_TTS_PLUGIN_ID,
            }

    monkeypatch.setattr(public_memorial_turn_support, "build_public_memorial_turn", lambda **kwargs: _StubTurn())

    client = _client(principal_id="exec-memorial-conversation-turn-headers")
    response = client.post(
        f"/memorials/{slug}/conversation-turn",
        content=_generated_wav_bytes(textish_seed="Hallo Manfred"),
        headers={"content-type": "audio/wav"},
    )

    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert response.json()["answer"] == "Ja, ich bin da."


def test_memorial_speech_transcribe_logs_stt_failures_to_private_bundle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    log_root = tmp_path / "private-stt-errors"
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_ENABLED", "1")
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_DIR", str(log_root))
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_ALLOW_LOCAL", "1")
    monkeypatch.setenv("EA_MEMORIAL_STT_ERROR_LOG_RETENTION_DAYS", "14")
    monkeypatch.setattr(
        public_memorials,
        "_memorial_transcribe_audio_blob",
        lambda **kwargs: {
            "transcription_status": "no_speech",
            "transcript_text": "",
            "transcriber": "local_audio_gate",
            "detail": "audio_silence",
        },
    )
    client = _client(principal_id="exec-memorial-stt-error-bundle")
    input_audio = _generated_wav_bytes(textish_seed="Hallo Manfred")

    response = client.post(
        f"/memorials/{slug}/speech-transcribe",
        content=input_audio,
        headers={"content-type": "audio/wav"},
    )

    assert response.status_code == 200
    bundles = _stt_error_bundles(log_root)
    assert len(bundles) == 1
    metadata = json.loads((bundles[0] / "error.json").read_text(encoding="utf-8"))
    assert metadata["route"] == "speech_transcribe"
    assert metadata["reason"] == "stt_no_speech"
    assert metadata["needs_fix"] is True
    assert metadata["stored_wav"] is True
    assert (bundles[0] / "input.wav").read_bytes() == input_audio


def test_memorial_speech_transcribe_route_accepts_hostile_captured_contact_clip(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials
    from app.product import service as product_service

    _clear_cartesia_env(monkeypatch)
    monkeypatch.setattr(product_service, "_pocket_onemin_api_keys", lambda: ("key-1",))
    monkeypatch.setattr(
        public_memorials,
        "_memorial_shadow_stt_result",
        lambda **kwargs: {
            "enabled": False,
            "provider": "blipai",
            "status": "disabled",
            "transcript_text": "",
            "correction": {"should_correct": False},
        },
    )
    monkeypatch.setattr(
        public_memorials,
        "_convert_audio_to_wav",
        lambda **kwargs: _amplify_wav_bytes(_captured_contact_opening_wav_bytes(), gain=1.08),
    )

    seen_paths: list[str] = []

    def _fake_upload(**kwargs):
        path = f"path-{len(seen_paths) + 1}-{kwargs['filename']}"
        return {"asset": {"key": path}, "fileContent": {"path": path}}

    def _fake_stt(**kwargs):
        audio_path = str(kwargs.get("audio_path") or "")
        seen_paths.append(audio_path)
        if len(seen_paths) == 1:
            return {
                "aiRecord": {
                    "status": "SUCCESS",
                    "aiRecordDetail": {
                        "responseObject": {
                            "text": "Untertitel der Amara.org-Community"
                        }
                    },
                }
            }
        return {
            "aiRecord": {
                "status": "SUCCESS",
                "aiRecordDetail": {
                    "responseObject": {
                        "text": "Hallo Manfred, kannst du jetzt mit mir sprechen?"
                    }
                },
            }
        }

    monkeypatch.setattr(product_service, "_onemin_asset_upload", _fake_upload)
    monkeypatch.setattr(product_service, "_onemin_speech_to_text", _fake_stt)

    client = _client(principal_id="exec-memorial-speech-transcribe-hostile-captured")
    response = client.post(
        f"/memorials/{slug}/speech-transcribe",
        content=_hostile_captured_wav_bytes(_captured_contact_opening_wav_bytes()),
        headers={"content-type": "audio/wav"},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(seen_paths) >= 2
    assert body["transcript_original_text"] == "Hallo Manfred, kannst du jetzt mit mir sprechen?"
    assert body["transcript_text"] == "Hallo Manfred, kannst du jetzt mit mir sprechen?"
    assert body["transcriber"] in {"1min.ai/whisper-1", "1min.ai/whisper-1+enhanced_wav"}


def test_memorial_speech_transcribe_route_rejects_overcompressed_captured_clip_before_provider_upload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.product import service as product_service

    monkeypatch.setattr(product_service, "_pocket_onemin_api_keys", lambda: ("key-1",))

    def _unexpected_upload(**kwargs):
        raise AssertionError("overcompressed clip should not be uploaded to speech provider")

    monkeypatch.setattr(product_service, "_onemin_asset_upload", _unexpected_upload)

    client = _client(principal_id="exec-memorial-speech-transcribe-overcompressed")
    response = client.post(
        f"/memorials/{slug}/speech-transcribe",
        content=_speed_up_wav_bytes(_captured_contact_opening_wav_bytes(), factor=3.2),
        headers={"content-type": "audio/wav"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["transcription_status"] == "no_speech"
    assert body["transcript_text"] == ""
    assert body["transcriber"] == "local_audio_gate"


def test_memorial_warmup_never_uses_piper_or_openvoice_tts() -> None:
    source = PUBLIC_MEMORIALS_SOURCE.read_text(encoding="utf-8")

    assert 'selected_plugin = PIPER_FAST_TTS_PLUGIN_ID' not in source
    assert 'piper_fast_synthesize_request(' not in source
    assert 'openvoice_synthesize_request_with_variant(' not in source
    assert "_schedule_memorial_voicewave_contact_prewarm(" in source
    assert "_schedule_memorial_server_voice_contact_prewarm(" in source


def test_memorial_landing_does_not_enable_conversation_on_warmup_timeout() -> None:
    source = PUBLIC_MEMORIALS_SOURCE.read_text(encoding="utf-8")

    assert "waitForMemorialVoiceReady(30000)" in source
    assert 'setMemorialLandingReady(false, "Ich bin gleich bereit.")' in source
    assert "if (!memorialLandingReady) void primeMemorialLanding();" in source
    assert 'let contactAcknowledgementReady = false;' in source
    assert 'contactAcknowledgementReady = true;' in source
    assert "if (completedConversationTurns === 0 && contactAcknowledgementReady)" in source
    assert "Die kurze Begrüßung ist nicht vorgeladen; das Gespräch bleibt verfügbar." not in source
    assert 'retryButton.dataset.action = "voice-readiness";' in source
    assert 'retryButton.textContent = "Sprachfunktion erneut versuchen";' in source
    assert 'retryButton.textContent = "Stimme erneut prüfen";' not in source
    assert "memorialWarmupPollDelayMs" in source
    assert "memorialLastWarmupStatus" in source
    assert "memorialLastWarmupStatus = payload;" in source
    assert "const retryMs = memorialWarmupPollDelayMs(memorialLastWarmupStatus);" in source
    assert "operator_recheck_after_seconds" in source
    assert "Math.max(700, Math.min(5000" in source
    assert "window.setTimeout(resolve, 900)" not in source
    assert "new Promise((resolve) => window.setTimeout(resolve, 12000))" not in source


def test_memorial_fast_tts_selector_skips_fast_path_for_recently_warm_lane(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.routes import public_memorials

    monkeypatch.setattr(
        public_memorials,
        "_memorial_live_warmup_snapshot",
        lambda warmup_slug: {"status": "warm_recent", "warm": True, "inflight": False, "errors": []},
    )

    prefer_fast_tts, reason = public_memorials._prefer_fast_tts_for_conversation_turn("manfred")

    assert prefer_fast_tts is False
    assert reason == ""


def test_memorial_warmup_probe_wav_bytes_returns_valid_wav() -> None:
    from app.api.routes import public_memorials

    payload = public_memorials._memorial_warmup_probe_wav_bytes()

    assert payload.startswith(b"RIFF")
    assert b"WAVE" in payload[:16]


def test_memorial_warmup_snapshot_marks_recent_errors_as_degraded(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.routes import public_memorials

    now = 1_234_567.0
    monkeypatch.setattr(public_memorials.time, "time", lambda: now)
    monkeypatch.setattr(
        public_memorials,
        "_MEMORIAL_LIVE_WARMUP_STATE",
        {
            "manfred": {
                "inflight": False,
                "started_at": now - 12.0,
                "completed_at": now - 4.0,
                "errors": ["speech:failed"],
            }
        },
    )

    snapshot = public_memorials._memorial_live_warmup_snapshot("manfred")

    assert snapshot["status"] == "degraded_recent"
    assert snapshot["warm"] is False
    assert snapshot["errors"] == ["speech:failed"]


def test_memorial_warmup_snapshot_tracks_voicewave_contact_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.routes import public_memorials

    now = 1_234_567.0
    monkeypatch.setattr(public_memorials.time, "time", lambda: now)
    monkeypatch.setattr(
        public_memorials,
        "_MEMORIAL_LIVE_WARMUP_STATE",
        {
            "manfred": {
                "inflight": False,
                "started_at": now - 30.0,
                "completed_at": now - 8.0,
                "errors": [],
                "voicewave_contact_required": True,
                "voicewave_contact_inflight": True,
                "voicewave_contact_started_at": now - 3.0,
                "voicewave_contact_completed_at": 0.0,
                "voicewave_contact_errors": [],
            }
        },
    )

    snapshot = public_memorials._memorial_live_warmup_snapshot("manfred")

    assert snapshot["status"] == "warming_voice"
    assert snapshot["warm"] is True
    assert snapshot["voice_required"] is True
    assert snapshot["voice_inflight"] is True
    assert snapshot["voice_started_at"] == now - 3.0
    assert snapshot["voice_age_seconds"] == 3.0
    assert snapshot["voice_prewarm_stale"] is False
    assert snapshot["voice_ready"] is False


def test_memorial_warmup_snapshot_tracks_server_voice_contact_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.routes import public_memorials

    now = 1_234_567.0
    monkeypatch.setattr(public_memorials.time, "time", lambda: now)
    monkeypatch.setattr(
        public_memorials,
        "_MEMORIAL_LIVE_WARMUP_STATE",
        {
            "manfred": {
                "inflight": False,
                "started_at": now - 30.0,
                "completed_at": now - 8.0,
                "errors": [],
                "voice_contact_required": True,
                "voice_contact_inflight": True,
                "voice_contact_started_at": now - 4.0,
                "voice_contact_completed_at": 0.0,
                "voice_contact_errors": [],
            }
        },
    )

    snapshot = public_memorials._memorial_live_warmup_snapshot("manfred")

    assert snapshot["status"] == "warming_voice"
    assert snapshot["warm"] is True
    assert snapshot["voice_required"] is True
    assert snapshot["voice_inflight"] is True
    assert snapshot["voice_started_at"] == now - 4.0
    assert snapshot["voice_age_seconds"] == 4.0
    assert snapshot["voice_prewarm_stale"] is False
    assert snapshot["voice_ready"] is False


def test_memorial_server_voice_contact_prewarm_deduplicates_canonical_contact_phrase(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.routes import public_memorials

    monkeypatch.setattr(public_memorials, "_load_voice_config", lambda slug: {"tts_plugin": public_memorials.UNMIXR_TTS_PLUGIN_ID})
    monkeypatch.setattr(
        public_memorials,
        "_tts_plugin_options",
        lambda **kwargs: {public_memorials.UNMIXR_TTS_PLUGIN_ID: {"tts_plugin_enabled": True}},
    )
    monkeypatch.setattr(
        public_memorials,
        "_resolve_server_tts_plugin",
        lambda **kwargs: (public_memorials.UNMIXR_TTS_PLUGIN_ID, {"tts_plugin_enabled": True}),
    )
    seen_texts: list[str] = []
    monkeypatch.setattr(
        public_memorials,
        "_render_memorial_tts_audio",
        lambda **kwargs: seen_texts.append(str(kwargs.get("text") or "")) or (b"audio", "audio/wav"),
    )

    public_memorials._run_memorial_server_voice_contact_prewarm("manfred")

    assert seen_texts == [public_memorials._memorial_contact_answer_body("Bist du da?")]


def test_memorial_server_voice_prewarm_rechecks_after_each_provider_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import HTTPException
    from app.api.routes import public_memorials

    public_memorials._MEMORIAL_LIVE_WARMUP_STATE["manfred"] = {}
    monkeypatch.setattr(
        public_memorials,
        "_load_voice_config",
        lambda _slug: {"tts_plugin": public_memorials.UNMIXR_TTS_PLUGIN_ID},
    )
    monkeypatch.setattr(public_memorials, "_tts_plugin_options", lambda **_kwargs: {})
    monkeypatch.setattr(
        public_memorials,
        "_resolve_server_tts_plugin",
        lambda **_kwargs: (
            public_memorials.UNMIXR_TTS_PLUGIN_ID,
            {"tts_plugin_enabled": True},
        ),
    )
    rendered: list[str] = []

    def _authorize(**_kwargs) -> None:
        if rendered:
            raise HTTPException(
                status_code=409,
                detail="memorial_voice_review_session_expired",
            )

    monkeypatch.setattr(
        public_memorials,
        "_require_memorial_voice_provider_authorization",
        _authorize,
    )
    monkeypatch.setattr(
        public_memorials,
        "_render_memorial_tts_audio",
        lambda **kwargs: rendered.append(str(kwargs["text"]))
        or (b"audio", "audio/wav"),
    )

    public_memorials._run_memorial_server_voice_contact_prewarm("manfred")

    assert len(rendered) == 1
    state = public_memorials._MEMORIAL_LIVE_WARMUP_STATE["manfred"]
    assert state["voice_contact_inflight"] is False
    assert state.get("voice_contact_completed_at", 0.0) == 0.0
    assert state["voice_contact_errors"] == [
        "server_voice_prewarm:409: memorial_voice_review_session_expired"
    ]


def test_memorial_contact_tts_cache_survives_pad_function_identity_change(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.api.routes import public_memorials

    _patch_memorial_runtime_roots(tmp_path)
    text = public_memorials._memorial_contact_answer_body("Bist du da?")
    synth_calls = {"count": 0}

    def _fake_synthesize(**kwargs):
        synth_calls["count"] += 1
        return _generated_wav_bytes(textish_seed=str(kwargs.get("text") or "contact")), "audio/wav"

    monkeypatch.setattr(public_memorials, "unmixr_synthesize_request", _fake_synthesize)
    monkeypatch.setattr(
        public_memorials,
        "_memorial_transcribe_audio_blob",
        lambda **kwargs: {"transcript_text": text, "transcriber": "unit"},
    )

    base_config = {"tts_plugin_voice_id": "voice-1", "lang": "de-AT"}
    merged_config = dict(base_config)
    selected_option = {"tts_plugin_enabled": True, "tts_plugin_voice_id": "voice-1"}

    audio_one, content_type_one = public_memorials._render_memorial_tts_audio(
        slug="manfred",
        text=text,
        merged_config=merged_config,
        base_config=base_config,
        selected_plugin=public_memorials.UNMIXR_TTS_PLUGIN_ID,
        selected_option=selected_option,
        lead_in_ms=public_memorials._MEMORIAL_CONTACT_TTS_LEAD_IN_MS,
        tail_silence_ms=public_memorials._MEMORIAL_CONTACT_TTS_TAIL_SILENCE_MS,
    )

    original_pad = public_memorials._pad_speech_audio_lead_in

    def _replacement_pad(*args, **kwargs):
        return original_pad(*args, **kwargs)

    _replacement_pad.__module__ = original_pad.__module__
    _replacement_pad.__qualname__ = original_pad.__qualname__
    monkeypatch.setattr(public_memorials, "_pad_speech_audio_lead_in", _replacement_pad)
    monkeypatch.setattr(
        public_memorials,
        "unmixr_synthesize_request",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("contact cache should survive restart-like function identity changes")),
    )

    audio_two, content_type_two = public_memorials._render_memorial_tts_audio(
        slug="manfred",
        text=text,
        merged_config=merged_config,
        base_config=base_config,
        selected_plugin=public_memorials.UNMIXR_TTS_PLUGIN_ID,
        selected_option=selected_option,
        lead_in_ms=public_memorials._MEMORIAL_CONTACT_TTS_LEAD_IN_MS,
        tail_silence_ms=public_memorials._MEMORIAL_CONTACT_TTS_TAIL_SILENCE_MS,
    )

    assert synth_calls["count"] == 1
    assert content_type_one == content_type_two == "audio/wav"
    assert audio_one == audio_two


def test_memorial_contact_tts_cache_rejects_pre_locale_policy_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.api.routes import public_memorials

    _patch_memorial_runtime_roots(tmp_path)
    text = public_memorials._memorial_contact_answer_body("Bist du da?")
    base_config = {
        "tts_plugin_voice_id": "voice-1",
        "lang": "de-AT",
        "unmixr_speaking_rate": "0.90",
    }
    merged_config = dict(base_config)
    selected_option = {"tts_plugin_enabled": True, "tts_plugin_voice_id": "voice-1"}
    normalized_text = public_memorials._normalize_memorial_spoken_tts_text(text)
    extra_filters = public_memorials._speech_postprocess_filters_for_config(public_memorials.UNMIXR_TTS_PLUGIN_ID, merged_config)
    legacy_payload = {
        "slug": "manfred",
        "plugin": public_memorials.UNMIXR_TTS_PLUGIN_ID,
        "voice_ref": "voice-1",
        "text": normalized_text,
        "lang": "de-AT",
        "base_voice_variant": public_memorials._effective_tts_base_voice_variant(merged_config),
        "speaking_rate": "0.90",
        "speaking_pitch": "",
        "speaking_volume": "",
        "lead_in_ms": public_memorials._MEMORIAL_CONTACT_TTS_LEAD_IN_MS,
        "tail_silence_ms": public_memorials._MEMORIAL_CONTACT_TTS_TAIL_SILENCE_MS,
        "extra_filters": extra_filters,
        "spoken_text_normalizer": "memorial_de_at_v2",
        "postprocess_impl": "app.api.routes.public_memorials:_pad_speech_audio_lead_in:legacy-runtime-id",
    }
    legacy_audio_path, legacy_meta_path = public_memorials._memorial_tts_render_cache_paths(cache_payload=legacy_payload)
    legacy_audio = _generated_wav_bytes(textish_seed=text)
    legacy_audio_path.write_bytes(legacy_audio)
    legacy_meta_path.write_text(
        json.dumps(
            {
                **legacy_payload,
                "contact_phrase_validation": {
                    "status": "pass",
                    "f1": 1.0,
                    "missing_tokens": [],
                    "transcript_text": text,
                },
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    synth_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        public_memorials,
        "unmixr_synthesize_request",
        lambda **kwargs: synth_calls.append(dict(kwargs))
        or (_generated_wav_bytes(textish_seed=f"locale-policy:{text}"), "audio/wav"),
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_transcribe_audio_blob",
        lambda **kwargs: {"transcript_text": text, "transcriber": "unit"},
    )

    audio, content_type = public_memorials._render_memorial_tts_audio(
        slug="manfred",
        text=text,
        merged_config=merged_config,
        base_config=base_config,
        selected_plugin=public_memorials.UNMIXR_TTS_PLUGIN_ID,
        selected_option=selected_option,
        lead_in_ms=public_memorials._MEMORIAL_CONTACT_TTS_LEAD_IN_MS,
        tail_silence_ms=public_memorials._MEMORIAL_CONTACT_TTS_TAIL_SILENCE_MS,
    )

    assert content_type == "audio/wav"
    assert audio != legacy_audio
    assert len(synth_calls) == 1
    assert synth_calls[0]["lang"] == "de-AT"
    assert synth_calls[0]["voice_id"] == "voice-1"
    cache_metadata = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in public_memorials._memorial_tts_render_cache_root().glob("*.json")
    ]
    assert any(
        item.get("provider_language_policy") == "unmixr_locale_preserving_v1"
        for item in cache_metadata
    )


def test_memorial_live_page_uses_minimal_realtime_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    client = _client(principal_id="exec-memorial-minimal-client")

    response = client.get(f"/memorials/{slug}")
    assert response.status_code == 200
    source = response.text

    assert "(payload.voice_required === false || payload.voice_ready === true)" in source
    assert "/memorials/manfred/realtime" in source
    assert re.search(rf'"/memorials/"\s*\+\s*"{re.escape(slug)}"\s*\+\s*"/conv"\s*\+\s*"ersation-turn"', source)
    assert "startLiveRealtimeSession" in source
    assert "gemini_live_websocket_pcm" in source
    assert "audio/pcm;rate=16000" in source
    assert "ScriptProcessor" in source
    assert "RTCPeerConnection" not in source
    assert "/memorials/manfred/realtime/webrtc" not in source
    assert "openai" not in source.lower()
    assert "live_realtime_unsupported" in source
    assert "ensureRealtimeSocket" in source
    assert "sendConversationTurnHttp" in source
    assert "ensureContactAcknowledgementAudio" in source
    assert "playFastContactAcknowledgement" in source
    assert "if (completedConversationTurns === 0 && contactAcknowledgementReady)" in source
    assert "await playFastContactAcknowledgement(generation);" in source
    assert f'const memorialReadinessEndpoint = "/memorials/{slug}/readiness";' in source
    authorization_start = source.index(
        "async function requireFreshMemorialVoiceAuthorization"
    )
    authorization_end = source.index(
        "async function ensureContactAcknowledgementAudio",
        authorization_start,
    )
    authorization_source = source[authorization_start:authorization_end]
    assert 'credentials: "same-origin"' in authorization_source
    assert 'mode: "same-origin"' in authorization_source
    assert 'cache: "no-store"' in authorization_source
    assert 'redirect: "error"' in authorization_source
    assert '"Cache-Control": "no-store"' in authorization_source
    assert "payload.release.allowed === true" in authorization_source
    assert "payload.spoken_voice_ready !== true" in authorization_source
    assert "blockMemorialVoiceAuthorization();" in authorization_source
    assert "contactAcknowledgementCacheEpoch += 1;" in source
    assert "contactAcknowledgementAudioBlob = null;" in source
    assert "contactAcknowledgementAudioPromise = null;" in source
    assert "setLastAnswerAudioBlob(null);" in source
    assert "cacheEpoch !== contactAcknowledgementCacheEpoch" in source
    acknowledgement_start = source.index(
        "async function playFastContactAcknowledgement"
    )
    acknowledgement_end = source.index(
        "function syncConversationButton",
        acknowledgement_start,
    )
    acknowledgement_source = source[acknowledgement_start:acknowledgement_end]
    assert acknowledgement_source.index(
        "await requireFreshMemorialVoiceAuthorization()"
    ) < acknowledgement_source.index(
        "await ensureContactAcknowledgementAudio()"
    )
    input_start = source.index("async function ensureInputStream")
    input_end = source.index("function pickRecorderMimeType", input_start)
    input_source = source[input_start:input_end]
    assert input_source.index(
        "await requireFreshMemorialVoiceAuthorization()"
    ) < input_source.index(
        "navigator.mediaDevices.getUserMedia"
    )
    conversation_start = source.index(
        "async function startConversationSession"
    )
    conversation_end = source.index(
        "async function finishConversationTurn",
        conversation_start,
    )
    conversation_source = source[conversation_start:conversation_end]
    assert conversation_source.index(
        "await requireFreshMemorialVoiceAuthorization({"
    ) < conversation_source.index(
        "await ensureLandingReadyForConversation()"
    )
    assert "requireReady: false" in conversation_source
    assert "const startToken = {};" in conversation_source
    assert "activeConversationStart !== startToken" in conversation_source
    assert "startGeneration !== activeGeneration" in conversation_source
    replay_start = source.index(
        'replayAnswerButton.addEventListener("click", async () =>'
    )
    replay_end = source.index(
        "if (toggleStatusButton)",
        replay_start,
    )
    replay_source = source[replay_start:replay_end]
    assert replay_source.index(
        "await requireFreshMemorialVoiceAuthorization()"
    ) < replay_source.index(
        "playMemorialAudio(replayBlob"
    )
    assert 'const contactAcknowledgementText = "Worüber möchtest du sprechen?";' in source
    assert 'const contactAcknowledgementText = "Worum geht es?";' not in source
    assert 'id="memorial-read-answer"' in source
    assert 'id="memorial-replay-answer"' in source
    assert 'id="memorial-toggle-status"' in source
    assert "setAnswerStatus(" in source
    assert 'method: "POST"' in source
    assert "conversation_turn_http_" in source
    assert "startRealtimeAudioTurn" in source
    assert "queueLiveBufferedAudioChunk" in source
    assert "decodeBufferedLiveAudioBlob" in source
    assert "recorder.start(250)" in source
    assert "const captureChunks = [];" in source
    assert "const captureIsCurrent = () => (" in source
    assert "captureChunks.push(event.data);" in source
    assert "if (!captureIsCurrent())" in source
    assert "activeRealtimeAudioTurn.sendBlob(event.data)" not in source
    assert "blob.arrayBuffer().then" in source
    assert "activeRealtimeAudioTurn = realtimeTurn;" in source
    assert "cancelRealtimeAudioTurn(activeRealtimeAudioTurn);" in source
    assert 'memorialConversationError("Das Gespräch wurde beendet.", "turn_cancelled")' in source
    assert "pcmChunksToWavBlob" in source
    assert "Ich sichere die Antwort lokal." in source
    assert "await finishConversationTurn(fallbackBlob, generation, null);" in source
    assert "const maxActiveSpeechMs = 3400;" in source
    assert "if (liveAnswerEventAt > 0) return;" in source
    assert "user_audio_start" in source
    assert "user_audio_end" in source
    assert 'if (type === "answer")' in source
    assert 'if (type === "audio_complete")' in source
    assert 'message.effective_text || payload.transcript_text || ""' in source
    assert 'Verstanden als: ' in source
    assert "showAnswerText(liveAnswerTranscript);" in source
    assert "turn_complete" in source
    assert "activeRecordingHadSpeech" in source
    assert "Ich habe kaum Stimme gehört" in source
    assert "now - lastVoiceAt > 920" in source
    assert 'ensureMemorialReady("page_load")' in source
    assert 'requestMemorialWarmup("conversation_start")' not in source
    assert "ensureMemorialReady(" in source
    assert "const memorialWarmupPollWindowMs = 45000;" in source
    assert "const memorialWarmupMaxPendingMs = 120000;" in source
    assert "function memorialReadinessState(payload)" in source
    assert "let lastPayload = null;" in source
    assert "return lastPayload;" in source
    assert 'readinessState === "pending"' in source
    assert '{ requestWarmup: false }' in source
    assert '"memorial_voice_preparing"' in source
    assert "beginConversationRecording" in source
    assert "finishConversationTurn" in source
    assert '"memorial_audio_unavailable"' in source
    assert '"audio_playback_timeout"' in source
    assert 'window.addEventListener("pagehide"' in source
    assert "window.__memorialMinimalBooted" in source
    assert "startConversation();" not in source
    assert "Gespräch beenden" in source
    assert "captureTurnAudio" not in source
    assert "ontouchstart=" not in source
    assert 'if (window.speechSynthesis) window.speechSynthesis.cancel();' in source
    assert "retireLegacyMemorialServiceWorkers" in source
    assert "navigator.serviceWorker.register" not in source
    assert "primeRealtimeSocket" not in source
    assert "cancelRealtimeTurn" not in source


def test_memorial_gemini_live_fails_closed_without_server_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    for name in list(os.environ):
        if name.startswith("GOOGLE_API_KEY_FALLBACK_"):
            monkeypatch.delenv(name, raising=False)
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "EA_GEMINI_API_KEY", "EA_GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("EA_MEMORIAL_GEMINI_LIVE_OAUTH", "0")
    client = _client(principal_id="exec-memorial-live-gemini-no-key")

    response = client.post(
        f"/memorials/{slug}/realtime/webrtc",
        content="v=0\r\n",
        headers={"content-type": "application/sdp"},
    )

    assert response.status_code == 503
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.json()["error"]["code"] == "gemini_live_unavailable"


def test_memorial_gemini_live_webrtc_requires_voice_consent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    private_root = tmp_path / "private"
    _write_private_voice(
        private_root,
        slug,
        {
            "tts_plugin": "voicewave_clone",
            "tts_plugin_voice_id": "Manfred Hoza Memorial",
            "voice_consent": {
                "status": "pending",
                "scope": [],
                "authorized_by": "",
                "authorized_at": "",
                "source_assets_reviewed": False,
                "revoked": False,
            },
        },
    )

    client = _client(principal_id="exec-memorial-live-gemini-no-consent")
    response = client.post(
        f"/memorials/{slug}/realtime/webrtc",
        content="v=0\r\n",
        headers={"content-type": "application/sdp"},
    )

    assert response.status_code == 403
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.json()["error"]["code"] == "voice_consent_required"


def test_memorial_full_realtime_client_uses_funeral_safe_pause_threshold() -> None:
    source = PUBLIC_MEMORIALS_SOURCE.read_text(encoding="utf-8")

    assert "Number(options.maxNoSpeechMs || options.autoStopMs || 2600)" in source
    assert "const minSpeechMs = 320" in source
    assert "Math.max(280, Number(options.silenceMs || 420))" in source
    assert "const maxAfterSpeechMs = Math.max(1800, Number(options.maxAfterSpeechMs || 4200));" in source


def test_memorial_gemini_live_uses_websocket_pcm_not_webrtc_sdp(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    monkeypatch.setenv("GOOGLE_API_KEY_FALLBACK_1", "test-gemini-key")
    monkeypatch.setenv("EA_MEMORIAL_GEMINI_LIVE_MODEL", "gemini-live-test")
    monkeypatch.setenv("EA_MEMORIAL_GEMINI_LIVE_VOICE", "Kore")
    client = _client(principal_id="exec-memorial-live-gemini")

    response = client.post(
        f"/memorials/{slug}/realtime/webrtc?personal_memory=1",
        content="v=0\r\no=browser 0 0 IN IP4 127.0.0.1\r\n",
        headers={"content-type": "application/sdp"},
    )

    assert response.status_code == 410
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.json()["error"]["code"] == "gemini_live_uses_websocket_pcm"
    setup = public_memorials._build_memorial_gemini_live_setup(slug=slug)
    assert setup["setup"]["model"] == "models/gemini-live-test"
    assert setup["setup"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == "Kore"
    assert setup["setup"]["responseModalities"] == ["AUDIO"]
    assert setup["setup"]["inputAudioTranscription"] == {}
    assert "Vermeide 'Jo'" in setup["setup"]["systemInstruction"]["parts"][0]["text"]
    assert "wiederhole nicht staendig denselben Satz" in setup["setup"]["systemInstruction"]["parts"][0]["text"]
    assert "test-gemini-key" not in json.dumps(setup)


def test_memorial_gemini_live_setup_is_pinned_to_german(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    setup = public_memorials._build_memorial_gemini_live_setup(slug=slug, language="en-US")
    instruction = setup["setup"]["systemInstruction"]["parts"][0]["text"]

    assert public_memorials._normalize_browser_language("de_AT") == "de-AT"
    assert public_memorials._normalize_browser_language("<script>") == "de-AT"
    assert "Antworte immer auf Deutsch (de-AT)" in instruction
    assert "browser language" not in instruction
    assert "Antworte auf Deutsch" not in instruction


def test_memorial_spoken_tts_text_normalizes_common_german_ascii_spellings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    spoken = public_memorials._normalize_memorial_spoken_tts_text(
        "Ich hoere dir zu und erzaehl dir etwas ueber das Gespraech fuer de-AT."
    )

    assert spoken == "Ich höre dir zu und erzähl dir etwas über das Gespräch für Deutsch."


def test_memorial_unmixr_defaults_to_natural_minimal_postprocess(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    filters = public_memorials._speech_postprocess_filters_for_config(
        public_memorials.UNMIXR_TTS_PLUGIN_ID,
        {},
    )

    assert public_memorials._speech_postprocess_profile_for_config(public_memorials.UNMIXR_TTS_PLUGIN_ID, {}) == "unmixr_natural_minimal"
    assert "afftdn" not in filters
    assert "acompressor" not in filters
    assert "lowpass=f=7600" in filters


def test_memorial_live_unmixr_policy_uses_clear_slow_profile() -> None:
    from app.api.routes import public_memorials

    merged = public_memorials._apply_memorial_live_clone_tts_policy(
        {
            "tts_plugin": public_memorials.UNMIXR_TTS_PLUGIN_ID,
            "tts_plugin_voice_id": "voice-123",
        }
    )

    assert merged["tts_plugin"] == public_memorials.UNMIXR_TTS_PLUGIN_ID
    assert merged["tts_postprocess_profile"] == "unmixr_realtime_clear"
    assert merged["unmixr_speaking_rate"] == "0.90"


def test_memorial_realtime_answer_compaction_keeps_live_voice_short() -> None:
    from app.api.routes import public_memorials

    compact = public_memorials._compact_memorial_realtime_answer(
        "Erstens ordnen wir die Sache ruhig und ohne Theater. "
        "Zweitens bleiben wir bei dem, was belegt ist. "
        "Drittens reden wir erst weiter, wenn der konkrete Punkt klar ist."
    )

    assert compact == "Erstens ordnen wir die Sache ruhig und ohne Theater. Zweitens bleiben wir bei dem, was belegt ist."

    long_compact = public_memorials._compact_memorial_realtime_answer(
        "Ich ordne das ruhig mit dir. "
        "Der erste Punkt ist belegt und bleibt wichtig. "
        "Der zweite Punkt ist noch offen und braucht eine klare Frage. "
        "Der dritte Punkt kommt erst danach."
    )

    assert len(long_compact) <= 160


def test_memorial_gemini_live_websocket_streams_pcm_to_upstream(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    monkeypatch.setenv("GOOGLE_API_KEY_FALLBACK_1", "test-gemini-key")
    monkeypatch.setenv("EA_GEMINI_LIVE_OUTPUT_AUDIO_MODE", "native")
    seen: dict[str, object] = {}

    class _FakeGeminiSocket:
        def __init__(self) -> None:
            self.sent: list[dict[str, object]] = []
            self._queue: asyncio.Queue[object] = asyncio.Queue()

        async def send(self, raw: str) -> None:
            payload = json.loads(raw)
            self.sent.append(payload)
            if "setup" in payload:
                await self._queue.put({"setupComplete": {}})
            realtime_input = payload.get("realtimeInput")
            if isinstance(realtime_input, dict) and realtime_input.get("audioStreamEnd") is True:
                await self._queue.put(
                    {
                        "serverContent": {
                            "inputTranscription": {"text": "Hallo Manfred."},
                            "modelTurn": {
                                "parts": [
                                    {
                                        "inlineData": {
                                            "mimeType": "audio/pcm;rate=24000",
                                            "data": base64.b64encode(b"\x00\x00\x01\x00").decode("ascii"),
                                        }
                                    }
                                ]
                            },
                            "outputTranscription": {"text": "Ja, ich bin da."},
                            "generationComplete": True,
                            "turnComplete": True,
                        }
                    }
                )

        def __aiter__(self):
            return self

        async def __anext__(self):
            item = await self._queue.get()
            if item is None:
                raise StopAsyncIteration
            return json.dumps(item)

        async def close(self) -> None:
            await self._queue.put(None)

    async def _fake_connect(uri: str, **kwargs):
        socket = _FakeGeminiSocket()
        seen["uri"] = uri
        seen["kwargs"] = kwargs
        seen["socket"] = socket
        return socket

    monkeypatch.setattr(public_memorials, "websockets", SimpleNamespace(connect=_fake_connect))
    client = _client(principal_id="exec-memorial-live-gemini-ws")
    speech_pcm = _pcm16_speech_bytes()

    with client.websocket_connect(f"/memorials/{slug}/realtime?personal_memory=1") as websocket:
        ready = websocket.receive_json()
        assert ready["provider"] == "gemini_live"
        websocket.send_json(
            {
                "type": "user_audio_start",
                "turn_id": "turn_pcm",
                "content_type": "audio/pcm;rate=16000",
                "transport": "gemini_live",
                "personal_memory_enabled": True,
            }
        )
        websocket.send_bytes(speech_pcm)
        websocket.send_json({"type": "user_audio_end", "turn_id": "turn_pcm"})
        messages = []
        for _ in range(12):
            message = websocket.receive_json()
            messages.append(message)
            if message.get("type") == "turn_complete":
                break

    fake_socket = seen["socket"]
    assert "test-gemini-key" in seen["uri"]
    assert all("test-gemini-key" not in json.dumps(payload) for payload in fake_socket.sent)
    assert fake_socket.sent[0]["setup"]["responseModalities"] == ["AUDIO"]
    audio_payloads = [
        payload
        for payload in fake_socket.sent
        if isinstance(payload.get("realtimeInput"), dict)
        and isinstance(payload["realtimeInput"].get("audio"), dict)
    ]
    assert audio_payloads
    assert audio_payloads[0]["realtimeInput"]["audio"]["mimeType"] == "audio/pcm;rate=16000"
    assert audio_payloads[0]["realtimeInput"]["audio"]["data"] == base64.b64encode(speech_pcm).decode("ascii")
    assert any(
        message.get("type") == "turn_admitted"
        and message.get("provider_work_started") is True
        and message.get("transport") == "gemini_live"
        for message in messages
    )
    admission_index = next(
        index
        for index, message in enumerate(messages)
        if message.get("type") == "turn_admitted"
    )
    listening_index = next(
        index
        for index, message in enumerate(messages)
        if message.get("type") == "phase"
        and message.get("phase") == "listening"
    )
    transcript_index = next(
        index
        for index, message in enumerate(messages)
        if message.get("type") == "transcript"
    )
    assert admission_index < listening_index < transcript_index
    assert any(message.get("type") == "transcript" and "Hallo Manfred" in message.get("text", "") for message in messages)
    assert any(message.get("type") == "audio_chunk" and message.get("content_type") == "audio/pcm;rate=24000" for message in messages)
    assert any(message.get("type") == "turn_complete" for message in messages)


def test_memorial_gemini_live_defaults_to_server_tts_audio(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    monkeypatch.setenv("GOOGLE_API_KEY_FALLBACK_1", "test-gemini-key")
    monkeypatch.setenv("UNMIXR_VOICE_ID", "live-unmixr-id")
    monkeypatch.delenv("EA_GEMINI_LIVE_OUTPUT_AUDIO_MODE", raising=False)
    monkeypatch.setattr(public_memorials, "_require_voice_consent", lambda *args, **kwargs: None)
    seen: dict[str, object] = {}

    class _FakeGeminiSocket:
        def __init__(self) -> None:
            self.sent: list[dict[str, object]] = []
            self._queue: asyncio.Queue[object] = asyncio.Queue()

        async def send(self, raw: str) -> None:
            payload = json.loads(raw)
            self.sent.append(payload)
            if "setup" in payload:
                await self._queue.put({"setupComplete": {}})
            realtime_input = payload.get("realtimeInput")
            if isinstance(realtime_input, dict) and realtime_input.get("audioStreamEnd") is True:
                await self._queue.put(
                    {
                        "serverContent": {
                            "inputTranscription": {"text": "Hallo Manfred."},
                            "outputTranscription": {"text": "Ja, ich"},
                            "generationComplete": False,
                        }
                    }
                )
                await self._queue.put(
                    {
                        "serverContent": {
                            "outputTranscription": {"text": "bin da."},
                            "generationComplete": True,
                            "turnComplete": True,
                        }
                    }
                )

        def __aiter__(self):
            return self

        async def __anext__(self):
            item = await self._queue.get()
            if item is None:
                raise StopAsyncIteration
            return json.dumps(item)

        async def close(self) -> None:
            await self._queue.put(None)

    async def _fake_connect(uri: str, **kwargs):
        socket = _FakeGeminiSocket()
        seen["socket"] = socket
        return socket

    monkeypatch.setattr(public_memorials, "websockets", SimpleNamespace(connect=_fake_connect))
    monkeypatch.setattr(
        public_memorials,
        "_load_voice_config",
        lambda slug: {
            "tts_plugin": public_memorials.OPENVOICE_TTS_PLUGIN_ID,
            "tts_plugin_voice_id": "stale-openvoice-id",
            "voice_profile_ready": True,
        },
    )
    monkeypatch.setattr(
        public_memorials,
        "_tts_plugin_options",
        lambda *, payload, voice_profile_ready: [{"tts_plugin": "unmixr_clone", "tts_plugin_enabled": True}],
    )

    def _fake_resolve_server_tts_plugin(*, payload, options):
        seen["resolved_tts_plugin"] = payload.get("tts_plugin")
        seen["resolved_voice_id"] = payload.get("tts_plugin_voice_id")
        return "unmixr_clone", {"tts_plugin": "unmixr_clone", "tts_plugin_enabled": True}

    monkeypatch.setattr(public_memorials, "_resolve_server_tts_plugin", _fake_resolve_server_tts_plugin)

    def _fake_render(**kwargs):
        seen["tts_text"] = kwargs["text"]
        seen["tts_lang"] = kwargs["merged_config"].get("lang")
        return b"fake-wav-audio", "audio/wav"

    monkeypatch.setattr(public_memorials, "_render_memorial_tts_audio", _fake_render)
    client = _client(principal_id="exec-memorial-live-server-tts")
    speech_pcm = _pcm16_speech_bytes()

    with client.websocket_connect(f"/memorials/{slug}/realtime?personal_memory=1") as websocket:
        assert websocket.receive_json()["provider"] == "gemini_live"
        websocket.send_json(
            {
                "type": "user_audio_start",
                "turn_id": "turn_server_tts",
                "content_type": "audio/pcm;rate=16000",
                "transport": "gemini_live",
                "browser_language": "en-US",
            }
        )
        websocket.send_bytes(speech_pcm)
        websocket.send_json({"type": "user_audio_end", "turn_id": "turn_server_tts"})
        messages = []
        for _ in range(12):
            message = websocket.receive_json()
            messages.append(message)
            if message.get("type") == "turn_complete":
                break

    assert seen["tts_text"] in CONTACT_REPLY_VARIANTS
    assert seen["tts_lang"] == "de-AT"
    assert seen["resolved_tts_plugin"] == "unmixr_clone"
    assert seen["resolved_voice_id"] == "live-unmixr-id"
    assert any(message.get("type") == "audio" and message.get("content_type") == "audio/wav" for message in messages)
    assert not any(message.get("type") == "audio_chunk" for message in messages)
    assert any(message.get("type") == "turn_complete" for message in messages)


def test_memorial_gemini_live_falls_back_to_stable_stt_when_input_transcript_is_empty(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    monkeypatch.setenv("GOOGLE_API_KEY_FALLBACK_1", "test-gemini-key")
    monkeypatch.setenv("UNMIXR_VOICE_ID", "live-unmixr-id")
    monkeypatch.delenv("EA_GEMINI_LIVE_OUTPUT_AUDIO_MODE", raising=False)
    monkeypatch.setattr(public_memorials, "_require_voice_consent", lambda *args, **kwargs: None)
    seen: dict[str, object] = {}

    class _FakeGeminiSocket:
        def __init__(self) -> None:
            self.sent: list[dict[str, object]] = []
            self._queue: asyncio.Queue[object] = asyncio.Queue()

        async def send(self, raw: str) -> None:
            payload = json.loads(raw)
            self.sent.append(payload)
            if "setup" in payload:
                await self._queue.put({"setupComplete": {}})
            realtime_input = payload.get("realtimeInput")
            if isinstance(realtime_input, dict) and realtime_input.get("audioStreamEnd") is True:
                await self._queue.put(
                    {
                        "serverContent": {
                            "outputTranscription": {"text": "Ich höre dich. Erzähl weiter."},
                            "generationComplete": True,
                            "turnComplete": True,
                        }
                    }
                )

        def __aiter__(self):
            return self

        async def __anext__(self):
            item = await self._queue.get()
            if item is None:
                raise StopAsyncIteration
            return json.dumps(item)

        async def close(self) -> None:
            await self._queue.put(None)

    async def _fake_connect(uri: str, **kwargs):
        socket = _FakeGeminiSocket()
        seen["socket"] = socket
        return socket

    monkeypatch.setattr(public_memorials, "websockets", SimpleNamespace(connect=_fake_connect))
    monkeypatch.setattr(
        public_memorials,
        "_memorial_transcribe_audio_blob",
        lambda *, payload, content_type: {
            "transcription_status": "transcribed",
            "transcript_text": "Wie ist das Wetter heute?",
            "transcriber": "stable-test-stt",
        },
    )
    monkeypatch.setattr(
        public_memorials,
        "_load_voice_config",
        lambda slug: {
            "tts_plugin": public_memorials.UNMIXR_TTS_PLUGIN_ID,
            "tts_plugin_voice_id": "live-unmixr-id",
            "voice_profile_ready": True,
        },
    )

    def _fake_render(**kwargs):
        seen["tts_text"] = kwargs["text"]
        seen["tts_content_type"] = kwargs["selected_option"].get("tts_plugin")
        seen["tts_postprocess_profile"] = kwargs["merged_config"].get("tts_postprocess_profile")
        seen["unmixr_speaking_rate"] = kwargs["merged_config"].get("unmixr_speaking_rate")
        seen["lead_in_ms"] = kwargs["lead_in_ms"]
        return b"fake-wav-audio", "audio/wav"

    monkeypatch.setattr(public_memorials, "_render_memorial_tts_audio", _fake_render)
    client = _client(principal_id="exec-memorial-live-stt-fallback")

    with client.websocket_connect(f"/memorials/{slug}/realtime?personal_memory=1") as websocket:
        assert websocket.receive_json()["provider"] == "gemini_live"
        websocket.send_json(
            {
                "type": "user_audio_start",
                "turn_id": "turn_weather_fallback",
                "content_type": "audio/pcm;rate=16000",
                "transport": "gemini_live",
            }
        )
        websocket.send_bytes(_pcm16_speech_bytes(samples=3200))
        websocket.send_json({"type": "user_audio_end", "turn_id": "turn_weather_fallback"})
        messages = []
        for _ in range(20):
            message = websocket.receive_json()
            messages.append(message)
            if message.get("type") == "turn_complete":
                break

    assert any(message.get("type") == "transcript" and message.get("text") == "Wie ist das Wetter heute?" for message in messages)
    assert "Wetter" in seen["tts_text"]
    assert seen["tts_text"] not in CONTACT_REPLY_VARIANTS
    assert seen["tts_postprocess_profile"] == "unmixr_realtime_clear"
    assert seen["unmixr_speaking_rate"] == "0.90"
    assert seen["lead_in_ms"] == public_memorials._MEMORIAL_REALTIME_TTS_LEAD_IN_MS
    assert any(message.get("type") == "audio_chunk" and message.get("content_type") == "audio/wav" for message in messages)
    assert any(message.get("type") == "audio_complete" and message.get("content_type") == "audio/wav" for message in messages)
    assert any(message.get("type") == "turn_complete" for message in messages)


def test_memorial_gemini_live_soft_fails_tts_without_visible_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    monkeypatch.setenv("GOOGLE_API_KEY_FALLBACK_1", "test-gemini-key")
    monkeypatch.setenv("UNMIXR_VOICE_ID", "live-unmixr-id")
    monkeypatch.delenv("EA_GEMINI_LIVE_OUTPUT_AUDIO_MODE", raising=False)
    monkeypatch.setattr(public_memorials, "_require_voice_consent", lambda *args, **kwargs: None)

    class _FakeGeminiSocket:
        def __init__(self) -> None:
            self._queue: asyncio.Queue[object] = asyncio.Queue()

        async def send(self, raw: str) -> None:
            payload = json.loads(raw)
            if "setup" in payload:
                await self._queue.put({"setupComplete": {}})
            realtime_input = payload.get("realtimeInput")
            if isinstance(realtime_input, dict) and realtime_input.get("audioStreamEnd") is True:
                await self._queue.put(
                    {
                        "serverContent": {
                            "inputTranscription": {"text": "Hallo Manfred, hörst du mich?"},
                            "outputTranscription": {"text": "Ja, ich bin da."},
                            "generationComplete": True,
                            "turnComplete": True,
                        }
                    }
                )

        def __aiter__(self):
            return self

        async def __anext__(self):
            item = await self._queue.get()
            if item is None:
                raise StopAsyncIteration
            return json.dumps(item)

        async def close(self) -> None:
            await self._queue.put(None)

    async def _fake_connect(uri: str, **kwargs):
        return _FakeGeminiSocket()

    monkeypatch.setattr(public_memorials, "websockets", SimpleNamespace(connect=_fake_connect))
    monkeypatch.setattr(
        public_memorials,
        "_load_voice_config",
        lambda slug: {
            "tts_plugin": public_memorials.UNMIXR_TTS_PLUGIN_ID,
            "tts_plugin_voice_id": "live-unmixr-id",
            "voice_profile_ready": True,
        },
    )
    monkeypatch.setattr(
        public_memorials,
        "_render_memorial_tts_audio",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("provider briefly unavailable")),
    )
    client = _client(principal_id="exec-memorial-live-server-tts-soft-fail")

    with client.websocket_connect(f"/memorials/{slug}/realtime?personal_memory=1") as websocket:
        assert websocket.receive_json()["provider"] == "gemini_live"
        websocket.send_json(
            {
                "type": "user_audio_start",
                "turn_id": "turn_server_tts_soft_fail",
                "content_type": "audio/pcm;rate=16000",
                "transport": "gemini_live",
            }
        )
        websocket.send_bytes(_pcm16_speech_bytes())
        websocket.send_json({"type": "user_audio_end", "turn_id": "turn_server_tts_soft_fail"})
        messages = []
        for _ in range(12):
            message = websocket.receive_json()
            messages.append(message)
            if message.get("type") == "turn_complete":
                break

    assert not any(message.get("type") == "error" for message in messages)
    assert any(message.get("type") == "audio_complete" and message.get("audio_unavailable") is True for message in messages)
    assert any(message.get("type") == "turn_complete" for message in messages)


def test_memorial_gemini_live_rejects_silent_pcm_before_model_answer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    monkeypatch.setenv("GOOGLE_API_KEY_FALLBACK_1", "test-gemini-key")
    monkeypatch.setattr(public_memorials, "_require_voice_consent", lambda *args, **kwargs: None)
    seen: dict[str, object] = {}

    class _FakeGeminiSocket:
        def __init__(self) -> None:
            self.sent: list[dict[str, object]] = []
            self._queue: asyncio.Queue[object] = asyncio.Queue()

        async def send(self, raw: str) -> None:
            payload = json.loads(raw)
            self.sent.append(payload)
            if "setup" in payload:
                await self._queue.put({"setupComplete": {}})
            realtime_input = payload.get("realtimeInput")
            if isinstance(realtime_input, dict) and realtime_input.get("audioStreamEnd") is True:
                raise AssertionError("silent pcm must not complete a Gemini Live model turn")

        def __aiter__(self):
            return self

        async def __anext__(self):
            item = await self._queue.get()
            if item is None:
                raise StopAsyncIteration
            return json.dumps(item)

        async def close(self) -> None:
            await self._queue.put(None)

    async def _fake_connect(uri: str, **kwargs):
        socket = _FakeGeminiSocket()
        seen["socket"] = socket
        return socket

    monkeypatch.setattr(public_memorials, "websockets", SimpleNamespace(connect=_fake_connect))
    client = _client(principal_id="exec-memorial-live-silent-pcm")

    with client.websocket_connect(f"/memorials/{slug}/realtime?personal_memory=1") as websocket:
        assert websocket.receive_json()["provider"] == "gemini_live"
        websocket.send_json(
            {
                "type": "user_audio_start",
                "turn_id": "turn_silent_pcm",
                "content_type": "audio/pcm;rate=16000",
                "transport": "gemini_live",
            }
        )
        websocket.send_bytes(b"\x00\x00" * 800)
        websocket.send_json({"type": "user_audio_end", "turn_id": "turn_silent_pcm"})
        messages = []
        for _ in range(6):
            message = websocket.receive_json()
            messages.append(message)
            if message.get("type") == "error":
                break

    fake_socket = seen["socket"]
    assert any(message.get("type") == "error" and message.get("message") == "speech_not_detected" for message in messages)
    assert not any(
        isinstance(payload.get("realtimeInput"), dict) and payload["realtimeInput"].get("audioStreamEnd") is True
        for payload in fake_socket.sent
    )
    assert not any(message.get("type") in {"audio", "audio_chunk", "turn_complete"} for message in messages)


def test_memorial_gemini_live_accepts_quiet_speech_mixed_with_room_noise(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    monkeypatch.setenv("GOOGLE_API_KEY_FALLBACK_1", "test-gemini-key")
    monkeypatch.setattr(public_memorials, "_require_voice_consent", lambda *args, **kwargs: None)
    seen: dict[str, object] = {}

    class _FakeGeminiSocket:
        def __init__(self) -> None:
            self.sent: list[dict[str, object]] = []
            self._queue: asyncio.Queue[object] = asyncio.Queue()

        async def send(self, raw: str) -> None:
            payload = json.loads(raw)
            self.sent.append(payload)
            if "setup" in payload:
                await self._queue.put({"setupComplete": {}})
            realtime_input = payload.get("realtimeInput")
            if isinstance(realtime_input, dict) and realtime_input.get("audioStreamEnd") is True:
                await self._queue.put(
                    {
                        "serverContent": {
                            "inputTranscription": {"text": "Hallo Manfred."},
                            "outputTranscription": {"text": "Ja, ich bin da."},
                            "generationComplete": True,
                            "turnComplete": True,
                        }
                    }
                )

        def __aiter__(self):
            return self

        async def __anext__(self):
            item = await self._queue.get()
            if item is None:
                raise StopAsyncIteration
            return json.dumps(item)

        async def close(self) -> None:
            await self._queue.put(None)

    async def _fake_connect(uri: str, **kwargs):
        socket = _FakeGeminiSocket()
        seen["socket"] = socket
        return socket

    monkeypatch.setattr(public_memorials, "websockets", SimpleNamespace(connect=_fake_connect))
    client = _client(principal_id="exec-memorial-live-quiet-noisy-pcm")
    mixed_pcm = _pcm16_mix_bytes(
        _pcm16_speech_bytes(samples=3200, sample=1700),
        _pcm16_noise_bytes(samples=3200, sample=120),
    )

    with client.websocket_connect(f"/memorials/{slug}/realtime?personal_memory=1") as websocket:
        assert websocket.receive_json()["provider"] == "gemini_live"
        websocket.send_json(
            {
                "type": "user_audio_start",
                "turn_id": "turn_quiet_noisy_pcm",
                "content_type": "audio/pcm;rate=16000",
                "transport": "gemini_live",
            }
        )
        websocket.send_bytes(mixed_pcm)
        websocket.send_json({"type": "user_audio_end", "turn_id": "turn_quiet_noisy_pcm"})
        messages = []
        for _ in range(12):
            message = websocket.receive_json()
            messages.append(message)
            if message.get("type") in {"turn_complete", "error"}:
                break

    fake_socket = seen["socket"]
    assert any(
        isinstance(payload.get("realtimeInput"), dict) and payload["realtimeInput"].get("audioStreamEnd") is True
        for payload in fake_socket.sent
    )
    assert any(message.get("type") == "transcript" and "Hallo Manfred" in message.get("text", "") for message in messages)
    assert any(message.get("type") == "turn_complete" and message.get("turn_id") == "turn_quiet_noisy_pcm" for message in messages)
    assert not any(message.get("type") == "error" and message.get("message") == "speech_not_detected" for message in messages)


def test_memorial_gemini_live_reports_oauth_scope_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    for name in list(os.environ):
        if name.startswith("GOOGLE_API_KEY_FALLBACK_"):
            monkeypatch.delenv(name, raising=False)
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "EA_GEMINI_API_KEY", "EA_GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    creds_path = tmp_path / "oauth_creds.json"
    creds_path.write_text(
        json.dumps(
            {
                "access_token": "oauth-access-token",
                "refresh_token": "oauth-refresh-token",
                "scope": "https://www.googleapis.com/auth/cloud-platform",
                "token_type": "Bearer",
                "expiry_date": int((time.time() + 3600) * 1000),
                "ea_memorial_live_refreshed_at": "2026-06-11T08:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_MEMORIAL_GEMINI_OAUTH_CREDS_PATH", str(creds_path))
    monkeypatch.setenv("EA_MEMORIAL_GEMINI_LIVE_OAUTH", "1")

    async def _fake_connect(uri: str, **kwargs):
        raise RuntimeError("Request had insufficient authentication scopes.")

    monkeypatch.setattr(public_memorials, "websockets", SimpleNamespace(connect=_fake_connect))
    client = _client(principal_id="exec-memorial-live-gemini-scope")

    with client.websocket_connect(f"/memorials/{slug}/realtime?personal_memory=1") as websocket:
        ready = websocket.receive_json()
        assert ready["provider"] == "gemini_live"
        websocket.send_json(
            {
                "type": "user_audio_start",
                "turn_id": "turn_scope",
                "content_type": "audio/pcm;rate=16000",
                "transport": "gemini_live",
                "personal_memory_enabled": True,
            }
        )
        error = websocket.receive_json()

    assert error == {"type": "error", "turn_id": "turn_scope", "message": "gemini_live_auth_scope_insufficient"}


def test_memorial_gemini_live_fails_soft_to_audio_buffer_after_oauth_scope_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    for name in list(os.environ):
        if name.startswith("GOOGLE_API_KEY_FALLBACK_"):
            monkeypatch.delenv(name, raising=False)
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "EA_GEMINI_API_KEY", "EA_GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    creds_path = tmp_path / "oauth_creds.json"
    creds_path.write_text(
        json.dumps(
            {
                "access_token": "oauth-access-token",
                "refresh_token": "oauth-refresh-token",
                "scope": "https://www.googleapis.com/auth/cloud-platform",
                "token_type": "Bearer",
                "expiry_date": int((time.time() + 3600) * 1000),
                "ea_memorial_live_refreshed_at": "2026-06-11T08:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_MEMORIAL_GEMINI_OAUTH_CREDS_PATH", str(creds_path))
    monkeypatch.setenv("EA_MEMORIAL_GEMINI_LIVE_OAUTH", "1")

    class _ScopeClosingGeminiSocket:
        async def send(self, raw: str) -> None:
            return None

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise RuntimeError("received 1008 policy violation Request had insufficient authentication scopes.")

        async def close(self) -> None:
            return None

    async def _fake_connect(uri: str, **kwargs):
        return _ScopeClosingGeminiSocket()

    monkeypatch.setattr(public_memorials, "websockets", SimpleNamespace(connect=_fake_connect))
    client = _client(principal_id="exec-memorial-live-gemini-scope-open")

    with client.websocket_connect(f"/memorials/{slug}/realtime?personal_memory=1") as websocket:
        ready = websocket.receive_json()
        assert ready["provider"] == "gemini_live"
        websocket.send_json(
            {
                "type": "user_audio_start",
                "turn_id": "turn_scope_open",
                "content_type": "audio/pcm;rate=16000",
                "transport": "gemini_live",
                "personal_memory_enabled": True,
            }
        )
        messages = [websocket.receive_json() for _ in range(3)]

    assert any(
        message.get("type") == "turn_admitted"
        and message.get("provider_work_started") is True
        and message.get("transport") == "gemini_live"
        for message in messages
    )
    listening_phases = [
        message
        for message in messages
        if message.get("type") == "phase"
        and message.get("phase") == "listening"
    ]
    assert len(listening_phases) == 2
    assert any(
        message.get("detail") == "Audio wird empfangen"
        for message in listening_phases
    )


def test_memorial_gemini_live_uses_mounted_oauth_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.api.routes import public_memorials

    for name in list(os.environ):
        if name.startswith("GOOGLE_API_KEY_FALLBACK_"):
            monkeypatch.delenv(name, raising=False)
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "EA_GEMINI_API_KEY", "EA_GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    creds_path = tmp_path / "oauth_creds.json"
    creds_path.write_text(
        json.dumps(
            {
                "access_token": "oauth-access-token",
                "refresh_token": "oauth-refresh-token",
                "scope": "https://www.googleapis.com/auth/cloud-platform",
                "token_type": "Bearer",
                "expiry_date": int((time.time() + 3600) * 1000),
                "ea_memorial_live_refreshed_at": "2026-06-11T08:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_MEMORIAL_GEMINI_OAUTH_CREDS_PATH", str(creds_path))
    monkeypatch.setenv("EA_MEMORIAL_GEMINI_LIVE_OAUTH", "1")

    uri, headers, auth_mode = public_memorials._gemini_live_connect_target()

    assert auth_mode == "oauth"
    assert uri == "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
    assert headers == {"Authorization": "Bearer oauth-access-token"}


def test_memorial_gemini_live_prefers_vertex_oauth_when_project_configured(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    for name in list(os.environ):
        if name.startswith("GOOGLE_API_KEY_FALLBACK_"):
            monkeypatch.delenv(name, raising=False)
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "EA_GEMINI_API_KEY", "EA_GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    creds_path = tmp_path / "oauth_creds.json"
    creds_path.write_text(
        json.dumps(
            {
                "access_token": "oauth-access-token",
                "refresh_token": "oauth-refresh-token",
                "scope": "https://www.googleapis.com/auth/cloud-platform",
                "token_type": "Bearer",
                "expiry_date": int((time.time() + 3600) * 1000),
                "ea_memorial_live_refreshed_at": "2026-06-11T08:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_MEMORIAL_GEMINI_OAUTH_CREDS_PATH", str(creds_path))
    monkeypatch.setenv("EA_MEMORIAL_GEMINI_LIVE_OAUTH", "1")
    monkeypatch.setenv("EA_GEMINI_LIVE_VERTEX_PROJECT", "openclaw-concierge")
    monkeypatch.setenv("EA_GEMINI_LIVE_VERTEX_LOCATION", "us-central1")
    monkeypatch.setenv("EA_GEMINI_LIVE_VERTEX_MODEL", "gemini-live-2.5-flash-native-audio")

    uri, headers, auth_mode = public_memorials._gemini_live_connect_target()
    setup = public_memorials._build_memorial_gemini_live_setup(slug=slug, backend=auth_mode)

    assert auth_mode == "vertex_oauth"
    assert uri == "wss://us-central1-aiplatform.googleapis.com/ws/google.cloud.aiplatform.v1.LlmBidiService/BidiGenerateContent"
    assert headers == {"Authorization": "Bearer oauth-access-token"}
    assert setup["setup"]["model"] == (
        "projects/openclaw-concierge/locations/us-central1/publishers/google/models/"
        "gemini-live-2.5-flash-native-audio"
    )
    assert setup["setup"]["generation_config"]["response_modalities"] == ["audio"]
    assert setup["setup"]["generation_config"]["speech_config"]["voice_config"]["prebuilt_voice_config"]["voice_name"] == "Kore"
    assert setup["setup"]["input_audio_transcription"] == {}
    assert setup["setup"]["realtime_input_config"]["automatic_activity_detection"] == {"disabled": True}
    assert "Vermeide 'Jo'" in setup["setup"]["system_instruction"]["parts"][0]["text"]


def test_memorial_gemini_live_websocket_streams_vertex_pcm_schema(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    for name in list(os.environ):
        if name.startswith("GOOGLE_API_KEY_FALLBACK_"):
            monkeypatch.delenv(name, raising=False)
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "EA_GEMINI_API_KEY", "EA_GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    creds_path = tmp_path / "oauth_creds.json"
    creds_path.write_text(
        json.dumps(
            {
                "access_token": "oauth-access-token",
                "refresh_token": "oauth-refresh-token",
                "scope": "https://www.googleapis.com/auth/cloud-platform",
                "token_type": "Bearer",
                "expiry_date": int((time.time() + 3600) * 1000),
                "ea_memorial_live_refreshed_at": "2026-06-11T08:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_MEMORIAL_GEMINI_OAUTH_CREDS_PATH", str(creds_path))
    monkeypatch.setenv("EA_MEMORIAL_GEMINI_LIVE_OAUTH", "1")
    monkeypatch.setenv("EA_GEMINI_LIVE_VERTEX_PROJECT", "openclaw-concierge")
    seen: dict[str, object] = {}

    class _FakeGeminiSocket:
        def __init__(self) -> None:
            self.sent: list[dict[str, object]] = []
            self._queue: asyncio.Queue[object] = asyncio.Queue()

        async def send(self, raw: str) -> None:
            payload = json.loads(raw)
            self.sent.append(payload)
            if "setup" in payload:
                await self._queue.put({"setupComplete": {}})
            realtime_input = payload.get("realtime_input")
            if isinstance(realtime_input, dict) and realtime_input.get("activityEnd") == {}:
                await self._queue.put(
                    {
                        "serverContent": {
                            "inputTranscription": {"text": "Hallo Manfred."},
                            "turnComplete": True,
                        }
                    }
                )

        def __aiter__(self):
            return self

        async def __anext__(self):
            item = await self._queue.get()
            if item is None:
                raise StopAsyncIteration
            return json.dumps(item)

        async def close(self) -> None:
            await self._queue.put(None)

    async def _fake_connect(uri: str, **kwargs):
        socket = _FakeGeminiSocket()
        seen["uri"] = uri
        seen["kwargs"] = kwargs
        seen["socket"] = socket
        return socket

    monkeypatch.setattr(public_memorials, "websockets", SimpleNamespace(connect=_fake_connect))
    client = _client(principal_id="exec-memorial-live-vertex-ws")
    speech_pcm = _pcm16_speech_bytes()

    with client.websocket_connect(f"/memorials/{slug}/realtime?personal_memory=1") as websocket:
        ready = websocket.receive_json()
        assert ready["provider"] == "gemini_live"
        websocket.send_json(
            {
                "type": "user_audio_start",
                "turn_id": "turn_vertex",
                "content_type": "audio/pcm;rate=16000",
                "transport": "gemini_live",
            }
        )
        websocket.send_bytes(speech_pcm)
        websocket.send_json({"type": "user_audio_end", "turn_id": "turn_vertex"})
        messages = []
        for _ in range(12):
            message = websocket.receive_json()
            messages.append(message)
            if message.get("type") == "turn_complete":
                break

    fake_socket = seen["socket"]
    assert seen["uri"] == "wss://us-central1-aiplatform.googleapis.com/ws/google.cloud.aiplatform.v1.LlmBidiService/BidiGenerateContent"
    assert seen["kwargs"]["additional_headers"] == {"Authorization": "Bearer oauth-access-token"}
    assert fake_socket.sent[0]["setup"]["model"].startswith("projects/openclaw-concierge/locations/us-central1/")
    audio_payloads = [
        payload
        for payload in fake_socket.sent
        if isinstance(payload.get("realtime_input"), dict)
        and isinstance(payload["realtime_input"].get("media_chunks"), list)
    ]
    assert any(
        isinstance(payload.get("realtime_input"), dict)
        and payload["realtime_input"].get("activityStart") == {}
        for payload in fake_socket.sent
    )
    assert audio_payloads
    assert audio_payloads[0]["realtime_input"]["media_chunks"][0]["mime_type"] == "audio/pcm;rate=16000"
    assert audio_payloads[0]["realtime_input"]["media_chunks"][0]["data"] == base64.b64encode(speech_pcm).decode("ascii")
    assert any(
        isinstance(payload.get("realtime_input"), dict)
        and payload["realtime_input"].get("activityEnd") == {}
        for payload in fake_socket.sent
    )
    assert any(message.get("type") == "turn_complete" for message in messages)


def test_memorial_gemini_live_refreshes_expired_oauth_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.api.routes import public_memorials

    for name in list(os.environ):
        if name.startswith("GOOGLE_API_KEY_FALLBACK_"):
            monkeypatch.delenv(name, raising=False)
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "EA_GEMINI_API_KEY", "EA_GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    creds_path = tmp_path / "oauth_creds.json"
    creds_path.write_text(
        json.dumps(
            {
                "access_token": "expired-access-token",
                "refresh_token": "oauth-refresh-token",
                "scope": "https://www.googleapis.com/auth/cloud-platform",
                "token_type": "Bearer",
                "expiry_date": int((time.time() - 60) * 1000),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_MEMORIAL_GEMINI_OAUTH_CREDS_PATH", str(creds_path))
    monkeypatch.setenv("EA_MEMORIAL_GEMINI_LIVE_OAUTH", "1")
    monkeypatch.setenv("EA_MEMORIAL_GEMINI_OAUTH_CLIENT_ID", "test-oauth-client-id")
    monkeypatch.setenv("EA_MEMORIAL_GEMINI_OAUTH_CLIENT_SECRET", "test-oauth-client-secret")
    seen: dict[str, object] = {}

    class _RefreshResponse:
        status_code = 200
        text = "{}"

        def json(self):
            return {"access_token": "fresh-access-token", "expires_in": 3600, "token_type": "Bearer"}

    def _fake_post(url, *, data, timeout):
        seen["url"] = url
        seen["data"] = dict(data)
        seen["timeout"] = timeout
        return _RefreshResponse()

    monkeypatch.setattr(public_memorials.requests, "post", _fake_post)

    uri, headers, auth_mode = public_memorials._gemini_live_connect_target()

    assert auth_mode == "oauth"
    assert headers == {"Authorization": "Bearer fresh-access-token"}
    assert seen["url"] == "https://oauth2.googleapis.com/token"
    assert seen["data"]["client_id"] == "test-oauth-client-id"
    assert seen["data"]["client_secret"] == "test-oauth-client-secret"
    assert seen["data"]["refresh_token"] == "oauth-refresh-token"
    assert seen["data"]["grant_type"] == "refresh_token"
    refreshed = json.loads(creds_path.read_text(encoding="utf-8"))
    assert refreshed["access_token"] == "fresh-access-token"
    assert refreshed["ea_memorial_live_refreshed_at"]
    assert uri.startswith("wss://generativelanguage.googleapis.com/ws/")


def test_memorial_gemini_live_reuses_existing_google_oauth_client_for_first_refresh(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.api.routes import public_memorials

    for name in list(os.environ):
        if name.startswith("GOOGLE_API_KEY_FALLBACK_"):
            monkeypatch.delenv(name, raising=False)
    for name in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "EA_GEMINI_API_KEY",
        "EA_GOOGLE_API_KEY",
        "EA_MEMORIAL_GEMINI_OAUTH_CLIENT_ID",
        "EA_MEMORIAL_GEMINI_OAUTH_CLIENT_SECRET",
        "EA_GEMINI_OAUTH_CLIENT_ID",
        "EA_GEMINI_OAUTH_CLIENT_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)
    creds_path = tmp_path / "oauth_creds.json"
    creds_path.write_text(
        json.dumps(
            {
                "access_token": "stale-but-future-access-token",
                "refresh_token": "oauth-refresh-token",
                "scope": "https://www.googleapis.com/auth/cloud-platform",
                "token_type": "Bearer",
                "expiry_date": int((time.time() + 3600) * 1000),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_MEMORIAL_GEMINI_OAUTH_CREDS_PATH", str(creds_path))
    monkeypatch.setenv("EA_MEMORIAL_GEMINI_LIVE_OAUTH", "1")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_ID", "existing-google-client")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_SECRET", "existing-google-secret")
    seen: dict[str, object] = {}

    class _RefreshResponse:
        status_code = 200
        text = "{}"

        def json(self):
            return {"access_token": "fresh-google-client-token", "expires_in": 3600, "token_type": "Bearer"}

    def _fake_post(url, *, data, timeout):
        seen["data"] = dict(data)
        return _RefreshResponse()

    monkeypatch.setattr(public_memorials.requests, "post", _fake_post)

    uri, headers, auth_mode = public_memorials._gemini_live_connect_target()

    assert auth_mode == "oauth"
    assert headers == {"Authorization": "Bearer fresh-google-client-token"}
    assert seen["data"]["client_id"] == "existing-google-client"
    assert seen["data"]["client_secret"] == "existing-google-secret"
    assert uri.startswith("wss://generativelanguage.googleapis.com/ws/")
    refreshed = json.loads(creds_path.read_text(encoding="utf-8"))
    assert refreshed["ea_memorial_live_refreshed_at"]


def test_memorial_gemini_live_rejects_stale_oauth_when_required_refresh_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.api.routes import public_memorials

    for name in list(os.environ):
        if name.startswith("GOOGLE_API_KEY_FALLBACK_"):
            monkeypatch.delenv(name, raising=False)
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "EA_GEMINI_API_KEY", "EA_GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    creds_path = tmp_path / "oauth_creds.json"
    creds_path.write_text(
        json.dumps(
            {
                "access_token": "stale-token",
                "refresh_token": "oauth-refresh-token",
                "scope": "https://www.googleapis.com/auth/cloud-platform",
                "token_type": "Bearer",
                "expiry_date": int((time.time() + 3600) * 1000),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_MEMORIAL_GEMINI_OAUTH_CREDS_PATH", str(creds_path))
    monkeypatch.setenv("EA_MEMORIAL_GEMINI_LIVE_OAUTH", "1")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_ID", "existing-google-client")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_SECRET", "existing-google-secret")

    class _RefreshResponse:
        status_code = 401
        text = '{"error":"unauthorized_client"}'

        def json(self):
            return {"error": "unauthorized_client"}

    monkeypatch.setattr(public_memorials.requests, "post", lambda *args, **kwargs: _RefreshResponse())

    uri, headers, auth_mode = public_memorials._gemini_live_connect_target()

    assert uri == ""
    assert headers == {}
    assert auth_mode == ""
    failed = json.loads(creds_path.read_text(encoding="utf-8"))
    assert failed["ea_memorial_live_refresh_failed_at"]
    assert failed["ea_memorial_live_refresh_failed_reason"] == "http_401"


def test_memorial_gemini_live_oauth_refresh_failure_cooldown_skips_repeated_http(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.api.routes import public_memorials

    for name in list(os.environ):
        if name.startswith("GOOGLE_API_KEY_FALLBACK_"):
            monkeypatch.delenv(name, raising=False)
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "EA_GEMINI_API_KEY", "EA_GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    creds_path = tmp_path / "oauth_creds.json"
    creds_path.write_text(
        json.dumps(
            {
                "access_token": "stale-token",
                "refresh_token": "oauth-refresh-token",
                "scope": "https://www.googleapis.com/auth/cloud-platform",
                "token_type": "Bearer",
                "expiry_date": int((time.time() + 3600) * 1000),
                "ea_memorial_live_refresh_failed_at": time.time(),
                "ea_memorial_live_refresh_failed_reason": "http_401",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_MEMORIAL_GEMINI_OAUTH_CREDS_PATH", str(creds_path))
    monkeypatch.setenv("EA_MEMORIAL_GEMINI_LIVE_OAUTH", "1")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_ID", "existing-google-client")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_SECRET", "existing-google-secret")
    seen = {"post": 0}

    def _fake_post(*args, **kwargs):
        seen["post"] += 1
        raise AssertionError("cooldown should skip oauth refresh http call")

    monkeypatch.setattr(public_memorials.requests, "post", _fake_post)

    uri, headers, auth_mode = public_memorials._gemini_live_connect_target()

    assert uri == ""
    assert headers == {}
    assert auth_mode == ""
    assert seen["post"] == 0


def test_memorial_live_page_stays_voice_only_without_legacy_video_call_ui(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    client = _client(principal_id="exec-memorial-voice-only-page")

    response = client.get(f"/memorials/{slug}")
    assert response.status_code == 200
    source = response.text

    assert "continueVideoCallWithoutCamera()" not in source
    assert 'id="memorial-video-call-preview"' not in source
    assert 'id="memorial-video-call-avatar-video"' not in source
    assert 'id="memorial-voice-config-form"' not in source
    assert 'id="memorial-voice-ab-wrap"' not in source
    assert "/voice-config" not in source
    assert "/voice-ab" not in source
    assert "/voice-clone" not in source
    assert "write_token" not in source
    assert "memorial_write_token" not in source
    assert "x-memorial-write-token" not in source


def _reset_memorial_live_warmup_state(
    monkeypatch: pytest.MonkeyPatch,
) -> object:
    from app.api.routes import public_memorials

    monkeypatch.setattr(public_memorials, "_MEMORIAL_LIVE_WARMUP_STATE", {})
    monkeypatch.setattr(
        public_memorials,
        "_MEMORIAL_LIVE_WARMUP_ACTIVE_RESERVATIONS",
        set(),
    )
    monkeypatch.setattr(public_memorials, "_MEMORIAL_LIVE_WARMUP_RESERVATION_SEQUENCE", 0)
    monkeypatch.setattr(public_memorials, "_MEMORIAL_VOICE_PREWARM_RESERVATION_SEQUENCE", 0)
    monkeypatch.setattr(public_memorials, "_MEMORIAL_RUNTIME_READINESS_CACHE_STATE", {})
    monkeypatch.setattr(public_memorials, "_memorial_voice_release_enforced", lambda: False)
    return public_memorials


def test_memorial_live_warmup_reserves_slug_before_starting_one_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_memorials = _reset_memorial_live_warmup_state(monkeypatch)

    class DeferredThread:
        created: list[DeferredThread] = []

        def __init__(self, *, target, args, daemon, name) -> None:
            self.target = target
            self.args = args
            self.daemon = daemon
            self.name = name
            self.created.append(self)

        def start(self) -> None:
            return None

    caller_count = 8
    barrier = threading.Barrier(caller_count + 1)
    result_lock = threading.Lock()
    results: list[dict[str, object]] = []
    failures: list[BaseException] = []

    def schedule() -> None:
        try:
            barrier.wait(timeout=5.0)
            result = public_memorials._schedule_memorial_live_warmup("manfred")
            with result_lock:
                results.append(result)
        except BaseException as exc:  # pragma: no cover - asserted below
            with result_lock:
                failures.append(exc)

    monkeypatch.setattr(
        public_memorials,
        "threading",
        SimpleNamespace(Thread=DeferredThread),
    )
    callers = [threading.Thread(target=schedule) for _ in range(caller_count)]
    for caller in callers:
        caller.start()
    barrier.wait(timeout=5.0)
    for caller in callers:
        caller.join(timeout=5.0)

    assert not failures
    assert all(not caller.is_alive() for caller in callers)
    assert len(DeferredThread.created) == 1
    assert sum(result["status"] == "queued" for result in results) == 1
    assert sum(result["status"] == "warming" for result in results) == caller_count - 1
    assert sum(bool(result["scheduled"]) for result in results) == 1


def test_memorial_live_warmup_backs_off_after_worker_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_memorials = _reset_memorial_live_warmup_state(monkeypatch)

    class InlineThread:
        def __init__(self, *, target, args, daemon, name) -> None:
            self.target = target
            self.args = args
            self.daemon = daemon
            self.name = name

        def start(self) -> None:
            self.target(*self.args)

    monkeypatch.setenv("EA_MEMORIAL_LIVE_WARMUP_FAILURE_BACKOFF_SECONDS", "45")
    monkeypatch.setattr(
        public_memorials,
        "_run_memorial_live_warmup",
        lambda _slug, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(
        public_memorials,
        "threading",
        SimpleNamespace(Thread=InlineThread),
    )

    queued = public_memorials._schedule_memorial_live_warmup("manfred")
    backed_off = public_memorials._schedule_memorial_live_warmup("manfred")

    assert queued["status"] == "queued"
    assert queued["scheduled"] is True
    assert backed_off["status"] == "failure_backoff"
    assert backed_off["scheduled"] is False
    assert 1 <= backed_off["retry_after_seconds"] <= 45
    with public_memorials._MEMORIAL_LIVE_WARMUP_LOCK:
        current = dict(public_memorials._MEMORIAL_LIVE_WARMUP_STATE["manfred"])
        active = set(public_memorials._MEMORIAL_LIVE_WARMUP_ACTIVE_RESERVATIONS)
    assert current["inflight"] is False
    assert current["errors"] == ["warmup_worker:RuntimeError"]
    assert not active


def test_memorial_live_warmup_refuses_capacity_without_spawning_waiter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_memorials = _reset_memorial_live_warmup_state(monkeypatch)

    class DeferredThread:
        created: list[DeferredThread] = []

        def __init__(self, *, target, args, daemon, name) -> None:
            self.target = target
            self.args = args
            self.daemon = daemon
            self.name = name
            self.created.append(self)

        def start(self) -> None:
            return None

    monkeypatch.setenv("EA_MEMORIAL_LIVE_WARMUP_MAX_CONCURRENCY", "1")
    monkeypatch.setattr(
        public_memorials,
        "threading",
        SimpleNamespace(Thread=DeferredThread),
    )

    first = public_memorials._schedule_memorial_live_warmup("manfred")
    refused = public_memorials._schedule_memorial_live_warmup("erika")

    assert first["status"] == "queued"
    assert refused["status"] == "capacity_limited"
    assert refused["scheduled"] is False
    assert refused["retry_after_seconds"] == 1
    assert len(DeferredThread.created) == 1
    with public_memorials._MEMORIAL_LIVE_WARMUP_LOCK:
        assert "erika" not in public_memorials._MEMORIAL_LIVE_WARMUP_STATE
        assert len(public_memorials._MEMORIAL_LIVE_WARMUP_ACTIVE_RESERVATIONS) == 1


def test_memorial_live_warmup_cleans_reservation_when_thread_start_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_memorials = _reset_memorial_live_warmup_state(monkeypatch)

    class FailingThread:
        def __init__(self, *, target, args, daemon, name) -> None:
            self.target = target
            self.args = args
            self.daemon = daemon
            self.name = name

        def start(self) -> None:
            raise RuntimeError("thread unavailable")

    monkeypatch.setenv("EA_MEMORIAL_LIVE_WARMUP_FAILURE_BACKOFF_SECONDS", "17")
    monkeypatch.setattr(
        public_memorials,
        "threading",
        SimpleNamespace(Thread=FailingThread),
    )

    failed = public_memorials._schedule_memorial_live_warmup("manfred")
    backed_off = public_memorials._schedule_memorial_live_warmup("manfred")

    assert failed["status"] == "schedule_failed"
    assert failed["scheduled"] is False
    assert failed["retry_after_seconds"] == 17
    assert backed_off["status"] == "failure_backoff"
    with public_memorials._MEMORIAL_LIVE_WARMUP_LOCK:
        current = dict(public_memorials._MEMORIAL_LIVE_WARMUP_STATE["manfred"])
        active = set(public_memorials._MEMORIAL_LIVE_WARMUP_ACTIVE_RESERVATIONS)
    assert current["inflight"] is False
    assert "warmup_reservation_id" not in current
    assert current["errors"] == ["warmup_schedule:RuntimeError"]
    assert not active


def test_memorial_live_warmup_records_unexpected_inner_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_memorials = _reset_memorial_live_warmup_state(monkeypatch)
    reservation_id = "manfred:1"
    public_memorials._MEMORIAL_LIVE_WARMUP_STATE["manfred"] = {
        "inflight": True,
        "warmup_reservation_id": reservation_id,
    }
    monkeypatch.setattr(
        public_memorials,
        "_load_memorial",
        lambda _slug: (_ for _ in ()).throw(RuntimeError("unexpected")),
    )

    public_memorials._run_memorial_live_warmup(
        "manfred",
        reservation_id=reservation_id,
    )

    current = public_memorials._MEMORIAL_LIVE_WARMUP_STATE["manfred"]
    assert current["inflight"] is False
    assert current["errors"] == ["warmup:RuntimeError"]
    assert current["completed_at"] > 0.0


def test_memorial_live_warmup_recovers_orphaned_stale_reservation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_memorials = _reset_memorial_live_warmup_state(monkeypatch)

    class DeferredThread:
        created: list[DeferredThread] = []

        def __init__(self, *, target, args, daemon, name) -> None:
            self.target = target
            self.args = args
            self.daemon = daemon
            self.name = name
            self.created.append(self)

        def start(self) -> None:
            return None

    stale_reservation_id = "manfred:stale"
    public_memorials._MEMORIAL_LIVE_WARMUP_STATE["manfred"] = {
        "inflight": True,
        "started_at": time.time() - 10.0,
        "completed_at": time.time() - 4.0,
        "warmup_reservation_id": stale_reservation_id,
    }
    monkeypatch.setenv("EA_MEMORIAL_LIVE_WARMUP_STALE_SECONDS", "5")
    monkeypatch.setattr(
        public_memorials,
        "threading",
        SimpleNamespace(Thread=DeferredThread),
    )

    result = public_memorials._schedule_memorial_live_warmup("manfred")

    assert result["status"] == "queued"
    assert result["scheduled"] is True
    assert len(DeferredThread.created) == 1
    current = dict(public_memorials._MEMORIAL_LIVE_WARMUP_STATE["manfred"])
    replacement_id = str(current["warmup_reservation_id"])
    assert replacement_id != stale_reservation_id
    assert current["inflight"] is True
    assert current["completed_at"] == 0.0
    assert current["warmup_stale_recovery_error"] == (
        "warmup_worker:stale_superseded"
    )
    assert public_memorials._MEMORIAL_LIVE_WARMUP_ACTIVE_RESERVATIONS == {
        replacement_id
    }

    monkeypatch.setattr(
        public_memorials,
        "_run_memorial_live_warmup",
        lambda *_args, **_kwargs: None,
    )
    public_memorials._run_reserved_memorial_live_warmup(
        "manfred",
        stale_reservation_id,
    )
    assert public_memorials._MEMORIAL_LIVE_WARMUP_STATE["manfred"][
        "warmup_reservation_id"
    ] == replacement_id
    assert public_memorials._MEMORIAL_LIVE_WARMUP_STATE["manfred"][
        "inflight"
    ] is True


def test_memorial_live_warmup_does_not_oversubscribe_stale_active_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_memorials = _reset_memorial_live_warmup_state(monkeypatch)
    stale_reservation_id = "manfred:stale-active"
    public_memorials._MEMORIAL_LIVE_WARMUP_STATE["manfred"] = {
        "inflight": True,
        "started_at": time.time() - 10.0,
        "completed_at": time.time() - 4.0,
        "warmup_reservation_id": stale_reservation_id,
    }
    public_memorials._MEMORIAL_LIVE_WARMUP_ACTIVE_RESERVATIONS.add(
        stale_reservation_id
    )
    monkeypatch.setenv("EA_MEMORIAL_LIVE_WARMUP_STALE_SECONDS", "5")

    result = public_memorials._schedule_memorial_live_warmup("manfred")

    assert result == {
        "status": "warmup_stale",
        "scheduled": False,
        "ttl_seconds": public_memorials._MEMORIAL_LIVE_WARMUP_TTL_SECONDS,
        "retry_after_seconds": 1,
    }
    assert public_memorials._MEMORIAL_LIVE_WARMUP_ACTIVE_RESERVATIONS == {
        stale_reservation_id
    }
    current = public_memorials._MEMORIAL_LIVE_WARMUP_STATE["manfred"]
    assert current["warmup_reservation_id"] == stale_reservation_id
    assert current["inflight"] is True
    assert current["completed_at"] > 0.0


def _configure_enabled_unmixr_voice_prewarm(
    monkeypatch: pytest.MonkeyPatch,
    public_memorials: object,
) -> None:
    monkeypatch.setattr(
        public_memorials,
        "_load_voice_config",
        lambda _slug: {"tts_plugin": public_memorials.UNMIXR_TTS_PLUGIN_ID},
    )
    monkeypatch.setattr(
        public_memorials,
        "_tts_plugin_options",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(
        public_memorials,
        "_resolve_server_tts_plugin",
        lambda **_kwargs: (
            public_memorials.UNMIXR_TTS_PLUGIN_ID,
            {"tts_plugin_enabled": True},
        ),
    )


def test_memorial_voice_prewarm_reservation_deduplicates_fresh_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_memorials = _reset_memorial_live_warmup_state(monkeypatch)
    _configure_enabled_unmixr_voice_prewarm(monkeypatch, public_memorials)

    class DeferredThread:
        created: list[DeferredThread] = []

        def __init__(self, *, target, args, daemon, name) -> None:
            self.target = target
            self.args = args
            self.daemon = daemon
            self.name = name
            self.created.append(self)

        def start(self) -> None:
            return None

    monkeypatch.setattr(
        public_memorials,
        "threading",
        SimpleNamespace(Thread=DeferredThread),
    )

    first = public_memorials._schedule_missing_memorial_voice_prewarm("manfred")
    duplicate = public_memorials._schedule_missing_memorial_voice_prewarm(
        "manfred"
    )

    assert first is True
    assert duplicate is False
    assert len(DeferredThread.created) == 1
    current = public_memorials._MEMORIAL_LIVE_WARMUP_STATE["manfred"]
    assert current["voice_contact_inflight"] is True
    assert str(current["voice_prewarm_reservation_id"]).startswith(
        "manfred:voice:"
    )


def test_memorial_voice_prewarm_does_not_oversubscribe_stale_active_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_memorials = _reset_memorial_live_warmup_state(monkeypatch)
    _configure_enabled_unmixr_voice_prewarm(monkeypatch, public_memorials)
    stale_reservation_id = "manfred:voice:stale-active"
    original = {
        "voice_prewarm_reservation_id": stale_reservation_id,
        "voice_prewarm_provider": public_memorials.UNMIXR_TTS_PLUGIN_ID,
        "voice_contact_required": True,
        "voice_contact_inflight": True,
        "voice_contact_started_at": time.time() - 10.0,
        "voice_contact_completed_at": 0.0,
        "voice_contact_errors": [],
    }
    public_memorials._MEMORIAL_LIVE_WARMUP_STATE["manfred"] = dict(original)
    monkeypatch.setenv("EA_MEMORIAL_VOICE_PREWARM_STALE_SECONDS", "5")
    monkeypatch.setattr(
        public_memorials,
        "_schedule_memorial_server_voice_contact_prewarm",
        lambda *_args, **_kwargs: pytest.fail(
            "stale active provider worker was physically oversubscribed"
        ),
    )

    scheduled = public_memorials._schedule_missing_memorial_voice_prewarm(
        "manfred"
    )

    assert scheduled is False
    assert public_memorials._MEMORIAL_LIVE_WARMUP_STATE["manfred"] == original


def test_memorial_voice_prewarm_recovers_orphaned_stale_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_memorials = _reset_memorial_live_warmup_state(monkeypatch)
    _configure_enabled_unmixr_voice_prewarm(monkeypatch, public_memorials)
    public_memorials._MEMORIAL_LIVE_WARMUP_STATE["manfred"] = {
        "voice_prewarm_provider": public_memorials.UNMIXR_TTS_PLUGIN_ID,
        "voice_contact_required": True,
        "voice_contact_inflight": True,
        "voice_contact_started_at": time.time() - 10.0,
        "voice_contact_completed_at": 0.0,
        "voice_contact_errors": [],
    }
    monkeypatch.setenv("EA_MEMORIAL_VOICE_PREWARM_STALE_SECONDS", "5")
    scheduled_workers: list[tuple[str, str]] = []
    monkeypatch.setattr(
        public_memorials,
        "_schedule_memorial_server_voice_contact_prewarm",
        lambda slug, *, reservation_id: scheduled_workers.append(
            (slug, reservation_id)
        ),
    )

    scheduled = public_memorials._schedule_missing_memorial_voice_prewarm(
        "manfred"
    )

    assert scheduled is True
    assert len(scheduled_workers) == 1
    replacement_id = scheduled_workers[0][1]
    assert scheduled_workers[0][0] == "manfred"
    assert replacement_id.startswith("manfred:voice:")
    current = public_memorials._MEMORIAL_LIVE_WARMUP_STATE["manfred"]
    assert current["voice_prewarm_reservation_id"] == replacement_id
    assert current["voice_contact_inflight"] is True
    assert current["voice_contact_started_at"] > time.time() - 5.0


def test_memorial_voice_prewarm_reservation_rolls_back_thread_start_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_memorials = _reset_memorial_live_warmup_state(monkeypatch)
    _configure_enabled_unmixr_voice_prewarm(monkeypatch, public_memorials)

    class FailingThread:
        def __init__(self, *, target, args, daemon, name) -> None:
            self.target = target
            self.args = args
            self.daemon = daemon
            self.name = name

        def start(self) -> None:
            raise RuntimeError("thread unavailable")

    monkeypatch.setattr(
        public_memorials,
        "threading",
        SimpleNamespace(Thread=FailingThread),
    )

    scheduled = public_memorials._schedule_missing_memorial_voice_prewarm(
        "manfred"
    )

    assert scheduled is False
    current = public_memorials._MEMORIAL_LIVE_WARMUP_STATE["manfred"]
    assert current["voice_contact_inflight"] is False
    assert current["voice_contact_errors"] == [
        "voice_prewarm_schedule:RuntimeError"
    ]
    assert "voice_prewarm_reservation_id" not in current


def test_memorial_voice_prewarm_provider_switch_clears_stale_voicewave_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_memorials = _reset_memorial_live_warmup_state(monkeypatch)
    _configure_enabled_unmixr_voice_prewarm(monkeypatch, public_memorials)

    class DeferredThread:
        def __init__(self, *, target, args, daemon, name) -> None:
            self.target = target
            self.args = args
            self.daemon = daemon
            self.name = name

        def start(self) -> None:
            return None

    public_memorials._MEMORIAL_LIVE_WARMUP_STATE["manfred"] = {
        "voice_prewarm_provider": public_memorials.VOICEWAVE_TTS_PLUGIN_ID,
        "voice_contact_required": True,
        "voice_contact_inflight": False,
        "voice_contact_completed_at": time.time() - 700.0,
        "voice_contact_errors": ["old-general-error"],
        "voicewave_contact_required": True,
        "voicewave_contact_inflight": False,
        "voicewave_contact_started_at": time.time() - 710.0,
        "voicewave_contact_completed_at": time.time() - 700.0,
        "voicewave_contact_errors": ["old-voicewave-error"],
    }
    monkeypatch.setattr(
        public_memorials,
        "threading",
        SimpleNamespace(Thread=DeferredThread),
    )

    scheduled = public_memorials._schedule_missing_memorial_voice_prewarm(
        "manfred"
    )

    assert scheduled is True
    current = public_memorials._MEMORIAL_LIVE_WARMUP_STATE["manfred"]
    assert current["voice_prewarm_provider"] == (
        public_memorials.UNMIXR_TTS_PLUGIN_ID
    )
    assert current["voicewave_contact_required"] is False
    assert current["voicewave_contact_inflight"] is False
    assert current["voicewave_contact_started_at"] == 0.0
    assert current["voicewave_contact_completed_at"] == 0.0
    assert current["voicewave_contact_errors"] == []


def test_memorial_voice_prewarm_completion_race_preserves_ready_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_memorials = _reset_memorial_live_warmup_state(monkeypatch)
    _configure_enabled_unmixr_voice_prewarm(monkeypatch, public_memorials)
    completed_at = time.time()

    def complete_then_resolve(**_kwargs):
        public_memorials._MEMORIAL_LIVE_WARMUP_STATE["manfred"] = {
            "voice_prewarm_provider": public_memorials.UNMIXR_TTS_PLUGIN_ID,
            "voice_contact_required": True,
            "voice_contact_inflight": False,
            "voice_contact_started_at": completed_at - 1.0,
            "voice_contact_completed_at": completed_at,
            "voice_contact_errors": [],
        }
        return (
            public_memorials.UNMIXR_TTS_PLUGIN_ID,
            {"tts_plugin_enabled": True},
        )

    monkeypatch.setattr(
        public_memorials,
        "_resolve_server_tts_plugin",
        complete_then_resolve,
    )
    monkeypatch.setattr(
        public_memorials,
        "_schedule_memorial_server_voice_contact_prewarm",
        lambda *_args, **_kwargs: pytest.fail(
            "completed voice prewarm was redundantly replaced"
        ),
    )

    scheduled = public_memorials._schedule_missing_memorial_voice_prewarm(
        "manfred"
    )
    response = public_memorials._memorial_live_warmup_existing_response(
        "manfred",
        {
            "inflight": False,
            "warm": True,
            "voice_required": True,
            "voice_prewarm_stale": False,
            "voice_ready": False,
            "voice_inflight": False,
        },
    )

    assert scheduled is False
    assert response == {
        "status": "warm_recent",
        "scheduled": False,
        "ttl_seconds": public_memorials._MEMORIAL_LIVE_WARMUP_TTL_SECONDS,
    }
    current = public_memorials._MEMORIAL_LIVE_WARMUP_STATE["manfred"]
    assert current["voice_contact_completed_at"] == completed_at
    assert current["voice_contact_errors"] == []


def test_memorial_voice_prewarm_old_generation_cannot_overwrite_newer_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_memorials = _reset_memorial_live_warmup_state(monkeypatch)
    current = {
        "voice_prewarm_reservation_id": "manfred:voice:new",
        "voice_contact_inflight": True,
        "voice_contact_started_at": time.time(),
        "voice_contact_errors": [],
    }
    public_memorials._MEMORIAL_LIVE_WARMUP_STATE["manfred"] = dict(current)
    monkeypatch.setattr(
        public_memorials,
        "_load_voice_config",
        lambda _slug: pytest.fail("stale worker reached provider configuration"),
    )

    public_memorials._run_memorial_server_voice_contact_prewarm(
        "manfred",
        "manfred:voice:old",
    )

    assert public_memorials._MEMORIAL_LIVE_WARMUP_STATE["manfred"] == current


def test_memorial_voicewave_prewarm_unexpected_failure_is_not_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_memorials = _reset_memorial_live_warmup_state(monkeypatch)
    reservation_id = "manfred:voice:1"
    public_memorials._MEMORIAL_LIVE_WARMUP_STATE["manfred"] = {
        "voice_prewarm_reservation_id": reservation_id,
        "voice_contact_inflight": True,
        "voicewave_contact_inflight": True,
    }
    monkeypatch.setattr(
        public_memorials,
        "_load_voice_config",
        lambda _slug: (_ for _ in ()).throw(RuntimeError("unexpected")),
    )

    public_memorials._run_memorial_voicewave_contact_prewarm(
        "manfred",
        "Manfred",
        reservation_id,
    )

    current = public_memorials._MEMORIAL_LIVE_WARMUP_STATE["manfred"]
    assert current["voice_contact_inflight"] is False
    assert current["voicewave_contact_inflight"] is False
    assert current["voice_contact_errors"] == [
        "voicewave_prewarm:unexpected"
    ]
    assert "voice_prewarm_reservation_id" not in current


def _configure_isolated_onemin_transcription_test(
    monkeypatch: pytest.MonkeyPatch,
    *,
    response: dict[str, object],
    observed_languages: list[str],
    add_success_status: bool = True,
) -> None:
    from app.api.routes import public_memorials
    from app.product import service as product_service

    _clear_cartesia_env(monkeypatch)
    public_memorials._MEMORIAL_STT_PROVIDER_COOLDOWNS.clear()
    public_memorials._MEMORIAL_STT_KEY_COOLDOWNS.clear()
    monkeypatch.setattr(
        public_memorials,
        "_memorial_shadow_stt_result",
        lambda **kwargs: {
            "enabled": False,
            "provider": "blipai",
            "status": "skipped",
            "transcript_text": "",
            "correction": {"should_correct": False},
        },
    )
    monkeypatch.setattr(
        public_memorials,
        "_convert_audio_to_wav",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("skip_enhanced")),
    )
    monkeypatch.setattr(public_memorials, "_wav_payload_has_speech_energy", lambda payload: True)
    monkeypatch.setattr(product_service, "_pocket_onemin_api_keys", lambda: ("key-1",))
    monkeypatch.setattr(
        product_service,
        "_onemin_asset_upload",
        lambda **kwargs: {"asset": {"key": "audio"}, "fileContent": {"path": "audio-path"}},
    )

    response_payload = dict(response)
    if add_success_status and isinstance(response_payload.get("aiRecord"), dict):
        ai_record = dict(response_payload["aiRecord"])
        ai_record.setdefault("status", "SUCCESS")
        response_payload["aiRecord"] = ai_record

    def _fake_onemin_speech_to_text(**kwargs):
        observed_languages.append(str(kwargs.get("language") or ""))
        return response_payload

    monkeypatch.setattr(product_service, "_onemin_speech_to_text", _fake_onemin_speech_to_text)


@pytest.mark.parametrize(
    ("source_language", "provider_language", "transcript"),
    (
        ("en-US", "en", "Anna opens the lantern while Ben reads the first page aloud."),
        ("de-AT", "de", "Anna öffnet die Laterne, während Ben die erste Seite laut liest."),
    ),
)
def test_memorial_transcribe_forwards_source_language_and_extracts_only_verbose_text(
    monkeypatch: pytest.MonkeyPatch,
    source_language: str,
    provider_language: str,
    transcript: str,
) -> None:
    from app.api.routes import public_memorials

    observed_languages: list[str] = []
    _configure_isolated_onemin_transcription_test(
        monkeypatch,
        observed_languages=observed_languages,
        response={
            "aiRecord": {
                "aiRecordDetail": {
                    "responseObject": {
                        "content": json.dumps(
                            {
                                "task": "transcribe",
                                "language": "provider metadata",
                                "duration": 20.4,
                                "text": transcript,
                                "segments": [{"text": "verbose metadata must not be appended"}],
                            }
                        )
                    }
                }
            }
        },
    )

    result = public_memorials._memorial_transcribe_audio_blob(
        payload=_generated_wav_bytes(textish_seed=transcript),
        content_type="audio/wav",
        language=source_language,
    )

    assert result["transcription_status"] == "transcribed"
    assert result["transcript_text"] == transcript
    assert observed_languages == [provider_language]


def test_memorial_transcribe_fails_closed_when_onemin_response_has_no_transcript_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials

    observed_languages: list[str] = []
    _configure_isolated_onemin_transcription_test(
        monkeypatch,
        observed_languages=observed_languages,
        response={
            "aiRecord": {
                "aiRecordDetail": {
                    "responseObject": {
                        "content": json.dumps(
                            {
                                "task": "transcribe",
                                "duration": 20.4,
                                "segments": [
                                    {"text": "segment metadata is not an authoritative transcript"}
                                ],
                            }
                        )
                    },
                    "resultObject": {"output": "plain provider metadata"},
                }
            }
        },
    )

    result = public_memorials._memorial_transcribe_audio_blob(
        payload=_generated_wav_bytes(textish_seed="Anna and Ben"),
        content_type="audio/wav",
        language="en-US",
    )

    assert result["transcription_status"] == "no_speech"
    assert result["transcript_text"] == ""
    assert result["retryable"] is True
    assert observed_languages == ["en"]


def test_audiobook_publication_stt_forwards_source_language_to_runtime_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.api.routes import public_memorials
    from app.services import audiobook_epub_pipeline

    monkeypatch.delenv("EA_AUDIOBOOK_PUBLICATION_STT_COMMAND", raising=False)
    monkeypatch.setattr(
        audiobook_epub_pipeline,
        "_transcribe_audiobook_publication_stt_sample_with_cartesia",
        lambda **kwargs: {"status": "failed", "reason": "cartesia_api_key_missing"},
    )
    observed: dict[str, object] = {}

    def _fake_runtime_transcribe(**kwargs):
        observed.update(kwargs)
        return {
            "transcription_status": "transcribed",
            "transcript_text": "Anna opens the lantern.",
            "transcriber": "1min.ai/whisper-1",
        }

    monkeypatch.setattr(public_memorials, "_memorial_transcribe_audio_blob", _fake_runtime_transcribe)
    sample_path = tmp_path / "sample.wav"
    sample_path.write_bytes(b"rights-safe-audio-fixture")

    result = audiobook_epub_pipeline._transcribe_audiobook_publication_stt_sample(
        sample_path=sample_path,
        language="en-US",
    )

    assert result["status"] == "transcribed"
    assert result["transcriber"] == "1min.ai/whisper-1"
    assert observed["language"] == "en-US"


def test_memorial_onemin_top_level_plaintext_response_object_remains_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials

    transcript = "Anna opens the lantern while Ben reads the first page aloud."
    observed_languages: list[str] = []
    _configure_isolated_onemin_transcription_test(
        monkeypatch,
        observed_languages=observed_languages,
        response={
            "aiRecord": {
                "aiRecordDetail": {
                    "responseObject": transcript,
                }
            }
        },
    )

    result = public_memorials._memorial_transcribe_audio_blob(
        payload=_generated_wav_bytes(textish_seed=transcript),
        content_type="audio/wav",
        language="en-US",
    )

    assert result["transcription_status"] == "transcribed"
    assert result["transcript_text"] == transcript
    assert observed_languages == ["en"]


@pytest.mark.parametrize(
    ("source_language", "provider_language"),
    (("en-US", "en"), ("de-AT", "de")),
)
def test_memorial_cartesia_fallback_uses_primary_language(
    monkeypatch: pytest.MonkeyPatch,
    source_language: str,
    provider_language: str,
) -> None:
    from app.api.routes import public_memorials
    from app.product import service as product_service

    monkeypatch.setenv("CARTESIA_API_KEY", "cartesia-test-key")
    monkeypatch.setattr(
        public_memorials,
        "_memorial_shadow_stt_result",
        lambda **kwargs: {
            "enabled": False,
            "provider": "blipai",
            "status": "skipped",
            "transcript_text": "",
            "correction": {"should_correct": False},
        },
    )
    observed_languages: list[str] = []

    def _fake_cartesia(**kwargs):
        observed_languages.append(str(kwargs.get("language") or ""))
        return {"text": "Anna opens the lantern while Ben reads the first page aloud."}

    monkeypatch.setattr(public_memorials, "_cartesia_transcribe_audio", _fake_cartesia)
    monkeypatch.setattr(product_service, "_pocket_onemin_api_keys", lambda: ())

    result = public_memorials._memorial_transcribe_audio_blob(
        payload=_generated_wav_bytes(textish_seed="Anna and Ben"),
        content_type="audio/wav",
        language=source_language,
    )

    assert result["transcription_status"] == "transcribed"
    assert observed_languages
    assert set(observed_languages) == {provider_language}
    assert public_memorials._memorial_cartesia_language(source_language) == provider_language


@pytest.mark.parametrize(
    ("source_language", "provider_language"),
    (("en-US", "en"), ("de-AT", "de")),
)
def test_audiobook_cartesia_request_uses_primary_language(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source_language: str,
    provider_language: str,
) -> None:
    import requests

    from app.services import audiobook_epub_pipeline

    monkeypatch.setattr(audiobook_epub_pipeline, "_audiobook_cartesia_api_key", lambda: "cartesia-test-key")
    observed: dict[str, object] = {}

    class _Response:
        status_code = 200

        @staticmethod
        def json():
            return {"text": "Anna opens the lantern while Ben reads the first page aloud."}

    def _fake_post(*args, **kwargs):
        observed.update(kwargs)
        return _Response()

    monkeypatch.setattr(requests, "post", _fake_post)
    sample_path = tmp_path / "sample.wav"
    sample_path.write_bytes(b"rights-safe-audio-fixture")

    result = audiobook_epub_pipeline._transcribe_audiobook_publication_stt_sample_with_cartesia(
        sample_path=sample_path,
        language=source_language,
    )

    assert result["status"] == "transcribed"
    assert dict(observed["data"])["language"] == provider_language
    assert audiobook_epub_pipeline._audiobook_cartesia_language(source_language) == provider_language


@pytest.mark.parametrize("invalid_language", ("eng-US", "eng", "e-US", "english"))
def test_cartesia_language_normalizers_reject_non_iso_639_1_primaries(
    invalid_language: str,
) -> None:
    from app.api.routes import public_memorials
    from app.services import audiobook_epub_pipeline

    assert public_memorials._memorial_cartesia_language(invalid_language) == "de"
    assert audiobook_epub_pipeline._audiobook_cartesia_language(invalid_language) == "de"


def test_onemin_whisper_request_uses_documented_plain_text_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.product import service as product_service

    observed: dict[str, object] = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        @staticmethod
        def read() -> bytes:
            return b'{"aiRecord":{"status":"SUCCESS"}}'

    def _fake_urlopen(request, timeout=180):
        observed["url"] = request.full_url
        observed["body"] = json.loads(request.data.decode("utf-8"))
        observed["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(product_service.urllib.request, "urlopen", _fake_urlopen)

    result = product_service._onemin_speech_to_text(
        api_key="private-test-key",
        audio_path="audios/private-test.wav",
        language="en",
    )

    assert result["aiRecord"]["status"] == "SUCCESS"
    assert observed["url"] == "https://api.1min.ai/api/features"
    assert observed["timeout"] == 180
    assert observed["body"] == {
        "type": "SPEECH_TO_TEXT",
        "model": "whisper-1",
        "promptObject": {
            "audioUrl": "audios/private-test.wav",
            "response_format": "text",
            "language": "en",
        },
    }


def test_onemin_transcript_parser_accepts_only_one_unambiguous_result() -> None:
    from app.product import service as product_service

    transcript = "Anna opens the lantern while Ben reads the first page aloud."

    assert product_service._onemin_transcript_text([transcript]) == transcript
    assert product_service._onemin_transcript_text([{"text": transcript}]) == transcript
    assert product_service._onemin_transcript_text([transcript, "provider metadata"]) == ""
    assert product_service._onemin_transcript_text({"output": "provider metadata"}) == ""


def test_pocket_onemin_retranscription_uses_safe_single_result_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.product import service as product_service

    transcript = "Anna opens the lantern while Ben reads the first page aloud."
    monkeypatch.setattr(product_service, "_pocket_onemin_api_keys", lambda: ("key-1",))
    monkeypatch.setattr(
        product_service,
        "_pocket_download_audio_blob",
        lambda **kwargs: (b"audio", "audio/wav", "https://example.invalid/audio.wav"),
    )
    monkeypatch.setattr(product_service, "_pocket_guess_audio_filename", lambda **kwargs: "audio.wav")
    monkeypatch.setattr(
        product_service,
        "_onemin_asset_upload",
        lambda **kwargs: {"fileContent": {"path": "audios/private.wav"}},
    )
    monkeypatch.setattr(
        product_service,
        "_onemin_speech_to_text",
        lambda **kwargs: {
            "aiRecord": {
                "status": "SUCCESS",
                "aiRecordDetail": {"resultObject": [transcript]},
            }
        },
    )

    result = product_service._pocket_retranscribe_with_onemin(
        recording_id="recording-1",
        title="Private title",
        language="en",
        audio_download_url="https://example.invalid/audio.wav",
    )

    assert result is not None
    assert result["transcript_text"] == transcript
    assert result["transcript_segment_count"] == 0


@pytest.mark.parametrize(
    "record_status",
    ("PROCESSING", "FAILURE", "unexpected-private-status", ""),
)
def test_pocket_onemin_retranscription_requires_success_status(
    monkeypatch: pytest.MonkeyPatch,
    record_status: str,
) -> None:
    from app.product import service as product_service

    monkeypatch.setattr(product_service, "_pocket_onemin_api_keys", lambda: ("key-1",))
    monkeypatch.setattr(
        product_service,
        "_pocket_download_audio_blob",
        lambda **kwargs: (b"audio", "audio/wav", "https://example.invalid/audio.wav"),
    )
    monkeypatch.setattr(product_service, "_pocket_guess_audio_filename", lambda **kwargs: "audio.wav")
    monkeypatch.setattr(
        product_service,
        "_onemin_asset_upload",
        lambda **kwargs: {"fileContent": {"path": "audios/private.wav"}},
    )
    monkeypatch.setattr(
        product_service,
        "_onemin_speech_to_text",
        lambda **kwargs: {
            "aiRecord": {
                "status": record_status,
                "aiRecordDetail": {"resultObject": ["private result must be ignored"]},
            }
        },
    )

    safe_status = (
        record_status.lower()
        if record_status in {"PROCESSING", "FAILURE"}
        else "missing" if not record_status else "other"
    )
    with pytest.raises(RuntimeError, match=f"^onemin_transcribe_status_{safe_status}$"):
        product_service._pocket_retranscribe_with_onemin(
            recording_id="recording-1",
            title="Private title",
            language="en",
            audio_download_url="https://example.invalid/audio.wav",
        )


def test_pocket_onemin_retranscription_continues_to_next_bounded_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.product import service as product_service

    transcript = "Anna opens the lantern while Ben reads the first page aloud."
    calls: list[str] = []
    monkeypatch.setattr(product_service, "_pocket_onemin_api_keys", lambda: ("key-1", "key-2"))
    monkeypatch.setattr(
        product_service,
        "_pocket_download_audio_blob",
        lambda **kwargs: (b"audio", "audio/wav", "https://example.invalid/audio.wav"),
    )
    monkeypatch.setattr(product_service, "_pocket_guess_audio_filename", lambda **kwargs: "audio.wav")
    monkeypatch.setattr(
        product_service,
        "_onemin_asset_upload",
        lambda **kwargs: {"fileContent": {"path": "audios/private.wav"}},
    )

    def _fake_transcribe(**kwargs):
        api_key = str(kwargs.get("api_key") or "")
        calls.append(api_key)
        if api_key == "key-1":
            return {"aiRecord": {"status": "FAILURE", "aiRecordDetail": {}}}
        return {
            "aiRecord": {
                "status": "SUCCESS",
                "aiRecordDetail": {"resultObject": [transcript]},
            }
        }

    monkeypatch.setattr(product_service, "_onemin_speech_to_text", _fake_transcribe)

    result = product_service._pocket_retranscribe_with_onemin(
        recording_id="recording-1",
        title="Private title",
        language="en",
        audio_download_url="https://example.invalid/audio.wav",
    )

    assert result is not None
    assert result["transcript_text"] == transcript
    assert calls == ["key-1", "key-2"]


def test_onemin_http_failures_never_expose_provider_response_bodies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from io import BytesIO

    from app.product import service as product_service

    private_body = b"PRIVATE_TRANSCRIPT_AND_PROVIDER_ID"

    def _raise_http_error(request, timeout=180):
        raise product_service.urllib.error.HTTPError(
            request.full_url,
            502,
            "private provider error",
            {},
            BytesIO(private_body),
        )

    monkeypatch.setattr(product_service.urllib.request, "urlopen", _raise_http_error)

    with pytest.raises(RuntimeError, match="^onemin_transcribe_http_502$") as transcribe_error:
        product_service._onemin_speech_to_text(
            api_key="private-test-key",
            audio_path="audios/private.wav",
            language="en",
        )
    with pytest.raises(RuntimeError, match="^onemin_asset_http_502$") as asset_error:
        product_service._onemin_asset_upload(
            api_key="private-test-key",
            filename="private.wav",
            content_type="audio/wav",
            payload=b"private audio",
        )

    assert private_body.decode("ascii") not in str(transcribe_error.value)
    assert private_body.decode("ascii") not in str(asset_error.value)
    assert "private provider error" not in str(transcribe_error.value)


def test_memorial_onemin_rejects_non_success_record_even_with_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials

    private_text = "PRIVATE failed provider output"
    observed_languages: list[str] = []
    _configure_isolated_onemin_transcription_test(
        monkeypatch,
        observed_languages=observed_languages,
        response={
            "aiRecord": {
                "status": "FAILURE",
                "aiRecordDetail": {"resultObject": [private_text]},
            }
        },
    )

    result = public_memorials._memorial_transcribe_audio_blob(
        payload=_generated_wav_bytes(textish_seed="Anna and Ben"),
        content_type="audio/wav",
        language="en-US",
    )

    assert result["transcription_status"] == "no_speech"
    assert result["detail"] == (
        "speech_transcribe_not_success:original:status_failure:"
        "response_missing:result_array_1_string_plain"
    )
    assert private_text not in json.dumps(result, sort_keys=True)


def test_memorial_onemin_rejects_missing_record_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials

    private_text = "PRIVATE missing-status provider output"
    observed_languages: list[str] = []
    _configure_isolated_onemin_transcription_test(
        monkeypatch,
        observed_languages=observed_languages,
        add_success_status=False,
        response={
            "aiRecord": {
                "aiRecordDetail": {"resultObject": [private_text]},
            }
        },
    )

    result = public_memorials._memorial_transcribe_audio_blob(
        payload=_generated_wav_bytes(textish_seed="Anna and Ben"),
        content_type="audio/wav",
        language="en-US",
    )

    assert result["transcription_status"] == "no_speech"
    assert result["detail"] == (
        "speech_transcribe_not_success:original:status_missing:"
        "response_missing:result_array_1_string_plain"
    )
    assert private_text not in json.dumps(result, sort_keys=True)


def test_memorial_transcribe_accepts_documented_single_result_text_array(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials

    transcript = "Anna opens the lantern while Ben reads the first page aloud."
    observed_languages: list[str] = []
    _configure_isolated_onemin_transcription_test(
        monkeypatch,
        observed_languages=observed_languages,
        response={
            "aiRecord": {
                "status": "SUCCESS",
                "aiRecordDetail": {"resultObject": [transcript]},
            }
        },
    )

    result = public_memorials._memorial_transcribe_audio_blob(
        payload=_generated_wav_bytes(textish_seed=transcript),
        content_type="audio/wav",
        language="en-US",
    )

    assert result["transcription_status"] == "transcribed"
    assert result["transcript_text"] == transcript
    assert observed_languages == ["en"]


def test_memorial_empty_transcript_reports_only_content_free_provider_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials

    private_text = "PRIVATE BOOK TEXT must never enter a failure receipt"
    observed_languages: list[str] = []
    _configure_isolated_onemin_transcription_test(
        monkeypatch,
        observed_languages=observed_languages,
        response={
            "aiRecord": {
                "status": "SUCCESS",
                "aiRecordDetail": {
                    "responseObject": {"content": private_text},
                    "resultObject": [
                        {"text": private_text},
                        {"text": "alternate provider output"},
                    ],
                },
            }
        },
    )

    result = public_memorials._memorial_transcribe_audio_blob(
        payload=_generated_wav_bytes(textish_seed="Anna and Ben"),
        content_type="audio/wav",
        language="en-US",
    )

    assert result["transcription_status"] == "no_speech"
    assert result["transcript_text"] == ""
    assert result["detail"] == (
        "speech_transcript_empty:original:status_success:"
        "response_object_content:result_array_2_object_text"
    )
    assert private_text not in json.dumps(result, sort_keys=True)
    assert "alternate provider output" not in json.dumps(result, sort_keys=True)
    assert observed_languages == ["en"]
