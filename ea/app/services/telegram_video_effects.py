from __future__ import annotations

import json
import math
import os
import contextlib
import shutil
import socket
import subprocess
import tempfile
import ipaddress
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image
from PIL import ImageDraw
from PIL import ImageFilter


_SUPPORTED_FIRE_MARKERS = (
    "real flames",
    "real fire",
    "flames",
    "fire ring",
    "catch fire",
    "caught fire",
    "on fire",
    "make on fire",
    "make it on fire",
    "look like on fire",
    "clothes could catch fire",
    "clothes catch fire",
    "look like fire",
)
_SPEED_UP_MARKERS = ("faster", "speed up", "speed it up", "make it faster", "increase speed")
_SLOW_DOWN_MARKERS = ("slower", "slow down", "slow it down", "make it slower", "decrease speed")
_LOUDER_MARKERS = ("louder", "turn it up", "turn up the audio", "increase volume", "make it louder")
_MUTE_MARKERS = ("mute", "remove audio", "without audio", "silent", "no audio")
_DEFAULT_ALLOWED_VIDEO_HOSTS = ("api.telegram.org",)
_DEFAULT_MAX_VIDEO_BYTES = 80 * 1024 * 1024


def supported_source_video_edit_summary() -> str:
    return "realistic flame overlays, brief burn accents, speed changes, louder audio, and mute/remove-audio edits"


def parse_source_video_edit_plan(text: str) -> dict[str, object]:
    normalized = " ".join(str(text or "").strip().lower().split())
    plan: dict[str, object] = {}
    if not normalized:
        return plan
    if any(marker in normalized for marker in _SUPPORTED_FIRE_MARKERS):
        plan["fire_overlay"] = True
    if any(marker in normalized for marker in _SPEED_UP_MARKERS):
        plan["speed_factor"] = 1.25
    elif any(marker in normalized for marker in _SLOW_DOWN_MARKERS):
        plan["speed_factor"] = 0.82
    if any(marker in normalized for marker in _LOUDER_MARKERS):
        plan["audio_gain_db"] = 4.0
    if any(marker in normalized for marker in _MUTE_MARKERS):
        plan["mute_audio"] = True
    return plan


def source_video_edit_enabled() -> bool:
    raw = str(os.getenv("EA_TELEGRAM_SOURCE_VIDEO_EDIT_ENABLED") or "1").strip().lower()
    return raw not in {"", "0", "false", "no", "off"}


def source_video_edit_supported(text: str) -> bool:
    return bool(parse_source_video_edit_plan(text))


def _ffmpeg_bin() -> str:
    return shutil.which("ffmpeg") or "/usr/bin/ffmpeg"


def _ffprobe_bin() -> str:
    return shutil.which("ffprobe") or "/usr/bin/ffprobe"


