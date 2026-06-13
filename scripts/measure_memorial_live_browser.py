#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import io
import math
import re
import shutil
import struct
import subprocess
import tempfile
import time
import wave
from datetime import UTC, datetime
from pathlib import Path


LIVE_PROMPT_TEXT = "Hallo Manfred, kannst du jetzt mit mir sprechen?"
DEFAULT_EXIT_GATE_MAX_FIRST_ANSWER_MS = 10000.0
DEFAULT_GOLD_MAX_FIRST_ANSWER_MS = 4500.0
DEFAULT_EXIT_GATE_REQUIRED_CONTEXT_MATCHES = 2
DEFAULT_EXIT_GATE_CONTEXT_TOKENS = (
    "ja",
    "da",
    "sprich",
    "sag",
    "beschaeftigt",
    "reagiere",
)
DEFAULT_EXIT_GATE_REQUIRED_GROUP_MATCHES = 2
EXIT_GATE_SEMANTIC_PROFILES = (
    {
        "id": "contact_opening",
        "prompt_tokens": ("hallo", "mit mir sprechen", "reden", "bist du da", "hoerst du"),
        "answer_tokens": DEFAULT_EXIT_GATE_CONTEXT_TOKENS,
        "minimum_context_matches": DEFAULT_EXIT_GATE_REQUIRED_CONTEXT_MATCHES,
        "required_any": (
            ("ja", "da"),
            ("sprich", "sag"),
            ("beschaeftigt", "reagiere"),
        ),
        "required_group_matches": DEFAULT_EXIT_GATE_REQUIRED_GROUP_MATCHES,
    },
    {
        "id": "decision_reflection",
        "prompt_tokens": ("entscheidung", "wichtigste frage", "schwierigen"),
        "answer_tokens": ("vorlaeufig", "urteil", "tatsachen", "unterlagen", "risiko", "fakten", "belegt"),
        "minimum_context_matches": 2,
        "required_any": (
            ("vorlaeufig", "urteil"),
            ("tatsachen", "unterlagen", "fakten"),
            ("risiko", "belegt"),
        ),
        "required_group_matches": 2,
    },
    {
        "id": "moral_conflict",
        "prompt_tokens": ("moralischen konflikt", "moral", "konflikt"),
        "answer_tokens": ("widerspreche", "nachgeben", "falsch", "werte", "haltung", "friedens", "blieb"),
        "minimum_context_matches": 2,
        "required_any": (
            ("widerspreche", "falsch"),
            ("nachgeben", "friedens"),
            ("werte", "haltung", "blieb", "konflikt"),
        ),
        "required_group_matches": 2,
    },
)


def _require_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as exc:  # pragma: no cover - runtime-only dependency
        raise SystemExit(
            "playwright_not_installed: run `python3 -m pip install playwright && python3 -m playwright install chromium`"
        ) from exc
    return sync_playwright


def _require_binary(name: str) -> str:
    resolved = shutil.which(name)
    if not resolved:
        raise SystemExit(f"missing_binary:{name}")
    return resolved


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_head() -> str:
    root = Path(__file__).resolve().parents[1]
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _git_dirty() -> bool:
    root = Path(__file__).resolve().parents[1]
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "status", "--short"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return True
    return bool(proc.stdout.strip()) if proc.returncode == 0 else True


def _is_local_base_url(value: str) -> bool:
    lowered = str(value or "").strip().lower()
    return any(marker in lowered for marker in ("://127.0.0.1", "://localhost", "://0.0.0.0", "://[::1]"))


def _pure_python_prompt_wav_bytes(text: str) -> bytes:
    sample_rate = 16000
    amplitude = 14000
    segments = max(4, min(18, len(str(text or "").split()) * 2))
    segment_frames = int(sample_rate * 0.16)
    silence_frames = int(sample_rate * 0.035)
    frames = bytearray()
    for index in range(segments):
        frequency = 280.0 + float((index % 5) * 62)
        for frame_index in range(segment_frames):
            envelope = min(1.0, frame_index / max(1, int(sample_rate * 0.02)))
            tail = min(1.0, (segment_frames - frame_index) / max(1, int(sample_rate * 0.03)))
            gain = min(envelope, tail)
            sample = int(amplitude * gain * math.sin((2.0 * math.pi * frequency * frame_index) / sample_rate))
            frames.extend(struct.pack("<h", sample))
        frames.extend(b"\x00\x00" * silence_frames)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(bytes(frames))
    return buffer.getvalue()


