from __future__ import annotations

import os
import pathlib
import tempfile
from pathlib import Path


def repo_root() -> Path:
    resolved = Path(__file__).resolve()
    fallback = pathlib.Path(os.getcwd())
    candidates: list[Path] = []
    for index in (4, 3, 2):
        if len(resolved.parents) > index:
            candidates.append(resolved.parents[index])
    candidates.append(fallback)
    for candidate in candidates:
        if (candidate / ".git").is_dir() or (candidate / ".codex-design").is_dir():
            return candidate
    if len(resolved.parents) > 2:
        return resolved.parents[2]
    return fallback


def memorial_data_root() -> Path:
    configured = str(os.getenv("EA_MEMORIAL_DATA_ROOT") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return repo_root()


def memorial_operator_status_path() -> Path:
    configured = str(os.getenv("EA_MEMORIAL_OPERATOR_STATUS_PATH") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return repo_root() / ".codex-design/product/MEMORIAL_OPERATOR_STATUS.generated.json"


def memorial_phrase_bank_path() -> Path:
    configured = str(os.getenv("EA_MEMORIAL_PHRASE_BANK_PATH") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return repo_root() / ".codex-design/product/MEMORIAL_PHRASE_BANK.manfred.generated.json"


def memorial_state_dir() -> Path:
    configured = str(os.getenv("EA_MEMORIAL_STATE_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return repo_root() / "state"


def public_memorial_artifact_root() -> Path:
    configured = str(os.getenv("EA_PUBLIC_MEMORIAL_ARTIFACT_DIR") or "").strip()
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.append(Path("/data/artifacts"))
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".ea_public_memorial_write_probe"
            probe.write_bytes(b"ok")
            probe.unlink(missing_ok=True)
            return candidate
        except OSError:
            continue
    fallback = Path(tempfile.gettempdir()) / "ea_public_memorial_artifacts"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


PUBLIC_MEMORIAL_ARTIFACT_ROOT = public_memorial_artifact_root()
PERSONAL_MEMORY_ROOT = PUBLIC_MEMORIAL_ARTIFACT_ROOT / "memorial_user_memory"
VOICE_AB_ROOT = PUBLIC_MEMORIAL_ARTIFACT_ROOT / "memorial_voice_ab"
VIDEO_MEETING_RUNTIME_ROOT = PUBLIC_MEMORIAL_ARTIFACT_ROOT / "memorial_video_meeting"
MEMORIAL_TTS_RENDER_CACHE_ROOT = PUBLIC_MEMORIAL_ARTIFACT_ROOT / "memorial_tts_render_cache"
MEMORIAL_PRESENT_WORLD_CACHE_ROOT = PUBLIC_MEMORIAL_ARTIFACT_ROOT / "memorial_present_world_cache"
PUBLIC_MEMORIAL_RATE_DB = PUBLIC_MEMORIAL_ARTIFACT_ROOT / "memorial_rate_limits.sqlite3"


def memorial_dir_candidates() -> list[Path]:
    candidates: list[Path] = []
    configured = str(os.getenv("EA_PUBLIC_MEMORIAL_DIR") or "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.append(memorial_data_root() / "memorial_data" / "public_memorials")
    candidates.append(memorial_data_root() / "public_memorials")
    candidates.append(Path("/mnt/pcloud/EA/public_memorials"))
    seen: set[str] = set()
    unique: list[Path] = []
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def memorial_dir() -> Path:
    for candidate in memorial_dir_candidates():
        if candidate.exists() and candidate.is_dir():
            try:
                if any(candidate.iterdir()):
                    return candidate
            except OSError:
                continue
    return memorial_dir_candidates()[0]


def resolved_memorial_root() -> Path:
    return memorial_dir().resolve()


def private_profile_dir_candidates() -> list[Path]:
    candidates: list[Path] = []
    configured = str(os.getenv("EA_PRIVATE_MEMORIAL_PROFILE_DIR") or "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.append(memorial_data_root() / "memorial_data" / "private_memorial_profiles")
    candidates.append(memorial_data_root() / "private_memorial_profiles")
    candidates.append(Path("/mnt/pcloud/EA/private_memorial_profiles"))
    seen: set[str] = set()
    unique: list[Path] = []
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def private_profile_dir() -> Path:
    for candidate in private_profile_dir_candidates():
        if candidate.exists() and candidate.is_dir():
            try:
                if any(candidate.iterdir()):
                    return candidate
            except OSError:
                continue
    return private_profile_dir_candidates()[0]
