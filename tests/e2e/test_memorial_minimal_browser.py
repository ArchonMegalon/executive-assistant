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
    monkeypatch.setenv("EA_SOURCE_REVISION", "a" * 40)
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
    original_phrase_bank_entry = public_memorials._memorial_phrase_bank_entry

    def _fake_phrase_bank_entry(phrase_id: str) -> dict[str, object]:
        entry = original_phrase_bank_entry(phrase_id)
        if phrase_id == "contact_opening":
            entry["audio_text"] = "Ich höre dir zu. Worum geht es?"
            entry["visible_text"] = "Ich höre dir zu. Worum geht es?"
        return entry

    monkeypatch.setattr(public_memorials, "_memorial_phrase_bank_entry", _fake_phrase_bank_entry)

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


def _install_fake_audio_runtime(
    context,
    *,
    playback_delay_ms: int = 1750,
    recorder_event_delay_ms: int = 0,
    blob_array_buffer_delay_ms: int = 0,
) -> None:
    assert playback_delay_ms > 0
    assert recorder_event_delay_ms >= 0
    assert blob_array_buffer_delay_ms >= 0
    context.add_init_script(
        """
        (() => {
          navigator.mediaDevices = navigator.mediaDevices || {};
          window.__getUserMediaCalls = 0;
          window.__memorialMediaTrackStopCalls = 0;
          window.__memorialMediaRecorderStarts = 0;
          window.__memorialMediaRecorderStops = 0;
          navigator.mediaDevices.getUserMedia = async () => {
            window.__getUserMediaCalls += 1;
            return {
              getTracks() {
                return [{
                  stop() {
                    window.__memorialMediaTrackStopCalls += 1;
                  },
                }];
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
              window.__memorialMediaRecorderStarts += 1;
              this.state = "recording";
              setTimeout(() => this.stop(), 250);
            }
            stop() {
              if (this.state === "inactive") return;
              window.__memorialMediaRecorderStops += 1;
              this.state = "inactive";
              const emitStop = () => {
                if (this.ondataavailable) {
                  const payload = new Uint8Array(512);
                  payload.fill(7);
                  this.ondataavailable({
                    data: new Blob([payload], { type: this.mimeType }),
                  });
                }
                if (this.onstop) this.onstop();
              };
              if (__RECORDER_EVENT_DELAY_MS__ > 0) {
                setTimeout(emitStop, __RECORDER_EVENT_DELAY_MS__);
              } else {
                emitStop();
              }
            }
            static isTypeSupported() {
              return true;
            }
          }

          window.MediaRecorder = FakeMediaRecorder;
          const originalBlobArrayBuffer = Blob.prototype.arrayBuffer;
          Blob.prototype.arrayBuffer = function memorialArrayBuffer() {
            if (
              __BLOB_ARRAY_BUFFER_DELAY_MS__ <= 0
              || !String(this.type || "").startsWith("audio/webm")
            ) {
              return originalBlobArrayBuffer.call(this);
            }
            return new Promise((resolve, reject) => {
              window.setTimeout(() => {
                originalBlobArrayBuffer.call(this).then(resolve, reject);
              }, __BLOB_ARRAY_BUFFER_DELAY_MS__);
            });
          };
          window.__memorialRealtimeFrames = [];
          window.__memorialAudioPlayCalls = 0;
          window.__memorialAudioEndedEvents = 0;
          window.__memorialAudioPauseCalls = 0;
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
          const originalPause = HTMLMediaElement.prototype.pause;
          HTMLMediaElement.prototype.pause = function pause() {
            window.__memorialAudioPauseCalls += 1;
            return originalPause.call(this);
          };
          HTMLMediaElement.prototype.play = function play() {
            window.__memorialAudioPlayCalls += 1;
            return new Promise((resolve) => {
              window.setTimeout(() => {
                window.__memorialAudioEndedEvents += 1;
                this.dispatchEvent(new Event("ended"));
                resolve();
              }, __PLAYBACK_DELAY_MS__);
            });
          };
        })();
        """.replace("__PLAYBACK_DELAY_MS__", str(playback_delay_ms))
        .replace("__RECORDER_EVENT_DELAY_MS__", str(recorder_event_delay_ms))
        .replace("__BLOB_ARRAY_BUFFER_DELAY_MS__", str(blob_array_buffer_delay_ms))
    )