def _synthesized_prompt_wav_bytes(text: str) -> bytes:
    espeak_bin = shutil.which("espeak-ng")
    ffmpeg_bin = shutil.which("ffmpeg")
    if not espeak_bin or not ffmpeg_bin:
        return _pure_python_prompt_wav_bytes(text)
    with tempfile.TemporaryDirectory(prefix="memorial-live-browser-") as tmpdir:
        tmp_path = Path(tmpdir)
        raw_wav = tmp_path / "speech.raw.wav"
        normalized_wav = tmp_path / "speech.16k.wav"
        subprocess.run(
            [
                espeak_bin,
                "-v",
                "de",
                "-s",
                "155",
                "-p",
                "44",
                "-w",
                str(raw_wav),
                text,
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                ffmpeg_bin,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(raw_wav),
                "-ac",
                "1",
                "-ar",
                "16000",
                str(normalized_wav),
            ],
            check=True,
            capture_output=True,
        )
        return normalized_wav.read_bytes()


def _fake_media_init_script(audio_base64: str) -> str:
    return f"""
(() => {{
  const audioBase64 = {json.dumps(audio_base64)};
  const decodeBase64 = (value) => Uint8Array.from(atob(String(value || "")), (char) => char.charCodeAt(0));
  const wavBytes = decodeBase64(audioBase64);
  const wavBlob = new Blob([wavBytes], {{ type: "audio/wav" }});

  class FakeTrack {{
    stop() {{}}
  }}

  class FakeStream {{
    getTracks() {{
      return [new FakeTrack()];
    }}
  }}

  class FakeMediaRecorder {{
    constructor(stream, options = {{}}) {{
      this.stream = stream;
      const requestedMimeType = (options && options.mimeType) ? String(options.mimeType) : "";
      this.mimeType = requestedMimeType.includes("wav") ? requestedMimeType : "audio/wav";
      this.state = "inactive";
      this.ondataavailable = null;
      this.onstart = null;
      this.onstop = null;
      this.onerror = null;
    }}
      start() {{
      this.state = "recording";
      setTimeout(() => {{
        if (this.onstart) this.onstart();
        this.stop();
      }}, 240);
    }}
    stop() {{
      if (this.state !== "recording") return;
      this.state = "inactive";
      setTimeout(() => {{
        if (this.ondataavailable) this.ondataavailable({{ data: wavBlob, size: wavBlob.size }});
        if (this.onstop) this.onstop();
      }}, 24);
    }}
    static isTypeSupported() {{
      return true;
    }}
  }}

  Object.defineProperty(window, "SpeechRecognition", {{ configurable: true, value: undefined }});
  Object.defineProperty(window, "webkitSpeechRecognition", {{ configurable: true, value: undefined }});
  Object.defineProperty(window, "MediaRecorder", {{ configurable: true, value: FakeMediaRecorder }});

  if (!navigator.mediaDevices) {{
    Object.defineProperty(navigator, "mediaDevices", {{ configurable: true, value: {{}} }});
  }}
  navigator.mediaDevices.getUserMedia = async () => new FakeStream();
  window.__memorial_audio_gate = {{ play_calls: 0, play_ended: 0, last_error: "" }};
  HTMLMediaElement.prototype.play = function play() {{
    window.__memorial_audio_gate.play_calls += 1;
    return new Promise((resolve, reject) => {{
      setTimeout(() => {{
        if (!this.getAttribute("src")) {{
          window.__memorial_audio_gate.play_ended += 1;
          window.__memorial_audio_gate.last_error = "missing_audio_src";
          reject(new Error("missing_audio_src"));
          return;
        }}
        window.__memorial_audio_gate.play_ended += 1;
        this.dispatchEvent(new Event("ended"));
        resolve();
      }}, 1750);
    }});
  }};
}})();
"""


