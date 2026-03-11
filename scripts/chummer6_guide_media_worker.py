#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shlex
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


EA_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = EA_ROOT / ".env"
STATE_OUT = Path("/docker/fleet/state/chummer6/ea_media_last.json")
FLEET_GUIDE_SCRIPT = Path("/docker/fleet/scripts/finish_chummer6_guide.py")
DEFAULT_PROVIDER_ORDER = [
    "magixai",
    "markupgo",
    "prompting_systems",
    "browseract_prompting_systems",
    "onemin",
    "local_raster",
]
PALETTES = [
    ("#0f766e", "#34d399"),
    ("#1d4ed8", "#7dd3fc"),
    ("#7c3aed", "#c084fc"),
    ("#7c2d12", "#fb923c"),
    ("#be123c", "#fb7185"),
    ("#4338ca", "#818cf8"),
]


def load_local_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_FILE.exists():
        return values
    for raw in ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


LOCAL_ENV = load_local_env()


def env_value(name: str) -> str:
    return str(os.environ.get(name) or LOCAL_ENV.get(name) or "").strip()


def import_guide_module():
    spec = importlib.util.spec_from_file_location("finish_chummer6_guide", FLEET_GUIDE_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {FLEET_GUIDE_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GUIDE = import_guide_module()


def provider_order() -> list[str]:
    raw = env_value("CHUMMER6_IMAGE_PROVIDER_ORDER")
    if not raw:
        return list(DEFAULT_PROVIDER_ORDER)
    values = [part.strip().lower() for part in raw.split(",") if part.strip()]
    return values or list(DEFAULT_PROVIDER_ORDER)


def shlex_command(env_name: str) -> list[str]:
    raw = env_value(env_name)
    return shlex.split(raw) if raw else []


def url_template(env_name: str) -> str:
    return env_value(env_name)


def format_command(parts: list[str], *, prompt: str, output: str, width: int, height: int) -> list[str]:
    return [part.format(prompt=prompt, output=output, width=width, height=height) for part in parts]


def run_command_provider(name: str, template: list[str], *, prompt: str, output_path: Path, width: int, height: int) -> tuple[bool, str]:
    if not template:
        return False, f"{name}:not_configured"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            format_command(template, prompt=prompt, output=str(output_path), width=width, height=height),
            check=True,
            text=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        return False, f"{name}:command_failed:{detail[:240]}"
    if output_path.exists() and output_path.stat().st_size > 0:
        return True, f"{name}:rendered"
    return False, f"{name}:empty_output"


def run_url_provider(name: str, template: str, *, prompt: str, output_path: Path, width: int, height: int) -> tuple[bool, str]:
    if not template:
        return False, f"{name}:not_configured"
    url = template.format(
        prompt=urllib.parse.quote(prompt, safe=""),
        width=width,
        height=height,
        output=urllib.parse.quote(str(output_path), safe=""),
    )
    request = urllib.request.Request(url, headers={"User-Agent": "EA-Chummer6-Media/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        return False, f"{name}:http_{exc.code}:{body[:240]}"
    except urllib.error.URLError as exc:
        return False, f"{name}:urlerror:{exc.reason}"
    if not data:
        return False, f"{name}:empty_output"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(data)
    return True, f"{name}:rendered"


def palette_for(prompt: str) -> tuple[str, str]:
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    return PALETTES[int(digest[:2], 16) % len(PALETTES)]


def title_for(prompt: str, output_path: Path) -> str:
    stem = output_path.stem.replace("-", " ").replace("_", " ").strip()
    if stem:
        return stem.title()
    words = [word for word in prompt.split() if word.isalpha()]
    return " ".join(words[:3]).title() or "Chummer6"


def layout_for(output_path: Path) -> str:
    name = output_path.name.lower()
    if "program-map" in name:
        return "grid"
    if "status-strip" in name:
        return "status"
    return "banner"


def render_local_raster(*, prompt: str, output_path: Path, width: int, height: int) -> tuple[bool, str]:
    accent, glow = palette_for(prompt)
    title = title_for(prompt, output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".gif":
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            for index in range(6):
                frame = GUIDE.synth_cyberpunk_png(
                    title,
                    accent,
                    glow,
                    width=width,
                    height=height,
                    phase=index * 0.55,
                    layout="banner",
                )
                (tmp / f"frame-{index:02d}.png").write_bytes(frame)
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-framerate",
                    "4",
                    "-i",
                    str(tmp / "frame-%02d.png"),
                    "-vf",
                    f"scale={width}:{height}:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        return True, "local_raster:animated"
    output_path.write_bytes(
        GUIDE.synth_cyberpunk_png(
            title,
            accent,
            glow,
            width=width,
            height=height,
            layout=layout_for(output_path),
        )
    )
    return True, "local_raster:rendered"


def render_with_ooda(*, prompt: str, output_path: Path, width: int, height: int) -> dict[str, object]:
    attempts: list[str] = []
    for provider in provider_order():
        normalized = provider.strip().lower()
        if normalized == "magixai":
            ok, detail = run_command_provider("magixai", shlex_command("CHUMMER6_MAGIXAI_RENDER_COMMAND"), prompt=prompt, output_path=output_path, width=width, height=height)
            if not ok:
                ok, detail = run_url_provider("magixai", url_template("CHUMMER6_MAGIXAI_RENDER_URL_TEMPLATE"), prompt=prompt, output_path=output_path, width=width, height=height)
        elif normalized == "markupgo":
            ok, detail = run_command_provider("markupgo", shlex_command("CHUMMER6_MARKUPGO_RENDER_COMMAND"), prompt=prompt, output_path=output_path, width=width, height=height)
            if not ok:
                ok, detail = run_url_provider("markupgo", url_template("CHUMMER6_MARKUPGO_RENDER_URL_TEMPLATE"), prompt=prompt, output_path=output_path, width=width, height=height)
        elif normalized == "prompting_systems":
            ok, detail = run_command_provider("prompting_systems", shlex_command("CHUMMER6_PROMPTING_SYSTEMS_RENDER_COMMAND"), prompt=prompt, output_path=output_path, width=width, height=height)
            if not ok:
                ok, detail = run_url_provider("prompting_systems", url_template("CHUMMER6_PROMPTING_SYSTEMS_RENDER_URL_TEMPLATE"), prompt=prompt, output_path=output_path, width=width, height=height)
        elif normalized == "browseract_prompting_systems":
            if env_value("BROWSERACT_API_KEY"):
                ok, detail = run_command_provider("browseract_prompting_systems", shlex_command("CHUMMER6_PROMPTING_SYSTEMS_RENDER_COMMAND"), prompt=prompt, output_path=output_path, width=width, height=height)
                if not ok:
                    ok, detail = run_url_provider("browseract_prompting_systems", url_template("CHUMMER6_PROMPTING_SYSTEMS_RENDER_URL_TEMPLATE"), prompt=prompt, output_path=output_path, width=width, height=height)
            else:
                ok, detail = False, "browseract_prompting_systems:not_configured"
        elif normalized in {"onemin", "1min", "1min.ai", "oneminai"}:
            ok, detail = run_command_provider("onemin", shlex_command("CHUMMER6_1MIN_RENDER_COMMAND"), prompt=prompt, output_path=output_path, width=width, height=height)
            if not ok:
                ok, detail = run_url_provider("onemin", url_template("CHUMMER6_1MIN_RENDER_URL_TEMPLATE"), prompt=prompt, output_path=output_path, width=width, height=height)
        elif normalized == "local_raster":
            ok, detail = render_local_raster(prompt=prompt, output_path=output_path, width=width, height=height)
        else:
            ok, detail = False, f"{normalized}:unknown_provider"
        attempts.append(detail)
        if ok:
            return {"provider": normalized, "status": detail, "attempts": attempts}
    raise RuntimeError("no image provider succeeded: " + " || ".join(attempts))


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a Chummer6 guide asset through EA provider selection.")
    sub = parser.add_subparsers(dest="command", required=True)
    render = sub.add_parser("render")
    render.add_argument("--prompt", required=True)
    render.add_argument("--output", required=True)
    render.add_argument("--width", type=int, default=1280)
    render.add_argument("--height", type=int, default=720)
    args = parser.parse_args()

    output_path = Path(args.output).expanduser()
    result = render_with_ooda(prompt=str(args.prompt), output_path=output_path, width=int(args.width), height=int(args.height))
    STATE_OUT.parent.mkdir(parents=True, exist_ok=True)
    STATE_OUT.write_text(json.dumps({"output": str(output_path), **result}, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output_path), "provider": result["provider"], "status": result["status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
