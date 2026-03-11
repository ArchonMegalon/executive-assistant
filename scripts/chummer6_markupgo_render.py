#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import math
import os
import random
import struct
import tempfile
import urllib.error
import urllib.request
import zlib
from pathlib import Path


EA_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = EA_ROOT / ".env"
BASE_URL = "https://api.markupgo.com/api/v1/image/buffer"
OVERRIDE_PATH = Path("/docker/fleet/state/chummer6/ea_overrides.json")


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


def load_media_overrides() -> dict[str, object]:
    if not OVERRIDE_PATH.exists():
        return {}
    try:
        loaded = json.loads(OVERRIDE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def scene_for(output_name: str, prompt: str) -> dict[str, object]:
    name = output_name.lower()
    default = {
        "badge": "Chummer6",
        "title": slug_title(prompt),
        "subtitle": teaser(prompt),
        "kicker": "Guide art",
        "note": "Fresh chrome for the guide wall.",
        "meta": "Chummer6 guide art",
        "overlay_hint": "analysis overlay",
        "visual_motifs": [],
        "overlay_callouts": [],
    }
    loaded = load_media_overrides()
    media = loaded.get("media") if isinstance(loaded, dict) else None
    if isinstance(media, dict):
        if name == "chummer6-hero.png":
            hero = media.get("hero")
            if isinstance(hero, dict):
                merged = dict(default)
                for key in ("badge", "title", "subtitle", "kicker", "note", "meta", "overlay_hint"):
                    value = str(hero.get(key, "")).strip()
                    if value:
                        merged[key] = value
                for key in ("visual_motifs", "overlay_callouts"):
                    raw = hero.get(key)
                    if isinstance(raw, list):
                        merged[key] = [str(entry).strip() for entry in raw if str(entry).strip()]
                return merged
        horizons = media.get("horizons")
        if isinstance(horizons, dict):
            slug = name.removesuffix(".png")
            row = horizons.get(slug)
            if isinstance(row, dict):
                merged = dict(default)
                for key in ("badge", "title", "subtitle", "kicker", "note", "meta", "overlay_hint"):
                    value = str(row.get(key, "")).strip()
                    if value:
                        merged[key] = value
                for key in ("visual_motifs", "overlay_callouts"):
                    raw = row.get(key)
                    if isinstance(raw, list):
                        merged[key] = [str(entry).strip() for entry in raw if str(entry).strip()]
                return merged
    return default


def hex_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) != 6:
        return (24, 240, 255)
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))


def clamp8(value: float) -> int:
    return max(0, min(255, int(round(value))))


def png_chunk(tag: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(tag)
    crc = zlib.crc32(data, crc) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


def rgba_png(width: int, height: int, pixels: bytes) -> bytes:
    header = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    stride = width * 4
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        start = y * stride
        rows.extend(pixels[start : start + stride])
    compressed = zlib.compress(bytes(rows), level=9)
    return header + png_chunk(b"IHDR", ihdr) + png_chunk(b"IDAT", compressed) + png_chunk(b"IEND", b"")


def blend_pixel(pixels: bytearray, width: int, height: int, x: int, y: int, color: tuple[int, int, int], alpha: float) -> None:
    if x < 0 or y < 0 or x >= width or y >= height or alpha <= 0:
        return
    idx = (y * width + x) * 4
    inv = max(0.0, min(1.0, 1.0 - alpha))
    pixels[idx] = clamp8((pixels[idx] * inv) + (color[0] * alpha))
    pixels[idx + 1] = clamp8((pixels[idx + 1] * inv) + (color[1] * alpha))
    pixels[idx + 2] = clamp8((pixels[idx + 2] * inv) + (color[2] * alpha))
    pixels[idx + 3] = 255


def draw_rect(pixels: bytearray, width: int, height: int, left: int, top: int, rect_w: int, rect_h: int, color: tuple[int, int, int], alpha: float) -> None:
    for y in range(max(0, top), min(height, top + rect_h)):
        for x in range(max(0, left), min(width, left + rect_w)):
            blend_pixel(pixels, width, height, x, y, color, alpha)


def draw_circle(pixels: bytearray, width: int, height: int, cx: int, cy: int, radius: int, color: tuple[int, int, int], alpha: float, *, fill: bool = False) -> None:
    r2 = radius * radius
    inner = (radius - 3) * (radius - 3)
    for y in range(max(0, cy - radius), min(height, cy + radius)):
        for x in range(max(0, cx - radius), min(width, cx + radius)):
            dx = x - cx
            dy = y - cy
            dist = dx * dx + dy * dy
            if fill:
                if dist <= r2:
                    blend_pixel(pixels, width, height, x, y, color, alpha * (1.0 - (dist / max(1, r2))))
            elif inner <= dist <= r2:
                blend_pixel(pixels, width, height, x, y, color, alpha)


def draw_line(pixels: bytearray, width: int, height: int, x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int], alpha: float) -> None:
    steps = max(abs(x1 - x0), abs(y1 - y0), 1)
    for step in range(steps + 1):
        t = step / steps
        x = int(round(x0 + ((x1 - x0) * t)))
        y = int(round(y0 + ((y1 - y0) * t)))
        blend_pixel(pixels, width, height, x, y, color, alpha)
        blend_pixel(pixels, width, height, x + 1, y, color, alpha * 0.5)
        blend_pixel(pixels, width, height, x, y + 1, color, alpha * 0.5)