def _realtime_stub_turn_init_script(prompt_text: str) -> str:
    answer = "Ja, ich bin da. Sag mir einfach, was dich beschaeftigt, dann reagiere ich direkt darauf."
    audio_base64 = base64.b64encode(_synthesized_prompt_wav_bytes(answer)).decode("ascii")
    return f"""
(() => {{
  const promptText = {json.dumps(str(prompt_text or "").strip())};
  const answerText = {json.dumps(answer)};
  const audioBase64 = {json.dumps(audio_base64)};
  const NativeWebSocket = window.WebSocket;
  if (!NativeWebSocket || !promptText) return;
  window.WebSocket = function MemorialRealtimeStubTurnWebSocket(url, protocols) {{
    const socket = protocols === undefined ? new NativeWebSocket(url) : new NativeWebSocket(url, protocols);
    const nativeSend = socket.send.bind(socket);
    const dispatchRealtimeMessage = (message) => {{
      const event = new MessageEvent("message", {{ data: JSON.stringify(message) }});
      socket.dispatchEvent(event);
      if (typeof socket.onmessage === "function") socket.onmessage(event);
    }};
    const dispatchStubTurn = (turnId) => {{
      window.setTimeout(() => dispatchRealtimeMessage({{ type: "phase", turn_id: turnId, phase: "transcribing", detail: "Audio wird transkribiert" }}), 20);
      window.setTimeout(() => dispatchRealtimeMessage({{ type: "transcript", turn_id: turnId, text: promptText }}), 40);
      window.setTimeout(() => dispatchRealtimeMessage({{ type: "answer", turn_id: turnId, text: answerText, sources: [], llm_model: "playwright_realtime_stub" }}), 60);
      window.setTimeout(() => dispatchRealtimeMessage({{ type: "audio", turn_id: turnId, audio_base64: audioBase64, content_type: "audio/wav" }}), 80);
      window.setTimeout(() => dispatchRealtimeMessage({{ type: "turn_complete", turn_id: turnId }}), 100);
    }};
    const suppressedAudioTurns = new Set();
    socket.send = (payload) => {{
      const socketUrl = String(socket.url || url || "");
      if (!socketUrl.includes("/realtime")) return nativeSend(payload);
      if (typeof payload === "string") {{
        try {{
          const message = JSON.parse(payload);
          const messageType = String((message && message.type) || "");
          const turnId = String((message && message.turn_id) || ("turn_" + Date.now()));
          if (messageType === "user_audio_start") {{
            suppressedAudioTurns.add(turnId);
            dispatchStubTurn(turnId);
            return undefined;
          }}
          if (messageType === "user_audio_end" && suppressedAudioTurns.has(turnId)) {{
            suppressedAudioTurns.delete(turnId);
            return undefined;
          }}
        }} catch (error) {{}}
      }}
      if (payload instanceof ArrayBuffer || ArrayBuffer.isView(payload) || payload instanceof Blob) {{
        if (suppressedAudioTurns.size > 0) return undefined;
      }}
      return nativeSend(payload);
    }};
    return socket;
  }};
  window.WebSocket.prototype = NativeWebSocket.prototype;
  Object.defineProperty(window.WebSocket, "CONNECTING", {{ value: NativeWebSocket.CONNECTING }});
  Object.defineProperty(window.WebSocket, "OPEN", {{ value: NativeWebSocket.OPEN }});
  Object.defineProperty(window.WebSocket, "CLOSING", {{ value: NativeWebSocket.CLOSING }});
  Object.defineProperty(window.WebSocket, "CLOSED", {{ value: NativeWebSocket.CLOSED }});
}})();
"""


def _transcribe_stub_payload(prompt_text: str) -> dict[str, object]:
    return {
        "transcription_status": "transcribed",
        "transcript_text": str(prompt_text or "").strip(),
        "transcriber": "playwright_stub",
    }


