#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
ENV_FILES = (ROOT / "ea" / ".env", ROOT / ".env")
PLAYWRIGHT_IMAGE = os.environ.get("EA_UI_PLAYWRIGHT_IMAGE", "chummer-playwright:local").strip() or "chummer-playwright:local"
DEFAULT_OUT_DIR = Path(os.environ.get("EA_UNMIXR_PROVIDER_OUT_DIR") or ROOT / "ea" / "_completion" / "unmixr_provider")
DEFAULT_REFERENCE_AUDIO = (
    ROOT
    / "memorial_data"
    / "private_memorial_profiles"
    / "manfred"
    / "voice_profile"
    / "curated"
    / "youtube-alt-60.wav"
)
DEFAULT_VOICE_LABEL = "ManfredHozaR2"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _slugify(value: object) -> str:
    lowered = "".join(char.lower() if char.isalnum() else "-" for char in str(value or "").strip())
    lowered = "-".join(part for part in lowered.split("-") if part)
    return lowered or f"unmixr-{uuid.uuid4().hex[:12]}"


def _env_value(name: str) -> str:
    direct = str(os.environ.get(name) or "").strip()
    if direct:
        return direct
    for env_file in ENV_FILES:
        if not env_file.is_file():
            continue
        for raw_line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == name:
                return value.strip()
    return ""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_count(text: str, pattern: str) -> int:
    match = re.search(pattern, str(text or ""), re.IGNORECASE)
    if not match:
        return -1
    try:
        return int(match.group(1))
    except Exception:
        return -1


def _summarize(body_text: str) -> dict[str, object]:
    monthly_used = -1
    monthly_limit = -1
    monthly_match = re.search(r"Monthly profiles\s+(\d+)\s*/\s*(\d+)", str(body_text or ""), re.IGNORECASE)
    if monthly_match:
        try:
            monthly_used = int(monthly_match.group(1))
            monthly_limit = int(monthly_match.group(2))
        except Exception:
            monthly_used = -1
            monthly_limit = -1
    return {
        "monthly_used": monthly_used,
        "monthly_limit": monthly_limit,
        "remaining": _parse_count(body_text, r"Remaining\s+(\d+)"),
        "saved_voices": _parse_count(body_text, r"Saved voices\s+(\d+)"),
        "no_voice_clones_found": "No voice clones found." in str(body_text or ""),
        "limit_banner_present": "reached the limit" in str(body_text or "").lower(),
    }


def _probe_unmixr_runtime(*, voice_ids: list[str], text: str = "Ja. Ich bin da.") -> list[dict[str, object]]:
    api_key = _env_value("UNMIXR_API_KEY")
    if not api_key:
        return []
    probes: list[dict[str, object]] = []
    headers = {"Authorization": f"Bearer {api_key}"}
    for voice_id in [str(item or "").strip() for item in voice_ids if str(item or "").strip()]:
        payload = {
            "text": text,
            "voice_id": voice_id,
            "language": "de",
            "response_type": "url",
            "speaking_rate": "medium",
            "speaking_pitch": "medium",
            "speaking_volume": "low",
        }
        record: dict[str, object] = {"voice_id": voice_id}
        try:
            response = requests.post(
                "https://unmixr.com/api/v1/short-tts/",
                headers=headers,
                json=payload,
                timeout=60,
            )
            record["status_code"] = int(response.status_code)
            try:
                body = response.json()
            except Exception:
                body = {}
            if isinstance(body, dict):
                record["success"] = bool(body.get("success"))
                record["provider_code"] = body.get("code")
                record["message"] = str(body.get("message") or body.get("detail") or body.get("error") or "").strip()
                audio_url = str(body.get("audio_url") or "").strip()
                if audio_url:
                    record["audio_url"] = audio_url
                    record["runtime_ready"] = True
                else:
                    record["runtime_ready"] = False
            else:
                record["success"] = False
                record["runtime_ready"] = False
                record["message"] = str(response.text or "").strip()[:500]
        except requests.RequestException as exc:
            record["success"] = False
            record["runtime_ready"] = False
            record["message"] = f"{type(exc).__name__}"
        probes.append(record)
    return probes


