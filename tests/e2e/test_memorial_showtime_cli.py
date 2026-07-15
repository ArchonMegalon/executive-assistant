from __future__ import annotations

import json
import math
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

uvicorn = pytest.importorskip("uvicorn")
Config = uvicorn.Config
Server = uvicorn.Server

from app.api.app import create_app


ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = ROOT / "ea"
EXAMPLES_ROOT = ROOT / "examples"


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def _wait_for_http(base_url: str, *, timeout_seconds: float = 15.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/memorials/manfred", timeout=2.0) as response:
                if int(getattr(response, "status", 0) or 0) == 200:
                    return
        except Exception:
            time.sleep(0.1)
    raise AssertionError(f"server at {base_url} did not become ready in time")


def _generated_wav_bytes(*, seed: str) -> bytes:
    sample_rate = 16000
    seed_value = sum((seed or "seed").encode("utf-8", errors="ignore")) or 1
    frequency = 180 + (seed_value % 120)
    lead = [0.0] * int(sample_rate * 0.2)
    tone = [0.18 * math.sin(2 * math.pi * frequency * i / sample_rate) for i in range(int(sample_rate * 1.0))]
    tail = [0.0] * int(sample_rate * 0.3)
    pcm = b"".join(
        int(max(-1.0, min(1.0, value)) * 32767).to_bytes(2, "little", signed=True)
        for value in (lead + tone + tail)
    )
    data_size = len(pcm)
    riff_size = 36 + data_size
    return (
        b"RIFF"
        + int(riff_size).to_bytes(4, "little")
        + b"WAVEfmt "
        + int(16).to_bytes(4, "little")
        + int(1).to_bytes(2, "little")
        + int(1).to_bytes(2, "little")
        + int(16000).to_bytes(4, "little")
        + int(32000).to_bytes(4, "little")
        + int(2).to_bytes(2, "little")
        + int(16).to_bytes(2, "little")
        + b"data"
        + int(data_size).to_bytes(4, "little")
        + pcm
    )


@pytest.fixture()
def memorial_showtime_server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[dict[str, object]]:
    from app.api.routes import public_memorials
    from app.services import memorial_archive_registry

    monkeypatch.setenv("EA_STORAGE_BACKEND", "memory")
    monkeypatch.setenv("EA_API_TOKEN", "")
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_ARCHIVE_PUBLISHED_SLUGS", "manfred")
    monkeypatch.delenv("EA_LEDGER_BACKEND", raising=False)
    monkeypatch.delenv("EA_DEFAULT_PRINCIPAL_ID", raising=False)
    monkeypatch.delenv("EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER", raising=False)
    monkeypatch.delenv("EA_OPERATOR_PRINCIPAL_IDS", raising=False)

    slug = "manfred"
    public_root = tmp_path / "public"
    private_root = tmp_path / "private"
    artifacts_root = tmp_path / "artifacts"
    registry_root = public_root
    bundle = public_root / slug
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "audio").mkdir()
    (bundle / "audio" / "clip.mp3").write_bytes(b"clip")
    (bundle / "icons").mkdir()
    for size in (180, 192, 512):
        (bundle / "icons" / f"manfred-{size}.png").write_bytes(b"\x89PNG\r\n\x1a\nicon")
    (bundle / "memorial.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "person_name": "Manfred Hoza",
                "title": "Erinnerungen an Manfred",
                "subtitle": "Eine ruhige Seite fuer Erinnerungen, belegte Gedanken und oeffentliche Quellen.",
                "intro": "Freigegebene Erinnerungen und nachvollziehbare Quellen stehen im Mittelpunkt.",
                "disclosure": "Neue Antworten bleiben quellengebunden und sind keine Originalaufnahme.",
                "audio_clips": [{"public": True, "asset_relpath": "audio/clip.mp3"}],
                "memory_cards": [
                    {
                        "public": True,
                        "title": "Gerechtigkeit",
                        "body": "Tatsachen, Verantwortung und Fairness gehoerten fuer ihn zusammen.",
                    }
                ],
                "external_sources": [
                    {
                        "visibility": "public",
                        "public": True,
                        "approved": True,
                        "label": "Oeffentliche Quelle",
                        "url": "https://example.test/manfred",
                        "status": "belegt",
                    }
                ],
                "suggested_prompts": ["Was war dir bei Gerechtigkeit wichtig?"],
                "pwa_app_name": "Manfred Gedenkseite",
                "pwa_short_name": "Manfred",
                "pwa_icon": {
                    "src_180": "icons/manfred-180.png",
                    "src_192": "icons/manfred-192.png",
                    "src_512": "icons/manfred-512.png",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (private_root / slug).mkdir(parents=True, exist_ok=True)
    (private_root / slug / "llm_profile_notes.json").write_text(
        json.dumps(
            {
                "visibility": "private_llm_context_only_not_public_page",
                "family_context_notes": [
                    {
                        "label": "private_family_context",
                        "confidence": "family_observation_no_diagnosis",
                        "note": "Private memorial-only notes to activate difficult-memory guardrails in tests.",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (private_root / slug / "tts_voice.json").write_text(
        json.dumps(
            {
                "tts_plugin": public_memorials.UNMIXR_TTS_PLUGIN_ID,
                "tts_plugin_voice_id": "fixture-unmixr-voice",
                "voice_label": "Tibor freigegebene synthetische Stimme",
                "voice_consent": {
                    "status": "approved",
                    "scope": ["synthesize", "conversation_turn", "realtime"],
                    "authorized_by": "family-owner",
                    "authorized_at": "2026-06-05T16:25:00Z",
                    "source_assets_reviewed": True,
                    "revoked": False,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (registry_root / slug).mkdir(parents=True, exist_ok=True)
    (registry_root / slug / "archive_registry.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "archive_sections": [{"title": "Oeffentliches Archiv", "audience": "public", "items": ["doc-public"]}],
                "fliplink_publications": [
                    {
                        "approved": True,
                        "id": "doc-public",
                        "title": "Public Doc",
                        "audience": "public",
                        "viewer_type": "smart_document",
                        "url": "https://archive.example/public",
                        "sensitivity": "PUBLIC",
                        "review_status": "published",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    public_memorials._PERSONAL_MEMORY_ROOT = artifacts_root / "memorial_user_memory"
    public_memorials._VOICE_AB_ROOT = artifacts_root / "memorial_voice_ab"
    public_memorials._PUBLIC_MEMORIAL_RATE_DB = artifacts_root / "memorial_rate_limits.sqlite3"
    public_memorials._MEMORIAL_TTS_RENDER_CACHE_ROOT = artifacts_root / "memorial_tts_render_cache"
    public_memorials._MEMORIAL_PRESENT_WORLD_CACHE_ROOT = artifacts_root / "memorial_present_world_cache"
    memorial_archive_registry.PUBLIC_MEMORIAL_ROOT = registry_root
    memorial_archive_registry.ARCHIVE_ROOT = tmp_path / "archive"

    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    monkeypatch.setenv("EA_PRIVATE_MEMORIAL_PROFILE_DIR", str(private_root))
    monkeypatch.setenv("UNMIXR_API_KEY", "fixture-unmixr-key")
    monkeypatch.setenv("UNMIXR_VOICE_ID", "fixture-unmixr-voice")
    transcript_lookup: dict[bytes, str] = {}

    def _fake_generate_text(*, messages, requested_model, max_output_tokens):
        prompt = str(messages[-1]["content"] or "").lower()
        if "gerechtigkeit" in prompt:
            text = "Ich wollte die Dinge sauber und fair trennen. Erst die Sache, dann das Urteil."
        elif "schach" in prompt:
            text = "Mit dem Schach sollt ihr ordentlich umgehen und nicht leichtfertig werden."
        elif "wirklich manfred" in prompt:
            text = "Ich spreche hier so, wie ihr mich erinnert, und bleibe bei dem, was belegt ist."
        else:
            text = "Ich antworte dir direkt und bleibe bei der Sache."
        return SimpleNamespace(text=text, provider_key="unit-test-model", model="unit-test-model")

    monkeypatch.setattr(public_memorials, "generate_text", _fake_generate_text)
    monkeypatch.setattr(public_memorials, "_enforce_public_memorial_rate_limit", lambda *args, **kwargs: None)
    def _fake_unmixr_synthesize_request(**kwargs):
        text = str(kwargs.get("text") or "audio")
        payload = _generated_wav_bytes(seed=text)
        transcript_lookup[payload] = text
        return payload, "audio/wav"

    monkeypatch.setattr(public_memorials, "unmixr_synthesize_request", _fake_unmixr_synthesize_request)

    def _fake_transcribe_audio_blob(*, payload: bytes, content_type: str) -> dict[str, object]:
        raw = bytes(payload or b"")
        text = transcript_lookup.get(raw, "")
        if not text:
            text = "Ich antworte dir direkt und bleibe bei der Sache."
        return {
            "transcription_status": "transcribed",
            "transcript_text": text,
            "transcriber": "fixture_stub",
        }

    monkeypatch.setattr(public_memorials, "_memorial_transcribe_audio_blob", _fake_transcribe_audio_blob)
    monkeypatch.setattr(
        public_memorials,
        "_pad_speech_audio_lead_in",
        lambda *, payload, content_type, silence_ms, tail_silence_ms, extra_filters: (payload, content_type),
    )

    port = _free_port()
    config = Config(app=create_app(), host="127.0.0.1", port=port, log_level="warning")
    server = Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    _wait_for_http(base_url)
    try:
        yield {
            "base_url": base_url,
            "slug": slug,
            "public_root": public_root,
            "private_root": private_root,
        }
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_memorial_showtime_cli_writes_pass_report(
    memorial_showtime_server: dict[str, object],
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "showtime"
    env = dict(os.environ)
    env["EA_PUBLIC_MEMORIAL_DIR"] = str(memorial_showtime_server["public_root"])
    env["EA_PRIVATE_MEMORIAL_PROFILE_DIR"] = str(memorial_showtime_server["private_root"])
    env["PYTHONPATH"] = str(APP_ROOT)
    env["TMPDIR"] = str(tmp_path / "tmp")
    Path(env["TMPDIR"]).mkdir(exist_ok=True)

    result = subprocess.run(
        [
            sys.executable,
            str(APP_ROOT / "scripts" / "memorial_showtime.py"),
            "--slug",
            "manfred",
            "--base-url",
            str(memorial_showtime_server["base_url"]),
            "--questions",
            str(EXAMPLES_ROOT / "demo_questions.manfred.json"),
            "--output-dir",
            str(output_dir),
            "--skip-unit-contracts",
            "--skip-exit-gates",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    report_json = output_dir / "showtime_report.json"
    report_md = output_dir / "showtime_report.md"
    snapshot = output_dir / "manfred_launch_snapshot.json"
    tts_audio = output_dir / "manfred-demo-tts.wav"
    voice_loop = output_dir / "voice_loop_report.json"

    assert report_json.is_file()
    assert report_md.is_file()
    assert snapshot.is_file()
    assert tts_audio.is_file()
    assert voice_loop.is_file()

    payload = json.loads(report_json.read_text(encoding="utf-8"))
    assert payload["status"] == "pass"
    names = [item["name"] for item in payload["results"]]
    assert "filesystem_preflight" in names
    assert "live_preflight" in names
    assert "live_demo_rehearsal" in names
    assert "voice_roundtrip_validation" in names
    assert "launch_snapshot" in names
    snapshot_step = next(item for item in payload["results"] if item["name"] == "launch_snapshot")
    assert snapshot_step["effective_status"] == "pass"
    assert snapshot_step["semantic_status"] == "pass"


def test_memorial_showtime_cli_optional_avatar_gate_warns_without_failing(
    memorial_showtime_server: dict[str, object],
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "showtime-optional-avatar"
    env = dict(os.environ)
    env["EA_PUBLIC_MEMORIAL_DIR"] = str(memorial_showtime_server["public_root"])
    env["EA_PRIVATE_MEMORIAL_PROFILE_DIR"] = str(memorial_showtime_server["private_root"])
    env["PYTHONPATH"] = str(APP_ROOT)
    env["TMPDIR"] = str(tmp_path / "tmp-optional-avatar")
    Path(env["TMPDIR"]).mkdir(exist_ok=True)

    result = subprocess.run(
        [
            sys.executable,
            str(APP_ROOT / "scripts" / "memorial_showtime.py"),
            "--slug",
            "manfred",
            "--base-url",
            str(memorial_showtime_server["base_url"]),
            "--questions",
            str(EXAMPLES_ROOT / "demo_questions.manfred.json"),
            "--output-dir",
                str(output_dir),
                "--skip-unit-contracts",
                "--skip-exit-gates",
                "--optional-exit-gates",
                "--avatar-optional",
            ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads((output_dir / "showtime_report.json").read_text(encoding="utf-8"))
    assert payload["status"] == "pass"
    avatar_step = next(item for item in payload["results"] if item["name"] == "avatar_video_call_status")
    assert avatar_step["effective_status"] == "pass"
    assert avatar_step["semantic_status"] == "warn"
    assert "avatar_video_not_published" in avatar_step["stdout_tail"]


def test_memorial_showtime_cli_launch_mode_rejects_skip_flags(tmp_path: Path) -> None:
    output_dir = tmp_path / "showtime-launch-invalid"
    result = subprocess.run(
        [
            sys.executable,
            str(APP_ROOT / "scripts" / "memorial_showtime.py"),
            "--slug",
            "manfred",
            "--base-url",
            "https://example.test",
            "--output-dir",
            str(output_dir),
            "--launch-mode",
            "--avatar-optional",
            "--skip-tts",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "--launch-mode forbids skip flags" in (result.stderr or "")