def _normalized_text(value: str) -> str:
    lowered = str(value or "").lower()
    return re.sub(r"[^a-z0-9äöüß]+", " ", lowered)


def _count_context_matches(answer_text: str, tokens: tuple[str, ...]) -> tuple[int, list[str]]:
    normalized = _normalized_text(answer_text)
    matched: list[str] = []
    for token in tokens:
        normalized_token = str(token or "").strip().lower()
        if normalized_token and normalized_token in normalized and normalized_token not in matched:
            matched.append(normalized_token)
    return len(matched), matched


def _semantic_profile_for_prompt(prompt_text: str) -> dict[str, object]:
    normalized_prompt = _normalized_text(prompt_text)
    best_profile = dict(EXIT_GATE_SEMANTIC_PROFILES[0])
    best_score = -1
    for profile in EXIT_GATE_SEMANTIC_PROFILES:
        prompt_tokens = tuple(str(token).strip().lower() for token in tuple(profile.get("prompt_tokens") or ()) if str(token).strip())
        score = sum(1 for token in prompt_tokens if token in normalized_prompt)
        if score > best_score:
            best_profile = dict(profile)
            best_score = score
    return best_profile


def _semantic_group_matches(answer_text: str, required_any: tuple[tuple[str, ...], ...]) -> tuple[int, list[list[str]]]:
    normalized = _normalized_text(answer_text)
    matched_groups: list[list[str]] = []
    for group in required_any:
        normalized_group = [str(token).strip().lower() for token in tuple(group or ()) if str(token).strip()]
        hits = [token for token in normalized_group if token in normalized]
        if hits:
            matched_groups.append(hits)
    return len(matched_groups), matched_groups


def _answer_satisfies_semantic_profile(answer_text: str, profile: dict[str, object]) -> tuple[bool, dict[str, object]]:
    answer_tokens = tuple(str(token).strip().lower() for token in tuple(profile.get("answer_tokens") or ()) if str(token).strip())
    minimum_context_matches = max(1, int(profile.get("minimum_context_matches") or 1))
    context_match_count, context_matches = _count_context_matches(answer_text, answer_tokens)
    required_any = tuple(tuple(group or ()) for group in tuple(profile.get("required_any") or ()))
    required_group_matches = max(0, int(profile.get("required_group_matches") or 0))
    group_match_count, matched_groups = _semantic_group_matches(answer_text, required_any)
    passed = context_match_count >= minimum_context_matches and group_match_count >= required_group_matches
    return passed, {
        "profile_id": str(profile.get("id") or ""),
        "context_match_count": int(context_match_count),
        "context_matches": list(context_matches),
        "required_group_matches": int(required_group_matches),
        "group_match_count": int(group_match_count),
        "matched_groups": list(matched_groups),
    }