def _probe_video(path: Path) -> dict[str, float]:
    completed = subprocess.run(
        [
            _ffprobe_bin(),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,duration",
            "-of",
            "json",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"source_video_probe_failed:{str(completed.stderr or completed.stdout or '').strip()[:200]}")
    payload = json.loads(str(completed.stdout or "{}"))
    streams = list(payload.get("streams") or [])
    if not streams:
        raise RuntimeError("source_video_stream_missing")
    stream = dict(streams[0] or {})
    width = max(int(float(stream.get("width") or 0)), 2)
    height = max(int(float(stream.get("height") or 0)), 2)
    duration = max(float(stream.get("duration") or 0.0), 1.0)
    return {"width": width, "height": height, "duration": duration}


def _allowed_video_hosts() -> tuple[str, ...]:
    raw = str(os.getenv("EA_TELEGRAM_VIDEO_DOWNLOAD_ALLOWED_HOSTS") or "").strip()
    values = [item.strip().lower() for item in raw.split(",") if item.strip()] if raw else list(_DEFAULT_ALLOWED_VIDEO_HOSTS)
    return tuple(dict.fromkeys(values))


def _max_video_download_bytes() -> int:
    try:
        configured = int(str(os.getenv("EA_TELEGRAM_VIDEO_DOWNLOAD_MAX_BYTES") or "").strip() or "0")
    except ValueError:
        configured = 0
    return max(1024 * 1024, configured or _DEFAULT_MAX_VIDEO_BYTES)


def _host_allowed(hostname: str) -> bool:
    host = str(hostname or "").strip().lower().rstrip(".")
    if not host:
        return False
    for allowed in _allowed_video_hosts():
        normalized = allowed.strip().lower().rstrip(".")
        if not normalized:
            continue
        if normalized.startswith(".") and host.endswith(normalized):
            return True
        if host == normalized:
            return True
    return False


def _host_resolves_publicly(hostname: str) -> bool:
    try:
        infos = socket.getaddrinfo(hostname, None)
    except Exception:
        return False
    if not infos:
        return False
    for info in infos:
        address = str(info[4][0])
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return False
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            return False
    return True


def _validate_video_source_url(url: str) -> str:
    normalized = str(url or "").strip()
    if not normalized:
        raise RuntimeError("source_video_url_missing")
    parsed = urllib.parse.urlparse(normalized)
    if parsed.scheme.lower() != "https":
        raise RuntimeError("source_video_url_scheme_forbidden")
    hostname = str(parsed.hostname or "").strip()
    if not _host_allowed(hostname):
        raise RuntimeError("source_video_url_host_forbidden")
    if not _host_resolves_publicly(hostname):
        raise RuntimeError("source_video_url_host_not_public")
    return urllib.parse.urlunparse(parsed)


class _SafeVideoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        _validate_video_source_url(str(newurl or ""))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _content_type_allowed(value: str) -> bool:
    content_type = str(value or "").split(";", 1)[0].strip().lower()
    return content_type.startswith("video/") or content_type in {"application/octet-stream", "binary/octet-stream"}


def _video_magic_allowed(path: Path) -> bool:
    try:
        header = path.read_bytes()[:64]
    except OSError:
        return False
    if len(header) < 12:
        return False
    return header[4:8] == b"ftyp" or header.startswith(b"\x1aE\xdf\xa3")


def _download_video(url: str, target: Path) -> Path:
    normalized_url = _validate_video_source_url(url)
    request = urllib.request.Request(normalized_url, headers={"User-Agent": "EA-Telegram-Video-Effects/1.0"})
    opener = urllib.request.build_opener(_SafeVideoRedirectHandler)
    max_bytes = _max_video_download_bytes()
    target.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with opener.open(request, timeout=180) as response:
        if not _content_type_allowed(str(response.headers.get("Content-Type") or "")):
            raise RuntimeError("source_video_content_type_forbidden")
        with target.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    with contextlib.suppress(OSError):
                        target.unlink()
                    raise RuntimeError("source_video_download_too_large")
                handle.write(chunk)
    if total <= 0:
        raise RuntimeError("source_video_download_empty")
    if not _video_magic_allowed(target):
        with contextlib.suppress(OSError):
            target.unlink()
        raise RuntimeError("source_video_magic_forbidden")
    return target


def _storage_root() -> Path:
    return Path(
        str(os.getenv("EA_TELEGRAM_SOURCE_VIDEO_EDIT_ROOT") or "/mnt/pcloud/EA/telegram_video_edits").strip()
    ).expanduser()


def _work_root() -> Path:
    return Path(
        str(os.getenv("EA_TELEGRAM_SOURCE_VIDEO_EDIT_WORK_ROOT") or "/tmp/ea-telegram-video-work").strip()
    ).expanduser()


def _flame_palette(frame_index: int, step: int) -> tuple[tuple[int, int, int, int], ...]:
    pulse = 0.5 + 0.5 * math.sin(frame_index * 0.33 + step * 0.21)
    outer = (255, int(96 + 80 * pulse), 24, int(78 + 38 * pulse))
    mid = (255, int(160 + 50 * pulse), 34, int(128 + 60 * pulse))
    core = (255, int(220 + 20 * pulse), int(140 + 40 * pulse), int(175 + 50 * pulse))
    return outer, mid, core


def _draw_flame_ring_frame(
    *,
    width: int,
    height: int,
    frame_index: int,
    frame_count: int,
    clothes_burn_window: tuple[int, int],
    target: Path,
) -> None:
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image, "RGBA")
    cx = width * 0.5
    cy = height * 0.5
    radius = min(width, height) * 0.17
    ring_band = max(int(radius * 0.12), 10)
    for step, angle_deg in enumerate(range(0, 360, 12)):
        angle = math.radians(angle_deg)
        jitter = math.sin(frame_index * 0.5 + step * 0.9) * radius * 0.03
        flame_height = radius * (0.15 + 0.10 * (0.5 + 0.5 * math.sin(frame_index * 0.31 + step * 1.17)))
        inner_r = radius - ring_band * 0.55 + jitter
        outer_r = radius + flame_height + jitter
        px = cx + math.cos(angle) * inner_r
        py = cy + math.sin(angle) * inner_r
        nx = cx + math.cos(angle + 0.08) * outer_r
        ny = cy + math.sin(angle + 0.08) * outer_r
        bx = cx + math.cos(angle - 0.08) * outer_r
        by = cy + math.sin(angle - 0.08) * outer_r
        outer, mid, core = _flame_palette(frame_index, step)
        draw.polygon([(px, py), (nx, ny), (bx, by)], fill=outer)
        draw.ellipse(
            (
                px - ring_band * 0.75,
                py - ring_band * 0.75,
                px + ring_band * 0.75,
                py + ring_band * 0.75,
            ),
            fill=mid,
        )
        draw.ellipse(
            (
                px - ring_band * 0.42,
                py - ring_band * 0.42,
                px + ring_band * 0.42,
                py + ring_band * 0.42,
            ),
            fill=core,
        )
    draw.ellipse(
        (
            cx - radius,
            cy - radius,
            cx + radius,
            cy + radius,
        ),
        outline=(255, 190, 70, 128),
        width=max(ring_band // 3, 5),
    )
    if clothes_burn_window[0] <= frame_index <= clothes_burn_window[1]:
        phase = 0.5 + 0.5 * math.sin((frame_index - clothes_burn_window[0]) * 0.8)
        patch_x = int(cx + radius * 0.16)
        patch_y = int(cy + radius * 0.48)
        patch_w = max(int(width * 0.05), 26)
        patch_h = max(int(height * 0.08), 48)
        for idx in range(6):
            outer, mid, core = _flame_palette(frame_index + idx, idx)
            offset = (idx - 2) * patch_w * 0.08
            top = patch_y - patch_h * (0.2 + 0.5 * phase)
            draw.polygon(
                [
                    (patch_x + offset, patch_y),
                    (patch_x + offset + patch_w * 0.32, top),
                    (patch_x + offset + patch_w * 0.64, patch_y - patch_h * 0.12),
                    (patch_x + offset + patch_w * 0.84, patch_y),
                ],
                fill=outer,
            )
            draw.ellipse(
                (
                    patch_x + offset - patch_w * 0.25,
                    patch_y - patch_h * 0.14,
                    patch_x + offset + patch_w * 0.55,
                    patch_y + patch_h * 0.22,
                ),
                fill=mid,
            )
            draw.ellipse(
                (
                    patch_x + offset + patch_w * 0.05,
                    patch_y - patch_h * 0.28,
                    patch_x + offset + patch_w * 0.35,
                    patch_y + patch_h * 0.02,
                ),
                fill=core,
            )
    image = image.filter(ImageFilter.GaussianBlur(radius=max(min(width, height) / 240.0, 1.5)))
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target)


