from __future__ import annotations

import json
import socket
import threading
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

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
            "intro": "Diese Seite sammelt echte Aufnahmen und belegte Erinnerungen.",
            "disclosure": "Originalaufnahmen sind als Original gekennzeichnet.",
            "audio_clips": [],
            "memory_cards": [
                {
                    "source_label": "Archiv",
                    "title": "Schach",
                    "body": "Das Schach bleibt in der Familie.",
                }
            ],
            "suggested_prompts": ["Was ist wirklich belegt?"],
        },
    )
    (private_root / slug).mkdir(parents=True, exist_ok=True)
    (private_root / slug / "tts_voice.json").write_text(
        json.dumps(
            {
                "tts_mode": "browser_speech_synthesis",
                "voice_label": "Tibor freigegebene synthetische Stimme",
                "lang": "de-AT",
                "rate": 0.88,
                "pitch": 0.86,
                "volume": 1.0,
                "voice_name_hints": ["Tibor", "de-AT"],
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
                "archive_sections": [
                    {"title": "Oeffentliches Archiv", "audience": "public", "items": ["doc-public"]},
                ],
                "fliplink_publications": [
                    {
                        "id": "doc-public",
                        "title": "Public Doc",
                        "audience": "public",
                        "viewer_type": "smart_document",
                        "url": "https://archive.example/public",
                        "description": "Visible",
                        "sensitivity": "PUBLIC",
                        "review_status": "approved",
                        "version": "2026-06-06",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    monkeypatch.setenv("EA_PRIVATE_MEMORIAL_PROFILE_DIR", str(private_root))
    public_memorials._PERSONAL_MEMORY_ROOT = artifacts_root / "memorial_user_memory"
    public_memorials._VOICE_AB_ROOT = artifacts_root / "memorial_voice_ab"
    public_memorials._PUBLIC_MEMORIAL_RATE_DB = artifacts_root / "memorial_rate_limits.sqlite3"
    memorial_archive_registry.PUBLIC_MEMORIAL_ROOT = registry_root
    memorial_archive_registry.ARCHIVE_ROOT = tmp_path / "archive"

    def _fake_generate_text(*, messages, requested_model, max_output_tokens):
        prompt = str(messages[-1]["content"] or "").lower()
        if "belegt" in prompt:
            text = "Belegt ist vor allem, was in Archivquellen und freigegebenen Erinnerungen auftaucht."
        else:
            text = "Ich antworte nur aus belegten Quellen und markierten Erinnerungen."
        return SimpleNamespace(text=text, provider_key="unit-test-model", model="unit-test-model")

    monkeypatch.setattr(public_memorials, "generate_text", _fake_generate_text)

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


def test_memorial_public_page_answers_visible_prompt_in_real_browser(
    browser: Browser,
    memorial_browser_server: dict[str, object],
) -> None:
    base_url = str(memorial_browser_server["base_url"])
    slug = str(memorial_browser_server["slug"])
    context = browser.new_context(viewport={"width": 1440, "height": 1100})
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/memorials/{slug}", wait_until="networkidle")
        assert response is not None and response.ok
        assert page.get_by_role("heading", name="Manfred Hoza").is_visible()
        assert page.get_by_role("button", name="Sprich mit der Erinnerung").is_visible()
        assert page.get_by_text("Tippen, sprechen, kurz warten, einfach weiterreden.").is_visible()
        assert page.locator("#memorial-archive").count() == 0
        assert page.get_by_text("Originalaufnahmen").count() == 0
        assert page.get_by_text("Belegte Erinnerungen").count() == 0
    finally:
        context.close()


def test_memorial_pwa_bootstrap_registers_service_worker_and_exposes_safe_voice_config(
    browser: Browser,
    memorial_browser_server: dict[str, object],
) -> None:
    base_url = str(memorial_browser_server["base_url"])
    slug = str(memorial_browser_server["slug"])
    context = browser.new_context(viewport={"width": 1280, "height": 960})
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/memorials/{slug}", wait_until="networkidle")
        assert response is not None and response.ok

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
              const registration = await navigator.serviceWorker.getRegistration(`/memorials/${currentSlug}`);
              return Boolean(registration && registration.scope.endsWith(`/memorials/${currentSlug}`));
            }""",
            slug,
        )
        assert has_registration is True

        voice_config = page.evaluate(
            """async (currentSlug) => {
              const response = await fetch(`/memorials/${currentSlug}/voice-config`);
              return response.json();
            }""",
            slug,
        )
        assert voice_config["slug"] == slug
        assert voice_config["tts_plugin"] == "browser_speech_synthesis"
        assert voice_config["tts_mode"] == "browser_speech_synthesis"
        assert voice_config["voice_label"] == "Tibor freigegebene synthetische Stimme"
        assert voice_config["voice_name_hints"] == ["Tibor", "de-AT"]
        assert "tts_plugin_voice_id" not in voice_config
        assert "provider_secret" not in voice_config
    finally:
        context.close()


def test_memorial_hero_conversation_uses_realtime_client_flow_without_hardware(
    browser: Browser,
    memorial_browser_server: dict[str, object],
) -> None:
    base_url = str(memorial_browser_server["base_url"])
    slug = str(memorial_browser_server["slug"])
    context = browser.new_context(viewport={"width": 1440, "height": 1100})
    context.add_init_script(
        """
        (() => {
          class FakeRecognition {
            constructor() {
              this.lang = "de-AT";
              this.interimResults = true;
              this.continuous = false;
              this.maxAlternatives = 1;
              this._emitted = false;
              this.onstart = null;
              this.onresult = null;
              this.onerror = null;
              this.onend = null;
            }
            start() {
              setTimeout(() => {
                if (this.onstart) this.onstart();
                if (!this._emitted) {
                  this._emitted = true;
                  setTimeout(() => {
                    if (this.onresult) {
                      this.onresult({
                        resultIndex: 0,
                        results: [
                          {
                            0: { transcript: "Wie klingt deine Stimme?" },
                            isFinal: true,
                            length: 1,
                          },
                        ],
                      });
                    }
                    setTimeout(() => {
                      if (this.onend) this.onend();
                    }, 10);
                  }, 20);
                } else {
                  setTimeout(() => {
                    if (this.onend) this.onend();
                  }, 10);
                }
              }, 10);
            }
            stop() {
              if (this.onend) setTimeout(() => this.onend(), 0);
            }
          }

          class FakeWebSocket {
            static OPEN = 1;
            static CLOSED = 3;
            constructor(url) {
              this.url = url;
              this.readyState = FakeWebSocket.OPEN;
              this.onopen = null;
              this.onmessage = null;
              this.onerror = null;
              this.onclose = null;
              setTimeout(() => {
                if (this.onopen) this.onopen();
                if (this.onmessage) {
                  this.onmessage({
                    data: JSON.stringify({ type: "ready", mode: "memorial_realtime_voice" }),
                  });
                }
              }, 0);
            }
            send(payload) {
              let parsed = null;
              try {
                parsed = JSON.parse(String(payload || ""));
              } catch (error) {
                return;
              }
              if (!parsed || parsed.type !== "user_text_turn") return;
              const turnId = String(parsed.turn_id || "");
              setTimeout(() => {
                if (this.onmessage) {
                  this.onmessage({
                    data: JSON.stringify({
                      type: "answer",
                      turn_id: turnId,
                      text: "Meine Stimme klingt ruhig, klar und durch echte Aufnahmen belegt.",
                      sources: ["Archiv"],
                      llm_model: "fake-realtime-model",
                    }),
                  });
                }
              }, 30);
              setTimeout(() => {
                if (this.onmessage) {
                  this.onmessage({
                    data: JSON.stringify({
                      type: "turn_complete",
                      turn_id: turnId,
                    }),
                  });
                }
              }, 60);
            }
            close() {
              this.readyState = FakeWebSocket.CLOSED;
              if (this.onclose) this.onclose();
            }
          }

          window.SpeechRecognition = FakeRecognition;
          window.webkitSpeechRecognition = FakeRecognition;
          window.WebSocket = FakeWebSocket;
          HTMLMediaElement.prototype.play = function play() {
            return Promise.resolve();
          };
        })();
        """
    )
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/memorials/{slug}", wait_until="networkidle")
        assert response is not None and response.ok

        page.get_by_role("button", name="Sprich mit der Erinnerung").click()
        page.wait_for_function(
            """
            () => {
              const answer = document.getElementById('memorial-chat-answer');
              return Boolean(
                answer &&
                answer.textContent &&
                answer.textContent.includes('Meine Stimme klingt ruhig, klar')
              );
            }
            """,
            timeout=5000,
        )
        answer_text = page.evaluate("document.getElementById('memorial-chat-answer').textContent")
        assert "Meine Stimme klingt ruhig, klar" in str(answer_text)
        assert "Quellen: Archiv" in str(answer_text)

        phase_text = page.locator("#memorial-speech-phase").text_content()
        assert phase_text in {"Bereit", "Ich hoere dir zu"}

        page.get_by_role("button", name="Sprich mit der Erinnerung").click()
        page.wait_for_function(
            """
            () => {
              const phase = document.getElementById('memorial-speech-phase');
              return Boolean(phase && phase.textContent && phase.textContent.includes('Bereit'));
            }
            """,
            timeout=5000,
        )
    finally:
        context.close()


def test_memorial_retry_button_recovers_from_microphone_denial(
    browser: Browser,
    memorial_browser_server: dict[str, object],
) -> None:
    base_url = str(memorial_browser_server["base_url"])
    slug = str(memorial_browser_server["slug"])
    context = browser.new_context(viewport={"width": 1280, "height": 960})
    context.add_init_script(
        """
        (() => {
          let attempt = 0;
          class FakeRecognition {
            constructor() {
              this.lang = "de-AT";
              this.interimResults = true;
              this.continuous = false;
              this.maxAlternatives = 1;
              this.onstart = null;
              this.onresult = null;
              this.onerror = null;
              this.onend = null;
            }
            start() {
              attempt += 1;
              setTimeout(() => {
                if (this.onstart) this.onstart();
                if (attempt === 1) {
                  setTimeout(() => {
                    if (this.onerror) this.onerror({ error: "not-allowed" });
                    if (this.onend) this.onend();
                  }, 10);
                  return;
                }
                setTimeout(() => {
                  if (this.onresult) {
                    this.onresult({
                      resultIndex: 0,
                      results: [
                        {
                          0: { transcript: "Erzaehl mir etwas ueber Gerechtigkeit." },
                          isFinal: true,
                          length: 1,
                        },
                      ],
                    });
                  }
                  setTimeout(() => {
                    if (this.onend) this.onend();
                  }, 10);
                }, 15);
              }, 10);
            }
            stop() {
              if (this.onend) setTimeout(() => this.onend(), 0);
            }
          }

          class FakeWebSocket {
            static OPEN = 1;
            static CLOSED = 3;
            constructor(url) {
              this.url = url;
              this.readyState = FakeWebSocket.OPEN;
              this.onopen = null;
              this.onmessage = null;
              this.onerror = null;
              this.onclose = null;
              setTimeout(() => {
                if (this.onopen) this.onopen();
                if (this.onmessage) {
                  this.onmessage({ data: JSON.stringify({ type: "ready" }) });
                }
              }, 0);
            }
            send(payload) {
              let parsed = null;
              try {
                parsed = JSON.parse(String(payload || ""));
              } catch (error) {
                return;
              }
              if (!parsed || parsed.type !== "user_text_turn") return;
              const turnId = String(parsed.turn_id || "");
              setTimeout(() => {
                if (this.onmessage) {
                  this.onmessage({
                    data: JSON.stringify({
                      type: "answer",
                      turn_id: turnId,
                      text: "Gerechtigkeit war mir wichtig, weil jeder gehoert werden sollte.",
                      sources: ["Archiv"],
                    }),
                  });
                }
              }, 20);
              setTimeout(() => {
                if (this.onmessage) {
                  this.onmessage({
                    data: JSON.stringify({ type: "turn_complete", turn_id: turnId }),
                  });
                }
              }, 40);
            }
            close() {
              this.readyState = FakeWebSocket.CLOSED;
              if (this.onclose) this.onclose();
            }
          }

          window.SpeechRecognition = FakeRecognition;
          window.webkitSpeechRecognition = FakeRecognition;
          window.WebSocket = FakeWebSocket;
          HTMLMediaElement.prototype.play = function play() {
            return Promise.resolve();
          };
        })();
        """
    )
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/memorials/{slug}", wait_until="networkidle")
        assert response is not None and response.ok

        page.get_by_role("button", name="Sprich mit der Erinnerung").click()
        page.get_by_role("button", name="Noch einmal versuchen").wait_for(state="visible", timeout=5000)
        assert page.get_by_text("Bitte erlaube kurz das Mikrofon und versuche es noch einmal.").is_visible()

        page.get_by_role("button", name="Noch einmal versuchen").click()
        page.wait_for_function(
            """
            () => {
              const answer = document.getElementById('memorial-chat-answer');
              return Boolean(
                answer &&
                answer.textContent &&
                answer.textContent.includes('Gerechtigkeit war mir wichtig')
              );
            }
            """,
            timeout=5000,
        )
    finally:
        context.close()


def test_memorial_pwa_launch_autostarts_conversation_when_opted_in(
    browser: Browser,
    memorial_browser_server: dict[str, object],
) -> None:
    base_url = str(memorial_browser_server["base_url"])
    slug = str(memorial_browser_server["slug"])
    context = browser.new_context(viewport={"width": 430, "height": 932})
    context.add_init_script(
        """
        (() => {
          try {
            window.localStorage.setItem("memorial_autostart_enabled_v1", "1");
          } catch (error) {}

          const originalMatchMedia = window.matchMedia ? window.matchMedia.bind(window) : null;
          window.matchMedia = (query) => {
            if (String(query || "") === "(display-mode: standalone)") {
              return {
                matches: true,
                media: query,
                onchange: null,
                addListener() {},
                removeListener() {},
                addEventListener() {},
                removeEventListener() {},
                dispatchEvent() { return false; },
              };
            }
            if (originalMatchMedia) return originalMatchMedia(query);
            return {
              matches: false,
              media: String(query || ""),
              onchange: null,
              addListener() {},
              removeListener() {},
              addEventListener() {},
              removeEventListener() {},
              dispatchEvent() { return false; },
            };
          };
          try {
            Object.defineProperty(window.navigator, "standalone", {
              configurable: true,
              get() { return true; },
            });
          } catch (error) {}

          class FakeRecognition {
            constructor() {
              this.lang = "de-AT";
              this.interimResults = true;
              this.continuous = false;
              this.maxAlternatives = 1;
              this.onstart = null;
              this.onresult = null;
              this.onerror = null;
              this.onend = null;
            }
            start() {
              setTimeout(() => {
                if (this.onstart) this.onstart();
                setTimeout(() => {
                  if (this.onresult) {
                    this.onresult({
                      resultIndex: 0,
                      results: [
                        {
                          0: { transcript: "Wie klingt deine Stimme?" },
                          isFinal: true,
                          length: 1,
                        },
                      ],
                    });
                  }
                  setTimeout(() => {
                    if (this.onend) this.onend();
                  }, 10);
                }, 20);
              }, 10);
            }
            stop() {
              if (this.onend) setTimeout(() => this.onend(), 0);
            }
          }

          class FakeWebSocket {
            static OPEN = 1;
            static CLOSED = 3;
            constructor(url) {
              this.url = url;
              this.readyState = FakeWebSocket.OPEN;
              this.onopen = null;
              this.onmessage = null;
              this.onerror = null;
              this.onclose = null;
              setTimeout(() => {
                if (this.onopen) this.onopen();
                if (this.onmessage) {
                  this.onmessage({
                    data: JSON.stringify({ type: "ready", mode: "memorial_realtime_voice" }),
                  });
                }
              }, 0);
            }
            send(payload) {
              let parsed = null;
              try {
                parsed = JSON.parse(String(payload || ""));
              } catch (error) {
                return;
              }
              if (!parsed || parsed.type !== "user_text_turn") return;
              const turnId = String(parsed.turn_id || "");
              setTimeout(() => {
                if (this.onmessage) {
                  this.onmessage({
                    data: JSON.stringify({
                      type: "answer",
                      turn_id: turnId,
                      text: "Meine Stimme klingt ruhig, klar und durch echte Aufnahmen belegt.",
                      sources: ["Archiv"],
                      llm_model: "fake-realtime-model",
                    }),
                  });
                }
              }, 30);
              setTimeout(() => {
                if (this.onmessage) {
                  this.onmessage({
                    data: JSON.stringify({
                      type: "turn_complete",
                      turn_id: turnId,
                    }),
                  });
                }
              }, 60);
            }
            close() {
              this.readyState = FakeWebSocket.CLOSED;
              if (this.onclose) this.onclose();
            }
          }

          window.SpeechRecognition = FakeRecognition;
          window.webkitSpeechRecognition = FakeRecognition;
          window.WebSocket = FakeWebSocket;
          HTMLMediaElement.prototype.play = function play() {
            return Promise.resolve();
          };
        })();
        """
    )
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/memorials/{slug}?source=pwa", wait_until="networkidle")
        assert response is not None and response.ok

        page.wait_for_function(
            """
            () => {
              const answer = document.getElementById('memorial-chat-answer');
              return Boolean(
                answer &&
                answer.textContent &&
                answer.textContent.includes('Meine Stimme klingt ruhig, klar')
              );
            }
            """,
            timeout=5000,
        )
        body_class = page.get_attribute("body", "class") or ""
        assert "pwa-standalone" in body_class
        answer_text = page.evaluate("document.getElementById('memorial-chat-answer').textContent")
        assert "Meine Stimme klingt ruhig, klar" in str(answer_text)
        assert "Quellen: Archiv" in str(answer_text)
    finally:
        context.close()


def test_memorial_pwa_offline_reload_uses_cached_memorial_page(
    browser: Browser,
    memorial_browser_server: dict[str, object],
) -> None:
    base_url = str(memorial_browser_server["base_url"])
    slug = str(memorial_browser_server["slug"])
    context = browser.new_context(viewport={"width": 1280, "height": 960})
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/memorials/{slug}?source=pwa", wait_until="networkidle")
        assert response is not None and response.ok
        page.wait_for_function(
            """
            async (currentSlug) => {
              if (!("serviceWorker" in navigator)) return false;
              const registration = await navigator.serviceWorker.getRegistration(`/memorials/${currentSlug}`);
              return Boolean(registration && registration.active);
            }
            """,
            arg=slug,
            timeout=5000,
        )
        second_response = page.reload(wait_until="networkidle")
        assert second_response is not None and second_response.ok
        page.wait_for_function(
            "() => Boolean(navigator.serviceWorker && navigator.serviceWorker.controller)",
            timeout=5000,
        )
        assert page.get_by_role("heading", name="Manfred Hoza").is_visible()

        context.set_offline(True)
        offline_response = page.reload(wait_until="domcontentloaded")
        assert offline_response is not None
        assert page.get_by_role("heading", name="Manfred Hoza").is_visible()
        assert page.get_by_role("button", name="Sprich mit der Erinnerung").is_visible()
    finally:
        context.set_offline(False)
        context.close()