def _parse_realtime_payload(payload: object) -> dict[str, object] | None:
    if payload is None:
        return None
    if isinstance(payload, (bytes, bytearray)):
        try:
            payload = bytes(payload).decode("utf-8", "ignore")
        except Exception:
            return None
    if not isinstance(payload, str):
        return None
    if not payload.strip():
        return None
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _wait_for_realtime_turn(
    context,
    slug: str,
    action,
    *,
    page=None,
    timeout_seconds: float = 35.0,
) -> dict[str, object]:
    state: dict[str, object] = {
        "done": False,
        "turn_id": "",
        "payload": {
            "answer": "",
            "audio_base64": "",
            "audio_chunks": [],
            "sources": [],
            "llm_model": "",
            "error": "",
            "audio_content_type": "",
        },
        "action_error": "",
    }

    def _handle_payload(parsed: dict[str, object] | None) -> None:
        if not parsed:
            return
        event_type = str(parsed.get("type", "")).strip()
        if event_type == "turn_complete":
            state["done"] = True
        elif event_type == "error":
            state["payload"]["error"] = str(parsed.get("message", "realtime_error"))
            state["done"] = True
        elif event_type == "cancelled":
            state["payload"]["error"] = str(parsed.get("message", "realtime_cancelled"))
            state["done"] = True
        elif event_type == "answer":
            state["payload"]["answer"] = str(parsed.get("text", "")).strip()
            if isinstance(parsed.get("sources"), list):
                state["payload"]["sources"] = list(parsed.get("sources"))
            if parsed.get("llm_model"):
                state["payload"]["llm_model"] = str(parsed.get("llm_model"))
        elif event_type == "audio":
            state["payload"]["audio_base64"] = str(parsed.get("audio_base64", ""))
            state["payload"]["audio_content_type"] = str(parsed.get("content_type", "audio/wav"))
        elif event_type == "audio_chunk":
            chunk = str(parsed.get("audio_base64", "")).strip()
            if chunk:
                payload = state.setdefault("payload", {})
                chunks = payload.get("audio_chunks")
                if not isinstance(chunks, list):
                    chunks = []
                    payload["audio_chunks"] = chunks
                chunks.append(chunk)
                state["payload_audio_chunks"] = chunks
                state["payload"]["audio_content_type"] = str(parsed.get("content_type", "audio/wav"))
        elif event_type == "audio_complete":
            state["payload"]["audio_content_type"] = str(parsed.get("content_type", "audio/wav"))
            collected = state.get("payload_audio_chunks")
            if isinstance(collected, list) and not str(state["payload"].get("audio_base64", "")).strip():
                state["payload"]["audio_base64"] = "".join(str(chunk) for chunk in collected)
            state.pop("payload_audio_chunks", None)
        if event_type in {"turn_complete", "error", "cancelled", "audio", "audio_complete", "answer", "audio_chunk"}:
            state["turn_id"] = str(parsed.get("turn_id", state.get("turn_id", "")) or "")

    def _on_frame(frame) -> None:
        _handle_payload(_parse_realtime_payload(getattr(frame, "payload", None)))

    def _on_websocket(socket) -> None:
        socket_url = str(getattr(socket, "url", "") or "")
        if f"/memorials/{slug}/realtime" not in socket_url:
            return
        socket.on("framereceived", _on_frame)

    context.on("websocket", _on_websocket)
    try:
        try:
            action()
        except Exception as exc:
            state["action_error"] = str(exc)
            raise
        deadline = time.perf_counter() + timeout_seconds
        seen_page_frame_count = 0
        while time.perf_counter() < deadline:
            if page is not None:
                try:
                    page_frames = page.evaluate(
                        "() => Array.isArray(window.__memorialRealtimeFrames) ? window.__memorialRealtimeFrames.slice() : []"
                    )
                except Exception:
                    page_frames = []
                if isinstance(page_frames, list):
                    for raw_frame in page_frames[seen_page_frame_count:]:
                        _handle_payload(_parse_realtime_payload(raw_frame))
                    seen_page_frame_count = len(page_frames)
            if bool(state.get("done")):
                break
            time.sleep(0.05)
        if not bool(state.get("done")):
            raise TimeoutError("timeout waiting for realtime turn_complete")
    finally:
        if hasattr(context, "off"):
            context.off("websocket", _on_websocket)
    return state


