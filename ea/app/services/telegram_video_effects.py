from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import tempfile
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
    "clothes could catch fire",
    "clothes catch fire",
    "look like fire",
)


def source_video_edit_enabled() -> bool:
    raw = str(os.getenv("EA_TELEGRAM_SOURCE_VIDEO_EDIT_ENABLED") or "1").strip().lower()
    return raw not in {"", "0", "false", "no", "off"}


def source_video_edit_supported(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().lower().split())
    if not normalized:
        return False
    return any(marker in normalized for marker in _SUPPORTED_FIRE_MARKERS)


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


def _download_video(url: str, target: Path) -> Path:
    request = urllib.request.Request(str(url), headers={"User-Agent": "EA-Telegram-Video-Effects/1.0"})
    with urllib.request.urlopen(request, timeout=180) as response:
        target.write_bytes(response.read())
    return target


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


def _compose_edited_video(*, source_path: Path, overlay_frames_dir: Path, overlay_fps: int, output_path: Path) -> None:
    command = [
        _ffmpeg_bin(),
        "-y",
        "-i",
        str(source_path),
        "-framerate",
        str(overlay_fps),
        "-i",
        str(overlay_frames_dir / "frame-%04d.png"),
        "-filter_complex",
        "[1:v]format=rgba,colorchannelmixer=aa=0.88[fx];"
        "[0:v][fx]overlay=0:0:eof_action=pass,eq=saturation=1.08:contrast=1.03:brightness=0.02,format=yuv420p[v]",
        "-map",
        "[v]",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-c:a",
        "copy",
        str(output_path),
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=600)
    if completed.returncode != 0 or not output_path.exists():
        detail = str(completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"source_video_edit_ffmpeg_failed:{detail[:240]}")


def render_local_source_video_edit(*, video_url: str, instruction_text: str) -> dict[str, object]:
    if not source_video_edit_enabled():
        raise RuntimeError("source_video_edit_disabled")
    if not source_video_edit_supported(instruction_text):
        raise RuntimeError("source_video_edit_unsupported")
    normalized_url = str(video_url or "").strip()
    if not normalized_url:
        raise RuntimeError("source_video_url_missing")
    storage_root = Path(
        str(os.getenv("EA_TELEGRAM_SOURCE_VIDEO_EDIT_ROOT") or "/mnt/pcloud/EA/telegram_video_edits").strip()
    ).expanduser()
    work_root = Path(
        str(os.getenv("EA_TELEGRAM_SOURCE_VIDEO_EDIT_WORK_ROOT") or "/tmp/ea-telegram-video-work").strip()
    ).expanduser()
    storage_root.mkdir(parents=True, exist_ok=True)
    work_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="telegram-source-video-", dir=str(work_root)) as temp_dir_raw:
        temp_dir = Path(temp_dir_raw)
        source_path = temp_dir / "source.mp4"
        overlay_dir = temp_dir / "overlay"
        output_path = temp_dir / "edited.mp4"
        _download_video(normalized_url, source_path)
        probe = _probe_video(source_path)
        fps, effect_duration = _render_overlay_frames(
            width=int(probe["width"]),
            height=int(probe["height"]),
            duration_seconds=float(probe["duration"]),
            frames_dir=overlay_dir,
        )
        _compose_edited_video(
            source_path=source_path,
            overlay_frames_dir=overlay_dir,
            overlay_fps=fps,
            output_path=output_path,
        )
        final_output = storage_root / f"{temp_dir.name}-edited.mp4"
        shutil.copy2(output_path, final_output)
    return {
        "status": "rendered",
        "provider": "local_source_video_fx",
        "video_file_path": str(final_output),
        "instruction_text": str(instruction_text or "").strip(),
        "effect_duration_seconds": effect_duration,
    }
