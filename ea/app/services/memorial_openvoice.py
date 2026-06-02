from __future__ import annotations

import os
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

import requests
from fastapi import HTTPException


OPENVOICE_TTS_PLUGIN_ID = "openvoice_local"
OPENVOICE_TTS_PLUGIN_LABEL = "OpenVoice Local Clone"
_OPENVOICE_BASE_URL_ENV = "OPENVOICE_BASE_URL"
_OPENVOICE_TIMEOUT_ENV = "OPENVOICE_TIMEOUT_SECONDS"
_OPENVOICE_MEMORIAL_VOICE_ID_ENV = "OPENVOICE_MEMORIAL_VOICE_ID"
_OPENVOICE_DEFAULT_TIMEOUT_SECONDS = 180
_OPENVOICE_DEFAULT_BASE_URL = "http://127.0.0.1:8093"
_OPENVOICE_CLONE_CLIP_SECONDS = 180
_OPENVOICE_CLONE_SAMPLE_RATE = 16000
_OPENVOICE_MAX_CURATED_CLIPS = 3


def openvoice_base_url() -> str:
    return str(os.environ.get(_OPENVOICE_BASE_URL_ENV) or _OPENVOICE_DEFAULT_BASE_URL).strip().rstrip("/")


def openvoice_timeout_seconds() -> int:
    raw = str(os.environ.get(_OPENVOICE_TIMEOUT_ENV) or "").strip()
    try:
        value = int(raw) if raw else _OPENVOICE_DEFAULT_TIMEOUT_SECONDS
    except ValueError:
        value = _OPENVOICE_DEFAULT_TIMEOUT_SECONDS
    return max(15, min(value, 900))


def openvoice_memorial_voice_id() -> str:
    return str(os.environ.get(_OPENVOICE_MEMORIAL_VOICE_ID_ENV) or "").strip()


def openvoice_plugin_option(*, configured_voice_id: str, voice_profile_ready: bool) -> dict[str, object]:
    base_url = openvoice_base_url()
    plugin_enabled = bool(base_url)
    needs_clone = bool(plugin_enabled and voice_profile_ready and not configured_voice_id)
    if not base_url:
        description = "Bitte OPENVOICE_BASE_URL auf einen self-hosted OpenVoice-Service setzen."
    elif needs_clone:
        description = "Stimmprofil ist bereit. Bitte jetzt den OpenVoice-Klon erzeugen."
    elif not configured_voice_id:
        description = "OpenVoice ist verbunden. Es fehlt noch eine aktive Voice-ID."
    else:
        description = "OpenVoice-Klon fuer Live-Sprachausgabe ist aktiviert."
    return {
        "tts_plugin": OPENVOICE_TTS_PLUGIN_ID,
        "tts_plugin_label": OPENVOICE_TTS_PLUGIN_LABEL,
        "tts_plugin_description": description,
        "tts_plugin_enabled": plugin_enabled,
        "tts_plugin_needs_clone": needs_clone,
        "tts_plugin_clone_capable": True,
        "tts_plugin_requires_voice_id": True,
        "tts_plugin_voice_id": configured_voice_id,
        "tts_plugin_voice_profile_ready": bool(voice_profile_ready),
        "tts_plugin_base_url": base_url,
    }


def _openvoice_request(
    *,
    method: str,
    path: str,
    json_payload: dict[str, object] | None = None,
    files: list[tuple[str, object]] | None = None,
    data: dict[str, str] | None = None,
) -> requests.Response:
    base_url = openvoice_base_url()
    if not base_url:
        raise HTTPException(status_code=503, detail="openvoice_base_url_missing")
    try:
        response = requests.request(
            method=method,
            url=f"{base_url}{path}",
            json=json_payload,
            files=files,
            data=data,
            timeout=openvoice_timeout_seconds(),
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"openvoice_upstream_unreachable:{type(exc).__name__}") from exc
    return response


def _prepare_clone_upload_path(path: Path) -> tuple[Path, bool]:
    if not path.is_file():
        raise HTTPException(status_code=400, detail="voice_profile_sample_missing")
    if path.stat().st_size <= 18 * 1024 * 1024:
        return path, False
    suffix = path.suffix or ".wav"
    handle = tempfile.NamedTemporaryFile(prefix="ea-openvoice-clone-", suffix=suffix, delete=False)
    temp_path = Path(handle.name)
    handle.close()
    cmd = [
        shutil.which("ffmpeg") or "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        str(path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(_OPENVOICE_CLONE_SAMPLE_RATE),
        "-t",
        str(_OPENVOICE_CLONE_CLIP_SECONDS),
        str(temp_path),
    ]
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=300,
        )
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=502, detail=f"voice_profile_sample_prepare_failed:{type(exc).__name__}") from exc
    if proc.returncode != 0 or not temp_path.is_file():
        temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=502, detail="voice_profile_sample_prepare_failed")
    return temp_path, True