def _render_overlay_frames(*, width: int, height: int, duration_seconds: float, frames_dir: Path) -> tuple[int, float]:
    fps = 10
    effect_duration = max(4.0, min(duration_seconds, 18.0))
    frame_count = max(int(math.ceil(effect_duration * fps)), fps * 4)
    clothes_start = int(frame_count * 0.42)
    clothes_end = min(frame_count - 1, clothes_start + max(int(fps * 0.9), 5))
    for frame_index in range(frame_count):
        _draw_flame_ring_frame(
            width=width,
            height=height,
            frame_index=frame_index,
            frame_count=frame_count,
            clothes_burn_window=(clothes_start, clothes_end),
            target=frames_dir / f"frame-{frame_index:04d}.png",
        )
    return fps, effect_duration


def _atempo_chain(speed_factor: float) -> str:
    factor = max(min(float(speed_factor or 1.0), 2.0), 0.5)
    stages: list[float] = []
    while factor > 2.0:
        stages.append(2.0)
        factor /= 2.0
    while factor < 0.5:
        stages.append(0.5)
        factor /= 0.5
    stages.append(factor)
    return ",".join(f"atempo={stage:.5f}" for stage in stages)


def _compose_edited_video(
    *,
    source_path: Path,
    overlay_frames_dir: Path | None,
    overlay_fps: int,
    output_path: Path,
    plan: dict[str, object],
) -> None:
    speed_factor = float(plan.get("speed_factor") or 1.0)
    mute_audio = bool(plan.get("mute_audio"))
    audio_gain_db = float(plan.get("audio_gain_db") or 0.0)
    audio_filters: list[str] = []
    if abs(speed_factor - 1.0) > 0.001:
        audio_filters.append(_atempo_chain(speed_factor))
    if audio_gain_db:
        audio_filters.append(f"volume={audio_gain_db}dB")
    audio_filter = ",".join(filter(None, audio_filters))
    input_args = ["-i", str(source_path)]
    filter_parts: list[str] = []
    video_input_label = "[0:v]"
    if overlay_frames_dir is not None:
        input_args.extend(["-framerate", str(overlay_fps), "-i", str(overlay_frames_dir / "frame-%04d.png")])
        filter_parts.append("[1:v]format=rgba,colorchannelmixer=aa=0.88[fx]")
        filter_parts.append(f"{video_input_label}[fx]overlay=0:0:eof_action=pass[v0]")
        video_input_label = "[v0]"
    video_filters = []
    if abs(speed_factor - 1.0) > 0.001:
        video_filters.append(f"setpts={1.0 / speed_factor:.6f}*PTS")
    video_filters.append("eq=saturation=1.08:contrast=1.03:brightness=0.02")
    video_filters.append("format=yuv420p")
    filter_parts.append(f"{video_input_label}{','.join(video_filters)}[v]")
    command = [_ffmpeg_bin(), "-y", *input_args]
    if not mute_audio and audio_filter:
        filter_parts.append(f"[0:a]{audio_filter}[a]")
    if filter_parts:
        command.extend(["-filter_complex", ";".join(filter_parts)])
    command = [
        *command,
        "-map",
        "[v]",
    ]
    if mute_audio:
        command.append("-an")
    elif audio_filter:
        command.extend(["-map", "[a]", "-c:a", "aac", "-b:a", "192k"])
    else:
        command.extend(["-map", "0:a?", "-c:a", "copy"])
    command.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            str(output_path),
        ]
    )
    completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=600)
    if completed.returncode != 0 or not output_path.exists():
        detail = str(completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"source_video_edit_ffmpeg_failed:{detail[:240]}")