def _measure(base_url: str, slug: str, prompt_text: str, *, stub_transcribe: bool = True) -> dict[str, object]:
    sync_playwright = _require_playwright()
    audio_bytes = _synthesized_prompt_wav_bytes(prompt_text)
    audio_base64 = base64.b64encode(audio_bytes).decode("ascii")
    page_url = f"{base_url.rstrip('/')}/memorials/{slug}"
    warmup_url = f"{page_url}/warmup-status"
    semantic_profile = _semantic_profile_for_prompt(prompt_text)
    started = time.perf_counter()
    with sync_playwright() as playwright:  # pragma: no cover - exercised in live runs
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
        context = browser.new_context(viewport={"width": 1440, "height": 1100})
        context.add_init_script(_fake_media_init_script(audio_base64))
        if stub_transcribe:
            context.add_init_script(_realtime_stub_turn_init_script(prompt_text))
            stub_body = json.dumps(_transcribe_stub_payload(prompt_text), ensure_ascii=False)
            context.route(
                f"**/memorials/{slug}/speech-transcribe",
                lambda route: route.fulfill(status=200, content_type="application/json", body=stub_body),
            )
        page = context.new_page()
        try:
            response = page.goto(page_url, wait_until="domcontentloaded", timeout=45000)
            if response is None or not response.ok:
                raise SystemExit("page_load_failed")
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            load_ms = (time.perf_counter() - started) * 1000.0
            warmup_before = page.evaluate(
                """async (url) => {
                  const response = await fetch(url);
                  return response.json();
                }""",
                warmup_url,
            )
            ready_started = time.perf_counter()
            page.wait_for_function(
                """
                () => {
                  const button = document.getElementById("memorial-conversation");
                  return Boolean(button && !button.disabled && button.textContent && button.textContent.includes("Gespräch beginnen"));
                }
                """,
                timeout=10000,
            )
            cta_ready_ms = (time.perf_counter() - ready_started) * 1000.0
            answer_started = time.perf_counter()
            turn_error = ""
            answer_text = ""
            phase_text = ""
            detail_text = ""
            conversation_turn_payload: dict[str, object] | None = None
            ui_audio_play_calls = 0
            ui_audio_play_ended = 0
            ui_audio_play_error = ""
            ui_audio_ready = False
            try:
                turn_state = _wait_for_realtime_turn(
                    context,
                    slug,
                    lambda: page.click("#memorial-conversation", timeout=5000),
                    page=page,
                    timeout_seconds=35.0,
                )
                if not bool(turn_state.get("done")):
                    raise TimeoutError("realtime_turn_incomplete")
                payload_state = turn_state.get("payload")
                if isinstance(payload_state, dict):
                    conversation_turn_payload = dict(payload_state)
                else:
                    conversation_turn_payload = {
                        "payload_type": "unexpected",
                        "payload": str(payload_state or ""),
                    }
                page.wait_for_function(
                    """
                    () => {
                      const answer = document.getElementById("memorial-chat-answer");
                      const audio = document.getElementById("memorial-speech-audio");
                      const answerReady = Boolean(answer && answer.textContent && answer.textContent.trim().length > 0);
                      const audioReady = Boolean(audio && audio.getAttribute("src") && audio.getAttribute("src").startsWith("blob:"));
                      return answerReady || audioReady;
                    }
                    """,
                    timeout=35000,
                )
                try:
                    answer_text = page.eval_on_selector("#memorial-chat-answer", "node => node.textContent || ''")
                except Exception:
                    answer_text = ""
                phase_text = page.eval_on_selector("#memorial-speech-phase", "node => node.textContent || ''")
                detail_text = page.eval_on_selector("#memorial-speech-detail", "node => node.textContent || ''")
                ui_audio_src = page.eval_on_selector(
                    "#memorial-speech-audio",
                    "node => node && node.getAttribute('src') ? node.getAttribute('src') : ''",
                )
                ui_audio_ready = str(ui_audio_src or "").startswith("blob:")
                try:
                    page.wait_for_function(
                        """
                        () => Boolean(
                          window.__memorial_audio_gate &&
                          window.__memorial_audio_gate.play_calls > 0 &&
                          (window.__memorial_audio_gate.play_ended > 0 || window.__memorial_audio_gate.last_error)
                        )
                        """,
                        timeout=5000,
                    )
                except Exception:
                    pass
                gate_state = page.evaluate(
                    "() => window.__memorial_audio_gate || { play_calls: 0, play_ended: 0, last_error: \"\" }"
                )
                ui_audio_play_calls = int(gate_state.get("play_calls") or 0)
                ui_audio_play_ended = int(gate_state.get("play_ended") or 0)
                ui_audio_play_error = str(gate_state.get("last_error") or "")
                page.click("#memorial-conversation", timeout=5000)
                page.wait_for_function(
                    """
                    () => {
                      const button = document.getElementById("memorial-conversation");
                      return Boolean(button && button.textContent && button.textContent.includes("Gespräch beginnen"));
                    }
                    """,
                    timeout=10000,
                )
            except Exception as exc:
                turn_error = str(exc)
                try:
                    answer_text = page.eval_on_selector("#memorial-chat-answer", "node => node.textContent || ''")
                except Exception:
                    answer_text = ""
                try:
                    phase_text = page.eval_on_selector("#memorial-speech-phase", "node => node.textContent || ''")
                except Exception:
                    phase_text = ""
                try:
                    detail_text = page.eval_on_selector("#memorial-speech-detail", "node => node.textContent || ''")
                except Exception:
                    detail_text = ""
            first_answer_ms = (time.perf_counter() - answer_started) * 1000.0
            warmup_after = page.evaluate(
                """async (url) => {
                  const response = await fetch(url);
                  return response.json();
                }""",
                warmup_url,
            )
            payload = dict(conversation_turn_payload or {})
            answer_text_from_payload = str(payload.get("answer") or "").strip()
            if not answer_text:
                answer_text = answer_text_from_payload
            audio_base64 = str(payload.get("audio_base64") or "").strip()
            audio_chunks = payload.get("audio_chunks")
            audio_chunks_present = False
            if isinstance(audio_chunks, list):
                audio_chunks_present = any(str(chunk).strip() for chunk in audio_chunks)
            audio_payload_ready = bool(audio_base64 or audio_chunks_present)
            audio_unavailable = bool(payload.get("audio_unavailable"))

            if not turn_error:
                if not answer_text:
                    turn_error = "missing_answer"
                elif not audio_payload_ready and not audio_unavailable:
                    turn_error = "missing_audio_payload"
                elif not ui_audio_ready and not audio_unavailable:
                    turn_error = "missing_ui_audio_output"
                elif not ui_audio_play_calls:
                    turn_error = "missing_ui_audio_playback"
                elif not ui_audio_play_ended and not ui_audio_play_error:
                    turn_error = "missing_ui_audio_playback_complete"

            result = {
                "base_url": base_url,
                "slug": slug,
                "prompt_text": prompt_text,
                "page_load_ms": round(load_ms, 1),
                "cta_ready_ms": round(cta_ready_ms, 1),
                "first_answer_ms": round(first_answer_ms, 1),
                "speech_transcribe_mode": "transcript_injected" if stub_transcribe else "live",
                "warmup_status_before": warmup_before,
                "warmup_status_after": warmup_after,
                "semantic_profile_id": str(semantic_profile.get("id") or ""),
                "answer_preview": str(answer_text).strip()[:240],
                "answer_context_match_count": 0,
                "answer_context_matches": [],
                "answer_semantic_group_match_count": 0,
                "answer_semantic_matched_groups": [],
                "answer_semantic_passed": False,
                "phase_text": str(phase_text).strip(),
                "detail_text": str(detail_text).strip(),
                "turn_error": turn_error[:240],
                "conversation_turn_payload": payload,
                "audio_ready_for_ui": bool(ui_audio_ready),
                "audio_payload_ready": bool(audio_payload_ready),
                "audio_unavailable": bool(audio_unavailable),
                "ui_audio_play_calls": int(ui_audio_play_calls),
                "ui_audio_play_ended": int(ui_audio_play_ended),
                "ui_audio_play_error": str(ui_audio_play_error),
            }
            context_match_count, context_matches = _count_context_matches(
                result["answer_preview"],
                DEFAULT_EXIT_GATE_CONTEXT_TOKENS,
            )
            result["answer_context_match_count"] = int(context_match_count)
            result["answer_context_matches"] = list(context_matches)
            semantic_passed, semantic_details = _answer_satisfies_semantic_profile(
                result["answer_preview"],
                semantic_profile,
            )
            result["semantic_profile_id"] = str(semantic_details.get("profile_id") or result["semantic_profile_id"])
            result["answer_context_match_count"] = int(semantic_details.get("context_match_count") or result["answer_context_match_count"])
            result["answer_context_matches"] = list(semantic_details.get("context_matches") or result["answer_context_matches"])
            result["answer_semantic_group_match_count"] = int(semantic_details.get("group_match_count") or 0)
            result["answer_semantic_matched_groups"] = list(semantic_details.get("matched_groups") or [])
            result["answer_semantic_passed"] = bool(semantic_passed)
        finally:
            context.close()
            browser.close()
    return result


