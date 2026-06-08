#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENV_FILES = (ROOT / "ea" / ".env", ROOT / ".env")
PLAYWRIGHT_IMAGE = os.environ.get("EA_UI_PLAYWRIGHT_IMAGE", "chummer-playwright:local").strip() or "chummer-playwright:local"
_OUTPUT_ROOT_CANDIDATES = (
    Path("/docker/fleet/state/chummer6/voicewave_provider"),
    Path("/mnt/pcloud/EA/voicewave_provider"),
    Path("/data/artifacts/voicewave_provider"),
    Path("/tmp/voicewave_provider"),
)
_SHARED_TEMP_ROOT_CANDIDATES = (
    Path(os.environ.get("EA_UI_SERVICE_SHARED_TEMP_ROOT", "/docker/fleet/state/browseract_ui_worker_shared")).expanduser(),
    Path("/mnt/pcloud/EA/browseract_ui_worker_shared"),
    Path("/tmp/browseract_ui_worker_shared"),
)
DEFAULT_VOICE_LABEL = "Manfred Hoza Memorial"
DEFAULT_REFERENCE_AUDIO = (
    ROOT
    / "memorial_data"
    / "private_memorial_profiles"
    / "manfred"
    / "voice_profile"
    / "optimization"
    / "candidates"
    / "oSQ9FhFc4YI-01440s-28.wav"
)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _slugify(value: object) -> str:
    lowered = "".join(char.lower() if char.isalnum() else "-" for char in str(value or "").strip())
    lowered = "-".join(part for part in lowered.split("-") if part)
    return lowered or f"voicewave-{uuid.uuid4().hex[:12]}"


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


def _first_writable_dir(candidates: tuple[Path, ...]) -> Path:
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        return candidate
    raise SystemExit("voicewave_runtime_storage_unavailable")


OUTPUT_ROOT = _first_writable_dir(_OUTPUT_ROOT_CANDIDATES)
SHARED_TEMP_ROOT = _first_writable_dir(_SHARED_TEMP_ROOT_CANDIDATES)


def _login_email(value: str) -> str:
    return value.strip() or _env_value("VOICEWAVE_LOGIN_EMAIL")


def _login_password(value: str) -> str:
    return value.strip() or _env_value("VOICEWAVE_LOGIN_PASSWORD")


