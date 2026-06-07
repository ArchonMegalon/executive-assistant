#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
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


def _synthesized_prompt_wav_bytes(text: str) -> bytes:
    _require_binary("espeak-ng")
    _require_binary("ffmpeg")
    with tempfile.TemporaryDirectory(prefix="memorial-live-browser-") as tmpdir:
        tmp_path = Path(tmpdir)
        raw_wav = tmp_path / "speech.raw.wav"
        normalized_wav = tmp_path / "speech.16k.wav"
        subprocess.run(
            [
                "espeak-ng",
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
                "ffmpeg",
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
      this.mimeType = "audio/wav";
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
      }}, 0);
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
}})();
"""


def _measure(base_url: str, slug: str, prompt_text: str) -> dict[str, object]:
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
        page = context.new_page()
        try:
            response = page.goto(page_url, wait_until="networkidle")
            if response is None or not response.ok:
                raise SystemExit("page_load_failed")
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
            page.click("#memorial-conversation")
            answer_started = time.perf_counter()
            page.wait_for_function(
                """
                () => {
                  const answer = document.getElementById("memorial-chat-answer");
                  return Boolean(answer && answer.textContent && answer.textContent.trim().length > 0);
                }
                """,
                timeout=30000,
            )
            first_answer_ms = (time.perf_counter() - answer_started) * 1000.0
            answer_text = page.eval_on_selector("#memorial-chat-answer", "node => node.textContent || ''")
            phase_text = page.eval_on_selector("#memorial-speech-phase", "node => node.textContent || ''")
            detail_text = page.eval_on_selector("#memorial-speech-detail", "node => node.textContent || ''")
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
                "warmup_status_before": warmup_before,
                "warmup_status_after": warmup_after,
                "answer_preview": str(answer_text).strip()[:240],
                "phase_text": str(phase_text).strip(),
                "detail_text": str(detail_text).strip(),
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
    args = parser.parse_args()

    result = _measure(args.base_url, args.slug, args.prompt_text)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