def extract_source_video_reference_packet(*, video_url: str) -> dict[str, object]:
    normalized_url = str(video_url or "").strip()
    if not normalized_url:
        raise RuntimeError("source_video_url_missing")
    storage_root = _storage_root()
    work_root = _work_root()
    storage_root.mkdir(parents=True, exist_ok=True)
    work_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="telegram-source-ref-", dir=str(work_root)) as temp_dir_raw:
        temp_dir = Path(temp_dir_raw)
        source_path = temp_dir / "source.mp4"
        frames_dir = temp_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        _download_video(normalized_url, source_path)
        probe = _probe_video(source_path)
        width = int(probe["width"])
        height = int(probe["height"])
        duration = float(probe["duration"])
        timestamps = [max(duration * ratio, 0.0) for ratio in (0.12, 0.34, 0.58, 0.82)]
        frame_paths: list[Path] = []
        for index, second in enumerate(timestamps, start=1):
            frame_path = frames_dir / f"frame-{index:02d}.jpg"
            completed = subprocess.run(
                [
                    _ffmpeg_bin(),
                    "-y",
                    "-ss",
                    f"{second:.3f}",
                    "-i",
                    str(source_path),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    str(frame_path),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if completed.returncode == 0 and frame_path.exists() and frame_path.stat().st_size > 0:
                frame_paths.append(frame_path)
        if not frame_paths:
            raise RuntimeError("source_video_reference_frames_missing")
        thumbs = [Image.open(path).convert("RGB") for path in frame_paths]
        thumb_width = 360
        thumb_height = max(int(thumb_width * (height / max(width, 1))), 180)
        margin = 16
        label_height = 38
        board = Image.new(
            "RGB",
            (margin + len(thumbs) * (thumb_width + margin), thumb_height + label_height + margin * 2),
            (18, 18, 22),
        )
        draw = ImageDraw.Draw(board)
        for index, image in enumerate(thumbs, start=1):
            resized = image.resize((thumb_width, thumb_height))
            x = margin + (index - 1) * (thumb_width + margin)
            y = margin
            board.paste(resized, (x, y))
            draw.text((x + 8, y + thumb_height + 8), f"T{index}", fill=(235, 235, 240))
        final_root = storage_root / f"reference-{temp_dir.name}"
        final_root.mkdir(parents=True, exist_ok=True)
        board_path = final_root / "reference-board.jpg"
        board.save(board_path, quality=92)
        persisted_frames: list[str] = []
        for index, path in enumerate(frame_paths, start=1):
            target = final_root / f"frame-{index:02d}.jpg"
            shutil.copy2(path, target)
            persisted_frames.append(str(target))
        return {
            "source_video_duration_seconds": duration,
            "source_video_width": width,
            "source_video_height": height,
            "reference_frame_paths": persisted_frames,
            "reference_board_path": str(board_path),
            "reference_summary": (
                f"Reference frames extracted from the uploaded source video at 4 points across {duration:.1f}s "
                f"({width}x{height})."
            ),
        }


def render_local_source_video_edit(*, video_url: str, instruction_text: str) -> dict[str, object]:
    if not source_video_edit_enabled():
        raise RuntimeError("source_video_edit_disabled")
    plan = parse_source_video_edit_plan(instruction_text)
    if not plan:
        raise RuntimeError("source_video_edit_unsupported")
    normalized_url = str(video_url or "").strip()
    if not normalized_url:
        raise RuntimeError("source_video_url_missing")
    storage_root = _storage_root()
    work_root = _work_root()
    storage_root.mkdir(parents=True, exist_ok=True)
    work_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="telegram-source-video-", dir=str(work_root)) as temp_dir_raw:
        temp_dir = Path(temp_dir_raw)
        source_path = temp_dir / "source.mp4"
        overlay_dir = temp_dir / "overlay"
        output_path = temp_dir / "edited.mp4"
        _download_video(normalized_url, source_path)
        probe = _probe_video(source_path)
        fps = 10
        effect_duration = 0.0
        overlay_frames_dir: Path | None = None
        if bool(plan.get("fire_overlay")):
            fps, effect_duration = _render_overlay_frames(
                width=int(probe["width"]),
                height=int(probe["height"]),
                duration_seconds=float(probe["duration"]),
                frames_dir=overlay_dir,
            )
            overlay_frames_dir = overlay_dir
        _compose_edited_video(
            source_path=source_path,
            overlay_frames_dir=overlay_frames_dir,
            overlay_fps=fps,
            output_path=output_path,
            plan=plan,
        )
        final_output = storage_root / f"{temp_dir.name}-edited.mp4"
        shutil.copy2(output_path, final_output)
    return {
        "status": "rendered",
        "provider": "local_source_video_fx",
        "video_file_path": str(final_output),
        "instruction_text": str(instruction_text or "").strip(),
        "effect_duration_seconds": effect_duration,
        "operations": sorted(str(key) for key, value in plan.items() if value not in {False, None, "", 0}),
    }