def _node_script() -> str:
    return r"""
const { chromium } = require('playwright');
const fs = require('fs');

async function main() {
  const packet = JSON.parse(fs.readFileSync(process.env.UNMIXR_PACKET_PATH, 'utf8'));
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1200 },
  });
  const page = await context.newPage();
  const result = {
    mode: 'clone',
    captured_at: new Date().toISOString(),
    voice_label: String(packet.voice_label || ''),
    reference_audio_path: String(packet.reference_audio_path || ''),
    url: '',
    title: '',
    body_text: '',
    errors: [],
    warnings: [],
    monthly_profiles_text: '',
    saved_voices_text: '',
    remaining_text: '',
    clone_names: [],
    api_hits: [],
    discovered_voice_ids: [],
    discovered_profile_ids: [],
    clone_visible: false,
    clone_submit_clicked: false,
    clone_created: false,
    ui_limit_blocked: false,
    ui_limit_detail: '',
  };

  async function wait(ms) {
    await page.waitForTimeout(Number(ms || 1000));
  }

  function collectIdsFromText(raw, voiceLabel) {
    const text = String(raw || '');
    const ids = [];
    const profileIds = [];
    const voiceRegexes = [
      /"voice_id"\s*:\s*"([0-9a-f-]{36})"/ig,
      /"id"\s*:\s*"([0-9a-f-]{36})"/ig,
      /\/voice\/([0-9a-f-]{36})\//ig,
    ];
    const profileRegexes = [
      /\/voiceprofile\/([0-9a-f-]{36})-/ig,
      /"profile_id"\s*:\s*"([0-9a-f-]{36})"/ig,
      /"voice_cloning_profile_id"\s*:\s*"([0-9a-f-]{36})"/ig,
    ];
    for (const pattern of voiceRegexes) {
      for (const match of text.matchAll(pattern)) {
        const value = String(match[1] || '').trim();
        if (value && !ids.includes(value)) ids.push(value);
      }
    }
    for (const pattern of profileRegexes) {
      for (const match of text.matchAll(pattern)) {
        const value = String(match[1] || '').trim();
        if (value && !profileIds.includes(value)) profileIds.push(value);
      }
    }
    if (voiceLabel && text.toLowerCase().includes(String(voiceLabel).toLowerCase())) {
      result.discovered_voice_ids = Array.from(new Set([...(result.discovered_voice_ids || []), ...ids])).slice(0, 20);
      result.discovered_profile_ids = Array.from(new Set([...(result.discovered_profile_ids || []), ...profileIds])).slice(0, 20);
    }
  }

  async function collectBody() {
    return String((await page.locator('body').innerText().catch(() => '')) || '');
  }

  async function clickIfPresent(locator) {
    if (await locator.count()) {
      await locator.first().click({ force: true }).catch(() => {});
      return true;
    }
    return false;
  }

  async function maybeLogin() {
    await page.goto('https://app.unmixr.com/voice-cloning', { waitUntil: 'domcontentloaded', timeout: 120000 }).catch(() => {});
    await wait(2000);
    const emailField = page.locator("input[type=email], input[name=email], input[autocomplete='email'], input[autocomplete='username']").first();
    if (await emailField.count()) {
      await emailField.fill(String(packet.login_email || ''));
      const passwordField = page.locator("input[type=password], input[name=password], input[autocomplete='current-password']").first();
      if (await passwordField.count()) {
        await passwordField.fill(String(packet.login_password || ''));
      }
      const submitButton = page.locator("form button[type=submit], form input[type=submit], button:has-text('Sign In'), button:has-text('Log In'), button:has-text('Login'), button:has-text('Continue')").first();
      if (await submitButton.count()) {
        await submitButton.click({ force: true }).catch(() => {});
      }
      await wait(8000);
      await page.goto('https://app.unmixr.com/voice-cloning', { waitUntil: 'domcontentloaded', timeout: 120000 }).catch(() => {});
      await wait(4000);
    }
  }

  async function acceptDisclaimerMaybe() {
    const agreeButton = page.getByRole('button', { name: /^AGREE$/i }).first();
    if (await agreeButton.count()) {
      await agreeButton.click({ force: true }).catch(() => {});
      await wait(1500);
    }
  }

  async function fillVisibleMetadata() {
    const visibleInputs = await page.locator('input').evaluateAll((nodes) => {
      return nodes.map((node, index) => {
        const style = window.getComputedStyle(node);
        const rect = node.getBoundingClientRect();
        return {
          index,
          type: String(node.getAttribute('type') || 'text').toLowerCase(),
          name: String(node.getAttribute('name') || ''),
          placeholder: String(node.getAttribute('placeholder') || ''),
          visible: !(style.display === 'none' || style.visibility === 'hidden') && rect.width > 0 && rect.height > 0,
        };
      });
    }).catch(() => []);
    const candidateIndexes = visibleInputs
      .filter((entry) => entry.visible && ['text', 'search', ''].includes(String(entry.type || '')))
      .map((entry) => Number(entry.index));
    if (candidateIndexes.length) {
      await page.locator('input').nth(candidateIndexes[0]).fill(String(packet.voice_label || ''));
      await wait(300);
    }
    const textareas = page.locator('textarea');
    if (await textareas.count()) {
      await textareas.first().fill(String(packet.description || ''));
      await wait(300);
    } else if (candidateIndexes.length >= 2) {
      await page.locator('input').nth(candidateIndexes[1]).fill(String(packet.description || ''));
      await wait(300);
    }
  }

  async function collectCloneNames() {
    const body = await collectBody();
    const lines = body.split(/\n+/).map((line) => String(line || '').trim()).filter(Boolean);
    const names = [];
    for (let index = 0; index < lines.length; index += 1) {
      if (/saved voices/i.test(lines[index])) continue;
      if (/No voice clones found\./i.test(lines[index])) continue;
      if (/^supported languages$/i.test(lines[index])) break;
      if (/^Your Voices$/i.test(lines[index])) {
        for (let inner = index + 1; inner < lines.length; inner += 1) {
          const value = lines[inner];
          if (!value || /^supported languages$/i.test(value)) break;
          if (/^\d+\s*(saved voices)?$/i.test(value)) continue;
          if (!names.includes(value)) names.push(value);
        }
        break;
      }
    }
    return names.slice(0, 24);
  }

  try {
    page.on('response', async (response) => {
      try {
        const url = String(response.url() || '');
        const lower = url.toLowerCase();
        if (!(lower.includes('/api/') || lower.includes('/voice') || lower.includes('/clone'))) return;
        const contentType = String(response.headers()['content-type'] || '');
        if (!contentType.includes('application/json')) return;
        const bodyText = await response.text().catch(() => '');
        result.api_hits.push({
          url,
          status: Number(response.status() || 0),
          body_excerpt: String(bodyText || '').slice(0, 2000),
        });
        collectIdsFromText(bodyText, packet.voice_label || '');
      } catch (error) {}
    });
    await maybeLogin();
    await acceptDisclaimerMaybe();
    await wait(1500);
    const uploadButton = page.getByRole('button', { name: /Upload Audio/i }).first();
    await clickIfPresent(uploadButton);
    await wait(1200);
    const fileInput = page.locator('input[type=file]').first();
    if (!(await fileInput.count())) {
      throw new Error('unmixr_clone_file_input_missing');
    }
    await fileInput.setInputFiles(String(packet.reference_audio_path || ''));
    await wait(4000);
    await fillVisibleMetadata();
    const submitButton = page.getByRole('button', { name: /^Submit$/i }).first();
    if (!(await submitButton.count())) {
      throw new Error('unmixr_clone_submit_missing');
    }
    await submitButton.click({ force: true }).catch(() => {});
    result.clone_submit_clicked = true;
    await wait(15000);
    result.url = String(page.url() || '');
    result.title = String((await page.title().catch(() => '')) || '');
    result.body_text = await collectBody();
    result.clone_names = await collectCloneNames();
    result.clone_visible = result.clone_names.some((name) => String(name || '').toLowerCase() === String(packet.voice_label || '').toLowerCase());
    result.clone_created = result.clone_visible;
    collectIdsFromText(result.body_text, packet.voice_label || '');
    const bodyLower = result.body_text.toLowerCase();
    if (bodyLower.includes('reached the limit')) {
      result.ui_limit_blocked = true;
      result.ui_limit_detail = 'reached_the_limit';
    }
    const monthlyMatch = result.body_text.match(/Monthly profiles\s+(\d+\s*\/\s*\d+)/i);
    if (monthlyMatch) result.monthly_profiles_text = String(monthlyMatch[1] || '');
    const remainingMatch = result.body_text.match(/Remaining\s+(\d+)/i);
    if (remainingMatch) result.remaining_text = String(remainingMatch[1] || '');
    const savedMatch = result.body_text.match(/Saved voices\s+(\d+)/i);
    if (savedMatch) result.saved_voices_text = String(savedMatch[1] || '');
    await page.screenshot({ path: process.env.UNMIXR_SCREENSHOT_PATH, fullPage: true }).catch((error) => {
      result.warnings.push(`screenshot:${String(error && error.message ? error.message : error)}`);
    });
    fs.writeFileSync(process.env.UNMIXR_HTML_PATH, await page.content(), 'utf8');
    console.log(JSON.stringify(result));
    await browser.close();
  } catch (error) {
    result.url = String(page.url() || '');
    result.title = String((await page.title().catch(() => '')) || '');
    result.body_text = await collectBody().catch(() => '');
    result.errors.push(String(error && error.stack ? error.stack : error));
    await page.screenshot({ path: process.env.UNMIXR_SCREENSHOT_PATH, fullPage: true }).catch(() => {});
    fs.writeFileSync(process.env.UNMIXR_HTML_PATH, await page.content().catch(() => ''), 'utf8');
    console.log(JSON.stringify(result));
    await browser.close();
    process.exit(1);
  }
}

main().catch((error) => {
  console.log(JSON.stringify({
    mode: 'clone',
    captured_at: new Date().toISOString(),
    voice_label: '',
    reference_audio_path: '',
    url: '',
    title: '',
    body_text: '',
    errors: [String(error && error.stack ? error.stack : error)],
    warnings: [],
    monthly_profiles_text: '',
    saved_voices_text: '',
    remaining_text: '',
    clone_names: [],
    clone_visible: false,
    clone_submit_clicked: false,
    clone_created: false,
    ui_limit_blocked: false,
    ui_limit_detail: '',
  }));
  process.exit(1);
});
"""


