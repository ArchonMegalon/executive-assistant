from __future__ import annotations

import base64
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
    assert body["answer"] == "Ja."


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
    assert body["answer"] == "Ja."
    assert body["llm_provider"] == "memorial_guardrail"
    assert body["fallback_reason"] == "direct_contact_opening"
    decoded_audio = base64.b64decode(body["audio_base64"])
    assert decoded_audio.startswith(b"RIFF")
    assert body["audio_content_type"] == "audio/wav"
    assert body["tts_plugin"] == public_memorials.OPENVOICE_TTS_PLUGIN_ID
    assert body["tts_fast_path"] is False
    assert seen_pad_calls == [{"silence_ms": 40, "tail_silence_ms": 120}]
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
    assert body["answer"] == "Ja."


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
    assert seen_voicewave_calls == [
        {
            "text": body["answer"],
            "voice_label": "Manfred Hoza Memorial",
        }
    ]


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

    assert seen_render_calls == [
        {
            "text": "Ja.",
            "slug": slug,
            "selected_plugin": public_memorials.VOICEWAVE_TTS_PLUGIN_ID,
            "lead_in_ms": 40,
            "tail_silence_ms": 120,
        },
        {
            "text": "Ja.",
            "slug": slug,
            "selected_plugin": public_memorials.VOICEWAVE_TTS_PLUGIN_ID,
            "lead_in_ms": 40,
            "tail_silence_ms": 120,
        },
        {
            "text": "Ja.",
            "slug": slug,
            "selected_plugin": public_memorials.VOICEWAVE_TTS_PLUGIN_ID,
            "lead_in_ms": 40,
            "tail_silence_ms": 120,
        },
    ]


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

    assert answer_message["text"] == "Ja."
    assert speaking_phase["detail"] == ""
    assert seen_pad_calls == [{"silence_ms": 40, "tail_silence_ms": 120}]


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

    answer = public_memorials._memorial_chat_answer(
        {"slug": slug, "person_name": "Manfred Hoza", "audio_clips": []},
        "Erzaehl mir etwas ueber deine Jugend.",
        {},
        "memorial-local-fast",
        slug=slug,
    )

    assert answer["llm_model"] == "memorial-local-fast"
    assert answer["llm_provider"] == "memorial_guardrail"
    assert answer["llm_request_model"] == "memorial-local-fast"
    assert answer["llm_fallback_used"] is True


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


def test_memorial_browser_playback_guardrails_are_shipped() -> None:
    source = Path("/docker/EA/ea/app/api/routes/public_memorials.py").read_text(encoding="utf-8")

    assert "audio_never_started" in source
    assert "audio_ended_too_soon" in source
    assert "/memorials/{html.escape(slug)}/playback-telemetry" in source
    assert "Manfreds Stimme konnte gerade nicht sauber starten." in source
    assert "Audio war gerade unzuverlaessig. Ich wechsle auf Browser-Stimme." not in source


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


def test_memorial_voicewave_postprocess_trims_dead_tail_silence() -> None:
    from app.api.routes import public_memorials

    filters = public_memorials._speech_postprocess_filters(public_memorials.VOICEWAVE_TTS_PLUGIN_ID)

    assert "silenceremove=stop_periods=-1" in filters
    assert "stop_duration=0.02" in filters
    assert "stop_threshold=-24dB" in filters
    assert "stop_silence=0.005" in filters
    assert "atempo=2.50" in filters


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
    assert 'text="Ich bin da."' in source


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


def test_memorial_live_page_uses_minimal_conversation_turn_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = _setup_memorial(monkeypatch, tmp_path)
    client = _client(principal_id="exec-memorial-minimal-client")

    response = client.get(f"/memorials/{slug}")
    assert response.status_code == 200
    source = response.text

    assert "(payload.voice_required === false || payload.voice_ready === true)" in source
    assert "/memorials/manfred/conversation-turn" in source
    assert 'requestMemorialWarmup("page_load")' in source
    assert 'requestMemorialWarmup("conversation_start")' in source
    assert "beginManualRecording" in source
    assert "finishConversationRecording" in source
    assert "Aufnahme beenden" in source
    assert "captureTurnAudio" not in source
    assert "ontouchstart=" not in source
    assert 'if (window.speechSynthesis) window.speechSynthesis.cancel();' in source
    assert "retireLegacyMemorialServiceWorkers" in source
    assert "navigator.serviceWorker.register" not in source
    assert "primeRealtimeSocket" not in source
    assert "cancelRealtimeTurn" not in source


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
