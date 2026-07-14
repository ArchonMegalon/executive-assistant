from __future__ import annotations

import asyncio
import json
import os
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
from playwright.sync_api import Browser, Page, sync_playwright  # noqa: E402

Config = uvicorn.Config
Server = uvicorn.Server

from app.api.app import create_app  # noqa: E402


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
                "approved": True,
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
    }


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
    monkeypatch.setenv("GOOGLE_API_KEY_FALLBACK_1", "playwright-gemini-live-key")
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
        _source_first_memorial_payload(slug),
    )
    private_audio_path = public_root / slug / PRIVATE_AUDIO_RELPATH
    private_audio_path.parent.mkdir(parents=True, exist_ok=True)
    private_audio_path.write_bytes(b"physically-present-private-audio")
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
    monkeypatch.setenv(
        "EA_PUBLIC_MEMORIAL_CONTRIBUTION_DIR",
        str(artifacts_root / "family_contributions" / "public"),
    )
    monkeypatch.setenv(
        "EA_PRIVATE_MEMORIAL_CONTRIBUTION_DIR",
        str(artifacts_root / "family_contributions" / "private"),
    )
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
            "started_at": time.time() - 2.0,
            "completed_at": time.time() - 1.0,
            "expires_at": time.time() + 599.0,
            "ttl_remaining_seconds": 599.0,
            "errors": [],
            "voice_ready": True,
            "voice_inflight": False,
            "voice_prewarm_stale": False,
            "voice_completed_at": time.time() - 1.0,
            "voice_expires_at": time.time() + 599.0,
            "voice_ttl_remaining_seconds": 599.0,
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

    class _FakeGeminiLiveSocket:
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
                            "inputTranscription": {"text": "Hallo Manfred, kannst du mich hoeren?"},
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

    async def _fake_gemini_connect(uri: str, **kwargs):
        return _FakeGeminiLiveSocket()

    monkeypatch.setattr(
        public_memorials,
        "websockets",
        type("_FakeWebsockets", (), {"connect": _fake_gemini_connect}),
    )
    real_voicewave_plugin_option = public_memorials.voicewave_plugin_option

    def _browser_voicewave_plugin_option(**kwargs):
        option = dict(real_voicewave_plugin_option(**kwargs))
        option.update(
            {
                "tts_plugin_enabled": True,
                "tts_plugin_voice_id": str(kwargs.get("configured_voice_id") or "browser-fixture-voice"),
            }
        )
        return option

    monkeypatch.setattr(public_memorials, "voicewave_plugin_option", _browser_voicewave_plugin_option)
    public_memorials._memorial_runtime_readiness_cache_invalidate(slug)

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


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH") or None,
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
          window.__memorialGetUserMediaCalls = 0;
          navigator.mediaDevices.getUserMedia = async () => {
            window.__memorialGetUserMediaCalls += 1;
            return {
              getTracks() {
                return [{ stop() {} }];
              },
            };
          };

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
              setTimeout(() => this.stop(), 250);
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
          window.__memorialRealtimeFrames = [];
          window.__memorialRealtimeUrls = [];
          const OriginalWebSocket = window.WebSocket;
          if (typeof OriginalWebSocket === "function") {
            window.WebSocket = function(url, protocols) {
              window.__memorialRealtimeUrls.push(String(url || ""));
              const socket = protocols != null ? new OriginalWebSocket(url, protocols) : new OriginalWebSocket(url);
              socket.addEventListener("message", (event) => {
                window.__memorialRealtimeFrames.push(String((event && event.data) || ""));
              });
              return socket;
            };
            window.WebSocket.CONNECTING = OriginalWebSocket.CONNECTING;
            window.WebSocket.OPEN = OriginalWebSocket.OPEN;
            window.WebSocket.CLOSING = OriginalWebSocket.CLOSING;
            window.WebSocket.CLOSED = OriginalWebSocket.CLOSED;
            window.WebSocket.prototype = OriginalWebSocket.prototype;
          }
          HTMLMediaElement.prototype.play = function play() {
            return new Promise((resolve) => {
              setTimeout(() => {
                this.dispatchEvent(new Event("ended"));
                resolve();
              }, 1750);
            });
          };
        })();
        """
    )


def _await_realtime_turn_complete(page: Page, slug: str, action, timeout_ms: int = 7000) -> dict[str, object]:
    state: dict[str, object] = {
        "done": False,
        "turn_id": "",
        "answer": "",
        "audio_seen": False,
        "action_error": "",
    }
    try:
        try:
            action()
        except Exception as exc:
            state["action_error"] = str(exc)
            raise
        deadline = time.perf_counter() + (timeout_ms / 1000.0)
        while time.perf_counter() < deadline:
            raw_frames = page.evaluate("() => Array.isArray(window.__memorialRealtimeFrames) ? window.__memorialRealtimeFrames.slice() : []")
            for payload in raw_frames:
                if payload is None:
                    continue
                try:
                    parsed = json.loads(str(payload))
                except Exception:
                    continue
                if not isinstance(parsed, dict):
                    continue
                turn_id = str(parsed.get("turn_id", "") or "")
                if turn_id and slug and "turn_" not in turn_id and not state.get("turn_id"):
                    continue
                event_type = str(parsed.get("type", "")).strip()
                if event_type == "turn_complete":
                    state["done"] = True
                if event_type == "answer":
                    state["answer"] = str(parsed.get("text") or "").strip()
                if event_type in {"audio", "audio_chunk", "audio_complete"}:
                    state["audio_seen"] = True
                if event_type in {"turn_complete", "error", "cancelled"} and not state.get("turn_id"):
                    state["turn_id"] = turn_id
            if bool(state.get("done")):
                break
            time.sleep(0.05)
        if not bool(state.get("done")):
            raise AssertionError(f"timeout waiting for realtime turn completion for {slug}")
    finally:
        pass
    return state


def _await_conversation_ready(page: Page, *, timeout_ms: int = 12000) -> None:
    try:
        page.wait_for_function(
            "() => !document.getElementById('memorial-conversation').disabled",
            timeout=timeout_ms,
        )
    except Exception as exc:
        diagnostics = page.evaluate(
            """() => {
              const button = document.getElementById("memorial-conversation");
              const phase = document.getElementById("memorial-speech-phase");
              const message = document.getElementById("memorial-speech-message");
              return {
                buttonDisabled: Boolean(button && button.disabled),
                buttonText: String((button && button.textContent) || "").trim(),
                phaseText: String((phase && phase.textContent) || "").trim(),
                messageText: String((message && message.textContent) || "").trim(),
              };
            }"""
        )
        raise AssertionError(f"conversation readiness timeout: {json.dumps(diagnostics, ensure_ascii=False)}") from exc


def test_memorial_public_page_is_source_first_accessible_and_private_by_default(
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
        conversation_button = page.locator("#memorial-conversation")
        assert conversation_button.count() == 1
        initial_label = (conversation_button.text_content() or "").strip()
        assert initial_label in {"Gespräch wird vorbereitet …", "Gespräch beginnen"}
        assert conversation_button.get_attribute("aria-label") == initial_label
        assert conversation_button.get_attribute("title") == initial_label

        assert page.locator("header + main#memorial-story").count() == 1
        assert page.locator("main#memorial-story + aside#memorial-conversation-region").count() == 1
        for viewport in ({"width": 1440, "height": 1100}, {"width": 390, "height": 844}):
            page.set_viewport_size(viewport)
            story_box = page.locator("main#memorial-story").bounding_box()
            conversation_box = page.locator(
                "aside#memorial-conversation-region"
            ).bounding_box()
            assert story_box is not None
            assert conversation_box is not None
            assert page.locator("aside#memorial-conversation-region").evaluate(
                "element => getComputedStyle(element).position"
            ) not in {"fixed", "sticky"}
            assert conversation_box["y"] >= story_box["y"] + story_box["height"] - 1
        page.set_viewport_size({"width": 1440, "height": 1100})
        assert page.locator("main#memorial-story").get_attribute("tabindex") == "-1"
        assert page.locator("aside#memorial-conversation-region").get_attribute("tabindex") == "-1"
        assert page.locator("aside#memorial-conversation-region").get_attribute("aria-label") == (
            "Quellengebundener Gedenkbegleiter für Manfred Hoza"
        )
        assert page.locator("a.skip-link").evaluate_all(
            "links => links.map((link) => link.getAttribute('href'))"
        ) == ["#memorial-story", "#memorial-conversation-region"]
        protected_forms = (
            (
                page.locator("#memorial-contribution-form"),
                f"/memorials/{slug}/contributions",
            ),
            (page.locator("#memorial-text-turn-form"), f"/memorials/{slug}/chat"),
        )
        for protected_form, expected_action in protected_forms:
            assert protected_form.get_attribute("method") == "post"
            assert protected_form.get_attribute("action") == expected_action
            assert protected_form.get_attribute("data-js-ready") == "true"
            assert protected_form.get_attribute("hidden") is None
            assert protected_form.get_attribute("inert") is None
            assert protected_form.get_attribute("aria-hidden") is None
            assert protected_form.get_attribute("aria-disabled") is None
            assert protected_form.is_visible()
        page.locator('a.skip-link[href="#memorial-story"]').focus()
        page.keyboard.press("Enter")
        assert page.evaluate("() => document.activeElement && document.activeElement.id") == "memorial-story"
        main_focus_style = page.locator("main#memorial-story").evaluate(
            "element => ({ style: getComputedStyle(element).outlineStyle, width: getComputedStyle(element).outlineWidth })"
        )
        assert main_focus_style["style"] != "none"
        assert main_focus_style["width"] != "0px"
        page.locator('a.skip-link[href="#memorial-conversation-region"]').focus()
        page.keyboard.press("Enter")
        assert page.evaluate("() => document.activeElement && document.activeElement.id") == "memorial-conversation-region"

        assert page.locator(
            '#memorial-speech-message[role="status"][aria-live="polite"][aria-atomic="true"]'
        ).count() == 1
        assert page.locator("#memorial-speech-note").get_attribute("role") is None
        assert page.locator("#memorial-speech-note").get_attribute("aria-live") is None
        assert page.locator("#memorial-speech-transcript-shell").get_attribute("aria-live") is None
        assert page.locator("#memorial-chat-answer").get_attribute("aria-live") == "polite"
        assert page.locator("#memorial-speech-audio").get_attribute("aria-hidden") == "true"
        assert page.locator("#memorial-speech-audio").get_attribute("controls") is None

        assert page.get_by_role("heading", name="Erinnerungen und belegte Quellen", exact=True).count() == 1
        assert page.get_by_role("heading", name="Behutsam bewahrte Spuren", exact=True).count() == 1
        assert page.get_by_role("heading", name="Öffentliche Quellen", exact=True).count() == 1
        assert page.get_by_role("heading", name="Fragen an den Gedenkbegleiter", exact=True).count() == 1
        assert page.locator("article.memory-card").count() == 6
        assert page.locator(".source-list a").count() == 8
        assert page.locator(".prompt-list li").count() == 4
        assert page.locator("[data-memorial-archive-audio]").count() == 0
        assert page.locator("#memorial-archive-title").count() == 0
        source_hrefs = page.locator(".source-list a").evaluate_all(
            "links => links.map((link) => link.getAttribute('href'))"
        )
        assert all(str(href).startswith("https://") for href in source_hrefs)
        assert page.locator(".source-list a").evaluate_all(
            "links => links.every((link) => !link.hasAttribute('target'))"
        )

        public_payload = page.evaluate(
            """async (currentSlug) => {
              const response = await fetch(`/memorials/${currentSlug}.json`);
              if (!response.ok) throw new Error(`public_payload_${response.status}`);
              return response.json();
            }""",
            slug,
        )
        assert public_payload["audio_clips"] == []
        assert len(public_payload["memory_cards"]) == 6
        assert len(public_payload["external_sources"]) == 8
        assert len(public_payload["suggested_prompts"]) == 4
        public_json = json.dumps(public_payload, ensure_ascii=False)
        page_html = page.content()
        for sentinel in (
            RAW_TRANSCRIPT_SENTINEL,
            PRIVATE_MEMORY_SENTINEL,
            PRIVATE_SOURCE_SENTINEL,
            PRIVATE_FAMILY_SENTINEL,
        ):
            assert sentinel not in public_json
            assert sentinel not in page_html

        private_audio_status = page.evaluate(
            """async (path) => {
              const response = await fetch(path);
              return response.status;
            }""",
            f"/memorials/files/{slug}/{PRIVATE_AUDIO_RELPATH}",
        )
        assert private_audio_status == 404
        assert "Optional: Am Handy/Desktop installieren." in page_html
        assert page.locator("#memorial-video-call").count() == 0
        assert page.locator("#memorial-voice-config-form").count() == 0
        assert page.locator("#memorial-voice-ab-wrap").count() == 0
        assert page.get_by_text("Tippen, sprechen, kurz warten, einfach weiterreden.").count() == 0
        assert page.get_by_text("Manfred Hennig").count() == 0
    finally:
        context.close()


def test_memorial_no_javascript_forms_fail_closed_without_leaking_private_text(
    browser: Browser,
    memorial_browser_server: dict[str, object],
) -> None:
    base_url = str(memorial_browser_server["base_url"])
    slug = str(memorial_browser_server["slug"])
    context = browser.new_context(
        viewport={"width": 390, "height": 844},
        java_script_enabled=False,
    )
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/memorials/{slug}", wait_until="domcontentloaded")
        assert response is not None and response.ok
        assert page.url == f"{base_url}/memorials/{slug}"

        notice = page.get_by_role(
            "region",
            name="Private Eingaben sind geschützt",
            exact=True,
        )
        assert notice.count() == 1
        assert notice.is_visible()
        assert "Formulare für private Erinnerungen und Fragen deaktiviert" in notice.inner_text()
        assert "es wurde nichts gesendet" in notice.inner_text()
        assert "Aktiviere JavaScript" in notice.inner_text()

        protected_forms = (
            (
                page.locator("#memorial-contribution-form"),
                f"/memorials/{slug}/contributions",
            ),
            (page.locator("#memorial-text-turn-form"), f"/memorials/{slug}/chat"),
        )
        for protected_form, expected_action in protected_forms:
            assert protected_form.get_attribute("method") == "post"
            assert protected_form.get_attribute("action") == expected_action
            assert protected_form.get_attribute("data-js-ready") == "false"
            assert protected_form.get_attribute("hidden") == ""
            assert protected_form.get_attribute("inert") == ""
            assert protected_form.get_attribute("aria-hidden") == "true"
            assert protected_form.get_attribute("aria-disabled") == "true"
            assert protected_form.is_hidden()
            assert protected_form.locator("input, textarea, button").evaluate_all(
                """controls => controls.every((control) => {
                  control.focus();
                  return document.activeElement !== control;
                })"""
            )
        protected_management = page.locator("#memorial-contribution-management")
        assert protected_management.get_attribute("data-js-ready") == "false"
        assert protected_management.get_attribute("hidden") == ""
        assert protected_management.get_attribute("inert") == ""
        assert protected_management.get_attribute("aria-hidden") == "true"
        assert protected_management.get_attribute("aria-disabled") == "true"
        assert protected_management.is_hidden()
        assert page.url == f"{base_url}/memorials/{slug}"
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
        _await_conversation_ready(page)

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
        _await_conversation_ready(page)
        _await_realtime_turn_complete(
            page,
            slug,
            lambda: page.evaluate("window.__memorialStartConversation && window.__memorialStartConversation()"),
            timeout_ms=12000,
        )
        active_button = page.locator("#memorial-conversation")
        assert "Gespräch stoppen" in ((active_button.text_content() or "").strip())
        assert active_button.get_attribute("aria-label") == "Gespräch stoppen"
        assert active_button.get_attribute("title") == "Gespräch stoppen"
        assert active_button.get_attribute("aria-pressed") == "true"
        default_memory = page.evaluate(
            """async (currentSlug) => {
              const response = await fetch(`/memorials/${currentSlug}/personal-memory`, {
                headers: {"x-memorial-personal-memory": "0"},
              });
              return response.json();
            }""",
            slug,
        )
        assert default_memory["enabled"] is False
        assert default_memory["item_count"] == 0
        realtime_urls = page.evaluate("() => window.__memorialRealtimeUrls.slice()")
        assert realtime_urls
        assert all("personal_memory=0" in str(url) for url in realtime_urls)
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
        stopped_button = page.locator("#memorial-conversation")
        assert "Gespräch beginnen" in ((stopped_button.text_content() or "").strip())
        assert stopped_button.get_attribute("aria-label") == "Gespräch beginnen"
        assert stopped_button.get_attribute("title") == "Gespräch beginnen"
        assert stopped_button.get_attribute("aria-pressed") == "false"
        phase_text = page.locator("#memorial-speech-phase").text_content() or ""
        assert phase_text in {"Ich bin da.", "Bereit"}
    finally:
        context.close()


def test_memorial_browser_persists_turn_only_after_personal_memory_opt_in(
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
        _await_conversation_ready(page)
        page.locator("details.conversation-settings > summary").click()
        page.locator("#memorial-personal-memory-optin").check()
        _await_realtime_turn_complete(
            page,
            slug,
            lambda: page.locator("#memorial-conversation").click(),
            timeout_ms=12000,
        )
        opted_in_memory = page.evaluate(
            """async (currentSlug) => {
              const response = await fetch(`/memorials/${currentSlug}/personal-memory`, {
                headers: {"x-memorial-personal-memory": "1"},
              });
              return response.json();
            }""",
            slug,
        )
        assert opted_in_memory["enabled"] is True
        assert opted_in_memory["item_count"] == 1
        realtime_urls = page.evaluate("() => window.__memorialRealtimeUrls.slice()")
        assert realtime_urls
        assert all("personal_memory=1" in str(url) for url in realtime_urls)
        page.locator("#memorial-conversation").click()
        page.wait_for_function(
            """() => {
              const button = document.getElementById("memorial-conversation");
              return Boolean(button && button.getAttribute("aria-pressed") === "false");
            }""",
            timeout=7000,
        )
    finally:
        context.close()


def test_memorial_browser_keyboard_text_turn_does_not_request_microphone(
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
        _await_conversation_ready(page)
        text_input = page.locator("#memorial-text-turn-input")
        text_input.fill("Woran soll ich mich heute erinnern?")
        text_input.press("Enter")
        page.wait_for_function(
            """() => {
              const answer = document.getElementById("memorial-chat-answer");
              const input = document.getElementById("memorial-text-turn-input");
              return Boolean(answer && !answer.hidden && answer.textContent.trim() && input && !input.disabled);
            }""",
            timeout=12000,
        )
        assert int(page.evaluate("() => window.__memorialGetUserMediaCalls || 0")) == 0
        assert page.locator("#memorial-conversation").get_attribute("aria-pressed") == "false"
        assert page.locator("#memorial-chat-answer").text_content()
    finally:
        context.close()


def test_memorial_browser_explains_microphone_permission_denial_and_keeps_text_fallback(
    browser: Browser,
    memorial_browser_server: dict[str, object],
) -> None:
    base_url = str(memorial_browser_server["base_url"])
    slug = str(memorial_browser_server["slug"])
    context = browser.new_context(viewport={"width": 430, "height": 932})
    _install_fake_audio_runtime(context)
    context.add_init_script(
        """
        (() => {
          navigator.mediaDevices = navigator.mediaDevices || {};
          navigator.mediaDevices.getUserMedia = async () => {
            window.__memorialGetUserMediaCalls = (window.__memorialGetUserMediaCalls || 0) + 1;
            throw new DOMException("permission denied", "NotAllowedError");
          };
        })();
        """
    )
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/memorials/{slug}", wait_until="domcontentloaded")
        assert response is not None and response.ok
        _await_conversation_ready(page)
        page.locator("#memorial-conversation").click()
        page.wait_for_function(
            """() => {
              const message = document.getElementById("memorial-speech-message");
              return Boolean(message && message.textContent.includes("Mikrofonzugriff ist blockiert"));
            }""",
            timeout=7000,
        )
        assert "Browser-Einstellungen" in (page.locator("#memorial-speech-detail").text_content() or "")
        assert page.locator("#memorial-text-turn-input").is_enabled()
        assert page.locator("#memorial-retry-button").is_visible()
    finally:
        context.close()


def test_memorial_browser_voice_warmup_failure_reaches_retry_and_text_fallback(
    browser: Browser,
    memorial_browser_server: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials

    monkeypatch.setattr(
        public_memorials,
        "_memorial_live_warmup_snapshot",
        lambda warmup_slug: {
            "status": "failed",
            "warm": False,
            "inflight": False,
            "started_at": time.time() - 2.0,
            "completed_at": time.time() - 1.0,
            "expires_at": 0.0,
            "ttl_remaining_seconds": 0.0,
            "errors": ["provider_unavailable"],
            "voice_required": True,
            "voice_ready": False,
            "voice_inflight": False,
            "voice_prewarm_state": "failed",
            "voice_started_at": time.time() - 2.0,
            "voice_completed_at": time.time() - 1.0,
            "voice_expires_at": 0.0,
            "voice_ttl_remaining_seconds": 0.0,
            "voice_errors": ["provider_unavailable"],
            "operator_recheck_after_seconds": 1,
        },
    )
    base_url = str(memorial_browser_server["base_url"])
    slug = str(memorial_browser_server["slug"])
    context = browser.new_context(viewport={"width": 430, "height": 932})
    _install_fake_audio_runtime(context)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/memorials/{slug}", wait_until="domcontentloaded")
        assert response is not None and response.ok
        page.wait_for_function(
            """() => {
              const message = document.getElementById("memorial-speech-message");
              const retry = document.getElementById("memorial-retry-button");
              return Boolean(
                message && message.textContent.includes("Stimme ist gerade nicht verfügbar") &&
                retry && !retry.hidden && retry.textContent.includes("Stimme erneut prüfen")
              );
            }""",
            timeout=7000,
        )
        assert page.locator("#memorial-conversation").is_disabled()
        assert page.locator("#memorial-text-turn-input").is_enabled()
        assert "Frage eintippen" in (page.locator("#memorial-speech-detail").text_content() or "")
    finally:
        context.close()


def test_memorial_browser_family_contributions_have_portable_exact_review_control(
    browser: Browser,
    memorial_browser_server: dict[str, object],
) -> None:
    base_url = str(memorial_browser_server["base_url"])
    slug = str(memorial_browser_server["slug"])
    context = browser.new_context(viewport={"width": 430, "height": 932})
    page: Page = context.new_page()
    private_sentinel = "BROWSER_PRIVATE_FAMILY_MEMORY_MUST_NOT_ESCAPE"
    try:
        response = page.goto(f"{base_url}/memorials/{slug}", wait_until="domcontentloaded")
        assert response is not None and response.ok

        def submit(title: str, body: str) -> None:
            page.locator("#memorial-contribution-title-input").fill(title)
            page.locator("#memorial-contribution-body").fill(body)
            page.locator("#memorial-contribution-name").fill("Familienmitglied")
            page.locator("#memorial-contribution-relationship").fill("Familie")
            page.locator("#memorial-contribution-consent").check()
            page.locator("#memorial-contribution-submit").click()
            page.wait_for_function(
                """() => {
                  const status = document.getElementById("memorial-contribution-status");
                  return Boolean(status && status.textContent.includes("Der Beitrag bleibt privat"));
                }""",
                timeout=7000,
            )

        submit("Ein ruhiger Familienmoment", private_sentinel)
        submit("Noch eine Erinnerung", "SECOND_BROWSER_PRIVATE_MEMORY_MUST_NOT_ESCAPE")
        stored_receipt = page.evaluate(
            """() => {
              const key = Object.keys(localStorage).find((item) => item.startsWith("memorial_contribution_receipt_"));
              return key ? JSON.parse(localStorage.getItem(key)) : null;
            }"""
        )
        assert len(stored_receipt) == 2
        assert all(
            row["schema_version"]
            == "ea.memorial_family_contribution.recovery_receipt.v1"
            for row in stored_receipt
        )
        assert all(row["slug"] == slug for row in stored_receipt)
        assert all(row["status_path"].endswith("/status") for row in stored_receipt)
        assert stored_receipt[0]["contribution_id"]
        assert stored_receipt[0]["manage_token"]
        first_receipt = stored_receipt[0]
        assert first_receipt["manage_token"] not in page.locator("body").inner_text()
        assert page.locator("#memorial-contribution-recovery-panel").is_visible()
        assert page.locator("#memorial-contribution-recovery-download").is_enabled()
        assert page.locator("#memorial-contribution-recovery-copy").is_enabled()
        assert page.locator(".contribution-management-card").count() == 2
        public_payload = page.evaluate(
            """async (currentSlug) => {
              const response = await fetch(`/memorials/${currentSlug}.json`);
              return response.json();
            }""",
            slug,
        )
        assert private_sentinel not in json.dumps(public_payload)

        from app.services.memorial_family_contributions import (
            propose_family_contribution_public_version,
        )

        proposed = propose_family_contribution_public_version(
            slug=slug,
            contribution_id=str(first_receipt["contribution_id"]),
            payload={
                "reviewer": "Browser curator",
                "title": "Exakt geprüfte öffentliche Überschrift",
                "body": "Exakt geprüfter öffentlicher Text.",
                "source_label": "Erinnerung aus der Familie",
            },
        )
        proposal_sha256 = proposed["public_proposal_binding"]["sha256"]
        decision_requests: list[dict[str, object]] = []

        def remember_decision(request) -> None:  # type: ignore[no-untyped-def]
            if "/proposal/" not in request.url or request.method != "POST":
                return
            decision_requests.append(request.post_data_json)

        page.on("request", remember_decision)
        page.locator("#memorial-contribution-management-jump").click()
        first_card = page.locator(".contribution-management-card").filter(
            has_text="Ein ruhiger Familienmoment"
        )
        first_card.get_by_text("Exakt geprüfte öffentliche Überschrift", exact=True).wait_for()
        assert "Exakt geprüfter öffentlicher Text." in first_card.inner_text()
        first_card.get_by_role("button", name="Genau diese Fassung freigeben").click()
        first_card.get_by_text("Von dir zur Veröffentlichung freigegeben", exact=True).wait_for()
        assert decision_requests[-1] == {"proposal_sha256": proposal_sha256}
        first_card = page.locator(".contribution-management-card").filter(
            has_text="Ein ruhiger Familienmoment"
        )
        first_card.get_by_role("button", name="Änderungen wünschen").click()
        first_card.get_by_text("Änderungswunsch gesendet", exact=True).wait_for()
        assert decision_requests[-1] == {"proposal_sha256": proposal_sha256}

        first_card = page.locator(".contribution-management-card").filter(
            has_text="Ein ruhiger Familienmoment"
        )
        first_card.get_by_text("Einreichung korrigieren", exact=True).click()
        corrected_body = "PRIVATE_CORRECTED_BROWSER_MEMORY_MUST_NOT_ESCAPE"
        first_card.locator('textarea[name="body"]').fill(corrected_body)
        first_card.get_by_role("button", name="Korrektur privat speichern").click()
        first_card.get_by_text("Korrektur wird geprüft", exact=True).wait_for()

        first_card = page.locator(".contribution-management-card").filter(
            has_text="Ein ruhiger Familienmoment"
        )
        page.once("dialog", lambda dialog: dialog.accept())
        first_card.get_by_role("button", name="Einreichung zurückziehen").click()
        first_card.get_by_text("Zurückgezogen · nicht öffentlich", exact=True).wait_for()
        retained_receipts = page.evaluate(
            """() => {
              const key = Object.keys(localStorage).find((item) => item.startsWith("memorial_contribution_receipt_"));
              return key ? JSON.parse(localStorage.getItem(key)) : [];
            }"""
        )
        assert len(retained_receipts) == 2
        assert any(
            item["contribution_id"] == first_receipt["contribution_id"]
            for item in retained_receipts
        )
        assert first_receipt["manage_token"] not in page.locator("body").inner_text()

        first_card = page.locator(".contribution-management-card").filter(
            has_text="Ein ruhiger Familienmoment"
        )
        page.once("dialog", lambda dialog: dialog.accept())
        first_card.get_by_role(
            "button", name="Beleg nur von diesem Gerät entfernen"
        ).click()
        page.wait_for_function(
            """() => {
              const key = Object.keys(localStorage).find((item) => item.startsWith("memorial_contribution_receipt_"));
              const receipts = key ? JSON.parse(localStorage.getItem(key)) : [];
              return Array.isArray(receipts) && receipts.length === 1;
            }""",
            timeout=7000,
        )
    finally:
        context.close()


def test_memorial_browser_recovery_import_and_storage_failure_keep_token_portable(
    browser: Browser,
    memorial_browser_server: dict[str, object],
) -> None:
    base_url = str(memorial_browser_server["base_url"])
    slug = str(memorial_browser_server["slug"])
    context = browser.new_context(viewport={"width": 430, "height": 932})

    def submit_direct(title: str) -> dict[str, object]:
        response = context.request.post(
            f"{base_url}/memorials/{slug}/contributions",
            data={
                "title": title,
                "body": f"Private recovery body for {title}",
                "publication_consent": True,
            },
        )
        assert response.ok
        return dict(response.json())

    def portable_receipt(submission: dict[str, object]) -> dict[str, object]:
        receipt = dict(submission["recovery_receipt"])
        receipt.update(
            {
                "slug": slug,
                "contribution_id": submission["contribution_id"],
                "manage_token": submission["manage_token"],
            }
        )
        return receipt

    first = submit_direct("Importierter Beleg eins")
    second = submit_direct("Importierter Altbeleg")
    third = submit_direct("Importierte JSON-Datei")
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/memorials/{slug}", wait_until="domcontentloaded")
        assert response is not None and response.ok
        page.locator("#memorial-contribution-recovery-import > summary").click()
        code_input = page.locator("#memorial-contribution-recovery-code")
        import_button = page.locator("#memorial-contribution-recovery-import-button")
        invalid = portable_receipt(first)
        invalid["slug"] = "another-memorial"
        code_input.fill(json.dumps(invalid))
        import_button.click()
        page.get_by_text(
            "Dieser Beleg ist ungültig oder gehört nicht zu dieser Gedenkseite. Es wurde nichts gespeichert.",
            exact=True,
        ).wait_for()
        assert page.evaluate(
            """() => !Object.keys(localStorage).some((key) => key.startsWith("memorial_contribution_receipt_"))"""
        )

        first_portable = portable_receipt(first)
        code_input.fill(json.dumps(first_portable))
        import_button.click()
        page.get_by_text(
            "Der Rücknahmebeleg wurde geprüft und auf diesem Gerät hinzugefügt.",
            exact=True,
        ).wait_for()
        page.get_by_role("heading", name="Importierter Beleg eins", exact=True).wait_for()

        legacy = {
            "contribution_id": second["contribution_id"],
            "manage_token": second["manage_token"],
        }
        code_input.fill(json.dumps(legacy))
        import_button.click()
        page.wait_for_function(
            """() => {
              const key = Object.keys(localStorage).find((item) => item.startsWith("memorial_contribution_receipt_"));
              const receipts = key ? JSON.parse(localStorage.getItem(key)) : [];
              return Array.isArray(receipts)
                && receipts.length === 2
                && receipts.every((receipt) => receipt.schema_version === "ea.memorial_family_contribution.recovery_receipt.v1");
            }""",
            timeout=7000,
        )

        third_portable = portable_receipt(third)
        page.locator("#memorial-contribution-recovery-file").set_input_files(
            {
                "name": "manfred-ruecknahmebeleg.json",
                "mimeType": "application/json",
                "buffer": json.dumps(third_portable).encode("utf-8"),
            }
        )
        import_button.click()
        page.wait_for_function(
            """() => {
              const key = Object.keys(localStorage).find((item) => item.startsWith("memorial_contribution_receipt_"));
              const receipts = key ? JSON.parse(localStorage.getItem(key)) : [];
              return Array.isArray(receipts) && receipts.length === 3;
            }""",
            timeout=7000,
        )
        for submission in (first, second, third):
            assert str(submission["manage_token"]) not in page.locator("body").inner_text()
    finally:
        context.close()

    volatile_context = browser.new_context(
        viewport={"width": 430, "height": 932},
        accept_downloads=True,
    )
    volatile_context.add_init_script(
        """
        (() => {
          const originalGet = Storage.prototype.getItem;
          const originalSet = Storage.prototype.setItem;
          const originalRemove = Storage.prototype.removeItem;
          const guarded = (key) => String(key || "").startsWith("memorial_contribution_receipt_");
          Storage.prototype.getItem = function(key) {
            if (guarded(key)) throw new DOMException("storage blocked", "SecurityError");
            return originalGet.call(this, key);
          };
          Storage.prototype.setItem = function(key, value) {
            if (guarded(key)) throw new DOMException("storage blocked", "SecurityError");
            return originalSet.call(this, key, value);
          };
          Storage.prototype.removeItem = function(key) {
            if (guarded(key)) throw new DOMException("storage blocked", "SecurityError");
            return originalRemove.call(this, key);
          };
          Object.defineProperty(navigator, "clipboard", {
            configurable: true,
            value: {
              writeText: async (value) => { window.__memorialCopiedRecoveryReceipt = String(value || ""); },
            },
          });
        })();
        """
    )
    volatile_page: Page = volatile_context.new_page()
    captured_submission: dict[str, object] = {}

    def capture_submission(response) -> None:  # type: ignore[no-untyped-def]
        if response.request.method != "POST" or not response.url.endswith(
            f"/memorials/{slug}/contributions"
        ):
            return
        if response.ok:
            captured_submission.update(response.json())

    volatile_page.on("response", capture_submission)
    try:
        response = volatile_page.goto(
            f"{base_url}/memorials/{slug}", wait_until="domcontentloaded"
        )
        assert response is not None and response.ok
        volatile_page.locator("#memorial-contribution-title-input").fill(
            "Beleg ohne Browserspeicher"
        )
        volatile_page.locator("#memorial-contribution-body").fill(
            "PRIVATE_VOLATILE_RECOVERY_BODY"
        )
        volatile_page.locator("#memorial-contribution-submit").click()
        volatile_page.get_by_text(
            "Der Beitrag wurde privat gespeichert. Sichere den Rücknahmebeleg jetzt, weil dieser Browser ihn nicht dauerhaft speichern konnte.",
            exact=True,
        ).wait_for()
        assert captured_submission["manage_token"]
        token = str(captured_submission["manage_token"])
        assert token not in volatile_page.locator("body").inner_text()
        assert volatile_page.locator("#memorial-contribution-recovery-panel").is_visible()

        with volatile_page.expect_download() as download_info:
            volatile_page.locator("#memorial-contribution-recovery-download").click()
        download = download_info.value
        assert download.suggested_filename.startswith(f"{slug}-ruecknahmebeleg-")
        downloaded_receipt = json.loads(Path(download.path()).read_text(encoding="utf-8"))
        assert downloaded_receipt["manage_token"] == token
        assert downloaded_receipt["slug"] == slug

        volatile_page.locator("#memorial-contribution-recovery-copy").click()
        volatile_page.wait_for_function(
            "() => Boolean(window.__memorialCopiedRecoveryReceipt)", timeout=7000
        )
        copied_receipt = json.loads(
            volatile_page.evaluate("() => window.__memorialCopiedRecoveryReceipt")
        )
        assert copied_receipt["manage_token"] == token
        assert volatile_page.evaluate(
            """() => {
              try {
                localStorage.getItem("memorial_contribution_receipt_manfred_v1");
                return false;
              } catch (error) {
                return true;
              }
            }"""
        )
    finally:
        volatile_context.close()


def test_memorial_browser_reduced_motion_avoids_smooth_answer_scroll(
    browser: Browser,
    memorial_browser_server: dict[str, object],
) -> None:
    base_url = str(memorial_browser_server["base_url"])
    slug = str(memorial_browser_server["slug"])
    context = browser.new_context(
        viewport={"width": 430, "height": 932},
        reduced_motion="reduce",
    )
    context.add_init_script(
        """
        (() => {
          window.__memorialScrollOptions = [];
          Element.prototype.scrollIntoView = function(options) {
            window.__memorialScrollOptions.push(options || {});
          };
        })();
        """
    )
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/memorials/{slug}", wait_until="domcontentloaded")
        assert response is not None and response.ok
        page.evaluate(
            """() => {
              const answer = document.getElementById("memorial-chat-answer");
              const tools = document.getElementById("memorial-chat-tools");
              const read = document.getElementById("memorial-read-answer");
              answer.hidden = false;
              answer.textContent = "Eine sichtbare Antwort.";
              tools.hidden = false;
              read.hidden = false;
            }"""
        )
        page.locator("#memorial-read-answer").click()
        options = page.evaluate("() => window.__memorialScrollOptions.slice()")
        assert options
        assert options[-1]["behavior"] == "auto"
    finally:
        context.close()


def test_memorial_browser_can_defer_all_provider_warmup_until_user_action(
    browser: Browser,
    memorial_browser_server: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EA_MEMORIAL_PAGE_PREWARM_ENABLED", "0")
    context = browser.new_context(
        viewport={"width": 390, "height": 844},
        reduced_motion="reduce",
    )
    page = context.new_page()
    requested_urls: list[str] = []
    page.on("request", lambda request: requested_urls.append(request.url))
    try:
        response = page.goto(
            f"{memorial_browser_server['base_url']}/memorials/{memorial_browser_server['slug']}",
            wait_until="domcontentloaded",
        )
        assert response is not None and response.status == 200
        page.wait_for_timeout(700)

        provider_work_paths = (
            "/warmup",
            "/warmup-status",
            "/speech-synthesize",
        )
        assert not [
            url
            for url in requested_urls
            if any(path in url for path in provider_work_paths)
        ]
        conversation = page.locator("#memorial-conversation")
        assert conversation.is_enabled()
        assert conversation.inner_text().strip() == "Gespräch beginnen"
        assert page.locator("#memorial-speech-message").inner_text().strip() == "Bereit."
    finally:
        context.close()
