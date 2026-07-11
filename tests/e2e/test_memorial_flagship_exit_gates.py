from __future__ import annotations

import json
import math
import os
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

uvicorn = pytest.importorskip("uvicorn")
Config = uvicorn.Config
Server = uvicorn.Server

from app.api.app import create_app


ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = ROOT / "ea"


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
        struct.pack("<h", int(max(-1.0, min(1.0, value)) * 32767))
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


RAW_TRANSCRIPT_SENTINEL = "RAW_TRANSCRIPT_MUST_NOT_ESCAPE"
PRIVATE_MEMORY_SENTINEL = "PRIVATE_MEMORY_MUST_NOT_ESCAPE"
PRIVATE_SOURCE_SENTINEL = "PRIVATE_SOURCE_MUST_NOT_ESCAPE"
PRIVATE_FAMILY_SENTINEL = "PRIVATE_FAMILY_NOTE_MUST_NOT_ESCAPE"
PRIVATE_AUDIO_RELPATH = "audio/private-family-recording.mp3"


def _source_first_memorial_payload(slug: str) -> dict[str, object]:
    return {
        "slug": slug,
        "person_name": "Manfred Hoza",
        "title": "Erinnerungen an Manfred",
        "subtitle": "Eine ruhige Seite für Erinnerungen, belegte Gedanken und öffentliche Quellen.",
        "intro": "Hier stehen freigegebene Erinnerungen und nachvollziehbare öffentliche Quellen im Mittelpunkt.",
        "disclosure": "Das Gespräch ist eine synthetische Annäherung und keine Originalaufnahme.",
        "transcript": RAW_TRANSCRIPT_SENTINEL,
        "family_notes": [{"note": PRIVATE_FAMILY_SENTINEL}],
        "public_source_notes": [{"note": PRIVATE_FAMILY_SENTINEL}],
        "audio_clips": [
            {
                "visibility": "private",
                "public": False,
                "title": "Private Familienaufnahme",
                "asset_relpath": PRIVATE_AUDIO_RELPATH,
                "transcript": RAW_TRANSCRIPT_SENTINEL,
                "public_transcript": RAW_TRANSCRIPT_SENTINEL,
            }
        ],
        "memory_cards": [
            {
                "visibility": "public",
                "public": True,
                "title": f"Freigegebene Erinnerung {index}",
                "body": f"Behutsam gekürzte Erinnerung Nummer {index}.",
                "source_label": "Familienfreigabe",
            }
            for index in range(1, 7)
        ]
        + [
            {
                "visibility": "private",
                "public": False,
                "title": PRIVATE_MEMORY_SENTINEL,
                "body": PRIVATE_MEMORY_SENTINEL,
            }
        ],
        "external_sources": [
            {
                "visibility": "public",
                "public": True,
                "label": f"Öffentliche Quelle {index}",
                "url": f"https://sources.example/manfred/{index}",
                "status": "belegt",
            }
            for index in range(1, 9)
        ]
        + [
            {
                "visibility": "private",
                "public": False,
                "label": PRIVATE_SOURCE_SENTINEL,
                "url": "https://private.example/manfred",
            }
        ],
        "suggested_prompts": [
            "Was war dir im Leben wichtig?",
            "Woran sollen wir uns erinnern?",
            "Wie bist du mit schwierigen Entscheidungen umgegangen?",
            "Welche Haltung möchtest du weitergeben?",
        ],
        "pwa_app_name": "Manfred Gedenkseite",
        "pwa_short_name": "Manfred",
        "pwa_icon": {
            "src_180": "icons/manfred-180.png",
            "src_192": "icons/manfred-192.png",
            "src_512": "icons/manfred-512.png",
        },
    }