def _install_fake_memorial_websocket(
    page: Page,
    *,
    response_delay_ms: int = 25,
    close_before_admission: bool = False,
    close_after_admission: bool = False,
) -> None:
    assert response_delay_ms >= 0
    page.evaluate(
        """({ responseDelayMs, closeBeforeAdmission, closeAfterAdmission }) => {
          window.__memorialFakeSocketStarts = 0;
          window.__memorialFakeSocketTurnEnds = 0;
          window.__memorialFakeSocketCancels = 0;
          window.__memorialFakeSocketCloses = 0;
          class FakeMemorialWebSocket extends EventTarget {
            constructor(url) {
              super();
              this.url = String(url || "");
              this.readyState = FakeMemorialWebSocket.CONNECTING;
              this.binaryType = "arraybuffer";
              this.onopen = null;
              this.onerror = null;
              this.onclose = null;
              this.activeTurnId = "";
              window.setTimeout(() => {
                this.readyState = FakeMemorialWebSocket.OPEN;
                const event = new Event("open");
                if (typeof this.onopen === "function") this.onopen(event);
                this.dispatchEvent(event);
                this.emit({
                  type: "ready",
                  mode: "spoken_turn_fallback",
                  native_realtime_available: false,
                });
              }, 0);
            }
            emit(payload) {
              this.dispatchEvent(new MessageEvent("message", {
                data: JSON.stringify(payload),
              }));
            }
            send(raw) {
              if (typeof raw !== "string") return;
              const payload = JSON.parse(raw);
              const type = String(payload.type || "");
              if (type === "user_audio_start") {
                this.activeTurnId = String(payload.turn_id || "");
                window.__memorialFakeSocketStarts += 1;
                return;
              }
              if (type === "cancel_current_turn") {
                window.__memorialFakeSocketCancels += 1;
                this.emit({
                  type: "cancelled",
                  turn_id: String(payload.turn_id || this.activeTurnId),
                });
                return;
              }
              if (type !== "user_audio_end") return;
              const turnId = String(payload.turn_id || this.activeTurnId);
              window.__memorialFakeSocketTurnEnds += 1;
              if (closeBeforeAdmission) {
                this.close(1011, "test_close_before_admission");
                return;
              }
              this.emit({
                type: "turn_admitted",
                turn_id: turnId,
                provider_work_started: true,
                transport: "ea_memorial_turn",
              });
              if (closeAfterAdmission) {
                this.close(1011, "test_close_after_admission");
                return;
              }
              window.setTimeout(() => {
                this.emit({
                  type: "phase",
                  phase: "thinking",
                  turn_id: turnId,
                });
                this.emit({
                  type: "transcript",
                  turn_id: turnId,
                  text: "Erzähl mir etwas über deine Familie.",
                  effective_text: "Erzähl mir etwas über deine Familie.",
                });
                this.emit({
                  type: "answer",
                  turn_id: turnId,
                  text: "Ich habe Familie immer als Verantwortung verstanden.",
                  sources: ["Freigegebene Erinnerung"],
                  llm_model: "memorial-test",
                });
                this.emit({
                  type: "audio",
                  turn_id: turnId,
                  audio_base64: btoa("fake-memorial-audio"),
                  content_type: "audio/wav",
                });
                this.emit({ type: "turn_complete", turn_id: turnId });
              }, responseDelayMs);
            }
            close(code = 1000) {
              if (this.readyState === FakeMemorialWebSocket.CLOSED) return;
              this.readyState = FakeMemorialWebSocket.CLOSED;
              window.__memorialFakeSocketCloses += 1;
              const event = new CloseEvent("close", { code });
              if (typeof this.onclose === "function") this.onclose(event);
              this.dispatchEvent(event);
            }
          }
          FakeMemorialWebSocket.CONNECTING = 0;
          FakeMemorialWebSocket.OPEN = 1;
          FakeMemorialWebSocket.CLOSING = 2;
          FakeMemorialWebSocket.CLOSED = 3;
          window.WebSocket = FakeMemorialWebSocket;
        }""",
        {
            "responseDelayMs": response_delay_ms,
            "closeBeforeAdmission": close_before_admission,
            "closeAfterAdmission": close_after_admission,
        },
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
        ({"width": 320, "height": 568}, "relative"),
    ],
)
def test_memorial_conversation_only_page_has_one_main_without_ui_noise(
    browser: Browser,
    memorial_minimal_server: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    viewport: dict[str, int],
    expected_dock_position: str,
) -> None:
    from app.api.routes import public_memorial_surface, public_memorials

    preview_session = {
        "slug": "manfred",
        "scopes": ["page", "readiness", "realtime"],
    }
    monkeypatch.setattr(
        public_memorial_surface,
        "_memorial_voice_review_http_session_payload",
        lambda *_args, **_kwargs: dict(preview_session),
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_review_http_session_payload",
        lambda *_args, **_kwargs: dict(preview_session),
    )
    base_url = str(memorial_minimal_server["base_url"])
    slug = str(memorial_minimal_server["slug"])
    context = browser.new_context(viewport=viewport)
    _install_fake_audio_runtime(context, playback_delay_ms=10)
    page: Page = context.new_page()
    page_errors: list[str] = []
    requests: list[str] = []
    websockets: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on("request", lambda request: requests.append(request.url))
    page.on("websocket", lambda websocket: websockets.append(websocket.url))
    try:
        response = page.goto(f"{base_url}/memorials/{slug}", wait_until="domcontentloaded")
        assert response is not None and response.ok
        page.wait_for_function(
            """() => (
              document.querySelectorAll("main#memorial-conversation-region").length === 1 &&
              document.getElementById("memorial-conversation") &&
              !document.getElementById("memorial-conversation").disabled &&
              document.getElementById("memorial-conversation").textContent.trim() === "Gespräch beginnen"
            )""",
            timeout=12000,
        )
        metrics = page.evaluate(
            """async () => {
              await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
              const conversation = document.getElementById("memorial-conversation-region");
              const header = document.querySelector("header");
              const conversationRect = conversation.getBoundingClientRect();
              const headerRect = header.getBoundingClientRect();
              const guidance = document.getElementById("memorial-conversation-disclosure");
              const conversationButton = document.getElementById("memorial-conversation");
              const idleMonitor = document.getElementById("memorial-speech-monitor");
              const visible = (element) => Boolean(
                element &&
                element.getBoundingClientRect().width > 0 &&
                element.getBoundingClientRect().height > 0 &&
                getComputedStyle(element).display !== "none" &&
                getComputedStyle(element).visibility !== "hidden"
              );
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
                installCount: document.querySelectorAll("#memorial-install-hint").length,
                memoryRoomLinks: document.querySelectorAll("a[href*='/memory-room']").length,
                mainLabel: conversation.getAttribute("aria-label"),
                guidanceAlign: getComputedStyle(guidance).textAlign,
                guidanceWidth: guidance.getBoundingClientRect().width,
                chatWidth: document.querySelector(".chat").getBoundingClientRect().width,
                idleMonitorDisplay: getComputedStyle(idleMonitor).display,
                idleMonitorHeight: idleMonitor.getBoundingClientRect().height,
                conversationState: conversation.getAttribute("data-conversation-state"),
                conversationBusy: conversation.getAttribute("aria-busy"),
                buttonExpanded: conversationButton.getAttribute("aria-expanded"),
                buttonBusy: conversationButton.getAttribute("aria-busy"),
                disclosurePrecedesButton: Boolean(
                  guidance.compareDocumentPosition(conversationButton)
                  & Node.DOCUMENT_POSITION_FOLLOWING
                ),
                visibleButtons: [...document.querySelectorAll("button")]
                  .filter(visible)
                  .map((button) => (button.getAttribute("aria-label") || button.textContent || "").trim()),
                visibleInputs: [...document.querySelectorAll("input,textarea,select")]
                  .filter(visible)
                  .map((input) => input.id || input.name || input.tagName.toLowerCase()),
                visibleConversationInteractives: [
                  ...conversation.querySelectorAll(
                    "button,input,textarea,select,summary,a[href]"
                  )
                ].filter(visible).map((element) => element.id || element.tagName.toLowerCase()),
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
        assert metrics["installCount"] == 0
        assert metrics["memoryRoomLinks"] == 0
        assert str(metrics["mainLabel"]).startswith("KI-Gespräch über ")
        assert metrics["guidanceAlign"] == "center"
        assert float(metrics["guidanceWidth"]) <= float(metrics["chatWidth"])
        assert metrics["idleMonitorDisplay"] == "none"
        assert float(metrics["idleMonitorHeight"]) == 0
        assert metrics["conversationState"] == "ready"
        assert metrics["conversationBusy"] == "false"
        assert metrics["buttonExpanded"] == "false"
        assert metrics["buttonBusy"] == "false"
        assert metrics["disclosurePrecedesButton"] is True
        assert metrics["visibleButtons"] == ["Gespräch beginnen"]
        assert metrics["visibleInputs"] == []
        assert metrics["visibleConversationInteractives"] == [
            "memorial-conversation"
        ]
        assert page.evaluate("window.__getUserMediaCalls") == 0

        disclosure = page.locator("#memorial-conversation-disclosure")
        assert disclosure.is_visible()
        assert "KI" in disclosure.inner_text()
        assert page.get_by_text("Die Stimme ist künstlich erzeugt.", exact=False).is_visible()
        assert page.get_by_role("button", name="Gespräch beginnen").is_visible()
        assert websockets == []
        assert all(
            request.startswith(base_url)
            for request in requests
        )

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


def test_memorial_conversation_only_focus_and_reduced_motion_stay_minimal(
    browser: Browser,
    memorial_minimal_server: dict[str, object],
) -> None:
    base_url = str(memorial_minimal_server["base_url"])
    slug = str(memorial_minimal_server["slug"])
    context = browser.new_context(viewport={"width": 320, "height": 568})
    page: Page = context.new_page()
    try:
        page.emulate_media(reduced_motion="reduce")
        response = page.goto(
            f"{base_url}/memorials/{slug}",
            wait_until="domcontentloaded",
        )
        assert response is not None and response.ok
        button = page.get_by_role(
            "button",
            name="Gespräch beginnen",
            exact=True,
        )
        button.wait_for(state="visible", timeout=12000)
        button.focus()
        metrics = page.evaluate(
            """() => {
              const button = document.getElementById("memorial-conversation");
              button.dataset.conversationState = "listening";
              const style = getComputedStyle(button);
              const marker = getComputedStyle(button, "::before");
              const rect = button.getBoundingClientRect();
              return {
                focused: document.activeElement === button,
                outlineWidth: parseFloat(style.outlineWidth || "0"),
                transitionDuration: style.transitionDuration,
                markerAnimationName: marker.animationName,
                markerTransitionDuration: marker.transitionDuration,
                buttonBottom: rect.bottom,
                viewportHeight: window.innerHeight,
                scrollWidth: document.documentElement.scrollWidth,
                viewportWidth: window.innerWidth,
              };
            }"""
        )
        assert metrics["focused"] is True
        assert float(metrics["outlineWidth"]) >= 2
        assert metrics["transitionDuration"] == "0s"
        assert metrics["markerAnimationName"] == "none"
        assert metrics["markerTransitionDuration"] == "0s"
        assert float(metrics["buttonBottom"]) <= float(metrics["viewportHeight"])
        assert int(metrics["scrollWidth"]) <= int(metrics["viewportWidth"]) + 1
    finally:
        context.close()


def test_memorial_transient_voice_warmup_stays_preparing_until_ready(
    browser: Browser,
    memorial_minimal_server: dict[str, object],
) -> None:
    base_url = str(memorial_minimal_server["base_url"])
    slug = str(memorial_minimal_server["slug"])
    context = browser.new_context(viewport={"width": 390, "height": 844})
    _install_fake_audio_runtime(context, playback_delay_ms=10)
    context.add_init_script(
        """
        (() => {
          const realNow = Date.now.bind(Date);
          let memorialClockOffsetMs = 0;
          Date.now = () => realNow() + memorialClockOffsetMs;
          window.__advanceMemorialClock = (milliseconds) => {
            memorialClockOffsetMs += Math.max(0, Number(milliseconds) || 0);
          };
        })();
        """
    )
    page: Page = context.new_page()
    readiness_requests: list[str] = []
    warmup_requests: list[str] = []
    status_requests: list[str] = []
    voice_ready = {"value": False}

    def route_readiness(route) -> None:
        readiness_requests.append(route.request.url)
        route.fulfill(
            status=503,
            content_type="application/json",
            body=json.dumps(
                {
                    "slug": slug,
                    "ready": False,
                    "spoken_voice_ready": False,
                    "release": {
                        "enforced": True,
                        "allowed": False,
                        "public_evaluation": True,
                    },
                }
            ),
        )

    def route_warmup(route) -> None:
        warmup_requests.append(route.request.url)
        route.fulfill(
            status=202,
            content_type="application/json",
            body=json.dumps({"status": "warming"}),
        )

    def route_warmup_status(route) -> None:
        status_requests.append(route.request.url)
        ready = voice_ready["value"]
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "status": "warm" if ready else "warming",
                    "warm": ready,
                    "inflight": not ready,
                    "voice_required": True,
                    "voice_ready": ready,
                    "voice_prewarm_stale": not ready,
                    "readiness_ttl_remaining_seconds": 300 if ready else 0,
                    "operator_recheck_after_seconds": 1,
                    "errors": [],
                    "voice_errors": [],
                }
            ),
        )

    try:
        page.route(
            f"{base_url}/memorials/{slug}/readiness",
            route_readiness,
        )
        page.route(
            f"{base_url}/memorials/{slug}/warmup",
            route_warmup,
        )
        page.route(
            f"{base_url}/memorials/{slug}/warmup-status",
            route_warmup_status,
        )
        response = page.goto(
            f"{base_url}/memorials/{slug}",
            wait_until="domcontentloaded",
        )
        assert response is not None and response.ok
        page.wait_for_function(
            "() => window.__memorialMinimalBooted === true",
            timeout=3000,
        )
        page.get_by_role(
            "button",
            name="Gespräch beginnen",
            exact=True,
        ).click()
        for _ in range(10):
            if status_requests:
                break
            page.wait_for_timeout(100)
        assert status_requests
        assert readiness_requests == [
            f"{base_url}/memorials/{slug}/readiness"
        ]
        assert page.locator("#memorial-conversation").is_disabled()
        assert page.locator("#memorial-conversation").inner_text().strip() == (
            "Gespräch wird vorbereitet …"
        )

        page.evaluate("window.__advanceMemorialClock(46_000)")
        page.wait_for_timeout(2600)
        assert warmup_requests == [
            f"{base_url}/memorials/{slug}/warmup",
            f"{base_url}/memorials/{slug}/warmup",
        ]
        assert len(status_requests) >= 2
        assert page.evaluate("window.__getUserMediaCalls") == 0
        assert page.locator("button:visible").count() == 1
        assert page.locator("#memorial-conversation").is_disabled()
        assert page.locator("#memorial-conversation").get_attribute(
            "aria-busy"
        ) == "true"
        assert page.locator("#memorial-conversation").inner_text().strip() == (
            "Gespräch wird vorbereitet …"
        )
        assert page.locator("#memorial-conversation-region").get_attribute(
            "data-conversation-state"
        ) == "preparing"
        assert page.locator("#memorial-speech-message").inner_text() != (
            "Sprechen ist gerade nicht möglich."
        )

        voice_ready["value"] = True
        button = page.get_by_role(
            "button",
            name="Gespräch beginnen",
            exact=True,
        )
        button.wait_for(state="visible", timeout=5000)
        page.wait_for_function(
            "() => !document.getElementById('memorial-conversation').disabled",
            timeout=5000,
        )
        assert button.is_enabled()
        assert page.locator("#memorial-conversation-region").get_attribute(
            "data-conversation-state"
        ) == "ready"
        assert page.evaluate("window.__getUserMediaCalls") == 0
        assert warmup_requests == [
            f"{base_url}/memorials/{slug}/warmup",
            f"{base_url}/memorials/{slug}/warmup",
        ]
    finally:
        context.close()


def test_memorial_blocked_voice_release_fails_closed_without_requesting_microphone(
    browser: Browser,
    memorial_minimal_server: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials

    monkeypatch.setattr(public_memorials, "_memorial_voice_release_enforced", lambda: True)
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_release_decision",
        lambda slug: {
            "allowed": False,
            "status": "blocked",
            "reason": "release_human_acceptance_missing",
            "provider_work_allowed": True,
        },
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
        page.wait_for_timeout(500)
        assert page.locator("#memorial-conversation-region").get_attribute("data-voice-release") == "blocked"
        conversation = page.get_by_role("button", name="Gespräch beginnen", exact=True)
        assert conversation.is_visible()
        assert conversation.is_enabled()
        assert conversation.get_attribute("aria-label") == "Gespräch beginnen"
        assert conversation.get_attribute("title") == "Gespräch beginnen"
        assert page.locator("#memorial-text-turn-form").is_hidden()
        assert page.locator("#memorial-retry-button").is_hidden()
        assert page.locator("#memorial-voice-recovery-note").is_hidden()
        assert page.locator("#memorial-conversation-disclosure").get_by_text(
            "Sprechen ist derzeit nicht verfügbar", exact=False
        ).is_visible()
        assert page.evaluate("window.__getUserMediaCalls") == 0
        assert page.locator("button:visible").count() == 1
        assert page.locator("input:visible,textarea:visible,select:visible").count() == 0

        conversation.click()
        page.wait_for_function(
            """() => {
              const message = document.getElementById("memorial-speech-message");
              return Boolean(
                message
                && message.textContent.includes("Sprechen ist derzeit nicht verfügbar")
              );
            }""",
            timeout=3000,
        )
        assert page.evaluate("window.__getUserMediaCalls") == 0
        assert page.locator("button:visible").count() == 1
        assert page.locator("input:visible,textarea:visible,select:visible").count() == 0
        assert page.locator("#memorial-text-turn-form").is_hidden()
        assert page.locator("#memorial-retry-button").is_hidden()
        assert conversation.inner_text().strip() == "Gespräch beginnen"
    finally:
        context.close()


def test_memorial_public_evaluation_is_enabled_without_review_cookie_and_stays_minimal(
    browser: Browser,
    memorial_minimal_server: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials

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
            "public_evaluation": True,
            "status": "public_evaluation",
            "receipt_status": "public_evaluation_authorized",
            "access_mode": "owner-authorized-public-evaluation",
            "disclosure_required": True,
            "provider_work_allowed": True,
        },
    )
    base_url = str(memorial_minimal_server["base_url"])
    slug = str(memorial_minimal_server["slug"])
    context = browser.new_context(viewport={"width": 390, "height": 844})
    page: Page = context.new_page()
    try:
        response = page.goto(
            f"{base_url}/memorials/{slug}",
            wait_until="domcontentloaded",
        )
        assert response is not None and response.ok
        conversation = page.get_by_role(
            "button",
            name="Gespräch beginnen",
            exact=True,
        )
        conversation.wait_for(state="visible", timeout=12000)
        page.wait_for_function(
            "() => !document.getElementById('memorial-conversation').disabled",
            timeout=12000,
        )

        region = page.locator("#memorial-conversation-region")
        assert region.get_attribute("data-voice-release") == "blocked"
        assert region.get_attribute("data-voice-access") == "public-evaluation"
        assert region.get_attribute("data-evaluation-status") == "owner-authorized"
        assert page.locator("body").get_attribute("data-operator-voice-preview") is None
        assert page.locator("button:visible").count() == 1
        assert page.locator("input:visible,textarea:visible,select:visible").count() == 0
        assert conversation.get_attribute("aria-describedby") == (
            "memorial-conversation-disclosure"
        )
        assert page.locator("#memorial-conversation-disclosure").inner_text() == (
            "Öffentliche Testphase: Diese KI-Rekonstruktion antwortet aus einer "
            "aus freigegebenen Erinnerungen und Quellen abgeleiteten Ich-Perspektive. "
            "Sie ist nicht Manfred und spricht nicht für ihn. Die künstlich erzeugte "
            "Stimme wird noch beurteilt. Mikrofon und Audio werden erst nach "
            "„Gespräch beginnen“ verarbeitet."
        )
        assert all(
            cookie["name"] != "ea_manfred_voice_review"
            for cookie in context.cookies()
        )

        readiness = context.request.get(
            f"{base_url}/memorials/{slug}/readiness",
            headers={"Accept": "application/json"},
        )
        assert readiness.status == 200
        readiness_payload = readiness.json()
        assert readiness_payload["ready"] is True
        assert readiness_payload["spoken_voice_ready"] is True
        assert readiness_payload["release"] == {
            "enforced": True,
            "allowed": False,
            "public_evaluation": True,
            "access_mode": "owner-authorized-public-evaluation",
            "disclosure_required": True,
            "status": "public_evaluation",
            "reason": "",
            "receipt_status": "public_evaluation_authorized",
        }
    finally:
        context.close()


def test_memorial_public_evaluation_revocation_blocks_before_microphone_or_socket(
    browser: Browser,
    memorial_minimal_server: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials

    decision: dict[str, object] = {
        "allowed": False,
        "public_evaluation": True,
        "status": "public_evaluation",
        "receipt_status": "public_evaluation_authorized",
        "access_mode": "owner-authorized-public-evaluation",
        "disclosure_required": True,
        "provider_work_allowed": True,
    }
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_release_enforced",
        lambda: True,
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_release_decision",
        lambda _slug: dict(decision),
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
            throw new Error("revoked evaluation must not request microphone");
          };
        })();
        """
    )
    page: Page = context.new_page()
    websockets: list[str] = []
    page.on("websocket", lambda websocket: websockets.append(websocket.url))
    try:
        response = page.goto(
            f"{base_url}/memorials/{slug}",
            wait_until="domcontentloaded",
        )
        assert response is not None and response.ok
        conversation = page.get_by_role(
            "button",
            name="Gespräch beginnen",
            exact=True,
        )
        conversation.wait_for(state="visible", timeout=12000)
        page.wait_for_function(
            "() => !document.getElementById('memorial-conversation').disabled",
            timeout=12000,
        )

        decision.update(
            {
                "public_evaluation": False,
                "status": "blocked",
                "receipt_status": "",
                "access_mode": "",
                "disclosure_required": False,
            }
        )
        public_memorials._memorial_runtime_readiness_cache_invalidate(slug)
        conversation.click()
        page.wait_for_function(
            """() => document.getElementById("memorial-speech-message")
              ?.textContent.includes("Sprechen ist derzeit nicht verfügbar")""",
            timeout=7000,
        )

        assert page.evaluate("window.__getUserMediaCalls") == 0
        assert websockets == []
        assert page.locator("#memorial-speech-audio").get_attribute("src") in {
            None,
            "",
        }
        assert page.locator("button:visible").count() == 1
        assert page.locator("input:visible,textarea:visible,select:visible").count() == 0
        assert conversation.inner_text().strip() == "Gespräch beginnen"
        assert all(
            cookie["name"] != "ea_manfred_voice_review"
            for cookie in context.cookies()
        )
    finally:
        context.close()