def _default_reference_audio(slug: str) -> Path:
    if slug.strip().lower() == "manfred" and DEFAULT_REFERENCE_AUDIO.is_file():
        return DEFAULT_REFERENCE_AUDIO
    raise SystemExit(f"voicewave_reference_audio_missing_for_slug:{slug.strip() or 'unknown'}")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _voicewave_node_script() -> str:
    return r"""
const { chromium } = require('playwright');
const fs = require('fs');

async function main() {
  const packet = JSON.parse(fs.readFileSync(process.env.VOICEWAVE_PACKET_PATH, 'utf8'));
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1200 },
    acceptDownloads: true,
  });
  const page = await context.newPage();
  const result = {
    mode: String(packet.mode || ''),
    url: '',
    title: '',
    bodyText: '',
    selectedVoiceBefore: '',
    selectedVoiceAfter: '',
    cloneVisible: false,
    cloneCountLabel: '',
    cloneNames: [],
    cloneAlreadyPresent: false,
    requestedVoiceLabel: String(packet.voice_label || ''),
    downloadSuggestedFilename: '',
    downloaded: false,
    errors: [],
    warnings: [],
  };
  const emailSel = "input[type=email], input[name=email], input[autocomplete='email'], input[autocomplete='username']";
  const passSel = "input[type=password], input[name=password], input[autocomplete='current-password']";

  async function wait(ms) {
    await page.waitForTimeout(Number(ms || 1000));
  }

  async function loginMaybe() {
    await page.goto('https://www.voicewave.ai/signin', { waitUntil: 'domcontentloaded', timeout: 120000 }).catch(() => {});
    await wait(3000);
    if (await page.locator(emailSel).count()) {
      await page.locator(emailSel).first().fill(String(packet.login_email || ''));
      await page.locator(passSel).first().fill(String(packet.login_password || ''));
      const button = page.locator("form button[type=submit], button:has-text('Sign In'), button:has-text('Log In'), button:has-text('Login'), button:has-text('Continue')").first();
      if (await button.count()) {
        await button.click({ force: true }).catch(() => {});
      }
    }
    await wait(8000);
    await page.goto('https://space.voicewave.ai/', { waitUntil: 'domcontentloaded', timeout: 120000 }).catch(() => {});
    await wait(4000);
  }

  async function selectedVoiceText() {
    return String(await page.locator('button[aria-label*="Select voice." i]').first().innerText().catch(() => '') || '').trim();
  }

  async function openVoiceDialog() {
    const trigger = page.locator('button[aria-label*="Select voice." i]').first();
    await trigger.click({ force: true }).catch(() => {});
    await wait(1200);
    return page.locator('[role=dialog]').first();
  }

  async function collectCloneNames(dialog) {
    return await dialog.evaluate((node) => {
      const text = String(node.innerText || node.textContent || '');
      const lines = text.split(/\n+/).map((line) => line.trim()).filter(Boolean);
      const names = [];
      for (let index = 0; index < lines.length; index += 1) {
        if (lines[index] === 'Clone' && index > 0) {
          const candidate = lines[index - 1];
          if (candidate && !names.includes(candidate)) names.push(candidate);
        }
      }
      return names.slice(0, 24);
    }).catch(() => []);
  }

  async function openMyClones(dialog) {
    const tab = dialog.locator('button').filter({ hasText: /My Clones/i }).first();
    if (!(await tab.count())) {
      result.warnings.push('my_clones_tab_missing');
      return dialog;
    }
    result.cloneCountLabel = String(await tab.innerText().catch(() => '') || '').trim();
    await tab.click({ force: true }).catch(() => {});
    await wait(1200);
    return dialog;
  }

  async function searchClone(dialog, voiceLabel) {
    const searchInput = dialog.locator('input[placeholder*="Search by name" i]').first();
    if (await searchInput.count()) {
      await searchInput.fill(String(voiceLabel || ''));
      await wait(1200);
    }
    const text = String(await dialog.innerText().catch(() => '') || '');
    if (/No voices match your filters\./i.test(text)) {
      return false;
    }
    return true;
  }

  async function chooseClone(dialog, voiceLabel) {
    const target = String(voiceLabel || '').trim();
    if (!target) throw new Error('voicewave_voice_label_missing');
    await openMyClones(dialog);
    result.cloneNames = await collectCloneNames(dialog);
    result.cloneVisible = result.cloneNames.some((name) => name.toLowerCase() === target.toLowerCase());
    if (!result.cloneVisible) {
      const searchVisible = await searchClone(dialog, target);
      result.cloneNames = await collectCloneNames(dialog);
      result.cloneVisible = searchVisible && result.cloneNames.some((name) => name.toLowerCase() === target.toLowerCase());
    }
    if (!result.cloneVisible) {
      throw new Error(`voicewave_clone_not_found:${target}`);
    }
    const cloneText = dialog.getByText(new RegExp(`^${target.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`, 'i')).first();
    const useButton = cloneText.locator('xpath=ancestor::*[self::div or self::li][1]').getByRole('button', { name: /use/i }).first();
    await useButton.click({ force: true }).catch(async () => {
      const fallback = dialog.getByRole('button', { name: /use/i }).first();
      await fallback.click({ force: true });
    });
    await wait(2000);
  }

  async function createClone(voiceLabel, referenceAudioPath) {
    const existingDialog = await openVoiceDialog();
    await openMyClones(existingDialog);
    result.cloneNames = await collectCloneNames(existingDialog);
    result.cloneVisible = result.cloneNames.some((name) => name.toLowerCase() === String(voiceLabel || '').trim().toLowerCase());
    if (result.cloneVisible) {
      result.cloneAlreadyPresent = true;
      await chooseClone(existingDialog, voiceLabel);
      return;
    }
    const cloneButton = page.locator('button[aria-label*="Clone a new voice" i]').first();
    if (!(await cloneButton.count())) {
      throw new Error('voicewave_clone_button_missing');
    }
    await cloneButton.click({ force: true });
    await wait(1500);
    const dialog = page.locator('[role=dialog]').first();
    await dialog.locator('#clone-voice-name').fill(String(voiceLabel || ''));
    const languageControl = dialog.locator('button[aria-haspopup="listbox"], select').first();
    if (await languageControl.count()) {
      await languageControl.click({ force: true }).catch(() => {});
      await wait(1000);
      const germanOption = page.getByText(/German \(Deutsch\)|German/i).last();
      if (await germanOption.count()) {
        await germanOption.click({ force: true }).catch(() => {});
        await wait(600);
      }
    }
    const fileInput = dialog.locator('input[type=file]').first();
    if (!(await fileInput.count())) {
      throw new Error('voicewave_clone_file_input_missing');
    }
    await fileInput.setInputFiles(String(referenceAudioPath || ''));
    await wait(2000);
    const createButton = dialog.locator('button[aria-label*="Create voice clone" i]').first();
    await createButton.click({ force: true }).catch(() => {});
    await wait(15000);
    const voiceDialog = await openVoiceDialog();
    await openMyClones(voiceDialog);
    result.cloneNames = await collectCloneNames(voiceDialog);
    result.cloneVisible = result.cloneNames.some((name) => name.toLowerCase() === String(voiceLabel || '').trim().toLowerCase());
    if (!result.cloneVisible) {
      throw new Error(`voicewave_clone_create_unverified:${String(voiceLabel || '').trim()}`);
    }
    await chooseClone(voiceDialog, voiceLabel);
  }

  async function fillEditor(text) {
    const editor = page.locator('[contenteditable="true"]').first();
    if (!(await editor.count())) throw new Error('voicewave_editor_missing');
    await editor.click({ force: true }).catch(() => {});
    await page.keyboard.press('Control+A').catch(() => {});
    await page.keyboard.press('Meta+A').catch(() => {});
    await page.keyboard.insertText(String(text || ''));
    await wait(800);
  }

  async function generateAudio() {
    const button = page.locator('button[aria-label*="Generate speech from text" i]').first();
    if (!(await button.count())) throw new Error('voicewave_generate_button_missing');
    await button.click({ force: true }).catch(() => {});
    await wait(12000);
  }

  async function exportAudio() {
    const button = page.locator('button[aria-label*="Export audio as WAV" i], button[aria-label*="Export audio as MP3" i]').first();
    if (!(await button.count())) throw new Error('voicewave_export_button_missing');
    const download = await Promise.all([
      page.waitForEvent('download', { timeout: 30000 }),
      button.click({ force: true }),
    ]).then((rows) => rows[0]);
    result.downloadSuggestedFilename = String(download.suggestedFilename ? download.suggestedFilename() : '').trim();
    await download.saveAs(process.env.VOICEWAVE_AUDIO_PATH);
    result.downloaded = fs.existsSync(process.env.VOICEWAVE_AUDIO_PATH);
  }

  try {
    await loginMaybe();
    result.selectedVoiceBefore = await selectedVoiceText();
    if (result.mode === 'catalog') {
      const dialog = await openVoiceDialog();
      await openMyClones(dialog);
      result.cloneNames = await collectCloneNames(dialog);
      result.cloneVisible = result.cloneNames.some((name) => name.toLowerCase() === String(result.requestedVoiceLabel || '').trim().toLowerCase());
    } else if (result.mode === 'clone') {
      await createClone(packet.voice_label, packet.reference_audio_path);
      result.selectedVoiceAfter = await selectedVoiceText();
    } else if (result.mode === 'render') {
      const dialog = await openVoiceDialog();
      await chooseClone(dialog, packet.voice_label);
      result.selectedVoiceAfter = await selectedVoiceText();
      await fillEditor(packet.text);
      await generateAudio();
      await exportAudio();
    } else {
      throw new Error(`voicewave_mode_unsupported:${result.mode}`);
    }
    result.url = String(page.url() || '');
    result.title = String((await page.title().catch(() => '')) || '');
    result.bodyText = String((await page.locator('body').innerText().catch(() => '')) || '').slice(0, 50000);
    await page.screenshot({ path: process.env.VOICEWAVE_SCREENSHOT_PATH, fullPage: true }).catch((error) => {
      result.warnings.push(`screenshot:${String(error && error.message ? error.message : error)}`);
    });
    console.log(JSON.stringify(result));
  } catch (error) {
    result.url = String(page.url() || '');
    result.title = String((await page.title().catch(() => '')) || '');
    result.bodyText = String((await page.locator('body').innerText().catch(() => '')) || '').slice(0, 50000);
    result.errors.push(String(error && error.stack ? error.stack : error));
    await page.screenshot({ path: process.env.VOICEWAVE_SCREENSHOT_PATH, fullPage: true }).catch(() => {});
    console.log(JSON.stringify(result));
    process.exit(1);
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.log(JSON.stringify({ mode: '', url: '', title: '', bodyText: '', selectedVoiceBefore: '', selectedVoiceAfter: '', cloneVisible: false, cloneCountLabel: '', cloneNames: [], cloneAlreadyPresent: false, requestedVoiceLabel: '', downloadSuggestedFilename: '', downloaded: false, warnings: [], errors: [String(error && error.stack ? error.stack : error)] }));
  process.exit(1);
});
"""


