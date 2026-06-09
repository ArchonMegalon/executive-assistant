from __future__ import annotations

import json
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
    frame = seed.encode("utf-8", errors="ignore") or b"seed"
    pcm = (frame * 400)[:3200]
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
                "subtitle": "Eine ruhige Seite fuer Gespraeche.",
                "intro": "Eine reduzierte Seite fuer das Gespraech.",
                "disclosure": "Diese Seite bleibt auf dem Gespraech fokussiert.",
                "audio_clips": [{"asset_relpath": "audio/clip.mp3"}],
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
                "tts_plugin": public_memorials.PIPER_FAST_TTS_PLUGIN_ID,
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
                        "id": "doc-public",
                        "title": "Public Doc",
                        "audience": "public",
                        "viewer_type": "smart_document",
                        "url": "https://archive.example/public",
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
    memorial_archive_registry.PUBLIC_MEMORIAL_ROOT = registry_root
    memorial_archive_registry.ARCHIVE_ROOT = tmp_path / "archive"

    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    monkeypatch.setenv("EA_PRIVATE_MEMORIAL_PROFILE_DIR", str(private_root))

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
    monkeypatch.setattr(
        public_memorials,
        "piper_fast_synthesize_request",
        lambda **kwargs: (_generated_wav_bytes(seed=str(kwargs.get("text") or "audio")), "audio/wav"),
    )
    def _fake_transcribe_audio_blob(*, payload: bytes, content_type: str) -> dict[str, object]:
        raw = bytes(payload or b"")
        if b"Hallo Manfred" in raw:
            text = "Hallo Manfred, kannst du direkt mit mir reden?"
        elif b"Ich antworte dir direkt und bleibe bei der Sache." in raw:
            text = "Ich antworte dir direkt und bleibe bei der Sache."
        elif b"Ja. Ich bin da." in raw:
            text = "Ja. Ich bin da."
        else:
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
    env["PYTHONPATH"] = "/docker/EA/ea"
    env["TMPDIR"] = str(tmp_path / "tmp")
    Path(env["TMPDIR"]).mkdir(exist_ok=True)

    result = subprocess.run(
        [
            sys.executable,
            "/docker/EA/ea/scripts/memorial_showtime.py",
            "--slug",
            "manfred",
            "--base-url",
            str(memorial_showtime_server["base_url"]),
            "--questions",
            "/docker/EA/examples/demo_questions.manfred.json",
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


def test_memorial_showtime_cli_optional_avatar_gate_warns_without_failing(
    memorial_showtime_server: dict[str, object],
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "showtime-optional-avatar"
    env = dict(os.environ)
    env["EA_PUBLIC_MEMORIAL_DIR"] = str(memorial_showtime_server["public_root"])
    env["EA_PRIVATE_MEMORIAL_PROFILE_DIR"] = str(memorial_showtime_server["private_root"])
    env["PYTHONPATH"] = "/docker/EA/ea"
    env["TMPDIR"] = str(tmp_path / "tmp-optional-avatar")
    Path(env["TMPDIR"]).mkdir(exist_ok=True)

    result = subprocess.run(
        [
            sys.executable,
            "/docker/EA/ea/scripts/memorial_showtime.py",
            "--slug",
            "manfred",
            "--base-url",
            str(memorial_showtime_server["base_url"]),
            "--questions",
            "/docker/EA/examples/demo_questions.manfred.json",
            "--output-dir",
            str(output_dir),
            "--skip-unit-contracts",
            "--skip-exit-gates",
            "--optional-exit-gates",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads((output_dir / "showtime_report.json").read_text(encoding="utf-8"))
    assert payload["status"] == "warn"
    avatar_step = next(item for item in payload["results"] if item["name"] == "avatar_video_call_status")
    assert avatar_step["effective_status"] == "warn"
    assert avatar_step["semantic_detail"]["warn_codes"] == ["avatar_video_not_published"]