def test_memorial_fresh_revocation_discards_preloaded_voice_before_playback(
    browser: Browser,
    memorial_minimal_server: dict[str, object],
) -> None:
    base_url = str(memorial_minimal_server["base_url"])
    slug = str(memorial_minimal_server["slug"])
    context = browser.new_context(viewport={"width": 390, "height": 844})
    _install_fake_audio_runtime(context)
    page: Page = context.new_page()
    revoked_readiness_requests: list[str] = []
    websockets: list[str] = []
    page.on("websocket", lambda websocket: websockets.append(websocket.url))
    try:
        response = page.goto(
            f"{base_url}/memorials/{slug}",
            wait_until="domcontentloaded",
        )
        assert response is not None and response.ok
        page.get_by_role(
            "button",
            name="Gespräch beginnen",
            exact=True,
        ).wait_for(state="visible", timeout=12000)
        page.get_by_role(
            "button",
            name="Gespräch beginnen",
            exact=True,
        ).click()
        page.wait_for_function(
            "() => Number(window.__memorialAudioPlayCalls || 0) >= 1",
            timeout=12000,
        )
        page.get_by_role(
            "button",
            name="Gespräch beenden",
            exact=True,
        ).click()
        page.get_by_role(
            "button",
            name="Gespräch beginnen",
            exact=True,
        ).wait_for(state="visible", timeout=7000)
        play_calls_before_revocation = page.evaluate(
            "window.__memorialAudioPlayCalls"
        )
        microphone_calls_before_revocation = page.evaluate(
            "window.__getUserMediaCalls"
        )
        websocket_count_before_revocation = len(websockets)

        def revoke_readiness(route) -> None:
            revoked_readiness_requests.append(route.request.url)
            route.fulfill(
                status=409,
                content_type="application/json",
                body=json.dumps(
                    {
                        "slug": slug,
                        "ready": False,
                        "spoken_voice_ready": False,
                        "release": {
                            "enforced": True,
                            "allowed": False,
                            "operator_preview": False,
                            "reason": "release_revoked",
                        },
                    }
                ),
            )

        page.route(
            f"{base_url}/memorials/{slug}/readiness",
            revoke_readiness,
        )
        page.get_by_role(
            "button",
            name="Gespräch beginnen",
            exact=True,
        ).click()
        page.wait_for_function(
            """() => document.getElementById("memorial-speech-message")
              ?.textContent.includes("Sprechen ist derzeit nicht verfügbar")""",
            timeout=7000,
        )

        assert revoked_readiness_requests
        assert (
            page.evaluate("window.__memorialAudioPlayCalls")
            == play_calls_before_revocation
        )
        assert (
            page.evaluate("window.__getUserMediaCalls")
            == microphone_calls_before_revocation
        )
        assert len(websockets) == websocket_count_before_revocation
        assert page.locator("#memorial-speech-audio").get_attribute("src") in {
            None,
            "",
        }
        assert page.locator("button:visible").count() == 1
        assert page.get_by_role(
            "button",
            name="Gespräch beginnen",
            exact=True,
        ).is_visible()
    finally:
        context.close()


