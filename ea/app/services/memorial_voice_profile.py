from __future__ import annotations

import json
import math
import os
import shutil
import struct
import subprocess
import textwrap
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hashlib import sha256


VOICE_PROFILE_MANIFEST_FILENAME = "voice_profile_manifest.json"
_DEFAULT_MANIFEST_ROOT = Path("/mnt/pcloud/EA/private_memorial_profiles")


def memorial_private_profile_root() -> Path:
    return Path(str(os.getenv("EA_PRIVATE_MEMORIAL_PROFILE_DIR") or str(_DEFAULT_MANIFEST_ROOT))).expanduser()


def _safe_slug(slug: str) -> str:
    safe = str(slug or "").strip().replace("/", "_").replace("..", "_")
    if not safe:
        raise ValueError("memorial_slug_missing")
    return safe


def memorial_voice_profile_dir(*, slug: str) -> Path:
    root = memorial_private_profile_root()
    candidate = (root / _safe_slug(slug)).resolve()
    if not candidate.is_dir() and candidate.exists():
        raise RuntimeError("memorial_profile_path_invalid")
    return candidate


def memorial_voice_profile_manifest_path(*, slug: str) -> Path:
    return memorial_voice_profile_dir(slug=slug) / VOICE_PROFILE_MANIFEST_FILENAME


def _manifest_payload_redacted(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(payload)
    audio_items = list(sanitized.get("audio_assets") or [])
    redacted: list[dict[str, Any]] = []
    for item in audio_items:
        if not isinstance(item, dict):
            continue
        redacted.append(
            {
                k: v
                for k, v in item.items()
                if k
                in {
                    "kind",
                    "source_label",
                    "asset_relpath",
                    "download_source",
                    "filename",
                    "duration_seconds",
                    "size_bytes",
                    "sha256",
                    "audio_features",
                    "analysis_status",
                    "error",
                }
            }
        )
    if redacted:
        sanitized["audio_assets"] = redacted
    return sanitized


def load_memorial_voice_profile(*, slug: str) -> dict[str, Any]:
    manifest_path = memorial_voice_profile_manifest_path(slug=slug)
    if not manifest_path.is_file():
        return {}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return _manifest_payload_redacted(payload)


def _normalize_audio_limit(value: object, *, fallback: int = 5, minimum: int = 1, maximum: int = 20) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, parsed))


def _normalize_url_list(value: object, *, max_items: int = 20) -> list[str]:
    result: list[str] = []
    for item in list(value or ()) if isinstance(value, list) else [value]:
        if len(result) >= max_items:
            break
        url = str(item or "").strip()
        if not url:
            continue
        if not url.lower().startswith(("http://", "https://")):
            continue
        result.append(url)
    return result


def _ffmpeg_bin() -> str:
    configured = str(os.environ.get("EA_FFMPEG_BIN") or "").strip()
    if configured:
        return configured
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise RuntimeError("ffmpeg_unavailable")


def _run_command(*, cmd: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)
    return proc.returncode, proc.stdout, proc.stderr


def _trimmed_error(payload: object) -> str:
    return textwrap.shorten(str(payload).replace("\n", " ").strip(), width=200, placeholder="…")


