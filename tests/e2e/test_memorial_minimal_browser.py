from __future__ import annotations

import json
import base64
import asyncio
import difflib
import socket
import struct
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
                if turn_id and slug and f"turn_" not in turn_id and not state.get("turn_id"):
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
    ("viewport", "max_slack"),
    [
        ({"width": 1440, "height": 1100}, 4),
        ({"width": 430, "height": 932}, 6),
    ],
)
def test_memorial_minimal_page_fits_single_viewport_without_scroll(
    browser: Browser,
    memorial_minimal_server: dict[str, object],
    viewport: dict[str, int],
    max_slack: int,
) -> None:
    base_url = str(memorial_minimal_server["base_url"])
    slug = str(memorial_minimal_server["slug"])
    context = browser.new_context(viewport=viewport)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/memorials/{slug}", wait_until="domcontentloaded")
        assert response is not None and response.ok
        page.wait_for_function(
            "() => !document.getElementById('memorial-conversation').disabled",
            timeout=5000,
        )
        metrics = page.evaluate(
            """() => ({
              html: document.documentElement.scrollHeight,
              body: document.body.scrollHeight,
              viewport: window.innerHeight,
              bodyOverflow: getComputedStyle(document.body).overflowY,
              htmlOverflow: getComputedStyle(document.documentElement).overflowY,
            })"""
        )
        assert int(metrics["html"]) <= int(metrics["viewport"]) + max_slack
        assert int(metrics["body"]) <= int(metrics["viewport"]) + max_slack
        assert metrics["bodyOverflow"] == "hidden"
        assert metrics["htmlOverflow"] == "hidden"
    finally:
        context.close()


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
            timeout=5000,
        )
        _await_realtime_turn_complete(
            page,
            slug,
            lambda: page.evaluate("window.__memorialStartConversation && window.__memorialStartConversation()"),
            timeout_ms=7000,
        )
        page.wait_for_function(
            """() => {
              const button = document.getElementById("memorial-conversation");
              return Boolean(button && button.textContent && button.textContent.includes("Gespräch stoppen"));
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
              return Boolean(button && button.textContent && button.textContent.includes("Gespräch beginnen"));
            }""",
            timeout=7000,
        )
        phase_text = page.locator("#memorial-speech-phase").text_content() or ""
        message_text = page.locator("#memorial-speech-message").text_content() or ""
        assert "Bitte noch einmal" not in phase_text
        assert "Bitte noch einmal" not in message_text
        assert page.locator("#memorial-retry-button").is_hidden()
    finally:
        context.close()


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
            timeout=5000,
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
            "Ja. Ich höre dich.",
            "Ich höre dich. Erzähl weiter.",
            "Ja. Sag mir, was dich gerade beschäftigt.",
            "Ich bin da. Erzähl mir bitte mehr.",
        }
        stt = result["stt"]
        assert isinstance(stt, dict)
        transcript = str(stt.get("transcript_text") or "")
        assert stt.get("transcription_status") == "transcribed"
        assert _text_similarity(transcript, result["assistantText"]) >= 0.9
        assert any(event.get("type") == "turn_complete" for event in result["events"])
    finally:
        context.close()
