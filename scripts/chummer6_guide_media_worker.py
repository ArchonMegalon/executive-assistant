#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import importlib.util
import json
import os
import shlex
import subprocess
import tempfile
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


EA_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = EA_ROOT / ".env"
STATE_OUT = Path("/docker/fleet/state/chummer6/ea_media_last.json")
MANIFEST_OUT = Path("/docker/fleet/state/chummer6/ea_media_manifest.json")
FLEET_GUIDE_SCRIPT = Path("/docker/fleet/scripts/finish_chummer6_guide.py")
DEFAULT_PROVIDER_ORDER = [
    "onemin",
    "magixai",
    "browseract_magixai",
    "browseract_prompting_systems",
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


def provider_busy_retries() -> int:
    raw = env_value("CHUMMER6_PROVIDER_BUSY_RETRIES") or env_value("CHUMMER6_1MIN_BUSY_RETRIES") or "3"
    try:
        return max(1, int(raw))
    except Exception:
        return 3


def provider_busy_delay_seconds() -> int:
    raw = env_value("CHUMMER6_PROVIDER_BUSY_DELAY_SECONDS") or env_value("CHUMMER6_1MIN_BUSY_DELAY_SECONDS") or "3"
    try:
        return max(1, int(raw))
    except Exception:
        return 3


def import_guide_module():
    spec = importlib.util.spec_from_file_location("finish_chummer6_guide", FLEET_GUIDE_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {FLEET_GUIDE_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GUIDE = import_guide_module()


def provider_order() -> list[str]:
    preferred = ["onemin", "magixai", "browseract_magixai", "browseract_prompting_systems"]
    raw = env_value("CHUMMER6_IMAGE_PROVIDER_ORDER")
    if not raw:
        return list(preferred)
    values = [part.strip().lower() for part in raw.split(",") if part.strip()]
    filtered = [
        value
        for value in values
        if value not in {"local_raster", "markupgo", "ooda_compositor", "scene_contract_renderer", "pollinations"}
    ]
    ordered = sorted(
        dict.fromkeys(filtered),
        key=lambda value: preferred.index(value) if value in preferred else len(preferred),
    )
    return ordered or list(preferred)


OVERRIDE_PATH = Path("/docker/fleet/state/chummer6/ea_overrides.json")


def shlex_command(env_name: str) -> list[str]:
    raw = env_value(env_name)
    if raw:
        return shlex.split(raw)
    defaults = {
        "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_RENDER_COMMAND": [
            "python3",
            str(EA_ROOT / "scripts" / "chummer6_browseract_prompting_systems.py"),
            "render",
            "--kind",
            "prompting_render",
            "--prompt",
            "{prompt}",
            "--target",
            "{target}",
            "--output",
            "{output}",
            "--width",
            "{width}",
            "--height",
            "{height}",
        ],
        "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_COMMAND": [
            "python3",
            str(EA_ROOT / "scripts" / "chummer6_browseract_prompting_systems.py"),
            "refine",
            "--prompt",
            "{prompt}",
            "--target",
            "{target}",
        ],
        "CHUMMER6_BROWSERACT_MAGIXAI_RENDER_COMMAND": [
            "python3",
            str(EA_ROOT / "scripts" / "chummer6_browseract_prompting_systems.py"),
            "render",
            "--kind",
            "magixai_render",
            "--prompt",
            "{prompt}",
            "--target",
            "{target}",
            "--output",
            "{output}",
            "--width",
            "{width}",
            "--height",
            "{height}",
        ],
        "CHUMMER6_PROMPT_REFINER_COMMAND": [
            "python3",
            str(EA_ROOT / "scripts" / "chummer6_browseract_prompting_systems.py"),
            "refine",
            "--prompt",
            "{prompt}",
            "--target",
            "{target}",
        ],
    }
    return list(defaults.get(env_name, []))


def url_template(env_name: str) -> str:
    return env_value(env_name)


def load_media_overrides() -> dict[str, object]:
    if not OVERRIDE_PATH.exists():
        return {}
    try:
        loaded = json.loads(OVERRIDE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def format_command(parts: list[str], *, prompt: str, target: str, output: str, width: int, height: int) -> list[str]:
    return [part.format(prompt=prompt, target=target, output=output, width=width, height=height) for part in parts]


def run_command_provider(name: str, template: list[str], *, prompt: str, output_path: Path, width: int, height: int) -> tuple[bool, str]:
    if not template:
        return False, f"{name}:not_configured"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            format_command(
                template,
                prompt=prompt,
                target=output_path.stem,
                output=str(output_path),
                width=width,
                height=height,
            ),
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


def run_pollinations_provider(*, prompt: str, output_path: Path, width: int, height: int) -> tuple[bool, str]:
    seed = int(hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:8], 16)
    endpoint = "https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt, safe="")
    configured = [entry.strip() for entry in env_value("CHUMMER6_POLLINATIONS_MODEL").split(",") if entry.strip()]
    candidates = configured or ["flux", "turbo", "flux-realism"]
    attempts: list[str] = []
    for model in candidates:
        params = {
            "width": str(width),
            "height": str(height),
            "nologo": "true",
            "seed": str(seed),
            "model": model,
        }
        url = endpoint + "?" + urllib.parse.urlencode(params)
        ok, detail = _download_remote_image(url, output_path=output_path, name=f"pollinations:{model}")
        attempts.append(detail)
        if ok:
            return ok, detail
    return False, " || ".join(attempts)


def _download_remote_image(url: str, *, output_path: Path, name: str) -> tuple[bool, str]:
    request = urllib.request.Request(url, headers={"User-Agent": f"EA-Chummer6-{name}/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        return False, f"{name}:image_http_{exc.code}:{body[:240]}"
    except urllib.error.URLError as exc:
        return False, f"{name}:image_urlerror:{exc.reason}"
    if not data:
        return False, f"{name}:image_empty_output"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(data)
    return True, f"{name}:rendered"


def run_magixai_api_provider(*, prompt: str, output_path: Path, width: int, height: int) -> tuple[bool, str]:
    api_key = env_value("AI_MAGICX_API_KEY")
    if not api_key:
        return False, "magixai:not_configured"
    model = env_value("CHUMMER6_MAGIXAI_MODEL") or "qwen-image"
    size = f"{width}x{height}"
    endpoint_specs = [
        (
            "/api/v1/ai-image/generate",
            {
                "model": model,
                "prompt": prompt,
                "size": size,
                "quality": "high",
                "style": "cinematic",
                "negative_prompt": "text, logo, watermark, UI labels, prompt text, low quality, blurry",
                "response_format": "url",
            },
        ),
        (
            "/ai-image/generate",
            {
                "model": model,
                "prompt": prompt,
                "size": size,
                "quality": "high",
                "style": "cinematic",
                "negative_prompt": "text, logo, watermark, UI labels, prompt text, low quality, blurry",
                "response_format": "url",
            },
        ),
        (
            "/api/v1/images/generations",
            {
                "model": model,
                "prompt": prompt,
                "size": size,
                "quality": "high",
                "response_format": "url",
                "n": 1,
            },
        ),
        (
            "/images/generations",
            {
                "model": model,
                "prompt": prompt,
                "size": size,
                "quality": "high",
                "response_format": "url",
                "n": 1,
            },
        ),
        (
            "/api/v1/ai-image/generate",
            {
                "model": model,
                "prompt": prompt,
                "image_size": size,
                "num_images": 1,
                "style": "cinematic",
                "negative_prompt": "text, logo, watermark, UI labels, prompt text, low quality, blurry",
                "response_format": "url",
            },
        ),
    ]
    configured_base = env_value("CHUMMER6_MAGIXAI_BASE_URL") or "https://api.aimagicx.com/api/v1"
    base_urls: list[str] = []
    for candidate in (
        configured_base,
        "https://api.aimagicx.com/api/v1",
        "https://api.aimagicx.com/api",
        "https://api.aimagicx.com",
        "https://beta.aimagicx.com/api/v1",
        "https://beta.aimagicx.com/api",
        "https://www.aimagicx.com/api/v1",
        "https://www.aimagicx.com/api",
        "https://beta.aimagicx.com",
        "https://www.aimagicx.com",
    ):
        normalized = str(candidate or "").strip().rstrip("/")
        if not normalized or normalized in base_urls:
            continue
        base_urls.append(normalized)
    def build_url(base_url: str, endpoint: str) -> str:
        clean_base = base_url.rstrip("/")
        clean_endpoint = endpoint.lstrip("/")
        if clean_base.endswith("/api/v1") and clean_endpoint.startswith("api/v1/"):
            clean_endpoint = clean_endpoint[len("api/v1/") :]
        elif clean_base.endswith("/api") and clean_endpoint.startswith("api/"):
            clean_endpoint = clean_endpoint[len("api/") :]
        return clean_base + "/" + clean_endpoint
    header_variants = [
        {
            "User-Agent": "EA-Chummer6-Magicx/1.0",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        {
            "User-Agent": "EA-Chummer6-Magicx/1.0",
            "Content-Type": "application/json",
            "X-API-Key": api_key,
        },
        {
            "User-Agent": "EA-Chummer6-Magicx/1.0",
            "Content-Type": "application/json",
            "API-KEY": api_key,
        },
    ]
    errors: list[str] = []
    seen_requests: set[tuple[str, tuple[tuple[str, str], ...], str]] = set()
    for base_url in base_urls:
        for endpoint, payload in endpoint_specs:
            url = build_url(base_url, endpoint)
            payload_json = json.dumps(payload, sort_keys=True)
            for headers in header_variants:
                header_key = tuple(sorted((str(key), str(value)) for key, value in headers.items()))
                request_key = (url, header_key, payload_json)
                if request_key in seen_requests:
                    continue
                seen_requests.add(request_key)
                request = urllib.request.Request(
                    url,
                    headers=headers,
                    data=payload_json.encode("utf-8"),
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(request, timeout=45) as response:
                        data = response.read()
                        content_type = str(response.headers.get("Content-Type") or "").lower()
                except urllib.error.HTTPError as exc:
                    body = exc.read().decode("utf-8", errors="replace").strip()
                    errors.append(f"{url}:http_{exc.code}:{body[:180]}")
                    continue
                except urllib.error.URLError as exc:
                    errors.append(f"{url}:urlerror:{exc.reason}")
                    continue
                if data:
                    if content_type.startswith("image/"):
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        output_path.write_bytes(data)
                        return True, "magixai:rendered"
                    decoded = data.decode("utf-8", errors="replace").strip()
                    if decoded.startswith("http://") or decoded.startswith("https://"):
                        ok, detail = _download_remote_image(decoded, output_path=output_path, name="magixai")
                        if ok:
                            return ok, detail
                        errors.append(detail)
                        continue
                    try:
                        body = json.loads(decoded)
                    except Exception:
                        errors.append(f"{url}:non_json_response:{decoded[:180]}")
                        continue
                candidates: list[str] = []
                if isinstance(body, dict):
                    for field in ("url", "image_url"):
                        value = str(body.get(field) or "").strip()
                        if value:
                            candidates.append(value)
                    data_rows = body.get("data")
                    if isinstance(data_rows, list):
                        for entry in data_rows:
                            if not isinstance(entry, dict):
                                continue
                            value = str(entry.get("url") or entry.get("image_url") or "").strip()
                            if value:
                                candidates.append(value)
                    output_rows = body.get("output")
                    if isinstance(output_rows, list):
                        for entry in output_rows:
                            if not isinstance(entry, dict):
                                continue
                            value = str(entry.get("url") or entry.get("image_url") or "").strip()
                            if value:
                                candidates.append(value)
                for candidate in candidates:
                    ok, detail = _download_remote_image(candidate, output_path=output_path, name="magixai")
                    if ok:
                        return ok, detail
                    errors.append(detail)
    return False, "magixai:" + " || ".join(errors[:6])


def resolve_onemin_image_keys() -> list[str]:
    script_path = EA_ROOT / "scripts" / "resolve_onemin_ai_key.sh"
    keys: list[str] = []
    seen: set[str] = set()
    if script_path.exists():
        try:
            output = subprocess.check_output(
                ["bash", str(script_path), "--all"],
                text=True,
            )
        except Exception:
            output = ""
        for raw in output.splitlines():
            key = str(raw or "").strip()
            if key and key not in seen:
                seen.add(key)
                keys.append(key)
    for env_name in ("ONEMIN_AI_API_KEY", "ONEMIN_AI_API_KEY_FALLBACK_1", "ONEMIN_AI_API_KEY_FALLBACK_2", "ONEMIN_AI_API_KEY_FALLBACK_3"):
        key = env_value(env_name)
        if key and key not in seen:
            seen.add(key)
            keys.append(key)
    if str(env_value("CHUMMER6_ONEMIN_USE_FALLBACK_KEYS") or "").strip().lower() not in {"1", "true", "yes", "on"}:
        primary = keys[:1]
        if primary:
            return primary
    return keys


def _collect_image_candidates(value: object) -> list[str]:
    found: list[str] = []
    if isinstance(value, str):
        candidate = str(value or "").strip()
        lowered = candidate.lower()
        if candidate.startswith("http://") or candidate.startswith("https://"):
            found.append(candidate)
        elif candidate.startswith("/"):
            found.append("https://api.1min.ai" + candidate)
        elif any(token in lowered for token in ("asset", "image", "render", "download")) and ("/" in candidate or "." in candidate):
            found.append("https://api.1min.ai/" + candidate.lstrip("/"))
        return found
    if isinstance(value, dict):
        for nested in value.values():
            found.extend(_collect_image_candidates(nested))
        return found
    if isinstance(value, (list, tuple, set)):
        for nested in value:
            found.extend(_collect_image_candidates(nested))
    return found


def run_onemin_api_provider(*, prompt: str, output_path: Path, width: int, height: int) -> tuple[bool, str]:
    keys = resolve_onemin_image_keys()
    if not keys:
        return False, "onemin:not_configured"
    model_candidates: list[str] = []
    for candidate in (
        env_value("CHUMMER6_ONEMIN_MODEL"),
        "gpt-image-1",
        "gpt-image-1-mini",
        "dall-e-3",
    ):
        normalized = str(candidate or "").strip()
        if normalized and normalized not in model_candidates:
            model_candidates.append(normalized)
    size = env_value("CHUMMER6_ONEMIN_IMAGE_SIZE") or "512x512"
    endpoints = [
        env_value("CHUMMER6_ONEMIN_ENDPOINT") or "https://api.1min.ai/api/features",
    ]
    errors: list[str] = []
    header_variants = []
    for key in keys:
        header_variants.append(
            {
                "User-Agent": "EA-Chummer6-1min/1.0",
                "Content-Type": "application/json",
                "API-KEY": key,
            }
        )
    seen_requests: set[tuple[str, tuple[tuple[str, str], ...], str]] = set()
    for url in endpoints:
        for model in model_candidates:
            prompt_object = {
                "prompt": prompt,
                "n": 1,
                "size": size,
                "quality": env_value("CHUMMER6_ONEMIN_IMAGE_QUALITY") or "low",
                "style": "natural",
                "output_format": "png",
                "background": "opaque",
            }
            payloads = [
                {
                    "type": "IMAGE_GENERATOR",
                    "model": model,
                    "promptObject": dict(prompt_object),
                },
            ]
            for payload in payloads:
                payload_json = json.dumps(payload, sort_keys=True)
                for headers in header_variants:
                    header_key = tuple(sorted((str(key), str(value)) for key, value in headers.items()))
                    request_key = (url, header_key, payload_json)
                    if request_key in seen_requests:
                        continue
                    seen_requests.add(request_key)
                    request = urllib.request.Request(
                        url,
                        headers=headers,
                        data=payload_json.encode("utf-8"),
                        method="POST",
                    )
                    try:
                        with urllib.request.urlopen(request, timeout=45) as response:
                            data = response.read()
                            content_type = str(response.headers.get("Content-Type") or "").lower()
                    except urllib.error.HTTPError as exc:
                        body = exc.read().decode("utf-8", errors="replace").strip()
                        retryable_busy = exc.code == 400 and "OPEN_AI_UNEXPECTED_ERROR" in body
                        if retryable_busy:
                            busy_recovered = False
                            for _attempt in range(provider_busy_retries()):
                                time.sleep(provider_busy_delay_seconds())
                                try:
                                    request = urllib.request.Request(
                                        url,
                                        headers=headers,
                                        data=payload_json.encode("utf-8"),
                                        method="POST",
                                    )
                                    with urllib.request.urlopen(request, timeout=45) as response:
                                        data = response.read()
                                        content_type = str(response.headers.get("Content-Type") or "").lower()
                                        busy_recovered = True
                                        break
                                except urllib.error.HTTPError as retry_exc:
                                    body = retry_exc.read().decode("utf-8", errors="replace").strip()
                                    retryable_busy = retry_exc.code == 400 and "OPEN_AI_UNEXPECTED_ERROR" in body
                                    if not retryable_busy:
                                        errors.append(f"{url}:{model}:http_{retry_exc.code}:{body[:180]}")
                                        break
                                except urllib.error.URLError as retry_url_exc:
                                    errors.append(f"{url}:{model}:urlerror:{retry_url_exc.reason}")
                                    break
                            if not busy_recovered:
                                if retryable_busy:
                                    errors.append(f"{url}:{model}:openai_busy")
                                continue
                        else:
                            errors.append(f"{url}:{model}:http_{exc.code}:{body[:180]}")
                            if exc.code == 401:
                                break
                            continue
                    except urllib.error.URLError as exc:
                        errors.append(f"{url}:{model}:urlerror:{exc.reason}")
                        continue
                    if data:
                        if content_type.startswith("image/"):
                            output_path.parent.mkdir(parents=True, exist_ok=True)
                            output_path.write_bytes(data)
                            return True, "onemin:rendered"
                        decoded = data.decode("utf-8", errors="replace").strip()
                        if decoded.startswith("http://") or decoded.startswith("https://"):
                            ok, detail = _download_remote_image(decoded, output_path=output_path, name="onemin")
                            if ok:
                                return ok, detail
                            errors.append(detail)
                            continue
                        try:
                            body = json.loads(decoded)
                        except Exception:
                            errors.append(f"{url}:{model}:non_json_response:{decoded[:180]}")
                            continue
                        for candidate in _collect_image_candidates(body):
                            ok, detail = _download_remote_image(candidate, output_path=output_path, name="onemin")
                            if ok:
                                return ok, detail
                            errors.append(detail)
    return False, "onemin:" + " || ".join(errors[:6])


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


def _font_path(bold: bool = False) -> str:
    path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    return path


def _write_text_file(directory: Path, name: str, value: str, *, width: int) -> Path:
    wrapped = textwrap.fill(" ".join(str(value or "").split()).strip(), width=width)
    path = directory / name
    path.write_text(wrapped + "\n", encoding="utf-8")
    return path


def _ffmpeg_path(value: Path) -> str:
    return str(value).replace("\\", "\\\\").replace(":", "\\:")


def _ooda_layout_for(target: str) -> str:
    lowered = str(target or "").lower()
    if "horizons-index" in lowered or "parts-index" in lowered:
        return "grid"
    if "current-status" in lowered or "public-surfaces" in lowered:
        return "status"
    return "banner"


def run_ooda_compositor(*, spec: dict[str, object], prompt: str, output_path: Path, width: int, height: int) -> tuple[bool, str]:
    row = spec.get("media_row") if isinstance(spec.get("media_row"), dict) else {}
    if not isinstance(row, dict):
        return False, "ooda_compositor:missing_media_row"
    title = " ".join(str(row.get("title", "") or output_path.stem).split()).strip() or output_path.stem.replace("-", " ").title()
    subtitle = " ".join(str(row.get("subtitle", "")).split()).strip()
    kicker = " ".join(str(row.get("kicker", "")).split()).strip()
    note = " ".join(str(row.get("note", "")).split()).strip()
    overlay_hint = " ".join(str(row.get("overlay_hint", "")).split()).strip()
    callouts = [str(entry).strip() for entry in (row.get("overlay_callouts") or []) if str(entry).strip()]
    motifs = [str(entry).strip() for entry in (row.get("visual_motifs") or []) if str(entry).strip()]
    scene_contract = row.get("scene_contract") if isinstance(row.get("scene_contract"), dict) else {}
    if not scene_contract or not str(scene_contract.get("visual_prompt") or row.get("visual_prompt") or "").strip():
        return False, "ooda_compositor:missing_scene_contract"
    layout = _ooda_layout_for(str(spec.get("target", output_path.name)))
    accent, glow = palette_for(prompt + "::" + title + "::" + str(scene_contract.get("palette", "")))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(
        GUIDE.synth_context_scene_png(
            title,
            accent,
            glow,
            scene_contract,
            scene_row=row,
            width=width,
            height=height,
            layout=layout,
        )
    )
    return True, "scene_contract_renderer:rendered"


def refine_prompt_local(prompt: str, *, target: str) -> str:
    return " ".join(prompt.split()).strip()


def refine_prompt_with_ooda(*, prompt: str, target: str) -> str:
    # Prompt refinement must use the external lane when it is configured.
    command_names = [
        "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_COMMAND",
        "CHUMMER6_PROMPTING_SYSTEMS_REFINE_COMMAND",
        "CHUMMER6_PROMPT_REFINER_COMMAND",
    ]
    template_names = [
        "CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_REFINE_URL_TEMPLATE",
        "CHUMMER6_PROMPTING_SYSTEMS_REFINE_URL_TEMPLATE",
        "CHUMMER6_PROMPT_REFINER_URL_TEMPLATE",
    ]
    attempted: list[str] = []
    external_expected = bool(env_value("BROWSERACT_API_KEY"))
    for env_name in command_names:
        command = shlex_command(env_name)
        if not command:
            continue
        external_expected = True
        try:
            completed = subprocess.run(
                [part.format(prompt=prompt, target=target) for part in command],
                check=True,
                text=True,
                capture_output=True,
            )
            refined = (completed.stdout or "").strip()
            if refined:
                return refined
            attempted.append(f"{env_name}:empty_output")
        except Exception as exc:
            attempted.append(f"{env_name}:{exc}")
    for env_name in template_names:
        template = url_template(env_name)
        if not template:
            continue
        external_expected = True
        url = template.format(
            prompt=urllib.parse.quote(prompt, safe=""),
            target=urllib.parse.quote(target, safe=""),
        )
        request = urllib.request.Request(url, headers={"User-Agent": "EA-Chummer6-PromptRefiner/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                refined = response.read().decode("utf-8", errors="replace").strip()
            if refined:
                return refined
            attempted.append(f"{env_name}:empty_output")
        except Exception as exc:
            attempted.append(f"{env_name}:{exc}")
    if external_expected:
        detail = " || ".join(attempted) if attempted else "no_external_refiner_succeeded"
        raise RuntimeError(f"prompt_refinement_failed:{detail}")
    return refine_prompt_local(prompt, target=target)


def sanitize_prompt_for_provider(prompt: str, *, provider: str) -> str:
    cleaned = " ".join(str(prompt or "").split()).strip()
    if not cleaned:
        return cleaned
    provider_name = str(provider or "").strip().lower()
    if provider_name in {"onemin", "1min", "1min.ai", "oneminai"}:
        replacements = {
            "Shadowrun": "cyberpunk tabletop",
            "shadowrun": "cyberpunk tabletop",
            "runner": "operative",
            "runners": "operatives",
            "dangerous": "tense",
            "combat": "tactical simulation",
            "crash-test dummy": "test mannequin",
            "crash test dummy": "test mannequin",
            "weapon": "gear",
            "weapons": "gear",
            "gun": "tool",
            "guns": "tools",
            "blood": "stress",
            "gore": "damage",
        }
        for src, dst in replacements.items():
            cleaned = cleaned.replace(src, dst)
        cleaned += " Safe-for-work, nonviolent, no gore, no weapons, no explicit danger."
    return cleaned


def build_safe_pollinations_prompt(*, prompt: str, spec: dict[str, object]) -> str:
    row = spec.get("media_row") if isinstance(spec, dict) else {}
    contract = row.get("scene_contract") if isinstance(row, dict) else {}
    if not isinstance(contract, dict):
        cleaned = " ".join(str(prompt or "").split()).strip()
        return cleaned[:220]
    subject = str(contract.get("subject") or "a cyberpunk protagonist").strip()
    environment = str(contract.get("environment") or "a neon-lit cyberpunk setting").strip()
    action = str(contract.get("action") or "holding the moment together").strip()
    metaphor = str(contract.get("metaphor") or "").strip()
    palette = str(contract.get("palette") or "rainy neon cyan and magenta").strip()
    mood = str(contract.get("mood") or "tense but inviting").strip()
    parts = [
        "Wide cinematic cyberpunk concept art",
        subject,
        f"in {environment}",
        action,
        metaphor if metaphor else "",
        mood,
        palette,
        "one focal subject",
        "no text no logo no watermark 16:9",
    ]
    return ", ".join(part for part in parts if part)[:240]


def build_safe_onemin_prompt(*, prompt: str, spec: dict[str, object]) -> str:
    row = spec.get("media_row") if isinstance(spec, dict) else {}
    contract = row.get("scene_contract") if isinstance(row, dict) else {}
    if not isinstance(contract, dict):
        return sanitize_prompt_for_provider(prompt, provider="onemin")
    subject = str(contract.get("subject") or "a cyberpunk protagonist").strip()
    environment = str(contract.get("environment") or "a neon-lit cyberpunk setting").strip()
    action = str(contract.get("action") or "holding the moment together").strip()
    metaphor = str(contract.get("metaphor") or "").strip()
    composition = str(contract.get("composition") or "single_protagonist").strip()
    palette = str(contract.get("palette") or "cool neon").strip()
    mood = str(contract.get("mood") or "focused").strip()
    props = ", ".join(str(entry).strip() for entry in (contract.get("props") or []) if str(entry).strip())
    overlays = ", ".join(str(entry).strip() for entry in (contract.get("overlays") or []) if str(entry).strip())
    parts = [
        "Wide cinematic cyberpunk concept art.",
        prompt,
        f"Subject: {subject}.",
        f"Environment: {environment}.",
        f"Action: {action}.",
        f"Visual metaphor: {metaphor}." if metaphor else "",
        f"Composition: {composition}.",
        f"Palette: {palette}.",
        f"Mood: {mood}.",
        f"Visible props: {props}." if props else "",
        f"Diegetic overlays: {overlays}." if overlays else "",
        "Keep the scene grounded, readable, and specific instead of generic poster collage.",
        "Safe-for-work, no gore, no watermark, no printed prompt text.",
        "No text, no logo, no watermark, 16:9.",
    ]
    return sanitize_prompt_for_provider(" ".join(part for part in parts if part), provider="onemin")


def _overlay_family(row: dict[str, object], spec: dict[str, object]) -> str:
    contract = row.get("scene_contract") if isinstance(row.get("scene_contract"), dict) else {}
    tokens = " ".join(
        [
            str(spec.get("target") or ""),
            str(row.get("overlay_hint") or ""),
            " ".join(str(entry).strip() for entry in (row.get("overlay_callouts") or []) if str(entry).strip()),
            str(contract.get("metaphor") or ""),
            str(contract.get("composition") or ""),
        ]
    ).lower()
    if any(token in tokens for token in ("x-ray", "xray", "modifier", "causality", "receipt trace")):
        return "xray"
    if any(token in tokens for token in ("replay", "seed", "timeline", "sim", "simulation")):
        return "replay"
    if any(token in tokens for token in ("dossier", "evidence", "briefing", "jackpoint")):
        return "dossier"
    if any(token in tokens for token in ("heat", "web", "network", "conspiracy")):
        return "network"
    if any(token in tokens for token in ("passport", "border", "compatibility")):
        return "passport"
    if any(token in tokens for token in ("forge", "anvil", "rules shard")):
        return "forge"
    return "hud"


def _ffmpeg_color(value: str, alpha: float) -> str:
    normalized = str(value or "#34d399").strip()
    if normalized.startswith("#"):
        normalized = "0x" + normalized[1:]
    return f"{normalized}@{alpha:.2f}"


def _overlay_filter_for(*, family: str, accent: str, glow: str, width: int, height: int) -> str:
    accent_soft = _ffmpeg_color(accent, 0.12)
    accent_hard = _ffmpeg_color(accent, 0.24)
    glow_soft = _ffmpeg_color(glow, 0.10)
    left_box = f"drawbox=x=24:y=24:w={max(180, width // 5)}:h={max(44, height // 9)}:color={accent_soft}:t=fill"
    bottom_strip = f"drawbox=x=24:y={max(24, height - 92)}:w={max(220, width // 2)}:h=56:color={glow_soft}:t=fill"
    corner_a = f"drawbox=x=18:y=18:w={max(140, width // 6)}:h=3:color={accent_hard}:t=fill"
    corner_b = f"drawbox=x=18:y=18:w=3:h={max(96, height // 6)}:color={accent_hard}:t=fill"
    if family == "xray":
        return ",".join(
            [
                f"drawgrid=w={max(48, width // 16)}:h={max(48, height // 9)}:t=1:c={glow_soft}",
                f"drawbox=x={width // 3}:y=0:w={max(18, width // 7)}:h={height}:color={accent_soft}:t=fill",
                left_box,
                bottom_strip,
                corner_a,
                corner_b,
            ]
        )
    if family == "replay":
        return ",".join(
            [
                f"drawbox=x=24:y={height // 2}:w={max(220, width - 48)}:h=4:color={accent_hard}:t=fill",
                f"drawbox=x={width // 2 - 2}:y={height // 2 - 20}:w=4:h=40:color={accent_hard}:t=fill",
                left_box,
                bottom_strip,
            ]
        )
    if family == "dossier":
        return ",".join(
            [
                left_box,
                f"drawbox=x={max(40, width - width // 3)}:y=32:w={max(180, width // 4)}:h={max(72, height // 5)}:color={accent_soft}:t=fill",
                f"drawbox=x={max(56, width - width // 3)}:y={height // 2}:w={max(200, width // 4)}:h={max(120, height // 4)}:color={glow_soft}:t=fill",
                bottom_strip,
            ]
        )
    if family == "network":
        return ",".join(
            [
                f"drawgrid=w={max(72, width // 10)}:h={max(72, height // 7)}:t=1:c={glow_soft}",
                f"drawbox=x={width // 5}:y={height // 3}:w=10:h=10:color={accent_hard}:t=fill",
                f"drawbox=x={width // 2}:y={height // 4}:w=10:h=10:color={accent_hard}:t=fill",
                f"drawbox=x={width - width // 4}:y={height // 2}:w=10:h=10:color={accent_hard}:t=fill",
                bottom_strip,
            ]
        )
    if family == "passport":
        return ",".join(
            [
                left_box,
                f"drawbox=x={width // 2 - 1}:y=24:w=2:h={height - 48}:color={accent_hard}:t=fill",
                f"drawbox=x={width // 2 + 12}:y=32:w={max(180, width // 4)}:h={max(72, height // 6)}:color={glow_soft}:t=fill",
                bottom_strip,
            ]
        )
    if family == "forge":
        return ",".join(
            [
                f"drawbox=x=24:y={height - 110}:w={width - 48}:h=4:color={accent_hard}:t=fill",
                f"drawbox=x={width // 2 - 32}:y={height // 3}:w=64:h=64:color={accent_soft}:t=fill",
                left_box,
                corner_a,
                corner_b,
            ]
        )
    return ",".join([left_box, bottom_strip, corner_a, corner_b])


def apply_context_overlay(*, output_path: Path, spec: dict[str, object], width: int, height: int) -> tuple[bool, str]:
    row = spec.get("media_row") if isinstance(spec.get("media_row"), dict) else {}
    if not isinstance(row, dict):
        return False, "context_overlay:missing_media_row"
    family = _overlay_family(row, spec)
    accent, glow = palette_for(
        str(spec.get("target") or output_path.name)
        + "::"
        + str(row.get("overlay_hint") or "")
        + "::"
        + family
    )
    filter_chain = _overlay_filter_for(family=family, accent=accent, glow=glow, width=width, height=height)
    with tempfile.NamedTemporaryFile(prefix="ch6_overlay_", suffix=output_path.suffix, delete=False) as handle:
        temp_output = Path(handle.name)
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(output_path),
                "-vf",
                filter_chain,
                "-frames:v",
                "1",
                str(temp_output),
            ],
            check=True,
            text=True,
            capture_output=True,
        )
        temp_output.replace(output_path)
        return True, f"context_overlay:{family}"
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        return False, f"context_overlay_failed:{family}:{detail[:220]}"
    finally:
        try:
            temp_output.unlink(missing_ok=True)
        except Exception:
            pass


def render_with_ooda(*, prompt: str, output_path: Path, width: int, height: int, spec: dict[str, object]) -> dict[str, object]:
    attempts: list[str] = []
    requested_order = spec.get("providers")
    if isinstance(requested_order, list):
        requested = [str(entry).strip().lower() for entry in requested_order if str(entry).strip()]
        preferred = provider_order()
        providers = sorted(
            dict.fromkeys(requested),
            key=lambda value: preferred.index(value) if value in preferred else len(preferred),
        ) or preferred
    else:
        providers = provider_order()
    for provider in providers:
        normalized = provider.strip().lower()
        if normalized == "pollinations":
            safe_prompt = build_safe_pollinations_prompt(prompt=prompt, spec=spec)
            ok, detail = run_pollinations_provider(prompt=safe_prompt, output_path=output_path, width=width, height=height)
        elif normalized == "magixai":
            safe_prompt = sanitize_prompt_for_provider(prompt, provider=normalized)
            ok, detail = run_magixai_api_provider(prompt=safe_prompt, output_path=output_path, width=width, height=height)
            if not ok:
                command_ok, command_detail = run_command_provider("magixai", shlex_command("CHUMMER6_MAGIXAI_RENDER_COMMAND"), prompt=safe_prompt, output_path=output_path, width=width, height=height)
                if command_ok or detail.endswith(":not_configured"):
                    ok, detail = command_ok, command_detail
            if not ok:
                url_ok, url_detail = run_url_provider("magixai", url_template("CHUMMER6_MAGIXAI_RENDER_URL_TEMPLATE"), prompt=safe_prompt, output_path=output_path, width=width, height=height)
                if url_ok or detail.endswith(":not_configured"):
                    ok, detail = url_ok, url_detail
        elif normalized == "markupgo":
            ok, detail = False, "markupgo:disabled_for_primary_art"
        elif normalized == "prompting_systems":
            ok, detail = run_command_provider("prompting_systems", shlex_command("CHUMMER6_PROMPTING_SYSTEMS_RENDER_COMMAND"), prompt=prompt, output_path=output_path, width=width, height=height)
            if not ok:
                url_ok, url_detail = run_url_provider("prompting_systems", url_template("CHUMMER6_PROMPTING_SYSTEMS_RENDER_URL_TEMPLATE"), prompt=prompt, output_path=output_path, width=width, height=height)
                if url_ok or detail.endswith(":not_configured"):
                    ok, detail = url_ok, url_detail
        elif normalized == "browseract_magixai":
            if env_value("BROWSERACT_API_KEY"):
                ok, detail = run_command_provider("browseract_magixai", shlex_command("CHUMMER6_BROWSERACT_MAGIXAI_RENDER_COMMAND"), prompt=prompt, output_path=output_path, width=width, height=height)
                if not ok:
                    url_ok, url_detail = run_url_provider("browseract_magixai", url_template("CHUMMER6_BROWSERACT_MAGIXAI_RENDER_URL_TEMPLATE"), prompt=prompt, output_path=output_path, width=width, height=height)
                    if url_ok or detail.endswith(":not_configured"):
                        ok, detail = url_ok, url_detail
            else:
                ok, detail = False, "browseract_magixai:not_configured"
        elif normalized == "browseract_prompting_systems":
            if env_value("BROWSERACT_API_KEY"):
                ok, detail = run_command_provider("browseract_prompting_systems", shlex_command("CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_RENDER_COMMAND"), prompt=prompt, output_path=output_path, width=width, height=height)
                if not ok:
                    url_ok, url_detail = run_url_provider("browseract_prompting_systems", url_template("CHUMMER6_BROWSERACT_PROMPTING_SYSTEMS_RENDER_URL_TEMPLATE"), prompt=prompt, output_path=output_path, width=width, height=height)
                    if url_ok or detail.endswith(":not_configured"):
                        ok, detail = url_ok, url_detail
                if not ok:
                    command_ok, command_detail = run_command_provider("browseract_prompting_systems", shlex_command("CHUMMER6_PROMPTING_SYSTEMS_RENDER_COMMAND"), prompt=prompt, output_path=output_path, width=width, height=height)
                    if command_ok or detail.endswith(":not_configured"):
                        ok, detail = command_ok, command_detail
                if not ok:
                    url_ok, url_detail = run_url_provider("browseract_prompting_systems", url_template("CHUMMER6_PROMPTING_SYSTEMS_RENDER_URL_TEMPLATE"), prompt=prompt, output_path=output_path, width=width, height=height)
                    if url_ok or detail.endswith(":not_configured"):
                        ok, detail = url_ok, url_detail
            else:
                ok, detail = False, "browseract_prompting_systems:not_configured"
        elif normalized in {"onemin", "1min", "1min.ai", "oneminai"}:
            safe_prompt = build_safe_onemin_prompt(prompt=prompt, spec=spec)
            ok, detail = run_onemin_api_provider(prompt=safe_prompt, output_path=output_path, width=width, height=height)
            if not ok:
                command_ok, command_detail = run_command_provider("onemin", shlex_command("CHUMMER6_1MIN_RENDER_COMMAND"), prompt=safe_prompt, output_path=output_path, width=width, height=height)
                if command_ok or detail.endswith(":not_configured"):
                    ok, detail = command_ok, command_detail
            if not ok:
                url_ok, url_detail = run_url_provider("onemin", url_template("CHUMMER6_1MIN_RENDER_URL_TEMPLATE"), prompt=safe_prompt, output_path=output_path, width=width, height=height)
                if url_ok or detail.endswith(":not_configured"):
                    ok, detail = url_ok, url_detail
        elif normalized in {"scene_contract_renderer", "ooda_compositor"}:
            ok, detail = False, f"{normalized}:disabled"
        elif normalized == "local_raster":
            ok, detail = False, "local_raster:disabled"
        else:
            ok, detail = False, f"{normalized}:unknown_provider"
        attempts.append(detail)
        if ok:
            return {"provider": normalized, "status": detail, "attempts": attempts}
    raise RuntimeError("no image provider succeeded: " + " || ".join(attempts))


def asset_specs() -> list[dict[str, object]]:
    loaded = load_media_overrides()
    media = loaded.get("media") if isinstance(loaded, dict) else {}
    pages = loaded.get("pages") if isinstance(loaded, dict) else {}
    section_ooda = loaded.get("section_ooda") if isinstance(loaded, dict) else {}
    page_ooda = section_ooda.get("pages") if isinstance(section_ooda, dict) else {}
    hero_override = media.get("hero") if isinstance(media, dict) else {}
    if not isinstance(hero_override, dict) or not str(hero_override.get("visual_prompt", "")).strip():
        raise RuntimeError("missing hero visual_prompt in EA overrides")
    if not isinstance(pages, dict):
        raise RuntimeError("missing page overrides in EA output")
    if not isinstance(page_ooda, dict):
        raise RuntimeError("missing page section OODA in EA output")

    def render_prompt_from_row(row: dict[str, object], *, role: str) -> str:
        contract = row.get("scene_contract") if isinstance(row.get("scene_contract"), dict) else {}
        subject = str(contract.get("subject", "")).strip()
        environment = str(contract.get("environment", "")).strip()
        action = str(contract.get("action", "")).strip()
        metaphor = str(contract.get("metaphor", "")).strip()
        composition = str(contract.get("composition", "")).strip()
        palette = str(contract.get("palette", "")).strip()
        mood = str(contract.get("mood", "")).strip()
        humor = str(contract.get("humor", "")).strip()
        props = ", ".join(str(entry).strip() for entry in (contract.get("props") or []) if str(entry).strip())
        overlays = ", ".join(str(entry).strip() for entry in (contract.get("overlays") or []) if str(entry).strip())
        motifs = ", ".join(str(entry).strip() for entry in (row.get("visual_motifs") or []) if str(entry).strip())
        callouts = ", ".join(str(entry).strip() for entry in (row.get("overlay_callouts") or []) if str(entry).strip())
        visual_prompt = str(row.get("visual_prompt", "")).strip()
        prompt_parts = [
            f"Wide cinematic cyberpunk concept art for the Chummer6 {role}.",
            visual_prompt,
            f"One clear focal subject: {subject}." if subject else "",
            f"Set the scene in {environment}." if environment else "",
            f"Show this happening: {action}." if action else "",
            f"Make the core visual metaphor immediately legible: {metaphor}." if metaphor else "",
            f"Use a {composition} composition." if composition else "",
            f"Palette: {palette}." if palette else "",
            f"Mood: {mood}." if mood else "",
            f"Humor note: {humor}." if humor else "",
            f"Concrete visible props: {props}." if props else "",
            f"Useful diegetic overlays in-scene: {overlays}." if overlays else "",
            f"Reader-facing motifs to weave in visually: {motifs}." if motifs else "",
            f"Overlay ideas to imply, not print literally: {callouts}." if callouts else "",
            "Make it feel like a lived-in Shadowrun street, lab, archive, forge, or table scene, not a product poster.",
            "Avoid generic skylines, abstract icon soup, flat infographics, or brochure-cover posing.",
            "Do not print text, prompts, OODA labels, metadata, or resolution callouts on the image.",
            "No text, no logo, no watermark, 16:9.",
        ]
        return " ".join(part for part in prompt_parts if part)

    def page_media_row(page_id: str, *, role: str, composition_hint: str) -> dict[str, object]:
        page_row = pages.get(page_id)
        ooda_row = page_ooda.get(page_id)
        if not isinstance(page_row, dict):
            raise RuntimeError(f"missing page override for media asset: {page_id}")
        if not isinstance(ooda_row, dict):
            raise RuntimeError(f"missing section OODA for media asset: {page_id}")
        act = ooda_row.get("act") if isinstance(ooda_row.get("act"), dict) else {}
        observe = ooda_row.get("observe") if isinstance(ooda_row.get("observe"), dict) else {}
        orient = ooda_row.get("orient") if isinstance(ooda_row.get("orient"), dict) else {}
        decide = ooda_row.get("decide") if isinstance(ooda_row.get("decide"), dict) else {}
        visual_seed = str(act.get("visual_prompt_seed", "")).strip()
        intro = str(page_row.get("intro", "")).strip()
        body = str(page_row.get("body", "")).strip()
        focal = str(orient.get("focal_subject", "")).strip()
        scene_logic = str(orient.get("scene_logic", "")).strip()
        overlay = str(decide.get("overlay_priority", "")).strip()
        interests = observe.get("likely_interest") if isinstance(observe.get("likely_interest"), list) else []
        concrete = observe.get("concrete_signals") if isinstance(observe.get("concrete_signals"), list) else []
        if not visual_seed:
            raise RuntimeError(f"missing visual prompt seed for page media asset: {page_id}")
        return {
            "title": role,
            "subtitle": intro,
            "kicker": str(page_row.get("kicker", "")).strip(),
            "note": body,
            "overlay_hint": overlay or str(orient.get("visual_devices", "")).strip(),
            "visual_prompt": visual_seed,
            "visual_motifs": [str(entry).strip() for entry in interests if str(entry).strip()],
            "overlay_callouts": [str(entry).strip() for entry in concrete if str(entry).strip()],
            "scene_contract": {
                "subject": focal or "a cyberpunk protagonist",
                "environment": scene_logic or body,
                "action": str(act.get("paragraph_seed", "")).strip() or str(act.get("one_liner", "")).strip(),
                "metaphor": page_id.replace("_", " "),
                "props": [str(entry).strip() for entry in interests if str(entry).strip()][:5],
                "overlays": [str(entry).strip() for entry in concrete if str(entry).strip()][:4],
                "composition": composition_hint,
                "palette": str(orient.get("visual_devices", "")).strip(),
                "mood": str(orient.get("emotional_goal", "")).strip(),
                "humor": str(orient.get("tone_rule", "")).strip(),
            },
        }

    def page_visual_prompt(page_id: str, *, role: str, composition_hint: str) -> str:
        return render_prompt_from_row(
            page_media_row(page_id, role=role, composition_hint=composition_hint),
            role=role,
        )

    specs: list[dict[str, object]] = [
        {
            "target": "assets/hero/chummer6-hero.png",
            "prompt": render_prompt_from_row(hero_override, role="landing hero"),
            "width": 960,
            "height": 540,
            "media_row": hero_override,
            "providers": provider_order(),
        },
        {
            "target": "assets/hero/poc-warning.png",
            "prompt": page_visual_prompt("readme", role="POC warning shelf", composition_hint="desk_still_life"),
            "width": 960,
            "height": 540,
            "media_row": page_media_row("readme", role="POC warning shelf", composition_hint="desk_still_life"),
            "providers": provider_order(),
        },
        {
            "target": "assets/pages/start-here.png",
            "prompt": page_visual_prompt("start_here", role="start-here banner", composition_hint="city_edge"),
            "width": 960,
            "height": 540,
            "media_row": page_media_row("start_here", role="start-here banner", composition_hint="city_edge"),
            "providers": provider_order(),
        },
        {
            "target": "assets/pages/what-chummer6-is.png",
            "prompt": page_visual_prompt("what_chummer6_is", role="what-is banner", composition_hint="single_protagonist"),
            "width": 960,
            "height": 540,
            "media_row": page_media_row("what_chummer6_is", role="what-is banner", composition_hint="single_protagonist"),
            "providers": provider_order(),
        },
        {
            "target": "assets/pages/where-to-go-deeper.png",
            "prompt": page_visual_prompt("where_to_go_deeper", role="deeper-dive banner", composition_hint="archive_room"),
            "width": 960,
            "height": 540,
            "media_row": page_media_row("where_to_go_deeper", role="deeper-dive banner", composition_hint="archive_room"),
            "providers": provider_order(),
        },
        {
            "target": "assets/pages/current-phase.png",
            "prompt": page_visual_prompt("current_phase", role="current-phase banner", composition_hint="workshop"),
            "width": 960,
            "height": 540,
            "media_row": page_media_row("current_phase", role="current-phase banner", composition_hint="workshop"),
            "providers": provider_order(),
        },
        {
            "target": "assets/pages/current-status.png",
            "prompt": page_visual_prompt("current_status", role="current-status banner", composition_hint="street_front"),
            "width": 960,
            "height": 540,
            "media_row": page_media_row("current_status", role="current-status banner", composition_hint="street_front"),
            "providers": provider_order(),
        },
        {
            "target": "assets/pages/public-surfaces.png",
            "prompt": page_visual_prompt("public_surfaces", role="public-surfaces banner", composition_hint="street_front"),
            "width": 960,
            "height": 540,
            "media_row": page_media_row("public_surfaces", role="public-surfaces banner", composition_hint="street_front"),
            "providers": provider_order(),
        },
        {
            "target": "assets/pages/parts-index.png",
            "prompt": page_visual_prompt("parts_index", role="parts-overview banner", composition_hint="district_map"),
            "width": 960,
            "height": 540,
            "media_row": page_media_row("parts_index", role="parts-overview banner", composition_hint="district_map"),
            "providers": provider_order(),
        },
        {
            "target": "assets/pages/horizons-index.png",
            "prompt": page_visual_prompt("horizons_index", role="horizons boulevard banner", composition_hint="horizon_boulevard"),
            "width": 960,
            "height": 540,
            "media_row": page_media_row("horizons_index", role="horizons boulevard banner", composition_hint="horizon_boulevard"),
            "providers": provider_order(),
        },
    ]
    part_overrides = media.get("parts") if isinstance(media, dict) else {}
    for slug, item in GUIDE.PARTS.items():
        override = part_overrides.get(slug) if isinstance(part_overrides, dict) else None
        if not isinstance(override, dict) or not str(override.get("visual_prompt", "")).strip():
            raise RuntimeError(f"missing part visual_prompt in EA overrides: {slug}")
        specs.append(
            {
                "target": f"assets/parts/{slug}.png",
                "prompt": render_prompt_from_row(override, role=f"{slug} part page"),
                "width": 960,
                "height": 540,
                "media_row": override,
                "providers": provider_order(),
            }
        )
    horizon_overrides = media.get("horizons") if isinstance(media, dict) else {}
    for slug, item in GUIDE.HORIZONS.items():
        override = horizon_overrides.get(slug) if isinstance(horizon_overrides, dict) else None
        if not isinstance(override, dict) or not str(override.get("visual_prompt", "")).strip():
            raise RuntimeError(f"missing horizon visual_prompt in EA overrides: {slug}")
        specs.append(
            {
                "target": f"assets/horizons/{slug}.png",
                "prompt": render_prompt_from_row(override, role=f"{slug} horizon page"),
                "width": 960,
                "height": 540,
                "media_row": override,
                "providers": provider_order(),
            }
        )
    return specs


def render_pack(*, output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    specs = asset_specs()
    concurrency = max(1, min(4, int(env_value("CHUMMER6_MEDIA_RENDER_CONCURRENCY") or "1")))

    def _render_spec(spec: dict[str, object]) -> dict[str, object]:
        target = str(spec["target"])
        prompt = refine_prompt_with_ooda(prompt=str(spec["prompt"]), target=target)
        width = int(spec.get("width", 1280))
        height = int(spec.get("height", 720))
        out_path = output_dir / target
        out_path.parent.mkdir(parents=True, exist_ok=True)
        result = render_with_ooda(prompt=prompt, output_path=out_path, width=width, height=height, spec=spec)
        return {
            "target": target,
            "output": str(out_path),
            "provider": result["provider"],
            "status": result["status"],
            "attempts": result["attempts"],
        }

    # Fail fast on the first asset instead of chewing through the whole pack when no real lane works.
    first_result = _render_spec(specs[0])
    ordered_results: list[dict[str, object] | None] = [None] * len(specs)
    ordered_results[0] = first_result
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        future_map = {
            executor.submit(_render_spec, spec): index
            for index, spec in enumerate(specs[1:], start=1)
        }
        for future in concurrent.futures.as_completed(future_map):
            index = future_map[future]
            ordered_results[index] = future.result()
    assets = [result for result in ordered_results if isinstance(result, dict)]
    manifest = {
        "output_dir": str(output_dir),
        "assets": assets,
    }
    MANIFEST_OUT.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    STATE_OUT.write_text(
        json.dumps(
            {
                "output": str(output_dir),
                "provider": assets[0]["provider"] if assets else "none",
                "status": f"pack:rendered:{len(assets)}",
                "attempts": [asset["status"] for asset in assets],
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a Chummer6 guide asset through EA provider selection.")
    sub = parser.add_subparsers(dest="command", required=True)
    render = sub.add_parser("render")
    render.add_argument("--prompt", required=True)
    render.add_argument("--output", required=True)
    render.add_argument("--width", type=int, default=1280)
    render.add_argument("--height", type=int, default=720)
    render_pack_parser = sub.add_parser("render-pack")
    render_pack_parser.add_argument("--output-dir", default="/docker/fleet/state/chummer6/ea_media_assets")
    args = parser.parse_args()

    if args.command == "render-pack":
        manifest = render_pack(output_dir=Path(args.output_dir).expanduser())
        print(json.dumps({"output_dir": manifest["output_dir"], "assets": len(manifest["assets"]), "status": "rendered"}))
        return 0

    output_path = Path(args.output).expanduser()
    result = render_with_ooda(
        prompt=str(args.prompt),
        output_path=output_path,
        width=int(args.width),
        height=int(args.height),
        spec={"target": str(output_path.name), "media_row": {}},
    )
    STATE_OUT.parent.mkdir(parents=True, exist_ok=True)
    STATE_OUT.write_text(json.dumps({"output": str(output_path), **result}, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output_path), "provider": result["provider"], "status": result["status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
