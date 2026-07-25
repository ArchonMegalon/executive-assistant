from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
import urllib.parse
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
from tests.browser_test_support import (  # noqa: E402
    BrowserRuntimeRoot,
    browser_ephemeral_runtime_root,
    launch_installed_chromium,
)


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
MEMORIAL_NAVIGATION_TIMEOUT_MS = 30_000
MEMORIAL_CONTRIBUTION_STATUS_TIMEOUT_MS = 7_000


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
def memorial_browser_runtime_root(
    tmp_path: Path,
) -> Iterator[BrowserRuntimeRoot]:
    with browser_ephemeral_runtime_root(tmp_path) as runtime:
        yield runtime


@pytest.fixture()
def memorial_browser_server(
    memorial_browser_runtime_root: BrowserRuntimeRoot,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[dict[str, object]]:
    from app.api.routes import public_memorials
    from app.services import memorial_archive_registry

    runtime_tmp = memorial_browser_runtime_root.path

    monkeypatch.setenv("EA_STORAGE_BACKEND", "memory")
    monkeypatch.setenv("EA_API_TOKEN", "")
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("GOOGLE_API_KEY_FALLBACK_1", "playwright-gemini-live-key")
    monkeypatch.delenv("EA_LEDGER_BACKEND", raising=False)
    monkeypatch.delenv("EA_DEFAULT_PRINCIPAL_ID", raising=False)
    monkeypatch.delenv("EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER", raising=False)
    monkeypatch.delenv("EA_OPERATOR_PRINCIPAL_IDS", raising=False)

    slug = "manfred"
    public_root = runtime_tmp / "public"
    private_root = runtime_tmp / "private"
    artifacts_root = runtime_tmp / "artifacts"
    registry_root = runtime_tmp / "public_registry"

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
    monkeypatch.setattr(
        public_memorials,
        "_PERSONAL_MEMORY_ROOT",
        artifacts_root / "memorial_user_memory",
    )
    monkeypatch.setattr(
        public_memorials,
        "_VOICE_AB_ROOT",
        artifacts_root / "memorial_voice_ab",
    )
    monkeypatch.setattr(
        public_memorials,
        "_PUBLIC_MEMORIAL_RATE_DB",
        artifacts_root / "memorial_rate_limits.sqlite3",
    )
    monkeypatch.setattr(memorial_archive_registry, "PUBLIC_MEMORIAL_ROOT", registry_root)
    monkeypatch.setattr(memorial_archive_registry, "ARCHIVE_ROOT", runtime_tmp / "archive")

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
    config = Config(
        app=app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        timeout_graceful_shutdown=2,
    )
    server = Server(config)
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
    thread = threading.Thread(
        target=server.run,
        name=f"memorial-browser-uvicorn-{port}",
        daemon=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    thread_started = False
    try:
        thread.start()
        thread_started = True
        _wait_for_http(base_url)
        yield {"base_url": base_url, "slug": slug}
    finally:
        try:
            server.should_exit = True
            if thread_started:
                thread.join(timeout=10.0)
                if thread.is_alive():
                    server.force_exit = True
                    thread.join(timeout=5.0)
                if thread.is_alive():
                    memorial_browser_runtime_root.retain = True
                    pytest.fail(
                        "memorial browser Uvicorn thread did not stop; "
                        "runtime root retained for diagnostics "
                        f"at {memorial_browser_runtime_root.path}: {thread.name}",
                        pytrace=False,
                    )
        finally:
            public_memorials._memorial_runtime_readiness_cache_invalidate(slug)


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
          window.__memorialGetUserMediaCalls = 0;
          window.__memorialTrackStopCalls = 0;
          navigator.mediaDevices.getUserMedia = async () => {
            window.__memorialGetUserMediaCalls += 1;
            return {
              getTracks() {
                return [{
                  stop() {
                    window.__memorialTrackStopCalls += 1;
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


def _assert_minimal_memorial_single_button(page: Page, label: str) -> None:
    conversation = page.locator("#memorial-conversation")
    assert conversation.is_visible()
    assert conversation.inner_text().strip() == label
    assert conversation.get_attribute("aria-label") == label
    assert conversation.get_attribute("title") == label
    assert page.locator("button:visible").count() == 1
    assert page.locator("button:visible").get_attribute("id") == "memorial-conversation"
    assert page.locator("input:visible, textarea:visible, select:visible").count() == 0
    for selector in (
        "#memorial-text-turn-form",
        "details.conversation-settings",
        "#memorial-retry-button",
        "#memorial-chat-tools",
        "#memorial-chat-status",
        "#memorial-read-answer",
        "#memorial-replay-answer",
        "#memorial-toggle-status",
        "#memorial-voice-recovery-note",
        "#memorial-install-hint",
    ):
        assert page.locator(selector).is_hidden(), selector
    assert page.locator("#memorial-contribution").count() == 0
    assert page.locator("#memorial-contribution-management").count() == 0


def test_memorial_private_review_cookie_reaches_readiness_from_same_origin_browser_get_only(
    browser: Browser,
    memorial_browser_server: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials

    base_url = str(memorial_browser_server["base_url"])
    slug = str(memorial_browser_server["slug"])
    configured_origin = base_url.replace("http://", "https://", 1)
    review_token = "browser-review-session-token"
    monkeypatch.setenv(
        "EA_PUBLIC_APP_BASE_URL",
        configured_origin,
    )

    def _session_payload(
        candidate: object,
        *,
        expected_kind: str,
        required_scope: str,
        now: int | None = None,
    ) -> dict[str, object] | None:
        del now
        if (
            candidate != review_token
            or expected_kind != "session"
            or required_scope != "readiness"
        ):
            return None
        return {
            "kind": "session",
            "expires_at": 2_000_000_000,
            "scopes": ["readiness"],
        }

    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_review_token_payload",
        _session_payload,
    )
    monkeypatch.setattr(
        public_memorials,
        "_require_voice_consent",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_runtime_readiness",
        lambda requested_slug, **kwargs: {
            "slug": requested_slug,
            "ready": True,
            "operator_preview": bool(
                kwargs.get("operator_preview_allowed")
            ),
        },
    )

    context = browser.new_context(
        extra_http_headers={"X-Forwarded-Proto": "https"},
    )
    page = context.new_page()
    readiness_request_headers: dict[str, str] = {}

    def _capture_readiness_request(request) -> None:
        if request.url.endswith(f"/memorials/{slug}/readiness"):
            readiness_request_headers.update(request.all_headers())

    page.on("request", _capture_readiness_request)
    try:
        response = page.goto(
            f"{base_url}/memorials/{slug}",
            wait_until="domcontentloaded",
            timeout=MEMORIAL_NAVIGATION_TIMEOUT_MS,
        )
        assert response is not None and response.ok
        context.add_cookies(
            [
                {
                    "name": "ea_manfred_voice_review",
                    "value": review_token,
                    "url": f"{base_url}/memorials/{slug}",
                }
            ]
        )

        same_origin = page.evaluate(
            """async (currentSlug) => {
              const response = await fetch(`/memorials/${currentSlug}/readiness`, {
                method: "GET",
                credentials: "same-origin",
                mode: "same-origin",
                cache: "no-store",
                redirect: "error",
                headers: {
                  "Accept": "application/json",
                  "Cache-Control": "no-store",
                },
              });
              return {status: response.status, payload: await response.json()};
            }""",
            slug,
        )
        assert same_origin["status"] == 200
        assert same_origin["payload"]["operator_preview"] is True
        assert "origin" not in readiness_request_headers
        assert (
            readiness_request_headers.get("sec-fetch-site")
            == "same-origin"
        )
        assert (
            readiness_request_headers.get("sec-fetch-mode")
            == "same-origin"
        )
        assert readiness_request_headers.get("sec-fetch-dest") == "empty"

        cross_site = context.request.get(
            f"{base_url}/memorials/{slug}/readiness",
            headers={
                "Accept": "application/json",
                "Sec-Fetch-Site": "cross-site",
                "Sec-Fetch-Mode": "same-origin",
                "Sec-Fetch-Dest": "empty",
            },
        )
        assert cross_site.status == 403
        assert (
            cross_site.json()["detail"]
            == "memorial_voice_review_origin_rejected"
        )
    finally:
        context.close()


def test_memorial_private_review_navigation_is_document_initiated_same_origin(
    browser: Browser,
    memorial_browser_server: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url = str(memorial_browser_server["base_url"])
    slug = str(memorial_browser_server["slug"])
    configured_origin = base_url.replace("http://", "https://", 1)
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", configured_origin)
    prime_url = (
        f"{base_url}/admin/memorials/manfred/voice-review"
    )
    memorial_url = f"{base_url}/memorials/{slug}"
    parsed_base = urllib.parse.urlsplit(base_url)
    request_headers: dict[str, dict[str, str]] = {}

    context = browser.new_context(
        extra_http_headers={"X-Forwarded-Proto": "https"},
    )
    page = context.new_page()

    def _capture_navigation(request) -> None:
        if request.is_navigation_request() and request.url in {
            prime_url,
            memorial_url,
        }:
            request_headers[request.url] = request.all_headers()

    page.on("request", _capture_navigation)
    try:
        prime_response = page.goto(
            prime_url,
            wait_until="domcontentloaded",
            timeout=MEMORIAL_NAVIGATION_TIMEOUT_MS,
        )
        assert prime_response is not None and prime_response.ok
        context.add_cookies(
            [
                {
                    "name": "ea_manfred_voice_review",
                    "value": "browser-review-session-token",
                    "domain": str(parsed_base.hostname or ""),
                    "path": f"/memorials/{slug}",
                    "secure": False,
                    "httpOnly": True,
                    "sameSite": "Strict",
                }
            ]
        )
        with page.expect_navigation(
            wait_until="domcontentloaded",
            timeout=MEMORIAL_NAVIGATION_TIMEOUT_MS,
        ) as navigation:
            page.evaluate(
                "(targetUrl) => window.location.replace(targetUrl)",
                memorial_url,
            )
        memorial_response = navigation.value
        assert memorial_response is not None and memorial_response.ok

        prime_headers = request_headers[prime_url]
        assert prime_headers.get("sec-fetch-site") == "none"
        assert prime_headers.get("sec-fetch-mode") == "navigate"
        assert prime_headers.get("sec-fetch-dest") == "document"
        assert "ea_manfred_voice_review" not in prime_headers.get(
            "cookie",
            "",
        )

        memorial_headers = request_headers[memorial_url]
        assert memorial_headers.get("sec-fetch-site") == "same-origin"
        assert memorial_headers.get("sec-fetch-mode") == "navigate"
        assert memorial_headers.get("sec-fetch-dest") == "document"
        assert "ea_manfred_voice_review=" in memorial_headers.get(
            "cookie",
            "",
        )
    finally:
        context.close()


def test_memorial_public_page_is_conversation_only_accessible_and_private_by_default(
    browser: Browser,
    memorial_browser_server: dict[str, object],
) -> None:
    base_url = str(memorial_browser_server["base_url"])
    slug = str(memorial_browser_server["slug"])
    context = browser.new_context(viewport={"width": 1440, "height": 1100})
    page: Page = context.new_page()
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    try:
        response = page.goto(f"{base_url}/memorials/{slug}", wait_until="domcontentloaded", timeout=MEMORIAL_NAVIGATION_TIMEOUT_MS)
        assert response is not None and response.ok
        conversation_button = page.locator("#memorial-conversation")
        assert conversation_button.count() == 1
        button_labels = conversation_button.evaluate(
            """button => ({
              text: String(button.textContent || "").trim(),
              aria: String(button.getAttribute("aria-label") || "").trim(),
              title: String(button.getAttribute("title") || "").trim(),
            })"""
        )
        initial_label = str(button_labels["text"])
        assert initial_label == "Gespräch beginnen"
        assert button_labels["aria"] == initial_label
        assert button_labels["title"] == initial_label

        assert page.locator("body[data-public-memorial-surface='conversation-only']").count() == 1
        assert page.locator("body > main").count() == 1
        assert page.locator("header + main#memorial-conversation-region").count() == 1
        assert page.locator("main#memorial-story").count() == 0
        assert page.locator("aside#memorial-conversation-region").count() == 0
        for viewport in ({"width": 1440, "height": 1100}, {"width": 390, "height": 844}):
            page.set_viewport_size(viewport)
            conversation_box = page.locator("main#memorial-conversation-region").bounding_box()
            assert conversation_box is not None
            assert page.locator("main#memorial-conversation-region").evaluate(
                "element => getComputedStyle(element).position"
            ) not in {"fixed", "sticky"}
            button_box = conversation_button.bounding_box()
            assert button_box is not None
            assert float(button_box["height"]) >= 56
            assert float(button_box["width"]) <= min(440, viewport["width"] - 40) + 1
            assert abs(
                float(button_box["x"])
                + (float(button_box["width"]) / 2)
                - (viewport["width"] / 2)
            ) <= 1
            assert page.evaluate(
                "() => document.documentElement.scrollWidth === document.documentElement.clientWidth"
            )
        page.set_viewport_size({"width": 1440, "height": 1100})
        conversation_main = page.locator("main#memorial-conversation-region")
        assert conversation_main.get_attribute("tabindex") == "-1"
        assert conversation_main.get_attribute("aria-label") == "KI-Gespräch über Manfred Hoza"
        assert page.locator("a.skip-link").evaluate_all(
            "links => links.map((link) => link.getAttribute('href'))"
        ) == ["#memorial-conversation-region"]
        text_form = page.locator("#memorial-text-turn-form")
        assert text_form.get_attribute("method") == "post"
        assert text_form.get_attribute("action") == f"/memorials/{slug}/chat"
        assert text_form.get_attribute("data-js-ready") == "false"
        assert text_form.get_attribute("hidden") == ""
        assert text_form.get_attribute("inert") == ""
        assert text_form.get_attribute("aria-hidden") == "true"
        assert text_form.get_attribute("aria-disabled") == "true"
        assert text_form.is_hidden()
        page.locator('a.skip-link[href="#memorial-conversation-region"]').focus()
        page.keyboard.press("Enter")
        assert page.evaluate("() => document.activeElement && document.activeElement.id") == "memorial-conversation-region"

        assert page.locator(
            '#memorial-speech-message[role="status"][aria-live="polite"][aria-atomic="true"]'
        ).count() == 1
        assert page.locator("#memorial-speech-note").get_attribute("role") is None
        assert page.locator("#memorial-speech-note").get_attribute("aria-live") is None
        assert page.locator("#memorial-speech-transcript-shell").get_attribute("aria-live") is None
        assert page.locator("#memorial-chat-answer").get_attribute("aria-live") is None
        assert page.locator("#memorial-speech-transcript").get_attribute("role") == "log"
        assert page.locator("#memorial-speech-transcript").get_attribute("aria-live") == "polite"
        assert page.locator("#memorial-speech-audio").get_attribute("aria-hidden") == "true"
        assert page.locator("#memorial-speech-audio").get_attribute("controls") is None

        assert page.get_by_role("heading", name="Erinnerungen an Manfred", exact=True).count() == 1
        assert page.get_by_text(
            "Ein ruhiger Ort für ein Gespräch über Manfred Hoza.",
            exact=True,
        ).count() == 0
        assert page.locator("article.memory-card").count() == 0
        assert page.locator(".source-list a").count() == 0
        assert page.locator(".prompt-list li").count() == 0
        assert page.locator("[data-memorial-archive-audio]").count() == 0
        assert page.locator("#memorial-archive-title").count() == 0
        assert page.locator("a[href*='/memory-room']").count() == 0
        assert page.locator("a[href*='/tours/']").count() == 0
        assert page.locator("header nav").count() == 0
        assert page.locator("#memorial-contribution").count() == 0
        assert page.locator("#memorial-contribution-form").count() == 0
        assert page.locator("#memorial-contribution-management").count() == 0
        privacy_settings = conversation_main.locator("details.conversation-settings")
        assert privacy_settings.count() == 1
        assert page.locator("details.conversation-settings").count() == 1
        assert privacy_settings.get_attribute("hidden") == ""
        assert privacy_settings.is_hidden()
        personal_memory_optin = privacy_settings.locator("#memorial-personal-memory-optin")
        personal_memory_status = privacy_settings.locator("#memorial-personal-memory-status")
        personal_memory_forget = privacy_settings.locator("#memorial-personal-memory-forget")
        assert personal_memory_optin.count() == 1
        assert personal_memory_optin.is_hidden()
        assert personal_memory_optin.is_checked() is False
        assert personal_memory_status.count() == 1
        assert personal_memory_status.is_hidden()
        assert personal_memory_forget.count() == 1
        assert personal_memory_forget.is_hidden()
        assert personal_memory_forget.is_disabled()
        assert personal_memory_forget.get_attribute("aria-disabled") == "true"
        assert page.locator("#memorial-install-hint").count() == 0
        assert page.locator("#memorial-retry-button").is_hidden()
        assert page.locator("#memorial-chat-tools").is_hidden()
        _assert_minimal_memorial_single_button(page, "Gespräch beginnen")

        disclosure = page.locator("#memorial-conversation-disclosure")
        assert disclosure.is_visible()
        disclosure_text = disclosure.inner_text()
        assert "KI-Rekonstruktion" in disclosure_text
        assert "Sie ist nicht Manfred und spricht nicht für ihn." in disclosure_text
        assert "Die Stimme ist künstlich erzeugt." in disclosure_text
        assert "erst nach „Gespräch beginnen“" in disclosure_text

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
        assert "Optional: Am Handy/Desktop installieren." not in page_html
        assert page.locator("#memorial-video-call").count() == 0
        assert page.locator("#memorial-voice-config-form").count() == 0
        assert page.locator("#memorial-voice-ab-wrap").count() == 0
        assert page.get_by_text("Tippen, sprechen, kurz warten, einfach weiterreden.").count() == 0
        assert page.get_by_text("Manfred Hennig").count() == 0
        page.wait_for_timeout(250)
        assert page_errors == []
    finally:
        context.close()


def test_memorial_no_javascript_conversation_fails_closed_without_leaking_private_text(
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
        response = page.goto(f"{base_url}/memorials/{slug}", wait_until="domcontentloaded", timeout=MEMORIAL_NAVIGATION_TIMEOUT_MS)
        assert response is not None and response.ok
        assert page.url == f"{base_url}/memorials/{slug}"
        assert page.locator("html").get_attribute("lang") == "de-AT"

        notice = page.locator("main#memorial-conversation-region noscript p")
        assert notice.count() == 1
        assert notice.is_visible()
        assert "Sprachgespräch und die schriftliche Alternative" in notice.inner_text()
        assert "nichts aufgenommen oder gesendet" in notice.inner_text()

        protected_form = page.locator("#memorial-text-turn-form")
        assert protected_form.get_attribute("method") == "post"
        assert protected_form.get_attribute("action") == f"/memorials/{slug}/chat"
        assert protected_form.get_attribute("data-js-ready") == "false"
        assert protected_form.get_attribute("hidden") == ""
        assert protected_form.get_attribute("inert") == ""
        assert protected_form.get_attribute("aria-hidden") == "true"
        assert protected_form.get_attribute("aria-disabled") == "true"
        assert protected_form.is_hidden()
        assert protected_form.locator("input, button").evaluate_all(
            """controls => controls.every((control) => {
              control.focus();
              return document.activeElement !== control;
            })"""
        )
        assert page.locator("#memorial-contribution-form").count() == 0
        assert page.locator("#memorial-contribution-management").count() == 0
        assert page.locator("#memorial-install-hint").count() == 0
        assert page.locator("#memorial-speech-note").is_hidden()
        assert page.locator("#memorial-speech-message").is_hidden()
        privacy_settings = page.locator(
            "main#memorial-conversation-region details.conversation-settings"
        )
        assert privacy_settings.count() == 1
        personal_memory_optin = privacy_settings.locator(
            "#memorial-personal-memory-optin"
        )
        assert personal_memory_optin.count() == 1
        assert personal_memory_optin.is_checked() is False
        assert personal_memory_optin.is_disabled()
        assert personal_memory_optin.get_attribute("aria-disabled") == "true"
        personal_memory_optin.focus()
        assert page.evaluate("() => document.activeElement?.id || ''") != (
            "memorial-personal-memory-optin"
        )
        assert privacy_settings.locator("#memorial-personal-memory-status").count() == 1
        personal_memory_forget = privacy_settings.locator("#memorial-personal-memory-forget")
        assert personal_memory_forget.count() == 1
        assert personal_memory_forget.is_disabled()
        assert personal_memory_forget.get_attribute("aria-disabled") == "true"
        assert privacy_settings.is_hidden()
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
        response = page.goto(f"{base_url}/memorials/{slug}", wait_until="domcontentloaded", timeout=MEMORIAL_NAVIGATION_TIMEOUT_MS)
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
        response = page.goto(f"{base_url}/memorials/{slug}", wait_until="domcontentloaded", timeout=MEMORIAL_NAVIGATION_TIMEOUT_MS)
        assert response is not None and response.ok
        _await_conversation_ready(page)
        assert page.locator("#memorial-conversation").inner_text().strip() == "Gespräch beginnen"
        turn_state = _await_realtime_turn_complete(
            page,
            slug,
            lambda: page.evaluate("window.__memorialStartConversation && window.__memorialStartConversation()"),
            timeout_ms=12000,
        )
        assert turn_state["done"] is True
        assert str(turn_state["answer"]).strip()
        active_button = page.locator("#memorial-conversation")
        assert (active_button.text_content() or "").strip() == "Gespräch beenden"
        assert active_button.get_attribute("aria-label") == "Gespräch beenden"
        assert active_button.get_attribute("title") == "Gespräch beenden"
        assert active_button.get_attribute("aria-pressed") == "true"
        _assert_minimal_memorial_single_button(page, "Gespräch beenden")
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
                button.textContent.trim() === "Gespräch beginnen"
              );
            }""",
            timeout=7000,
        )
        assert page.locator("#memorial-retry-button").is_hidden()
        stopped_button = page.locator("#memorial-conversation")
        assert (stopped_button.text_content() or "").strip() == "Gespräch beginnen"
        assert stopped_button.get_attribute("aria-label") == "Gespräch beginnen"
        assert stopped_button.get_attribute("title") == "Gespräch beginnen"
        assert stopped_button.get_attribute("aria-pressed") == "false"
        assert int(page.evaluate("() => window.__memorialTrackStopCalls || 0")) >= 1
        _assert_minimal_memorial_single_button(page, "Gespräch beginnen")
        phase_text = page.locator("#memorial-speech-phase").text_content() or ""
        assert phase_text in {"Ich bin da.", "Bereit"}
    finally:
        context.close()


def test_memorial_personal_memory_route_persists_only_with_explicit_opt_in(
    browser: Browser,
    memorial_browser_server: dict[str, object],
) -> None:
    base_url = str(memorial_browser_server["base_url"])
    slug = str(memorial_browser_server["slug"])
    context = browser.new_context(viewport={"width": 430, "height": 932})
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/memorials/{slug}", wait_until="domcontentloaded", timeout=MEMORIAL_NAVIGATION_TIMEOUT_MS)
        assert response is not None and response.ok
        privacy_settings = page.locator(
            "main#memorial-conversation-region details.conversation-settings"
        )
        assert privacy_settings.count() == 1
        assert privacy_settings.is_hidden()
        assert privacy_settings.locator("#memorial-personal-memory-optin").is_hidden()
        assert privacy_settings.locator("#memorial-personal-memory-status").is_hidden()
        assert privacy_settings.locator("#memorial-personal-memory-forget").is_hidden()
        assert page.locator("input:visible, textarea:visible, select:visible").count() == 0

        opted_out = context.request.get(
            f"{base_url}/memorials/{slug}/personal-memory",
            headers={"x-memorial-personal-memory": "0"},
        )
        assert opted_out.ok
        assert opted_out.json()["enabled"] is False
        assert opted_out.json()["item_count"] == 0

        chat = context.request.post(
            f"{base_url}/memorials/{slug}/chat",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "x-memorial-personal-memory": "1",
            },
            data={"question": "Woran soll ich mich heute erinnern?"},
        )
        assert chat.ok
        assert str(chat.json().get("answer") or "").strip()

        opted_in = context.request.get(
            f"{base_url}/memorials/{slug}/personal-memory",
            headers={"x-memorial-personal-memory": "1"},
        )
        assert opted_in.ok
        assert opted_in.json()["enabled"] is True
        assert opted_in.json()["item_count"] == 1

        forgotten = context.request.delete(
            f"{base_url}/memorials/{slug}/personal-memory",
            headers={"x-memorial-personal-memory": "1"},
        )
        assert forgotten.ok
        assert forgotten.json()["status"] == "forgotten"
        assert forgotten.json()["item_count"] == 0

        storage_value = page.evaluate(
            """(currentSlug) => window.localStorage.getItem(
              `memorial_personal_memory_enabled_${currentSlug}_v2`
            )""",
            slug,
        )
        assert storage_value is None

        after_forget = context.request.get(
            f"{base_url}/memorials/{slug}/personal-memory",
            headers={"x-memorial-personal-memory": "1"},
        )
        assert after_forget.ok
        assert after_forget.json()["enabled"] is True
        assert after_forget.json()["item_count"] == 0
    finally:
        context.close()


def test_memorial_browser_hides_keyboard_text_turn_until_voice_action(
    browser: Browser,
    memorial_browser_server: dict[str, object],
) -> None:
    base_url = str(memorial_browser_server["base_url"])
    slug = str(memorial_browser_server["slug"])
    context = browser.new_context(viewport={"width": 430, "height": 932})
    _install_fake_audio_runtime(context)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/memorials/{slug}", wait_until="domcontentloaded", timeout=MEMORIAL_NAVIGATION_TIMEOUT_MS)
        assert response is not None and response.ok
        _await_conversation_ready(page)
        assert page.locator("#memorial-text-turn-form").is_hidden()
        text_input = page.locator("#memorial-text-turn-input")
        assert text_input.is_hidden()
        text_input.focus()
        assert page.evaluate("() => document.activeElement?.id || ''") != "memorial-text-turn-input"
        assert int(page.evaluate("() => window.__memorialGetUserMediaCalls || 0")) == 0
        assert page.locator("#memorial-conversation").get_attribute("aria-pressed") == "false"
        assert page.locator("#memorial-conversation").inner_text().strip() == "Gespräch beginnen"
        assert page.locator("button:visible").count() == 1
        assert page.locator("#memorial-chat-answer").is_hidden()
    finally:
        context.close()


def test_memorial_browser_explains_microphone_permission_denial_and_resets_primary_control(
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
        response = page.goto(f"{base_url}/memorials/{slug}", wait_until="domcontentloaded", timeout=MEMORIAL_NAVIGATION_TIMEOUT_MS)
        assert response is not None and response.ok
        _await_conversation_ready(page)
        assert page.locator("#memorial-text-turn-form").is_hidden()
        assert page.locator("#memorial-retry-button").is_hidden()
        page.locator("#memorial-conversation").click()
        page.wait_for_function(
            """() => {
              const message = document.getElementById("memorial-speech-message");
              return Boolean(message && message.textContent.includes("Mikrofonzugriff ist blockiert"));
            }""",
            timeout=7000,
        )
        assert "Browser-Einstellungen" in (page.locator("#memorial-speech-detail").text_content() or "")
        assert int(page.evaluate("() => window.__memorialGetUserMediaCalls || 0")) == 1
        conversation = page.locator("#memorial-conversation")
        assert conversation.is_enabled()
        assert conversation.inner_text().strip() == "Gespräch beginnen"
        assert conversation.get_attribute("aria-label") == "Gespräch beginnen"
        assert conversation.get_attribute("title") == "Gespräch beginnen"
        assert conversation.get_attribute("aria-pressed") == "false"
        _assert_minimal_memorial_single_button(page, "Gespräch beginnen")
        assert "Textfrage" not in (page.locator("#memorial-speech-detail").text_content() or "")

        conversation.click()
        page.wait_for_function(
            "() => Number(window.__memorialGetUserMediaCalls || 0) >= 2",
            timeout=7000,
        )
        page.wait_for_function(
            """() => {
              const message = document.getElementById("memorial-speech-message");
              return Boolean(message && message.textContent.includes("Mikrofonzugriff ist blockiert"));
            }""",
            timeout=7000,
        )
        _assert_minimal_memorial_single_button(page, "Gespräch beginnen")
    finally:
        context.close()


@pytest.mark.parametrize("failure_stage", ("stt", "tts"))
def test_memorial_browser_all_provider_errors_keep_conversation_as_only_visible_button(
    browser: Browser,
    memorial_browser_server: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    from app.api.routes import public_memorials

    def fail_provider(**kwargs):
        raise RuntimeError(f"{failure_stage}_provider_unavailable")

    if failure_stage == "stt":
        monkeypatch.setattr(public_memorials, "_memorial_transcribe_audio_blob", fail_provider)
    else:
        monkeypatch.setattr(public_memorials, "_render_memorial_tts_audio", fail_provider)

    base_url = str(memorial_browser_server["base_url"])
    slug = str(memorial_browser_server["slug"])
    context = browser.new_context(viewport={"width": 430, "height": 932})
    _install_fake_audio_runtime(context)
    page: Page = context.new_page()
    try:
        response = page.goto(
            f"{base_url}/memorials/{slug}",
            wait_until="domcontentloaded",
            timeout=MEMORIAL_NAVIGATION_TIMEOUT_MS,
        )
        assert response is not None and response.ok
        _await_conversation_ready(page)
        page.locator("#memorial-conversation").click()
        page.wait_for_function(
            """() => {
              const message = document.getElementById("memorial-speech-message");
              return Boolean(message && message.textContent.includes("Bitte noch einmal sprechen"));
            }""",
            timeout=12000,
        )
        _assert_minimal_memorial_single_button(page, "Gespräch beginnen")
        assert page.locator("#memorial-speech-note").is_visible()
        assert page.locator("#memorial-speech-message").get_attribute("role") == "status"
        assert int(page.evaluate("() => window.__memorialGetUserMediaCalls || 0")) == 1

        page.locator("#memorial-conversation").click()
        page.wait_for_function(
            "() => Number(window.__memorialGetUserMediaCalls || 0) >= 2",
            timeout=12000,
        )
        page.wait_for_function(
            """() => {
              const message = document.getElementById("memorial-speech-message");
              return Boolean(message && message.textContent.includes("Bitte noch einmal sprechen"));
            }""",
            timeout=12000,
        )
        _assert_minimal_memorial_single_button(page, "Gespräch beginnen")
    finally:
        context.close()


def test_memorial_browser_voice_warmup_failure_stays_minimal_and_exposes_recovery_api(
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
    warmup_requests: list[str] = []
    page.on(
        "request",
        lambda request: warmup_requests.append(request.url)
        if request.url.endswith(f"/memorials/{slug}/warmup")
        else None,
    )
    try:
        response = page.goto(f"{base_url}/memorials/{slug}", wait_until="domcontentloaded", timeout=MEMORIAL_NAVIGATION_TIMEOUT_MS)
        assert response is not None and response.ok
        conversation = page.locator("#memorial-conversation")
        assert conversation.is_enabled()
        assert conversation.inner_text().strip() == "Gespräch beginnen"
        assert conversation.get_attribute("aria-label") == "Gespräch beginnen"
        assert conversation.get_attribute("title") == "Gespräch beginnen"
        assert page.locator("#memorial-text-turn-form").is_hidden()
        assert page.locator("#memorial-retry-button").is_hidden()
        assert page.locator("button:visible").count() == 1

        queued = context.request.post(
            f"{base_url}/memorials/{slug}/warmup",
            headers={"Accept": "application/json"},
        )
        assert queued.status == 202
        assert queued.json()["status"] == "queued"
        status = context.request.get(
            f"{base_url}/memorials/{slug}/warmup-status",
            headers={"Accept": "application/json"},
        )
        assert status.ok
        status_payload = status.json()
        assert status_payload["ready"] is False
        assert status_payload["operator_action_required"] is True
        assert status_payload["errors"] == ["provider_unavailable"]
        assert status_payload["voice_errors"] == ["provider_unavailable"]

        conversation.click()
        page.wait_for_function(
            """() => {
              const message = document.getElementById("memorial-speech-message");
              return Boolean(message && message.textContent.includes("Sprechen ist gerade nicht möglich"));
            }""",
            timeout=7000,
        )
        _assert_minimal_memorial_single_button(page, "Gespräch beginnen")
        assert len(warmup_requests) == 2

        conversation.click()
        page.wait_for_function(
            """() => {
              const message = document.getElementById("memorial-speech-message");
              return Boolean(message && message.textContent.includes("Sprechen ist gerade nicht möglich"));
            }""",
            timeout=7000,
        )
        page.wait_for_function(
            "() => document.getElementById('memorial-conversation').disabled === false",
            timeout=7000,
        )
        assert len(warmup_requests) == 3
        _assert_minimal_memorial_single_button(page, "Gespräch beginnen")
    finally:
        context.close()


def test_memorial_family_contribution_routes_keep_portable_exact_review_control(
    browser: Browser,
    memorial_browser_server: dict[str, object],
) -> None:
    base_url = str(memorial_browser_server["base_url"])
    slug = str(memorial_browser_server["slug"])
    context = browser.new_context(viewport={"width": 430, "height": 932})
    page: Page = context.new_page()
    private_sentinel = "BROWSER_PRIVATE_FAMILY_MEMORY_MUST_NOT_ESCAPE"
    try:
        response = page.goto(f"{base_url}/memorials/{slug}", wait_until="domcontentloaded", timeout=MEMORIAL_NAVIGATION_TIMEOUT_MS)
        assert response is not None and response.ok
        assert page.locator("#memorial-contribution").count() == 0
        assert page.locator("#memorial-contribution-form").count() == 0
        assert page.locator("#memorial-contribution-management").count() == 0

        def submit(title: str, body: str) -> dict[str, object]:
            submission = context.request.post(
                f"{base_url}/memorials/{slug}/contributions",
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                data={
                    "title": title,
                    "body": body,
                    "contributor_name": "Familienmitglied",
                    "relationship": "Familie",
                    "publication_consent": True,
                },
            )
            assert submission.ok
            return dict(submission.json())

        first = submit("Ein ruhiger Familienmoment", private_sentinel)
        second = submit(
            "Noch eine Erinnerung",
            "SECOND_BROWSER_PRIVATE_MEMORY_MUST_NOT_ESCAPE",
        )
        for submission in (first, second):
            receipt = dict(submission["recovery_receipt"])
            receipt.update(
                {
                    "slug": slug,
                    "contribution_id": submission["contribution_id"],
                    "manage_token": submission["manage_token"],
                }
            )
            assert receipt["schema_version"] == "ea.memorial_family_contribution.recovery_receipt.v1"
            assert receipt["slug"] == slug
            assert receipt["status_path"].endswith("/status")
            assert submission["contribution_id"]
            assert submission["manage_token"]
            assert str(submission["manage_token"]) not in page.locator("body").inner_text()

        contribution_id = str(first["contribution_id"])
        manage_token = str(first["manage_token"])
        contribution_path = f"{base_url}/memorials/{slug}/contributions/{contribution_id}"
        manage_headers = {
            "Accept": "application/json",
            "x-memorial-contribution-token": manage_token,
        }
        unauthorized = context.request.get(f"{contribution_path}/manage")
        assert unauthorized.status == 403
        managed = context.request.get(
            f"{contribution_path}/manage",
            headers=manage_headers,
        )
        assert managed.ok
        assert managed.json()["submission"]["body"] == private_sentinel

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
            contribution_id=contribution_id,
            payload={
                "reviewer": "Browser curator",
                "title": "Exakt geprüfte öffentliche Überschrift",
                "body": "Exakt geprüfter öffentlicher Text.",
                "source_label": "Erinnerung aus der Familie",
            },
        )
        proposal_sha256 = proposed["public_proposal_binding"]["sha256"]
        approved = context.request.post(
            f"{contribution_path}/proposal/approve",
            headers={**manage_headers, "Content-Type": "application/json"},
            data={"proposal_sha256": proposal_sha256},
        )
        assert approved.ok
        assert approved.json()["status"] == "approved_for_publication"
        rejected = context.request.post(
            f"{contribution_path}/proposal/reject",
            headers={**manage_headers, "Content-Type": "application/json"},
            data={"proposal_sha256": proposal_sha256},
        )
        assert rejected.ok
        assert rejected.json()["status"] == "proposal_rejected"

        corrected_body = "PRIVATE_CORRECTED_BROWSER_MEMORY_MUST_NOT_ESCAPE"
        corrected = context.request.post(
            f"{contribution_path}/correct",
            headers={**manage_headers, "Content-Type": "application/json"},
            data={
                "title": "Ein ruhiger Familienmoment",
                "body": corrected_body,
                "contributor_name": "Familienmitglied",
                "relationship": "Familie",
                "publication_consent": True,
                "correction_reason": "Browser route contract",
            },
        )
        assert corrected.ok
        assert corrected.json()["status"] == "correction_pending"

        withdrawn = context.request.post(
            f"{contribution_path}/withdraw",
            headers={**manage_headers, "Content-Type": "application/json"},
            data={"reason": "Von der beitragenden Person zurückgezogen."},
        )
        assert withdrawn.ok
        assert withdrawn.json()["status"] == "withdrawn"
        assert withdrawn.json()["visibility"] == "private"

        refreshed_public_payload = context.request.get(
            f"{base_url}/memorials/{slug}.json"
        )
        assert refreshed_public_payload.ok
        serialized_public = json.dumps(refreshed_public_payload.json())
        assert private_sentinel not in serialized_public
        assert corrected_body not in serialized_public
        assert manage_token not in page.locator("body").inner_text()
    finally:
        context.close()


def test_memorial_recovery_receipts_remain_portable_without_public_management_ui(
    browser: Browser,
    memorial_browser_server: dict[str, object],
) -> None:
    base_url = str(memorial_browser_server["base_url"])
    slug = str(memorial_browser_server["slug"])
    context = browser.new_context(viewport={"width": 430, "height": 932})
    page_errors: list[str] = []
    page: Page = context.new_page()
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    def submit_direct(title: str) -> dict[str, object]:
        response = context.request.post(
            f"{base_url}/memorials/{slug}/contributions",
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            data={
                "title": title,
                "body": f"Private recovery body for {title}",
                "publication_consent": True,
            },
        )
        assert response.ok
        return dict(response.json())

    try:
        response = page.goto(
            f"{base_url}/memorials/{slug}",
            wait_until="domcontentloaded",
            timeout=MEMORIAL_NAVIGATION_TIMEOUT_MS,
        )
        assert response is not None and response.ok
        assert page.locator("#memorial-contribution").count() == 0
        assert page.locator("#memorial-contribution-recovery-import").count() == 0
        assert page.locator("#memorial-contribution-management").count() == 0

        submissions = [
            submit_direct("Portabler Beleg eins"),
            submit_direct("Portabler Beleg zwei"),
            submit_direct("Portabler Beleg drei"),
        ]
        body_text = page.locator("body").inner_text()
        for submission in submissions:
            portable = dict(submission["recovery_receipt"])
            portable.update(
                {
                    "slug": slug,
                    "contribution_id": submission["contribution_id"],
                    "manage_token": submission["manage_token"],
                }
            )
            restored = json.loads(json.dumps(portable))
            assert restored == portable
            assert restored["schema_version"] == "ea.memorial_family_contribution.recovery_receipt.v1"
            assert restored["slug"] == slug
            assert restored["status_path"].endswith("/status")
            assert restored["manage_token_header"] == "x-memorial-contribution-token"
            assert restored["token_recoverable"] is False
            token = str(restored["manage_token"])
            assert token not in body_text
            managed = context.request.get(
                f"{base_url}/memorials/{slug}/contributions/{restored['contribution_id']}/manage",
                headers={"x-memorial-contribution-token": token},
            )
            assert managed.ok
            assert managed.json()["contribution_id"] == restored["contribution_id"]

        denied = context.request.get(
            f"{base_url}/memorials/{slug}/contributions/{submissions[0]['contribution_id']}/manage",
            headers={"x-memorial-contribution-token": "invalid-portable-token-value-00000000"},
        )
        assert denied.status == 403
        page.wait_for_timeout(200)
        assert page_errors == []
    finally:
        context.close()

    storage_blocked_context = browser.new_context(viewport={"width": 430, "height": 932})
    storage_blocked_context.add_init_script(
        """
        (() => {
          const guarded = (key) => String(key || "").startsWith("memorial_contribution_receipt_");
          for (const method of ["getItem", "setItem", "removeItem"]) {
            const original = Storage.prototype[method];
            Storage.prototype[method] = function(key, ...args) {
              if (guarded(key)) throw new DOMException("storage blocked", "SecurityError");
              return original.call(this, key, ...args);
            };
          }
        })();
        """
    )
    storage_page_errors: list[str] = []
    storage_page: Page = storage_blocked_context.new_page()
    storage_page.on("pageerror", lambda error: storage_page_errors.append(str(error)))
    try:
        response = storage_page.goto(
            f"{base_url}/memorials/{slug}",
            wait_until="domcontentloaded",
            timeout=MEMORIAL_NAVIGATION_TIMEOUT_MS,
        )
        assert response is not None and response.ok
        assert storage_page.locator("#memorial-contribution").count() == 0
        _await_conversation_ready(storage_page)
        _assert_minimal_memorial_single_button(storage_page, "Gespräch beginnen")
        direct = storage_blocked_context.request.post(
            f"{base_url}/memorials/{slug}/contributions",
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            data={
                "title": "Beleg ohne Browserspeicher",
                "body": "PRIVATE_VOLATILE_RECOVERY_BODY",
                "publication_consent": True,
            },
        )
        assert direct.ok
        direct_payload = dict(direct.json())
        direct_token = str(direct_payload["manage_token"])
        assert direct_token not in storage_page.locator("body").inner_text()
        managed = storage_blocked_context.request.get(
            f"{base_url}/memorials/{slug}/contributions/{direct_payload['contribution_id']}/manage",
            headers={"x-memorial-contribution-token": direct_token},
        )
        assert managed.ok
        storage_page.wait_for_timeout(200)
        assert storage_page_errors == []
    finally:
        storage_blocked_context.close()




def test_memorial_browser_reduced_motion_keeps_minimal_control_focus_stable(
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
        response = page.goto(f"{base_url}/memorials/{slug}", wait_until="domcontentloaded", timeout=MEMORIAL_NAVIGATION_TIMEOUT_MS)
        assert response is not None and response.ok
        _await_conversation_ready(page)
        conversation = page.locator("#memorial-conversation")
        assert conversation.inner_text().strip() == "Gespräch beginnen"
        assert page.locator("#memorial-chat-tools").is_hidden()
        assert page.locator("#memorial-read-answer").is_hidden()
        assert page.locator("button:visible").count() == 1
        conversation.focus()
        assert page.evaluate("() => document.activeElement?.id || ''") == "memorial-conversation"
        options = page.evaluate("() => window.__memorialScrollOptions.slice()")
        assert options == []
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
            timeout=MEMORIAL_NAVIGATION_TIMEOUT_MS,
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
        assert conversation.get_attribute("aria-label") == "Gespräch beginnen"
        assert conversation.get_attribute("title") == "Gespräch beginnen"
        assert page.locator("#memorial-speech-message").is_hidden()
        assert page.locator("#memorial-text-turn-form").is_hidden()
        assert page.locator("#memorial-retry-button").is_hidden()
        _assert_minimal_memorial_single_button(page, "Gespräch beginnen")
    finally:
        context.close()