def _run_browser(packet: dict[str, object], *, screenshot_path: Path, audio_path: Path, timeout_seconds: int) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="voicewave-worker-", dir=str(SHARED_TEMP_ROOT)) as temp_dir_raw:
        temp_dir = Path(temp_dir_raw)
        packet_path = temp_dir / "packet.json"
        packet_path.write_text(json.dumps(packet, ensure_ascii=False), encoding="utf-8")
        completed = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-i",
                "-v",
                f"{temp_dir}:{temp_dir}",
                "-v",
                f"{screenshot_path.parent}:{screenshot_path.parent}",
                "-v",
                f"{audio_path.parent}:{audio_path.parent}",
                "-e",
                f"VOICEWAVE_PACKET_PATH={packet_path}",
                "-e",
                f"VOICEWAVE_SCREENSHOT_PATH={screenshot_path}",
                "-e",
                f"VOICEWAVE_AUDIO_PATH={audio_path}",
                PLAYWRIGHT_IMAGE,
                "node",
                "-e",
                _voicewave_node_script(),
            ],
            text=True,
            capture_output=True,
            timeout=max(300, timeout_seconds + 90),
            check=False,
        )
    raw = str(completed.stdout or "").strip()
    if not raw:
        raise RuntimeError(f"voicewave_worker_empty_output:{str(completed.stderr or '').strip()[:400]}")
    loaded = json.loads(raw.splitlines()[-1])
    if completed.returncode != 0:
        raise RuntimeError(f"voicewave_worker_failed:{str(loaded.get('errors') or completed.stderr or raw)[:500]}")
    if not isinstance(loaded, dict):
        raise RuntimeError("voicewave_worker_output_invalid")
    return loaded