@pytest.fixture()
def memorial_flagship_server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[dict[str, object]]:
    from app.api.routes import public_memorials
    from app.services import memorial_archive_registry
    from types import SimpleNamespace

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
    (bundle / PRIVATE_AUDIO_RELPATH).write_bytes(b"physically-present-private-audio")
    (bundle / "icons").mkdir()
    for size in (180, 192, 512):
        (bundle / "icons" / f"manfred-{size}.png").write_bytes(b"\x89PNG\r\n\x1a\nicon")
    (bundle / "memorial.json").write_text(
        json.dumps(_source_first_memorial_payload(slug), ensure_ascii=False),
        encoding="utf-8",
    )
    (private_root / slug).mkdir(parents=True, exist_ok=True)
    (private_root / slug / "tts_voice.json").write_text(
        json.dumps(
            {
                "tts_plugin": public_memorials.UNMIXR_TTS_PLUGIN_ID,
                "tts_plugin_voice_id": "fixture-unmixr-voice",
                "voice_label": "Tibor freigegebene synthetische Stimme",
                "lang": "de-AT",
                "rate": 0.88,
                "pitch": 0.86,
                "volume": 1.0,
                "voice_name_hints": ["Tibor", "de-AT"],
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
                    },
                    {
                        "id": "doc-family",
                        "title": "Family Doc",
                        "audience": "family",
                        "viewer_type": "smart_document",
                        "url": "https://archive.example/family",
                        "review_status": "published",
                    },
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

    def _fake_unmixr_synthesize_request(**kwargs):
        text = str(kwargs.get("text") or "audio")
        payload = _generated_wav_bytes(seed=text)
        transcript_lookup[payload] = text
        return payload, "audio/wav"

    def _fake_transcribe_audio_blob(*, payload: bytes, content_type: str) -> dict[str, object]:
        text = transcript_lookup.get(bytes(payload or b""), "")
        if not text:
            text = "Ich antworte dir direkt und bleibe bei der Sache."
        return {
            "transcription_status": "transcribed",
            "transcript_text": text,
            "transcriber": "fixture_stub",
        }

    monkeypatch.setattr(public_memorials, "unmixr_synthesize_request", _fake_unmixr_synthesize_request)
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


def test_memorial_flagship_preflight_cli_passes_against_runtime(memorial_flagship_server: dict[str, object], tmp_path: Path) -> None:
    base_url = str(memorial_flagship_server["base_url"])
    env = dict(os.environ)
    env["EA_PUBLIC_MEMORIAL_DIR"] = str(memorial_flagship_server["public_root"])
    env["EA_PRIVATE_MEMORIAL_PROFILE_DIR"] = str(memorial_flagship_server["private_root"])
    env["PYTHONPATH"] = str(APP_ROOT)
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    env["TMPDIR"] = str(tmpdir)

    result = subprocess.run(
        [
            sys.executable,
            str(APP_ROOT / "scripts" / "memorial_flagship_preflight.py"),
            "manfred",
            "--base-url",
            base_url,
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "pass"
    codes = {item["code"] for item in payload["findings"]}
    assert "live_public_page_source_first" in codes
    assert "live_public_tts_rejects_override" in codes
    assert "archive_registry_public_only" in codes


def test_memorial_flagship_http_surface_is_source_first_and_private_by_default(
    memorial_flagship_server: dict[str, object],
) -> None:
    base_url = str(memorial_flagship_server["base_url"])
    with urllib.request.urlopen(f"{base_url}/memorials/manfred", timeout=5.0) as response:
        body = response.read().decode("utf-8", errors="replace")
    with urllib.request.urlopen(f"{base_url}/memorials/manfred.json", timeout=5.0) as response:
        public_payload = json.loads(response.read().decode("utf-8", errors="replace"))

    assert "Gespräch beginnen" in body
    assert "Optional: Am Handy/Desktop installieren." in body
    assert "Erinnerungen und belegte Quellen" in body
    assert "Behutsam bewahrte Spuren" in body
    assert "Öffentliche Quellen" in body
    assert "Fragen als ruhiger Einstieg" in body
    assert body.count('class="story-card memory-card"') == 6
    assert body.count('https://sources.example/manfred/') == 8
    assert body.count('<li>') >= 12
    assert "Tippen, sprechen, kurz warten, einfach weiterreden." not in body
    assert "Stimmvergleich und Feedback" not in body
    assert public_payload["audio_clips"] == []
    assert len(public_payload["memory_cards"]) == 6
    assert len(public_payload["external_sources"]) == 8
    assert len(public_payload["suggested_prompts"]) == 4
    public_json = json.dumps(public_payload, ensure_ascii=False)
    for sentinel in (
        RAW_TRANSCRIPT_SENTINEL,
        PRIVATE_MEMORY_SENTINEL,
        PRIVATE_SOURCE_SENTINEL,
        PRIVATE_FAMILY_SENTINEL,
    ):
        assert sentinel not in body
        assert sentinel not in public_json

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(
            f"{base_url}/memorials/files/manfred/{PRIVATE_AUDIO_RELPATH}",
            timeout=5.0,
        )
    assert exc_info.value.code == 404


def test_memorial_flagship_live_browser_measurement_passes(
    memorial_flagship_server: dict[str, object],
    tmp_path: Path,
) -> None:
    output = tmp_path / "memorial-live-turn-gate.json"
    python_bin = ROOT / ".venv" / "bin" / "python"
    if not python_bin.is_file():
        python_bin = Path(sys.executable)
    result = subprocess.run(
        [
            str(python_bin),
            str(ROOT / "scripts" / "measure_memorial_live_browser.py"),
            "--base-url",
            str(memorial_flagship_server["base_url"]),
            "--slug",
            "manfred",
            "--output",
            str(output),
            "--exit-gate",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=dict(os.environ),
    )

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "pass"
    assert payload["failed_codes"] == []


def test_memorial_browser_measurement_retries_only_pre_page_target_closed(monkeypatch) -> None:
    from scripts import measure_memorial_live_browser

    class _Chromium:
        def __init__(self) -> None:
            self.attempts = 0

        def launch(self, **kwargs):
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("TargetClosedError: Target page, context or browser has been closed")
            return {"browser": "ready", "kwargs": kwargs}

    chromium = _Chromium()
    playwright = type("_Playwright", (), {"chromium": chromium})()
    monkeypatch.setattr(measure_memorial_live_browser.time, "sleep", lambda _seconds: None)

    browser, attempts, errors = measure_memorial_live_browser._launch_chromium_with_startup_retry(
        playwright,
        headless=True,
    )

    assert attempts == 2
    assert chromium.attempts == 2
    assert browser["browser"] == "ready"
    assert len(errors) == 1
    assert "TargetClosedError" in errors[0]


def test_memorial_flagship_exit_gate_script_accepts_optional_avatar_warn(
    memorial_flagship_server: dict[str, object],
    tmp_path: Path,
) -> None:
    if os.getenv("MEMORIAL_FLAGSHIP_EXIT_GATES_RUNNING", "").strip():
        pytest.skip("Avoid recursive memorial_flagship_exit_gates.sh self-invocation while the script is the active top-level gate.")
    env = dict(os.environ)
    env["EA_PUBLIC_MEMORIAL_DIR"] = str(memorial_flagship_server["public_root"])
    env["EA_PRIVATE_MEMORIAL_PROFILE_DIR"] = str(memorial_flagship_server["private_root"])
    env["PYTHONPATH"] = str(APP_ROOT)
    env["MEMORIAL_FLAGSHIP_BASE_URL"] = str(memorial_flagship_server["base_url"])
    tmpdir = tmp_path / "tmp-exit-gate"
    tmpdir.mkdir()
    env["TMPDIR"] = str(tmpdir)

    result = subprocess.run(
        [str(ROOT / "scripts" / "memorial_flagship_exit_gates.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    room_ready = json.loads((tmpdir / "manfred_room_ready_exit_gate" / "room_ready_report.json").read_text(encoding="utf-8"))
    showtime = json.loads((tmpdir / "manfred_room_ready_exit_gate" / "showtime_report.json").read_text(encoding="utf-8"))
    avatar_step = next(item for item in room_ready["results"] if item["name"] == "avatar_video_call_status")
    voice_step = next(item for item in showtime["results"] if item["name"] == "voice_roundtrip_validation")
    assert avatar_step["effective_status"] == "pass"
    assert avatar_step["semantic_status"] == "warn"
    assert voice_step["effective_status"] == "pass"