def test_candidate_browser_audit_requires_single_blocked_action(
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
    assert evidence["visible_button_ids"] == ["memorial-conversation"]
    assert evidence["visible_button_labels"] == ["Gespräch beginnen"]
    assert evidence["visible_non_button_control_ids"] == []
    assert evidence["text_form_visible"] is False
    assert evidence["text_input_focused"] is False
    assert evidence["separate_retry_visible"] is False
    assert evidence["conversation_action_exercised"] is True
    for field in candidate_verify.BROWSER_ZERO_COUNT_FIELDS:
        assert evidence[field] == 0


@pytest.mark.parametrize(
    (
        "decision",
        "expected_voice_release",
        "expected_voice_access",
        "expected_evaluation_status",
    ),
    [
        (
            {
                "allowed": False,
                "public_evaluation": True,
                "status": "public_evaluation",
                "reason": "",
                "receipt_status": "public_evaluation_authorized",
                "access_mode": "owner-authorized-public-evaluation",
                "disclosure_required": True,
                "provider_work_allowed": True,
            },
            "blocked",
            "public-evaluation",
            "owner-authorized",
        ),
        (
            {
                "allowed": True,
                "public_evaluation": False,
                "status": "released",
                "reason": "",
                "receipt_status": "released",
                "access_mode": "public-release",
                "disclosure_required": True,
                "provider_work_allowed": True,
            },
            "available",
            "public-release",
            "",
        ),
    ],
    ids=("public-evaluation", "public-release"),
)
def test_authorized_live_candidate_browser_audit_is_passive(
    memorial_minimal_server: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    decision: dict[str, object],
    expected_voice_release: str,
    expected_voice_access: str,
    expected_evaluation_status: str,
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
        lambda _slug: dict(decision),
    )
    with urllib.request.urlopen(
        f"{memorial_minimal_server['base_url']}/memorials/manfred",
        timeout=5,
    ) as response:
        source_revision = str(
            response.headers.get("X-EA-Source-Revision") or ""
        ).strip()
    assert len(source_revision) == 40
    assert all(
        character in "0123456789abcdef"
        for character in source_revision
    )

    with ThreadPoolExecutor(max_workers=1) as executor:
        def _resolve_installed_chromium() -> str | None:
            with sync_playwright() as playwright:
                executable_path, _executable_source = (
                    _resolve_chromium_executable(playwright)
                )
            return executable_path

        executable_path = executor.submit(
            _resolve_installed_chromium
        ).result(timeout=10)
        assert executable_path is not None
        monkeypatch.setenv(
            "EA_PLAYWRIGHT_CHROMIUM_EXECUTABLE",
            executable_path,
        )
        evidence = executor.submit(
            candidate_verify.audit_browser_surface,
            str(memorial_minimal_server["base_url"]),
            public_origin="https://myexternalbrain.com",
            expected_voice_release=expected_voice_release,
            expected_voice_access=expected_voice_access,
            expected_evaluation_status=expected_evaluation_status,
            expected_source_revision=source_revision,
            exercise_conversation_action=False,
        ).result(timeout=30)

    assert evidence["status"] == "pass"
    assert evidence["conversation_action_exercised"] is False
    assert evidence["voice_release"] == expected_voice_release
    assert evidence["voice_access"] == expected_voice_access
    assert evidence["evaluation_status"] == expected_evaluation_status
    assert evidence["visible_button_ids"] == ["memorial-conversation"]
    assert evidence["visible_button_labels"] == ["Gespräch beginnen"]
    assert evidence["automatic_provider_requests"] == 0
    assert evidence["automatic_readiness_requests"] == 0
    assert evidence["automatic_microphone_requests"] == 0
    assert evidence["automatic_websockets"] == 0
    for field in candidate_verify.BROWSER_ZERO_COUNT_FIELDS:
        assert evidence[field] == 0


def test_provider_free_candidate_browser_click_performs_no_provider_work(
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
            "public_evaluation": True,
            "status": "public_evaluation",
            "reason": "",
            "receipt_status": "public_evaluation_authorized",
            "access_mode": "owner-authorized-public-evaluation",
            "disclosure_required": True,
            "provider_work_allowed": False,
        },
    )
    with urllib.request.urlopen(
        f"{memorial_minimal_server['base_url']}/memorials/manfred",
        timeout=5,
    ) as response:
        source_revision = str(
            response.headers.get("X-EA-Source-Revision") or ""
        ).strip()
    assert len(source_revision) == 40
    assert all(character in "0123456789abcdef" for character in source_revision)

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
            expected_voice_release="blocked",
            expected_voice_access="public-evaluation",
            expected_evaluation_status="owner-authorized",
            expected_source_revision=source_revision,
        ).result(timeout=30)

    assert evidence["status"] == "pass"
    assert evidence["memorial_surface"] == "conversation_only"
    assert evidence["voice_release"] == "blocked"
    assert evidence["voice_access"] == "public-evaluation"
    assert evidence["evaluation_status"] == "owner-authorized"
    assert evidence["visible_button_ids"] == ["memorial-conversation"]
    assert evidence["visible_button_labels"] == ["Gespräch beginnen"]
    assert evidence["visible_non_button_control_ids"] == []
    assert evidence["text_form_visible"] is False
    assert evidence["text_input_focused"] is False
    assert evidence["separate_retry_visible"] is False
    assert evidence["conversation_action_exercised"] is True
    for field in candidate_verify.BROWSER_ZERO_COUNT_FIELDS:
        assert evidence[field] == 0


