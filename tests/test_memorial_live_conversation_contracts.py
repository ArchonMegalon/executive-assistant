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
        ("Hallo Manfred, kann ich jetzt mit dir reden?", "Ja"),
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

    seen_messages: list[list[dict[str, str]]] = []
    input_audio = _generated_wav_bytes(textish_seed="Hallo Manfred, kann ich jetzt mit dir reden?")
    output_audio = _generated_wav_bytes(textish_seed="Ja, ich bin da.")

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
        "piper_fast_synthesize_request",
        lambda **kwargs: (output_audio, "audio/wav"),
    )
    monkeypatch.setattr(
        public_memorials,
        "_pad_speech_audio_lead_in",
        lambda *, payload, content_type, silence_ms, tail_silence_ms, extra_filters: (payload, content_type),
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
    assert body["transcript_text"] == "Hallo Manfred, kann ich jetzt mit dir reden?"
    assert body["sources"] == []
    assert "Ja, ich bin da." in body["answer"]
    decoded_audio = base64.b64decode(body["audio_base64"])
    assert decoded_audio.startswith(b"RIFF")
    assert body["audio_content_type"] == "audio/wav"
    assert seen_messages
    assert any(
        "memorial_timing event=conversation_turn" in record.getMessage()
        and "requested_model=ea-gemini-flash" in record.getMessage()
        and f"tts_plugin={public_memorials.PIPER_FAST_TTS_PLUGIN_ID}" in record.getMessage()
        for record in caplog.records
    )
    evidence_block = seen_messages[-1][1]["content"]
    assert "Antwortmodus: gegenwaertige Live-Interaktion." in evidence_block
    assert "Erinnerungsgedaechtnis:" not in evidence_block


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
        "piper_fast_synthesize_request",
        lambda **kwargs: (output_audio, "audio/wav"),
    )
    monkeypatch.setattr(
        public_memorials,
        "_pad_speech_audio_lead_in",
        lambda *, payload, content_type, silence_ms, tail_silence_ms, extra_filters: (payload, content_type),
    )

    client = _client(principal_id="exec-memorial-live-gemini-turn")
    response = client.post(
        f"/memorials/{slug}/conversation-turn",
        content=input_audio,
        headers={"content-type": "audio/wav"},
    )

    assert response.status_code == 200
    body = response.json()
    assert seen_requested_models == [GEMINI_VORTEX_PUBLIC_MODEL]
    assert body["llm_request_model"] == GEMINI_VORTEX_PUBLIC_MODEL
    assert body["llm_fallback_used"] is False


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
        "ttl_seconds": 600,
    }


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