def _ffprobe_duration_seconds(path: Path) -> float:
    cmd = [
        shutil.which("ffprobe") or "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
        )
    except Exception:
        return 0.0
    if proc.returncode != 0:
        return 0.0
    try:
        return max(0.0, float((proc.stdout or "").strip() or "0"))
    except ValueError:
        return 0.0


def _curate_clone_paths(sample_paths: list[Path]) -> list[Path]:
    if len(sample_paths) <= _OPENVOICE_MAX_CURATED_CLIPS:
        return sample_paths
    scored: list[tuple[float, Path]] = []
    for path in sample_paths:
        duration = _ffprobe_duration_seconds(path)
        size_bytes = path.stat().st_size if path.is_file() else 0
        basename = path.name.lower()
        score = 0.0
        if "hanusch" in basename or "enhanced" in basename:
            score += 2.5
        if basename.endswith(".wav"):
            score += 0.5
        target = min(duration, float(_OPENVOICE_CLONE_CLIP_SECONDS))
        if target > 0:
            score += min(target / 45.0, 3.0)
            score -= abs(target - 90.0) / 240.0
        if size_bytes > 0:
            score += min(math.log10(size_bytes), 8.0) / 8.0
        scored.append((score, path))
    scored.sort(key=lambda item: item[0], reverse=True)
    curated = [path for _, path in scored[:_OPENVOICE_MAX_CURATED_CLIPS]]
    return curated


def openvoice_clone_request(*, slug: str, voice_label: str, sample_paths: list[Path]) -> str:
    if not sample_paths:
        raise HTTPException(status_code=400, detail="voice_profile_no_samples")
    sample_paths = _curate_clone_paths(sample_paths)
    prepared_files: list[tuple[str, object]] = []
    temp_paths: list[Path] = []
    try:
        for index, path in enumerate(sample_paths, start=1):
            upload_path, is_temp = _prepare_clone_upload_path(path)
            if is_temp:
                temp_paths.append(upload_path)
            prepared_files.append(
                (
                    "files",
                    (
                        f"memorial-{slug}-{index}{upload_path.suffix or '.wav'}",
                        upload_path.read_bytes(),
                        "application/octet-stream",
                    ),
                )
            )
        response = _openvoice_request(
            method="POST",
            path="/clone",
            data={
                "slug": slug,
                "voice_label": voice_label,
                "voice_id": f"{slug}-openvoice",
            },
            files=prepared_files,
        )
    finally:
        for temp_path in temp_paths:
            temp_path.unlink(missing_ok=True)
    try:
        payload = response.json()
    except Exception:
        payload = {}
    if response.status_code >= 400 or not response.ok:
        detail = str(payload.get("detail") or payload.get("error") or "openvoice_clone_failed").strip()
        raise HTTPException(status_code=502, detail=f"{detail}:{response.status_code}")
    voice_id = str(payload.get("voice_id") or payload.get("id") or "").strip()
    if not voice_id:
        raise HTTPException(status_code=502, detail="openvoice_clone_invalid_response")
    return voice_id


def openvoice_synthesize_request(*, text: str, voice_id: str, lang: str) -> tuple[bytes, str]:
    return openvoice_synthesize_request_with_variant(text=text, voice_id=voice_id, lang=lang, base_voice_variant="")


def openvoice_synthesize_request_with_variant(*, text: str, voice_id: str, lang: str, base_voice_variant: str) -> tuple[bytes, str]:
    normalized_voice_id = str(voice_id or "").strip()
    if not normalized_voice_id:
        raise HTTPException(status_code=409, detail="tts_voice_id_missing")
    response = _openvoice_request(
        method="POST",
        path="/synthesize",
        json_payload={
            "text": text,
            "voice_id": normalized_voice_id,
            "lang": str(lang or "de").strip() or "de",
            "base_voice_variant": str(base_voice_variant or "default").strip() or "default",
        },
    )
    if response.status_code >= 400 or not response.ok:
        try:
            payload = response.json()
        except Exception:
            payload = {}
        detail = str(payload.get("detail") or payload.get("error") or "openvoice_tts_failed").strip()
        raise HTTPException(status_code=502, detail=f"{detail}:{response.status_code}")
    content = response.content
    if not content:
        raise HTTPException(status_code=502, detail="openvoice_tts_no_audio")
    content_type = str(response.headers.get("Content-Type") or "audio/wav").split(";", 1)[0].strip().lower() or "audio/wav"
    return content, content_type
