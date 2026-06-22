#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


ROOT = Path(os.environ.get("PROPERTYQUARRY_ROOT") or Path(__file__).resolve().parents[1])
ENV_FILES = [
    ROOT / ".env",
    Path(os.environ.get("EA_MAGICFIT_ENV_FILE") or ROOT / ".env.magicfit"),
]
MAGICFIT_HOME_URL = "https://magicfit.pushowl.com/home"
MAGICFIT_VIDEO_URL = "https://magicfit.pushowl.com/agents/generate?mode=video"
VIDEO_URL_RE = re.compile(r"https://(?:cdn\.pushowl\.com|media\.powlcdn\.com)/magicfit/[^\"'\s<>]+?\.(?:mp4|webm)(?:[^\"'\s<>]*)?")
NEGATIVE = ", ".join(
    [
        "no storyboard",
        "no slideshow",
        "no empty unfurnished flat",
        "no abrupt cut before final 240 degree sweep",
        "no ending cut before sweep completes",
        "no fade-out before final sweep",
        "no cartoon",
        "no toy diorama",
        "no visible text",
        "no watermark",
        "no broken geometry",
        "no sterile showroom look",
    ]
)


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


def load_env() -> None:
    for path in ENV_FILES:
        load_env_file(path)


def arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render a MagicFit property flythrough clip.")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--duration", type=int, default=10)
    parser.add_argument("--aspect-label", default="Landscape (16:9)")
    parser.add_argument("--timeout-minutes", type=int, default=18)
    parser.add_argument("--model-label", default="")
    parser.add_argument("--state-json", default="")
    return parser


def magicfit_duration(seconds: int) -> int:
    allowed = [4, 6, 8, 10, 12, 15]
    return min(allowed, key=lambda candidate: (abs(candidate - seconds), -candidate))


def collect_video_urls(text: str) -> list[str]:
    return list(dict.fromkeys(url.replace("\\u0026", "&").rstrip("),]") for url in VIDEO_URL_RE.findall(text or "")))


def url_timestamp(url: str) -> int:
    match = re.search(r"/magicfit/(\d+)-", url)
    if match is None:
        return 0
    try:
        return int(match.group(1))
    except Exception:
        return 0


def choose_newest_video(urls: set[str], baseline: set[str], submitted_at_ms: int) -> str:
    candidates: list[tuple[int, str]] = []
    for url in urls:
        if url in baseline:
            continue
        if "/ik-thumbnail." in url:
            continue
        timestamp = url_timestamp(url)
        if timestamp and timestamp < submitted_at_ms - 120000:
            continue
        candidates.append((timestamp, url))
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1] if candidates else ""


def download(url: str, out_path: Path) -> None:
    response = requests.get(url, timeout=120, stream=True)
    response.raise_for_status()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as handle:
        for chunk in response.iter_content(chunk_size=1024 * 128):
            if chunk:
                handle.write(chunk)


def maybe_login(page) -> None:
    print("magicfit: open home", flush=True)
    page.goto(MAGICFIT_HOME_URL, wait_until="domcontentloaded", timeout=120000)
    page.wait_for_timeout(4000)
    body = page.locator("body").inner_text(timeout=10000)
    if not re.search(r"login|sign in|email|password", body, re.I):
        print("magicfit: already logged in", flush=True)
        return
    email = (os.environ.get("CHUMMER_EA_MAGICFIT_EMAIL") or os.environ.get("MAGICFIT_EMAIL") or "").strip()
    password = (os.environ.get("CHUMMER_EA_MAGICFIT_PASSWORD") or os.environ.get("MAGICFIT_PASSWORD") or "").strip()
    if not email or not password:
        raise RuntimeError("magicfit_credentials_missing")
    email_field = page.locator("input[type=email], input[name*=email i], input[placeholder*=email i]").first
    if email_field.count():
        email_field.fill(email)
    password_field = page.locator("input[type=password]").first
    if password_field.count():
        password_field.fill(password)
    submit = page.get_by_role("button", name=re.compile(r"sign in|login|continue|submit", re.I)).first
    if submit.count():
        submit.click()
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(8000)
    print("magicfit: login submitted", flush=True)