def _catalog_summary(browser_output: dict[str, object], *, requested_voice_label: str) -> dict[str, object]:
    clone_names = [str(item).strip() for item in list(browser_output.get("cloneNames") or []) if str(item or "").strip()]
    return {
        "captured_at": _utc_now(),
        "provider_key": "voicewave",
        "mode": "catalog",
        "requested_voice_label": requested_voice_label,
        "clone_count_label": str(browser_output.get("cloneCountLabel") or "").strip(),
        "clone_names": clone_names,
        "clone_visible": bool(browser_output.get("cloneVisible")),
        "selected_voice": str(browser_output.get("selectedVoiceBefore") or "").strip(),
        "url": str(browser_output.get("url") or "").strip(),
        "title": str(browser_output.get("title") or "").strip(),
        "body_excerpt": str(browser_output.get("bodyText") or "").strip()[:1600],
        "warnings": list(browser_output.get("warnings") or []),
        "errors": list(browser_output.get("errors") or []),
    }


def _clone_summary(browser_output: dict[str, object], *, voice_label: str, reference_audio_path: Path) -> dict[str, object]:
    return {
        "captured_at": _utc_now(),
        "provider_key": "voicewave",
        "mode": "clone",
        "voice_label": voice_label,
        "reference_audio_path": reference_audio_path.as_posix(),
        "reference_audio_sha256": _sha256_file(reference_audio_path),
        "clone_already_present": bool(browser_output.get("cloneAlreadyPresent")),
        "clone_visible": bool(browser_output.get("cloneVisible")),
        "clone_count_label": str(browser_output.get("cloneCountLabel") or "").strip(),
        "clone_names": [str(item).strip() for item in list(browser_output.get("cloneNames") or []) if str(item or "").strip()],
        "selected_voice_before": str(browser_output.get("selectedVoiceBefore") or "").strip(),
        "selected_voice_after": str(browser_output.get("selectedVoiceAfter") or "").strip(),
        "url": str(browser_output.get("url") or "").strip(),
        "title": str(browser_output.get("title") or "").strip(),
        "body_excerpt": str(browser_output.get("bodyText") or "").strip()[:1600],
        "warnings": list(browser_output.get("warnings") or []),
        "errors": list(browser_output.get("errors") or []),
    }


