from __future__ import annotations

import json
import socket
import threading
import time
import urllib.request
import wave
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path

import pytest

uvicorn = pytest.importorskip("uvicorn")
pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Browser, Page, sync_playwright

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


def _write_public_memorial(root: Path, slug: str, payload: dict[str, object]) -> None:
    bundle_dir = root / slug
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "memorial.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_private_voice(root: Path, slug: str, payload: dict[str, object]) -> None:
    profile_dir = root / slug
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "tts_voice.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _wav_bytes() -> bytes:
    sample_rate = 16_000
    total_frames = int(sample_rate * 0.22)
    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * total_frames)
    return buffer.getvalue()


@pytest.fixture()
def memorial_browser_server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[dict[str, object]]:
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
    registry_root = tmp_path / "public_registry"

    _write_public_memorial(
        public_root,
        slug,
        {
            "slug": slug,
            "person_name": "Manfred Hoza",
            "title": "Erinnerungen an Manfred",
            "subtitle": "Eine ruhige Seite fuer Erinnerungen und Originalstimme.",
            "audio_clips": [],
        },
    )
    _write_private_voice(
        private_root,
        slug,
        {
            "tts_plugin": "voicewave_clone",
            "tts_plugin_voice_id": "Manfred Hoza Memorial",
            "voice_label": "Manfred Hoza · VoiceWave-Klon",
            "voice_consent": {
                "status": "approved",
                "scope": ["synthesize", "conversation_turn", "realtime"],
                "authorized_by": "test-family",
                "authorized_at": "2026-06-08T16:00:00Z",
                "source_assets_reviewed": True,
                "revoked": False,
            },
        },
    )
    (registry_root / slug).mkdir(parents=True, exist_ok=True)
    (registry_root / slug / "archive_registry.json").write_text(
        json.dumps({"slug": slug, "archive_sections": [], "fliplink_publications": []}, ensure_ascii=False),
        encoding="utf-8",
    )

    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    monkeypatch.setenv("EA_PRIVATE_MEMORIAL_PROFILE_DIR", str(private_root))
    public_memorials._PERSONAL_MEMORY_ROOT = artifacts_root / "memorial_user_memory"
    public_memorials._VOICE_AB_ROOT = artifacts_root / "memorial_voice_ab"
    public_memorials._PUBLIC_MEMORIAL_RATE_DB = artifacts_root / "memorial_rate_limits.sqlite3"
    memorial_archive_registry.PUBLIC_MEMORIAL_ROOT = registry_root
    memorial_archive_registry.ARCHIVE_ROOT = tmp_path / "archive"

    monkeypatch.setattr(
        public_memorials,
        "_schedule_memorial_live_warmup",
        lambda warmup_slug: {"status": "queued", "scheduled": True, "ttl_seconds": 600},
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_live_warmup_snapshot",
        lambda warmup_slug: {
            "status": "warm_recent",
            "warm": True,
            "inflight": False,
            "started_at": 10.0,
            "completed_at": 12.0,
            "errors": [],
            "voice_ready": True,
            "voice_inflight": False,
            "voice_completed_at": 12.0,
            "voice_errors": [],
            "voice_required": True,
        },
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_transcribe_audio_blob",
        lambda **kwargs: {
            "transcription_status": "transcribed",
            "transcript_text": "Hallo Manfred, kannst du jetzt mit mir sprechen?",
            "transcriber": "playwright_stub",
        },
    )
    monkeypatch.setattr(
        public_memorials,
        "_render_memorial_tts_audio",
        lambda **kwargs: (_wav_bytes(), "audio/wav"),
    )

    app = create_app()
    port = _free_port()
    config = Config(app=app, host="127.0.0.1", port=port, log_level="warning")
    server = Server(config)
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    _wait_for_http(base_url)
    try:
        yield {"base_url": base_url, "slug": slug}
    finally:
        server.should_exit = True
        thread.join(timeout=10.0)


@pytest.fixture()
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--no-proxy-server",
            ],
        )
        try:
            yield browser
        finally:
            browser.close()


def _install_fake_audio_runtime(context) -> None:
    context.add_init_script(
        """
        (() => {
          navigator.mediaDevices = navigator.mediaDevices || {};
          navigator.mediaDevices.getUserMedia = async () => ({
            getTracks() {
              return [{ stop() {} }];
            },
          });

          class FakeMediaRecorder {
            constructor(stream, options) {
              this.stream = stream;
              this.mimeType = (options && options.mimeType) || "audio/webm";
              this.state = "inactive";
              this.ondataavailable = null;
              this.onerror = null;
              this.onstop = null;
            }
            start() {
              this.state = "recording";
              setTimeout(() => this.stop(), 40);
            }
            stop() {
              if (this.state === "inactive") return;
              if (this.ondataavailable) {
                const payload = new Uint8Array(512);
                payload.fill(7);
                this.ondataavailable({
                  data: new Blob([payload], { type: this.mimeType }),
                });
              }
              this.state = "inactive";
              if (this.onstop) this.onstop();
            }
            static isTypeSupported() {
              return true;
            }
          }

          window.MediaRecorder = FakeMediaRecorder;
          HTMLMediaElement.prototype.play = function play() {
            return new Promise((resolve) => {
              setTimeout(() => {
                this.dispatchEvent(new Event("ended"));
                resolve();
              }, 40);
            });
          };
        })();
        """
    )