def scene_tokens(text: str) -> set[str]:
    lowered = str(text or "").lower()
    tags: set[str] = set()
    for token in (
        "x-ray", "xray", "dice", "modifier", "source", "forensic", "ghost", "replay", "simulation", "dummy", "branching",
        "dossier", "evidence", "graph", "network", "table", "team", "commlink", "forge", "anvil", "sparks", "mirror",
        "timeline", "passport", "travel", "heat", "consequence", "thread", "conflict", "lua", "scripted", "receipt",
        "support", "sr4", "sr5", "sr6", "overlay",
    ):
        if token in lowered:
            tags.add(token.replace(" ", "_"))
    return tags


def render_scene_png(prompt: str, scene: dict[str, str], *, width: int, height: int) -> bytes:
    seed = int(hashlib.sha256((prompt + json.dumps(scene, sort_keys=True)).encode("utf-8")).hexdigest()[:16], 16)
    rng = random.Random(seed)
    bg, accent_a, accent_b = theme_for(prompt)
    bg_rgb = hex_rgb(bg)
    a_rgb = hex_rgb(accent_a)
    b_rgb = hex_rgb(accent_b)
    pixels = bytearray(width * height * 4)
    scene_text = " ".join(
        [
            prompt,
            str(scene.get("title", "")),
            str(scene.get("subtitle", "")),
            str(scene.get("overlay_hint", "")),
            *[str(entry) for entry in scene.get("visual_motifs", []) if str(entry).strip()],
            *[str(entry) for entry in scene.get("overlay_callouts", []) if str(entry).strip()],
        ]
    )
    tokens = scene_tokens(scene_text)
    for y in range(height):
        u = y / max(1, height - 1)
        for x in range(width):
            t = x / max(1, width - 1)
            r = bg_rgb[0] * (0.42 + 0.18 * t) + a_rgb[0] * (0.08 * u)
            g = bg_rgb[1] * (0.42 + 0.12 * u) + a_rgb[1] * (0.06 * t)
            b = bg_rgb[2] * (0.56 + 0.16 * (1.0 - t)) + b_rgb[2] * (0.08 * u)
            vignette = 1.0 - 0.58 * (((t - 0.5) ** 2) + ((u - 0.5) ** 2))
            idx = (y * width + x) * 4
            pixels[idx] = clamp8(r * vignette)
            pixels[idx + 1] = clamp8(g * vignette)
            pixels[idx + 2] = clamp8(b * vignette)
            pixels[idx + 3] = 255

    # Holographic grid and scanlines.
    for y in range(0, height, 32):
        draw_line(pixels, width, height, 0, y, width, y, (255, 255, 255), 0.045)
    for x in range(0, width, 46):
        draw_line(pixels, width, height, x, 0, x, height, (255, 255, 255), 0.03)

    # Generic scene anchors.
    draw_circle(pixels, width, height, int(width * 0.76), int(height * 0.26), int(min(width, height) * 0.12), a_rgb, 0.28, fill=True)
    draw_circle(pixels, width, height, int(width * 0.18), int(height * 0.72), int(min(width, height) * 0.09), b_rgb, 0.24, fill=True)

    if "x-ray" in tokens or "xray" in tokens or "modifier" in tokens or "dice" in tokens or "source" in tokens:
        for column in range(4):
            left = int(width * (0.14 + column * 0.12))
            top = int(height * (0.18 + (column % 2) * 0.05))
            draw_rect(pixels, width, height, left, top, int(width * 0.08), int(height * 0.44), a_rgb, 0.10)
            draw_circle(pixels, width, height, left + int(width * 0.04), top + int(height * 0.09), int(height * 0.05), b_rgb, 0.32)
            draw_circle(pixels, width, height, left + int(width * 0.04), top + int(height * 0.23), int(height * 0.035), a_rgb, 0.28)
            draw_circle(pixels, width, height, left + int(width * 0.04), top + int(height * 0.35), int(height * 0.025), b_rgb, 0.22)
        hub_points = [
            (int(width * 0.62), int(height * 0.22)),
            (int(width * 0.70), int(height * 0.34)),
            (int(width * 0.62), int(height * 0.48)),
            (int(width * 0.78), int(height * 0.42)),
        ]
        for ax, ay in hub_points:
            draw_circle(pixels, width, height, ax, ay, int(height * 0.03), a_rgb, 0.4)
        for (x0, y0), (x1, y1) in zip(hub_points, hub_points[1:]):
            draw_line(pixels, width, height, x0, y0, x1, y1, b_rgb, 0.34)
        hand_x = int(width * 0.26)
        hand_y = int(height * 0.56)
        draw_rect(pixels, width, height, hand_x, hand_y, int(width * 0.05), int(height * 0.16), (230, 245, 255), 0.10)
        for index, offset in enumerate((0, 18, 36, 54)):
            fx = hand_x + offset
            draw_line(pixels, width, height, fx, hand_y, fx + 8, hand_y - int(height * 0.16), (230, 245, 255), 0.18)
            draw_circle(pixels, width, height, fx + 4, hand_y - int(height * (0.06 + index * 0.01)), 8, (230, 245, 255), 0.18)
        for pip_x, pip_y in ((0.47, 0.60), (0.52, 0.56), (0.58, 0.61), (0.54, 0.66)):
            draw_circle(pixels, width, height, int(width * pip_x), int(height * pip_y), 10, b_rgb, 0.30, fill=True)

    if "forge" in tokens or "anvil" in tokens or "sparks" in tokens:
        draw_rect(pixels, width, height, int(width * 0.24), int(height * 0.54), int(width * 0.24), int(height * 0.10), (18, 22, 28), 0.55)
        for _ in range(180):
            px = int(width * 0.36 + rng.uniform(-140, 140))
            py = int(height * 0.48 + rng.uniform(-90, 30))
            blend_pixel(pixels, width, height, px, py, b_rgb, 0.65)

    if "dossier" in tokens or "evidence" in tokens:
        for idx, angle in enumerate((-8, 6, -3)):
            left = int(width * 0.16 + idx * width * 0.06)
            top = int(height * 0.22 + idx * height * 0.02)
            draw_rect(pixels, width, height, left, top, int(width * 0.18), int(height * 0.26), (230, 230, 232), 0.12)
        draw_line(pixels, width, height, int(width * 0.58), int(height * 0.22), int(width * 0.78), int(height * 0.47), b_rgb, 0.38)
        draw_line(pixels, width, height, int(width * 0.78), int(height * 0.47), int(width * 0.66), int(height * 0.62), b_rgb, 0.38)

    if "simulation" in tokens or "dummy" in tokens or "branching" in tokens:
        draw_circle(pixels, width, height, int(width * 0.34), int(height * 0.30), int(height * 0.05), (255, 210, 90), 0.26, fill=True)
        draw_rect(pixels, width, height, int(width * 0.31), int(height * 0.36), int(width * 0.06), int(height * 0.22), (255, 210, 90), 0.18)
        for offset in (-120, 0, 120):
            draw_line(pixels, width, height, int(width * 0.48), int(height * 0.36), int(width * 0.68), int(height * 0.26 + offset * 0.2), a_rgb, 0.34)

    if "table" in tokens or "team" in tokens or "commlink" in tokens:
        draw_rect(pixels, width, height, int(width * 0.24), int(height * 0.54), int(width * 0.36), int(height * 0.08), (36, 42, 56), 0.44)
        for px in (0.22, 0.40, 0.56):
            draw_circle(pixels, width, height, int(width * px), int(height * 0.45), int(height * 0.05), a_rgb, 0.18, fill=True)

    if "graph" in tokens or "network" in tokens or "heat" in tokens or "consequence" in tokens or "thread" in tokens or "conflict" in tokens:
        nodes = [(rng.randint(int(width*0.12), int(width*0.88)), rng.randint(int(height*0.16), int(height*0.84))) for _ in range(9)]
        for x0, y0 in nodes:
            draw_circle(pixels, width, height, x0, y0, 16, a_rgb, 0.38)
        for index in range(len(nodes)-1):
            draw_line(pixels, width, height, nodes[index][0], nodes[index][1], nodes[index+1][0], nodes[index+1][1], b_rgb, 0.22)

    if "mirror" in tokens or "timeline" in tokens or "passport" in tokens or "travel" in tokens:
        draw_rect(pixels, width, height, int(width * 0.18), int(height * 0.20), int(width * 0.20), int(height * 0.42), a_rgb, 0.10)
        draw_rect(pixels, width, height, int(width * 0.50), int(height * 0.20), int(width * 0.20), int(height * 0.42), b_rgb, 0.10)
        draw_line(pixels, width, height, int(width * 0.44), int(height * 0.20), int(width * 0.44), int(height * 0.68), (255, 255, 255), 0.14)

    if "lua" in tokens or "scripted" in tokens or "receipt" in tokens or "support" in tokens or "sr4" in tokens or "sr5" in tokens or "sr6" in tokens:
        draw_rect(pixels, width, height, int(width * 0.58), int(height * 0.68), int(width * 0.24), int(height * 0.10), (255, 255, 255), 0.06)
        for idx in range(6):
            x = int(width * 0.60) + idx * int(width * 0.03)
            draw_line(pixels, width, height, x, int(height * 0.69), x, int(height * 0.76), a_rgb, 0.22)
        for idx in range(3):
            y = int(height * (0.71 + idx * 0.02))
            draw_line(pixels, width, height, int(width * 0.60), y, int(width * 0.80), y, b_rgb, 0.18)

    return rgba_png(width, height, bytes(pixels))