def _run_playwright(packet: dict[str, object], *, temp_dir: Path, timeout_seconds: int) -> dict[str, object]:
    packet_path = temp_dir / "packet.json"
    result_path = temp_dir / "result.json"
    screenshot_path = temp_dir / "preview.png"
    html_path = temp_dir / "result.html"
    packet_path.write_text(json.dumps(packet, ensure_ascii=True), encoding="utf-8")
    command = [
        "docker",
        "run",
        "--rm",
        "-i",
        "-v",
        f"{temp_dir}:{temp_dir}",
        "-e",
        f"UNMIXR_PACKET_PATH={packet_path}",
        "-e",
        f"UNMIXR_RESULT_PATH={result_path}",
        "-e",
        f"UNMIXR_SCREENSHOT_PATH={screenshot_path}",
        "-e",
        f"UNMIXR_HTML_PATH={html_path}",
        PLAYWRIGHT_IMAGE,
        "node",
        "-",
    ]
    env = os.environ.copy()
    env.update(
        {
            "UNMIXR_PACKET_PATH": str(packet_path),
            "UNMIXR_RESULT_PATH": str(result_path),
            "UNMIXR_SCREENSHOT_PATH": str(screenshot_path),
            "UNMIXR_HTML_PATH": str(html_path),
        }
    )
    completed = subprocess.run(
        command,
        input=_node_script(),
        text=True,
        capture_output=True,
        env=env,
        timeout=max(240, int(timeout_seconds) + 120),
        check=False,
    )
    raw = str(completed.stdout or "").strip()
    if not raw:
        raise RuntimeError(f"unmixr_browseract_clone_empty_output:{str(completed.stderr or '').strip()[:400]}")
    payload = json.loads(raw.splitlines()[-1])
    if not isinstance(payload, dict):
        raise RuntimeError("unmixr_browseract_clone_invalid_output")
    payload["_worker_exit_code"] = int(completed.returncode)
    payload["screenshot_path"] = str(screenshot_path)
    payload["html_path"] = str(html_path)
    return payload