def _compute_audio_signature(*, source_path: Path) -> dict[str, Any]:
    temp_wav = source_path.with_suffix(f"{source_path.suffix}.signature.{uuid.uuid4().hex}.wav")
    ffmpeg_bin = _ffmpeg_bin()
    command = [
        ffmpeg_bin,
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        str(source_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-sample_fmt",
        "s16",
        "-acodec",
        "pcm_s16le",
        str(temp_wav),
    ]
    try:
        return_code, _, stderr = _run_command(cmd=command)
        if return_code != 0 or not temp_wav.is_file():
            raise RuntimeError(f"audio_convert_failed:{(stderr or '').strip()[:120]}")
        size_bytes = source_path.stat().st_size
        with temp_wav.open("rb") as _:
            pass
        return _compute_signature_from_wav(temp_wav=temp_wav, size_bytes=size_bytes)
    finally:
        temp_wav.unlink(missing_ok=True)


def _compute_signature_from_wav(*, temp_wav: Path, size_bytes: int) -> dict[str, Any]:
    import wave

    duration_seconds = 0.0
    sample_rate = 0
    frame_count = 0
    sample_sum_abs = 0.0
    sq_sum = 0.0
    zcr_count = 0
    max_abs = 0.0
    silence_count = 0

    with wave.open(str(temp_wav), "rb") as wav_file:
        sample_rate = int(wav_file.getframerate())
        frame_count = int(wav_file.getnframes())
        if sample_rate <= 0:
            raise RuntimeError("audio_invalid_sample_rate")
        duration_seconds = frame_count / float(sample_rate)
        sample_width = int(wav_file.getsampwidth())
        if sample_width != 2:
            raise RuntimeError("audio_unsupported_sample_width")
        fmt = "<h"
        prev_sign = 0
        silence_threshold = 0.015
        while True:
            raw = wav_file.readframes(4096)
            if not raw:
                break
            for raw_sample in struct.iter_unpack(fmt, raw):
                value = raw_sample[0] / 32768.0
                abs_value = abs(value)
                sample_sum_abs += abs_value
                sq_sum += abs_value * abs_value
                if abs_value > max_abs:
                    max_abs = abs_value
                if abs_value <= silence_threshold:
                    silence_count += 1
                sign = 0 if abs(value) < 1e-9 else (1 if value > 0 else -1)
                if prev_sign != 0 and sign != 0 and sign != prev_sign:
                    zcr_count += 1
                if sign != 0:
                    prev_sign = sign
    if frame_count <= 0:
        raise RuntimeError("audio_empty")
    rms = math.sqrt(sq_sum / frame_count)
    mean_abs = sample_sum_abs / frame_count
    zcr = zcr_count / frame_count
    silence_ratio = silence_count / frame_count
    speech_ratio = 1.0 - silence_ratio
    return {
        "duration_seconds": round(duration_seconds, 3),
        "sample_rate": sample_rate,
        "channels": 1,
        "frame_count": frame_count,
        "size_bytes": size_bytes,
        "audio_features": {
            "rms": round(rms, 5),
            "mean_abs": round(mean_abs, 5),
            "peak": round(max_abs, 5),
            "zero_crossing_ratio": round(zcr, 5),
            "speech_ratio": round(speech_ratio, 5),
            "silence_ratio": round(silence_ratio, 5),
        },
    }


def _yt_dlp_bin() -> str:
    configured = str(os.getenv("YTDLP_BIN") or "").strip()
    if configured:
        return configured
    found = shutil.which("yt-dlp")
    if not found:
        raise RuntimeError("yt_dlp_unavailable")
    return found


def _search_youtube_urls(*, query: str, max_results: int) -> list[str]:
    query_text = query.strip()
    if not query_text:
        return []
    command = [
        _yt_dlp_bin(),
        "-j",
        "--flat-playlist",
        "--no-warnings",
        "--no-check-certificate",
        f"ytsearch{max_results}:{query_text}",
    ]
    return_code, stdout, stderr = _run_command(cmd=command)
    if return_code != 0:
        message = (stderr or stdout or "yt_dlp_search_failed").strip()
        if not message:
            message = "yt_dlp_search_failed"
        raise RuntimeError(f"youtube_search_failed:{message[:180]}")
    urls: list[str] = []
    for raw in stdout.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        url = str(payload.get("url") or payload.get("webpage_url") or "").strip()
        if url.startswith("http"):
            urls.append(url)
    return urls[:max_results]


def _download_youtube_audio(*, urls: list[str], output_dir: Path) -> tuple[list[Path], list[str]]:
    if not urls:
        return [], []
    output_dir.mkdir(parents=True, exist_ok=True)
    downloads: list[Path] = []
    failures: list[str] = []
    yt_bin = _yt_dlp_bin()
    for url in urls:
        normalized_url = str(url or "").strip()
        if not normalized_url:
            failures.append("")
            continue
        existing_hint = None
        if "youtube.com/watch" in normalized_url:
            video_id = normalized_url.rsplit("v=", 1)[-1]
            if "&" in video_id:
                video_id = video_id.split("&", 1)[0]
            if video_id:
                existing_hint = output_dir / f"{video_id}.mp3"
        if existing_hint and existing_hint.exists() and existing_hint.stat().st_size > 0:
            downloads.append(existing_hint)
            continue
        command = [
            yt_bin,
            "--extract-audio",
            "--audio-format",
            "mp3",
            "--audio-quality",
            "0",
            "--no-playlist",
            "--no-check-certificate",
            "--no-overwrites",
            "-o",
            str(output_dir / "%(id)s.%(ext)s"),
            normalized_url,
        ]
        before = {candidate for candidate in output_dir.glob("*")}
        return_code, _, stderr = _run_command(cmd=command)
        if return_code != 0:
            failures.append(normalized_url)
            continue
        after = sorted(set(output_dir.glob("*")) - before, key=lambda path: path.name)
        if after:
            downloads.extend(after)
        elif existing_hint and existing_hint.exists() and existing_hint.stat().st_size > 0:
            downloads.append(existing_hint)
        else:
            failures.append(normalized_url)
    return downloads, failures


def _read_profile_asset_bytes(*, path: Path) -> bytes:
    return path.read_bytes()


def _sha256_for_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def build_memorial_voice_profile(
    *,
    slug: str,
    public_audio_paths: list[Path],
    youtube_query: str = "",
    youtube_urls: list[str] | None = None,
    youtube_limit: int = 5,
) -> dict[str, Any]:
    profile_dir = memorial_voice_profile_dir(slug=slug)
    profile_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir = profile_dir / "voice_profile"
    manifest_dir.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []

    candidates: list[tuple[str, Path, str, str]] = []
    normalized_youtube_urls = _normalize_url_list(youtube_urls or [], max_items=youtube_limit)

    for source_path in public_audio_paths:
        if not source_path.is_file():
            continue
        candidates.append(("public_clip", source_path, source_path.name, str(source_path)))

    downloaded_youtube: list[Path] = []
    failed_youtube_urls: list[str] = []
    normalized_query = str(youtube_query or "").strip()
    if normalized_query:
        try:
            search_results = _search_youtube_urls(query=normalized_query, max_results=max(youtube_limit, 1))
            normalized_youtube_urls.extend(search_results)
        except Exception as exc:
            warnings.append(f"youtube_search_failed:{_trimmed_error(exc)}")
    if normalized_youtube_urls:
        try:
            downloaded_youtube, failed_youtube_urls = _download_youtube_audio(
                urls=normalized_youtube_urls[:youtube_limit],
                output_dir=manifest_dir,
            )
        except Exception as exc:
            warnings.append(f"youtube_download_failed:{_trimmed_error(exc)}")
            downloaded_youtube = []
            failed_youtube_urls = list(dict.fromkeys(normalized_youtube_urls[:youtube_limit]))
        for path in downloaded_youtube:
            candidates.append(("youtube", path, path.name, str(path))
            )
        for failed_url in failed_youtube_urls:
            normalized_failed_url = str(failed_url or "").strip() or "youtube-url"
            failed_marker = manifest_dir / f"failed_{len(candidates)}.txt"
            failed_marker.write_text(normalized_failed_url + "\n", encoding="utf-8")
            candidates.append(("youtube_failed", failed_marker, failed_marker.name, normalized_failed_url))

    if not candidates:
        raise RuntimeError("voice_profile_no_audio")

    asset_items: list[dict[str, Any]] = []
    for source_kind, path, display_name, source_ref in candidates:
        item: dict[str, Any] = {
            "kind": source_kind,
            "filename": display_name,
            "source_label": source_ref,
        }
        try:
            asset_bytes = _read_profile_asset_bytes(path=path)
            item["sha256"] = _sha256_for_bytes(asset_bytes)
            item["size_bytes"] = len(asset_bytes)
            signature = _compute_audio_signature(source_path=path)
            item.update(signature)
            item["analysis_status"] = "ok"
        except Exception as exc:
            item["analysis_status"] = "failed"
            item["analysis_error"] = str(exc)
        item["asset_relpath"] = str(path.relative_to(profile_dir)) if path.is_relative_to(profile_dir) else path.name
        asset_items.append(item)

    if not asset_items:
        raise RuntimeError("voice_profile_no_audio")
    processed_count = len([item for item in asset_items if item.get("analysis_status") == "ok"])
    voice_cloning_supported = processed_count > 0

    manifest = {
        "manifest_version": "1",
        "slug": _safe_slug(slug),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "policy": {
            "voice_cloning_supported": bool(voice_cloning_supported),
            "voice_cloning_policy": "explicit_audio_sources_for_cloning",
            "notes": "Profile is built from explicit public audio and optional YouTube sources for potential speaker-clone workflows.",
        },
        "source": {
            "youtube_query": normalized_query,
            "youtube_urls": normalized_youtube_urls[:youtube_limit],
            "youtube_download_count": len(downloaded_youtube),
            "public_clip_count": len(public_audio_paths),
            "warnings": warnings,
        },
        "audio_assets": asset_items,
        "source_counts": {
            "public_clips": len(public_audio_paths),
            "youtube_urls": len(normalized_youtube_urls),
            "youtube_downloads": len(downloaded_youtube),
            "processed": processed_count,
            "failed": len([item for item in asset_items if item.get("analysis_status") != "ok"]),
        },
    }

    manifest_path = memorial_voice_profile_manifest_path(slug=slug)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return _manifest_payload_redacted(manifest)