def test_enforced_authorized_page_missing_provider_marker_fails_closed(
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
            "allowed": True,
            "public_evaluation": False,
            "status": "released",
            "reason": "",
        },
    )
    with urllib.request.urlopen(
        f"{memorial_minimal_server['base_url']}/memorials/manfred",
        timeout=5,
    ) as response:
        source_revision = str(
            response.headers.get("X-EA-Source-Revision") or ""
        ).strip()
    assert len(source_revision) == 40
    assert all(character in "0123456789abcdef" for character in source_revision)

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
            expected_voice_release="available",
            expected_voice_access="public-release",
            expected_source_revision=source_revision,
        ).result(timeout=30)

    assert evidence["status"] == "pass"
    assert evidence["visible_button_ids"] == ["memorial-conversation"]
    assert evidence["visible_button_labels"] == ["Gespräch beginnen"]
    for field in candidate_verify.BROWSER_ZERO_COUNT_FIELDS:
        assert evidence[field] == 0


def test_memorial_microphone_error_retries_with_same_single_button(
    browser: Browser,
    memorial_minimal_server: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorial_surface, public_memorials

    preview_session = {
        "slug": "manfred",
        "scopes": ["page", "readiness", "realtime"],
    }
    monkeypatch.setattr(
        public_memorial_surface,
        "_memorial_voice_review_http_session_payload",
        lambda *_args, **_kwargs: dict(preview_session),
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_review_http_session_payload",
        lambda *_args, **_kwargs: dict(preview_session),
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
            throw new DOMException("unexpected microphone request", "NotAllowedError");
          };
        })();
        """
    )
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/memorials/{slug}", wait_until="domcontentloaded")
        assert response is not None and response.ok
        start = page.get_by_role("button", name="Gespräch beginnen", exact=True)
        start.wait_for(state="visible", timeout=12000)
        start.click()
        page.wait_for_function(
            """() => {
              const message = document.getElementById("memorial-speech-message");
              return Boolean(
                message
                && message.textContent.includes("Mikrofonzugriff ist blockiert")
              );
            }""",
            timeout=7000,
        )
        assert page.evaluate("window.__getUserMediaCalls") == 1
        assert page.locator("#memorial-text-turn-form").is_hidden()
        assert page.locator("#memorial-retry-button").is_hidden()
        assert page.locator("button:visible").count() == 1
        assert page.locator("input:visible,textarea:visible,select:visible").count() == 0
        assert start.inner_text().strip() == "Gespräch beginnen"
        assert start.get_attribute("aria-label") == "Gespräch beginnen"
        assert start.get_attribute("title") == "Gespräch beginnen"

        start.click()
        page.wait_for_function(
            "() => Number(window.__getUserMediaCalls || 0) >= 2",
            timeout=7000,
        )
        assert page.locator("#memorial-text-turn-form").is_hidden()
        assert page.locator("#memorial-retry-button").is_hidden()
        assert page.locator("button:visible").count() == 1
        assert page.locator("input:visible,textarea:visible,select:visible").count() == 0
        assert start.inner_text().strip() == "Gespräch beginnen"
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
        assert page.evaluate("window.__getUserMediaCalls") == 0
        assert page.locator("button:visible").count() == 1
        assert page.locator("#memorial-conversation").get_attribute(
            "aria-expanded"
        ) == "false"
        page.evaluate(
            """() => {
              const region = document.getElementById("memorial-conversation-region");
              window.__memorialConversationStates = [
                String(region.dataset.conversationState || "")
              ];
              new MutationObserver(() => {
                const state = String(region.dataset.conversationState || "");
                const states = window.__memorialConversationStates;
                if (state && states[states.length - 1] !== state) states.push(state);
              }).observe(region, {
                attributes: true,
                attributeFilter: ["data-conversation-state"]
              });
            }"""
        )
        turn = _await_realtime_turn_complete(
            page,
            slug,
            lambda: page.get_by_role("button", name="Gespräch beginnen", exact=True).click(),
            timeout_ms=12000,
        )
        assert page.evaluate("window.__getUserMediaCalls") >= 1
        assert " ich " in f" {str(turn['answer']).casefold()} "
        assert turn["audio_seen"] is True
        disclosure = page.locator("#memorial-conversation-disclosure")
        assert disclosure.is_visible()
        assert "KI-Rekonstruktion" in (disclosure.text_content() or "")
        assert "ist nicht Manfred" in (disclosure.text_content() or "")
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
        page.wait_for_function(
            "() => Number(window.__memorialAudioPlayCalls || 0) >= 1",
            timeout=7000,
        )
        page.wait_for_function(
            "() => Number(window.__memorialAudioEndedEvents || 0) >= 1",
            timeout=7000,
        )
        states = page.evaluate(
            "() => window.__memorialConversationStates.slice()"
        )
        state_cursor = -1
        for expected_state in (
            "preparing",
            "listening",
            "working",
            "speaking",
            "listening",
        ):
            state_cursor = states.index(expected_state, state_cursor + 1)
        assert page.locator("#memorial-conversation").get_attribute(
            "aria-expanded"
        ) == "true"
        assert page.evaluate(
            "document.activeElement && document.activeElement.id"
        ) == "memorial-conversation"
        page.locator("#memorial-conversation").click()
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
        turns = page.locator("#memorial-speech-transcript > .speech-turn")
        assert turns.count() >= 2
        assert turns.nth(0).get_attribute("class") == "speech-turn user"
        assert turns.nth(1).get_attribute("class") == "speech-turn assistant"
        assert turns.nth(0).locator("strong").text_content() == "Du"
        assert turns.nth(1).locator("strong").text_content() == "KI-Begleiter"
        assert "ich " in (turns.nth(1).text_content() or "").casefold()
        assert page.evaluate("window.__memorialAudioPlayCalls") >= 1
        assert page.evaluate("window.__memorialAudioEndedEvents") >= 1
        assert page.locator("#memorial-speech-transcript-live").is_hidden()
        assert page.locator("#memorial-chat-answer").is_hidden()
        assert page.locator("#memorial-conversation-region").get_attribute(
            "data-conversation-state"
        ) == "ready"
    finally:
        context.close()


def test_memorial_conversation_start_is_single_flight(
    browser: Browser,
    memorial_minimal_server: dict[str, object],
) -> None:
    base_url = str(memorial_minimal_server["base_url"])
    slug = str(memorial_minimal_server["slug"])
    context = browser.new_context(viewport={"width": 390, "height": 844})
    _install_fake_audio_runtime(context, playback_delay_ms=10)
    page: Page = context.new_page()
    try:
        response = page.goto(
            f"{base_url}/memorials/{slug}",
            wait_until="domcontentloaded",
        )
        assert response is not None and response.ok
        page.get_by_role(
            "button",
            name="Gespräch beginnen",
            exact=True,
        ).wait_for(state="visible", timeout=12000)
        page.evaluate(
            """() => {
              window.__memorialStartConversation();
              window.__memorialStartConversation();
            }"""
        )
        page.wait_for_function(
            "() => Number(window.__memorialMediaRecorderStarts || 0) === 1",
            timeout=12000,
        )
        page.wait_for_timeout(100)
        assert page.evaluate("window.__getUserMediaCalls") == 1
        assert page.evaluate("window.__memorialMediaRecorderStarts") == 1
        assert page.locator("#memorial-conversation").get_attribute(
            "aria-expanded"
        ) == "true"
        assert page.locator("#memorial-conversation").get_attribute(
            "aria-busy"
        ) == "false"
        assert page.locator("button:visible").count() == 1

        page.get_by_role(
            "button",
            name="Gespräch beenden",
            exact=True,
        ).click()
        page.get_by_role(
            "button",
            name="Gespräch beginnen",
            exact=True,
        ).wait_for(state="visible", timeout=7000)
        assert page.evaluate("window.__memorialMediaTrackStopCalls") >= 1
    finally:
        context.close()


def test_memorial_stale_recorder_stop_cannot_break_clean_restart(
    browser: Browser,
    memorial_minimal_server: dict[str, object],
) -> None:
    base_url = str(memorial_minimal_server["base_url"])
    slug = str(memorial_minimal_server["slug"])
    context = browser.new_context(viewport={"width": 390, "height": 844})
    _install_fake_audio_runtime(
        context,
        playback_delay_ms=1100,
        recorder_event_delay_ms=450,
    )
    page: Page = context.new_page()
    try:
        response = page.goto(
            f"{base_url}/memorials/{slug}",
            wait_until="domcontentloaded",
        )
        assert response is not None and response.ok
        _install_fake_memorial_websocket(page)
        start = page.get_by_role(
            "button",
            name="Gespräch beginnen",
            exact=True,
        )
        start.wait_for(state="visible", timeout=12000)
        start.click()
        page.wait_for_function(
            "() => Number(window.__memorialMediaRecorderStarts || 0) === 1",
            timeout=12000,
        )
        page.get_by_role(
            "button",
            name="Gespräch beenden",
            exact=True,
        ).click()
        start.wait_for(state="visible", timeout=7000)
        start.click()
        page.wait_for_function(
            "() => Number(window.__memorialMediaRecorderStarts || 0) === 2",
            timeout=12000,
        )
        page.evaluate("window.__memorialRealtimeFrames = []")
        turn = _await_realtime_turn_complete(
            page,
            slug,
            lambda: None,
            timeout_ms=12000,
        )
        assert turn["done"] is True
        assert turn["audio_seen"] is True
        assert " ich " in f" {str(turn['answer']).casefold()} "
        assert page.locator(
            "#memorial-speech-transcript > .speech-turn.assistant"
        ).count() >= 1

        page.evaluate(
            """() => {
              const button = document.getElementById("memorial-conversation");
              if (button && button.textContent.includes("Gespräch beenden")) {
                button.click();
              }
            }"""
        )
        start.wait_for(state="visible", timeout=7000)
        assert page.evaluate("window.__memorialMediaTrackStopCalls") >= 2
        assert page.locator("button:visible").count() == 1
    finally:
        context.close()


def test_memorial_stop_cancels_socket_turn_without_http_fallback_or_playback(
    browser: Browser,
    memorial_minimal_server: dict[str, object],
) -> None:
    base_url = str(memorial_minimal_server["base_url"])
    slug = str(memorial_minimal_server["slug"])
    context = browser.new_context(viewport={"width": 390, "height": 844})
    _install_fake_audio_runtime(context, playback_delay_ms=10)
    page: Page = context.new_page()
    http_turn_requests: list[str] = []
    speech_requests: list[str] = []

    def unexpected_http_turn(route) -> None:
        http_turn_requests.append(route.request.url)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "answer": "Ich sollte nach dem Stoppen nicht mehr antworten.",
                    "audio_base64": base64.b64encode(b"unexpected").decode(
                        "ascii"
                    ),
                    "audio_content_type": "audio/wav",
                }
            ),
        )

    try:
        page.route(
            f"{base_url}/memorials/{slug}/conversation-turn",
            unexpected_http_turn,
        )
        response = page.goto(
            f"{base_url}/memorials/{slug}",
            wait_until="domcontentloaded",
        )
        assert response is not None and response.ok
        _install_fake_memorial_websocket(page, response_delay_ms=800)
        page.get_by_role(
            "button",
            name="Gespräch beginnen",
            exact=True,
        ).click()
        page.wait_for_function(
            "() => Number(window.__memorialFakeSocketTurnEnds || 0) === 1",
            timeout=12000,
        )
        playback_calls_before_stop = page.evaluate(
            "window.__memorialAudioPlayCalls"
        )
        page.get_by_role(
            "button",
            name="Gespräch beenden",
            exact=True,
        ).click()
        page.get_by_role(
            "button",
            name="Gespräch beginnen",
            exact=True,
        ).wait_for(state="visible", timeout=7000)
        page.wait_for_timeout(1000)

        assert page.evaluate("window.__memorialFakeSocketCancels") == 1
        assert page.evaluate("window.__memorialFakeSocketCloses") == 1
        assert http_turn_requests == []
        assert (
            page.evaluate("window.__memorialAudioPlayCalls")
            == playback_calls_before_stop
        )
        assert page.locator(
            "#memorial-speech-transcript > .speech-turn.assistant"
        ).count() == 0
        assert page.locator("#memorial-conversation-region").get_attribute(
            "data-conversation-state"
        ) == "ready"
    finally:
        context.close()


def test_memorial_socket_close_before_provider_admission_uses_http_fallback_once(
    browser: Browser,
    memorial_minimal_server: dict[str, object],
) -> None:
    base_url = str(memorial_minimal_server["base_url"])
    slug = str(memorial_minimal_server["slug"])
    context = browser.new_context(viewport={"width": 390, "height": 844})
    _install_fake_audio_runtime(context, playback_delay_ms=10)
    page: Page = context.new_page()
    http_turn_requests: list[str] = []
    speech_requests: list[str] = []
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    def route_http_turn(route) -> None:
        http_turn_requests.append(route.request.url)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "transcript_text": "Erzähl mir etwas über deine Familie.",
                    "transcript_effective_text": (
                        "Erzähl mir etwas über deine Familie."
                    ),
                    "answer": (
                        "Ich habe Familie immer als Verantwortung verstanden."
                    ),
                    "sources": ["Freigegebene Erinnerung"],
                    "llm_model": "memorial-http-fallback-test",
                    "audio_base64": base64.b64encode(
                        b"fake-http-fallback-audio"
                    ).decode("ascii"),
                    "audio_content_type": "audio/wav",
                }
            ),
        )

    def route_speech_transcribe(route) -> None:
        speech_requests.append(route.request.url)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "transcription_status": "transcribed",
                    "transcript_text": (
                        "Erzähl mir etwas über deine Familie."
                    ),
                }
            ),
        )

    try:
        page.route(
            f"{base_url}/memorials/{slug}/speech-transcribe",
            route_speech_transcribe,
        )
        page.route(
            f"{base_url}/memorials/{slug}/conversation-turn",
            route_http_turn,
        )
        response = page.goto(
            f"{base_url}/memorials/{slug}",
            wait_until="domcontentloaded",
        )
        assert response is not None and response.ok
        _install_fake_memorial_websocket(
            page,
            close_before_admission=True,
        )
        page.get_by_role(
            "button",
            name="Gespräch beginnen",
            exact=True,
        ).click()
        page.wait_for_function(
            """() => (
              Number(window.__memorialFakeSocketTurnEnds || 0) === 1
              && Number(window.__memorialAudioPlayCalls || 0) >= 1
              && document.querySelectorAll(
                "#memorial-speech-transcript > .speech-turn.assistant"
              ).length >= 1
            )""",
            timeout=12000,
        )
        page.evaluate(
            """() => {
              const button = document.getElementById("memorial-conversation");
              if (button && button.textContent.includes("Gespräch beenden")) {
                button.click();
              }
            }"""
        )

        assert http_turn_requests == [
            f"{base_url}/memorials/{slug}/conversation-turn"
        ]
        assert speech_requests == [
            f"{base_url}/memorials/{slug}/speech-transcribe"
        ]
        assert page.evaluate("window.__memorialFakeSocketCloses") == 1
        assert page_errors == []
        assert "Ich habe Familie" in (
            page.locator(
                "#memorial-speech-transcript > .speech-turn.assistant"
            ).last.inner_text()
            or ""
        )
    finally:
        context.close()


def test_memorial_early_stop_observes_pending_socket_turn_rejection(
    browser: Browser,
    memorial_minimal_server: dict[str, object],
) -> None:
    base_url = str(memorial_minimal_server["base_url"])
    slug = str(memorial_minimal_server["slug"])
    context = browser.new_context(viewport={"width": 390, "height": 844})
    _install_fake_audio_runtime(
        context,
        playback_delay_ms=10,
        blob_array_buffer_delay_ms=900,
    )
    context.add_init_script(
        """
        (() => {
          window.__memorialUnhandledRejections = 0;
          window.addEventListener("unhandledrejection", () => {
            window.__memorialUnhandledRejections += 1;
          });
        })();
        """
    )
    page: Page = context.new_page()
    http_turn_requests: list[str] = []

    def unexpected_http_turn(route) -> None:
        http_turn_requests.append(route.request.url)
        route.abort()

    try:
        page.route(
            f"{base_url}/memorials/{slug}/conversation-turn",
            unexpected_http_turn,
        )
        response = page.goto(
            f"{base_url}/memorials/{slug}",
            wait_until="domcontentloaded",
        )
        assert response is not None and response.ok
        _install_fake_memorial_websocket(page)
        page.get_by_role(
            "button",
            name="Gespräch beginnen",
            exact=True,
        ).click()
        page.wait_for_function(
            "() => Number(window.__memorialFakeSocketStarts || 0) === 1",
            timeout=12000,
        )
        assert page.evaluate("window.__memorialFakeSocketTurnEnds") == 0
        page.get_by_role(
            "button",
            name="Gespräch beenden",
            exact=True,
        ).click()
        page.get_by_role(
            "button",
            name="Gespräch beginnen",
            exact=True,
        ).wait_for(state="visible", timeout=7000)
        page.wait_for_timeout(1200)

        assert page.evaluate("window.__memorialFakeSocketCancels") == 1
        assert page.evaluate("window.__memorialFakeSocketCloses") == 1
        assert page.evaluate("window.__memorialFakeSocketTurnEnds") == 0
        assert page.evaluate("window.__memorialUnhandledRejections") == 0
        assert http_turn_requests == []
        assert page.locator("#memorial-conversation-region").get_attribute(
            "data-conversation-state"
        ) == "ready"
    finally:
        context.close()


def test_memorial_socket_close_after_provider_admission_never_duplicates_http_work(
    browser: Browser,
    memorial_minimal_server: dict[str, object],
) -> None:
    base_url = str(memorial_minimal_server["base_url"])
    slug = str(memorial_minimal_server["slug"])
    context = browser.new_context(viewport={"width": 390, "height": 844})
    _install_fake_audio_runtime(context, playback_delay_ms=10)
    page: Page = context.new_page()
    http_provider_requests: list[str] = []
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    def unexpected_http_provider_work(route) -> None:
        http_provider_requests.append(route.request.url)
        route.abort()

    try:
        page.route(
            f"{base_url}/memorials/{slug}/speech-transcribe",
            unexpected_http_provider_work,
        )
        page.route(
            f"{base_url}/memorials/{slug}/conversation-turn",
            unexpected_http_provider_work,
        )
        response = page.goto(
            f"{base_url}/memorials/{slug}",
            wait_until="domcontentloaded",
        )
        assert response is not None and response.ok
        _install_fake_memorial_websocket(
            page,
            close_after_admission=True,
        )
        page.get_by_role(
            "button",
            name="Gespräch beginnen",
            exact=True,
        ).click()
        page.wait_for_function(
            """() => (
              Number(window.__memorialFakeSocketTurnEnds || 0) === 1
              && document.getElementById("memorial-conversation-region")
                ?.dataset.conversationState === "error"
              && document.getElementById("memorial-conversation")
                ?.textContent.trim() === "Gespräch beginnen"
            )""",
            timeout=12000,
        )

        assert page.evaluate("window.__memorialFakeSocketCloses") == 1
        assert http_provider_requests == []
        assert page_errors == []
        assert page.locator("button:visible").count() == 1
        assert page.locator("#memorial-speech-message").inner_text() == (
            "Bitte noch einmal sprechen."
        )
    finally:
        context.close()


def test_memorial_missing_turn_audio_stops_in_single_button_retry_state(
    browser: Browser,
    memorial_minimal_server: dict[str, object],
) -> None:
    base_url = str(memorial_minimal_server["base_url"])
    slug = str(memorial_minimal_server["slug"])
    context = browser.new_context(viewport={"width": 390, "height": 844})
    _install_fake_audio_runtime(context, playback_delay_ms=10)
    page: Page = context.new_page()
    speech_requests: list[str] = []
    turn_requests: list[str] = []

    def route_memorial_turn(route) -> None:
        if route.request.url.endswith("/speech-transcribe"):
            speech_requests.append(route.request.url)
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "transcription_status": "transcribed",
                        "transcript_text": (
                            "Erzähl mir bitte etwas über deine Familie."
                        ),
                    }
                ),
            )
            return
        turn_requests.append(route.request.url)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "answer": (
                        "Ich habe Familie immer als Verantwortung verstanden."
                    ),
                    "sources": ["Freigegebene Erinnerung"],
                    "audio_base64": "",
                    "audio_content_type": "audio/wav",
                }
            ),
        )

    try:
        page.route(
            f"{base_url}/memorials/{slug}/speech-transcribe",
            route_memorial_turn,
        )
        page.route(
            f"{base_url}/memorials/{slug}/conversation-turn",
            route_memorial_turn,
        )
        response = page.goto(
            f"{base_url}/memorials/{slug}",
            wait_until="domcontentloaded",
        )
        assert response is not None and response.ok
        page.evaluate(
            """() => {
              class BrokenWebSocket {
                constructor() {
                  throw new Error("test_realtime_unavailable");
                }
              }
              BrokenWebSocket.CONNECTING = 0;
              BrokenWebSocket.OPEN = 1;
              BrokenWebSocket.CLOSING = 2;
              BrokenWebSocket.CLOSED = 3;
              window.WebSocket = BrokenWebSocket;
            }"""
        )
        page.get_by_role(
            "button",
            name="Gespräch beginnen",
            exact=True,
        ).click()
        page.wait_for_function(
            """() => (
              document.getElementById("memorial-conversation-region")
                ?.dataset.conversationState === "error"
              && document.getElementById("memorial-conversation")
                ?.textContent.trim() === "Gespräch beginnen"
            )""",
            timeout=12000,
        )
        assert len(speech_requests) == 1
        assert len(turn_requests) == 1
        assert page.evaluate("window.__memorialMediaRecorderStarts") == 1
        page.wait_for_timeout(900)
        assert page.evaluate("window.__memorialMediaRecorderStarts") == 1
        assert page.locator("button:visible").count() == 1
        assert page.locator("#memorial-retry-button").is_hidden()
        assert page.locator("#memorial-speech-message").inner_text() == (
            "Die Stimme ist gerade nicht verfügbar."
        )
        assistant = page.locator(
            "#memorial-speech-transcript > .speech-turn.assistant"
        )
        assert assistant.count() == 1
        assert "Ich habe Familie" in (assistant.inner_text() or "")
    finally:
        context.close()


@pytest.mark.skipif(not _HAS_WEBSOCKET_PROTOCOL, reason="uvicorn websocket protocol support requires websockets or wsproto")
def test_memorial_active_tts_can_be_interrupted_without_claiming_physical_audibility(
    browser: Browser,
    memorial_minimal_server: dict[str, object],
) -> None:
    base_url = str(memorial_minimal_server["base_url"])
    slug = str(memorial_minimal_server["slug"])
    context = browser.new_context(viewport={"width": 430, "height": 932})
    _install_fake_audio_runtime(context, playback_delay_ms=30000)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/memorials/{slug}", wait_until="domcontentloaded")
        assert response is not None and response.ok
        start = page.get_by_role("button", name="Gespräch beginnen", exact=True)
        start.wait_for(state="visible", timeout=12000)
        start.click()
        page.wait_for_function(
            "() => Number(window.__memorialAudioPlayCalls || 0) >= 1",
            timeout=12000,
        )
        assert page.evaluate("window.__memorialAudioEndedEvents") == 0

        page.locator("#memorial-conversation").click()
        page.get_by_role("button", name="Gespräch beginnen", exact=True).wait_for(
            state="visible",
            timeout=7000,
        )
        assert page.evaluate("window.__memorialAudioPauseCalls") >= 1
        assert page.evaluate("window.__memorialAudioEndedEvents") == 0
        assert page.evaluate("window.__memorialMediaTrackStopCalls") >= 1
        assistant_turns = page.locator(
            "#memorial-speech-transcript > .speech-turn.assistant"
        )
        assert assistant_turns.count() >= 1
        assert assistant_turns.first.is_visible()
        assert page.locator("button:visible").count() == 1
        # These counters prove browser events only; room audibility remains a human-only gate.
    finally:
        context.close()


@pytest.mark.skipif(not _HAS_WEBSOCKET_PROTOCOL, reason="uvicorn websocket protocol support requires websockets or wsproto")
def test_memorial_minimal_browser_voice_exit_gate_roundtrips_tts_to_stt(
    browser: Browser,
    memorial_minimal_server: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials

    # This test owns the in-browser audio roundtrip. TLS/proxy admission is
    # covered separately and cannot be represented by this loopback HTTP server.
    monkeypatch.setattr(
        public_memorials,
        "_memorial_realtime_websocket_transport_allowed",
        lambda _websocket: True,
    )
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
            "Ich höre dir zu. Worum geht es?",
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