def attempt_clone(
    *,
    login_email: str,
    login_password: str,
    reference_audio_path: Path,
    voice_label: str,
    description: str,
    output_dir: Path,
    timeout_seconds: int,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    run_slug = f"{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{_slugify(voice_label)}"
    run_dir = output_dir / run_slug
    run_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="unmixr-browseract-clone-") as temp_dir_raw:
        temp_dir = Path(temp_dir_raw)
        staged_audio_path = temp_dir / reference_audio_path.name
        shutil.copy2(reference_audio_path, staged_audio_path)
        packet = {
            "login_email": login_email,
            "login_password": login_password,
            "reference_audio_path": str(staged_audio_path),
            "voice_label": voice_label,
            "description": description,
        }
        worker = _run_playwright(packet, temp_dir=temp_dir, timeout_seconds=timeout_seconds)
        temp_screenshot_path = Path(str(worker.get("screenshot_path") or "")).expanduser()
        temp_html_path = Path(str(worker.get("html_path") or "")).expanduser()
        persisted_screenshot_path = run_dir / "workspace.png"
        persisted_html_path = run_dir / "workspace.html"
        if temp_screenshot_path.is_file():
            shutil.copy2(temp_screenshot_path, persisted_screenshot_path)
        if temp_html_path.is_file():
            shutil.copy2(temp_html_path, persisted_html_path)
    summary = {
        "captured_at": _utc_now(),
        "provider_key": "unmixr",
        "mode": "browseract_ui_clone_attempt",
        "voice_label": voice_label,
        "reference_audio_path": str(reference_audio_path),
        "reference_audio_sha256": _sha256_file(reference_audio_path),
        "reference_audio_size_bytes": reference_audio_path.stat().st_size,
        "worker_exit_code": int(worker.get("_worker_exit_code") or 0),
        "url": str(worker.get("url") or "").strip(),
        "title": str(worker.get("title") or "").strip(),
        "clone_submit_clicked": bool(worker.get("clone_submit_clicked")),
        "clone_created": bool(worker.get("clone_created")),
        "clone_visible": bool(worker.get("clone_visible")),
        "clone_names": list(worker.get("clone_names") or []),
        "ui_limit_blocked": bool(worker.get("ui_limit_blocked")),
        "ui_limit_detail": str(worker.get("ui_limit_detail") or "").strip(),
        "monthly_profiles_text": str(worker.get("monthly_profiles_text") or "").strip(),
        "remaining_text": str(worker.get("remaining_text") or "").strip(),
        "saved_voices_text": str(worker.get("saved_voices_text") or "").strip(),
        "warnings": list(worker.get("warnings") or []),
        "errors": list(worker.get("errors") or []),
        "api_hits": list(worker.get("api_hits") or []),
        "discovered_voice_ids": list(worker.get("discovered_voice_ids") or []),
        "discovered_profile_ids": list(worker.get("discovered_profile_ids") or []),
        "runtime_probes": _probe_unmixr_runtime(voice_ids=list(worker.get("discovered_profile_ids") or [])),
        "body_excerpt": str(worker.get("body_text") or "").strip()[:8000],
        "screenshot_path": str((run_dir / "workspace.png").resolve()) if (run_dir / "workspace.png").is_file() else str(worker.get("screenshot_path") or "").strip(),
        "html_path": str((run_dir / "workspace.html").resolve()) if (run_dir / "workspace.html").is_file() else str(worker.get("html_path") or "").strip(),
        "slot_summary": _summarize(str(worker.get("body_text") or "")),
    }
    output_path = run_dir / "report.json"
    output_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"report_path": str(output_path), "summary": summary}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Attempt a real Unmixr UI clone via BrowserAct/Playwright automation.")
    parser.add_argument("--login-email", default="")
    parser.add_argument("--login-password", default="")
    parser.add_argument("--reference-audio", default=str(DEFAULT_REFERENCE_AUDIO))
    parser.add_argument("--voice-label", default=DEFAULT_VOICE_LABEL)
    parser.add_argument("--description", default="Memorial voice refresh candidate for Manfred Hoza.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--timeout-seconds", type=int, default=180)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    login_email = str(args.login_email or "").strip() or _env_value("UNMIXR_USERNAME") or _env_value("BROWSERACT_USERNAME")
    login_password = str(args.login_password or "").strip() or _env_value("UNMIXR_PASSWORD") or _env_value("BROWSERACT_PASSWORD")
    if not login_email:
        raise SystemExit("unmixr_login_email_missing")
    if not login_password:
        raise SystemExit("unmixr_login_password_missing")
    reference_audio_path = Path(str(args.reference_audio or DEFAULT_REFERENCE_AUDIO)).expanduser()
    if not reference_audio_path.is_file():
        raise SystemExit(f"unmixr_reference_audio_missing:{reference_audio_path}")
    result = attempt_clone(
        login_email=login_email,
        login_password=login_password,
        reference_audio_path=reference_audio_path,
        voice_label=str(args.voice_label or DEFAULT_VOICE_LABEL).strip() or DEFAULT_VOICE_LABEL,
        description=str(args.description or "").strip(),
        output_dir=Path(str(args.output_dir or DEFAULT_OUT_DIR)).expanduser(),
        timeout_seconds=max(60, int(args.timeout_seconds or 180)),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