def _with_exit_gate_status(
    result: dict[str, object],
    *,
    exit_gate: bool,
    gold_mode: bool,
    require_public_origin: bool,
    max_first_answer_ms: float,
) -> dict[str, object]:
    reasons: list[str] = []
    if result.get("turn_error"):
        reasons.append(str(result.get("turn_error") or "missing_gate_feedback"))
    elif not str(result.get("answer_preview") or "").strip():
        reasons.append("missing_answer_preview")
    if not bool(result.get("audio_payload_ready")):
        reasons.append("missing_audio_payload")
    if not bool(result.get("audio_ready_for_ui")):
        reasons.append("missing_ui_audio_output")
    if not bool(result.get("ui_audio_play_calls")):
        reasons.append("missing_ui_audio_playback")
    if not bool(result.get("ui_audio_play_ended")) and not result.get("ui_audio_play_error"):
        reasons.append("missing_ui_audio_playback_complete")
    if float(result.get("first_answer_ms") or 0.0) > float(max_first_answer_ms):
        reasons.append("first_answer_too_slow")
    if not bool(result.get("answer_semantic_passed")):
        reasons.append("answer_semantics_failed")
    if require_public_origin and _is_local_base_url(str(result.get("base_url") or "")):
        reasons.append("public_origin_required")
    if gold_mode and _git_dirty():
        reasons.append("dirty_worktree")

    payload = dict(result)
    payload.update(
        {
            "contract_name": "ea.memorial_realtime_browser_exit_gate",
            "generated_at": _utc_now(),
            "generated_by": "scripts/measure_memorial_live_browser.py",
            "git_head": _git_head(),
            "dirty_worktree": _git_dirty(),
            "status": "pass" if not reasons else "fail",
            "exit_gate": bool(exit_gate),
            "gold_mode": bool(gold_mode),
            "require_public_origin": bool(require_public_origin),
            "max_first_answer_ms": float(max_first_answer_ms),
            "failed_codes": reasons,
            "gold_claim_allowed": bool(gold_mode) and not reasons,
        }
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure the live memorial browser first-turn path.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8090")
    parser.add_argument("--slug", default="manfred")
    parser.add_argument("--prompt-text", default=LIVE_PROMPT_TEXT)
    parser.add_argument("--output", default="")
    parser.add_argument("--exit-gate", action="store_true", help="Exit with failure if turn lacks answer/audio output.")
    parser.add_argument("--real-stt", action="store_true", help="Use the live STT endpoint instead of a deterministic browser stub.")
    parser.add_argument("--gold-mode", action="store_true", help="Write a stricter memorial browser-gold receipt.")
    parser.add_argument("--require-public-origin", action="store_true", help="Fail gold/browser proof on localhost origins.")
    parser.add_argument("--max-first-answer-ms", type=float, default=0.0)
    args = parser.parse_args()

    result = _measure(args.base_url, args.slug, args.prompt_text, stub_transcribe=not args.real_stt)
    max_first_answer_ms = float(args.max_first_answer_ms or (DEFAULT_GOLD_MAX_FIRST_ANSWER_MS if args.gold_mode else DEFAULT_EXIT_GATE_MAX_FIRST_ANSWER_MS))
    receipt = _with_exit_gate_status(
        result,
        exit_gate=bool(args.exit_gate),
        gold_mode=bool(args.gold_mode),
        require_public_origin=bool(args.require_public_origin),
        max_first_answer_ms=max_first_answer_ms,
    )
    rendered = json.dumps(receipt, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if args.exit_gate:
        if receipt["status"] == "pass":
            print("EXIT_GATE_PASS")
            return 0
        print(f"EXIT_GATE_FAIL: {'; '.join(str(item) for item in receipt['failed_codes'])}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
