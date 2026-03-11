#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


EA_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = EA_ROOT / ".env"
BASE_URL = "https://api.markupgo.com/api/v1/image/buffer"


def env_value(name: str) -> str:
    direct = str(os.environ.get(name) or "").strip()
    if direct:
        return direct
    if ENV_FILE.exists():
        for raw in ENV_FILE.read_text(errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == name:
                return value.strip()
    return ""


def theme_for(seed: str) -> tuple[str, str, str]:
    palettes = [
        ("#0b1020", "#18f0ff", "#ff2f92"),
        ("#0f0d1a", "#7bff5b", "#2ee6ff"),
        ("#120914", "#ffcc33", "#ff4f8b"),
        ("#08141a", "#76ffd1", "#4fb3ff"),
    ]
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return palettes[int(digest[:2], 16) % len(palettes)]


def slug_title(prompt: str) -> str:
    cleaned = " ".join(prompt.replace("-", " ").replace(",", " ").split())
    if not cleaned:
        return "Chummer6"
    words = cleaned.split()
    title = " ".join(words[:4]).strip()
    return title.title()


def teaser(prompt: str) -> str:
    cleaned = " ".join(prompt.split())
    if len(cleaned) <= 140:
        return cleaned
    return cleaned[:137].rstrip() + "..."


def scene_for(output_name: str, prompt: str) -> dict[str, str]:
    name = output_name.lower()
    scenes = {
        "chummer6-hero.png": {
            "badge": "Visitor Center",
            "title": "Same shadows. Bigger future.",
            "subtitle": "A readable front door for the next Chummer, with less corp-speak and more chrome.",
            "kicker": "Guide repo",
        },
        "karma-forge.png": {
            "badge": "Horizon",
            "title": "Karma Forge",
            "subtitle": "Personalized rules without forked-code chaos.",
            "kicker": "Overlay future",
        },
        "nexus-pan.png": {
            "badge": "Horizon",
            "title": "NEXUS-PAN",
            "subtitle": "A live table, not just isolated character files.",
            "kicker": "Session mesh",
        },
        "alice.png": {
            "badge": "Horizon",
            "title": "ALICE",
            "subtitle": "Stress-test the build before the run stress-tests you.",
            "kicker": "Simulation lab",
        },
        "jackpoint.png": {
            "badge": "Horizon",
            "title": "JACKPOINT",
            "subtitle": "Turn raw data into dossiers without pretending vibes are evidence.",
            "kicker": "Dossier forge",
        },
        "ghostwire.png": {
            "badge": "Horizon",
            "title": "GHOSTWIRE",
            "subtitle": "Replay a run like a forensic sim and find the moment the drek hit the fan.",
            "kicker": "Forensic replay",
        },
        "rule-x-ray.png": {
            "badge": "Horizon",
            "title": "RULE X-RAY",
            "subtitle": "Every number explains itself, down to the last miserable modifier.",
            "kicker": "Math autopsy",
        },
        "heat-web.png": {
            "badge": "Horizon",
            "title": "HEAT WEB",
            "subtitle": "Consequences, grudges, and faction heat woven into one ugly city map.",
            "kicker": "Consequence graph",
        },
        "mirrorshard.png": {
            "badge": "Horizon",
            "title": "MIRRORSHARD",
            "subtitle": "Compare alternate futures of the same runner without losing the plot.",
            "kicker": "Variant compare",
        },
        "run-passport.png": {
            "badge": "Horizon",
            "title": "RUN PASSPORT",
            "subtitle": "Move a character across rule environments with their scars intact.",
            "kicker": "Portability lane",
        },
        "threadcutter.png": {
            "badge": "Horizon",
            "title": "THREADCUTTER",
            "subtitle": "Conflict analysis for overlays before they turn your table into a knife fight.",
            "kicker": "Conflict audit",
        },
        "blackbox-loadout.png": {
            "badge": "Horizon",
            "title": "BLACKBOX LOADOUT",
            "subtitle": "A merciless prep check for runners who think vibes count as equipment.",
            "kicker": "Prep scanner",
        },
    }
    if name in scenes:
        return scenes[name]
    return {
        "badge": "Chummer6",
        "title": slug_title(prompt),
        "subtitle": teaser(prompt),
        "kicker": "Guide art",
    }


def build_html(prompt: str, output_name: str, *, width: int, height: int) -> str:
    bg, accent_a, accent_b = theme_for(prompt)
    scene = scene_for(output_name, prompt)
    title = html.escape(scene["title"])
    subtitle = html.escape(scene["subtitle"])
    badge = html.escape(scene["badge"])
    kicker = html.escape(scene["kicker"])
    ratio = f"{width}x{height}"
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      width: {width}px;
      height: {height}px;
      overflow: hidden;
      font-family: 'Segoe UI', system-ui, sans-serif;
      background:
        radial-gradient(circle at 20% 20%, {accent_a}33 0, transparent 40%),
        radial-gradient(circle at 80% 25%, {accent_b}2a 0, transparent 35%),
        linear-gradient(135deg, {bg} 0%, #05070d 100%);
      color: #f4f7fb;
    }}
    .frame {{
      position: relative;
      width: 100%;
      height: 100%;
      padding: 52px 58px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }}
    .noise {{
      position: absolute;
      inset: 0;
      background:
        radial-gradient(circle at 14% 70%, {accent_a}22 0, transparent 22%),
        radial-gradient(circle at 76% 18%, {accent_b}22 0, transparent 18%),
        radial-gradient(circle at 84% 82%, #ffffff10 0, transparent 12%);
      mix-blend-mode: screen;
      opacity: 0.9;
      pointer-events: none;
    }}
    .grid {{
      position: absolute;
      inset: 0;
      background-image:
        linear-gradient(rgba(255,255,255,0.04) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255,255,255,0.04) 1px, transparent 1px);
      background-size: 52px 52px;
      mask-image: linear-gradient(to bottom, rgba(0,0,0,0.7), transparent);
      pointer-events: none;
    }}
    .chip {{
      display: inline-flex;
      align-items: center;
      gap: 10px;
      padding: 10px 16px;
      border-radius: 999px;
      border: 1px solid rgba(255,255,255,0.14);
      background: rgba(5,8,15,0.52);
      color: {accent_a};
      font-size: 18px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      width: fit-content;
      backdrop-filter: blur(4px);
    }}
    .headline {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 280px;
      gap: 24px;
      align-items: start;
    }}
    .title {{
      font-size: {max(52, min(86, width // 13))}px;
      line-height: 0.94;
      font-weight: 900;
      letter-spacing: -0.03em;
      max-width: 78%;
      text-wrap: balance;
      text-shadow: 0 0 30px rgba(0,0,0,0.35);
    }}
    .subtitle {{
      max-width: 70%;
      font-size: {max(22, min(34, width // 40))}px;
      line-height: 1.3;
      color: rgba(244,247,251,0.88);
      text-wrap: pretty;
    }}
    .footer {{
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
    }}
    .sidecard {{
      justify-self: end;
      width: 280px;
      min-height: 240px;
      padding: 22px 24px;
      border-radius: 30px;
      border: 1px solid rgba(255,255,255,0.12);
      background:
        linear-gradient(180deg, rgba(255,255,255,0.08), rgba(255,255,255,0.02)),
        rgba(7, 10, 18, 0.52);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.08), 0 14px 50px rgba(0,0,0,0.28);
      backdrop-filter: blur(8px);
    }}
    .sidecard .small {{
      font-size: 14px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: rgba(244,247,251,0.58);
      margin-bottom: 18px;
    }}
    .sidecard .big {{
      font-size: 30px;
      line-height: 1.05;
      font-weight: 900;
      color: {accent_b};
      margin-bottom: 14px;
      text-shadow: 0 0 18px {accent_b}33;
    }}
    .sidecard .line {{
      height: 4px;
      width: 100%;
      border-radius: 999px;
      background: linear-gradient(90deg, {accent_a}, {accent_b});
      margin: 18px 0 12px;
      opacity: 0.9;
    }}
    .sidecard .note {{
      font-size: 16px;
      line-height: 1.4;
      color: rgba(244,247,251,0.82);
    }}
    .brand {{
      font-size: 34px;
      font-weight: 800;
      color: {accent_b};
      letter-spacing: 0.02em;
      text-shadow: 0 0 18px {accent_b}55;
    }}
    .meta {{
      font-size: 18px;
      color: rgba(244,247,251,0.62);
      text-transform: uppercase;
      letter-spacing: 0.12em;
    }}
    .beam {{
      position: absolute;
      right: -80px;
      bottom: 56px;
      width: {max(260, width // 3)}px;
      height: {max(260, height // 2)}px;
      border-radius: 40px;
      background:
        linear-gradient(160deg, {accent_a} 0%, transparent 70%),
        linear-gradient(20deg, {accent_b} 0%, transparent 78%);
      filter: blur(28px);
      opacity: 0.52;
      transform: rotate(-10deg);
    }}
    .beacon {{
      position: absolute;
      left: 54px;
      bottom: 84px;
      width: 180px;
      height: 180px;
      border-radius: 34px;
      border: 1px solid rgba(255,255,255,0.14);
      background:
        linear-gradient(135deg, rgba(255,255,255,0.08), rgba(255,255,255,0.01)),
        rgba(2,6,14,0.52);
      box-shadow: inset 0 0 18px rgba(255,255,255,0.05), 0 14px 40px rgba(0,0,0,0.35);
      overflow: hidden;
      transform: rotate(-6deg);
    }}
    .beacon::before,
    .beacon::after {{
      content: "";
      position: absolute;
      inset: 20px;
      border-radius: 24px;
      border: 1px solid {accent_a}55;
    }}
    .beacon::after {{
      inset: 42px;
      border-color: {accent_b}55;
    }}
  </style>
</head>
<body>
  <div class="frame">
    <div class="noise"></div>
    <div class="grid"></div>
    <div class="beam"></div>
    <div class="beacon"></div>
    <div class="chip">{badge}</div>
    <div class="headline">
      <div>
        <div class="title">{title}</div>
        <div class="subtitle">{subtitle}</div>
      </div>
      <div class="sidecard">
        <div class="small">Current vibe</div>
        <div class="big">{kicker}</div>
        <div class="line"></div>
        <div class="note">Chrome, caution, and just enough bad decisions to feel like home.</div>
      </div>
    </div>
    <div class="footer">
      <div class="brand">Chummer6</div>
      <div class="meta">{ratio} • generated locally via EA</div>
    </div>
  </div>
</body>
</html>
"""


def render(prompt: str, output: Path, *, width: int, height: int) -> None:
    api_key = env_value("MARKUPGO_API_KEY")
    if not api_key:
        raise SystemExit("MARKUPGO_API_KEY is not configured")
    body = {
        "source": {
            "type": "html",
            "data": build_html(prompt, output.name, width=width, height=height),
        },
        "options": {
            "properties": {
                "format": "png",
                "width": width,
                "height": height,
                "clip": True,
            },
            "optimizeForSpeed": True,
        },
    }
    request = urllib.request.Request(
        BASE_URL,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "User-Agent": "EA-Chummer6-MarkupGo/1.0",
        },
        data=json.dumps(body).encode("utf-8"),
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        raise SystemExit(f"MarkupGo HTTP {exc.code}: {body[:300]}")
    except urllib.error.URLError as exc:
        raise SystemExit(f"MarkupGo transport error: {exc.reason}")
    if not data:
        raise SystemExit("MarkupGo returned empty output")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render Chummer6 art through MarkupGo.")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    args = parser.parse_args()
    render(str(args.prompt), Path(args.output).expanduser(), width=int(args.width), height=int(args.height))
    print(json.dumps({"output": str(Path(args.output).expanduser()), "status": "rendered"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