def _render_summary(
    browser_output: dict[str, object],
    *,
    voice_label: str,
    text: str,
    screenshot_path: Path,
    audio_path: Path,
) -> dict[str, object]:
    downloaded = audio_path.is_file() and audio_path.stat().st_size > 0
    return {
        "captured_at": _utc_now(),
        "provider_key": "voicewave",
        "mode": "render",
        "voice_label": voice_label,
        "text": text,
        "downloaded": downloaded and bool(browser_output.get("downloaded")),
        "download_suggested_filename": str(browser_output.get("downloadSuggestedFilename") or "").strip(),
        "selected_voice_before": str(browser_output.get("selectedVoiceBefore") or "").strip(),
        "selected_voice_after": str(browser_output.get("selectedVoiceAfter") or "").strip(),
        "audio_path": audio_path.as_posix() if downloaded else "",
        "audio_size_bytes": audio_path.stat().st_size if downloaded else 0,
        "audio_sha256": _sha256_file(audio_path) if downloaded else "",
        "screenshot_path": screenshot_path.as_posix() if screenshot_path.is_file() else "",
        "clone_visible": bool(browser_output.get("cloneVisible")),
        "clone_count_label": str(browser_output.get("cloneCountLabel") or "").strip(),
        "url": str(browser_output.get("url") or "").strip(),
        "title": str(browser_output.get("title") or "").strip(),
        "body_excerpt": str(browser_output.get("bodyText") or "").strip()[:1600],
        "warnings": list(browser_output.get("warnings") or []),
        "errors": list(browser_output.get("errors") or []),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create or render a memorial VoiceWave custom voice through the live Studio UI.")
    subparsers = parser.add_subparsers(dest="mode", required=True)

    catalog = subparsers.add_parser("catalog", help="Inspect visible VoiceWave clone inventory.")
    catalog.add_argument("--voice-label", default=DEFAULT_VOICE_LABEL)
    catalog.add_argument("--login-email", default="")
    catalog.add_argument("--login-password", default="")
    catalog.add_argument("--output", default=str(OUTPUT_ROOT / "voicewave_catalog.generated.json"))
    catalog.add_argument("--screenshot-output", default=str(OUTPUT_ROOT / "voicewave_catalog.latest.png"))
    catalog.add_argument("--timeout-seconds", type=int, default=180)

    clone = subparsers.add_parser("clone", help="Create a VoiceWave custom voice from a reference audio clip.")
    clone.add_argument("--slug", default="manfred")
    clone.add_argument("--voice-label", default=DEFAULT_VOICE_LABEL)
    clone.add_argument("--reference-audio", default="")
    clone.add_argument("--login-email", default="")
    clone.add_argument("--login-password", default="")
    clone.add_argument("--output", default=str(OUTPUT_ROOT / "voicewave_clone_create.generated.json"))
    clone.add_argument("--screenshot-output", default=str(OUTPUT_ROOT / "voicewave_clone_create.latest.png"))
    clone.add_argument("--timeout-seconds", type=int, default=240)

    render = subparsers.add_parser("render", help="Render memorial text with a VoiceWave custom voice and export WAV.")
    render.add_argument("--voice-label", default=DEFAULT_VOICE_LABEL)
    render.add_argument("--text", required=True)
    render.add_argument("--login-email", default="")
    render.add_argument("--login-password", default="")
    render.add_argument("--output", default=str(OUTPUT_ROOT / "voicewave_render.generated.json"))
    render.add_argument("--screenshot-output", default=str(OUTPUT_ROOT / "voicewave_render.latest.png"))
    render.add_argument("--audio-output", default=str(OUTPUT_ROOT / "voicewave_render.latest.wav"))
    render.add_argument("--timeout-seconds", type=int, default=240)

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    login_email = _login_email(getattr(args, "login_email", ""))
    login_password = _login_password(getattr(args, "login_password", ""))
    if not login_email:
        raise SystemExit("voicewave_login_email_missing")
    if not login_password:
        raise SystemExit("voicewave_login_password_missing")

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    SHARED_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    screenshot_path = Path(str(getattr(args, "screenshot_output", OUTPUT_ROOT / "voicewave.latest.png"))).expanduser()
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    output_path = Path(str(getattr(args, "output", OUTPUT_ROOT / "voicewave.generated.json"))).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path = Path(str(getattr(args, "audio_output", OUTPUT_ROOT / "voicewave.latest.wav"))).expanduser()
    audio_path.parent.mkdir(parents=True, exist_ok=True)

    packet: dict[str, object] = {
        "mode": args.mode,
        "login_email": login_email,
        "login_password": login_password,
        "voice_label": str(getattr(args, "voice_label", DEFAULT_VOICE_LABEL)).strip() or DEFAULT_VOICE_LABEL,
    }
    if args.mode == "clone":
        reference_audio = Path(str(args.reference_audio or "")).expanduser() if str(args.reference_audio or "").strip() else _default_reference_audio(args.slug)
        if not reference_audio.is_file():
            raise SystemExit(f"voicewave_reference_audio_missing:{reference_audio}")
        packet["reference_audio_path"] = reference_audio.as_posix()
    if args.mode == "render":
        packet["text"] = str(args.text).strip()
    try:
        browser_output = _run_browser(
            packet,
            screenshot_path=screenshot_path,
            audio_path=audio_path,
            timeout_seconds=max(120, int(getattr(args, "timeout_seconds", 240))),
        )
    except RuntimeError as exc:
        payload = {
            "captured_at": _utc_now(),
            "provider_key": "voicewave",
            "mode": args.mode,
            "requested_voice_label": str(packet.get("voice_label") or "").strip(),
            "status": "failed",
            "errors": [str(exc)],
        }
        _write_json(output_path, payload)
        print(json.dumps({"status": "failed", "output": output_path.as_posix(), "error": str(exc)[:500]}, ensure_ascii=False))
        return 1

    if args.mode == "catalog":
        payload = _catalog_summary(browser_output, requested_voice_label=str(packet.get("voice_label") or "").strip())
    elif args.mode == "clone":
        payload = _clone_summary(browser_output, voice_label=str(packet.get("voice_label") or "").strip(), reference_audio_path=reference_audio)
    else:
        payload = _render_summary(
            browser_output,
            voice_label=str(packet.get("voice_label") or "").strip(),
            text=str(packet.get("text") or "").strip(),
            screenshot_path=screenshot_path,
            audio_path=audio_path,
        )
    _write_json(output_path, payload)
    print(
        json.dumps(
            {
                "status": "ok",
                "mode": args.mode,
                "output": output_path.as_posix(),
                "voice_label": str(packet.get("voice_label") or "").strip(),
                "downloaded": bool(payload.get("downloaded")),
                "clone_visible": bool(payload.get("clone_visible")),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