def data_uri(png_bytes: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")


def build_html(prompt: str, output_name: str, *, width: int, height: int) -> str:
    bg, accent_a, accent_b = theme_for(prompt)
    scene = scene_for(output_name, prompt)
    backdrop = data_uri(render_scene_png(prompt, scene, width=width, height=height))
    title = html.escape(scene["title"])
    subtitle = html.escape(scene["subtitle"])
    badge = html.escape(scene["badge"])
    kicker = html.escape(scene["kicker"])
    note = html.escape(scene.get("note", "Chrome, caution, and just enough bad decisions to feel like home."))
    overlay_hint = html.escape(scene.get("overlay_hint", "analysis overlay"))
    overlay_callouts = [html.escape(str(entry)) for entry in scene.get("overlay_callouts", []) if str(entry).strip()]
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
        linear-gradient(180deg, rgba(4,6,12,0.06), rgba(4,6,12,0.72)),
        url('{backdrop}') center / cover no-repeat,
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
    .hud {{
      position: absolute;
      top: 48px;
      right: 56px;
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      width: 360px;
      justify-content: flex-end;
    }}
    .hud-chip {{
      padding: 8px 12px;
      border-radius: 999px;
      font-size: 13px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: rgba(255,255,255,0.82);
      border: 1px solid rgba(255,255,255,0.14);
      background: rgba(6, 10, 18, 0.42);
      backdrop-filter: blur(8px);
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
      margin-top: 60px;
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
    .callout-strip {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      margin-top: 20px;
      max-width: 680px;
    }}
    .callout {{
      padding: 10px 14px;
      border-radius: 14px;
      border: 1px solid rgba(255,255,255,0.14);
      background: rgba(6, 10, 18, 0.48);
      backdrop-filter: blur(8px);
      color: rgba(240, 246, 252, 0.92);
      font-size: 14px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
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
      opacity: 0.36;
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
    <div class="hud">
      <div class="hud-chip">{overlay_hint}</div>
      <div class="hud-chip">OODA</div>
      <div class="hud-chip">Live signal</div>
    </div>
    <div class="chip">{badge}</div>
    <div class="headline">
      <div>
        <div class="title">{title}</div>
        <div class="subtitle">{subtitle}</div>
        {"<div class='callout-strip'>" + "".join(f"<div class='callout'>{entry}</div>" for entry in overlay_callouts[:4]) + "</div>" if overlay_callouts else ""}
      </div>
      <div class="sidecard">
        <div class="small">Street note</div>
        <div class="big">{kicker}</div>
        <div class="line"></div>
        <div class="note">{note}</div>
      </div>
    </div>
    <div class="footer">
      <div class="brand">Chummer6</div>
      <div class="meta">{ratio}</div>
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