def test_memorial_public_page_ships_only_the_minimal_safe_surface(
    browser: Browser,
    memorial_browser_server: dict[str, object],
) -> None:
    base_url = str(memorial_browser_server["base_url"])
    slug = str(memorial_browser_server["slug"])
    context = browser.new_context(viewport={"width": 1440, "height": 1100})
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/memorials/{slug}", wait_until="domcontentloaded")
        assert response is not None and response.ok
        page.wait_for_function(
            "() => !document.getElementById('memorial-conversation').disabled",
            timeout=5000,
        )
        assert page.locator("#memorial-conversation").count() == 1
        button_text = (page.locator("#memorial-conversation").text_content() or "").strip()
        assert button_text in {"Gespräch beginnen", "Gespräch stoppen"}
        assert page.locator("#memorial-video-call").count() == 0
        assert page.locator("#memorial-voice-config-form").count() == 0
        assert page.locator("#memorial-voice-ab-wrap").count() == 0
        assert page.get_by_text("Tippen, sprechen, kurz warten, einfach weiterreden.").count() == 0
        assert page.get_by_text("Manfred Hennig").count() == 0
    finally:
        context.close()


def test_memorial_page_exposes_single_active_voice_config_without_service_worker_registration(
    browser: Browser,
    memorial_browser_server: dict[str, object],
) -> None:
    base_url = str(memorial_browser_server["base_url"])
    slug = str(memorial_browser_server["slug"])
    context = browser.new_context(viewport={"width": 1280, "height": 960})
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/memorials/{slug}", wait_until="domcontentloaded")
        assert response is not None and response.ok
        page.wait_for_function(
            "() => !document.getElementById('memorial-conversation').disabled",
            timeout=5000,
        )

        manifest_href = page.get_attribute("link[rel='manifest']", "href")
        assert manifest_href is not None
        manifest = page.evaluate(
            """async (href) => {
              const response = await fetch(href);
              return response.json();
            }""",
            manifest_href,
        )
        assert manifest["display"] == "standalone"
        assert manifest["start_url"] == f"/memorials/{slug}?source=pwa"
        assert str(manifest["scope"]) == f"/memorials/{slug}"

        page.wait_for_timeout(1200)
        has_registration = page.evaluate(
            """async (currentSlug) => {
              if (!("serviceWorker" in navigator)) return false;
              const registrations = await navigator.serviceWorker.getRegistrations();
              return registrations.some((registration) => String(registration.scope || "").includes(`/memorials/${currentSlug}`));
            }""",
            slug,
        )
        assert has_registration is False

        voice_config = page.evaluate(
            """async (currentSlug) => {
              const response = await fetch(`/memorials/${currentSlug}/voice-config`);
              return response.json();
            }""",
            slug,
        )
        assert voice_config["slug"] == slug
        assert voice_config["tts_plugin"] == "voicewave_clone"
        assert voice_config["voice_label"] == "Manfred Hoza · VoiceWave-Klon"
        if "available_options" in voice_config:
            assert len(voice_config["available_options"]) == 1
            assert voice_config["available_options"][0]["tts_plugin"] == "voicewave_clone"
            assert voice_config["available_options"][0]["voice_label"] == "Manfred Hoza · VoiceWave-Klon"
        assert "tts_plugin_voice_id" not in voice_config
        assert "provider_secret" not in voice_config
    finally:
        context.close()


def test_memorial_public_page_finishes_one_browser_turn_without_followup_overlap(
    browser: Browser,
    memorial_browser_server: dict[str, object],
) -> None:
    base_url = str(memorial_browser_server["base_url"])
    slug = str(memorial_browser_server["slug"])
    context = browser.new_context(viewport={"width": 430, "height": 932})
    _install_fake_audio_runtime(context)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/memorials/{slug}", wait_until="domcontentloaded")
        assert response is not None and response.ok
        page.wait_for_function(
            "() => !document.getElementById('memorial-conversation').disabled",
            timeout=5000,
        )
        with page.expect_response(
            lambda response: response.url.endswith(f"/memorials/{slug}/conversation-turn") and response.status == 200,
            timeout=7000,
        ):
            page.evaluate("window.__memorialStartConversation && window.__memorialStartConversation()")
        page.wait_for_function(
            """() => {
              const audio = document.getElementById("memorial-speech-audio");
              return Boolean(audio && audio.getAttribute("src") && audio.getAttribute("src").startsWith("blob:"));
            }""",
            timeout=7000,
        )
        page.evaluate("window.__memorialStartConversation && window.__memorialStartConversation()")
        page.wait_for_function(
            """() => {
              const button = document.getElementById("memorial-conversation");
              return Boolean(
                button &&
                button.getAttribute("aria-pressed") === "false" &&
                button.textContent &&
                button.textContent.includes("Gespräch beginnen")
              );
            }""",
            timeout=7000,
        )
        assert page.locator("#memorial-retry-button").is_hidden()
        assert "Gespräch beginnen" in ((page.locator("#memorial-conversation").text_content() or "").strip())
        phase_text = page.locator("#memorial-speech-phase").text_content() or ""
        assert phase_text in {"Ich bin da.", "Bereit"}
    finally:
        context.close()
