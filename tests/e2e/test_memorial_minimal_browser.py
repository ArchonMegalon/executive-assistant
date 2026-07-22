from __future__ import annotations

import json
import base64
import asyncio
import difflib
import importlib.util
import socket
import struct
import threading
import time
import urllib.request
import wave
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

import pytest

uvicorn = pytest.importorskip("uvicorn")
pytest.importorskip("playwright.sync_api")
_HAS_WEBSOCKET_PROTOCOL = importlib.util.find_spec("websockets") is not None or importlib.util.find_spec("wsproto") is not None
from playwright.sync_api import Browser, Page, sync_playwright  # noqa: E402

Config = uvicorn.Config
Server = uvicorn.Server

from app.api.app import create_app  # noqa: E402
from tests.browser_test_support import launch_installed_chromium  # noqa: E402


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
                "title": (
                    "Jimdo-Seite, Familienchronik und die lange Spur durch mehrere Lebensabschnitte"
                    if index == 3
                    else f"Freigegebene Erinnerung {index}"
                ),
                "body": (
                    "Eine ausführliche freigegebene Erinnerung mit genügend ruhigem Kontext, "
                    "um die längste reale Kartenform auf einem schmalen Mobilgerät abzubilden. "
                    "Sie beschreibt mehrere Stationen, Menschen und belegte Zusammenhänge, ohne "
                    "private Angaben zu ergänzen. Der vollständige Text bleibt in der Liste lesbar, "
                    "während die räumliche Karte nur eine bounded Vorschau zeigt."
                    if index == 3
                    else f"Behutsam gekürzte Erinnerung Nummer {index}."
                ),
                "public_excerpt": (
                    "Eine ausführliche freigegebene Erinnerung mit genügend ruhigem Kontext, "
                    "um die längste reale Kartenform auf einem schmalen Mobilgerät abzubilden. "
                    "Sie beschreibt mehrere Stationen, Menschen und belegte Zusammenhänge, ohne "
                    "private Angaben zu ergänzen. Der vollständige Text bleibt in der Liste lesbar, "
                    "während die räumliche Karte nur eine kurze Vorschau zeigt."
                    if index == 3
                    else f"Behutsam gekürzte Erinnerung Nummer {index}."
                ),
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


