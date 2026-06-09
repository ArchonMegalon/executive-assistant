#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import io
import math
import shutil
import struct
import subprocess
import tempfile
import time
import wave
from pathlib import Path


LIVE_PROMPT_TEXT = "Hallo Manfred, kannst du jetzt mit mir sprechen?"


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
  const wavBlob = new Blob([wavBytes], {{ type: "audio/webm" }});

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
      this.mimeType = "audio/webm";
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
      }}, 40);
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
  HTMLMediaElement.prototype.play = function play() {{
    return new Promise((resolve) => {{
      setTimeout(() => {{
        this.dispatchEvent(new Event("ended"));
        resolve();
      }}, 40);
    }});
  }};
}})();
"""


def _transcribe_stub_payload(prompt_text: str) -> dict[str, object]:
    return {
        "transcription_status": "transcribed",
        "transcript_text": str(prompt_text or "").strip(),
        "transcriber": "playwright_stub",
    }


def _measure(base_url: str, slug: str, prompt_text: str, *, stub_transcribe: bool = True) -> dict[str, object]:
    sync_playwright = _require_playwright()
    audio_bytes = _synthesized_prompt_wav_bytes(prompt_text)
    audio_base64 = base64.b64encode(audio_bytes).decode("ascii")
    page_url = f"{base_url.rstrip('/')}/memorials/{slug}"
    warmup_url = f"{page_url}/warmup-status"
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
            try:
                with page.expect_response(
                    lambda response: response.url.endswith(f"/memorials/{slug}/conversation-turn") and response.status == 200,
                    timeout=35000,
                ):
                    page.click("#memorial-conversation", timeout=5000)
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
                answer_text = page.eval_on_selector("#memorial-chat-answer", "node => node.textContent || ''")
                phase_text = page.eval_on_selector("#memorial-speech-phase", "node => node.textContent || ''")
                detail_text = page.eval_on_selector("#memorial-speech-detail", "node => node.textContent || ''")
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
                "answer_preview": str(answer_text).strip()[:240],
                "phase_text": str(phase_text).strip(),
                "detail_text": str(detail_text).strip(),
                "turn_error": turn_error[:240],
            }
        finally:
            context.close()
            browser.close()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure the live memorial browser first-turn path.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8090")
    parser.add_argument("--slug", default="manfred")
    parser.add_argument("--prompt-text", default=LIVE_PROMPT_TEXT)
    parser.add_argument("--output", default="")
    parser.add_argument("--real-stt", action="store_true", help="Use the live STT endpoint instead of a deterministic browser stub.")
    args = parser.parse_args()

    result = _measure(args.base_url, args.slug, args.prompt_text, stub_transcribe=not args.real_stt)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