def select_button(page, current_text: str, option_text: str) -> None:
    try:
        page.get_by_role("button", name=current_text).last.click(timeout=10000)
        page.wait_for_timeout(500)
        page.get_by_text(option_text, exact=True).last.click(timeout=10000)
        page.wait_for_timeout(500)
    except PlaywrightTimeoutError:
        pass


def fill_prompt(page, prompt: str) -> None:
    box = page.locator('[contenteditable="true"][role="textbox"]').first
    box.wait_for(timeout=10000)
    box.evaluate(
        """(node) => {
            node.scrollIntoView({ block: 'center', inline: 'nearest' });
            node.focus();
            node.textContent = '';
        }"""
    )
    page.wait_for_timeout(200)
    box.click(timeout=10000, force=True)
    page.keyboard.type(prompt, delay=1)
    page.wait_for_timeout(800)


def collect_visible_video_urls(page) -> set[str]:
    urls: set[str] = set()
    html = page.content()
    urls.update(collect_video_urls(html))
    try:
        video_urls = page.locator("video").evaluate_all("(nodes) => nodes.map((v) => v.currentSrc || v.src).filter(Boolean)")
    except Exception:
        video_urls = []
    for url in list(video_urls or []):
        if "magicfit" in str(url):
            urls.add(str(url))
    return urls


def run() -> int:
    load_env()
    args = arg_parser().parse_args()
    out_path = Path(args.out).resolve()
    state_path = Path(args.state_json).resolve() if args.state_json else None
    prompt = f"{args.prompt.strip()} Global constraints: {NEGATIVE}."
    provider_duration = magicfit_duration(int(args.duration or 10))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1440, "height": 1100}, accept_downloads=True)
        page = context.new_page()
        try:
            maybe_login(page)
            print("magicfit: open video generator", flush=True)
            page.goto(MAGICFIT_VIDEO_URL, wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(5000)
            baseline = collect_visible_video_urls(page)
            print(f"magicfit: baseline urls={len(baseline)}", flush=True)
            select_button(page, "9:16", args.aspect_label)
            select_button(page, "4s", f"{provider_duration}s")
            if args.model_label:
                select_button(page, "Veo 3.1", args.model_label)
            fill_prompt(page, prompt)
            events: list[dict[str, object]] = []
            seen_urls: set[str] = set()

            def handle_response(response) -> None:
                url = response.url
                if "magicfit" not in url and "pushowl" not in url:
                    return
                item = {
                    "method": response.request.method,
                    "status": response.status,
                    "url": url,
                    "content_type": response.headers.get("content-type", ""),
                }
                events.append(item)
                if re.search(r"(?:cdn\.pushowl\.com|media\.powlcdn\.com)/magicfit/.*\.(mp4|webm)(?:$|\?)", url):
                    seen_urls.add(url)
                try:
                    body = response.text() if re.search(r"json|script|text", item["content_type"], re.I) else ""
                except Exception:
                    body = ""
                if body:
                    seen_urls.update(collect_video_urls(body))

            page.on("response", handle_response)
            submitted_at_ms = int(time.time() * 1000)
            submit = page.locator("form button").last
            print("magicfit: submit job", flush=True)
            submit.click(timeout=30000)
            page.wait_for_timeout(3000)
            deadline = time.time() + max(int(args.timeout_minutes or 18), 1) * 60
            video_url = ""
            poll_count = 0
            while time.time() < deadline and not video_url:
                page.wait_for_timeout(10000)
                poll_count += 1
                seen_urls.update(collect_visible_video_urls(page))
                video_url = choose_newest_video(seen_urls, baseline, submitted_at_ms)
                print(f"magicfit: poll={poll_count} seen_urls={len(seen_urls)} found={bool(video_url)}", flush=True)
            if not video_url:
                raise RuntimeError("magicfit_video_url_not_found")
            print("magicfit: download clip", flush=True)
            download(video_url, out_path)
            payload = {
                "provider": "MagicFit",
                "video_output_url": video_url,
                "output_file": str(out_path),
                "duration_seconds_requested": int(args.duration or 10),
                "duration_seconds_magicfit": provider_duration,
                "aspect_label": args.aspect_label,
                "prompt": prompt,
                "page_url": page.url,
                "events_tail": events[-80:],
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            if state_path is not None:
                state_path.parent.mkdir(parents=True, exist_ok=True)
                state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            print(json.dumps(payload))
            return 0
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    raise SystemExit(run())
