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


def build_html(prompt: str, *, width: int, height: int) -> str:
    bg, accent_a, accent_b = theme_for(prompt)
    title = html.escape(slug_title(prompt))
    subtitle = html.escape(teaser(prompt))
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
  </style>
</head>
<body>
  <div class="frame">
    <div class="grid"></div>
    <div class="beam"></div>
    <div class="chip">Chummer6 generated art</div>
    <div>
      <div class="title">{title}</div>
      <div class="subtitle">{subtitle}</div>
    </div>
    <div class="footer">
      <div class="brand">Chummer6</div>
      <div class="meta">{ratio} • MarkupGo render</div>
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
            "data": build_html(prompt, width=width, height=height),
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
