from __future__ import annotations

import base64
import asyncio
import io
import json
import logging
import math
import os
import struct
import time
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from app.services.brain_catalog import GEMINI_VORTEX_PUBLIC_MODEL


CONTACT_REPLY_VARIANTS = {"Worum geht es?"}


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

    client = TestClient(create_app())
    client.headers.update({"X-EA-Principal-ID": principal_id})
    return client


def _write_public_memorial(root: Path, slug: str, payload: dict[str, object]) -> None:
    bundle_dir = root / slug
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "memorial.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_private_voice(root: Path, slug: str, payload: dict[str, object]) -> None:
    profile_dir = root / slug
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "tts_voice.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


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


def _setup_memorial(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    slug = "manfred"
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
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
                {"label": "Interview Audio", "status": "audio_ready", "url": "https://youtube.example/interview"}
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


def test_memorial_shadow_stt_fast_primary_candidate_accepts_plausible_user_question() -> None:
    from app.api.routes import public_memorials

    assert public_memorials._memorial_shadow_stt_is_fast_primary_candidate("Wie ist das Wetter heute in Wien?") is True
    assert public_memorials._memorial_shadow_stt_is_fast_primary_candidate("Hallo Manfred, kannst du jetzt mit mir sprechen?") is True
    assert public_memorials._memorial_shadow_stt_is_fast_primary_candidate("Was ist der aktuelle Stand?") is True


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


def test_memorial_transcribe_applies_shadow_stt_correction_to_effective_transcript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials
    from app.product import service as product_service

    monkeypatch.setattr(product_service, "_pocket_onemin_api_keys", lambda: ("key-1",))
    monkeypatch.setattr(
        product_service,
        "_onemin_asset_upload",
        lambda **kwargs: {"asset": {"key": "audio-key"}, "fileContent": {"path": "audio-path"}},
    )
    monkeypatch.setattr(
        product_service,
        "_onemin_speech_to_text",
        lambda **kwargs: {"aiRecord": {"aiRecordDetail": {"responseObject": {"text": "Untertitel der Amara.org-Community"}}}},
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
    assert result["primary_transcript_text"] == "Untertitel der Amara.org-Community"


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
        lambda **kwargs: {"aiRecord": {"aiRecordDetail": {"responseObject": {"text": "Wie ist das Wetter heute in Wien?"}}}},
    )
    monkeypatch.setattr(public_memorials, "_wav_payload_has_speech_energy", lambda payload: True)

    result = public_memorials._memorial_transcribe_audio_blob(
        payload=_generated_wav_bytes(textish_seed="Wie ist das Wetter heute in Wien?"),
        content_type="audio/wav",
    )

    assert result["transcript_text"] == "Wie ist das Wetter heute in Wien?"
    assert result["transcriber"] == "1min.ai/whisper-1+enhanced_wav"


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
        return {"aiRecord": {"aiRecordDetail": {"responseObject": {"text": text}}}}

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
        return {"aiRecord": {"aiRecordDetail": {"responseObject": {"text": text}}}}

    monkeypatch.setattr(product_service, "_onemin_speech_to_text", _fake_stt)

    result = public_memorials._memorial_transcribe_audio_blob(
        payload=b"not-a-real-webm",
        content_type="audio/webm",
    )

    assert len(seen_paths) == 1
    assert result["transcript_text"] == "Wie ist das Wetter heute in Wien?"
    assert result["primary_transcript_text"] == "Wie ist das Wetter heute in Wien?"
    assert result["transcriber"].endswith("enhanced_wav")


def test_memorial_transcribe_prefers_enhanced_wav_before_original_for_strong_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials
    from app.product import service as product_service

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
        return {"aiRecord": {"aiRecordDetail": {"responseObject": {"text": "Wie ist das Wetter heute in Wien?"}}}}

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
        return {"aiRecord": {"aiRecordDetail": {"responseObject": {"text": "Wie ist das Wetter heute in Wien?"}}}}

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

    seen_messages: list[list[dict[str, str]]] = []
    input_audio = _generated_wav_bytes(textish_seed="Hallo Manfred, kann ich jetzt mit dir reden?")
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
        "openvoice_synthesize_request_with_variant",
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
    decoded_audio = base64.b64decode(body["audio_base64"])
    assert decoded_audio.startswith(b"RIFF")
    assert body["audio_content_type"] == "audio/wav"
    assert body["tts_plugin"] == public_memorials.OPENVOICE_TTS_PLUGIN_ID
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
        and f"tts_plugin={public_memorials.OPENVOICE_TTS_PLUGIN_ID}" in record.getMessage()
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
        "openvoice_synthesize_request_with_variant",
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
        "openvoice_synthesize_request_with_variant",
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


def test_memorial_conversation_turn_exposes_original_and_effective_transcript_text(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

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
        "openvoice_synthesize_request_with_variant",
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
        "openvoice_synthesize_request_with_variant",
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

    input_audio = _generated_wav_bytes(textish_seed="Kannst du mich hoeren?")
    output_audio = _generated_wav_bytes(textish_seed="Ich antworte aus dem Erinnerungsmodus.")

    monkeypatch.setattr(
        public_memorials,
        "_memorial_transcribe_audio_blob",
        lambda **kwargs: {
            "transcription_status": "transcribed",
            "transcript_text": "Kannst du mich hoeren?",
            "transcriber": "unit-test",
        },
    )

    def _slow_chat_answer(*args, **kwargs):
        time.sleep(0.05)
        return {
            "answer": "Diese langsame Antwort darf nicht ausgeliefert werden.",
            "sources": [],
            "llm_model": "slow-model",
            "llm_provider": "slow-provider",
            "llm_request_model": "slow-model",
            "llm_fallback_used": False,
        }

    monkeypatch.setattr(public_memorials, "_MEMORIAL_CONVERSATION_TURN_LLM_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(public_memorials, "_memorial_chat_answer", _slow_chat_answer)
    monkeypatch.setattr(
        public_memorials,
        "openvoice_synthesize_request_with_variant",
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
    assert body["llm_fallback_used"] is True
    assert body["llm_provider"] == "memorial_guardrail"
    assert body["fallback_reason"] == "conversation_turn_llm_timeout"
    assert body["audio_base64"]
    assert "langsame Antwort" not in body["answer"]


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

    input_audio = _generated_wav_bytes(textish_seed="Hallo Manfred, kann ich jetzt mit dir reden?")
    output_audio = _generated_wav_bytes(textish_seed="Ja, ich bin da.")
    openvoice_calls: list[dict[str, object]] = []

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
        "openvoice_synthesize_request_with_variant",
        lambda **kwargs: openvoice_calls.append(kwargs) or (output_audio, "audio/wav"),
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
    assert openvoice_calls
    assert body["tts_plugin"] == public_memorials.OPENVOICE_TTS_PLUGIN_ID
    assert body["tts_fast_path"] is False
    assert "tts_fast_path_reason" not in body
    assert scheduled == []


def test_memorial_conversation_turn_rescues_transcription_failure_with_ooda_reply(
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
        content=_generated_wav_bytes(textish_seed="Hallo?"),
        headers={"content-type": "audio/wav"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "ort" in body["answer"].lower()
    assert "zeit" in body["answer"].lower()
    assert body["fallback_reason"] == "rescue_ooda_loop"
    assert body["turn_rescue_reason"] == "speech_transcription_empty"
    assert body["tts_plugin"] == public_memorials.UNMIXR_TTS_PLUGIN_ID
    assert seen_unmixr_calls


def test_memorial_conversation_turn_rescues_throttled_transcription_with_ooda_reply(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
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

    output_audio = _generated_wav_bytes(textish_seed="Ordne mir erst Ort, Zeit und den konkreten Stand.")
    seen_openvoice_calls: list[dict[str, object]] = []

    def _raise_throttled(**kwargs):
        raise public_memorials.HTTPException(
            status_code=502,
            detail="Request was throttled. Expected available in 3007 seconds.:429",
        )

    monkeypatch.setattr(public_memorials, "_memorial_transcribe_audio_blob", _raise_throttled)
    monkeypatch.setattr(
        public_memorials,
        "openvoice_synthesize_request_with_variant",
        lambda **kwargs: seen_openvoice_calls.append(kwargs) or (output_audio, "audio/wav"),
    )
    monkeypatch.setattr(
        public_memorials,
        "_pad_speech_audio_lead_in",
        lambda *, payload, content_type, silence_ms, tail_silence_ms, extra_filters: (payload, content_type),
    )

    client = _client(principal_id="exec-memorial-live-rescue-throttle")
    response = client.post(
        f"/memorials/{slug}/conversation-turn",
        content=_generated_wav_bytes(textish_seed="Hallo?"),
        headers={"content-type": "audio/wav"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "ort" in body["answer"].lower()
    assert "zeit" in body["answer"].lower()
    assert body["fallback_reason"] == "rescue_ooda_loop"
    assert "Request was throttled" in body["turn_rescue_reason"]
    assert body["tts_plugin"] == public_memorials.OPENVOICE_TTS_PLUGIN_ID
    assert seen_openvoice_calls


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
        content=_generated_wav_bytes(textish_seed="Hallo?"),
        headers={"content-type": "audio/wav"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["fallback_reason"] == "rescue_ooda_loop"
    assert body["audio_unavailable"] is True
    assert body["audio_base64"] == ""
    assert "ort" in body["answer"].lower()


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
        "piper_fast_synthesize_request",
        lambda **kwargs: (b"RIFFwarmup", "audio/wav"),
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
        "piper_fast_synthesize_request",
        lambda **kwargs: (b"RIFFwarmup", "audio/wav"),
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

    _write_private_voice(
        Path(str(tmp_path / "private")),
        slug,
        {
            "tts_plugin": public_memorials.PIPER_FAST_TTS_PLUGIN_ID,
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

    cache_root = tmp_path / "tts-cache"
    synth_calls = {"count": 0}
    pad_calls = {"count": 0}

    monkeypatch.setattr(public_memorials, "_MEMORIAL_TTS_RENDER_CACHE_ROOT", cache_root)
    monkeypatch.setattr(
        public_memorials,
        "piper_fast_synthesize_request",
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
    assert (
        "ich spreche hier so, wie ihr mich erinnert" in body["answer"].lower()
        or "so spreche ich hier" in body["answer"].lower()
    )


def test_memorial_realtime_rejects_audio_bytes_before_start(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    _write_private_voice(
        Path(str(tmp_path / "private")),
        slug,
        {
            "tts_plugin": public_memorials.PIPER_FAST_TTS_PLUGIN_ID,
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

    _write_private_voice(
        Path(str(tmp_path / "private")),
        slug,
        {
            "tts_plugin": public_memorials.PIPER_FAST_TTS_PLUGIN_ID,
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
    client = _client(principal_id="exec-memorial-live-realtime-mode")

    with client.websocket_connect(f"/memorials/{slug}/realtime") as websocket:
        ready = websocket.receive_json()

    assert ready["type"] == "ready"
    assert ready["mode"] == "memorial_realtime_voice"
    assert ready["audio_transport"] == "gemini_live_websocket_pcm"
    assert ready["turn_timing"] == "streaming_audio_server_vad"
    assert ready["provider"] == "gemini_live"
    assert ready["fallback_provider"] == "ea_memorial_turn"
    assert ready["fallback_transport"] == "ea_websocket_audio_turn"
    assert "openai" not in json.dumps(ready).lower()
    assert ready["redesign_target"] == "native_speech_to_speech_live_audio"


def test_memorial_realtime_text_turn_falls_back_when_llm_times_out(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    output_audio = _generated_wav_bytes(textish_seed="Fallback Antwort von Manfred.")
    _write_private_voice(
        Path(str(tmp_path / "private")),
        slug,
        {
            "tts_plugin": public_memorials.PIPER_FAST_TTS_PLUGIN_ID,
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
        "piper_fast_synthesize_request",
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
    source = Path("/docker/EA/ea/app/api/routes/public_memorials.py").read_text(encoding="utf-8")

    assert 'raise HTTPException(status_code=504, detail="tts_timeout")' in source
    assert 'raise HTTPException(status_code=502, detail="tts_plugin_failed")' in source
    assert "Realtime conversation optimizes for immediate audible response over premium voice quality." not in source


def test_memorial_realtime_contact_opening_uses_short_reply_and_small_audio_pad(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    _write_private_voice(
        Path(str(tmp_path / "private")),
        slug,
        {
            "tts_plugin": public_memorials.PIPER_FAST_TTS_PLUGIN_ID,
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

    output_audio = _generated_wav_bytes(textish_seed="Ja. Du kannst mit mir reden.")
    seen_pad_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        public_memorials,
        "piper_fast_synthesize_request",
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
    assert seen_pad_calls == [
        {
            "silence_ms": public_memorials._MEMORIAL_CONTACT_TTS_LEAD_IN_MS,
            "tail_silence_ms": public_memorials._MEMORIAL_CONTACT_TTS_TAIL_SILENCE_MS,
        }
    ]


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
            "tts_plugin": public_memorials.PIPER_FAST_TTS_PLUGIN_ID,
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
        "piper_fast_synthesize_request",
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


def test_memorial_voice_chat_model_prefers_gemini_for_live_interaction() -> None:
    from app.api.routes import public_memorials

    selected = public_memorials._resolve_memorial_voice_chat_model(
        {"chat_models": [GEMINI_VORTEX_PUBLIC_MODEL, "ea-coder-fast", "deepseek-chat"]},
        {},
        "Hallo Manfred, kannst du kurz direkt mit mir reden?",
    )

    assert selected == GEMINI_VORTEX_PUBLIC_MODEL


def test_memorial_voice_chat_model_forces_gemini_for_live_interaction_even_when_catalog_prefers_coder() -> None:
    from app.api.routes import public_memorials

    selected = public_memorials._resolve_memorial_voice_chat_model(
        {"chat_models": ["ea-coder-fast", "deepseek-chat"]},
        {},
        "Hallo Manfred, kannst du kurz direkt mit mir reden?",
    )

    assert selected == GEMINI_VORTEX_PUBLIC_MODEL


def test_memorial_voice_chat_model_keeps_memorial_local_fast_as_default_non_live_choice() -> None:
    from app.api.routes import public_memorials

    selected = public_memorials._resolve_memorial_voice_chat_model(
        {"chat_models": ["memorial-local-fast", GEMINI_VORTEX_PUBLIC_MODEL, "ea-coder-fast"]},
        {},
        "Erzaehl mir etwas ueber deine Jugend.",
    )

    assert selected == "memorial-local-fast"


def test_memorial_voice_chat_model_uses_gemini_live_fallback_without_explicit_model_catalog() -> None:
    from app.api.routes import public_memorials

    selected = public_memorials._resolve_memorial_voice_chat_model(
        {},
        {},
        "Hallo Manfred, kann ich jetzt mit dir reden?",
    )

    assert selected == GEMINI_VORTEX_PUBLIC_MODEL


def test_memorial_realtime_chat_model_always_prefers_gemini() -> None:
    from app.api.routes import public_memorials

    selected = public_memorials._resolve_memorial_realtime_chat_model(
        {"chat_models": ["memorial-local-fast", "ea-coder-best"]},
        {},
    )

    assert selected == GEMINI_VORTEX_PUBLIC_MODEL


def test_memorial_realtime_chat_model_never_uses_default_openai_style_fallback() -> None:
    from app.api.routes import public_memorials

    selected = public_memorials._resolve_memorial_realtime_chat_model({}, {})

    assert selected == GEMINI_VORTEX_PUBLIC_MODEL
    assert selected != public_memorials.DEFAULT_PUBLIC_MODEL


def test_memorial_realtime_timeout_copy_invites_retry_without_sounding_like_a_failure() -> None:
    source = Path("/docker/EA/ea/app/api/routes/public_memorials.py").read_text(encoding="utf-8")

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


def test_public_memorial_page_primes_background_warmup_on_render(
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
    assert seen == [slug]


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


def test_memorial_warmup_status_route_reports_snapshot_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    from app.api.routes import public_memorials

    monkeypatch.setattr(
        public_memorials,
        "_memorial_live_warmup_snapshot",
        lambda warmup_slug: {
            "status": "warm_recent",
            "warm": True,
            "inflight": False,
            "started_at": 123.0,
            "completed_at": 145.0,
            "errors": [],
            "voice_ready": True,
            "voice_inflight": False,
            "voice_completed_at": 145.0,
            "voice_errors": [],
            "voice_required": True,
        },
    )

    client = _client(principal_id="exec-memorial-warmup-status")
    response = client.get(f"/memorials/{slug}/warmup-status")

    assert response.status_code == 200
    assert response.json() == {
        "slug": slug,
        "status": "warm_recent",
        "warm": True,
        "inflight": False,
        "started_at": 123.0,
        "completed_at": 145.0,
        "errors": [],
        "voice_ready": True,
        "voice_inflight": False,
        "voice_completed_at": 145.0,
        "voice_errors": [],
        "voice_required": True,
        "ttl_seconds": 600,
    }


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
    source = Path("/docker/EA/ea/app/api/routes/public_memorials.py").read_text(encoding="utf-8")

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
    source = Path("/docker/EA/ea/app/api/routes/public_memorials.py").read_text(encoding="utf-8")

    assert 'transcribingText: "Einen Moment ..."' in source
    assert 'setSpeechStatus("Ich höre zu.", "listening", "Sprich, wenn du magst");' in source
    assert 'setTimeout(recordConversationTurn, 1200);' in source
    assert "Ich habe dich sofort. Einen Moment ..." not in source
    assert "Ich habe dich. Einen Moment ..." not in source


def test_memorial_live_page_source_accepts_shorter_first_turn_browser_transcripts() -> None:
    source = Path("/docker/EA/ea/app/api/routes/public_memorials.py").read_text(encoding="utf-8")

    assert "const looksGreeting =" in source
    assert "const hasSpeechLikeChars = /[a-z0-9äöüß]/i.test(normalized);" in source
    assert "isFirstConversationTurn && hasSpeechLikeChars && normalized.length >= 3" in source
    assert "conversationIdleMisses >= 1 && hasSpeechLikeChars && normalized.length >= 2" in source
    assert "if (!looksDirected && !(conversationIdleMisses >= 1 && normalized.length >= 8 && words.length >= 2)) return false;" in source


def test_memorial_live_page_source_does_not_fallback_to_browser_voice_when_realtime_server_audio_is_missing() -> None:
    source = Path("/docker/EA/ea/app/api/routes/public_memorials.py").read_text(encoding="utf-8")

    assert 'browserSpeechFallbackConfig("Browser Fallback")' not in source
    assert "Manfreds Stimme konnte gerade nicht sauber starten." in source
    assert '}} else if (conversationActive) {{' in source


def test_memorial_live_page_source_primes_audio_output_before_playback() -> None:
    source = Path("/docker/EA/ea/app/api/routes/public_memorials.py").read_text(encoding="utf-8")

    assert "async function primeMemorialAudioOutput(durationMs = 900)" in source
    assert "gain.gain.value = 0.0008;" in source
    assert "await primeMemorialAudioOutput(650);" in source
    assert "void primeMemorialAudioOutput(1200);" in source
    assert "void primeMemorialAudioOutput(900);" in source


def test_memorial_live_page_source_rejects_cut_off_audio_before_next_turn() -> None:
    source = Path("/docker/EA/ea/app/api/routes/public_memorials.py").read_text(encoding="utf-8")

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
    assert response.json()["transcript_text"] == "Hallo Manfred"
    assert any(
        "memorial_timing event=speech_transcribe" in record.getMessage()
        and "transcript_chars=13" in record.getMessage()
        and "status=transcribed" in record.getMessage()
        for record in caplog.records
    )


def test_memorial_warmup_prefers_fast_piper_tts_instead_of_profile_voice() -> None:
    source = Path("/docker/EA/ea/app/api/routes/public_memorials.py").read_text(encoding="utf-8")

    assert 'selected_plugin = PIPER_FAST_TTS_PLUGIN_ID' in source
    assert 'piper_fast_synthesize_request(' in source
    assert '_memorial_contact_answer_body("Hallo Manfred")' in source


def test_memorial_landing_does_not_enable_conversation_on_warmup_timeout() -> None:
    source = Path("/docker/EA/ea/app/api/routes/public_memorials.py").read_text(encoding="utf-8")

    assert "waitForMemorialVoiceReady(30000)" in source
    assert 'setMemorialLandingReady(false, "Ich bin gleich bereit.")' in source
    assert 'if (!memorialLandingReady) void ensureMemorialReady("warmup_retry");' in source
    assert 'let contactAcknowledgementReady = false;' in source
    assert 'contactAcknowledgementReady = true;' in source
    assert 'memorialLandingReady && completedConversationTurns === 0 && !contactAcknowledgementReady' in source
    assert 'label = "Stimme wird vorbereitet …";' in source
    assert 'setMemorialLandingReady(false, "Ich bereite meine Stimme noch kurz vor.");' in source
    assert 'void ensureMemorialReady("contact_ack_retry");' in source
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


def test_memorial_contact_tts_cache_adopts_legacy_runtime_key(
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

    monkeypatch.setattr(
        public_memorials,
        "unmixr_synthesize_request",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("legacy cache entry should be adopted before synthesis")),
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
    assert audio == legacy_audio


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
    assert "/memorials/manfred/conversation-turn" in source
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
    assert 'const contactAcknowledgementText = "Worum geht es?";' in source
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
    assert "activeRealtimeAudioTurn.sendBlob(event.data)" not in source
    assert "blob.arrayBuffer().then" in source
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
    assert "beginConversationRecording" in source
    assert "finishConversationTurn" in source
    assert "window.__memorialMinimalBooted" in source
    assert "startConversation();" not in source
    assert "Gespräch stoppen" in source
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
    assert response.json()["error"]["code"] == "gemini_live_unavailable"


def test_memorial_full_realtime_client_uses_funeral_safe_pause_threshold() -> None:
    source = Path("/docker/EA/ea/app/api/routes/public_memorials.py").read_text(encoding="utf-8")

    assert "Number(options.silenceMs || 520)" in source
    assert "const minSpeechMs = 520" in source
    assert "Math.max(420, Number(options.silenceMs || 520))" in source


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
        phase = websocket.receive_json()
        fallback_phase = websocket.receive_json()

    assert phase["phase"] == "listening"
    assert fallback_phase == {
        "type": "phase",
        "turn_id": "turn_scope_open",
        "phase": "listening",
        "detail": "Audio wird empfangen",
    }


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
        for _ in range(8):
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