def _spoken_pcm16_bytes(*, seconds: float = 0.75, sample_rate: int = 16_000) -> bytes:
    total_samples = int(sample_rate * seconds)
    # Square-ish voiced test signal: enough energy to pass the live speech gate without relying on a host microphone.
    values = []
    period = max(1, sample_rate // 180)
    for index in range(total_samples):
        values.append(9000 if (index // period) % 2 == 0 else -9000)
    return struct.pack("<" + "h" * len(values), *values)


def _text_similarity(left: str, right: str) -> float:
    normalized_left = " ".join(str(left or "").lower().split())
    normalized_right = " ".join(str(right or "").lower().split())
    return difflib.SequenceMatcher(None, normalized_left, normalized_right).ratio()


@pytest.fixture()
def memorial_minimal_server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[dict[str, object]]:
    from app.api.routes import public_memorials
    from app.services import memorial_archive_registry

    monkeypatch.setenv("EA_STORAGE_BACKEND", "memory")
    monkeypatch.setenv("EA_API_TOKEN", "")
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("GOOGLE_API_KEY_FALLBACK_1", "playwright-gemini-live-key")
    monkeypatch.setenv("UNMIXR_API_KEY", "playwright-unmixr-key")
    monkeypatch.setenv("UNMIXR_VOICE_ID", "playwright-unmixr-voice")
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
            "tts_plugin": "unmixr_clone",
            "tts_plugin_voice_id": "playwright-unmixr-voice",
            "voice_label": "Manfred Hoza · Unmixr-Teststimme",
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
    def _fake_transcribe_audio_blob(**kwargs):
        content_type = str(kwargs.get("content_type") or "")
        payload = bytes(kwargs.get("payload") or b"")
        if content_type.startswith("audio/wav") and b"memorial-answer-audio" in payload:
            marker = payload.split(b"memorial-answer-audio:", 1)[-1]
            transcript_text = marker.decode("utf-8", errors="ignore").strip() or "Ich höre dich. Erzähl weiter."
        else:
            transcript_text = "Hallo Manfred, kannst du jetzt mit mir sprechen?"
        return {
            "transcription_status": "transcribed",
            "transcript_text": transcript_text,
            "transcriber": "playwright_stub",
        }

    monkeypatch.setattr(public_memorials, "_memorial_transcribe_audio_blob", _fake_transcribe_audio_blob)
    monkeypatch.setattr(
        public_memorials,
        "_render_memorial_tts_audio",
        lambda **kwargs: (_wav_bytes() + b"memorial-answer-audio:" + str(kwargs.get("text") or "").encode("utf-8"), "audio/wav"),
    )

    class _FakeGeminiLiveSocket:
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

    monkeypatch.setattr(public_memorials, "websockets", type("_FakeWebsockets", (), {"connect": _fake_gemini_connect}))
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
        browser = launch_installed_chromium(
            playwright,
            args=(
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--no-proxy-server",
            ),
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
          window.__getUserMediaCalls = 0;
          navigator.mediaDevices.getUserMedia = async () => {
            window.__getUserMediaCalls += 1;
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
          const OriginalWebSocket = window.WebSocket;
          if (typeof OriginalWebSocket === "function") {
            window.WebSocket = function(url, protocols) {
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


@pytest.mark.parametrize(
    ("viewport", "expected_dock_position"),
    [
        ({"width": 1440, "height": 1100}, "relative"),
        ({"width": 430, "height": 932}, "relative"),
        ({"width": 900, "height": 650}, "relative"),
    ],
)
def test_memorial_conversation_only_page_has_one_main_without_ui_noise(
    browser: Browser,
    memorial_minimal_server: dict[str, object],
    viewport: dict[str, int],
    expected_dock_position: str,
) -> None:
    base_url = str(memorial_minimal_server["base_url"])
    slug = str(memorial_minimal_server["slug"])
    context = browser.new_context(viewport=viewport)
    page: Page = context.new_page()
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    try:
        response = page.goto(f"{base_url}/memorials/{slug}", wait_until="domcontentloaded")
        assert response is not None and response.ok
        page.wait_for_function(
            """() => (
              document.querySelectorAll("main#memorial-conversation-region").length === 1 &&
              document.getElementById("memorial-text-turn-form") &&
              !document.getElementById("memorial-text-turn-form").hidden &&
              !document.getElementById("memorial-conversation").disabled
            )""",
            timeout=12000,
        )
        metrics = page.evaluate(
            """async () => {
              const settings = document.querySelector("details.conversation-settings");
              settings.open = true;
              window.scrollTo(0, document.documentElement.scrollHeight);
              await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
              const conversation = document.getElementById("memorial-conversation-region");
              const header = document.querySelector("header");
              const conversationRect = conversation.getBoundingClientRect();
              const headerRect = header.getBoundingClientRect();
              const guidance = document.getElementById("memorial-conversation-disclosure");
              const idleMonitor = document.getElementById("memorial-speech-monitor");
              const textInput = document.getElementById("memorial-text-turn-input");
              const textSubmit = document.getElementById("memorial-text-turn-submit");
              const personalMemoryToggle = document.querySelector(".conversation-toggle-control");
              const personalMemoryForget = document.getElementById("memorial-personal-memory-forget");
              return {
                scrollHeight: document.documentElement.scrollHeight,
                scrollWidth: document.documentElement.scrollWidth,
                viewportHeight: window.innerHeight,
                viewportWidth: window.innerWidth,
                dockPosition: getComputedStyle(conversation).position,
                conversationTop: conversationRect.top,
                headerBottom: headerRect.bottom,
                bodyPaddingBottom: parseFloat(getComputedStyle(document.body).paddingBottom || "0"),
                bodyOverflow: getComputedStyle(document.body).overflowY,
                htmlOverflow: getComputedStyle(document.documentElement).overflowY,
                mainCount: document.querySelectorAll("body > main").length,
                storyCount: document.querySelectorAll("#memorial-story").length,
                navigationCount: document.querySelectorAll("header nav").length,
                contributionCount: document.querySelectorAll("#memorial-contribution").length,
                settingsCount: document.querySelectorAll("details.conversation-settings").length,
                settingsWithinConversationCount: conversation.querySelectorAll("details.conversation-settings").length,
                personalMemoryOptinCount: conversation.querySelectorAll("#memorial-personal-memory-optin").length,
                personalMemoryStatusCount: conversation.querySelectorAll("#memorial-personal-memory-status").length,
                personalMemoryForgetCount: conversation.querySelectorAll("#memorial-personal-memory-forget").length,
                personalMemoryChecked: document.getElementById("memorial-personal-memory-optin").checked,
                personalMemoryForgetDisabled: document.getElementById("memorial-personal-memory-forget").disabled,
                personalMemoryForgetAriaDisabled: document.getElementById("memorial-personal-memory-forget").getAttribute("aria-disabled"),
                personalMemoryToggleHeight: personalMemoryToggle.getBoundingClientRect().height,
                personalMemoryForgetHeight: personalMemoryForget.getBoundingClientRect().height,
                installCount: document.querySelectorAll("#memorial-install-hint").length,
                memoryRoomLinks: document.querySelectorAll("a[href*='/memory-room']").length,
                mainLabel: conversation.getAttribute("aria-label"),
                guidanceAlign: getComputedStyle(guidance).textAlign,
                guidanceWidth: guidance.getBoundingClientRect().width,
                chatWidth: document.querySelector(".chat").getBoundingClientRect().width,
                idleMonitorDisplay: getComputedStyle(idleMonitor).display,
                idleMonitorHeight: idleMonitor.getBoundingClientRect().height,
                inputFontSize: parseFloat(getComputedStyle(textInput).fontSize),
                inputHeight: textInput.getBoundingClientRect().height,
                submitHeight: textSubmit.getBoundingClientRect().height,
              };
            }"""
        )
        assert int(metrics["scrollHeight"]) >= int(metrics["viewportHeight"])
        assert int(metrics["scrollWidth"]) <= int(metrics["viewportWidth"]) + 1
        assert metrics["dockPosition"] == expected_dock_position
        assert metrics["bodyOverflow"] == "auto"
        assert metrics["htmlOverflow"] == "auto"
        assert float(metrics["conversationTop"]) >= float(metrics["headerBottom"]) - 1
        assert float(metrics["bodyPaddingBottom"]) == 0
        assert metrics["mainCount"] == 1
        assert metrics["storyCount"] == 0
        assert metrics["navigationCount"] == 0
        assert metrics["contributionCount"] == 0
        assert metrics["settingsCount"] == 1
        assert metrics["settingsWithinConversationCount"] == 1
        assert metrics["personalMemoryOptinCount"] == 1
        assert metrics["personalMemoryStatusCount"] == 1
        assert metrics["personalMemoryForgetCount"] == 1
        assert metrics["personalMemoryChecked"] is False
        assert metrics["personalMemoryForgetDisabled"] is True
        assert metrics["personalMemoryForgetAriaDisabled"] == "true"
        assert float(metrics["personalMemoryToggleHeight"]) >= 44
        assert float(metrics["personalMemoryForgetHeight"]) >= 44
        assert metrics["installCount"] == 0
        assert metrics["memoryRoomLinks"] == 0
        assert str(metrics["mainLabel"]).startswith("KI-Gespräch über ")
        assert metrics["guidanceAlign"] == "center"
        assert float(metrics["guidanceWidth"]) <= float(metrics["chatWidth"])
        assert metrics["idleMonitorDisplay"] == "none"
        assert float(metrics["idleMonitorHeight"]) == 0
        assert float(metrics["inputFontSize"]) >= 16
        assert float(metrics["inputHeight"]) >= 44
        assert float(metrics["submitHeight"]) >= 44

        assert page.get_by_text("Die Stimme ist künstlich erzeugt.", exact=False).is_visible()
        assert page.get_by_role("button", name="Gespräch starten").is_visible()
        assert page.get_by_label("Oder schreiben").is_visible()

        page_html = page.content()
        for sentinel in (
            RAW_TRANSCRIPT_SENTINEL,
            PRIVATE_MEMORY_SENTINEL,
            PRIVATE_SOURCE_SENTINEL,
            PRIVATE_FAMILY_SENTINEL,
        ):
            assert sentinel not in page_html
        page.wait_for_timeout(250)
        assert page_errors == []
    finally:
        context.close()


def test_memorial_blocked_voice_release_has_one_text_action_and_never_requests_microphone(
    browser: Browser,
    memorial_minimal_server: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials

    monkeypatch.setattr(public_memorials, "_memorial_voice_release_enforced", lambda: True)
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_release_decision",
        lambda slug: {"allowed": False, "status": "blocked", "reason": "release_human_acceptance_missing"},
    )
    base_url = str(memorial_minimal_server["base_url"])
    slug = str(memorial_minimal_server["slug"])
    context = browser.new_context(viewport={"width": 390, "height": 844})
    context.add_init_script(
        """
        (() => {
          window.__getUserMediaCalls = 0;
          navigator.mediaDevices = navigator.mediaDevices || {};
          navigator.mediaDevices.getUserMedia = async () => {
            window.__getUserMediaCalls += 1;
            throw new DOMException("blocked test microphone", "NotAllowedError");
          };
        })();
        """
    )
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/memorials/{slug}", wait_until="domcontentloaded")
        assert response is not None and response.ok
        page.wait_for_function(
            "() => !document.getElementById('memorial-text-turn-form').hidden",
            timeout=3000,
        )
        assert page.locator("#memorial-conversation-region").get_attribute("data-voice-release") == "blocked"
        assert page.locator("#memorial-conversation").is_hidden()
        assert page.locator("#memorial-voice-recovery-note").is_hidden()
        assert page.locator("#memorial-conversation-disclosure").get_by_text(
            "Sprechen ist derzeit nicht verfügbar", exact=False
        ).is_visible()
        assert page.locator("label[for='memorial-text-turn-input']").text_content() == "Frage schreiben"
        assert page.locator("#memorial-speech-message").text_content() == "Schreiben ist bereit."

        page.locator("#memorial-text-turn-input").fill("Was war Manfred wichtig?")
        page.locator("#memorial-text-turn-input").press("Enter")
        page.wait_for_function(
            "() => document.querySelectorAll('#memorial-speech-transcript > .speech-turn').length === 2",
            timeout=5000,
        )
        assert page.evaluate("window.__getUserMediaCalls") == 0
        assert page.locator("#memorial-speech-transcript > .speech-turn").count() == 2
        assert page.locator("#memorial-chat-answer").is_hidden()
        source_toggle = page.locator("#memorial-toggle-status")
        source_status = page.locator("#memorial-chat-status")
        assert source_toggle.is_visible()
        assert source_toggle.get_attribute("aria-expanded") == "false"
        assert source_status.is_hidden()
        source_toggle.click()
        assert source_toggle.get_attribute("aria-expanded") == "true"
        assert source_status.is_visible()
        assert source_status.inner_text() == (
            "Quellen: Öffentliche Quelle 1, Öffentliche Quelle 2, "
            "Öffentliche Quelle 3, Öffentliche Quelle 4"
        )
    finally:
        context.close()


def test_candidate_browser_audit_accepts_current_blocked_talk_copy(
    memorial_minimal_server: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials
    from scripts.measure_memorial_live_browser import _resolve_chromium_executable
    from scripts import verify_manfred_memorial_candidate as candidate_verify

    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_release_enforced",
        lambda: True,
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_release_decision",
        lambda _slug: {
            "allowed": False,
            "status": "blocked",
            "reason": "release_human_acceptance_missing",
        },
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        def _resolve_installed_chromium() -> str | None:
            with sync_playwright() as playwright:
                executable_path, _executable_source = _resolve_chromium_executable(playwright)
            return executable_path

        executable_path = executor.submit(_resolve_installed_chromium).result(timeout=10)
        assert executable_path is not None
        monkeypatch.setenv("EA_PLAYWRIGHT_CHROMIUM_EXECUTABLE", executable_path)
        evidence = executor.submit(
            candidate_verify.audit_browser_surface,
            str(memorial_minimal_server["base_url"]),
            public_origin="https://myexternalbrain.com",
        ).result(timeout=30)

    assert evidence["status"] == "pass"
    assert evidence["memorial_surface"] == "conversation_only"
    for field in candidate_verify.BROWSER_ZERO_COUNT_FIELDS:
        assert evidence[field] == 0


def test_memorial_text_retry_resubmits_text_without_starting_microphone(
    browser: Browser,
    memorial_minimal_server: dict[str, object],
) -> None:
    base_url = str(memorial_minimal_server["base_url"])
    slug = str(memorial_minimal_server["slug"])
    context = browser.new_context(viewport={"width": 390, "height": 844})
    context.add_init_script(
        """
        (() => {
          window.__getUserMediaCalls = 0;
          navigator.mediaDevices = navigator.mediaDevices || {};
          navigator.mediaDevices.getUserMedia = async () => {
            window.__getUserMediaCalls += 1;
            throw new DOMException("unexpected microphone request", "NotAllowedError");
          };
        })();
        """
    )
    failed_requests: list[str] = []
    page: Page = context.new_page()

    def fail_text_turn(route) -> None:
        failed_requests.append(route.request.url)
        route.fulfill(
            status=503,
            content_type="application/json",
            body=json.dumps({"detail": "test_text_failure"}),
        )

    page.route(f"**/memorials/{slug}/chat", fail_text_turn)
    try:
        response = page.goto(f"{base_url}/memorials/{slug}", wait_until="domcontentloaded")
        assert response is not None and response.ok
        page.wait_for_function(
            """() => (
              !document.getElementById('memorial-text-turn-form').hidden &&
              !document.getElementById('memorial-conversation').disabled
            )""",
            timeout=12000,
        )
        text_input = page.locator("#memorial-text-turn-input")
        text_input.fill("Welche Erinnerung ist belegt?")
        text_input.press("Enter")
        retry = page.get_by_role("button", name="Textfrage erneut senden")
        retry.wait_for(state="visible", timeout=3000)
        assert len(failed_requests) == 1
        assert page.evaluate("window.__getUserMediaCalls") == 0

        retry.click()
        page.wait_for_timeout(250)
        assert len(failed_requests) == 2
        assert page.evaluate("window.__getUserMediaCalls") == 0
        assert text_input.input_value() == "Welche Erinnerung ist belegt?"
        assert retry.is_visible()
    finally:
        context.close()


def test_memorial_memory_room_mobile_keyboard_and_back_journey(
    browser: Browser,
    memorial_minimal_server: dict[str, object],
) -> None:
    base_url = str(memorial_minimal_server["base_url"])
    slug = str(memorial_minimal_server["slug"])
    context = browser.new_context(viewport={"width": 320, "height": 568})
    page: Page = context.new_page()
    room_requests: list[str] = []
    page.on("request", lambda request: room_requests.append(request.url))
    try:
        response = page.goto(
            f"{base_url}/memorials/{slug}/memory-room",
            wait_until="domcontentloaded",
        )
        assert response is not None and response.ok
        page.wait_for_function(
            "() => document.querySelector('[data-room-status]')?.textContent?.startsWith('Bereit')",
            timeout=3000,
        )

        metrics = page.evaluate(
            """() => {
              const stage = document.getElementById("memory-room-stage");
              const lastEntry = document.querySelector(".memory-entry:last-child");
              return {
                lang: document.documentElement.lang,
                scrollWidth: document.documentElement.scrollWidth,
                viewportWidth: window.innerWidth,
                bodyOverflow: getComputedStyle(document.body).overflowY,
                htmlOverflow: getComputedStyle(document.documentElement).overflowY,
                touchAction: getComputedStyle(stage).touchAction,
                perspective: getComputedStyle(stage).perspective,
                transformStyle: getComputedStyle(document.querySelector("[data-room-orbit]")).transformStyle,
                memoryCount: document.querySelectorAll(".memory-entry").length,
                lastEntryExists: Boolean(lastEntry),
                externalAssets: Array.from(document.querySelectorAll("script[src],link[rel=stylesheet],iframe"))
                  .map((node) => node.getAttribute("src") || node.getAttribute("href")),
              };
            }"""
        )
        assert metrics["lang"] == "de"
        assert int(metrics["scrollWidth"]) <= int(metrics["viewportWidth"]) + 1
        assert metrics["bodyOverflow"] == "auto"
        assert metrics["htmlOverflow"] == "auto"
        assert "pan-y" in str(metrics["touchAction"])
        assert metrics["perspective"] != "none"
        assert metrics["transformStyle"] == "preserve-3d"
        assert int(metrics["memoryCount"]) == 6
        assert metrics["lastEntryExists"] is True
        assert metrics["externalAssets"] == []
        assert all(url.startswith(base_url) for url in room_requests)
        assert page.get_by_text("keine Rekonstruktion eines realen Ortes").is_visible()
        assert page.locator("header [data-room-back]").get_attribute("href") == (
            f"/memorials/{slug}#memorial-conversation-region"
        )
        assert page.locator("header [data-room-back]").text_content() == "← Zurück zum Gespräch"
        assert page.locator("footer [data-room-back]").text_content() == "Zurück zum Gedenkgespräch"

        stage = page.locator("#memory-room-stage")
        stage.focus()
        page.keyboard.press("ArrowRight")
        assert page.locator("[data-room-position]").text_content() == "2 / 6"
        rotated = page.evaluate(
            """() => ({
              angle: document.querySelector("[data-room-orbit]").style.getPropertyValue("--room-angle"),
              active: document.querySelector(".room-panel.is-active")?.getAttribute("data-room-panel"),
            })"""
        )
        assert rotated == {"angle": "-60deg", "active": "1"}
        page.keyboard.press("ArrowRight")
        page.wait_for_function(
            "() => document.querySelector('[data-room-position]')?.textContent === '3 / 6'"
        )
        bounds = page.evaluate(
            """() => {
              const stage = document.getElementById("memory-room-stage").getBoundingClientRect();
              const status = document.querySelector("[data-room-status]").getBoundingClientRect();
              const controls = document.querySelector(".room-controls").getBoundingClientRect();
              const panel = document.querySelector(".room-panel.is-active").getBoundingClientRect();
              return {
                panelTop: panel.top,
                panelBottom: panel.bottom,
                statusBottom: status.bottom,
                controlsTop: controls.top,
                stageTop: stage.top,
                stageBottom: stage.bottom,
              };
            }"""
        )
        assert float(bounds["panelTop"]) >= float(bounds["statusBottom"]) + 4
        assert float(bounds["panelBottom"]) <= float(bounds["controlsTop"]) - 4
        assert float(bounds["panelTop"]) >= float(bounds["stageTop"])
        assert float(bounds["panelBottom"]) <= float(bounds["stageBottom"])

        stage.hover()
        before_scroll = page.evaluate("window.scrollY")
        page.mouse.wheel(0, 520)
        page.wait_for_timeout(120)
        after_scroll = page.evaluate("window.scrollY")
        assert float(after_scroll) > float(before_scroll)

        page.emulate_media(reduced_motion="reduce")
        page.locator('[data-memory-focus="5"]').click()
        page.wait_for_function(
            "() => document.querySelector('[data-room-position]')?.textContent === '6 / 6'"
        )
        reduced_motion = page.evaluate(
            """() => ({
              matches: matchMedia("(prefers-reduced-motion: reduce)").matches,
              transition: getComputedStyle(document.querySelector("[data-room-orbit]")).transitionDuration,
              activePanels: document.querySelectorAll(".room-panel.is-active").length,
            })"""
        )
        assert reduced_motion["matches"] is True
        assert reduced_motion["transition"] == "0s"
        assert int(reduced_motion["activePanels"]) == 1

        page.locator("[data-room-back]").first.click()
        page.wait_for_url(f"{base_url}/memorials/{slug}#memorial-conversation-region")
        assert page.locator("#memorial-conversation-region").is_visible()
    finally:
        context.close()


def test_memorial_memory_room_no_js_keeps_every_memory_and_back_link(
    browser: Browser,
    memorial_minimal_server: dict[str, object],
) -> None:
    base_url = str(memorial_minimal_server["base_url"])
    slug = str(memorial_minimal_server["slug"])
    context = browser.new_context(
        viewport={"width": 320, "height": 568},
        java_script_enabled=False,
    )
    page: Page = context.new_page()
    try:
        response = page.goto(
            f"{base_url}/memorials/{slug}/memory-room",
            wait_until="domcontentloaded",
        )
        assert response is not None and response.ok
        assert page.locator("#memory-room-stage").is_hidden()
        no_js_notice = page.locator("noscript .room-trust")
        assert no_js_notice.is_visible()
        assert "Alle freigegebenen Erinnerungen bleiben vollständig" in (
            no_js_notice.text_content() or ""
        )
        assert page.locator(".memory-entry").count() == 6
        assert page.locator(".memory-focus:visible").count() == 0
        footer_link = page.locator("footer [data-room-back]")
        footer_link.scroll_into_view_if_needed()
        assert footer_link.is_visible()
        metrics = page.evaluate(
            """() => ({
              scrollWidth: document.documentElement.scrollWidth,
              viewportWidth: window.innerWidth,
              scrollY: window.scrollY,
            })"""
        )
        assert int(metrics["scrollWidth"]) <= int(metrics["viewportWidth"]) + 1
        assert float(metrics["scrollY"]) > 0
    finally:
        context.close()


def test_memorial_memory_room_initialization_failure_keeps_readable_fallback(
    browser: Browser,
    memorial_minimal_server: dict[str, object],
) -> None:
    base_url = str(memorial_minimal_server["base_url"])
    slug = str(memorial_minimal_server["slug"])
    context = browser.new_context(viewport={"width": 390, "height": 844})
    context.add_init_script(
        """
        (() => {
          const original = Document.prototype.querySelector;
          Document.prototype.querySelector = function querySelector(selector) {
            if (selector === "[data-room-orbit]") return null;
            return original.call(this, selector);
          };
        })();
        """
    )
    page: Page = context.new_page()
    try:
        response = page.goto(
            f"{base_url}/memorials/{slug}/memory-room",
            wait_until="domcontentloaded",
        )
        assert response is not None and response.ok
        page.wait_for_function(
            "() => document.querySelector('[data-room-status]')?.textContent?.startsWith('Die 3D-Ansicht konnte nicht')"
        )
        assert page.locator(".memory-entry").count() == 6
        assert page.locator(".memory-focus:visible").count() == 0
        assert page.locator(".room-controls").is_hidden()
        assert page.locator("footer [data-room-back]").is_visible()
    finally:
        context.close()


@pytest.mark.skipif(not _HAS_WEBSOCKET_PROTOCOL, reason="uvicorn websocket protocol support requires websockets or wsproto")
def test_memorial_minimal_page_completes_one_browser_conversation_turn(
    browser: Browser,
    memorial_minimal_server: dict[str, object],
) -> None:
    base_url = str(memorial_minimal_server["base_url"])
    slug = str(memorial_minimal_server["slug"])
    context = browser.new_context(viewport={"width": 430, "height": 932})
    _install_fake_audio_runtime(context)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/memorials/{slug}", wait_until="domcontentloaded")
        assert response is not None and response.ok
        page.wait_for_function(
            "() => !document.getElementById('memorial-conversation').disabled",
            timeout=12000,
        )
        _await_realtime_turn_complete(
            page,
            slug,
            lambda: page.evaluate("window.__memorialStartConversation && window.__memorialStartConversation()"),
            timeout_ms=12000,
        )
        page.wait_for_function(
            """() => {
              const button = document.getElementById("memorial-conversation");
              return Boolean(button && button.textContent && button.textContent.includes("Gespräch beenden"));
            }""",
            timeout=3000,
        )
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
              return Boolean(button && button.textContent && button.textContent.includes("Gespräch starten"));
            }""",
            timeout=7000,
        )
        phase_text = page.locator("#memorial-speech-phase").text_content() or ""
        message_text = page.locator("#memorial-speech-message").text_content() or ""
        assert "Bitte noch einmal" not in phase_text
        assert "Bitte noch einmal" not in message_text
        assert page.locator("#memorial-retry-button").is_hidden()
        turns = page.locator("#memorial-speech-transcript > .speech-turn")
        assert turns.count() == 2
        assert turns.nth(0).get_attribute("class") == "speech-turn user"
        assert turns.nth(1).get_attribute("class") == "speech-turn assistant"
        assert turns.nth(0).locator("strong").text_content() == "Du"
        assert turns.nth(1).locator("strong").text_content() == "KI-Begleiter"
        assert page.locator("#memorial-speech-transcript-live").is_hidden()
        assert page.locator("#memorial-chat-answer").is_hidden()
    finally:
        context.close()


@pytest.mark.skipif(not _HAS_WEBSOCKET_PROTOCOL, reason="uvicorn websocket protocol support requires websockets or wsproto")
def test_memorial_minimal_browser_voice_exit_gate_roundtrips_tts_to_stt(
    browser: Browser,
    memorial_minimal_server: dict[str, object],
) -> None:
    base_url = str(memorial_minimal_server["base_url"])
    slug = str(memorial_minimal_server["slug"])
    spoken_pcm_base64 = base64.b64encode(_spoken_pcm16_bytes()).decode("ascii")
    context = browser.new_context(
        viewport={"width": 430, "height": 932},
        locale="en-US",
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
    )
    _install_fake_audio_runtime(context)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/memorials/{slug}", wait_until="domcontentloaded")
        assert response is not None and response.ok
        page.wait_for_function(
            "() => !document.getElementById('memorial-conversation').disabled",
            timeout=12000,
        )
        result = page.evaluate(
            """async ({ slug, spokenPcmBase64 }) => {
              const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
              const wsUrl = `${wsProtocol}//${window.location.host}/memorials/${slug}/realtime?personal_memory=1&lang=en-US`;
              const websocket = new WebSocket(wsUrl);
              websocket.binaryType = "arraybuffer";
              const events = [];
              let assistantText = "";
              let audioBase64 = "";
              let audioContentType = "";
              let ttsPlugin = "";
              let error = "";

              const waitForEvent = (predicate, timeoutMs) => new Promise((resolve, reject) => {
                const deadline = window.setTimeout(() => {
                  cleanup();
                  reject(new Error("timeout"));
                }, timeoutMs);
                const cleanup = () => {
                  window.clearTimeout(deadline);
                  websocket.removeEventListener("message", onMessage);
                  websocket.removeEventListener("error", onError);
                };
                const onError = () => {
                  cleanup();
                  reject(new Error("websocket_error"));
                };
                const onMessage = (event) => {
                  const payload = JSON.parse(String(event.data || "{}"));
                  events.push(payload);
                  if (payload.type === "response.output_audio_transcript.done" || payload.type === "answer") {
                    assistantText = String(payload.transcript || payload.text || assistantText || "");
                  }
                  if (payload.type === "audio") {
                    audioBase64 = String(payload.audio_base64 || payload.audio || "");
                    audioContentType = String(payload.content_type || payload.mime_type || "");
                    ttsPlugin = String(payload.tts_plugin || "");
                  }
                  if (payload.type === "error") {
                    error = String(payload.message || payload.detail || "error");
                  }
                  if (predicate(payload)) {
                    cleanup();
                    resolve(payload);
                  }
                };
                websocket.addEventListener("message", onMessage);
                websocket.addEventListener("error", onError);
              });

              await new Promise((resolve, reject) => {
                websocket.addEventListener("open", resolve, { once: true });
                websocket.addEventListener("error", () => reject(new Error("websocket_open_error")), { once: true });
              });
              await waitForEvent((payload) => payload.type === "ready" || payload.type === "setup_complete", 5000);

              websocket.send(JSON.stringify({
                type: "user_audio_start",
                turn_id: "exit_gate_browser_voice",
                content_type: "audio/pcm;rate=16000",
                transport: "gemini_live",
                browser_language: "en-US"
              }));
              const binary = atob(spokenPcmBase64);
              const bytes = new Uint8Array(binary.length);
              for (let index = 0; index < binary.length; index += 1) {
                bytes[index] = binary.charCodeAt(index);
              }
              websocket.send(bytes.buffer);
              websocket.send(JSON.stringify({
                type: "user_audio_end",
                turn_id: "exit_gate_browser_voice",
                content_type: "audio/pcm;rate=16000",
                transport: "gemini_live",
                browser_language: "en-US"
              }));
              await waitForEvent((payload) => payload.type === "turn_complete" || payload.type === "error", 8000);
              websocket.close();

              let stt = null;
              if (audioBase64) {
                const audioBinary = atob(audioBase64);
                const audioBytes = new Uint8Array(audioBinary.length);
                for (let index = 0; index < audioBinary.length; index += 1) {
                  audioBytes[index] = audioBinary.charCodeAt(index);
                }
                const sttResponse = await fetch(`/memorials/${slug}/speech-transcribe`, {
                  method: "POST",
                  headers: { "Content-Type": audioContentType || "audio/wav" },
                  body: new Blob([audioBytes], { type: audioContentType || "audio/wav" })
                });
                stt = await sttResponse.json();
              }

              return { events, assistantText, audioBase64, audioContentType, ttsPlugin, error, stt };
            }""",
            {"slug": slug, "spokenPcmBase64": spoken_pcm_base64},
        )
        assert not result["error"]
        assert result["audioBase64"]
        assert result["audioContentType"] == "audio/wav"
        assert result["ttsPlugin"] == "unmixr_clone"
        assert result["assistantText"] in {
            "Worum geht es?",
            "Ja. Ich höre dich.",
            "Ich höre dich. Sag es mir in Ruhe.",
            "Ja. Sag mir, was dich gerade beschäftigt.",
            "Sprich ruhig weiter. Ich antworte dir direkt.",
        }
        assert "Ich bin da" not in result["assistantText"]
        stt = result["stt"]
        assert isinstance(stt, dict)
        transcript = str(stt.get("transcript_text") or "")
        assert stt.get("transcription_status") == "transcribed"
        assert _text_similarity(transcript, result["assistantText"]) >= 0.9
        assert any(event.get("type") == "turn_complete" for event in result["events"])
    finally:
        context.close()
