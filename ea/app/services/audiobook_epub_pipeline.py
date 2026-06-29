from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
import base64
import errno
import io
import hmac
from html import unescape
from html.parser import HTMLParser
import hashlib
import json
import math
import mimetypes
import os
from pathlib import Path
import posixpath
import re
import shutil
import shlex
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import struct
import wave
import zipfile
import xml.etree.ElementTree as ET

from app.services.memorial_openvoice import (
    unmixr_language,
    unmixr_api_key,
    unmixr_api_key_slot_count,
    unmixr_memorial_voice_id,
    unmixr_speaking_pitch,
    unmixr_speaking_rate,
    unmixr_speaking_volume,
    unmixr_synthesize_request,
)


CONTRACT_NAME = "ea.telegram_epub_to_audiobook.v1"
PLAYER_AUDIOBOOK_ACCESS_CONTRACT_NAME = "ea.player_scoped_audiobookshelf_reference.v1"
AUDIOBOOK_JOB_RECEIPT_CONTRACT_NAME = "ea.telegram_epub_audiobook_job_receipt.v1"
AUDIOBOOK_RUNTIME_PREFLIGHT_CONTRACT_NAME = "ea.telegram_epub_audiobook_runtime_preflight.v1"
VOICE_AUDITION_CONTRACT_NAME = "ea.telegram_epub_audiobook_voice_audition.v1"
PLAYBACK_ACCEPTANCE_CONTRACT_NAME = "ea.telegram_epub_audiobook_playback_acceptance.v1"
VOICE_FEEDBACK_CONTRACT_NAME = "ea.audiobook_voice_feedback.v1"
EA_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DURABLE_AUDIOBOOK_ROOT = Path(os.environ.get("EA_AUDIOBOOK_DURABLE_STORAGE_ROOT") or EA_ROOT / "data" / "audiobooks")
DEFAULT_JOB_ROOT = DEFAULT_DURABLE_AUDIOBOOK_ROOT / "jobs"
DEFAULT_AUDIOBOOKSHELF_IMPORT_ROOT = DEFAULT_DURABLE_AUDIOBOOK_ROOT / "audiobookshelf"
DEFAULT_ENV_FILES = (EA_ROOT / ".env", EA_ROOT / ".env.local", EA_ROOT / "ea" / ".env")
_EPUB_MIME_TYPES = {"application/epub+zip", "application/octet-stream", "application/zip", ""}
_KINDLE_SOURCE_EXTENSIONS = {".azw", ".azw3", ".mobi", ".prc"}
_KINDLE_MIME_TYPES = {
    "application/octet-stream",
    "application/x-mobipocket-ebook",
    "application/vnd.amazon.ebook",
    "application/x-mobi8-ebook",
    "",
}
_HTML_MEDIA_TYPES = {"application/xhtml+xml", "text/html", "application/xml", "text/xml"}
_IMAGE_MEDIA_TYPES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
_AUDIO_EXTENSION_BY_TYPE = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/flac": ".flac",
    "audio/ogg": ".ogg",
    "audio/aiff": ".aiff",
}
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._()\\[\\] -]+")
_PROVIDER_WAIT_RE = re.compile(r"(?:available|retry|try again)[^0-9]{0,40}(\d{2,})\s*seconds?", re.IGNORECASE)
_VOICE_DISCOVERY_CACHE: dict[str, tuple[float, tuple["VoicePreset", ...]]] = {}
_DOTENV_CACHE: dict[tuple[Path, ...], dict[str, str]] = {}
_AUDIOBOOK_CLEANUP_MISSING_ERRNOS = {
    errno.ENOENT,
    errno.ENOTDIR,
    getattr(errno, "ESTALE", errno.ENOENT),
    getattr(errno, "ENOTCONN", errno.ENOENT),
}


@dataclass(frozen=True)
class EpubChapter:
    index: int
    title: str
    source_href: str
    text_path: str
    audio_filename: str
    char_count: int
    sha256: str


@dataclass(frozen=True)
class EpubMetadata:
    title: str
    author: str
    language: str
    source_filename: str
    source_sha256: str
    cover_image_path: str = ""
    cover_media_type: str = ""


@dataclass(frozen=True)
class VoicePreset:
    preset_key: str
    voice_id: str
    label: str
    language: str
    tags: tuple[str, ...]
    supported_languages: tuple[str, ...] = ()
    default: bool = False
    source: str = "env"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _parse_iso_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on", "enabled"}


def _env_int(name: str, default: int, *, minimum: int = 1, maximum: int | None = None) -> int:
    raw = str(os.getenv(name) or "").strip()
    try:
        value = int(float(raw or str(default)))
    except Exception:
        value = default
    value = max(value, minimum)
    if maximum is not None:
        value = min(value, maximum)
    return value


def _env_float(name: str, default: float, *, minimum: float = 0.0, maximum: float | None = None) -> float:
    raw = str(os.getenv(name) or "").strip()
    try:
        value = float(raw or str(default))
    except Exception:
        value = default
    value = max(value, minimum)
    if maximum is not None:
        value = min(value, maximum)
    return value


def _env_path(name: str, default: Path) -> Path:
    raw = str(os.getenv(name) or "").strip()
    return Path(raw).expanduser() if raw else default


def _split_configured_paths(value: str) -> tuple[Path, ...]:
    raw = str(value or "").strip()
    if not raw:
        return ()
    paths: list[Path] = []
    for item in re.split(r"[:;,]", raw):
        normalized = str(item or "").strip()
        if normalized:
            paths.append(Path(normalized).expanduser())
    return tuple(paths)


def _dotenv_values(env_files: tuple[Path, ...] = DEFAULT_ENV_FILES) -> dict[str, str]:
    cached = _DOTENV_CACHE.get(env_files)
    if cached is not None:
        return dict(cached)
    values: dict[str, str] = {}
    for path in env_files:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key:
                continue
            normalized = value.strip()
            if len(normalized) >= 2 and normalized[:1] == normalized[-1:] and normalized[:1] in {"'", '"'}:
                normalized = normalized[1:-1]
            values[key] = normalized
    _DOTENV_CACHE[env_files] = dict(values)
    return dict(values)


def _env_or_dotenv(name: str, default: str = "") -> str:
    direct = str(os.getenv(name) or "").strip()
    if direct:
        return direct
    return str(_dotenv_values().get(name) or default).strip()


def _storage_path_accessible(path: Path) -> bool:
    return bool(_storage_path_probe(path).get("accessible"))


def _storage_path_probe(path: Path) -> dict[str, object]:
    target = Path(path)
    try:
        if target.exists():
            return {"path": str(target), "accessible": True, "status": "present"}
        parent = target.parent
        if parent != target and parent.exists():
            return {"path": str(target), "accessible": True, "status": "parent_present"}
        return {"path": str(target), "accessible": False, "status": "missing"}
    except OSError as exc:
        errno_value = getattr(exc, "errno", None)
        status = "oserror"
        if errno_value == getattr(errno, "ENOTCONN", None):
            status = "disconnected_mount"
        elif errno_value == getattr(errno, "ESTALE", None):
            status = "stale_mount"
        return {
            "path": str(target),
            "accessible": False,
            "status": status,
            "error": type(exc).__name__,
            "errno": int(errno_value) if errno_value is not None else None,
        }


def _env_path_with_host_fallback(name: str, default: Path, *, host_fallback_name: str = "") -> Path:
    raw = _env_or_dotenv(name)
    if raw:
        candidate = Path(raw).expanduser()
        if _storage_path_accessible(candidate):
            return candidate
    if host_fallback_name:
        host_raw = _env_or_dotenv(host_fallback_name)
        if host_raw:
            candidate = Path(host_raw).expanduser()
            if _storage_path_accessible(candidate):
                return candidate
    return default


def telegram_audiobook_skill_enabled() -> bool:
    if str(os.getenv("EA_TELEGRAM_AUDIOBOOK_ENABLED") or "").strip():
        return _env_bool("EA_TELEGRAM_AUDIOBOOK_ENABLED", True)
    return _env_bool("EA_TELEGRAM_AUDIOBOOK_EPUB_ENABLED", True)


def telegram_epub_skill_enabled() -> bool:
    return telegram_audiobook_skill_enabled()


def external_tts_enabled() -> bool:
    return _env_bool("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", False)


def unmixr_auto_render_enabled() -> bool:
    return external_tts_enabled() and _env_bool("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", False)


def _voice_candidate_allowed_for_audition(candidate: dict[str, object]) -> bool:
    provider = str(candidate.get("provider") or "").strip()
    preset_key = str(candidate.get("preset_key") or candidate.get("candidate_key") or "").strip()
    return provider != "piper_local_fast" and not preset_key.startswith("piper_local_fast")


def _unmixr_max_segments_per_run() -> int:
    return _env_int("EA_AUDIOBOOK_UNMIXR_MAX_SEGMENTS_PER_RUN", 20, minimum=0, maximum=500)


def _audiobook_cinematic_narration() -> bool:
    return _env_bool("EA_AUDIOBOOK_CINEMATIC_NARRATION", True)


def _audiobook_cinematic_single_pass() -> bool:
    # One uninterrupted cinematic narration is required for premium quality output.
    # Keep this hard-pinned to true to prevent clip-stitch artifacts at runtime.
    return True


def _audiobook_cinematic_max_chars_per_request() -> int:
    return _env_int(
        "EA_AUDIOBOOK_CINEMATIC_MAX_CHARS_PER_REQUEST",
        _env_int("EA_AUDIOBOOK_UNMIXR_MAX_CHARS_PER_REQUEST", 50000, minimum=8000, maximum=200000),
        minimum=8000,
        maximum=200000,
    )


def _cinematic_master_audio_path(audio_dir: Path) -> Path:
    return audio_dir / "_cinematic_master.wav"


def _cinematic_master_audio_mode_path(audio_dir: Path) -> Path:
    return audio_dir / "_cinematic_master.mode"


def _cinematic_master_audio_signature_path(audio_dir: Path) -> Path:
    return audio_dir / "_cinematic_master.signature"


def _collect_cinematic_track_input(*, job_dir: Path, chapters: tuple[EpubChapter, ...]) -> tuple[tuple[EpubChapter, str], ...]:
    if not chapters:
        return ()
    values: list[tuple[EpubChapter, str]] = []
    for chapter in chapters:
        source_text = (job_dir / "chapters" / chapter.text_path).read_text(encoding="utf-8")
        values.append((chapter, str(source_text or "").strip()))
    return tuple(values)


def _cinematic_track_signature(*, chapter_inputs: tuple[tuple[EpubChapter, str], ...]) -> str:
    payload = "\n".join(f"{chapter.index}:{text}" for chapter, text in chapter_inputs)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_CINEMATIC_MASTER_SINGLE_PASS_MODE = "unmixr_cinematic_single_pass"


def _discover_or_build_cinematic_master_audio(
    *,
    job_dir: Path,
    chapters: tuple[EpubChapter, ...],
) -> Path | None:
    if not _audiobook_cinematic_narration():
        return None
    audio_dir = job_dir / "audio"
    cinematic_master = _cinematic_master_audio_path(audio_dir)
    if not cinematic_master.is_file() or cinematic_master.stat().st_size <= 0:
        return None

    cinematic_mode_path = _cinematic_master_audio_mode_path(audio_dir)
    cinematic_signature_path = _cinematic_master_audio_signature_path(audio_dir)
    cinematic_track_input = _collect_cinematic_track_input(job_dir=job_dir, chapters=chapters)
    if not cinematic_track_input:
        return None
    cinematic_signature_expected = _cinematic_track_signature(chapter_inputs=tuple(cinematic_track_input))

    cinematic_mode = ""
    cinematic_signature_cached = ""
    if cinematic_mode_path.is_file():
        try:
            cinematic_mode = cinematic_mode_path.read_text(encoding="utf-8").strip()
        except OSError:
            cinematic_mode = ""
    if cinematic_signature_path.is_file():
        try:
            cinematic_signature_cached = cinematic_signature_path.read_text(encoding="utf-8").strip()
        except OSError:
            cinematic_signature_cached = ""

    if (
        cinematic_mode != _CINEMATIC_MASTER_SINGLE_PASS_MODE
        or not cinematic_signature_cached
        or cinematic_signature_cached != cinematic_signature_expected
    ):
        return None

    return cinematic_master


def _unmixr_pacing_wait_seconds() -> int:
    return _env_int("EA_AUDIOBOOK_UNMIXR_PACING_WAIT_SECONDS", 1800, minimum=60, maximum=86400)


def _unmixr_bulk_pacing_char_threshold() -> int:
    return _env_int("EA_AUDIOBOOK_UNMIXR_BULK_PACING_CHAR_THRESHOLD", 60000, minimum=0, maximum=5_000_000)


def _priority_audiobook_source_kinds() -> tuple[str, ...]:
    raw = str(os.getenv("EA_AUDIOBOOK_PRIORITY_SOURCE_KINDS") or "").strip()
    if not raw:
        return ("origin_dossier_story", "origin_dossier")
    return tuple(_normalize_tag(part) for part in raw.split(",") if _normalize_tag(part))


def _job_render_context(job_dir: Path, chapters: tuple[EpubChapter, ...]) -> dict[str, object]:
    try:
        job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    except Exception:
        job = {}
    source = dict(job.get("source") or {}) if isinstance(job, dict) else {}
    totals = dict(job.get("totals") or {}) if isinstance(job, dict) else {}
    return {
        "source_kind": _normalize_tag(source.get("kind")),
        "total_chars": int(totals.get("char_count") or sum(chapter.char_count for chapter in chapters)),
    }


def _unmixr_bulk_pacing_policy(*, job_dir: Path, chapters: tuple[EpubChapter, ...]) -> dict[str, object]:
    max_segments = _unmixr_max_segments_per_run()
    wait_seconds = _unmixr_pacing_wait_seconds()
    context = _job_render_context(job_dir, chapters)
    source_kind = str(context.get("source_kind") or "")
    total_chars = int(context.get("total_chars") or 0)
    threshold = _unmixr_bulk_pacing_char_threshold()
    priority_source = source_kind in _priority_audiobook_source_kinds()
    enabled = max_segments > 0 and not priority_source and total_chars >= threshold
    return {
        "enabled": enabled,
        "max_segments_per_run": max_segments,
        "wait_seconds": wait_seconds,
        "bulk_char_threshold": threshold,
        "priority_source": priority_source,
        "source_kind": source_kind,
        "total_chars": total_chars,
    }


def m4b_auto_merge_enabled() -> bool:
    return _env_bool("EA_AUDIOBOOK_M4B_AUTO_MERGE", True)


def ffmpeg_m4b_fallback_enabled() -> bool:
    return _env_bool("EA_AUDIOBOOK_FFMPEG_M4B_FALLBACK", True)


def audiobookshelf_import_enabled() -> bool:
    return _env_bool("EA_AUDIOBOOKSHELF_AUTO_IMPORT", True)


def audiobook_jobs_root() -> Path:
    return _env_path_with_host_fallback(
        "EA_AUDIOBOOK_JOBS_ROOT",
        DEFAULT_JOB_ROOT,
        host_fallback_name="EA_AUDIOBOOK_JOBS_HOST_ROOT",
    )


def audiobook_job_discovery_roots() -> tuple[Path, ...]:
    configured = [
        *_split_configured_paths(str(os.getenv("EA_AUDIOBOOK_JOB_DISCOVERY_ROOTS") or "")),
        *_split_configured_paths(str(os.getenv("EA_AUDIOBOOK_JOBS_ROOT") or "")),
        *_split_configured_paths(str(os.getenv("EA_AUDIOBOOK_JOBS_HOST_ROOT") or "")),
        audiobook_jobs_root(),
        DEFAULT_JOB_ROOT,
    ]
    roots: list[Path] = []
    seen: set[str] = set()
    for root in configured:
        try:
            key = str(root.resolve())
        except Exception:
            key = str(root)
        if key in seen:
            continue
        seen.add(key)
        if _storage_path_accessible(root):
            roots.append(root)
    return tuple(roots)


def iter_audiobook_job_manifests(*, newest_first: bool = False) -> tuple[Path, ...]:
    manifests: list[Path] = []
    seen: set[str] = set()
    for root in audiobook_job_discovery_roots():
        try:
            root_manifests = tuple(root.glob("*/job.json"))
        except OSError:
            continue
        for manifest_path in root_manifests:
            try:
                key = str(manifest_path.resolve())
            except Exception:
                key = str(manifest_path)
            if key in seen:
                continue
            seen.add(key)
            manifests.append(manifest_path)

    def _sort_key(path: Path) -> tuple[float, str]:
        try:
            mtime = float(path.stat().st_mtime)
        except OSError:
            mtime = 0.0
        return (mtime, str(path))

    return tuple(sorted(manifests, key=_sort_key, reverse=bool(newest_first)))


def audiobook_voice_feedback_path() -> Path:
    return _env_path("EA_AUDIOBOOK_VOICE_FEEDBACK_PATH", audiobook_jobs_root() / "voice-feedback.json")


def audiobookshelf_import_root() -> Path:
    return _env_path_with_host_fallback(
        "EA_AUDIOBOOKSHELF_IMPORT_ROOT",
        DEFAULT_AUDIOBOOKSHELF_IMPORT_ROOT,
        host_fallback_name="EA_AUDIOBOOKSHELF_IMPORT_HOST_ROOT",
    )


def audiobook_job_cleanup_enabled() -> bool:
    return _env_bool("EA_AUDIOBOOK_JOB_CLEANUP_ENABLED", True)


def _audiobook_job_cleanup_min_age_seconds() -> int:
    return _env_int("EA_AUDIOBOOK_JOB_CLEANUP_MIN_AGE_SECONDS", 300, minimum=0, maximum=604800)


def _audiobook_job_cleanup_remove_render_dirs() -> bool:
    return _env_bool("EA_AUDIOBOOK_JOB_CLEANUP_REMOVE_RENDER_DIRS", True)


def _audiobook_job_cleanup_prune_staging_days() -> int:
    return _env_int("EA_AUDIOBOOK_JOB_CLEANUP_STAGING_RETENTION_DAYS", 2, minimum=0, maximum=90)


def audiobookshelf_public_share_enabled() -> bool:
    return _env_bool("EA_AUDIOBOOKSHELF_PUBLIC_SHARE_ENABLED", False)


def m4b_tool_bin() -> str:
    return str(os.getenv("EA_M4B_TOOL_BIN") or "m4b-tool").strip() or "m4b-tool"


def _normalize_tag(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _normalize_language(value: object) -> str:
    return str(value or "").strip().replace("_", "-").lower()


def _split_tags(value: object) -> tuple[str, ...]:
    if isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = re.split(r"[,; ]+", str(value or ""))
    seen: list[str] = []
    for item in raw_items:
        tag = _normalize_tag(item)
        if tag and tag not in seen:
            seen.append(tag)
    return tuple(seen)


def _audiobook_voice_language_from_tags(tags: tuple[str, ...]) -> str:
    explicit = _normalize_language(os.getenv("EA_AUDIOBOOK_DEFAULT_VOICE_LANGUAGE") or "")
    if explicit:
        return explicit
    tag_set = {str(tag).lower() for tag in tags}
    if tag_set.intersection({"german", "de", "de_de", "deutsch"}):
        return "de"
    if tag_set.intersection({"english", "en", "en_us", "en_gb"}):
        return _normalize_language(os.getenv("UNMIXR_LANGUAGE") or "en-US")
    return _normalize_language(os.getenv("UNMIXR_LANGUAGE") or "en-US")


def _row_tag_values(row: dict[str, object]) -> tuple[object, ...]:
    values: list[object] = []
    for key in ("tags", "style_tags", "genres"):
        value = row.get(key)
        if isinstance(value, (list, tuple, set)):
            values.extend(value)
        elif value:
            values.extend(re.split(r"[,; ]+", str(value)))
    return tuple(values)


def _voice_blocklist_terms() -> tuple[str, ...]:
    raw = str(os.getenv("EA_AUDIOBOOK_VOICE_BLOCKLIST") or "alice").strip()
    return tuple(_normalize_tag(part) for part in re.split(r"[,;]+", raw) if _normalize_tag(part))


def audiobook_voice_audition_enabled() -> bool:
    return _env_bool("EA_AUDIOBOOK_VOICE_AUDITION_ENABLED", True)


def audiobook_voice_discovery_enabled() -> bool:
    return _env_bool("EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED", True)


def audiobook_voice_discovery_target_count() -> int:
    return _env_int("EA_AUDIOBOOK_VOICE_DISCOVERY_TARGET_COUNT", 100, minimum=3, maximum=300)


def audiobook_voice_sample_generation_max_attempts(*, batch_size: int | None = None) -> int:
    default_attempts = max((int(batch_size or 3) * 4), 12)
    return _env_int("EA_AUDIOBOOK_VOICE_SAMPLE_GENERATION_MAX_ATTEMPTS", default_attempts, minimum=1, maximum=100)


def audiobook_voice_audition_min_candidates() -> int:
    return _env_int("EA_AUDIOBOOK_VOICE_AUDITION_MIN_CANDIDATES", 3, minimum=1, maximum=30)


def _coerce_voice_discovery_target_count(*, requested_count: int | None = None) -> int:
    base_count = audiobook_voice_discovery_target_count()
    if requested_count is None:
        return base_count
    try:
        normalized = int(requested_count)
    except Exception:
        return base_count
    normalized = max(normalized, 3)
    return min(max(normalized, base_count), 300)


def is_audiobook_source_document(*, filename: str, mime_type: str = "") -> bool:
    normalized_filename = str(filename or "").strip().lower().split("?", 1)[0]
    normalized_mime = str(mime_type or "").strip().lower().split(";", 1)[0]
    suffix = Path(normalized_filename).suffix
    if suffix == ".epub":
        return normalized_mime in _EPUB_MIME_TYPES
    if suffix in _KINDLE_SOURCE_EXTENSIONS:
        return normalized_mime in _KINDLE_MIME_TYPES
    return False


def is_epub_document(*, filename: str, mime_type: str = "") -> bool:
    return is_audiobook_source_document(filename=filename, mime_type=mime_type)


def _is_kindle_source_document(path_or_filename: object) -> bool:
    return Path(str(path_or_filename or "").strip().split("?", 1)[0].lower()).suffix in _KINDLE_SOURCE_EXTENSIONS


def _ebook_convert_bin() -> str:
    return str(os.getenv("EA_AUDIOBOOK_EBOOK_CONVERT_BIN") or "ebook-convert").strip() or "ebook-convert"


def _kindle_to_epub_converter_available() -> bool:
    return shutil.which(_ebook_convert_bin()) is not None


def _convert_kindle_source_to_epub(*, source_path: Path, output_path: Path) -> dict[str, object]:
    if not _kindle_to_epub_converter_available():
        return {
            "status": "blocked",
            "reason": "kindle_audiobook_converter_missing",
            "converter": _ebook_convert_bin(),
            "raw_paths_exposed": False,
        }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [_ebook_convert_bin(), str(source_path), str(output_path)]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=_env_int("EA_AUDIOBOOK_KINDLE_CONVERT_TIMEOUT_SECONDS", 900, minimum=30, maximum=7200),
        )
    except Exception as exc:
        return {
            "status": "failed",
            "reason": type(exc).__name__,
            "converter": _ebook_convert_bin(),
            "raw_paths_exposed": False,
        }
    if completed.returncode != 0 or not output_path.is_file() or output_path.stat().st_size <= 0:
        return {
            "status": "failed",
            "reason": "kindle_to_epub_conversion_failed",
            "converter": _ebook_convert_bin(),
            "returncode": completed.returncode,
            "stderr_tail": str(completed.stderr or "")[-1200:],
            "raw_paths_exposed": False,
        }
    try:
        validate_epub_archive(output_path)
    except Exception as exc:
        return {
            "status": "failed",
            "reason": "kindle_to_epub_output_invalid",
            "detail": type(exc).__name__,
            "converter": _ebook_convert_bin(),
            "raw_paths_exposed": False,
        }
    return {
        "status": "converted",
        "converter": _ebook_convert_bin(),
        "source_sha256": _sha256_file(source_path),
        "epub_sha256": _sha256_file(output_path),
        "raw_paths_exposed": False,
    }


def _safe_filename(value: str, *, fallback: str = "untitled", suffix: str = "") -> str:
    normalized = " ".join(str(value or "").replace("/", " ").replace("\\", " ").split()).strip()
    normalized = _SAFE_NAME_RE.sub("", normalized).strip(" .")
    if not normalized:
        normalized = fallback
    if len(normalized) > 96:
        normalized = normalized[:96].rstrip(" .")
    if suffix and not normalized.lower().endswith(suffix.lower()):
        normalized = f"{normalized}{suffix}"
    return normalized


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _durable_storage_root() -> Path:
    return _env_path("EA_AUDIOBOOK_DURABLE_STORAGE_ROOT", DEFAULT_DURABLE_AUDIOBOOK_ROOT)


def _legacy_pcloud_root() -> Path | None:
    configured = str(os.environ.get("EA_AUDIOBOOK_PCLOUD_ROOT") or "").strip()
    if not configured:
        return None
    return Path(configured).expanduser()


def _require_durable_storage_root(root: Path) -> None:
    normalized = root.expanduser().resolve()
    if _env_bool("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", False):
        return
    durable_root = _durable_storage_root().expanduser().resolve()
    try:
        normalized.relative_to(durable_root)
    except ValueError as exc:
        raise RuntimeError("audiobook_jobs_root_must_be_on_durable_storage") from exc
    if not _durable_storage_available_for_path(normalized):
        raise RuntimeError("durable_storage_not_available_for_audiobook_jobs")


def _require_audiobook_storage_root(root: Path) -> None:
    _require_durable_storage_root(root)


def _durable_storage_available_for_path(path: Path) -> bool:
    durable_root = _durable_storage_root().expanduser()
    try:
        normalized = path.expanduser().resolve()
    except Exception:
        normalized = path.expanduser()
    try:
        normalized.relative_to(durable_root.resolve())
    except ValueError:
        return False
    if _path_storage_kind(normalized) == "pcloud":
        return _pcloud_mount_available_for_path(normalized)
    return durable_root.exists()


def _pcloud_mount_available_for_path(path: Path) -> bool:
    pcloud = _legacy_pcloud_root()
    if pcloud is None:
        return False
    try:
        normalized = path.expanduser().resolve()
    except Exception:
        normalized = path.expanduser()
    try:
        normalized.relative_to(pcloud)
    except ValueError:
        return False
    current = normalized if normalized.exists() else normalized.parent
    while current != current.parent:
        if current.exists() and current.is_mount():
            return True
        if current == pcloud:
            break
        current = current.parent
    return pcloud.exists() and pcloud.is_mount()


def _telegram_file_url_allowed(source_url: str) -> bool:
    parsed = urllib.parse.urlparse(str(source_url or "").strip())
    if parsed.scheme != "https":
        return False
    if parsed.netloc.lower() != "api.telegram.org":
        return False
    return parsed.path.startswith("/file/bot")


def is_telegram_epub_download_url_allowed(source_url: str) -> bool:
    return _telegram_file_url_allowed(source_url)


def _declared_epub_byte_limit() -> int:
    return _env_int("EA_AUDIOBOOK_TELEGRAM_MAX_BYTES", 200 * 1024 * 1024, minimum=1024 * 32)


def _epub_max_uncompressed_bytes() -> int:
    return _env_int("EA_AUDIOBOOK_EPUB_MAX_UNCOMPRESSED_BYTES", 600 * 1024 * 1024, minimum=1024 * 1024)


def _epub_max_archive_entries() -> int:
    return _env_int("EA_AUDIOBOOK_EPUB_MAX_ARCHIVE_ENTRIES", 2500, minimum=10, maximum=20000)


def _safe_zip_member_name(value: object) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw or raw.startswith("/") or "\x00" in raw:
        return ""
    normalized = posixpath.normpath(raw)
    if normalized in {"", ".", ".."} or normalized.startswith("../") or "/../" in f"/{normalized}/":
        return ""
    return normalized


def validate_epub_archive(epub_path: Path) -> dict[str, object]:
    try:
        with zipfile.ZipFile(epub_path) as zip_handle:
            infos = zip_handle.infolist()
            if len(infos) > _epub_max_archive_entries():
                raise RuntimeError("epub_archive_entry_count_exceeded")
            total_uncompressed = 0
            names: set[str] = set()
            for info in infos:
                safe_name = _safe_zip_member_name(info.filename)
                if not safe_name:
                    raise RuntimeError("epub_archive_unsafe_member_path")
                total_uncompressed += int(info.file_size or 0)
                if total_uncompressed > _epub_max_uncompressed_bytes():
                    raise RuntimeError("epub_archive_uncompressed_size_exceeded")
                names.add(safe_name)
            if "mimetype" not in names:
                raise RuntimeError("epub_mimetype_missing")
            mimetype = zip_handle.read("mimetype").decode("ascii", "replace").strip()
            if mimetype != "application/epub+zip":
                raise RuntimeError("epub_mimetype_invalid")
            if "META-INF/container.xml" not in names:
                raise RuntimeError("epub_container_missing")
            rootfile, _opf_root = _read_opf(zip_handle)
            safe_rootfile = _safe_zip_member_name(rootfile)
            if not safe_rootfile or safe_rootfile not in names:
                raise RuntimeError("epub_rootfile_unsafe_or_missing")
    except zipfile.BadZipFile as exc:
        raise RuntimeError("telegram_epub_not_zip") from exc
    return {
        "status": "pass",
        "entry_count": len(infos),
        "uncompressed_bytes": total_uncompressed,
        "rootfile": safe_rootfile,
    }


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        raise urllib.error.HTTPError(req.full_url, code, "redirects_disabled", headers, fp)


def download_telegram_epub(*, source_url: str, target_path: Path, max_bytes: int | None = None) -> dict[str, object]:
    if not _telegram_file_url_allowed(source_url):
        raise RuntimeError("telegram_epub_url_not_allowed")
    limit = max_bytes or _declared_epub_byte_limit()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(source_url, headers={"Accept": "application/epub+zip,application/octet-stream"})
    total = 0
    digest = hashlib.sha256()
    try:
        with opener.open(request, timeout=_env_int("EA_AUDIOBOOK_TELEGRAM_DOWNLOAD_TIMEOUT_SECONDS", 90, minimum=5)) as response:
            with target_path.open("wb") as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > limit:
                        raise RuntimeError("telegram_epub_too_large")
                    digest.update(chunk)
                    output.write(chunk)
    except Exception:
        with contextlib_suppress_unlink(target_path):
            pass
        raise
    if total < 58:
        raise RuntimeError("telegram_epub_empty_or_invalid")
    with target_path.open("rb") as handle:
        if handle.read(2) != b"PK":
            raise RuntimeError("telegram_epub_not_zip")
    archive_validation = validate_epub_archive(target_path)
    return {"bytes": total, "sha256": digest.hexdigest(), "archive_validation": archive_validation}


class contextlib_suppress_unlink:
    def __init__(self, path: Path) -> None:
        self.path = path

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            self.path.unlink(missing_ok=True)
        except Exception:
            pass
        return False


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        lowered = tag.lower()
        if lowered in {"script", "style", "svg", "math"}:
            self._skip_depth += 1
        if lowered in {"p", "div", "section", "article", "br", "li", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style", "svg", "math"} and self._skip_depth:
            self._skip_depth -= 1
        if lowered in {"p", "div", "section", "article", "li", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = " ".join(str(data or "").split())
        if text:
            self.parts.append(text)

    def text(self) -> str:
        rendered = "\n".join(part.strip() for part in " ".join(self.parts).split("\n") if part.strip())
        rendered = re.sub(r"\n{3,}", "\n\n", rendered)
        return unescape(rendered).strip()


class _TitleExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._capture_tag = ""
        self.candidates: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        lowered = tag.lower()
        if lowered in {"h1", "h2", "title"} and not self._capture_tag:
            self._capture_tag = lowered

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == self._capture_tag:
            self._capture_tag = ""

    def handle_data(self, data: str) -> None:
        if self._capture_tag:
            text = " ".join(str(data or "").split()).strip()
            if text:
                self.candidates.append(text)

    def title(self) -> str:
        return next((candidate for candidate in self.candidates if candidate), "")


def _html_to_text(payload: bytes) -> str:
    raw = payload.decode("utf-8", "replace")
    parser = _TextExtractor()
    parser.feed(raw)
    return _clean_epub_text(parser.text())


def _clean_epub_text(text: str) -> str:
    cleaned = str(text or "").replace("\ufeff", " ")
    cleaned = re.sub(r"[ \t\r\f\v]+", " ", cleaned)
    cleaned = re.sub(r"\n[ \t]+", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _html_title(payload: bytes) -> str:
    raw = payload.decode("utf-8", "replace")
    parser = _TitleExtractor()
    parser.feed(raw)
    return parser.title()


def _xml_text(root: ET.Element, names: tuple[str, ...]) -> str:
    for element in root.iter():
        local = element.tag.rsplit("}", 1)[-1].lower()
        if local in names:
            text = " ".join(str(element.text or "").split()).strip()
            if text:
                return text
    return ""


def _read_opf(zip_handle: zipfile.ZipFile) -> tuple[str, ET.Element]:
    container = ET.fromstring(zip_handle.read("META-INF/container.xml"))
    rootfile = ""
    for element in container.iter():
        if element.tag.rsplit("}", 1)[-1] == "rootfile":
            rootfile = str(element.attrib.get("full-path") or "").strip()
            if rootfile:
                break
    if not rootfile:
        raise RuntimeError("epub_rootfile_missing")
    safe_rootfile = _safe_zip_member_name(rootfile)
    if not safe_rootfile:
        raise RuntimeError("epub_rootfile_unsafe_or_missing")
    return safe_rootfile, ET.fromstring(zip_handle.read(safe_rootfile))


def _opf_manifest_and_spine(opf_root: ET.Element) -> tuple[dict[str, dict[str, str]], list[str]]:
    manifest: dict[str, dict[str, str]] = {}
    spine: list[str] = []
    for element in opf_root.iter():
        local = element.tag.rsplit("}", 1)[-1]
        if local == "item":
            item_id = str(element.attrib.get("id") or "").strip()
            if item_id:
                manifest[item_id] = {
                    "href": str(element.attrib.get("href") or "").strip(),
                    "media_type": str(element.attrib.get("media-type") or "").strip().lower(),
                    "properties": str(element.attrib.get("properties") or "").strip().lower(),
                }
        elif local == "itemref":
            idref = str(element.attrib.get("idref") or "").strip()
            if idref:
                spine.append(idref)
    return manifest, spine


def _opf_cover_item_id(opf_root: ET.Element) -> str:
    for element in opf_root.iter():
        local = element.tag.rsplit("}", 1)[-1].lower()
        if local != "meta":
            continue
        name = str(element.attrib.get("name") or element.attrib.get("property") or "").strip().lower()
        if name == "cover":
            value = str(element.attrib.get("content") or "").strip()
            if value:
                return value
    return ""


def _zip_join(base: str, href: str) -> str:
    joined = posixpath.normpath(posixpath.join(posixpath.dirname(base), href))
    if not _safe_zip_member_name(joined):
        raise RuntimeError("epub_href_outside_archive")
    return joined


def _extract_epub_cover_image(
    *,
    zip_handle: zipfile.ZipFile,
    rootfile: str,
    opf_root: ET.Element,
    manifest: dict[str, dict[str, str]],
    target_dir: Path,
) -> tuple[str, str]:
    cover_id = _opf_cover_item_id(opf_root)
    cover_item: dict[str, str] = {}
    if cover_id and cover_id in manifest:
        cover_item = manifest[cover_id]
    if not cover_item:
        for item_id, item in manifest.items():
            media_type = str(item.get("media_type") or "").strip().lower()
            properties = str(item.get("properties") or "").strip().lower()
            href = str(item.get("href") or "").strip().lower()
            if media_type in _IMAGE_MEDIA_TYPES and (
                "cover-image" in properties
                or item_id.strip().lower() in {"cover", "cover_image", "cover-image"}
                or "cover" in Path(href).stem.lower()
            ):
                cover_item = item
                break
    media_type = str(cover_item.get("media_type") or "").strip().lower()
    href = str(cover_item.get("href") or "").strip()
    if not href or media_type not in _IMAGE_MEDIA_TYPES:
        return "", ""
    member = _zip_join(rootfile, href)
    try:
        payload = zip_handle.read(member)
    except Exception:
        return "", ""
    if not payload:
        return "", ""
    target_dir.mkdir(parents=True, exist_ok=True)
    extension = _IMAGE_MEDIA_TYPES.get(media_type) or Path(href).suffix.lower() or ".jpg"
    target = target_dir / f"cover{extension}"
    target.write_bytes(payload)
    return str(target), media_type


def _epub_content_filter_enabled() -> bool:
    return _env_bool("EA_AUDIOBOOK_EPUB_FILTER_NON_CONTENT", True)


def _normalize_filter_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\ufeff", " ").lower()).strip()


def _epub_filter_min_content_chars() -> int:
    return _env_int("EA_AUDIOBOOK_EPUB_MIN_CONTENT_CHARS", 240, minimum=0, maximum=5000)


def _epub_chapter_skip_reason(
    *,
    metadata_title: str,
    chapter_title: str,
    text: str,
    saw_promotional_tail: bool,
) -> str:
    if not _epub_content_filter_enabled():
        return ""
    normalized_title = _normalize_filter_text(chapter_title)
    normalized_book_title = _normalize_filter_text(metadata_title)
    normalized_text = _normalize_filter_text(text)
    char_count = len(text.strip())
    if not normalized_text:
        return "empty"
    if saw_promotional_tail:
        return "after_promotional_tail"
    if char_count <= 12 and normalized_title in {"cover", "umschlag", "titel", "title"}:
        return "cover_stub"
    legal_markers = (
        "urheberrechtlich geschützt",
        "technische sicherungsmaßnahmen",
        "unauthorized use",
        "all rights reserved",
        "copyright",
        "kopierschutz",
    )
    if any(marker in normalized_text for marker in legal_markers) and char_count < 2500:
        return "legal_notice"
    promotional_markers = (
        "weitere interessante titel",
        "haben sie lust gleich weiterzulesen",
        "auch im kösel-verlag erschienen",
        "auch im verlag erschienen",
        "zum newsletter anmelden",
        "buchentdecker-service",
        "bestellen sie unseren exklusiven newsletter",
        "neuerscheinungen, gewinnspiele",
    )
    if any(marker in normalized_text for marker in promotional_markers):
        return "promotional_tail"
    if char_count < _epub_filter_min_content_chars():
        if re.fullmatch(r"(teil|part)\s+[0-9ivxlcdm]+[:\s].*", normalized_text):
            return "part_title_stub"
        if normalized_text in {"anhang", "appendix"}:
            return "part_title_stub"
        if normalized_book_title and normalized_text.startswith(normalized_book_title):
            return "book_title_stub"
        if normalized_title in {"cover", "umschlag", "title", "titel"}:
            return "cover_stub"
    toc_markers = ("inhalt einleitung", "contents introduction", "inhaltsverzeichnis")
    if char_count < 5000 and any(marker in normalized_text for marker in toc_markers):
        heading_hits = len(re.findall(r"\b(teil|kapitel|chapter|einleitung|schluss|anhang)\b", normalized_text))
        if heading_hits >= 4:
            return "table_of_contents"
    return ""


def extract_epub_chapters(*, epub_path: Path, chapter_dir: Path, source_filename: str = "") -> tuple[EpubMetadata, tuple[EpubChapter, ...]]:
    chapter_dir.mkdir(parents=True, exist_ok=True)
    source_sha = _sha256_file(epub_path)
    chapters: list[EpubChapter] = []
    validate_epub_archive(epub_path)
    with zipfile.ZipFile(epub_path) as zip_handle:
        rootfile, opf_root = _read_opf(zip_handle)
        manifest, spine = _opf_manifest_and_spine(opf_root)
        title = _xml_text(opf_root, ("title",)) or Path(source_filename or epub_path.name).stem
        author = _xml_text(opf_root, ("creator",)) or ""
        language = _xml_text(opf_root, ("language",)) or str(os.getenv("EA_AUDIOBOOK_DEFAULT_LANGUAGE") or "en-US")
        cover_image_path, cover_media_type = _extract_epub_cover_image(
            zip_handle=zip_handle,
            rootfile=rootfile,
            opf_root=opf_root,
            manifest=manifest,
            target_dir=chapter_dir.parent / "assets",
        )
        saw_promotional_tail = False
        for idref in spine:
            item = manifest.get(idref) or {}
            href = str(item.get("href") or "").strip()
            media_type = str(item.get("media_type") or "").strip().lower()
            if not href or (media_type and media_type not in _HTML_MEDIA_TYPES):
                continue
            chapter_member = _zip_join(rootfile, href)
            try:
                payload = zip_handle.read(chapter_member)
            except KeyError:
                continue
            text = _html_to_text(payload)
            if not text:
                continue
            chapter_title = _html_title(payload) or Path(href).stem.replace("_", " ").replace("-", " ").title()
            skip_reason = _epub_chapter_skip_reason(
                metadata_title=title,
                chapter_title=chapter_title,
                text=text,
                saw_promotional_tail=saw_promotional_tail,
            )
            if skip_reason:
                if skip_reason == "promotional_tail":
                    saw_promotional_tail = True
                continue
            index = len(chapters) + 1
            safe_title = _safe_filename(chapter_title, fallback=f"Chapter {index:03d}")
            text_filename = f"{index:03d} - {safe_title}.txt"
            audio_filename = f"{index:03d} - {safe_title}.wav"
            text_path = chapter_dir / text_filename
            text_path.write_text(text + "\n", encoding="utf-8")
            chapters.append(
                EpubChapter(
                    index=index,
                    title=chapter_title,
                    source_href=chapter_member,
                    text_path=text_path.name,
                    audio_filename=audio_filename,
                    char_count=len(text),
                    sha256=_sha256_bytes(text.encode("utf-8")),
                )
            )
    if not chapters:
        raise RuntimeError("epub_no_readable_chapters")
    metadata = EpubMetadata(
        title=title,
        author=author,
        language=language,
        source_filename=source_filename or epub_path.name,
        source_sha256=source_sha,
        cover_image_path=cover_image_path,
        cover_media_type=cover_media_type,
    )
    return metadata, tuple(chapters)


def _load_voice_presets_from_value(value: object, *, source: str) -> tuple[VoicePreset, ...]:
    if not value:
        return ()
    if isinstance(value, dict):
        raw_rows = []
        for key, row in value.items():
            if isinstance(row, dict):
                raw_rows.append({"preset_key": key, **row})
    elif isinstance(value, list):
        raw_rows = [row for row in value if isinstance(row, dict)]
    else:
        return ()
    presets: list[VoicePreset] = []
    for index, row in enumerate(raw_rows, start=1):
        voice_id = str(row.get("voice_id") or row.get("id") or "").strip()
        if not voice_id:
            continue
        preset_key = _normalize_tag(row.get("preset_key") or row.get("key") or row.get("name") or f"voice_{index:02d}")
        label = str(row.get("label") or row.get("name") or preset_key or f"Voice {index}").strip()
        language = _normalize_language(row.get("language") or row.get("lang") or os.getenv("UNMIXR_LANGUAGE") or "en-US")
        supported_languages = _split_languages(
            row.get("supported_languages")
            or row.get("supported_locales")
            or row.get("other_languages")
            or row.get("languages")
            or language
        )
        tags = _split_tags(_row_tag_values(row))
        if not tags:
            tags = ("narration", "neutral")
        presets.append(
            VoicePreset(
                preset_key=preset_key or f"voice_{index:02d}",
                voice_id=voice_id,
                label=label,
                language=language,
                tags=tags,
                supported_languages=supported_languages,
                default=bool(row.get("default")),
                source=source,
            )
        )
    return tuple(presets)


def _split_languages(value: object) -> tuple[str, ...]:
    raw_items: list[object]
    if isinstance(value, dict):
        raw_items = list(value.keys())
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = re.split(r"[,; ]+", str(value or ""))
    seen: list[str] = []
    for item in raw_items:
        language = _normalize_language(item)
        if language and language not in seen:
            seen.append(language)
    return tuple(seen)


def _voice_discovery_cache_seconds() -> int:
    return _env_int("EA_AUDIOBOOK_VOICE_DISCOVERY_CACHE_SECONDS", 21600, minimum=0, maximum=86400)


def _voice_discovery_timeout_seconds() -> int:
    return _env_int("EA_AUDIOBOOK_VOICE_DISCOVERY_TIMEOUT_SECONDS", 15, minimum=3, maximum=60)


def _voice_discovery_providers() -> tuple[str, ...]:
    raw = str(os.getenv("EA_AUDIOBOOK_VOICE_DISCOVERY_PROVIDERS") or "unmixr").strip()
    providers = tuple(_normalize_tag(part) for part in re.split(r"[,;]+", raw) if _normalize_tag(part))
    return providers or ("unmixr",)


def _unmixr_voice_discovery_use_cases() -> tuple[str, ...]:
    raw = str(
        os.getenv("EA_AUDIOBOOK_UNMIXR_VOICE_DISCOVERY_USE_CASES")
        or "audiobook-voices,uc:general,narration-voices,documentary-voices,podcast-voices,all"
    ).strip()
    values = tuple(part.strip() for part in re.split(r"[,;]+", raw) if part.strip())
    return values or ("audiobook-voices",)


def _unmixr_voice_discovery_specs() -> tuple[tuple[str, str, str], ...]:
    specs: list[tuple[str, str, str]] = []
    default_filter = _unmixr_voice_discovery_filter_param()
    for raw_value in _unmixr_voice_discovery_use_cases():
        value = str(raw_value or "").strip()
        if not value:
            continue
        normalized = value.strip().lower()
        if normalized in {"all", "*", "unfiltered"}:
            specs.append(("", "", "all"))
            continue
        filter_param = default_filter
        filter_value = value
        explicit_filter = False
        if ":" in value:
            prefix, suffix = value.split(":", 1)
            prefix = _normalize_tag(prefix)
            if prefix in {"c", "uc"} and suffix.strip():
                filter_param = prefix
                filter_value = suffix.strip()
                explicit_filter = True
        elif "=" in value:
            prefix, suffix = value.split("=", 1)
            prefix = _normalize_tag(prefix)
            if prefix in {"c", "uc"} and suffix.strip():
                filter_param = prefix
                filter_value = suffix.strip()
                explicit_filter = True
        label = f"{filter_param}:{filter_value}" if explicit_filter and filter_param else filter_value
        specs.append((filter_param, filter_value, label))
    return tuple(specs) or (("c", "audiobook-voices", "c:audiobook-voices"),)


def _voice_discovery_key(*, provider: str, target_count: int) -> str:
    if provider == "unmixr":
        use_cases = ",".join(spec[2] for spec in _unmixr_voice_discovery_specs())
        return f"{provider}|{target_count}|{use_cases}"
    return f"{provider}|{target_count}"


def _cached_voice_discovery(key: str) -> tuple[VoicePreset, ...] | None:
    cached = _VOICE_DISCOVERY_CACHE.get(key)
    if not cached:
        return None
    cached_at, presets = cached
    ttl = _voice_discovery_cache_seconds()
    if ttl <= 0 or time.time() - cached_at > ttl:
        _VOICE_DISCOVERY_CACHE.pop(key, None)
        return None
    return presets


def _store_voice_discovery_cache(key: str, presets: tuple[VoicePreset, ...]) -> tuple[VoicePreset, ...]:
    _VOICE_DISCOVERY_CACHE[key] = (time.time(), presets)
    return presets


def _fetch_json_url(*, url: str, api_key: str, timeout_seconds: int) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        payload = response.read()
    parsed = json.loads(payload.decode("utf-8"))
    return parsed if isinstance(parsed, dict) else {}


def _unmixr_voice_discovery_fields() -> str:
    return str(
        os.getenv("EA_AUDIOBOOK_UNMIXR_VOICE_DISCOVERY_FIELDS")
        or "uuid,character,gender,language,quality,capabilities,roles,use_cases,other_languages,supported_locales,is_available,is_multilingual,description,age,personality,wpm"
    ).strip()


def _unmixr_voice_discovery_filter_param() -> str:
    value = _normalize_tag(os.getenv("EA_AUDIOBOOK_UNMIXR_VOICE_DISCOVERY_FILTER_PARAM") or "c")
    return value if value in {"c", "uc"} else "c"


def _unmixr_voice_list_url(*, filter_param: str, filter_value: str, page_size: int) -> str:
    query = {
        "page_size": str(page_size),
        "fields": _unmixr_voice_discovery_fields(),
    }
    if filter_param and filter_value:
        query[filter_param] = filter_value
    return "https://unmixr.com/api/v1/voice-list/?" + urllib.parse.urlencode(query)


def _unmixr_voice_row_tags(row: dict[str, object], *, use_case: str) -> tuple[str, ...]:
    normalized_use_case = _normalize_tag(use_case)
    values: list[object] = [use_case]
    if any(term in normalized_use_case for term in ("audiobook", "narration", "documentary", "podcast")):
        values.extend(["audiobook", "narration"])
    for key in ("gender", "quality", "age", "capabilities", "roles", "use_cases", "personality"):
        value = row.get(key)
        if isinstance(value, (list, tuple, set)):
            values.extend(value)
        elif value:
            values.extend(re.split(r"[,; ]+", str(value)))
    description = str(row.get("description") or "").lower()
    for tag, needles in {
        "warm": ("warm", "approachable", "friendly"),
        "calm": ("calm", "soothing", "gentle"),
        "clear": ("clear", "crisp", "precise"),
        "expressive": ("expressive", "emotional", "dramatic"),
        "storytelling": ("storytelling", "story", "audiobook"),
        "professional": ("professional", "corporate", "formal"),
        "documentary": ("documentary",),
        "podcast": ("podcast",),
    }.items():
        if any(needle in description for needle in needles):
            values.append(tag)
    return _split_tags(values)


def _voice_preset_from_unmixr_row(row: dict[str, object], *, use_case: str, index: int) -> VoicePreset | None:
    if row.get("is_available") is False:
        return None
    voice_id = str(row.get("uuid") or row.get("voice_id") or row.get("id") or "").strip()
    if not voice_id:
        return None
    label = str(row.get("character") or row.get("label") or row.get("name") or f"Audio Voice {index}").strip()
    base_key = _normalize_tag(label) or f"voice_{index:02d}"
    preset_key = f"unmixr_{base_key}_{voice_id[:8].lower()}"
    language = _normalize_language(row.get("language") or os.getenv("UNMIXR_LANGUAGE") or "en-US")
    supported_languages = _split_languages(row.get("supported_locales") or row.get("other_languages") or language)
    if language and language not in supported_languages:
        supported_languages = (language, *supported_languages)
    tags = _unmixr_voice_row_tags(row, use_case=use_case)
    return VoicePreset(
        preset_key=preset_key,
        voice_id=voice_id,
        label=label,
        language=language,
        tags=tags or ("audiobook", "narration"),
        supported_languages=supported_languages,
        default=False,
        source=f"discovery:unmixr:{use_case}",
    )


def _discover_unmixr_voice_presets(*, target_count: int) -> tuple[VoicePreset, ...]:
    api_key = unmixr_api_key()
    if not api_key:
        return ()
    key = _voice_discovery_key(provider="unmixr", target_count=target_count)
    cached = _cached_voice_discovery(key)
    if cached is not None:
        return cached
    timeout_seconds = _voice_discovery_timeout_seconds()
    specs = _unmixr_voice_discovery_specs()
    page_size = min(max(target_count, 100), 100)
    rows: list[VoicePreset] = []
    encountered_fetch_error = False
    seen_voice_ids: set[str] = set()
    for filter_param, filter_value, source_label in specs:
        url = _unmixr_voice_list_url(filter_param=filter_param, filter_value=filter_value, page_size=page_size)
        try:
            payload = _fetch_json_url(url=url, api_key=api_key, timeout_seconds=timeout_seconds)
        except Exception:
            encountered_fetch_error = True
            continue
        for raw_row in list(payload.get("results") or []):
            if not isinstance(raw_row, dict):
                continue
            preset = _voice_preset_from_unmixr_row(raw_row, use_case=source_label, index=len(rows) + 1)
            if preset is None or preset.voice_id in seen_voice_ids:
                continue
            seen_voice_ids.add(preset.voice_id)
            rows.append(preset)
    if encountered_fetch_error and len(rows) < target_count:
        return tuple(rows)
    return _store_voice_discovery_cache(key, tuple(rows))


def _refresh_discovery_forced() -> None:
    _VOICE_DISCOVERY_CACHE.clear()


def discover_audiobook_voice_presets(*, target_count: int | None = None) -> tuple[VoicePreset, ...]:
    if not audiobook_voice_discovery_enabled():
        return ()
    target = _coerce_voice_discovery_target_count(requested_count=target_count or audiobook_voice_discovery_target_count())
    rows: list[VoicePreset] = []
    seen_voice_ids: set[str] = set()
    for provider in _voice_discovery_providers():
        if provider != "unmixr":
            continue
        for preset in _discover_unmixr_voice_presets(target_count=target):
            if preset.voice_id in seen_voice_ids:
                continue
            seen_voice_ids.add(preset.voice_id)
            rows.append(preset)
    return tuple(rows)


def _augment_voice_presets_with_discovery(presets: tuple[VoicePreset, ...], *, target_count: int | None = None) -> tuple[VoicePreset, ...]:
    if not presets or not audiobook_voice_discovery_enabled():
        return presets
    target = _coerce_voice_discovery_target_count(requested_count=target_count or audiobook_voice_discovery_target_count())
    if len({preset.voice_id for preset in presets}) >= target:
        return presets
    rows: list[VoicePreset] = []
    seen_voice_ids: set[str] = set()
    for preset in (*presets, *discover_audiobook_voice_presets(target_count=target)):
        if preset.voice_id in seen_voice_ids:
            continue
        seen_voice_ids.add(preset.voice_id)
        rows.append(preset)
    return tuple(rows)


def load_unmixr_voice_presets(*, target_count: int | None = None) -> tuple[VoicePreset, ...]:
    raw_path = str(os.getenv("EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_PATH") or "").strip()
    if raw_path:
        path = Path(raw_path).expanduser()
        if path.is_file():
            try:
                presets = _load_voice_presets_from_value(json.loads(path.read_text(encoding="utf-8")), source=f"file:{path}")
                return _augment_voice_presets_with_discovery(
                    presets,
                    target_count=target_count or audiobook_voice_discovery_target_count(),
                )
            except Exception:
                return ()
    raw_json = str(os.getenv("EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON") or "").strip()
    if raw_json:
        try:
            presets = _load_voice_presets_from_value(json.loads(raw_json), source="env:EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON")
            if presets:
                return _augment_voice_presets_with_discovery(
                    presets,
                    target_count=target_count or audiobook_voice_discovery_target_count(),
                )
        except Exception:
            return ()
    discovered = discover_audiobook_voice_presets(target_count=target_count or audiobook_voice_discovery_target_count())
    if discovered:
        default_voice_id = unmixr_memorial_voice_id()
        if default_voice_id and all(preset.voice_id != default_voice_id for preset in discovered):
            default_tags = _split_tags(os.getenv("EA_AUDIOBOOK_DEFAULT_VOICE_TAGS") or "narration,neutral,general")
            discovered = (
                VoicePreset(
                    preset_key="default_env_voice",
                    voice_id=default_voice_id,
                    label=str(os.getenv("EA_AUDIOBOOK_DEFAULT_VOICE_LABEL") or "Configured audio voice").strip(),
                    language=_audiobook_voice_language_from_tags(default_tags),
                    tags=default_tags,
                    supported_languages=(_audiobook_voice_language_from_tags(default_tags),),
                    default=True,
                    source="env:UNMIXR_VOICE_ID",
                ),
                *discovered,
            )
        return discovered
    default_voice_id = unmixr_memorial_voice_id()
    if not default_voice_id:
        return ()
    default_tags = _split_tags(os.getenv("EA_AUDIOBOOK_DEFAULT_VOICE_TAGS") or "narration,neutral,general")
    default_language = _audiobook_voice_language_from_tags(default_tags)
    return (
        VoicePreset(
            preset_key="default_env_voice",
            voice_id=default_voice_id,
            label=str(os.getenv("EA_AUDIOBOOK_DEFAULT_VOICE_LABEL") or "Configured audio voice").strip(),
            language=default_language,
            tags=default_tags,
            supported_languages=(default_language,),
            default=True,
            source="env:UNMIXR_VOICE_ID",
        ),
    )


def _book_sample_text(*, job_dir: Path, chapters: tuple[EpubChapter, ...], max_chars: int = 24000) -> str:
    parts: list[str] = []
    remaining = max_chars
    for chapter in chapters:
        path = job_dir / "chapters" / chapter.text_path
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        if not text:
            continue
        parts.append(text[:remaining])
        remaining -= len(parts[-1])
        if remaining <= 0:
            break
    return "\n\n".join(parts).strip()


def _book_topic_from_profile(*, signal_scores: dict[str, int], fiction_score: int, nonfiction_score: int, tags: list[str]) -> str:
    tag_set = {str(tag or "").strip().lower() for tag in tags}
    if "technical" in tag_set:
        return "technical nonfiction"
    if "memoir" in tag_set:
        return "memoir / biography"
    if "children" in tag_set:
        return "children / young reader"
    if "thriller" in tag_set:
        return "thriller / crime"
    if "romance" in tag_set:
        return "romance"
    if fiction_score > nonfiction_score:
        return "fiction with dialogue" if "dialogue" in tag_set else "fiction"
    return "nonfiction / guidance"


def _infer_author_gender(author: str) -> str:
    raw_author = str(author or "").strip()
    if "," in raw_author:
        parts = [part.strip() for part in raw_author.split(",") if part.strip()]
        if len(parts) >= 2:
            raw_author = f"{parts[1]} {parts[0]}"
    normalized = " ".join(raw_author.replace(",", " ").split()).strip()
    if not normalized:
        return ""
    first = re.sub(r"[^A-Za-zÀ-ÿ-]+", "", normalized.split()[0]).strip("-").lower()
    if len(first) <= 1:
        return ""
    female_names = {
        "alice",
        "anna",
        "anne",
        "barbara",
        "bettina",
        "birgit",
        "brigitte",
        "christine",
        "claudia",
        "diana",
        "elisabeth",
        "eva",
        "franziska",
        "helga",
        "julia",
        "katharina",
        "laura",
        "lisa",
        "maria",
        "marie",
        "nicole",
        "sandra",
        "sarah",
        "sabine",
        "susanne",
    }
    male_names = {
        "andreas",
        "alexander",
        "bernd",
        "christian",
        "daniel",
        "david",
        "florian",
        "frank",
        "georg",
        "hans",
        "johannes",
        "josef",
        "karl",
        "markus",
        "martin",
        "max",
        "michael",
        "peter",
        "stefan",
        "thomas",
        "tobias",
        "wolfgang",
    }
    if first in female_names:
        return "female"
    if first in male_names:
        return "male"
    return ""


def profile_book_for_voice(*, metadata: EpubMetadata, chapters: tuple[EpubChapter, ...], job_dir: Path) -> dict[str, object]:
    sample = _book_sample_text(job_dir=job_dir, chapters=chapters)
    lower = f"{metadata.title}\n{sample}".lower()
    words = re.findall(r"[a-zA-ZÀ-ÿ0-9']+", sample)
    word_count = len(words)
    quote_count = lower.count('"') + lower.count("“") + lower.count("”") + lower.count("»") + lower.count("«")
    dialogue_markers = sum(lower.count(marker) for marker in (" said ", " replied ", " asked ", " whispered ", " cried ", " sagte ", " fragte ", " antwortete "))
    dialogue_ratio = min(1.0, (quote_count / max(word_count, 1)) * 8.0 + (dialogue_markers / max(word_count, 1)) * 35.0)
    keyword_groups = {
        "nonfiction": ("guide", "introduction", "principle", "strategy", "business", "science", "history", "manual", "essay", "framework", "chapter"),
        "technical": ("api", "code", "algorithm", "system", "data", "architecture", "configuration", "workflow", "implementation"),
        "memoir": ("memoir", "autobiography", "my life", "erinnerung", "biography"),
        "fiction": ("novel", "prologue", "epilogue", "chapter one", "said", "replied", "asked"),
        "thriller": ("murder", "crime", "detective", "danger", "escape", "secret", "shadow"),
        "children": ("children", "young reader", "bedtime", "fairy", "school"),
        "romance": ("love", "heart", "kiss", "romance"),
        "german": (" der ", " die ", " und ", " nicht ", " ich ", " sie "),
    }
    signal_scores: dict[str, int] = {}
    for key, needles in keyword_groups.items():
        signal_scores[key] = sum(1 for needle in needles if needle in lower)
    fiction_score = signal_scores["fiction"] + int(dialogue_ratio >= 0.12) * 2
    nonfiction_score = signal_scores["nonfiction"] + signal_scores["technical"] + signal_scores["memoir"]
    tags: list[str] = []
    if fiction_score > nonfiction_score:
        tags.append("fiction")
    else:
        tags.append("nonfiction")
    if dialogue_ratio >= 0.10:
        tags.extend(("dialogue", "expressive"))
    if signal_scores["technical"] >= 2:
        tags.extend(("technical", "clear"))
    if signal_scores["memoir"]:
        tags.extend(("memoir", "warm"))
    for key in ("thriller", "children", "romance"):
        if signal_scores[key]:
            tags.append(key)
    if _normalize_language(metadata.language).startswith("de") or signal_scores["german"] >= 3:
        tags.append("german")
    topic = _book_topic_from_profile(
        signal_scores=signal_scores,
        fiction_score=fiction_score,
        nonfiction_score=nonfiction_score,
        tags=tags,
    )
    return {
        "language": metadata.language,
        "title": metadata.title,
        "author": metadata.author,
        "author_gender_signal": _infer_author_gender(metadata.author),
        "topic": topic,
        "word_count_sampled": word_count,
        "chapter_count": len(chapters),
        "dialogue_ratio": round(dialogue_ratio, 4),
        "fiction_score": fiction_score,
        "nonfiction_score": nonfiction_score,
        "signal_scores": signal_scores,
        "recommended_tags": tuple(dict.fromkeys(tags)),
        "sample_sha256": _sha256_bytes(sample.encode("utf-8")) if sample else "",
    }


def _public_book_profile(profile: dict[str, object]) -> dict[str, object]:
    return {
        "language": profile.get("language"),
        "topic": profile.get("topic"),
        "author_gender_signal": profile.get("author_gender_signal", ""),
        "dialogue_ratio": profile.get("dialogue_ratio"),
        "fiction_score": profile.get("fiction_score"),
        "nonfiction_score": profile.get("nonfiction_score"),
        "recommended_tags": list(profile.get("recommended_tags") or []),
        "sample_sha256": profile.get("sample_sha256"),
    }


def _backfill_voice_selection_book_profile(
    *,
    voice_selection: dict[str, object],
    metadata: EpubMetadata,
    chapters: tuple[EpubChapter, ...],
    job_dir: Path,
) -> tuple[dict[str, object], bool]:
    normalized_selection = dict(voice_selection or {})
    existing_profile = dict(normalized_selection.get("book_profile") or {})
    fresh_profile = _public_book_profile(profile_book_for_voice(metadata=metadata, chapters=chapters, job_dir=job_dir))
    merged_profile = dict(existing_profile)
    changed = False
    for key, value in fresh_profile.items():
        current_value = merged_profile.get(key)
        if key == "recommended_tags":
            if not list(current_value or []) and list(value or []):
                merged_profile[key] = list(value or [])
                changed = True
            continue
        if current_value in (None, "") and value not in (None, ""):
            merged_profile[key] = value
            changed = True
    if changed:
        normalized_selection["book_profile"] = merged_profile
    return normalized_selection, changed


def _select_author_gender_preferred_candidate(
    candidate_rows: list[dict[str, object]],
    *,
    author_gender_signal: str,
) -> tuple[dict[str, object], bool]:
    if not candidate_rows:
        return {}, False

    def _first_match(*, require_author_gender_match: bool, require_language_match: bool) -> dict[str, object]:
        for row in candidate_rows:
            if require_author_gender_match and not bool(row.get("author_gender_match")):
                continue
            if require_language_match and not bool(row.get("language_match")):
                continue
            return dict(row)
        return {}

    normalized_author_gender_signal = str(author_gender_signal or "").strip().lower()
    if normalized_author_gender_signal:
        selected = _first_match(require_author_gender_match=True, require_language_match=True)
        if selected:
            return selected, True
        selected = _first_match(require_author_gender_match=True, require_language_match=False)
        if selected:
            return selected, True
    selected = _first_match(require_author_gender_match=False, require_language_match=True)
    if selected:
        return selected, False
    return dict(candidate_rows[0]), False


def _voice_language_score(book_language: str, voice_language: str, supported_languages: tuple[str, ...] = ()) -> int:
    book = _normalize_language(book_language)
    voice = _normalize_language(voice_language)
    supported = tuple(_normalize_language(item) for item in supported_languages if _normalize_language(item))
    if not book or (not voice and not supported):
        return 0
    if book == voice:
        return 35
    if book in supported:
        return 34
    if book.split("-", 1)[0] == voice.split("-", 1)[0]:
        return 24
    for language in supported:
        if book.split("-", 1)[0] == language.split("-", 1)[0]:
            return 24
    return -20


def _voice_language_matches(book_language: str, voice_language: str, supported_languages: tuple[str, ...] = ()) -> bool:
    return _voice_language_score(book_language, voice_language, supported_languages) >= 24


def _selected_voice_language_mismatch(*, metadata: EpubMetadata, voice_selection: dict[str, object]) -> dict[str, object]:
    if _env_bool("EA_AUDIOBOOK_ALLOW_VOICE_LANGUAGE_MISMATCH", False):
        return {}
    public = dict(voice_selection.get("public") or {})
    selected = dict(public.get("selected") or {})
    if not selected:
        selected = dict(public)
    if (
        bool(voice_selection.get("voice_language_override_by_user"))
        or bool(public.get("voice_language_override_by_user"))
        or bool(selected.get("voice_language_override_by_user"))
    ):
        return {}
    book_language = _normalize_language(metadata.language)
    voice_language = _normalize_language(selected.get("language"))
    supported_languages = _split_languages(selected.get("supported_languages") or voice_language)
    if not book_language or (not voice_language and not supported_languages):
        return {}
    if _voice_language_matches(book_language, voice_language, supported_languages):
        return {}
    return {
        "book_language": book_language,
        "voice_language": voice_language,
        "supported_languages": list(supported_languages[:20]),
        "selected_label_sha256": _sha256_bytes(str(selected.get("label") or "").encode("utf-8"))
        if str(selected.get("label") or "").strip()
        else "",
        "selected_voice_id_sha256": str(selected.get("voice_id_sha256") or "").strip(),
    }


def _voice_feedback_key(*, preset_key: object, voice_id_sha256: object, label: object = "") -> str:
    voice_hash = str(voice_id_sha256 or "").strip()
    if voice_hash:
        return f"voice:{voice_hash}"
    preset = _normalize_tag(preset_key)
    if preset:
        return f"preset:{preset}"
    label_hash = _sha256_bytes(str(label or "").strip().encode("utf-8"))
    return f"label:{label_hash}" if label_hash else ""


def _load_audiobook_voice_feedback() -> dict[str, object]:
    path = audiobook_voice_feedback_path()
    if not path.is_file():
        return {"contract_name": VOICE_FEEDBACK_CONTRACT_NAME, "voices": {}, "books": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"contract_name": VOICE_FEEDBACK_CONTRACT_NAME, "voices": {}, "books": {}}
    if not isinstance(payload, dict):
        return {"contract_name": VOICE_FEEDBACK_CONTRACT_NAME, "voices": {}, "books": {}}
    payload.setdefault("contract_name", VOICE_FEEDBACK_CONTRACT_NAME)
    payload.setdefault("voices", {})
    payload.setdefault("books", {})
    return payload


def _write_audiobook_voice_feedback(payload: dict[str, object]) -> None:
    path = audiobook_voice_feedback_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload["contract_name"] = VOICE_FEEDBACK_CONTRACT_NAME
    payload["updated_at"] = _now_iso()
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _source_feedback_key(job: dict[str, object] | None = None, metadata: EpubMetadata | None = None) -> str:
    job = job or {}
    source = dict(job.get("source") or {})
    metadata_payload = dict(job.get("metadata") or {})
    raw = (
        str(source.get("source_sha256") or "").strip()
        or str(metadata_payload.get("source_sha256") or "").strip()
        or (metadata.source_sha256 if metadata is not None else "")
    )
    if raw:
        return _sha256_bytes(str(raw).encode("utf-8"))
    if metadata is not None:
        title = str(metadata.title or "").strip().lower()
        author = str(metadata.author or "").strip().lower()
    else:
        title = str(metadata_payload.get("title") or "").strip().lower()
        author = str(metadata_payload.get("author") or "").strip().lower()
    return _sha256_bytes(f"{title}|{author}".encode("utf-8")) if title or author else ""


def _audiobook_voice_feedback_adjustment(
    *,
    preset_key: object,
    voice_id_sha256: object,
    label: object = "",
    source_key: str = "",
) -> dict[str, object]:
    payload = _load_audiobook_voice_feedback()
    key = _voice_feedback_key(preset_key=preset_key, voice_id_sha256=voice_id_sha256, label=label)
    voice = dict(dict(payload.get("voices") or {}).get(key) or {}) if key else {}
    selected_count = int(voice.get("selected_count") or 0)
    dismissed_count = int(voice.get("dismissed_count") or 0)
    global_adjustment = max(-60, min(60, selected_count * 8 - dismissed_count * 5))
    same_book_adjustment = 0
    same_book_selected = False
    if source_key and key:
        book = dict(dict(payload.get("books") or {}).get(source_key) or {})
        same_book_selected = str(book.get("selected_voice_key") or "").strip() == key and bool(
            book.get("completed_audiobook_ready")
        )
        if same_book_selected:
            same_book_adjustment = 120
    return {
        "voice_feedback_key": key,
        "voice_feedback_selected_count": selected_count,
        "voice_feedback_dismissed_count": dismissed_count,
        "voice_feedback_adjustment": global_adjustment,
        "same_book_voice_reuse": same_book_selected,
        "same_book_voice_adjustment": same_book_adjustment,
        "voice_feedback_total_adjustment": global_adjustment + same_book_adjustment,
    }


def record_audiobook_voice_feedback(
    *,
    job: dict[str, object],
    candidate: dict[str, object],
    action: str,
) -> dict[str, object]:
    public = dict(candidate.get("public") or candidate)
    key = _voice_feedback_key(
        preset_key=public.get("preset_key") or candidate.get("candidate_key"),
        voice_id_sha256=public.get("voice_id_sha256") or candidate.get("voice_id_sha256"),
        label=public.get("label"),
    )
    if not key:
        return {}
    normalized_action = _normalize_tag(action)
    payload = _load_audiobook_voice_feedback()
    voices = dict(payload.get("voices") or {})
    row = dict(voices.get(key) or {})
    row.setdefault("voice_id_sha256", str(public.get("voice_id_sha256") or candidate.get("voice_id_sha256") or "").strip())
    row.setdefault("preset_key", str(public.get("preset_key") or candidate.get("candidate_key") or "").strip())
    if str(public.get("label") or "").strip():
        row["label_sha256"] = _sha256_bytes(str(public.get("label") or "").strip().encode("utf-8"))
    if normalized_action in {"use", "select", "use_this", "selected"}:
        row["selected_count"] = int(row.get("selected_count") or 0) + 1
        row["last_selected_at"] = _now_iso()
    elif normalized_action in {"dismiss", "reject", "dismiss_all"}:
        row["dismissed_count"] = int(row.get("dismissed_count") or 0) + 1
        row["last_dismissed_at"] = _now_iso()
    else:
        return {}
    row["raw_voice_id_exposed"] = False
    voices[key] = row
    payload["voices"] = voices
    if normalized_action in {"use", "select", "use_this", "selected"}:
        source_key = _source_feedback_key(job=job)
        if source_key:
            books = dict(payload.get("books") or {})
            books[source_key] = {
                "source_sha256_sha256": source_key,
                "selected_voice_key": key,
                "selected_at": _now_iso(),
                "completed_audiobook_ready": str(job.get("status") or "").strip() == "audiobookshelf_imported",
                "raw_source_sha_exposed": False,
            }
            payload["books"] = books
    _write_audiobook_voice_feedback(payload)
    return {
        "status": "recorded",
        "action": normalized_action,
        "voice_feedback_key_sha256": _sha256_bytes(key.encode("utf-8")),
        "raw_voice_id_exposed": False,
        "raw_source_sha_exposed": False,
    }


def record_audiobook_completed_voice_feedback(job: dict[str, object]) -> None:
    provider = dict(job.get("provider") or {})
    voice_selection = dict(provider.get("voice_selection") or {})
    selected = dict(voice_selection.get("selected") or {})
    candidate_key = str(voice_selection.get("selected_candidate_key") or selected.get("preset_key") or "").strip()
    if not selected and not candidate_key:
        return
    source_key = _source_feedback_key(job=job)
    feedback_key = _voice_feedback_key(
        preset_key=candidate_key or selected.get("preset_key"),
        voice_id_sha256=selected.get("voice_id_sha256"),
        label=selected.get("label"),
    )
    if not source_key or not feedback_key:
        return
    payload = _load_audiobook_voice_feedback()
    books = dict(payload.get("books") or {})
    book = dict(books.get(source_key) or {})
    book.update(
        {
            "source_sha256_sha256": source_key,
            "selected_voice_key": feedback_key,
            "completed_audiobook_ready": True,
            "completed_at": _now_iso(),
            "raw_source_sha_exposed": False,
        }
    )
    books[source_key] = book
    payload["books"] = books
    _write_audiobook_voice_feedback(payload)


def _ranked_unmixr_voice_candidates(
    *,
    metadata: EpubMetadata,
    chapters: tuple[EpubChapter, ...],
    job_dir: Path,
    target_count: int | None = None,
) -> dict[str, object]:
    presets = load_unmixr_voice_presets(target_count=target_count or audiobook_voice_discovery_target_count())
    if not presets:
        return {
            "status": "blocked",
            "reason": "unmixr_voice_catalog_missing",
            "voice_id": "",
            "public": {
                "status": "blocked",
                "reason": "unmixr_voice_catalog_missing",
                "strategy": "book_profile_voice_selection",
            },
        }
    profile = profile_book_for_voice(metadata=metadata, chapters=chapters, job_dir=job_dir)
    desired_tags = set(str(item) for item in profile.get("recommended_tags") or ())
    author_gender_signal = str(profile.get("author_gender_signal") or "").strip().lower()
    blocklist_terms = _voice_blocklist_terms()
    source_key = _source_feedback_key(metadata=metadata)
    candidate_rows: list[dict[str, object]] = []
    for preset in presets:
        tags = set(preset.tags)
        tag_overlap = sorted(desired_tags.intersection(tags))
        language_score = _voice_language_score(str(profile.get("language") or ""), preset.language, preset.supported_languages)
        language_match = _voice_language_matches(
            str(profile.get("language") or ""),
            preset.language,
            preset.supported_languages,
        )
        score = language_score
        score += 8 if "narration" in tags or "audiobook" in tags else 0
        score += 6 * len(tag_overlap)
        if "nonfiction" in desired_tags and tags.intersection({"clear", "calm", "professional", "neutral"}):
            score += 8
        if "fiction" in desired_tags and tags.intersection({"expressive", "warm", "storytelling", "dramatic"}):
            score += 8
        if "dialogue" in desired_tags and tags.intersection({"expressive", "dialogue", "character"}):
            score += 8
        if "technical" in desired_tags and tags.intersection({"clear", "precise", "professional"}):
            score += 8
        if author_gender_signal and author_gender_signal in tags:
            score += 10
        if preset.default:
            score += 2
        voice_search_blob = _normalize_tag(" ".join((preset.preset_key, preset.label, " ".join(preset.tags))))
        blocked_by_user = any(term and term in voice_search_blob for term in blocklist_terms)
        if blocked_by_user:
            score -= 1000
        voice_hash = _sha256_bytes(preset.voice_id.encode("utf-8"))
        feedback = _audiobook_voice_feedback_adjustment(
            preset_key=preset.preset_key,
            voice_id_sha256=voice_hash,
            label=preset.label,
            source_key=source_key,
        )
        score += int(feedback.get("voice_feedback_total_adjustment") or 0)
        candidate_rows.append(
            {
                "preset_key": preset.preset_key,
                "label": preset.label,
                "language": preset.language,
                "supported_languages": list(preset.supported_languages[:20]),
                "language_match": language_match,
                "language_score": language_score,
                "tags": list(preset.tags),
                "score": score,
                "matched_tags": tag_overlap,
                "author_gender_match": bool(author_gender_signal and author_gender_signal in tags),
                "default": preset.default,
                "blocked_by_user": blocked_by_user,
                "voice_id_sha256": voice_hash,
                "voice_feedback_adjustment": int(feedback.get("voice_feedback_adjustment") or 0),
                "voice_feedback_selected_count": int(feedback.get("voice_feedback_selected_count") or 0),
                "voice_feedback_dismissed_count": int(feedback.get("voice_feedback_dismissed_count") or 0),
                "same_book_voice_reuse": bool(feedback.get("same_book_voice_reuse")),
                "same_book_voice_adjustment": int(feedback.get("same_book_voice_adjustment") or 0),
                "_voice_id": preset.voice_id,
            }
        )
    candidate_rows.sort(
        key=lambda row: (bool(row.get("language_match")), int(row["score"]), bool(row["default"])),
        reverse=True,
    )
    return {
        "status": "ranked",
        "profile": profile,
        "candidate_rows": candidate_rows,
        "candidate_count": len(candidate_rows),
    }


def select_unmixr_voice_for_book(
    *,
    metadata: EpubMetadata,
    chapters: tuple[EpubChapter, ...],
    job_dir: Path,
) -> dict[str, object]:
    ranking = _ranked_unmixr_voice_candidates(metadata=metadata, chapters=chapters, job_dir=job_dir)
    if str(ranking.get("status") or "") == "blocked":
        return ranking
    candidate_rows = [dict(row) for row in list(ranking.get("candidate_rows") or []) if isinstance(row, dict)]
    if not candidate_rows:
        return {
            "status": "blocked",
            "reason": "unmixr_voice_catalog_missing",
            "voice_id": "",
            "public": {
                "status": "blocked",
                "reason": "unmixr_voice_catalog_missing",
                "strategy": "book_profile_voice_selection",
            },
        }
    profile = dict(ranking.get("profile") or {})
    selected, author_gender_preference_used = _select_author_gender_preferred_candidate(
        candidate_rows,
        author_gender_signal=str(profile.get("author_gender_signal") or ""),
    )
    if not selected:
        selected = dict(candidate_rows[0])
        author_gender_preference_used = False
    voice_id = str(selected.pop("_voice_id") or "")
    for row in candidate_rows:
        row.pop("_voice_id", None)
    public = {
        "status": "selected" if len(candidate_rows) > 1 else "single_configured_voice",
        "strategy": "book_profile_voice_selection",
        "author_gender_preference_used": author_gender_preference_used,
        "selected": selected,
        "book_profile": _public_book_profile(profile),
        "candidate_count": len(candidate_rows),
        "candidate_scores": candidate_rows[:8],
    }
    return {"status": "selected", "voice_id": voice_id, "public": public}


def _voice_audition_dir(job_dir: Path) -> Path:
    return job_dir / "voice_audition"


def _voice_audition_private_path(job_dir: Path) -> Path:
    return _voice_audition_dir(job_dir) / "private.json"


def _load_voice_audition_private(job_dir: Path) -> dict[str, object]:
    path = _voice_audition_private_path(job_dir)
    if not path.is_file():
        return {"contract_name": VOICE_AUDITION_CONTRACT_NAME, "candidates": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"contract_name": VOICE_AUDITION_CONTRACT_NAME, "candidates": {}}
    if not isinstance(payload, dict):
        return {"contract_name": VOICE_AUDITION_CONTRACT_NAME, "candidates": {}}
    payload.setdefault("contract_name", VOICE_AUDITION_CONTRACT_NAME)
    payload.setdefault("candidates", {})
    return payload


def _write_voice_audition_private(job_dir: Path, payload: dict[str, object]) -> None:
    path = _voice_audition_private_path(job_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _voice_audition_token(*, job_id: str, preset_key: str, voice_id_sha256: str) -> str:
    return hashlib.sha256(f"{job_id}|{preset_key}|{voice_id_sha256}".encode("utf-8")).hexdigest()[:14]


def _voice_sample_text(*, job_dir: Path, chapters: tuple[EpubChapter, ...]) -> str:
    text = _book_sample_text(
        job_dir=job_dir,
        chapters=chapters,
        max_chars=_env_int("EA_AUDIOBOOK_VOICE_SAMPLE_SOURCE_CHARS", 900, minimum=120, maximum=8000),
    )
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized:
        return ""
    sentences = [part.strip() for part in re.split(r"(?<=[.!?。！？])\s+", normalized) if part.strip()]
    sample = " ".join(sentences[:2]).strip() if sentences else normalized
    max_chars = _env_int("EA_AUDIOBOOK_VOICE_SAMPLE_MAX_CHARS", 240, minimum=60, maximum=1200)
    if len(sample) > max_chars:
        sample = sample[:max_chars].rsplit(" ", 1)[0].strip() or sample[:max_chars].strip()
    return sample


def _safe_public_voice_candidate(row: dict[str, object], *, token: str, sample_path: Path | None = None) -> dict[str, object]:
    public = {key: value for key, value in dict(row).items() if key != "_voice_id"}
    public["callback_token"] = token
    if sample_path is not None:
        public["sample_file"] = sample_path.name
        public["sample_sha256"] = _sha256_file(sample_path) if sample_path.is_file() else ""
        public["sample_audio_ready"] = sample_path.is_file()
    return public


def _voice_candidate_has_tag(row: dict[str, object], tag: str) -> bool:
    normalized = _normalize_tag(tag)
    return normalized in {_normalize_tag(item) for item in list(row.get("tags") or []) if _normalize_tag(item)}


_VOICE_LABEL_VARIANT_SUFFIXES = {
    "express",
    "fast",
    "high",
    "hq",
    "neural",
    "plus",
    "premium",
    "pro",
    "standard",
    "v1",
    "v2",
    "v3",
    "wavenet",
}


def _voice_label_family_key(label: object) -> str:
    without_parenthetical = re.sub(r"\([^)]*\)", " ", str(label or ""))
    parts = [part for part in _normalize_tag(without_parenthetical).split("_") if part]
    while len(parts) > 1 and parts[-1] in _VOICE_LABEL_VARIANT_SUFFIXES:
        parts.pop()
    return "_".join(parts)


def _voice_candidate_identity_keys(row: dict[str, object]) -> set[str]:
    keys: set[str] = set()
    preset_key = str(row.get("preset_key") or row.get("candidate_key") or "").strip()
    if preset_key:
        keys.add(f"preset:{preset_key}")
    voice_id_sha = str(row.get("voice_id_sha256") or "").strip()
    if not voice_id_sha and str(row.get("_voice_id") or "").strip():
        voice_id_sha = _sha256_bytes(str(row.get("_voice_id") or "").strip().encode("utf-8"))
    if voice_id_sha:
        keys.add(f"voice:{voice_id_sha}")
    label_key = _voice_label_family_key(row.get("label"))
    if label_key:
        keys.add(f"label_family:{label_key}")
    return keys


def _voice_candidate_identity_keys_from_private_candidates(
    *,
    private_candidates: dict[object, object],
    candidate_keys: set[str],
) -> set[str]:
    identities: set[str] = set()
    if not candidate_keys:
        return identities
    for candidate in private_candidates.values():
        if not isinstance(candidate, dict):
            continue
        candidate_key = str(candidate.get("candidate_key") or "").strip()
        public = dict(candidate.get("public") or {})
        public_key = str(public.get("preset_key") or "").strip()
        if candidate_key not in candidate_keys and public_key not in candidate_keys:
            continue
        row = {**public, "candidate_key": candidate_key}
        identities.update(_voice_candidate_identity_keys(row))
    return identities


def _prefer_nonpremium_after_dismissals(
    *,
    candidate_rows: list[dict[str, object]],
    dismissed_keys: set[str],
    exclude_keys: set[str],
    replacement_count: int,
) -> bool:
    if replacement_count <= 0:
        return False
    dismissed_premium_threshold = _env_int("EA_AUDIOBOOK_VOICE_PREMIUM_DISMISSAL_DIVERSIFY_THRESHOLD", 3, minimum=1, maximum=30)
    dismissed_premium_count = 0
    available_nonpremium_count = 0
    for row in candidate_rows:
        preset_key = str(row.get("preset_key") or "").strip()
        is_premium = _voice_candidate_has_tag(row, "premium")
        if preset_key in dismissed_keys and is_premium:
            dismissed_premium_count += 1
        if (
            preset_key
            and preset_key not in exclude_keys
            and bool(row.get("language_match"))
            and not is_premium
            and _voice_candidate_allowed_for_audition(row)
        ):
            available_nonpremium_count += 1
    return dismissed_premium_count >= dismissed_premium_threshold and available_nonpremium_count >= replacement_count


def _metadata_from_job(job: dict[str, object]) -> EpubMetadata:
    metadata_payload = dict(job.get("metadata") or {})
    return EpubMetadata(
        title=str(metadata_payload.get("title") or "").strip(),
        author=str(metadata_payload.get("author") or "").strip(),
        language=str(metadata_payload.get("language") or "en-US").strip() or "en-US",
        source_filename=str(metadata_payload.get("source_filename") or "book.epub").strip() or "book.epub",
        source_sha256=str(metadata_payload.get("source_sha256") or "").strip(),
        cover_image_path=str(metadata_payload.get("cover_image_path") or "").strip(),
        cover_media_type=str(metadata_payload.get("cover_media_type") or "").strip(),
    )


def _ensure_epub_cover_asset(job_dir: Path, payload: dict[str, object], metadata: EpubMetadata) -> EpubMetadata:
    if _cover_image_path(job_dir, metadata) is not None:
        return metadata
    source = dict(payload.get("source") or {})
    storage = dict(payload.get("storage") or {})
    source_epub_raw = str(source.get("source_epub") or storage.get("source_epub") or "").strip()
    if not source_epub_raw:
        return metadata
    source_epub = Path(source_epub_raw)
    if not source_epub.is_file():
        return metadata
    expected_sha = str(source.get("source_sha256") or metadata.source_sha256 or "").strip()
    if expected_sha and _sha256_file(source_epub) != expected_sha:
        return metadata
    try:
        validate_epub_archive(source_epub)
        with zipfile.ZipFile(source_epub) as zip_handle:
            rootfile, opf_root = _read_opf(zip_handle)
            manifest, _spine = _opf_manifest_and_spine(opf_root)
            cover_image_path, cover_media_type = _extract_epub_cover_image(
                zip_handle=zip_handle,
                rootfile=rootfile,
                opf_root=opf_root,
                manifest=manifest,
                target_dir=job_dir / "assets",
            )
    except Exception:
        return metadata
    if not cover_image_path:
        return metadata
    metadata_payload = dict(payload.get("metadata") or {})
    metadata_payload["cover_image_path"] = cover_image_path
    metadata_payload["cover_media_type"] = cover_media_type
    payload["metadata"] = metadata_payload
    return _metadata_from_job(payload)


def _chapters_from_job(job: dict[str, object]) -> tuple[EpubChapter, ...]:
    return tuple(
        EpubChapter(
            index=int(dict(item).get("index") or 0),
            title=str(dict(item).get("title") or "").strip(),
            source_href=str(dict(item).get("source_href") or "").strip(),
            text_path=str(dict(item).get("text_path") or "").strip(),
            audio_filename=str(dict(item).get("audio_filename") or "").strip(),
            char_count=int(dict(item).get("char_count") or 0),
            sha256=str(dict(item).get("sha256") or "").strip(),
        )
        for item in list(job.get("chapters") or [])
        if isinstance(item, dict)
    )


def prepare_audiobook_voice_audition(*, job_dir: Path, batch_size: int = 3, refill_pending: bool = False) -> dict[str, object]:
    job = _load_job(job_dir)
    if not audiobook_voice_audition_enabled():
        return job
    if not external_tts_enabled():
        return job
    metadata = _metadata_from_job(job)
    chapters = _chapters_from_job(job)
    provider_payload = dict(job.get("provider") or {})
    current_selection = dict(provider_payload.get("voice_selection") or {})
    if str(current_selection.get("status") or "") == "selected_by_user":
        repaired_selection, repaired = _backfill_voice_selection_book_profile(
            voice_selection=current_selection,
            metadata=metadata,
            chapters=chapters,
            job_dir=job_dir,
        )
        if repaired:
            provider_payload["voice_selection"] = repaired_selection
            job["provider"] = provider_payload
            job["updated_at"] = _now_iso()
            _write_job(job_dir, job)
            _write_current_job_receipt_best_effort(job_dir)
        return job
    min_candidates = audiobook_voice_audition_min_candidates()
    ranking_target_count = _coerce_voice_discovery_target_count(
        requested_count=audiobook_voice_discovery_target_count()
    )

    ranking = None
    candidate_rows: list[dict[str, object]] = []
    profile = {}
    for _ in range(2):
        ranking = _ranked_unmixr_voice_candidates(
            metadata=metadata,
            chapters=chapters,
            job_dir=job_dir,
            target_count=ranking_target_count,
        )
        candidate_rows = [dict(row) for row in list(ranking.get("candidate_rows") or []) if isinstance(row, dict)]
        profile = dict(ranking.get("profile") or {})
        if len(candidate_rows) >= min_candidates:
            break
        if _ == 0:
            _refresh_discovery_forced()
            continue
        break
    if len(candidate_rows) < min_candidates:
        provider_payload["voice_selection"] = {
            "contract_name": VOICE_AUDITION_CONTRACT_NAME,
            "status": "blocked",
            "reason": "voice_catalog_underfilled",
            "strategy": "generic_voice_discovery_then_book_profile_voice_audition",
            "candidate_count": len(candidate_rows),
            "required_candidate_count": min_candidates,
            "target_catalog_count": audiobook_voice_discovery_target_count(),
            "discovery_enabled": audiobook_voice_discovery_enabled(),
            "discovery_providers": list(_voice_discovery_providers()),
            "book_profile": _public_book_profile(profile),
            "pending_candidate_keys": [],
            "pending_batch": [],
            "raw_voice_ids_exposed": False,
            "sample_text_exposed": False,
        }
        job["provider"] = provider_payload
        job["status"] = "blocked_voice_catalog"
        job["next_action"] = "discover_or_configure_audiobook_voice_catalog"
        job["updated_at"] = _now_iso()
        _write_job(job_dir, job)
        _write_current_job_receipt_best_effort(job_dir)
        return job
    dismissed_keys = {
        str(item or "").strip()
        for item in list(current_selection.get("dismissed_candidate_keys") or [])
        if str(item or "").strip()
    }
    pending_keys = [
        str(item or "").strip()
        for item in list(current_selection.get("pending_candidate_keys") or [])
        if str(item or "").strip()
    ]
    private_payload = _load_voice_audition_private(job_dir)
    private_candidates = dict(private_payload.get("candidates") or {})
    dismissed_identity_keys = {
        str(item or "").strip()
        for item in list(current_selection.get("dismissed_voice_identity_keys") or [])
        if str(item or "").strip()
    }
    dismissed_identity_keys.update(
        _voice_candidate_identity_keys_from_private_candidates(
            private_candidates=private_candidates,
            candidate_keys=dismissed_keys,
        )
    )
    pending_still_active = [key for key in pending_keys if key not in dismissed_keys]
    current_pending_batch_raw = [
        row
        for row in list(current_selection.get("pending_batch") or [])
        if isinstance(row, dict) and str(row.get("preset_key") or "").strip() in pending_still_active
        and _voice_candidate_allowed_for_audition(row)
    ]
    current_pending_batch: list[dict[str, object]] = []
    active_identity_keys: set[str] = set()
    for row in current_pending_batch_raw:
        identity_keys = _voice_candidate_identity_keys(row)
        if identity_keys and identity_keys.intersection(dismissed_identity_keys | active_identity_keys):
            continue
        current_pending_batch.append(row)
        active_identity_keys.update(identity_keys)
    pending_still_active = [
        str(row.get("preset_key") or "").strip()
        for row in current_pending_batch
        if isinstance(row, dict) and str(row.get("preset_key") or "").strip()
    ]
    stored_book_profile = dict(current_selection.get("book_profile") or {})
    stored_author_gender_signal = str(stored_book_profile.get("author_gender_signal") or "").strip().lower()
    refreshed_author_gender_signal = str(profile.get("author_gender_signal") or "").strip().lower()
    refresh_pending_batch_for_author_gender_signal = (
        str(current_selection.get("status") or "").strip() == "waiting_user_choice"
        and bool(current_pending_batch)
        and bool(refreshed_author_gender_signal)
        and refreshed_author_gender_signal != stored_author_gender_signal
    )
    if refresh_pending_batch_for_author_gender_signal:
        current_pending_batch = []
        active_identity_keys = set()
        pending_still_active = []
    requested_batch_size = max(batch_size, 1)
    if pending_still_active and current_pending_batch and not refill_pending and len(current_pending_batch) >= requested_batch_size:
        job["status"] = "waiting_voice_selection"
        job["next_action"] = "choose_audiobook_voice"
        _write_job(job_dir, job)
        return job
    if pending_still_active and current_pending_batch and not refill_pending:
        refill_pending = True

    audition_strategy = (
        "generic_voice_discovery_then_book_profile_voice_audition"
        if audiobook_voice_discovery_enabled()
        else "book_profile_voice_audition"
    )
    sample_text = _voice_sample_text(job_dir=job_dir, chapters=chapters)
    if not sample_text:
        provider_payload["voice_selection"] = {
            "contract_name": VOICE_AUDITION_CONTRACT_NAME,
            "status": "blocked",
            "reason": "voice_sample_text_missing",
            "strategy": audition_strategy,
        }
        job["provider"] = provider_payload
        job["status"] = "blocked_external_tts"
        job["next_action"] = "inspect_epub_chapter_text"
        _write_job(job_dir, job)
        return job

    active_key_set = set(pending_still_active) if refill_pending else set()
    replacement_count = max(max(batch_size, 1) - len(current_pending_batch), 0) if refill_pending else max(batch_size, 1)
    exclude_key_set = dismissed_keys | active_key_set
    exclude_identity_key_set = set(dismissed_identity_keys) | (set(active_identity_keys) if refill_pending else set())
    author_gender_signal = str(profile.get("author_gender_signal") or "").strip().lower()
    author_gender_preference_used = False
    prefer_nonpremium_after_dismissals = _prefer_nonpremium_after_dismissals(
        candidate_rows=candidate_rows,
        dismissed_keys=dismissed_keys,
        exclude_keys=exclude_key_set,
        replacement_count=replacement_count,
    )

    def _pick_pending_rows(
        source_rows: list[dict[str, object]],
        *,
        exclude_keys: set[str],
        exclude_identity_keys: set[str],
        limit: int,
        require_language_match: bool = True,
        prefer_nonpremium: bool = False,
        require_author_gender_match: bool = False,
    ) -> list[dict[str, object]]:
        selected_rows: list[dict[str, object]] = []
        selected_set: set[str] = set()
        selected_identity_keys: set[str] = set()
        if limit <= 0:
            return selected_rows
        for row in source_rows:
            preset_key = str(row.get("preset_key") or "").strip()
            if not preset_key or preset_key in exclude_keys or preset_key in selected_set:
                continue
            identity_keys = _voice_candidate_identity_keys(row)
            if identity_keys and identity_keys.intersection(exclude_identity_keys | selected_identity_keys):
                continue
            if not _voice_candidate_allowed_for_audition(row):
                continue
            if prefer_nonpremium and _voice_candidate_has_tag(row, "premium"):
                continue
            if require_author_gender_match and author_gender_signal and not _voice_candidate_has_tag(row, author_gender_signal):
                continue
            if require_language_match and not _voice_language_matches(
                metadata.language,
                str(row.get("language") or ""),
                _split_languages(row.get("supported_languages") or row.get("language")),
            ):
                continue
            selected_rows.append(row)
            selected_set.add(preset_key)
            selected_identity_keys.update(identity_keys)
            if len(selected_rows) >= limit:
                break
        return selected_rows

    def _pick_gender_fit_then_general_rows(
        source_rows: list[dict[str, object]],
        *,
        exclude_keys: set[str],
        exclude_identity_keys: set[str],
        limit: int,
        require_language_match: bool = True,
        prefer_nonpremium: bool = False,
    ) -> list[dict[str, object]]:
        nonlocal author_gender_preference_used
        if not author_gender_signal:
            return _pick_pending_rows(
                source_rows,
                exclude_keys=exclude_keys,
                exclude_identity_keys=exclude_identity_keys,
                limit=limit,
                require_language_match=require_language_match,
                prefer_nonpremium=prefer_nonpremium,
            )
        preferred_rows = _pick_pending_rows(
            source_rows,
            exclude_keys=exclude_keys,
            exclude_identity_keys=exclude_identity_keys,
            limit=limit,
            require_language_match=require_language_match,
            prefer_nonpremium=prefer_nonpremium,
            require_author_gender_match=True,
        )
        if not preferred_rows:
            return _pick_pending_rows(
                source_rows,
                exclude_keys=exclude_keys,
                exclude_identity_keys=exclude_identity_keys,
                limit=limit,
                require_language_match=require_language_match,
                prefer_nonpremium=prefer_nonpremium,
            )
        author_gender_preference_used = True
        if len(preferred_rows) >= limit:
            return preferred_rows
        preferred_keys = {
            str(row.get("preset_key") or "").strip()
            for row in preferred_rows
            if str(row.get("preset_key") or "").strip()
        }
        preferred_identities: set[str] = set()
        for row in preferred_rows:
            preferred_identities.update(_voice_candidate_identity_keys(row))
        general_rows = _pick_pending_rows(
            source_rows,
            exclude_keys=exclude_keys | preferred_keys,
            exclude_identity_keys=exclude_identity_keys | preferred_identities,
            limit=limit - len(preferred_rows),
            require_language_match=require_language_match,
            prefer_nonpremium=prefer_nonpremium,
        )
        return [*preferred_rows, *general_rows]

    discovery_expanded_target_count = 0

    def _expand_discovery_when_candidate_pool_is_thin() -> None:
        nonlocal candidate_rows
        nonlocal discovery_expanded_target_count
        nonlocal author_gender_signal
        nonlocal prefer_nonpremium_after_dismissals
        nonlocal profile
        nonlocal ranking
        nonlocal ranking_target_count
        if not audiobook_voice_discovery_enabled():
            return
        if ranking_target_count >= 300:
            return
        expanded_target = _coerce_voice_discovery_target_count(
            requested_count=max(
                ranking_target_count * 2,
                ranking_target_count + len(dismissed_keys) + (requested_batch_size * 12),
            )
        )
        if expanded_target <= ranking_target_count:
            return
        expanded_ranking = _ranked_unmixr_voice_candidates(
            metadata=metadata,
            chapters=chapters,
            job_dir=job_dir,
            target_count=expanded_target,
        )
        expanded_rows = [
            dict(row)
            for row in list(expanded_ranking.get("candidate_rows") or [])
            if isinstance(row, dict)
        ]
        if len(expanded_rows) < len(candidate_rows):
            return
        if len(expanded_rows) == len(candidate_rows) and len(candidate_rows) < ranking_target_count:
            return
        ranking = expanded_ranking
        candidate_rows = expanded_rows
        profile = dict(ranking.get("profile") or {})
        author_gender_signal = str(profile.get("author_gender_signal") or "").strip().lower()
        ranking_target_count = expanded_target
        discovery_expanded_target_count = expanded_target
        prefer_nonpremium_after_dismissals = _prefer_nonpremium_after_dismissals(
            candidate_rows=candidate_rows,
            dismissed_keys=dismissed_keys,
            exclude_keys=exclude_key_set,
            replacement_count=replacement_count,
        )

    attempt_budget = audiobook_voice_sample_generation_max_attempts(batch_size=requested_batch_size)
    replacement_attempt_limit = max(max(replacement_count, 1), attempt_budget)
    next_rows: list[dict[str, object]] = _pick_gender_fit_then_general_rows(
        candidate_rows,
        exclude_keys=exclude_key_set,
        exclude_identity_keys=exclude_identity_key_set,
        limit=replacement_attempt_limit,
        prefer_nonpremium=prefer_nonpremium_after_dismissals,
    )
    if not next_rows and prefer_nonpremium_after_dismissals:
        next_rows = _pick_gender_fit_then_general_rows(
            candidate_rows,
            exclude_keys=exclude_key_set,
            exclude_identity_keys=exclude_identity_key_set,
            limit=replacement_attempt_limit,
        )
    if len(next_rows) < replacement_attempt_limit:
        _expand_discovery_when_candidate_pool_is_thin()
        next_rows = _pick_gender_fit_then_general_rows(
            candidate_rows,
            exclude_keys=exclude_key_set,
            exclude_identity_keys=exclude_identity_key_set,
            limit=replacement_attempt_limit,
            prefer_nonpremium=prefer_nonpremium_after_dismissals,
        )
        if not next_rows and prefer_nonpremium_after_dismissals:
            next_rows = _pick_gender_fit_then_general_rows(
                candidate_rows,
                exclude_keys=exclude_key_set,
                exclude_identity_keys=exclude_identity_key_set,
                limit=replacement_attempt_limit,
            )
    language_fallback_used = False

    if not next_rows and refill_pending and current_pending_batch and dismissed_keys and audiobook_voice_discovery_enabled():
        _refresh_discovery_forced()
        refill_target_count = _coerce_voice_discovery_target_count(
            requested_count=len(dismissed_keys) + len(current_pending_batch) + max(replacement_count, 1)
        )
        ranking = _ranked_unmixr_voice_candidates(
            metadata=metadata,
            chapters=chapters,
            job_dir=job_dir,
            target_count=refill_target_count,
        )
        candidate_rows = [dict(row) for row in list(ranking.get("candidate_rows") or []) if isinstance(row, dict)]
        profile = dict(ranking.get("profile") or {})
        author_gender_signal = str(profile.get("author_gender_signal") or "").strip().lower()
        exclude_key_set = dismissed_keys | active_key_set
        prefer_nonpremium_after_dismissals = _prefer_nonpremium_after_dismissals(
            candidate_rows=candidate_rows,
            dismissed_keys=dismissed_keys,
            exclude_keys=exclude_key_set,
            replacement_count=replacement_count,
        )
        next_rows = _pick_gender_fit_then_general_rows(
            candidate_rows,
            exclude_keys=exclude_key_set,
            exclude_identity_keys=exclude_identity_key_set,
            limit=replacement_attempt_limit,
            prefer_nonpremium=prefer_nonpremium_after_dismissals,
        )
        if not next_rows and prefer_nonpremium_after_dismissals:
            next_rows = _pick_gender_fit_then_general_rows(
                candidate_rows,
                exclude_keys=exclude_key_set,
                exclude_identity_keys=exclude_identity_key_set,
                limit=replacement_attempt_limit,
            )

    if not next_rows and refill_pending and dismissed_keys:
        next_rows = _pick_gender_fit_then_general_rows(
            candidate_rows,
            exclude_keys=exclude_key_set,
            exclude_identity_keys=exclude_identity_key_set,
            limit=replacement_attempt_limit,
            require_language_match=False,
            prefer_nonpremium=prefer_nonpremium_after_dismissals,
        )
        if not next_rows and prefer_nonpremium_after_dismissals:
            next_rows = _pick_gender_fit_then_general_rows(
                candidate_rows,
                exclude_keys=exclude_key_set,
                exclude_identity_keys=exclude_identity_key_set,
                limit=replacement_attempt_limit,
                require_language_match=False,
            )
        language_fallback_used = bool(next_rows)

    if not next_rows and not current_pending_batch:
        provider_payload["voice_selection"] = {
            **current_selection,
            "contract_name": VOICE_AUDITION_CONTRACT_NAME,
            "status": "exhausted",
            "strategy": audition_strategy,
            "dismissed_candidate_keys": sorted(dismissed_keys),
            "dismissed_voice_identity_keys": sorted(dismissed_identity_keys),
            "pending_candidate_keys": [],
            "pending_batch": [],
            "reason": "voice_catalog_exhausted",
        }
        job["provider"] = provider_payload
        job["status"] = "voice_selection_exhausted"
        job["next_action"] = "add_more_voice_presets_or_reset_dismissals"
        _write_job(job_dir, job)
        return job

    sample_dir = _voice_audition_dir(job_dir) / "samples"
    sample_dir.mkdir(parents=True, exist_ok=True)
    pending_batch: list[dict[str, object]] = list(current_pending_batch) if refill_pending else []
    pending_identity_keys: set[str] = set()
    for row in pending_batch:
        if isinstance(row, dict):
            pending_identity_keys.update(_voice_candidate_identity_keys(row))
    pending_sample_hashes = {
        str(row.get("sample_sha256") or "").strip()
        for row in pending_batch
        if isinstance(row, dict) and str(row.get("sample_sha256") or "").strip()
    }
    sample_path_by_hash: dict[str, Path] = {}
    for row in pending_batch:
        if not isinstance(row, dict):
            continue
        sample_file = str(row.get("sample_file") or "").strip()
        sample_hash = str(row.get("sample_sha256") or "").strip()
        if sample_file and sample_hash:
            sample_path = _voice_audition_dir(job_dir) / "samples" / sample_file
            if sample_path.is_file():
                sample_path_by_hash[sample_hash] = sample_path
    replacement_keys: list[str] = []
    sample_generation_failures: list[dict[str, object]] = []
    duplicate_rows: list[tuple[dict[str, object], str, str, str, str, str, Path]] = []
    for row in next_rows:
        if refill_pending and len(replacement_keys) >= replacement_count:
            break
        if len(pending_batch) >= requested_batch_size:
            break
        preset_key = str(row.get("preset_key") or "").strip()
        voice_id = str(row.get("_voice_id") or "").strip()
        voice_id_sha = str(row.get("voice_id_sha256") or "").strip() or _sha256_bytes(voice_id.encode("utf-8"))
        identity_keys = _voice_candidate_identity_keys(row)
        if identity_keys and identity_keys.intersection(pending_identity_keys):
            sample_generation_failures.append(
                {
                    "preset_key_sha256": _sha256_bytes(preset_key.encode("utf-8")) if preset_key else "",
                    "reason": "duplicate_voice_identity",
                }
            )
            continue
        token = _voice_audition_token(job_id=str(job.get("job_id") or job_dir.name), preset_key=preset_key, voice_id_sha256=voice_id_sha)
        target = sample_dir / f"{token}.wav"
        try:
            if not target.is_file():
                audio_bytes, content_type, _ = _synthesize_unmixr_with_retries(
                    text=sample_text,
                    voice_id=voice_id,
                    lang=metadata.language,
                    speaking_rate=unmixr_speaking_rate(),
                    speaking_pitch=unmixr_speaking_pitch(),
                    speaking_volume=unmixr_speaking_volume(),
                )
                rendered_path = _write_provider_audio_file(audio_bytes=audio_bytes, content_type=content_type, target_wav=target)
            else:
                rendered_path = target
        except Exception as exc:
            sample_generation_failures.append(
                {
                    "preset_key_sha256": _sha256_bytes(preset_key.encode("utf-8")) if preset_key else "",
                    "reason": _exception_detail(exc)[:160] or type(exc).__name__,
                }
            )
            continue
        sample_sha256 = _sha256_file(rendered_path) if rendered_path.is_file() else ""
        if sample_sha256:
            sample_path_by_hash.setdefault(sample_sha256, rendered_path)
        if sample_sha256 and sample_sha256 in pending_sample_hashes:
            sample_generation_failures.append(
                {
                    "preset_key_sha256": _sha256_bytes(preset_key.encode("utf-8")) if preset_key else "",
                    "reason": "duplicate_voice_sample_audio",
                }
            )
            duplicate_rows.append(
                (dict(row), preset_key, token, voice_id, voice_id_sha, sample_sha256, rendered_path)
            )
            continue
        public_candidate = _safe_public_voice_candidate(row, token=token, sample_path=rendered_path)
        pending_batch.append(public_candidate)
        if sample_sha256:
            pending_sample_hashes.add(sample_sha256)
        pending_identity_keys.update(_voice_candidate_identity_keys(public_candidate))
        replacement_keys.append(preset_key)
        private_candidates[token] = {
            "candidate_key": preset_key,
            "voice_id": voice_id,
            "voice_id_sha256": voice_id_sha,
            "sample_path": str(rendered_path),
            "public": public_candidate,
        }
        if len(pending_batch) >= requested_batch_size:
            break

    if len(pending_batch) < requested_batch_size and duplicate_rows:
        used_duplicate_preset_keys: set[str] = set()
        for (
            duplicate_row,
            duplicate_preset_key,
            duplicate_token,
            duplicate_voice_id,
            duplicate_voice_id_sha,
            duplicate_sample_sha256,
            duplicate_rendered_path,
            ) in duplicate_rows:
            if len(pending_batch) >= requested_batch_size:
                break
            duplicate_source_path = sample_path_by_hash.get(duplicate_sample_sha256)
            if not duplicate_rendered_path.is_file():
                if duplicate_source_path and duplicate_source_path.is_file():
                    try:
                        shutil.copy2(duplicate_source_path, duplicate_rendered_path)
                    except Exception:
                        continue
                else:
                    continue
            if duplicate_preset_key and any(
                str(row.get("preset_key") or "").strip() == duplicate_preset_key for row in pending_batch
            ):
                continue
            duplicate_identity_keys = _voice_candidate_identity_keys(duplicate_row)
            if duplicate_identity_keys and duplicate_identity_keys.intersection(pending_identity_keys):
                continue
            public_candidate = _safe_public_voice_candidate(
                duplicate_row,
                token=duplicate_token,
                sample_path=duplicate_rendered_path,
            )
            if duplicate_preset_key:
                used_duplicate_preset_keys.add(duplicate_preset_key)
            pending_batch.append(public_candidate)
            pending_identity_keys.update(_voice_candidate_identity_keys(public_candidate))
            replacement_keys.append(duplicate_preset_key)
            private_candidates[duplicate_token] = {
                "candidate_key": duplicate_preset_key,
                "voice_id": duplicate_voice_id,
                "voice_id_sha256": duplicate_voice_id_sha,
                "sample_path": str(duplicate_rendered_path),
                "public": public_candidate,
            }
            if len(pending_batch) >= requested_batch_size:
                break
        for (
            duplicate_row,
            duplicate_preset_key,
            duplicate_token,
            duplicate_voice_id,
            duplicate_voice_id_sha,
            duplicate_sample_sha256,
            duplicate_rendered_path,
        ) in duplicate_rows:
            if duplicate_preset_key in used_duplicate_preset_keys:
                continue
            duplicate_rendered_path.unlink(missing_ok=True)
    private_payload.update(
        {
            "contract_name": VOICE_AUDITION_CONTRACT_NAME,
            "job_id": str(job.get("job_id") or job_dir.name),
            "updated_at": _now_iso(),
            "sample_text_sha256": _sha256_bytes(sample_text.encode("utf-8")),
            "sample_text_chars": len(sample_text),
            "candidates": private_candidates,
        }
    )
    _write_voice_audition_private(job_dir, private_payload)
    profile = dict(ranking.get("profile") or {})
    language_matched_candidate_count = sum(
        1
        for row in candidate_rows
        if isinstance(row, dict)
        and bool(row.get("language_match"))
        and _voice_candidate_allowed_for_audition(row)
    )
    underfilled = len(pending_batch) < requested_batch_size
    if refill_pending and underfilled and sample_generation_failures:
        underfilled_reason = "voice_sample_generation_failed_after_dismissal"
    elif refill_pending and underfilled:
        underfilled_reason = "voice_catalog_underfilled_after_dismissals"
    elif language_fallback_used:
        underfilled_reason = "voice_catalog_language_relaxed_after_dismissals"
    elif underfilled and sample_generation_failures:
        underfilled_reason = "voice_sample_generation_failed"
    elif underfilled:
        underfilled_reason = "voice_catalog_underfilled"
    else:
        underfilled_reason = ""
    updated_voice_selection = {
        "contract_name": VOICE_AUDITION_CONTRACT_NAME,
            "status": "waiting_user_choice",
            "reason": underfilled_reason,
            "strategy": audition_strategy,
            "discovery_enabled": audiobook_voice_discovery_enabled(),
            "discovery_providers": list(_voice_discovery_providers()),
            "target_catalog_count": ranking_target_count,
            "discovery_expanded_target_count": discovery_expanded_target_count,
            "book_profile": _public_book_profile(profile),
        "candidate_count": len(candidate_rows),
        "language_matched_candidate_count": language_matched_candidate_count,
        "requested_batch_size": requested_batch_size,
        "batch_size": len(pending_batch),
        "underfilled": underfilled,
        "underfilled_reason": underfilled_reason,
        "sample_generation_failed_count": len(sample_generation_failures),
        "sample_generation_failures": sample_generation_failures[:5],
        "sample_generation_attempt_limit": replacement_attempt_limit,
        "premium_dismissal_diversity_used": prefer_nonpremium_after_dismissals,
        "author_gender_preference_used": author_gender_preference_used,
        "language_relaxed_after_dismissals": language_fallback_used,
        "pending_candidate_keys": [
            str(row.get("preset_key") or "").strip()
            for row in pending_batch
            if isinstance(row, dict) and str(row.get("preset_key") or "").strip()
        ],
        "pending_voice_identity_keys": sorted(pending_identity_keys),
        "replacement_candidate_keys": replacement_keys,
        "dismissed_candidate_keys": sorted(dismissed_keys),
        "dismissed_voice_identity_keys": sorted(dismissed_identity_keys),
        "pending_batch": pending_batch,
        "selected": {},
        "raw_voice_ids_exposed": False,
        "sample_text_exposed": False,
    }
    provider_payload["voice_selection"] = updated_voice_selection
    provider_payload["raw_sample_text_leaves_ea"] = True
    provider_payload["raw_book_text_leaves_ea"] = False
    job["provider"] = provider_payload
    render_result = dict(job.get("render_result") or {})
    if isinstance(render_result.get("voice_selection"), dict):
        render_result["voice_selection"] = updated_voice_selection
        if underfilled_reason:
            render_result["reason"] = underfilled_reason
        job["render_result"] = render_result
    job["status"] = "waiting_voice_selection"
    job["next_action"] = "choose_audiobook_voice"
    job["updated_at"] = _now_iso()
    _write_job(job_dir, job)
    _write_current_job_receipt_best_effort(job_dir)
    return job


def audiobook_voice_audition_sample_messages(job: dict[str, object]) -> list[dict[str, object]]:
    job_dir = Path(str(dict(job.get("storage") or {}).get("job_dir") or ""))
    if not job_dir:
        return []
    voice_selection = dict(dict(job.get("provider") or {}).get("voice_selection") or {})
    rows: list[dict[str, object]] = []
    for candidate in list(voice_selection.get("pending_batch") or []):
        if not isinstance(candidate, dict):
            continue
        if not _voice_candidate_allowed_for_audition(candidate):
            continue
        sample_file = Path(str(candidate.get("sample_file") or "")).name
        token = str(candidate.get("callback_token") or "").strip()
        if not sample_file or not token:
            continue
        sample_path = _voice_audition_dir(job_dir) / "samples" / sample_file
        if not sample_path.is_file():
            continue
        rows.append(
            {
                "token": token,
                "label": str(candidate.get("label") or "Voice sample").strip(),
                "score": int(candidate.get("score") or 0),
                "matched_tags": list(candidate.get("matched_tags") or []),
                "audio_path": str(sample_path),
            }
        )
    return rows


def reopen_audiobook_voice_selection_for_language_mismatch(*, job_dir: Path, limit: int = 3) -> dict[str, object]:
    job = _load_job(job_dir)
    metadata = _metadata_from_job(job)
    provider_payload = dict(job.get("provider") or {})
    current_selection = dict(provider_payload.get("voice_selection") or {})
    dismissed_keys = {
        str(item or "").strip()
        for item in list(current_selection.get("dismissed_candidate_keys") or [])
        if str(item or "").strip()
    }
    private_payload = _load_voice_audition_private(job_dir)
    private_candidates = dict(private_payload.get("candidates") or {})
    rows: list[dict[str, object]] = []
    for candidate in private_candidates.values():
        if not isinstance(candidate, dict):
            continue
        public = dict(candidate.get("public") or {})
        if not _voice_candidate_allowed_for_audition(public):
            continue
        preset_key = str(public.get("preset_key") or candidate.get("candidate_key") or "").strip()
        if preset_key and preset_key in dismissed_keys:
            continue
        sample_file = Path(str(public.get("sample_file") or "")).name
        token = str(public.get("callback_token") or "").strip()
        if not token or not sample_file:
            continue
        if not (_voice_audition_dir(job_dir) / "samples" / sample_file).is_file():
            continue
        if not _voice_language_matches(
            metadata.language,
            str(public.get("language") or ""),
            _split_languages(public.get("supported_languages") or public.get("language")),
        ):
            continue
        rows.append(public)
    rows.sort(key=lambda row: int(row.get("score") or 0), reverse=True)
    selected_rows = rows[: max(1, int(limit or 3))]
    if not selected_rows:
        return job
    pending_keys = [
        str(row.get("preset_key") or "").strip()
        for row in selected_rows
        if str(row.get("preset_key") or "").strip()
    ]
    reopened_selection = {
        **current_selection,
        "contract_name": VOICE_AUDITION_CONTRACT_NAME,
        "status": "waiting_user_choice",
        "reason": "selected_voice_language_mismatch",
        "pending_candidate_keys": pending_keys,
        "pending_batch": selected_rows,
        "selected": {},
        "selected_candidate_key": "",
        "selected_callback_token": "",
        "raw_voice_ids_exposed": False,
        "sample_text_exposed": False,
        "last_action": {
            "action": "reopen",
            "status": "replacement_ready",
            "reason": "selected_voice_language_mismatch",
            "replacement_count": len(selected_rows),
            "replacement_candidate_keys": pending_keys,
        },
    }
    provider_payload["voice_selection"] = reopened_selection
    provider_payload["raw_book_text_leaves_ea"] = False
    job["provider"] = provider_payload
    job["status"] = "waiting_voice_selection"
    job["next_action"] = "choose_audiobook_voice"
    job["render_result"] = {
        "status": "waiting_voice_selection",
        "reason": "selected_voice_language_mismatch",
        "voice_selection": reopened_selection,
    }
    job["updated_at"] = _now_iso()
    _write_job(job_dir, job)
    _write_current_job_receipt_best_effort(job_dir)
    if dismissed_keys and len(selected_rows) < max(1, int(limit or 3)):
        return prepare_audiobook_voice_audition(
            job_dir=job_dir,
            batch_size=max(1, int(limit or 3)),
            refill_pending=True,
        )
    return job


def _audiobook_voice_sample_delivery_summary(
    *,
    expected_count: int,
    sample_receipts: list[dict[str, object]] | tuple[dict[str, object], ...],
) -> dict[str, object]:
    receipts = [dict(item) for item in list(sample_receipts or []) if isinstance(item, dict)]
    sent_count = sum(1 for item in receipts if str(item.get("status") or "").strip().lower() == "sent")
    failed_count = sum(1 for item in receipts if str(item.get("status") or "").strip().lower() == "failed")
    skipped_count = sum(1 for item in receipts if str(item.get("status") or "").strip().lower() == "skipped")
    attempted_count = len(receipts)
    if expected_count <= 0:
        status = "not_required"
    elif sent_count >= expected_count and expected_count > 0:
        status = "sent"
    elif sent_count > 0:
        status = "partial"
    elif attempted_count > 0:
        status = "failed"
    else:
        status = "not_attempted"
    reasons: list[str] = []
    for item in receipts:
        reason = str(item.get("reason") or "").strip()
        if reason and reason not in reasons:
            reasons.append(reason)
    return {
        "status": status,
        "expected_count": max(int(expected_count), 0),
        "attempted_count": attempted_count,
        "sent_count": sent_count,
        "failed_count": failed_count,
        "skipped_count": skipped_count,
        "reason": reasons[0] if reasons else "",
        "reasons": reasons[:5],
        "token_sha256": [
            _sha256_bytes(str(item.get("token") or "").encode("utf-8"))
            for item in receipts
            if str(item.get("token") or "").strip()
        ],
        "samples": [
            {
                "token_sha256": _sha256_bytes(str(item.get("token") or "").encode("utf-8")),
                "status": str(item.get("status") or "").strip(),
                "media_message_id_sha256": str(item.get("media_message_id_sha256") or "").strip(),
                "button_message_id_sha256": str(item.get("button_message_id_sha256") or "").strip(),
                "button_count": int(item.get("button_count") or 0),
                "buttons_fallback": bool(item.get("buttons_fallback")),
                "control_kind": str(item.get("control_kind") or "").strip(),
            }
            for item in receipts
            if str(item.get("token") or "").strip()
        ],
        "updated_at": _now_iso(),
    }


def record_audiobook_voice_sample_delivery(
    *,
    job: dict[str, object],
    sample_receipts: list[dict[str, object]] | tuple[dict[str, object], ...],
) -> dict[str, object]:
    job_dir_raw = str(dict(job.get("storage") or {}).get("job_dir") or "").strip()
    job_dir = Path(job_dir_raw) if job_dir_raw else Path()
    if job_dir_raw and job_dir.is_dir():
        current_job = _load_job(job_dir)
    else:
        current_job = dict(job)
    receipt_count = len([item for item in list(sample_receipts or []) if isinstance(item, dict)])
    expected_count = receipt_count or len(audiobook_voice_audition_sample_messages(current_job))
    summary = _audiobook_voice_sample_delivery_summary(
        expected_count=expected_count,
        sample_receipts=sample_receipts,
    )
    telegram = dict(current_job.get("telegram") or {})
    telegram["voice_sample_delivery"] = summary
    current_job["telegram"] = telegram
    current_job["updated_at"] = _now_iso()
    if job_dir_raw and job_dir.is_dir():
        _write_job(job_dir, current_job)
        _write_current_job_receipt_best_effort(job_dir)
    return current_job


def _find_voice_audition_job_by_token(token: str) -> tuple[Path, dict[str, object], dict[str, object]]:
    normalized = str(token or "").strip()
    if not normalized:
        raise RuntimeError("voice_audition_token_missing")
    for root in audiobook_job_discovery_roots():
        for private_path in sorted(root.glob("*/voice_audition/private.json")):
            private_payload = _load_voice_audition_private(private_path.parent.parent)
            candidate = dict(dict(private_payload.get("candidates") or {}).get(normalized) or {})
            if candidate:
                return private_path.parent.parent, private_payload, candidate
    raise RuntimeError("voice_audition_token_not_found")


def selected_unmixr_voice_for_job(job_dir: Path) -> dict[str, object]:
    try:
        job = _load_job(job_dir)
    except Exception:
        return {}
    voice_selection = dict(dict(job.get("provider") or {}).get("voice_selection") or {})
    metadata = _metadata_from_job(job)
    chapters = _chapters_from_job(job)
    repaired_selection, repaired = _backfill_voice_selection_book_profile(
        voice_selection=voice_selection,
        metadata=metadata,
        chapters=chapters,
        job_dir=job_dir,
    )
    if repaired:
        provider_payload = dict(job.get("provider") or {})
        provider_payload["voice_selection"] = repaired_selection
        job["provider"] = provider_payload
        job["updated_at"] = _now_iso()
        _write_job(job_dir, job)
        voice_selection = repaired_selection
    private_payload = _load_voice_audition_private(job_dir)
    recovered_token = str(private_payload.get("selected_callback_token") or "").strip()
    if str(voice_selection.get("status") or "") != "selected_by_user" and recovered_token:
        candidate = dict(dict(private_payload.get("candidates") or {}).get(recovered_token) or {})
        voice_id = str(candidate.get("voice_id") or "").strip()
        public_candidate = dict(candidate.get("public") or {})
        if voice_id and public_candidate:
            selected = {
                key: value
                for key, value in public_candidate.items()
                if key not in {"sample_file", "sample_sha256", "sample_audio_ready"}
            }
            recovered_selection = {
                **voice_selection,
                "contract_name": VOICE_AUDITION_CONTRACT_NAME,
                "status": "selected_by_user",
                "selected": selected,
                "selected_candidate_key": str(private_payload.get("selected_candidate_key") or candidate.get("candidate_key") or "").strip(),
                "selected_callback_token": recovered_token,
                "pending_candidate_keys": [],
                "pending_batch": [],
                "raw_voice_ids_exposed": False,
                "sample_text_exposed": False,
                "last_action": {
                    "action": "use",
                    "candidate_key": str(private_payload.get("selected_candidate_key") or candidate.get("candidate_key") or "").strip(),
                    "batch_advanced": False,
                    "remaining_in_batch": 0,
                    "status": "selected_by_user",
                    "recovered_from_private_audition": True,
                },
            }
            return {"status": "selected", "voice_id": voice_id, "public": recovered_selection}
    if str(voice_selection.get("status") or "") != "selected_by_user":
        if str(voice_selection.get("status") or "") == "waiting_user_choice":
            return {
                "status": "blocked",
                "reason": "voice_selection_pending",
                "voice_id": "",
                "public": voice_selection,
            }
        return {}
    token = str(voice_selection.get("selected_callback_token") or "").strip()
    candidate = dict(dict(private_payload.get("candidates") or {}).get(token) or {})
    voice_id = str(candidate.get("voice_id") or "").strip()
    if not voice_id:
        return {}
    return {"status": "selected", "voice_id": voice_id, "public": voice_selection}


def _reset_audiobook_render_outputs_for_new_voice(job_dir: Path) -> dict[str, object]:
    removed: list[str] = []
    removed_bytes = 0
    for child_name in ("audio", "output"):
        child = job_dir / child_name
        if not child.exists():
            continue
        if child.is_dir():
            removed_bytes += sum(int(item.stat().st_size or 0) for item in child.rglob("*") if item.is_file())
            shutil.rmtree(child)
        else:
            removed_bytes += int(child.stat().st_size or 0)
            child.unlink()
        removed.append(child_name)
    return {
        "status": "reset" if removed else "not_needed",
        "removed_paths": removed,
        "removed_bytes": removed_bytes,
        "reset_at": _now_iso() if removed else "",
    }


def _audiobook_job_last_updated_at(job: dict[str, object], *, fallback: datetime | None = None) -> datetime | None:
    for key in ("updated_at", "created_at"):
        parsed = _parse_iso_datetime(job.get(key))
        if parsed is not None:
            return parsed
    return fallback


def _audiobook_cleanup_is_benign_filesystem_race(exc: BaseException) -> bool:
    if isinstance(exc, (FileNotFoundError, NotADirectoryError)):
        return True
    if isinstance(exc, OSError):
        return getattr(exc, "errno", None) in _AUDIOBOOK_CLEANUP_MISSING_ERRNOS
    return False


def _audiobook_cleanup_path_kind(path: Path) -> str:
    try:
        if not path.exists():
            return "missing"
        return "dir" if path.is_dir() else "file"
    except OSError as exc:
        if _audiobook_cleanup_is_benign_filesystem_race(exc):
            return "missing"
        raise


def _audiobook_cleanup_relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except Exception:
        return str(path)


def _audiobook_cleanup_remove_path(path: Path) -> int:
    path_kind = _audiobook_cleanup_path_kind(path)
    if path_kind == "missing":
        return 0
    if path_kind == "dir":
        removed_bytes = 0
        try:
            path_items = tuple(path.rglob("*"))
        except OSError as exc:
            if _audiobook_cleanup_is_benign_filesystem_race(exc):
                path_items = ()
            else:
                raise
        for item in path_items:
            try:
                if not item.is_file():
                    continue
                removed_bytes += int(item.stat().st_size or 0)
            except OSError as exc:
                if _audiobook_cleanup_is_benign_filesystem_race(exc):
                    continue
                raise

        def _ignore_missing_remove_error(function, remove_path, excinfo) -> None:
            _ = function
            _ = remove_path
            exc = excinfo[1] if isinstance(excinfo, tuple) else excinfo
            if _audiobook_cleanup_is_benign_filesystem_race(exc):
                return
            raise exc

        try:
            try:
                shutil.rmtree(path, onerror=_ignore_missing_remove_error)
            except TypeError as exc:
                if "onerror" not in str(exc):
                    raise
                shutil.rmtree(path, onexc=_ignore_missing_remove_error)
        except (OSError, TypeError) as exc:
            if not _audiobook_cleanup_is_benign_filesystem_race(exc):
                raise
        return removed_bytes
    try:
        removed_bytes = int(path.stat().st_size or 0)
    except OSError as exc:
        if _audiobook_cleanup_is_benign_filesystem_race(exc):
            return 0
        raise
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        if not _audiobook_cleanup_is_benign_filesystem_race(exc):
            raise
    return removed_bytes


def cleanup_audiobook_job_artifacts(
    job_dir: Path,
    *,
    force: bool = False,
    now: datetime | None = None,
) -> dict[str, object]:
    observed_at = now or datetime.now(UTC)
    try:
        job_dir_missing = not job_dir.is_dir()
    except OSError as exc:
        if not _audiobook_cleanup_is_benign_filesystem_race(exc):
            return {
                "status": "failed",
                "reason": type(exc).__name__,
                "removed_bytes": 0,
                "removed_paths": [],
                "job_dir_name": job_dir.name,
            }
        job_dir_missing = True
    if job_dir_missing:
        return {"status": "missing", "removed_bytes": 0, "removed_paths": [], "job_dir_name": job_dir.name}
    try:
        job, job_manifest_source = _load_cleanup_job(job_dir)
    except Exception as exc:
        if isinstance(exc, RuntimeError) and str(exc) == "audiobook_job_manifest_missing":
            return {
                "status": "missing",
                "reason": "job_manifest_missing",
                "removed_bytes": 0,
                "removed_paths": [],
                "job_dir_name": job_dir.name,
            }
        if _audiobook_cleanup_is_benign_filesystem_race(exc):
            return {
                "status": "missing",
                "reason": type(exc).__name__,
                "removed_bytes": 0,
                "removed_paths": [],
                "job_dir_name": job_dir.name,
            }
        return {
            "status": "failed",
            "reason": type(exc).__name__,
            "removed_bytes": 0,
            "removed_paths": [],
            "job_dir_name": job_dir.name,
        }
    job_status = str(job.get("status") or "").strip()
    updated_at = _audiobook_job_last_updated_at(job)
    age_seconds = int((observed_at - updated_at).total_seconds()) if updated_at is not None else None
    if not force and age_seconds is not None and age_seconds < _audiobook_job_cleanup_min_age_seconds():
        return {
            "status": "deferred",
            "reason": "job_recently_updated",
            "age_seconds": age_seconds,
            "removed_bytes": 0,
            "removed_paths": [],
            "job_dir_name": job_dir.name,
        }

    removable_paths: list[Path] = []
    if _audiobook_job_cleanup_remove_render_dirs() and job_status == "audiobookshelf_imported":
        removable_paths.extend(job_dir / name for name in ("audio", "output", "m4b"))
        source_dir = job_dir / "source"
        if _audiobook_cleanup_path_kind(source_dir) == "dir":
            try:
                removable_paths.extend(
                    item
                    for item in source_dir.glob("*.converted.epub")
                    if _audiobook_cleanup_path_kind(item) == "file"
                )
            except OSError as exc:
                if not _audiobook_cleanup_is_benign_filesystem_race(exc):
                    raise
    removable_paths.extend(
        [
            job_dir / "resume_state.json",
            job_dir / "resume_result.json",
            job_dir / "audiobookshelf_share_state.json",
            job_dir / "resume_cover_backfill_result.json",
            job_dir / "audio_publication_gate.json",
        ]
    )
    try:
        removable_paths.extend(
            path
            for path in job_dir.rglob("*.partial")
            if _audiobook_cleanup_path_kind(path) == "file"
        )
    except OSError as exc:
        if not _audiobook_cleanup_is_benign_filesystem_race(exc):
            raise

    removed_paths: list[str] = []
    removed_bytes = 0
    removal_errors: list[dict[str, str]] = []
    skipped_paths: list[dict[str, str]] = []
    seen: set[str] = set()
    for path in removable_paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        try:
            path_kind = _audiobook_cleanup_path_kind(path)
        except OSError as exc:
            removal_errors.append(
                {
                    "path": _audiobook_cleanup_relative_path(path, job_dir),
                    "error": type(exc).__name__,
                }
            )
            continue
        if path_kind == "missing":
            skipped_paths.append(
                {
                    "path": _audiobook_cleanup_relative_path(path, job_dir),
                    "reason": "missing_before_remove",
                }
            )
            continue
        try:
            removed_bytes += _audiobook_cleanup_remove_path(path)
        except Exception as exc:
            if _audiobook_cleanup_is_benign_filesystem_race(exc):
                skipped_paths.append(
                    {
                        "path": _audiobook_cleanup_relative_path(path, job_dir),
                        "reason": type(exc).__name__,
                    }
                )
                continue
            removal_errors.append(
                {
                    "path": _audiobook_cleanup_relative_path(path, job_dir),
                    "error": type(exc).__name__,
                }
            )
            continue
        removed_paths.append(_audiobook_cleanup_relative_path(path, job_dir))
    result_status = "cleaned" if removed_paths else "failed" if removal_errors else "not_needed"
    result = {
        "status": result_status,
        "job_dir_name": job_dir.name,
        "job_status": job_status,
        "job_manifest_source": job_manifest_source,
        "age_seconds": age_seconds if age_seconds is not None else -1,
        "removed_bytes": removed_bytes,
        "removed_paths": removed_paths,
        "cleaned_at": observed_at.isoformat().replace("+00:00", "Z"),
    }
    if removal_errors:
        result["removal_errors"] = removal_errors
    if skipped_paths:
        result["skipped_paths"] = skipped_paths
    return result


def _cleanup_stale_audiobook_incoming_files(*, now: datetime | None = None) -> dict[str, object]:
    observed_at = now or datetime.now(UTC)
    incoming_roots = [root / "_incoming" for root in audiobook_job_discovery_roots()]
    accessible_roots: list[Path] = []
    skipped_paths: list[dict[str, str]] = []
    for root in incoming_roots:
        try:
            if root.is_dir():
                accessible_roots.append(root)
        except OSError as exc:
            item = {"path": str(root), "reason": type(exc).__name__}
            if getattr(exc, "errno", None) is not None:
                item["errno"] = int(exc.errno)
            skipped_paths.append(item)
            continue
    if not accessible_roots:
        result: dict[str, object] = {"status": "missing", "removed_files": 0, "removed_bytes": 0, "removed_paths": []}
        if skipped_paths:
            result["skipped_paths"] = skipped_paths
        return result
    retention = timedelta(days=_audiobook_job_cleanup_prune_staging_days())
    removed_files = 0
    removed_bytes = 0
    removed_paths: list[str] = []
    for incoming_root in accessible_roots:
        try:
            stale_candidates = sorted(incoming_root.rglob("*"))
        except OSError as exc:
            if not _audiobook_cleanup_is_benign_filesystem_race(exc):
                skipped_paths.append({"path": str(incoming_root), "reason": type(exc).__name__})
            continue
        for path in stale_candidates:
            try:
                if not path.is_file():
                    continue
            except OSError as exc:
                if _audiobook_cleanup_is_benign_filesystem_race(exc):
                    continue
                skipped_paths.append({"path": str(path), "reason": type(exc).__name__})
                continue
            try:
                mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            except OSError as exc:
                if _audiobook_cleanup_is_benign_filesystem_race(exc):
                    continue
                skipped_paths.append({"path": str(path), "reason": type(exc).__name__})
                continue
            if observed_at - mtime < retention:
                continue
            try:
                removed_bytes += int(path.stat().st_size or 0)
                path.unlink(missing_ok=True)
            except OSError as exc:
                if _audiobook_cleanup_is_benign_filesystem_race(exc):
                    skipped_paths.append({"path": str(path), "reason": type(exc).__name__})
                    continue
                skipped_paths.append({"path": str(path), "reason": type(exc).__name__})
                continue
            removed_files += 1
            try:
                relative = str(path.relative_to(incoming_root))
            except Exception:
                relative = str(path)
            removed_paths.append(f"{incoming_root}:{relative}")
        try:
            dir_candidates = sorted(incoming_root.rglob("*"), reverse=True)
        except OSError as exc:
            if not _audiobook_cleanup_is_benign_filesystem_race(exc):
                skipped_paths.append({"path": str(incoming_root), "reason": type(exc).__name__})
            continue
        for path in dir_candidates:
            try:
                is_dir = path.is_dir()
            except OSError as exc:
                if not _audiobook_cleanup_is_benign_filesystem_race(exc):
                    skipped_paths.append({"path": str(path), "reason": type(exc).__name__})
                continue
            if is_dir:
                try:
                    next(path.iterdir())
                except StopIteration:
                    try:
                        path.rmdir()
                    except OSError as exc:
                        if not _audiobook_cleanup_is_benign_filesystem_race(exc):
                            skipped_paths.append({"path": str(path), "reason": type(exc).__name__})
                except OSError as exc:
                    if not _audiobook_cleanup_is_benign_filesystem_race(exc):
                        skipped_paths.append({"path": str(path), "reason": type(exc).__name__})
    result = {
        "status": "cleaned" if removed_files else "not_needed",
        "removed_files": removed_files,
        "removed_bytes": removed_bytes,
        "removed_paths": removed_paths,
    }
    if skipped_paths:
        result["skipped_paths"] = skipped_paths
    return result


def _audiobook_job_contact_duplicate_identity(job: dict[str, object]) -> str:
    source = dict(job.get("source") or {})
    metadata = dict(job.get("metadata") or {})
    source_kind = str(source.get("kind") or "").strip()
    title = str(metadata.get("title") or job.get("title") or "").strip()
    author = str(metadata.get("author") or "").strip()
    totals = dict(job.get("totals") or {})
    chapter_count = int(totals.get("chapter_count") or 0)
    char_count = int(totals.get("char_count") or 0)
    whatsapp = dict(job.get("whatsapp") or {})
    sender_ref = str(whatsapp.get("sender_ref") or "").strip()
    chat_ref = str(whatsapp.get("chat_ref") or "").strip()
    if not (sender_ref or chat_ref):
        return ""
    if not (title or author):
        return ""
    if chapter_count <= 0 or char_count <= 0:
        return ""
    scoped_payload = "|".join(
        (
            sender_ref,
            chat_ref,
            title,
            author,
            str(chapter_count),
            str(char_count),
        )
    )
    return f"{source_kind}|contact-title-author-size:{_sha256_bytes(scoped_payload.encode('utf-8'))}"


def _audiobook_job_whatsapp_duplicate_scope(job: dict[str, object]) -> str:
    whatsapp = dict(job.get("whatsapp") or {})
    sender_ref = str(whatsapp.get("sender_ref") or "").strip()
    chat_ref = str(whatsapp.get("chat_ref") or "").strip()
    if not (sender_ref or chat_ref):
        return ""
    return _sha256_bytes(f"{sender_ref}|{chat_ref}".encode("utf-8"))


def _audiobook_job_duplicate_identities(job: dict[str, object]) -> list[str]:
    source = dict(job.get("source") or {})
    metadata = dict(job.get("metadata") or {})
    source_kind = str(source.get("kind") or "").strip()
    source_sha256 = (
        str(source.get("source_sha256") or "").strip()
        or str(metadata.get("source_sha256") or "").strip()
    )
    whatsapp_scope = _audiobook_job_whatsapp_duplicate_scope(job)
    identities: list[str] = []
    if source_sha256:
        if whatsapp_scope:
            identities.append(f"{source_kind}|whatsapp-source:{whatsapp_scope}:{source_sha256}")
        else:
            identities.append(f"{source_kind}|sha256:{source_sha256}")
    contact_identity = _audiobook_job_contact_duplicate_identity(job)
    if contact_identity and contact_identity not in identities:
        identities.append(contact_identity)
    if identities:
        return identities
    title = str(metadata.get("title") or job.get("title") or "").strip()
    author = str(metadata.get("author") or "").strip()
    if title or author:
        if whatsapp_scope:
            title_author_hash = _sha256_bytes(f"{title}|{author}".encode("utf-8"))
            return [f"{source_kind}|whatsapp-title-author:{whatsapp_scope}:{title_author_hash}"]
        return [f"{source_kind}|title-author:{_sha256_bytes(f'{title}|{author}'.encode('utf-8'))}"]
    return []


def _audiobook_job_duplicate_identity(job: dict[str, object]) -> str:
    identities = _audiobook_job_duplicate_identities(job)
    if identities:
        return identities[0]
    return ""


def _cleanup_superseded_audiobook_job(
    job_dir: Path,
    *,
    job: dict[str, object],
    reason: str,
    observed_at: datetime,
) -> dict[str, object]:
    removable_paths: list[Path] = [
        job_dir / "audio",
        job_dir / "output",
        job_dir / "m4b",
        job_dir / "chapters",
        job_dir / "assets",
        job_dir / "voice_audition",
        job_dir / "source",
        job_dir / "resume_state.json",
        job_dir / "resume_result.json",
        job_dir / "audiobookshelf_share_state.json",
        job_dir / "resume_cover_backfill_result.json",
        job_dir / "audio_publication_gate.json",
    ]
    try:
        removable_paths.extend(
            path
            for path in job_dir.rglob("*.partial")
            if _audiobook_cleanup_path_kind(path) == "file"
        )
    except OSError as exc:
        if not _audiobook_cleanup_is_benign_filesystem_race(exc):
            raise

    removed_paths: list[str] = []
    removed_bytes = 0
    skipped_paths: list[dict[str, str]] = []
    seen: set[str] = set()
    for path in removable_paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        try:
            if _audiobook_cleanup_path_kind(path) == "missing":
                skipped_paths.append(
                    {
                        "path": _audiobook_cleanup_relative_path(path, job_dir),
                        "reason": "missing_before_remove",
                    }
                )
                continue
            removed_bytes += _audiobook_cleanup_remove_path(path)
        except Exception as exc:
            if _audiobook_cleanup_is_benign_filesystem_race(exc):
                skipped_paths.append(
                    {
                        "path": _audiobook_cleanup_relative_path(path, job_dir),
                        "reason": type(exc).__name__,
                    }
                )
                continue
            raise
        removed_paths.append(_audiobook_cleanup_relative_path(path, job_dir))

    updated_job = dict(job)
    updated_job["status"] = "superseded_duplicate"
    updated_job["next_action"] = "none"
    updated_job["blocking_reason"] = reason
    updated_job["updated_at"] = observed_at.isoformat().replace("+00:00", "Z")
    cleanup = dict(updated_job.get("cleanup") or {})
    cleanup["superseded_duplicate"] = {
        "reason": reason,
        "cleaned_at": observed_at.isoformat().replace("+00:00", "Z"),
        "removed_bytes": removed_bytes,
        "removed_paths": removed_paths,
    }
    if skipped_paths:
        cleanup["superseded_duplicate"]["skipped_paths"] = skipped_paths
    updated_job["cleanup"] = cleanup
    _write_job(job_dir, updated_job)

    result = {
        "status": "cleaned",
        "job_dir_name": job_dir.name,
        "job_status": str(job.get("status") or "").strip(),
        "reason": reason,
        "duplicate_identity": _audiobook_job_duplicate_identity(job),
        "removed_bytes": removed_bytes,
        "removed_paths": removed_paths,
        "cleaned_at": observed_at.isoformat().replace("+00:00", "Z"),
    }
    if skipped_paths:
        result["skipped_paths"] = skipped_paths
    return result


def _cleanup_superseded_audiobook_jobs(
    manifests: list[Path],
    *,
    force: bool = False,
    now: datetime | None = None,
) -> dict[str, object]:
    observed_at = now or datetime.now(UTC)
    groups: dict[str, list[tuple[datetime, Path, dict[str, object]]]] = {}
    for manifest_path in manifests:
        try:
            job = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        identities = _audiobook_job_duplicate_identities(job)
        if not identities:
            continue
        updated_at = _audiobook_job_last_updated_at(job) or observed_at
        for identity in identities:
            groups.setdefault(identity, []).append((updated_at, manifest_path.parent, job))

    results: list[dict[str, object]] = []
    removed_bytes = 0
    removed_paths = 0
    cleaned_jobs = 0
    min_age_seconds = _audiobook_job_cleanup_min_age_seconds()
    cleaned_job_dirs: set[str] = set()

    for identity, rows in groups.items():
        if len(rows) < 2:
            continue
        rows.sort(key=lambda row: (row[0], row[1].name), reverse=True)
        newer_statuses: set[str] = set()
        for index, (updated_at, job_dir, job) in enumerate(rows):
            job_dir_key = str(job_dir)
            if job_dir_key in cleaned_job_dirs:
                continue
            if index == 0:
                newer_statuses.add(str(job.get("status") or "").strip())
                continue
            status = str(job.get("status") or "").strip()
            if not force and (observed_at - updated_at).total_seconds() < min_age_seconds:
                newer_statuses.add(status)
                continue
            reason = ""
            if status == "waiting_voice_selection":
                if any(candidate_status != "superseded_duplicate" for candidate_status in newer_statuses):
                    reason = "superseded_waiting_voice_selection_duplicate"
            elif status == "m4b_ready" and "audiobookshelf_imported" in newer_statuses:
                reason = "superseded_m4b_ready_after_import"
            elif status == "audiobookshelf_imported" and "audiobookshelf_imported" in newer_statuses:
                reason = "superseded_older_imported_duplicate"
            elif status == "chapters_extracted" and "audiobookshelf_imported" in newer_statuses:
                reason = "superseded_chapters_extracted_after_import"
            if not reason:
                newer_statuses.add(status)
                continue
            try:
                result = _cleanup_superseded_audiobook_job(
                    job_dir,
                    job=job,
                    reason=reason,
                    observed_at=observed_at,
                )
            except Exception as exc:
                results.append(
                    {
                        "status": "failed",
                        "job_dir_name": job_dir.name,
                        "job_status": status,
                        "reason": reason,
                        "duplicate_identity": identity,
                        "removed_bytes": 0,
                        "removed_paths": [],
                        "cleanup_error": type(exc).__name__,
                        "cleaned_at": observed_at.isoformat().replace("+00:00", "Z"),
                    }
                )
                newer_statuses.add(status)
                continue
            results.append(result)
            if str(result.get("status") or "") == "cleaned":
                cleaned_jobs += 1
                cleaned_job_dirs.add(job_dir_key)
            removed_bytes += int(result.get("removed_bytes") or 0)
            removed_paths += len(list(result.get("removed_paths") or []))
            newer_statuses.add(status)

    return {
        "status": "cleaned" if cleaned_jobs else "not_needed",
        "cleaned_jobs": cleaned_jobs,
        "removed_bytes": removed_bytes,
        "removed_paths": removed_paths,
        "results": results,
    }


def cleanup_finished_audiobook_jobs(
    *,
    limit: int | None = None,
    force: bool = False,
    now: datetime | None = None,
) -> dict[str, object]:
    observed_at = now or datetime.now(UTC)
    roots = audiobook_job_discovery_roots()
    manifests = list(iter_audiobook_job_manifests())
    if not roots:
        root_probe = _storage_path_probe(audiobook_jobs_root())
        return {
            "status": "missing",
            "cleaned_jobs": 0,
            "removed_bytes": 0,
            "removed_paths": 0,
            "results": [],
            "job_root": root_probe,
            "staging": {"status": "missing", "removed_files": 0, "removed_bytes": 0, "removed_paths": []},
        }
    if limit is not None:
        manifests = manifests[: max(int(limit), 0)]
    results: list[dict[str, object]] = []
    cleaned_jobs = 0
    removed_bytes = 0
    removed_paths = 0
    failed_jobs = 0
    skipped_jobs = 0
    for manifest_path in manifests:
        try:
            result = cleanup_audiobook_job_artifacts(manifest_path.parent, force=force, now=observed_at)
        except Exception as exc:
            result = {
                "status": "failed",
                "reason": type(exc).__name__,
                "job_dir_name": manifest_path.parent.name,
                "removed_bytes": 0,
                "removed_paths": [],
                "cleaned_at": observed_at.isoformat().replace("+00:00", "Z"),
            }
        if str(result.get("status") or "") == "cleaned":
            cleaned_jobs += 1
            results.append(result)
        elif str(result.get("status") or "") == "failed":
            failed_jobs += 1
            results.append(result)
        elif str(result.get("status") or "") == "missing":
            skipped_jobs += 1
        removed_bytes += int(result.get("removed_bytes") or 0)
        removed_paths += len(list(result.get("removed_paths") or []))
    try:
        superseded = _cleanup_superseded_audiobook_jobs(manifests, force=force, now=observed_at)
    except Exception as exc:
        superseded = {
            "status": "failed",
            "cleaned_jobs": 0,
            "removed_bytes": 0,
            "removed_paths": 0,
            "results": [],
            "reason": type(exc).__name__,
        }
        failed_jobs += 1
    cleaned_jobs += int(superseded.get("cleaned_jobs") or 0)
    removed_bytes += int(superseded.get("removed_bytes") or 0)
    removed_paths += int(superseded.get("removed_paths") or 0)
    results.extend(list(superseded.get("results") or []))
    try:
        staging = _cleanup_stale_audiobook_incoming_files(now=observed_at)
    except Exception as exc:
        staging = {
            "status": "failed",
            "removed_files": 0,
            "removed_bytes": 0,
            "removed_paths": [],
            "reason": type(exc).__name__,
        }
        failed_jobs += 1
    removed_bytes += int(staging.get("removed_bytes") or 0)
    removed_paths += len(list(staging.get("removed_paths") or []))
    status = "cleaned" if cleaned_jobs or int(staging.get("removed_files") or 0) else "not_needed"
    if failed_jobs:
        status = "partial" if cleaned_jobs or int(staging.get("removed_files") or 0) else "failed"
    return {
        "status": status,
        "cleaned_jobs": cleaned_jobs,
        "failed_jobs": failed_jobs,
        "skipped_jobs": skipped_jobs,
        "removed_bytes": removed_bytes,
        "removed_paths": removed_paths,
        "results": results,
        "superseded": superseded,
        "staging": staging,
    }


def _audiobook_publication_artifacts_require_voice_reset(job: dict[str, object]) -> bool:
    merge_result = dict(job.get("merge_result") or {})
    import_result = dict(job.get("audiobookshelf_import") or {})
    publication_gate = dict(job.get("audio_publication_gate") or {})
    public_share = dict(import_result.get("public_share") or {})
    if str(merge_result.get("status") or "").strip() == "m4b_ready":
        return True
    if str(import_result.get("status") or "").strip() == "imported":
        return True
    if str(public_share.get("status") or "").strip() == "revoked_wrong_voice":
        return True
    if bool(import_result.get("wrong_voice_artifact_revoked")):
        return True
    gate_issues = {str(issue or "").strip() for issue in list(publication_gate.get("issues") or [])}
    return bool(
        gate_issues.intersection(
            {
                "previous_piper_fallback_revoked_wrong_voice",
                "public_share_revoked_wrong_voice",
                "audiobook_voice_revoked_wrong_voice",
            }
        )
    )


def _blocked_player_scoped_reference(*, reason: str) -> dict[str, object]:
    return {
        "contract_name": "ea.player_scoped_audiobookshelf_reference.v1",
        "status": "blocked",
        "reason": str(reason or "audio_publication_not_ready").strip() or "audio_publication_not_ready",
        "raw_library_path_exposed": False,
        "vendor_token_exposed": False,
    }


def _blocked_audiobookshelf_public_share(*, reason: str) -> dict[str, object]:
    return {
        "status": "blocked_audio_publication_gate",
        "reason": str(reason or "audio_publication_not_ready").strip() or "audio_publication_not_ready",
        "token_exposed": False,
        "raw_library_path_exposed": False,
        "telegram_followup_pending": False,
    }


def _voice_audition_candidate_active_for_use(
    *,
    voice_selection: dict[str, object],
    candidate_key: str,
    callback_token: str,
) -> bool:
    if str(voice_selection.get("status") or "").strip() != "waiting_user_choice":
        return False
    normalized_key = str(candidate_key or "").strip()
    normalized_token = str(callback_token or "").strip()
    if not normalized_key or not normalized_token:
        return False
    pending_keys = {
        str(item or "").strip()
        for item in list(voice_selection.get("pending_candidate_keys") or [])
        if str(item or "").strip()
    }
    if pending_keys and normalized_key not in pending_keys:
        return False
    for row in list(voice_selection.get("pending_batch") or []):
        if not isinstance(row, dict):
            continue
        if (
            str(row.get("preset_key") or "").strip() == normalized_key
            and str(row.get("callback_token") or "").strip() == normalized_token
        ):
            return True
    return False


def apply_audiobook_voice_audition_action(*, callback_token: str, action: str) -> dict[str, object]:
    normalized_action = _normalize_tag(action)
    job_dir, private_payload, candidate = _find_voice_audition_job_by_token(callback_token)
    job = _load_job(job_dir)
    provider_payload = dict(job.get("provider") or {})
    voice_selection = dict(provider_payload.get("voice_selection") or {})
    candidate_key = str(candidate.get("candidate_key") or "").strip()
    public_candidate = dict(candidate.get("public") or {})
    active_for_use = _voice_audition_candidate_active_for_use(
        voice_selection=voice_selection,
        candidate_key=candidate_key,
        callback_token=str(callback_token or "").strip(),
    )
    mismatch_recovery = (
        str(voice_selection.get("reason") or "").strip() == "selected_voice_language_mismatch"
        or str((job.get("render_result") or {}).get("reason") or "").strip() == "selected_voice_language_mismatch"
    )
    if (
        normalized_action in {"use", "select", "use_this"}
        and not _voice_candidate_allowed_for_audition(public_candidate)
        and not active_for_use
        and not mismatch_recovery
    ):
        normalized_action = "dismiss"
    if normalized_action in {"use", "select", "use_this"}:
        if not active_for_use and not mismatch_recovery:
            voice_selection["last_action"] = {
                "action": "use",
                "candidate_key": candidate_key,
                "status": "stale_candidate_ignored",
                "active_pending_keys": [
                    str(item or "").strip()
                    for item in list(voice_selection.get("pending_candidate_keys") or [])
                    if str(item or "").strip()
                ],
            }
            provider_payload["voice_selection"] = voice_selection
            job["provider"] = provider_payload
            job["updated_at"] = _now_iso()
            _write_job(job_dir, job)
            _write_current_job_receipt_best_effort(job_dir)
            return job
        previous_candidate_key = str(voice_selection.get("selected_candidate_key") or "").strip()
        render_reset: dict[str, object] = {}
        if candidate_key and (
            (previous_candidate_key and previous_candidate_key != candidate_key)
            or mismatch_recovery
            or _audiobook_publication_artifacts_require_voice_reset(job)
        ):
            render_reset = _reset_audiobook_render_outputs_for_new_voice(job_dir)
        selected = {key: value for key, value in public_candidate.items() if key not in {"sample_file", "sample_sha256", "sample_audio_ready"}}
        explicit_language_override = bool(voice_selection.get("voice_language_override_by_user")) or bool(
            selected.get("voice_language_override_by_user")
        )
        voice_selection.update(
            {
                "contract_name": VOICE_AUDITION_CONTRACT_NAME,
                "status": "selected_by_user",
                "selected": selected,
                "selected_candidate_key": candidate_key,
                "selected_callback_token": str(callback_token or "").strip(),
                "selected_at": _now_iso(),
                "pending_candidate_keys": [],
                "pending_batch": [],
                "voice_language_override_by_user": explicit_language_override,
                "raw_voice_ids_exposed": False,
                "sample_text_exposed": False,
                "last_action": {
                    "action": "use",
                    "candidate_key": candidate_key,
                    "batch_advanced": False,
                    "remaining_in_batch": 0,
                    "status": "selected_by_user",
                },
            }
        )
        if render_reset:
            voice_selection["render_reset_for_new_voice"] = render_reset
        provider_payload["voice_selection"] = voice_selection
        provider_payload["raw_book_text_leaves_ea"] = unmixr_auto_render_enabled()
        job["provider"] = provider_payload
        if render_reset:
            job["render_result"] = {
                "status": "reset_for_new_voice",
                "previous_candidate_key_sha256": _sha256_bytes(previous_candidate_key.encode("utf-8"))
                if previous_candidate_key
                else "",
                "selected_candidate_key_sha256": _sha256_bytes(candidate_key.encode("utf-8")) if candidate_key else "",
            }
            job["merge_result"] = {"status": "waiting_for_chapter_audio"}
            job["audiobookshelf_import"] = {
                "status": "waiting_for_m4b",
                "player_scoped_reference": _blocked_player_scoped_reference(reason="waiting_for_new_voice_render"),
                "public_share": _blocked_audiobookshelf_public_share(reason="waiting_for_new_voice_render"),
            }
            job["audio_publication_gate"] = {
                "contract_name": "ea.audiobook_publication_audio_gate.v1",
                "checked_at": _now_iso(),
                "status": "pending",
                "issues": ["waiting_for_new_voice_render"],
                "raw_paths_exposed": False,
            }
        job["status"] = "voice_selected"
        job["next_action"] = "render_chapter_audio"
        job["updated_at"] = _now_iso()
        private_payload["selected_callback_token"] = str(callback_token or "").strip()
        private_payload["selected_candidate_key"] = candidate_key
        private_payload["updated_at"] = _now_iso()
        _write_voice_audition_private(job_dir, private_payload)
        feedback = record_audiobook_voice_feedback(job=job, candidate=candidate, action="selected")
        if feedback:
            voice_selection["last_action"]["voice_feedback"] = feedback
            provider_payload["voice_selection"] = voice_selection
            job["provider"] = provider_payload
        _write_job(job_dir, job)
        return continue_job(job_dir) if unmixr_auto_render_enabled() else job
    if normalized_action in {"dismiss", "reject"}:
        if not _voice_audition_candidate_active_for_use(
            voice_selection=voice_selection,
            candidate_key=candidate_key,
            callback_token=str(callback_token or "").strip(),
        ):
            voice_selection["last_action"] = {
                "action": "dismiss",
                "candidate_key": candidate_key,
                "status": "stale_candidate_ignored",
                "active_pending_keys": [
                    str(item or "").strip()
                    for item in list(voice_selection.get("pending_candidate_keys") or [])
                    if str(item or "").strip()
                ],
            }
            provider_payload["voice_selection"] = voice_selection
            job["provider"] = provider_payload
            job["updated_at"] = _now_iso()
            _write_job(job_dir, job)
            _write_current_job_receipt_best_effort(job_dir)
            return job
        dismissed = {
            str(item or "").strip()
            for item in list(voice_selection.get("dismissed_candidate_keys") or [])
            if str(item or "").strip()
        }
        dismissed_identity_keys = {
            str(item or "").strip()
            for item in list(voice_selection.get("dismissed_voice_identity_keys") or [])
            if str(item or "").strip()
        }
        if candidate_key:
            dismissed.add(candidate_key)
        dismissed_identity_keys.update(_voice_candidate_identity_keys({**public_candidate, "candidate_key": candidate_key}))
        feedback = record_audiobook_voice_feedback(job=job, candidate=candidate, action="dismiss")
        pending_keys = [
            str(item or "").strip()
            for item in list(voice_selection.get("pending_candidate_keys") or [])
            if str(item or "").strip()
        ]
        voice_selection["dismissed_candidate_keys"] = sorted(dismissed)
        voice_selection["dismissed_voice_identity_keys"] = sorted(dismissed_identity_keys)
        active_pending = [key for key in pending_keys if key not in dismissed]
        remaining_batch = [
            row
            for row in list(voice_selection.get("pending_batch") or [])
            if isinstance(row, dict) and str(row.get("preset_key") or "").strip() in active_pending
            and not _voice_candidate_identity_keys(row).intersection(dismissed_identity_keys)
        ]
        active_pending = [
            str(row.get("preset_key") or "").strip()
            for row in remaining_batch
            if isinstance(row, dict) and str(row.get("preset_key") or "").strip()
        ]
        voice_selection["pending_candidate_keys"] = active_pending
        voice_selection["pending_batch"] = remaining_batch
        provider_payload["voice_selection"] = voice_selection
        job["provider"] = provider_payload
        job["status"] = "waiting_voice_selection"
        job["next_action"] = "choose_audiobook_voice"
        job["updated_at"] = _now_iso()
        _write_job(job_dir, job)
        next_job = prepare_audiobook_voice_audition(job_dir=job_dir, refill_pending=True)
        next_provider = dict(next_job.get("provider") or {})
        next_selection = dict(next_provider.get("voice_selection") or {})
        next_batch = [row for row in list(next_selection.get("pending_batch") or []) if isinstance(row, dict)]
        next_status = str(next_selection.get("status") or "").strip()
        sample_generation_failed_count = int(next_selection.get("sample_generation_failed_count") or 0)
        sample_generation_failed = bool(sample_generation_failed_count)
        replacement_keys = [
            str(item or "").strip()
            for item in list(next_selection.get("replacement_candidate_keys") or [])
            if str(item or "").strip()
        ]
        batch_advanced = next_status == "waiting_user_choice" and bool(replacement_keys)
        action_status = (
            "replacement_ready"
            if batch_advanced
            else "replacement_failed"
            if sample_generation_failed
            else next_status or "voice_catalog_exhausted"
        )
        next_selection["last_action"] = {
            "action": "dismiss",
            "candidate_key": candidate_key,
            "batch_advanced": batch_advanced,
            "remaining_in_batch": len(next_batch),
            "replacement_candidate_keys": replacement_keys,
            "replacement_count": len(replacement_keys),
            "sample_generation_failed_count": sample_generation_failed_count,
            "status": action_status,
        }
        if feedback:
            next_selection["last_action"]["voice_feedback"] = feedback
        next_provider["voice_selection"] = next_selection
        next_job["provider"] = next_provider
        next_job["updated_at"] = _now_iso()
        _write_job(job_dir, next_job)
        _write_current_job_receipt_best_effort(job_dir)
        return next_job
    raise RuntimeError("voice_audition_action_invalid")


def estimate_eta(*, total_chars: int, chapter_count: int, has_external_tts: bool, has_m4b_assembly: bool) -> dict[str, object]:
    # Conservative operator-facing estimate: provider render plus merge/import overhead.
    render_minutes = max(10, int(total_chars / _env_int("EA_AUDIOBOOK_ESTIMATED_RENDER_CHARS_PER_MINUTE", 6500, minimum=500)))
    merge_minutes = max(5, int(chapter_count / 8) + 5)
    total_minutes = render_minutes + merge_minutes
    if not has_external_tts:
        blocker = "external_tts_disabled"
    elif not has_m4b_assembly:
        blocker = "m4b_assembly_missing"
    else:
        blocker = ""
    eta = datetime.now(UTC) + timedelta(minutes=total_minutes)
    return {
        "estimated_minutes_after_unblocked": total_minutes,
        "estimated_ready_at_after_unblocked": eta.isoformat().replace("+00:00", "Z"),
        "blocker": blocker,
    }


def build_m4b_tool_command(
    *,
    audio_dir: Path,
    output_file: Path,
    title: str,
    author: str = "",
    narrator: str = "",
    cover_path: Path | None = None,
) -> list[str]:
    command = [
        m4b_tool_bin(),
        "merge",
        str(audio_dir),
        "--output-file",
        str(output_file),
        "--name",
        title or output_file.stem,
        "--artist",
        narrator or author or "EA Narration",
        "--writer",
        author or "",
        "--albumartist",
        author or narrator or "EA Narration",
        "--audio-codec",
        "aac",
        "--audio-bitrate",
        str(os.getenv("EA_AUDIOBOOK_M4B_BITRATE") or "96k"),
        "--audio-channels",
        str(os.getenv("EA_AUDIOBOOK_M4B_CHANNELS") or "1"),
    ]
    if cover_path and cover_path.is_file():
        command.extend(["--cover", str(cover_path)])
    return command


def _audio_inputs_ready(
    job_dir: Path,
    chapters: tuple[EpubChapter, ...],
    *,
    cinematic_track_path: Path | None = None,
) -> bool:
    audio_dir = job_dir / "audio"
    if cinematic_track_path is not None and cinematic_track_path.is_file() and cinematic_track_path.stat().st_size > 0:
        return True
    for chapter in chapters:
        expected = _chapter_audio_path(audio_dir, chapter)
        if expected is not None:
            continue
        return False
    return True


def _chapter_audio_path(audio_dir: Path, chapter: EpubChapter) -> Path | None:
    expected = audio_dir / chapter.audio_filename
    if expected.is_file() and expected.stat().st_size > 0:
        return expected
    stem = expected.with_suffix("")
    for extension in (".wav", ".mp3", ".flac", ".ogg", ".aiff", ".m4a"):
        candidate = stem.with_suffix(extension)
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    return None


def _convert_audio_to_wav(*, source: Path, target: Path) -> bool:
    ffmpeg = shutil.which(str(os.getenv("EA_FFMPEG_BIN") or "ffmpeg").strip() or "ffmpeg")
    if not ffmpeg:
        return False
    completed = subprocess.run(
        [ffmpeg, "-y", "-i", str(source), "-ac", "1", "-ar", "44100", str(target)],
        check=False,
        capture_output=True,
        text=True,
        timeout=_env_int("EA_AUDIOBOOK_AUDIO_CONVERT_TIMEOUT_SECONDS", 600, minimum=10),
    )
    return completed.returncode == 0 and target.is_file() and target.stat().st_size > 0


def _audio_normalization_enabled() -> bool:
    return _env_bool("EA_AUDIOBOOK_AUDIO_NORMALIZATION_ENABLED", True)


def _audio_quality_report_enabled() -> bool:
    return _env_bool("EA_AUDIOBOOK_AUDIO_QUALITY_REPORT_ENABLED", True)


def audiobook_voice_sample_audio_quality_gate_enabled() -> bool:
    return _env_bool("EA_AUDIOBOOK_VOICE_SAMPLE_AUDIO_QUALITY_GATE_ENABLED", True)


def _normalize_rendered_audio_file(path: Path) -> Path:
    if not _audio_normalization_enabled() or not path.is_file():
        return path
    ffmpeg = shutil.which(str(os.getenv("EA_FFMPEG_BIN") or "ffmpeg").strip() or "ffmpeg")
    if not ffmpeg:
        return path
    target = path.with_name(f"{path.stem}.normalized{path.suffix}")
    filter_chain = str(
        os.getenv("EA_AUDIOBOOK_AUDIO_NORMALIZATION_FILTER")
        or "dynaudnorm=f=150:g=15,loudnorm=I=-16:TP=-1.5:LRA=11"
    ).strip()
    completed = subprocess.run(
        [ffmpeg, "-y", "-i", str(path), "-af", filter_chain, str(target)],
        check=False,
        capture_output=True,
        text=True,
        timeout=_env_int("EA_AUDIOBOOK_AUDIO_NORMALIZE_TIMEOUT_SECONDS", 600, minimum=10),
    )
    if completed.returncode == 0 and target.is_file() and target.stat().st_size > 0:
        target.replace(path)
    else:
        target.unlink(missing_ok=True)
    return path


def _pcm_sample_abs(sample: bytes, *, sample_width: int) -> float:
    if sample_width == 1:
        return abs((int(sample[0]) - 128) / 128.0)
    if sample_width == 2:
        return abs(int.from_bytes(sample, "little", signed=True) / 32768.0)
    if sample_width == 3:
        return abs(int.from_bytes(sample, "little", signed=True) / 8388608.0)
    if sample_width == 4:
        return abs(int.from_bytes(sample, "little", signed=True) / 2147483648.0)
    return 0.0


def _pcm_window_stats(*, payload: bytes, sample_width: int, channels: int, audible_threshold: float) -> dict[str, object]:
    frame_width = max(1, sample_width) * max(1, channels)
    frame_count = len(payload) // frame_width
    if frame_count <= 0 or sample_width not in {1, 2, 3, 4}:
        return {
            "frame_count": 0,
            "peak": 0.0,
            "rms": 0.0,
            "first_audible_frame": -1,
            "last_audible_frame": -1,
        }
    peak = 0.0
    sum_squares = 0.0
    first_audible = -1
    last_audible = -1
    for frame_index in range(frame_count):
        frame_start = frame_index * frame_width
        frame_peak = 0.0
        for channel_index in range(max(1, channels)):
            sample_start = frame_start + channel_index * sample_width
            sample = payload[sample_start : sample_start + sample_width]
            if len(sample) != sample_width:
                continue
            frame_peak = max(frame_peak, _pcm_sample_abs(sample, sample_width=sample_width))
        peak = max(peak, frame_peak)
        sum_squares += frame_peak * frame_peak
        if frame_peak >= audible_threshold:
            if first_audible < 0:
                first_audible = frame_index
            last_audible = frame_index
    return {
        "frame_count": frame_count,
        "peak": round(peak, 6),
        "rms": round(math.sqrt(sum_squares / frame_count), 6),
        "first_audible_frame": first_audible,
        "last_audible_frame": last_audible,
    }


def _rendered_audio_quality_report(path: Path) -> dict[str, object]:
    if not _audio_quality_report_enabled():
        return {"status": "skipped", "reason": "audio_quality_report_disabled"}
    if not path.is_file():
        return {"status": "failed", "reason": "audio_file_missing"}
    if path.suffix.lower() != ".wav":
        return {"status": "skipped", "reason": "audio_quality_report_wav_only", "extension": path.suffix.lower()}
    audible_threshold = _env_float("EA_AUDIOBOOK_AUDIO_AUDIBLE_RMS_THRESHOLD", 0.004, minimum=0.0001, maximum=0.2)
    quiet_tail_threshold = _env_float("EA_AUDIOBOOK_AUDIO_QUIET_TAIL_RMS_THRESHOLD", 0.006, minimum=0.0001, maximum=0.2)
    tail_window_seconds = _env_float("EA_AUDIOBOOK_AUDIO_TAIL_WINDOW_SECONDS", 1.5, minimum=0.25, maximum=10.0)
    min_duration_seconds = _env_float("EA_AUDIOBOOK_AUDIO_MIN_DURATION_SECONDS", 0.08, minimum=0.01, maximum=10.0)
    clipping_peak_threshold = _env_float("EA_AUDIOBOOK_AUDIO_CLIPPING_PEAK_THRESHOLD", 0.98, minimum=0.5, maximum=1.0)
    min_sample_rate = _env_int("EA_AUDIOBOOK_AUDIO_MIN_SAMPLE_RATE", 8000, minimum=1000, maximum=384000)
    max_sample_rate = _env_int("EA_AUDIOBOOK_AUDIO_MAX_SAMPLE_RATE", 192000, minimum=min_sample_rate, maximum=384000)
    max_trailing_silence_seconds = _env_float(
        "EA_AUDIOBOOK_AUDIO_MAX_TRAILING_SILENCE_SECONDS",
        1.2,
        minimum=0.1,
        maximum=20.0,
    )
    analysis_seconds = max(6.0, tail_window_seconds * 3.0, max_trailing_silence_seconds + 2.0)
    head_seconds = _env_float("EA_AUDIOBOOK_AUDIO_HEAD_ANALYSIS_SECONDS", 2.0, minimum=0.25, maximum=10.0)
    try:
        with wave.open(str(path), "rb") as wav_file:
            channels = int(wav_file.getnchannels() or 0)
            sample_width = int(wav_file.getsampwidth() or 0)
            frame_rate = int(wav_file.getframerate() or 0)
            frame_count = int(wav_file.getnframes() or 0)
            if channels <= 0 or sample_width <= 0 or frame_rate <= 0 or frame_count <= 0:
                return {"status": "failed", "reason": "audio_wav_metadata_invalid"}
            duration_seconds = frame_count / float(frame_rate)
            head_frames = min(frame_count, max(1, int(frame_rate * head_seconds)))
            wav_file.setpos(0)
            head_payload = wav_file.readframes(head_frames)
            tail_frames = min(frame_count, max(1, int(frame_rate * analysis_seconds)))
            wav_file.setpos(max(0, frame_count - tail_frames))
            tail_payload = wav_file.readframes(tail_frames)
            final_frames = min(frame_count, max(1, int(frame_rate * tail_window_seconds)))
            wav_file.setpos(max(0, frame_count - final_frames))
            final_payload = wav_file.readframes(final_frames)
    except Exception as exc:
        return {"status": "failed", "reason": "audio_wav_read_failed", "error_type": type(exc).__name__}

    head_stats = _pcm_window_stats(
        payload=head_payload,
        sample_width=sample_width,
        channels=channels,
        audible_threshold=audible_threshold,
    )
    tail_stats = _pcm_window_stats(
        payload=tail_payload,
        sample_width=sample_width,
        channels=channels,
        audible_threshold=audible_threshold,
    )
    final_stats = _pcm_window_stats(
        payload=final_payload,
        sample_width=sample_width,
        channels=channels,
        audible_threshold=audible_threshold,
    )
    tail_frame_count = int(tail_stats.get("frame_count") or 0)
    last_audible_frame = int(tail_stats.get("last_audible_frame") or -1)
    trailing_silence_seconds = (
        (tail_frame_count - last_audible_frame - 1) / float(frame_rate)
        if last_audible_frame >= 0 and tail_frame_count > 0
        else min(duration_seconds, tail_frame_count / float(frame_rate))
    )
    speech_energy_present = max(float(head_stats.get("peak") or 0.0), float(tail_stats.get("peak") or 0.0)) >= audible_threshold
    peak = max(float(head_stats.get("peak") or 0.0), float(tail_stats.get("peak") or 0.0))
    quiet_tail = (
        duration_seconds >= tail_window_seconds
        and float(final_stats.get("rms") or 0.0) < quiet_tail_threshold
        and speech_energy_present
    )
    excessive_trailing_silence = trailing_silence_seconds > max_trailing_silence_seconds
    issues: list[str] = []
    if duration_seconds < min_duration_seconds:
        issues.append("too_short")
    if not speech_energy_present:
        issues.append("speech_energy_missing")
    if peak >= clipping_peak_threshold:
        issues.append("clipping")
    if frame_rate < min_sample_rate or frame_rate > max_sample_rate:
        issues.append("sample_rate_out_of_range")
    if channels not in {1, 2}:
        issues.append("channel_count_unsupported")
    if sample_width not in {1, 2, 3, 4}:
        issues.append("sample_width_unsupported")
    if quiet_tail:
        issues.append("quiet_tail")
    if excessive_trailing_silence:
        issues.append("trailing_silence")
    hard_failures = {
        "too_short",
        "speech_energy_missing",
        "clipping",
        "sample_rate_out_of_range",
        "channel_count_unsupported",
        "sample_width_unsupported",
    }
    status = "failed" if any(issue in hard_failures for issue in issues) else "warn" if issues else "pass"
    return {
        "status": status,
        "duration_seconds": round(duration_seconds, 3),
        "channels": channels,
        "sample_rate": frame_rate,
        "sample_width_bytes": sample_width,
        "peak": round(peak, 6),
        "clipping_peak_threshold": clipping_peak_threshold,
        "min_duration_seconds": min_duration_seconds,
        "speech_energy_present": speech_energy_present,
        "head_peak": head_stats.get("peak", 0.0),
        "tail_peak": tail_stats.get("peak", 0.0),
        "tail_rms": final_stats.get("rms", 0.0),
        "tail_window_seconds": round(min(duration_seconds, tail_window_seconds), 3),
        "quiet_tail": quiet_tail,
        "trailing_silence_seconds": round(max(0.0, trailing_silence_seconds), 3),
        "excessive_trailing_silence": excessive_trailing_silence,
        "issues": issues,
    }


def audiobook_voice_sample_audio_quality_gate(path: Path) -> dict[str, object]:
    if not audiobook_voice_sample_audio_quality_gate_enabled():
        return {"ok": True, "status": "skipped", "reason": "voice_sample_audio_quality_gate_disabled"}
    if not path.is_file():
        return {"ok": False, "status": "failed", "reason": "sample_audio_missing"}
    if path.suffix.lower() != ".wav":
        return {"ok": True, "status": "skipped", "reason": "voice_sample_audio_quality_gate_wav_only"}
    report = _rendered_audio_quality_report(path)
    status = str(report.get("status") or "").strip().lower()
    if status == "failed":
        issues = [str(item).strip() for item in list(report.get("issues") or []) if str(item).strip()]
        reason = "voice_sample_audio_quality_failed"
        if issues:
            reason = f"{reason}:{','.join(issues[:4])}"
        elif str(report.get("reason") or "").strip():
            reason = f"{reason}:{str(report.get('reason')).strip()}"
        return {"ok": False, "status": "failed", "reason": reason, "audio_quality": report}
    return {"ok": True, "status": status or "pass", "reason": "", "audio_quality": report}


def _write_provider_audio_file(*, audio_bytes: bytes, content_type: str, target_wav: Path) -> Path:
    target_wav.parent.mkdir(parents=True, exist_ok=True)
    extension = (
        _AUDIO_EXTENSION_BY_TYPE.get(str(content_type or "").split(";", 1)[0].lower())
        or mimetypes.guess_extension(content_type or "")
        or ".bin"
    )
    provider_target = target_wav.with_suffix(extension)
    provider_target.write_bytes(audio_bytes)
    if provider_target.suffix.lower() != ".wav":
        if _convert_audio_to_wav(source=provider_target, target=target_wav):
            provider_target.unlink(missing_ok=True)
            return _normalize_rendered_audio_file(target_wav)
        return provider_target
    return _normalize_rendered_audio_file(provider_target)


def _merge_audio_segments_to_wav(*, segment_paths: tuple[Path, ...], target: Path) -> bool:
    if not segment_paths:
        return False
    ffmpeg = shutil.which(_ffmpeg_bin())
    if not ffmpeg:
        return False
    work_dir = target.parent / f"{target.stem}.parts"
    work_dir.mkdir(parents=True, exist_ok=True)
    concat_file = work_dir / "concat.txt"
    _write_ffmpeg_concat_file(concat_file, segment_paths)
    completed = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-ac",
            "1",
            "-ar",
            "44100",
            str(target),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=_env_int("EA_AUDIOBOOK_AUDIO_SEGMENT_MERGE_TIMEOUT_SECONDS", 1800, minimum=30),
    )
    return completed.returncode == 0 and target.is_file() and target.stat().st_size > 0


def _audiobook_paragraph_pauses_enabled() -> bool:
    return _env_bool("EA_AUDIOBOOK_PARAGRAPH_PAUSES_ENABLED", True)


def _audiobook_paragraph_pause_seconds() -> float:
    return _env_float("EA_AUDIOBOOK_PARAGRAPH_PAUSE_SECONDS", 0.45, minimum=0.0, maximum=3.0)


def _write_silence_wav(path: Path, *, seconds: float, sample_rate: int = 44100) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame_count = max(int(float(seconds) * sample_rate), 1)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * frame_count)
    return path


def _chapter_text_segment_rows(text: str, *, max_chars: int) -> tuple[dict[str, object], ...]:
    normalized = str(text or "").strip()
    if not normalized:
        return ()
    if not _audiobook_paragraph_pauses_enabled():
        return tuple({"text": segment, "paragraph_break_after": False} for segment in _chapter_text_segments(normalized, max_chars=max_chars))
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n{2,}", normalized) if paragraph.strip()]
    rows: list[dict[str, object]] = []
    for paragraph_index, paragraph in enumerate(paragraphs):
        chunks: list[str] = []
        while len(paragraph) > max_chars:
            split_at = paragraph.rfind(" ", 0, max_chars)
            if split_at < max_chars // 2:
                split_at = max_chars
            chunks.append(paragraph[:split_at].strip())
            paragraph = paragraph[split_at:].strip()
        if paragraph:
            chunks.append(paragraph)
        for chunk_index, chunk in enumerate(chunks):
            if not chunk:
                continue
            rows.append(
                {
                    "text": chunk,
                    "paragraph_break_after": (
                        paragraph_index < len(paragraphs) - 1
                        and chunk_index == len(chunks) - 1
                        and _audiobook_paragraph_pause_seconds() > 0
                    ),
                }
            )
    return tuple(rows)


def _chapter_text_segments(text: str, *, max_chars: int) -> tuple[str, ...]:
    normalized = str(text or "").strip()
    if len(normalized) <= max_chars:
        return (normalized,) if normalized else ()
    segments: list[str] = []
    paragraphs = re.split(r"\n{2,}", normalized)
    current = ""
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            segments.append(current)
            current = ""
        while len(paragraph) > max_chars:
            split_at = paragraph.rfind(" ", 0, max_chars)
            if split_at < max_chars // 2:
                split_at = max_chars
            segments.append(paragraph[:split_at].strip())
            paragraph = paragraph[split_at:].strip()
        current = paragraph
    if current:
        segments.append(current)
    return tuple(segment for segment in segments if segment)


def _exception_detail(exc: BaseException) -> str:
    detail = getattr(exc, "detail", "")
    if detail:
        return str(detail)
    return str(exc)


def _provider_wait_seconds_from_text(value: object) -> int:
    text = str(value or "")
    match = _PROVIDER_WAIT_RE.search(text)
    if not match:
        return 0
    try:
        return max(int(match.group(1)), 0)
    except Exception:
        return 0


def _unmixr_retryable_error(exc: BaseException) -> bool:
    detail = _exception_detail(exc).lower()
    if "input too long" in detail or "limit your input" in detail:
        return False
    if _provider_wait_seconds_from_text(detail) > _env_int(
        "EA_AUDIOBOOK_UNMIXR_MAX_INLINE_THROTTLE_WAIT_SECONDS",
        180,
        minimum=0,
        maximum=3600,
    ):
        return False
    status_code = int(getattr(exc, "status_code", 0) or 0)
    if status_code in {429, 500, 502, 503, 504}:
        return True
    return any(
        marker in detail
        for marker in (
            "no_audio_url",
            "upstream_unreachable",
            "audio_fetch_failed",
            "temporar",
            "timeout",
            "rate",
            "429",
            "502",
            "503",
            "504",
        )
    )


def _synthesize_unmixr_with_retries(
    *,
    text: str,
    voice_id: str,
    lang: str,
    speaking_rate: str | None,
    speaking_pitch: str | None,
    speaking_volume: str | None,
) -> tuple[bytes, str, list[str]]:
    attempts = _env_int("EA_AUDIOBOOK_UNMIXR_RETRY_COUNT", 3, minimum=1, maximum=8)
    base_sleep = _env_int("EA_AUDIOBOOK_UNMIXR_RETRY_BACKOFF_SECONDS", 4, minimum=0, maximum=120)
    errors: list[str] = []
    for attempt in range(1, attempts + 1):
        try:
            audio_bytes, content_type = unmixr_synthesize_request(
                text=text,
                voice_id=voice_id,
                lang=lang,
                speaking_rate=speaking_rate,
                speaking_pitch=speaking_pitch,
                speaking_volume=speaking_volume,
            )
            return audio_bytes, content_type, errors
        except Exception as exc:
            detail = _exception_detail(exc)
            errors.append(f"attempt_{attempt}:{detail}")
            if attempt >= attempts or not _unmixr_retryable_error(exc):
                raise
            if base_sleep > 0:
                time.sleep(base_sleep * attempt)
    raise RuntimeError("unmixr_retry_exhausted")


def _provider_balance_blocker(reason: object) -> bool:
    return _external_tts_blocker_code(reason) == "provider_balance_or_prebuilt_characters"


def _removed_local_piper_render_result(voice_selection: dict[str, object]) -> dict[str, object]:
    return {
        "status": "blocked",
        "reason": "local_piper_fallback_removed",
        "provider": "piper_local_fast",
        "voice_selection": voice_selection,
        "replacement_voice_required": False,
    }


def render_unmixr_chapter_audio(*, job_dir: Path, chapters: tuple[EpubChapter, ...], metadata: EpubMetadata) -> dict[str, object]:
    audio_dir = job_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    cinematic_track_input = _collect_cinematic_track_input(job_dir=job_dir, chapters=chapters) if _audiobook_cinematic_narration() else ()
    cinematic_track_signature = _cinematic_track_signature(chapter_inputs=cinematic_track_input)
    if _audiobook_cinematic_narration():
        cinematic_master = _cinematic_master_audio_path(audio_dir)
        cinematic_mode_path = _cinematic_master_audio_mode_path(audio_dir)
        cinematic_signature_path = _cinematic_master_audio_signature_path(audio_dir)
        cinematic_mode = ""
        if cinematic_mode_path.is_file():
            try:
                cinematic_mode = cinematic_mode_path.read_text(encoding="utf-8").strip()
            except OSError:
                cinematic_mode = ""
        cinematic_cached_signature = ""
        if cinematic_signature_path.is_file():
            try:
                cinematic_cached_signature = cinematic_signature_path.read_text(encoding="utf-8").strip()
            except OSError:
                cinematic_cached_signature = ""
        if (
            cinematic_master.is_file()
            and cinematic_mode == _CINEMATIC_MASTER_SINGLE_PASS_MODE
            and cinematic_cached_signature == cinematic_track_signature
        ):
            if cinematic_master.is_file() and cinematic_master.stat().st_size > 0:
                rendered = []
                for chapter in chapters:
                    source_text = (job_dir / "chapters" / chapter.text_path).read_text(encoding="utf-8")
                    normalized_source_text = str(source_text or "").strip()
                    if not normalized_source_text:
                        rendered.append({"chapter": chapter.index, "status": "skipped_empty"})
                        continue
                    rendered.append(
                        {
                            "chapter": chapter.index,
                            "status": "already_present",
                            "path": cinematic_master.name,
                            "segment_count": 1,
                            "audio_quality": _rendered_audio_quality_report(cinematic_master),
                        }
                    )
                return {
                    "status": "already_rendered",
                    "reason": "cinematic_master_present",
                    "chapters": rendered,
                    "voice_selection": dict(selected_unmixr_voice_for_job(job_dir) or select_unmixr_voice_for_book(metadata=metadata, chapters=chapters, job_dir=job_dir)).get(
                        "public",
                        {},
                    ),
                    "cinematic_master_audio": str(cinematic_master),
                }

        if cinematic_master.is_file() and cinematic_master.stat().st_size > 0:
            try:
                cinematic_master.unlink()
                cinematic_mode_path.unlink()
                cinematic_signature_path.unlink()
            except OSError:
                pass
    elif _audio_inputs_ready(job_dir, chapters):
        return {"status": "already_rendered", "reason": "chapter_audio_present"}
    voice_selection = selected_unmixr_voice_for_job(job_dir) or select_unmixr_voice_for_book(
        metadata=metadata,
        chapters=chapters,
        job_dir=job_dir,
    )
    public_voice_selection = dict(voice_selection.get("public") or {})
    selected_public = dict(public_voice_selection.get("selected") or {})
    if str(selected_public.get("provider") or "").strip() == "piper_local_fast":
        return _removed_local_piper_render_result(public_voice_selection)
    if not unmixr_auto_render_enabled():
        return {"status": "blocked", "reason": "external_tts_disabled_or_auto_render_off"}
    voice_id = str(voice_selection.get("voice_id") or "").strip()
    if not voice_id:
        return {
            "status": "blocked",
            "reason": str(voice_selection.get("reason") or "unmixr_voice_selection_missing"),
            "voice_selection": dict(voice_selection.get("public") or {}),
        }
    render_language = _normalize_language(metadata.language)
    language_mismatch = _selected_voice_language_mismatch(metadata=metadata, voice_selection=voice_selection)
    if language_mismatch:
        return {
            "status": "blocked",
            "reason": "selected_voice_language_mismatch",
            "provider": "unmixr",
            "voice_selection": dict(voice_selection.get("public") or {}),
            "voice_language_mismatch": language_mismatch,
        }
    # This path uses Unmixr's short TTS endpoint. Keep segments conservative; long-form
    # Studio/Narration imports are a separate provider workflow.
    max_chars = _env_int("EA_AUDIOBOOK_UNMIXR_MAX_CHARS_PER_REQUEST", 1800, minimum=1000, maximum=200000)
    cinematic_max_chars = _audiobook_cinematic_max_chars_per_request()
    pacing_policy = _unmixr_bulk_pacing_policy(job_dir=job_dir, chapters=chapters)
    segments_rendered_this_run = 0
    rendered: list[dict[str, object]] = []
    if _audiobook_cinematic_narration():
        cinematic_master = _cinematic_master_audio_path(audio_dir)
        cinematic_track_chapters: list[tuple[EpubChapter, str]] = [item for item in cinematic_track_input if item[1]]
        for chapter, text in cinematic_track_input:
            if not text:
                rendered.append({"chapter": chapter.index, "status": "skipped_empty"})

        if not cinematic_track_chapters:
            return {"status": "rendered", "chapters": rendered, "voice_selection": dict(voice_selection.get("public") or {})}

        cinematic_text = " ".join(source_text for _, source_text in cinematic_track_chapters)
        if _audiobook_cinematic_single_pass():
            segment_rows = ({"text": cinematic_text, "paragraph_break_after": False},)
        else:
            segment_rows = tuple(
                {"text": segment, "paragraph_break_after": False}
                for segment in _chapter_text_segments(cinematic_text, max_chars=cinematic_max_chars)
            )
        if not segment_rows:
            for chapter, _ in cinematic_track_chapters:
                rendered.append({"chapter": chapter.index, "status": "skipped_empty"})
            return {"status": "rendered", "chapters": rendered, "voice_selection": dict(voice_selection.get("public") or {})}

        part_dir = audio_dir / "_cinematic-parts"
        segment_paths: list[Path] = []
        content_types: list[str] = []
        retry_errors: list[str] = []
        segment_audio_quality: list[dict[str, object]] = []

        for segment_index, segment_row in enumerate(segment_rows, start=1):
            segment = str(segment_row.get("text") or "").strip()
            if not segment:
                continue
            segment_target = cinematic_master if _audiobook_cinematic_single_pass() else part_dir / f"_cinematic-{segment_index:03d}.wav"
            if segment_target.is_file() and segment_target.stat().st_size > 0:
                segment_paths.append(segment_target)
                content_types.append("existing")
                segment_audio_quality.append(_rendered_audio_quality_report(segment_target))
                continue
            if bool(pacing_policy.get("enabled")) and segments_rendered_this_run >= int(pacing_policy.get("max_segments_per_run") or 0):
                wait_seconds = int(pacing_policy.get("wait_seconds") or 0)
                return {
                    "status": "provider_pacing_wait",
                    "reason": "unmixr_segment_pacing_limit",
                    "provider": "unmixr",
                    "provider_wait_seconds": wait_seconds,
                    "provider_retry_after": (datetime.now(UTC) + timedelta(seconds=wait_seconds)).isoformat().replace("+00:00", "Z"),
                    "chapter_index": cinematic_track_chapters[0][0].index,
                    "segment_index": segment_index,
                    "segment_count": len(segment_rows),
                    "segments_rendered_this_run": segments_rendered_this_run,
                    "pacing": pacing_policy,
                    "voice_selection": dict(voice_selection.get("public") or {}),
                }
            try:
                audio_bytes, content_type, segment_retry_errors = _synthesize_unmixr_with_retries(
                    text=segment,
                    voice_id=voice_id,
                    lang=render_language,
                    speaking_rate=unmixr_speaking_rate(),
                    speaking_pitch=unmixr_speaking_pitch(),
                    speaking_volume=unmixr_speaking_volume(),
                )
            except Exception as exc:
                detail = _exception_detail(exc)
                wait_seconds = _provider_wait_seconds_from_text(detail)
                if wait_seconds:
                    return {
                        "status": "provider_throttled",
                        "reason": detail,
                        "provider": "unmixr",
                        "provider_wait_seconds": wait_seconds,
                        "provider_retry_after": (datetime.now(UTC) + timedelta(seconds=wait_seconds)).isoformat().replace("+00:00", "Z"),
                        "chapter_index": cinematic_track_chapters[0][0].index,
                        "segment_index": segment_index,
                        "segment_count": len(segment_rows),
                        "voice_selection": dict(voice_selection.get("public") or {}),
                    }
                if _provider_balance_blocker(detail):
                    return {
                        "status": "blocked",
                        "reason": detail or "unmixr_tts_failed",
                        "provider": "unmixr",
                        "chapter_index": cinematic_track_chapters[0][0].index,
                        "segment_index": segment_index,
                        "segment_count": len(segment_rows),
                        "voice_selection": dict(voice_selection.get("public") or {}),
                        "replacement_voice_required": True,
                    }
                return {
                    "status": "blocked",
                    "reason": detail or "unmixr_tts_failed",
                    "provider": "unmixr",
                    "chapter_index": cinematic_track_chapters[0][0].index,
                    "segment_index": segment_index,
                    "segment_count": len(segment_rows),
                    "voice_selection": dict(voice_selection.get("public") or {}),
                    "replacement_voice_required": False,
                }
            retry_errors.extend(segment_retry_errors)
            rendered_segment = _write_provider_audio_file(
                audio_bytes=audio_bytes,
                content_type=content_type,
                target_wav=segment_target,
            )
            segments_rendered_this_run += 1
            segment_paths.append(rendered_segment)
            content_types.append(content_type)
            segment_audio_quality.append(_rendered_audio_quality_report(rendered_segment))
        if not _audiobook_cinematic_single_pass() and not _merge_audio_segments_to_wav(segment_paths=tuple(segment_paths), target=cinematic_master):
            return {
                "status": "blocked",
                "reason": "cinematic_master_merge_failed",
                "segment_count": len(segment_paths),
                "segment_merge_input_count": len(segment_paths),
            }
        cinematic_audio_quality = _rendered_audio_quality_report(cinematic_master)
        try:
            cinematic_mode_path.write_text(_CINEMATIC_MASTER_SINGLE_PASS_MODE, encoding="utf-8")
            cinematic_signature_path = _cinematic_master_audio_signature_path(audio_dir)
            cinematic_signature_path.write_text(cinematic_track_signature, encoding="utf-8")
        except OSError:
            pass
        rendered = []
        for chapter in chapters:
            source_text = (job_dir / "chapters" / chapter.text_path).read_text(encoding="utf-8")
            if not str(source_text or "").strip():
                rendered.append({"chapter": chapter.index, "status": "skipped_empty"})
                continue
            rendered.append(
                {
                    "chapter": chapter.index,
                    "status": "rendered",
                    "path": cinematic_master.name,
                    "segment_count": len(segment_rows),
                    "paragraph_pause_count": 0,
                    "paragraph_pause_seconds": 0.0,
                    "content_types": content_types,
                    "retry_errors": retry_errors,
                    "audio_quality": cinematic_audio_quality,
                    "segment_audio_quality": segment_audio_quality,
                }
            )
        return {
            "status": "rendered",
            "chapters": rendered,
            "voice_selection": dict(voice_selection.get("public") or {}),
            "cinematic_master_audio": str(cinematic_master),
        }

    for chapter in chapters:
        target = audio_dir / chapter.audio_filename
        if target.is_file() and target.stat().st_size > 0:
            rendered.append(
                {
                    "chapter": chapter.index,
                    "status": "already_present",
                    "path": target.name,
                    "audio_quality": _rendered_audio_quality_report(target),
                }
            )
            continue
        source_text = (job_dir / "chapters" / chapter.text_path).read_text(encoding="utf-8")
        normalized_source_text = str(source_text or "").strip()
        if not normalized_source_text:
            rendered.append({"chapter": chapter.index, "status": "skipped_empty"})
            continue

        segment_rows = _chapter_text_segment_rows(normalized_source_text, max_chars=max_chars)
        if not segment_rows:
            rendered.append({"chapter": chapter.index, "status": "skipped_empty"})
            continue

        segment_paths: list[Path] = []
        merge_paths: list[Path] = []
        content_types: list[str] = []
        retry_errors: list[str] = []
        segment_audio_quality: list[dict[str, object]] = []
        paragraph_pause_count = 0
        paragraph_pause_seconds = _audiobook_paragraph_pause_seconds() if _audiobook_paragraph_pauses_enabled() else 0.0
        part_dir = audio_dir / f"{chapter.index:03d}-parts"
        for segment_index, segment_row in enumerate(segment_rows, start=1):
            segment = str(segment_row.get("text") or "")
            segment_target = target if len(segment_rows) == 1 else part_dir / f"{chapter.index:03d}-{segment_index:02d}.wav"
            existing_segment = _chapter_audio_path(
                segment_target.parent,
                EpubChapter(
                    index=chapter.index,
                    title=chapter.title,
                    source_href=chapter.source_href,
                    text_path=chapter.text_path,
                    audio_filename=segment_target.name,
                    char_count=len(segment),
                    sha256=_sha256_bytes(segment.encode("utf-8")),
                ),
            )
            if existing_segment is not None:
                segment_paths.append(existing_segment)
                merge_paths.append(existing_segment)
                if bool(segment_row.get("paragraph_break_after")) and len(segment_rows) > 1:
                    paragraph_pause_count += 1
                    merge_paths.append(
                        _write_silence_wav(
                            part_dir / f"{chapter.index:03d}-{segment_index:02d}-paragraph-pause.wav",
                            seconds=paragraph_pause_seconds,
                        )
                    )
                content_types.append("existing")
                segment_audio_quality.append(_rendered_audio_quality_report(existing_segment))
                continue
            if bool(pacing_policy.get("enabled")) and segments_rendered_this_run >= int(
                pacing_policy.get("max_segments_per_run") or 0
            ):
                wait_seconds = int(pacing_policy.get("wait_seconds") or 0)
                return {
                    "status": "provider_pacing_wait",
                    "reason": "unmixr_segment_pacing_limit",
                    "provider": "unmixr",
                    "provider_wait_seconds": wait_seconds,
                    "provider_retry_after": (datetime.now(UTC) + timedelta(seconds=wait_seconds))
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "chapter_index": chapter.index,
                    "segment_index": segment_index,
                    "segment_count": len(segment_rows),
                    "segments_rendered_this_run": segments_rendered_this_run,
                    "pacing": pacing_policy,
                    "voice_selection": dict(voice_selection.get("public") or {}),
                }
            try:
                audio_bytes, content_type, segment_retry_errors = _synthesize_unmixr_with_retries(
                    text=segment,
                    voice_id=voice_id,
                    lang=render_language,
                    speaking_rate=unmixr_speaking_rate(),
                    speaking_pitch=unmixr_speaking_pitch(),
                    speaking_volume=unmixr_speaking_volume(),
                )
            except Exception as exc:
                detail = _exception_detail(exc)
                wait_seconds = _provider_wait_seconds_from_text(detail)
                if wait_seconds:
                    return {
                        "status": "provider_throttled",
                        "reason": detail,
                        "provider": "unmixr",
                        "provider_wait_seconds": wait_seconds,
                        "provider_retry_after": (datetime.now(UTC) + timedelta(seconds=wait_seconds))
                        .isoformat()
                        .replace("+00:00", "Z"),
                        "chapter_index": chapter.index,
                        "segment_index": segment_index,
                        "segment_count": 1,
                        "voice_selection": dict(voice_selection.get("public") or {}),
                    }
                if _provider_balance_blocker(detail):
                    return {
                        "status": "blocked",
                        "reason": detail or "unmixr_tts_failed",
                        "provider": "unmixr",
                        "chapter_index": chapter.index,
                        "segment_index": segment_index,
                        "segment_count": len(segment_rows),
                        "voice_selection": dict(voice_selection.get("public") or {}),
                        "replacement_voice_required": True,
                    }
                return {
                    "status": "blocked",
                    "reason": detail or "unmixr_tts_failed",
                    "provider": "unmixr",
                    "chapter_index": chapter.index,
                    "segment_index": segment_index,
                    "segment_count": len(segment_rows),
                    "voice_selection": dict(voice_selection.get("public") or {}),
                }
            retry_errors.extend(segment_retry_errors)
            rendered_segment = _write_provider_audio_file(
                audio_bytes=audio_bytes,
                content_type=content_type,
                target_wav=segment_target,
            )
            segments_rendered_this_run += 1
            segment_paths.append(rendered_segment)
            merge_paths.append(rendered_segment)
            if bool(segment_row.get("paragraph_break_after")) and len(segment_rows) > 1:
                paragraph_pause_count += 1
                merge_paths.append(
                    _write_silence_wav(
                        part_dir / f"{chapter.index:03d}-{segment_index:02d}-paragraph-pause.wav",
                        seconds=paragraph_pause_seconds,
                    )
                )
            content_types.append(content_type)
            segment_audio_quality.append(_rendered_audio_quality_report(rendered_segment))
        if len(merge_paths) > 1:
            if _merge_audio_segments_to_wav(segment_paths=tuple(merge_paths), target=target):
                rendered_path = target
            else:
                return {
                    "status": "blocked",
                    "reason": "chapter_segment_merge_failed",
                    "chapter_index": chapter.index,
                    "segment_count": len(segment_paths),
                    "merge_input_count": len(merge_paths),
                }
        else:
            rendered_path = segment_paths[0]
        chapter_audio_quality = _rendered_audio_quality_report(rendered_path)
        rendered.append(
            {
                "chapter": chapter.index,
                "status": "rendered",
                "path": rendered_path.name,
                "segment_count": len(segment_paths),
                "paragraph_pause_count": paragraph_pause_count,
                "paragraph_pause_seconds": round(paragraph_pause_seconds, 3) if paragraph_pause_count else 0.0,
                "content_types": content_types,
                "retry_errors": retry_errors,
                "audio_quality": chapter_audio_quality,
                "segment_audio_quality": segment_audio_quality,
            }
        )
    return {"status": "rendered", "chapters": rendered, "voice_selection": dict(voice_selection.get("public") or {})}


def _load_job(job_dir: Path) -> dict[str, object]:
    path = job_dir / "job.json"
    if not path.is_file():
        raise RuntimeError("audiobook_job_manifest_missing")
    return json.loads(path.read_text(encoding="utf-8"))


def _load_cleanup_job(job_dir: Path) -> tuple[dict[str, object], str]:
    try:
        return _load_job(job_dir), "job.json"
    except json.JSONDecodeError:
        receipt_path = job_dir / "job_receipt.json"
        if not receipt_path.is_file():
            raise
        loaded = json.loads(receipt_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise
        return loaded, "job_receipt.json"


def _write_job(job_dir: Path, payload: dict[str, object]) -> None:
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "job.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _path_storage_kind(path: Path) -> str:
    try:
        resolved = path.expanduser().resolve()
    except Exception:
        resolved = path.expanduser()
    try:
        resolved.relative_to(_durable_storage_root())
        return "durable"
    except ValueError:
        pcloud = _legacy_pcloud_root()
        if pcloud is not None:
            try:
                resolved.relative_to(pcloud)
                return "pcloud"
            except ValueError:
                pass
        return "local"


def _durable_or_allowed(path: Path) -> bool:
    if _env_bool("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", False):
        return True
    return _path_storage_kind(path) in {"durable", "pcloud"} and _durable_storage_available_for_path(path)


def _file_count_and_bytes(path: Path, pattern: str) -> dict[str, int]:
    if not path.is_dir():
        return {"count": 0, "bytes": 0}
    files = [item for item in path.glob(pattern) if item.is_file()]
    return {
        "count": len(files),
        "bytes": sum(int(item.stat().st_size or 0) for item in files),
    }


def _safe_receipt_chapters(chapters: list[object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in chapters:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "index": int(item.get("index") or 0),
                "title": str(item.get("title") or "").strip(),
                "char_count": int(item.get("char_count") or 0),
                "text_sha256": str(item.get("sha256") or "").strip(),
                "audio_filename": Path(str(item.get("audio_filename") or "")).name,
            }
        )
    return rows


def _audio_quality_reports_from_render_result(render_result: dict[str, object]) -> list[dict[str, object]]:
    reports: list[dict[str, object]] = []
    for item in list(render_result.get("chapters") or []):
        if not isinstance(item, dict):
            continue
        audio_quality = item.get("audio_quality")
        if isinstance(audio_quality, dict):
            reports.append(audio_quality)
        for segment_quality in list(item.get("segment_audio_quality") or []):
            if isinstance(segment_quality, dict):
                reports.append(segment_quality)
    return reports


def _audio_quality_receipt_summary(render_result: dict[str, object]) -> dict[str, object]:
    reports = _audio_quality_reports_from_render_result(render_result)
    checked_reports = [
        report
        for report in reports
        if str(report.get("status") or "").strip().lower() not in {"", "skipped"}
    ]
    issue_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    for report in checked_reports:
        status = str(report.get("status") or "unknown").strip().lower() or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1
        for issue in list(report.get("issues") or []):
            key = str(issue or "").strip().lower()
            if key:
                issue_counts[key] = issue_counts.get(key, 0) + 1
    if not checked_reports:
        status = "not_checked"
    elif status_counts.get("failed", 0):
        status = "failed"
    elif status_counts.get("warn", 0):
        status = "warn"
    else:
        status = "pass"
    return {
        "status": status,
        "checked_files": len(checked_reports),
        "passed_files": status_counts.get("pass", 0),
        "warned_files": status_counts.get("warn", 0),
        "failed_files": status_counts.get("failed", 0),
        "quiet_tail_count": issue_counts.get("quiet_tail", 0),
        "trailing_silence_count": issue_counts.get("trailing_silence", 0),
        "speech_energy_missing_count": issue_counts.get("speech_energy_missing", 0),
        "issue_counts": issue_counts,
        "raw_audio_paths_exposed": False,
    }


def _audio_publication_stt_receipt_summary(audio_publication_gate: dict[str, object]) -> dict[str, object]:
    stt_gate = dict(audio_publication_gate.get("stt") or {})
    sample_summaries: list[dict[str, object]] = []
    for sample in list(stt_gate.get("samples") or []):
        if not isinstance(sample, dict):
            continue
        sample_summaries.append(
            {
                "index": int(sample.get("index") or 0),
                "status": str(sample.get("status") or "").strip(),
                "issue": str(sample.get("issue") or "").strip(),
                "warning": str(sample.get("warning") or "").strip(),
                "attempt_count": int(sample.get("attempt_count") or 0),
                "transcriber": str(sample.get("transcriber") or "").strip(),
                "transcript_sha256": str(sample.get("transcript_sha256") or "").strip(),
                "transcript_token_count": int(sample.get("transcript_token_count") or 0),
                "book_token_overlap": float(sample.get("book_token_overlap") or 0.0),
                "book_unique_token_overlap": float(sample.get("book_unique_token_overlap") or 0.0),
                "extractor_seek_mode": str(sample.get("extractor_seek_mode") or "").strip(),
                "raw_text_exposed": False,
            }
        )
    return {
        "status": str(stt_gate.get("status") or "").strip(),
        "enabled": bool(stt_gate.get("enabled")),
        "required": bool(stt_gate.get("required")),
        "sample_count": int(stt_gate.get("sample_count") or 0),
        "sample_seconds": int(stt_gate.get("sample_seconds") or 0),
        "passed_samples": int(stt_gate.get("passed_samples") or 0),
        "failed_samples": int(stt_gate.get("failed_samples") or 0),
        "issues": list(stt_gate.get("issues") or []) if isinstance(stt_gate.get("issues"), list) else [],
        "warnings": list(stt_gate.get("warnings") or []) if isinstance(stt_gate.get("warnings"), list) else [],
        "min_transcript_tokens": int(stt_gate.get("min_transcript_tokens") or 0),
        "min_book_token_overlap": float(stt_gate.get("min_book_token_overlap") or 0.0),
        "source_text_sha256": str(stt_gate.get("source_text_sha256") or "").strip(),
        "source_token_count": int(stt_gate.get("source_token_count") or 0),
        "samples": sample_summaries,
        "raw_text_exposed": False,
    }


def build_audiobook_job_receipt(*, job_dir: Path, observed_at: datetime | None = None) -> dict[str, object]:
    job = _load_job(job_dir)
    observed = observed_at or datetime.now(UTC)
    metadata = dict(job.get("metadata") or {})
    provider = dict(job.get("provider") or {})
    render_result = dict(job.get("render_result") or {})
    merge_result = dict(job.get("merge_result") or {})
    import_result = dict(job.get("audiobookshelf_import") or {})
    telegram = dict(job.get("telegram") or {})
    whatsapp = dict(job.get("whatsapp") or {})
    source = dict(job.get("source") or {})
    storage = dict(job.get("storage") or {})
    output_file_raw = str(merge_result.get("output_file") or "").strip()
    imported_path_raw = str(import_result.get("target_path") or "").strip()
    output_file = Path(output_file_raw) if output_file_raw else None
    imported_path = Path(imported_path_raw) if imported_path_raw else None
    job_manifest = job_dir / "job.json"
    audio_dir = job_dir / "audio"
    output_dir = job_dir / "output"
    part_files = [item for item in audio_dir.glob("*-parts/*") if item.is_file()] if audio_dir.is_dir() else []
    chapter_audio = _file_count_and_bytes(audio_dir, "*.wav")
    output_files = _file_count_and_bytes(output_dir, "*")
    source_epub = Path(str(source.get("source_epub") or storage.get("source_epub") or ""))
    source_epub_sha = str(source.get("source_sha256") or metadata.get("source_sha256") or "").strip()
    if not source_epub_sha and source_epub.is_file():
        source_epub_sha = _sha256_file(source_epub)

    player_reference = dict(import_result.get("player_scoped_reference") or {})
    public_share = dict(import_result.get("public_share") or {})
    public_share_status_for_receipt = str(public_share.get("status") or "").strip()
    public_share_url_for_receipt = (
        str(public_share.get("absolute_url") or "").strip()
        if public_share_status_for_receipt == "public_share_ready"
        else ""
    )
    public_share_delivery = dict(public_share.get("telegram_delivery") or {})
    if not public_share_delivery:
        direct_share_delivery = dict(telegram.get("audiobook_public_share_delivery") or {})
        if direct_share_delivery:
            public_share_delivery = {
                "status": str(direct_share_delivery.get("status") or "").strip(),
                "notified_at": str(direct_share_delivery.get("sent_at") or "").strip(),
                "message_id": direct_share_delivery.get("message_id"),
                "reason": str(direct_share_delivery.get("reason") or "").strip(),
                "callback_tokens_exposed": False,
                "audiobookshelf_token_exposed": False,
            }
    whatsapp_public_share_delivery = dict(public_share.get("whatsapp_delivery") or {})
    if not whatsapp_public_share_delivery:
        whatsapp_public_share_delivery = dict(whatsapp.get("public_share_delivery") or {})
    whatsapp_public_share_message_hash = str(whatsapp_public_share_delivery.get("message_id_sha256") or "").strip()
    raw_whatsapp_public_share_message_id = str(whatsapp_public_share_delivery.get("message_id") or "").strip()
    if not whatsapp_public_share_message_hash and raw_whatsapp_public_share_message_id:
        whatsapp_public_share_message_hash = _sha256_bytes(raw_whatsapp_public_share_message_id.encode("utf-8"))
    public_share_playback_e2e = dict(public_share.get("playback_e2e") or {})
    playback_acceptance = dict(job.get("playback_acceptance") or {})
    audio_publication_gate = _audiobook_publication_gate(job)
    voice_sample_delivery = dict(telegram.get("voice_sample_delivery") or {})
    retry_after = str(render_result.get("provider_retry_after") or "").strip()
    external_tts_blocker_reason = str(render_result.get("reason") or job.get("next_action") or "").strip()
    raw_next_action = str(job.get("next_action") or "").strip()
    scheduler_next_action = raw_next_action
    receipt_next_action = raw_next_action
    if str(job.get("status") or "").strip() == "blocked_external_tts" and _external_tts_blocker_code(
        external_tts_blocker_reason
    ):
        scheduler_next_action = (
            "retry_external_tts_after_provider_blocker"
            if _external_tts_blocker_is_retryable(external_tts_blocker_reason)
            else "resolve_external_tts_provider_blocker"
        )
        receipt_next_action = scheduler_next_action
    external_tts_retry_at = _audiobook_job_external_tts_retry_at(job)
    priority_score = _audiobook_resume_priority(job)
    priority_label = _audiobook_resume_priority_label(job)
    wait_kind = _audiobook_wait_kind(render_result)
    privacy = {
        "raw_book_text_in_receipt": False,
        "source_epub_path_exposed": False,
        "chapter_text_path_exposed": False,
        "telegram_chat_id_exposed": False,
        "telegram_message_id_exposed": False,
        "telegram_file_url_exposed": False,
        "telegram_token_exposed": False,
        "provider_voice_id_exposed": False,
        "provider_secret_exposed": False,
        "audiobookshelf_token_exposed": False,
        "audiobookshelf_raw_path_exposed": False,
        "private_job_path_exposed": False,
        "whatsapp_sender_ref_exposed": False,
        "whatsapp_message_id_exposed": False,
    }
    receipt = {
        "contract_name": AUDIOBOOK_JOB_RECEIPT_CONTRACT_NAME,
        "status": str(job.get("status") or "").strip(),
        "observed_at": observed.isoformat().replace("+00:00", "Z"),
        "job_id": str(job.get("job_id") or job_dir.name).strip(),
        "job_dir_name": job_dir.name,
        "updated_at": str(job.get("updated_at") or "").strip(),
        "next_action": receipt_next_action,
        "source": {
            "kind": str(source.get("kind") or "").strip(),
            "priority_for_resume": priority_score == 0,
            "rights_basis": str(source.get("rights_basis") or "").strip(),
            "source_filename": Path(str(source.get("source_filename") or metadata.get("source_filename") or "")).name,
            "source_sha256": source_epub_sha,
            "source_url_sha256": str(telegram.get("source_url_sha256") or "").strip(),
        },
        "metadata": {
            "title": str(metadata.get("title") or "").strip(),
            "author": str(metadata.get("author") or "").strip(),
            "language": str(metadata.get("language") or "").strip(),
        },
        "totals": dict(job.get("totals") or {}),
        "chapters": _safe_receipt_chapters(list(job.get("chapters") or [])),
        "render": {
            "status": str(render_result.get("status") or "").strip(),
            "provider": str(render_result.get("provider") or provider.get("preferred") or "").strip(),
            "chapter_index": int(render_result.get("chapter_index") or 0),
            "segment_index": int(render_result.get("segment_index") or 0),
            "segment_count": int(render_result.get("segment_count") or 0),
            "provider_wait_seconds": int(render_result.get("provider_wait_seconds") or 0),
            "provider_retry_after": retry_after,
            "external_tts_blocker_code": _external_tts_blocker_code(external_tts_blocker_reason),
            "external_tts_blocker_retryable": _external_tts_blocker_is_retryable(external_tts_blocker_reason),
            "external_tts_blocker_reason_sha256": _sha256_bytes(external_tts_blocker_reason.encode("utf-8"))
            if external_tts_blocker_reason
            else "",
            "wait_kind": wait_kind,
            "pacing": dict(render_result.get("pacing") or {}),
            "chapter_audio_files": chapter_audio["count"],
            "chapter_audio_bytes": chapter_audio["bytes"],
            "segment_part_files": len(part_files),
            "segment_part_bytes": sum(int(item.stat().st_size or 0) for item in part_files),
            "voice_selection": dict(provider.get("voice_selection") or render_result.get("voice_selection") or {}),
            "audio_quality": _audio_quality_receipt_summary(render_result),
        },
        "assembly": {
            "status": str(merge_result.get("status") or "").strip(),
            "provider": str(merge_result.get("provider") or ("m4b-tool" if merge_result.get("command") else "")).strip(),
            "output_file_ready": bool(output_file and output_file.is_file()),
            "output_file_sha256": _sha256_file(output_file) if output_file and output_file.is_file() else "",
            "output_files": output_files["count"],
            "output_bytes": output_files["bytes"],
            "chapter_metadata_embedded": str(merge_result.get("status") or "").strip() == "m4b_ready"
            and int(merge_result.get("chapter_count") or len(list(job.get("chapters") or []))) > 0,
            "cover_embedded": bool(merge_result.get("cover_embedded")),
            "cover_filename": Path(str(merge_result.get("cover_filename") or "")).name,
        },
        "audiobookshelf_import": {
            "status": str(import_result.get("status") or "").strip(),
            "target_storage_kind": _path_storage_kind(imported_path) if imported_path else "",
            "target_file_ready": bool(imported_path and imported_path.is_file()),
            "target_file_sha256": _sha256_file(imported_path) if imported_path and imported_path.is_file() else "",
            "player_scoped_reference_status": str(player_reference.get("status") or "").strip(),
            "player_scoped_reference_token_sha256": str(player_reference.get("token_sha256") or "").strip(),
            "public_share_status": public_share_status_for_receipt,
            "public_share_url": public_share_url_for_receipt,
            "public_share_url_suppressed": bool(public_share.get("absolute_url")) and public_share_status_for_receipt != "public_share_ready",
            "public_share_slug_sha256": str(public_share.get("slug_sha256") or "").strip(),
            "public_share_token_exposed": bool(public_share.get("token_exposed")),
            "public_share_raw_library_path_exposed": bool(public_share.get("raw_library_path_exposed")),
            "public_share_telegram_followup_pending": bool(public_share.get("telegram_followup_pending")),
            "public_share_telegram_delivery_status": str(public_share_delivery.get("status") or "").strip(),
            "public_share_telegram_notified_at": str(public_share_delivery.get("notified_at") or "").strip(),
            "public_share_telegram_message_id_present": bool(str(public_share_delivery.get("message_id") or "").strip()),
            "public_share_telegram_message_id_sha256": _sha256_bytes(
                str(public_share_delivery.get("message_id") or "").encode("utf-8")
            )
            if str(public_share_delivery.get("message_id") or "").strip()
            else "",
            "public_share_telegram_delivery_reason": str(public_share_delivery.get("reason") or "").strip(),
            "public_share_telegram_callback_tokens_exposed": bool(public_share_delivery.get("callback_tokens_exposed")),
            "public_share_telegram_audiobookshelf_token_exposed": bool(public_share_delivery.get("audiobookshelf_token_exposed")),
            "public_share_whatsapp_followup_pending": bool(public_share.get("whatsapp_followup_pending")),
            "public_share_whatsapp_delivery_status": str(whatsapp_public_share_delivery.get("status") or "").strip(),
            "public_share_whatsapp_notified_at": str(whatsapp_public_share_delivery.get("notified_at") or "").strip(),
            "public_share_whatsapp_message_id_present": bool(whatsapp_public_share_message_hash),
            "public_share_whatsapp_message_id_sha256": whatsapp_public_share_message_hash,
            "public_share_whatsapp_delivery_reason": str(whatsapp_public_share_delivery.get("reason") or "").strip(),
            "public_share_whatsapp_callback_tokens_exposed": bool(
                whatsapp_public_share_delivery.get("callback_tokens_exposed")
            ),
            "public_share_whatsapp_audiobookshelf_token_exposed": bool(
                whatsapp_public_share_delivery.get("audiobookshelf_token_exposed")
            ),
            "public_share_playback_e2e_status": str(public_share_playback_e2e.get("status") or "").strip(),
            "public_share_playback_e2e_browser": str(public_share_playback_e2e.get("browser") or "").strip(),
            "public_share_playback_e2e_checked_at": str(public_share_playback_e2e.get("checked_at") or "").strip(),
            "public_share_playback_e2e_reason": str(public_share_playback_e2e.get("reason") or "").strip(),
            "public_share_playback_e2e_page_response_status": int(
                public_share_playback_e2e.get("page_response_status") or 0
            ),
            "public_share_playback_e2e_track_response_status": int(
                public_share_playback_e2e.get("track_response_status") or 0
            ),
            "public_share_playback_e2e_track_content_type": str(
                public_share_playback_e2e.get("track_content_type") or ""
            ).strip(),
            "public_share_playback_e2e_track_response_resource_type": str(
                public_share_playback_e2e.get("track_response_resource_type") or ""
            ).strip(),
            "public_share_playback_e2e_duration_seconds": float(
                public_share_playback_e2e.get("duration_seconds") or 0.0
            ),
            "public_share_playback_e2e_current_time_after_play_seconds": float(
                public_share_playback_e2e.get("current_time_after_play_seconds") or 0.0
            ),
            "public_share_playback_e2e_media_error_present": bool(public_share_playback_e2e.get("media_error")),
            "public_share_playback_e2e_media_error_code": int(public_share_playback_e2e.get("media_error_code") or 0),
        },
        "audio_publication_gate": {
            "status": str(audio_publication_gate.get("status") or "").strip(),
            "issues": list(audio_publication_gate.get("issues") or [])
            if isinstance(audio_publication_gate.get("issues"), list)
            else [],
            "audio_streams": int(audio_publication_gate.get("audio_streams") or 0),
            "cover_streams": int(audio_publication_gate.get("cover_streams") or 0),
            "chapters": int(audio_publication_gate.get("chapters") or 0),
            "duration_seconds": float(audio_publication_gate.get("duration_seconds") or 0.0),
            "target_file_sha256": str(audio_publication_gate.get("target_file_sha256") or "").strip(),
            "target_file_size": int(audio_publication_gate.get("target_file_size") or 0),
            "volume": dict(audio_publication_gate.get("volume") or {}),
            "stt": _audio_publication_stt_receipt_summary(audio_publication_gate),
            "raw_paths_exposed": False,
        },
        "scheduler_resume": {
            "next_action": scheduler_next_action,
            "next_action_sha256": _sha256_bytes(raw_next_action.encode("utf-8")) if raw_next_action else "",
            "retry_after": retry_after
            or (external_tts_retry_at.isoformat().replace("+00:00", "Z") if external_tts_retry_at else ""),
            "external_tts_blocker_retryable": _external_tts_blocker_is_retryable(external_tts_blocker_reason),
            "external_tts_blocker_code": _external_tts_blocker_code(external_tts_blocker_reason),
            "priority_score": priority_score,
            "priority_label": priority_label,
            "priority_source_kinds": list(_priority_audiobook_source_kinds()),
            "resume_state_present": (job_dir / "resume_state.json").is_file(),
        },
        "storage": {
            "job_storage_kind": _path_storage_kind(job_dir),
            "audiobookshelf_storage_kind": _path_storage_kind(audiobookshelf_import_root()),
            "manifest_sha256": _sha256_file(job_manifest) if job_manifest.is_file() else "",
        },
        "telegram": {
            "chat_bound": bool(str(telegram.get("chat_id") or "").strip()),
            "message_bound": bool(str(telegram.get("message_id") or "").strip()),
            "caption_present": bool(str(telegram.get("caption") or "").strip()),
            "caption_sha256": _sha256_bytes(str(telegram.get("caption") or "").encode("utf-8"))
            if str(telegram.get("caption") or "").strip()
            else "",
            "voice_sample_delivery_status": str(voice_sample_delivery.get("status") or "").strip(),
            "voice_sample_delivery_expected_count": int(voice_sample_delivery.get("expected_count") or 0),
            "voice_sample_delivery_attempted_count": int(voice_sample_delivery.get("attempted_count") or 0),
            "voice_sample_delivery_sent_count": int(voice_sample_delivery.get("sent_count") or 0),
            "voice_sample_delivery_failed_count": int(voice_sample_delivery.get("failed_count") or 0),
            "voice_sample_delivery_skipped_count": int(voice_sample_delivery.get("skipped_count") or 0),
            "voice_sample_delivery_reason": str(voice_sample_delivery.get("reason") or "").strip(),
            "voice_sample_callback_tokens_exposed": False,
        },
        "whatsapp": {
            "sender_bound": bool(str(whatsapp.get("sender_ref") or "").strip()),
            "session_bound": bool(str(whatsapp.get("session_ref") or "").strip()),
            "session_ref_sha256": _sha256_bytes(str(whatsapp.get("session_ref") or "").encode("utf-8"))
            if str(whatsapp.get("session_ref") or "").strip()
            else "",
            "source": str(whatsapp.get("source") or "").strip(),
            "message_hash_present": bool(
                str(
                    whatsapp.get("message_id_sha256")
                    or whatsapp.get("last_callback_message_id_sha256")
                    or whatsapp.get("intake_reply_message_id_sha256")
                    or ""
                ).strip()
            ),
            "voice_sample_delivery_status": str(
                dict(whatsapp.get("voice_sample_delivery") or {}).get("status") or ""
            ).strip(),
            "voice_sample_delivery_expected_count": int(
                dict(whatsapp.get("voice_sample_delivery") or {}).get("expected_count") or 0
            ),
            "voice_sample_delivery_attempted_count": int(
                dict(whatsapp.get("voice_sample_delivery") or {}).get("attempted_count") or 0
            ),
            "voice_sample_delivery_sent_count": int(
                dict(whatsapp.get("voice_sample_delivery") or {}).get("sent_count") or 0
            ),
            "voice_sample_delivery_failed_count": int(
                dict(whatsapp.get("voice_sample_delivery") or {}).get("failed_count") or 0
            ),
            "voice_sample_delivery_skipped_count": int(
                dict(whatsapp.get("voice_sample_delivery") or {}).get("skipped_count") or 0
            ),
            "voice_sample_delivery_reason": str(
                dict(whatsapp.get("voice_sample_delivery") or {}).get("reason") or ""
            ).strip(),
            "voice_sample_callback_tokens_exposed": False,
        },
        "playback_acceptance": {
            "contract_name": str(
                playback_acceptance.get("contract_name") or PLAYBACK_ACCEPTANCE_CONTRACT_NAME
            ).strip(),
            "status": str(playback_acceptance.get("status") or "not_recorded").strip(),
            "accepted": playback_acceptance.get("accepted") is True,
            "source": str(playback_acceptance.get("source") or "").strip(),
            "recorded_at": str(playback_acceptance.get("recorded_at") or "").strip(),
            "feedback_sha256": str(playback_acceptance.get("feedback_sha256") or "").strip(),
            "message_id_sha256": str(playback_acceptance.get("message_id_sha256") or "").strip(),
            "public_share_url_sha256": str(playback_acceptance.get("public_share_url_sha256") or "").strip(),
            "audiobookshelf_target_file_sha256": str(
                playback_acceptance.get("audiobookshelf_target_file_sha256") or ""
            ).strip(),
            "telegram_public_share_message_id_sha256": str(
                playback_acceptance.get("telegram_public_share_message_id_sha256") or ""
            ).strip(),
            "whatsapp_public_share_message_id_sha256": str(
                playback_acceptance.get("whatsapp_public_share_message_id_sha256") or ""
            ).strip(),
            "raw_feedback_exposed": bool(playback_acceptance.get("raw_feedback_exposed")),
            "raw_message_id_exposed": bool(playback_acceptance.get("raw_message_id_exposed")),
            "callback_ready": bool(
                str(dict(public_share.get("playback_acceptance_callback") or {}).get("token") or "").strip()
            ),
            "callback_token_exposed": False,
        },
        "privacy": privacy,
    }
    return receipt


def write_audiobook_job_receipt(*, job_dir: Path, output_path: Path) -> dict[str, object]:
    receipt = build_audiobook_job_receipt(job_dir=job_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def _write_current_job_receipt_best_effort(job_dir: Path) -> dict[str, object]:
    try:
        receipt = write_audiobook_job_receipt(job_dir=job_dir, output_path=job_dir / "job_receipt.json")
    except Exception as exc:
        return {"status": "failed", "error": str(exc), "error_type": type(exc).__name__}
    return {
        "status": "written",
        "path": "job_receipt.json",
        "receipt_status": str(receipt.get("status") or "").strip(),
    }


def record_audiobook_playback_acceptance(
    *,
    job_dir: Path,
    accepted: bool = True,
    source: str = "telegram",
    message_id: str = "",
    feedback: str = "",
) -> dict[str, object]:
    job = _load_job(job_dir)
    import_result = dict(job.get("audiobookshelf_import") or {})
    public_share = dict(import_result.get("public_share") or {})
    public_share_delivery = dict(public_share.get("telegram_delivery") or {})
    whatsapp_public_share_delivery = dict(public_share.get("whatsapp_delivery") or {})
    if not whatsapp_public_share_delivery:
        whatsapp_public_share_delivery = dict(dict(job.get("whatsapp") or {}).get("public_share_delivery") or {})
    target_path = Path(str(import_result.get("target_path") or ""))
    public_share_url = str(public_share.get("absolute_url") or "").strip()
    normalized_message_id = str(message_id or "").strip()
    if not normalized_message_id:
        normalized_message_id = str(public_share_delivery.get("message_id") or "").strip()
    whatsapp_public_share_message_hash = str(whatsapp_public_share_delivery.get("message_id_sha256") or "").strip()
    raw_whatsapp_public_share_message_id = str(whatsapp_public_share_delivery.get("message_id") or "").strip()
    if not whatsapp_public_share_message_hash and raw_whatsapp_public_share_message_id:
        whatsapp_public_share_message_hash = _sha256_bytes(raw_whatsapp_public_share_message_id.encode("utf-8"))
    playback_acceptance = {
        "contract_name": PLAYBACK_ACCEPTANCE_CONTRACT_NAME,
        "status": "accepted" if accepted else "rejected",
        "accepted": bool(accepted),
        "source": _normalize_tag(source) or "operator",
        "recorded_at": _now_iso(),
        "feedback_sha256": _sha256_bytes(str(feedback or "").encode("utf-8")) if str(feedback or "").strip() else "",
        "message_id_sha256": _sha256_bytes(normalized_message_id.encode("utf-8")) if normalized_message_id else "",
        "public_share_url_sha256": _sha256_bytes(public_share_url.encode("utf-8")) if public_share_url else "",
        "audiobookshelf_target_file_sha256": _sha256_file(target_path) if target_path.is_file() else "",
        "telegram_public_share_message_id_sha256": _sha256_bytes(
            str(public_share_delivery.get("message_id") or "").encode("utf-8")
        )
        if str(public_share_delivery.get("message_id") or "").strip()
        else "",
        "whatsapp_public_share_message_id_sha256": whatsapp_public_share_message_hash,
        "raw_feedback_exposed": False,
        "raw_message_id_exposed": False,
    }
    job["playback_acceptance"] = playback_acceptance
    job["updated_at"] = _now_iso()
    if accepted:
        job["next_action"] = "playback_accepted"
    else:
        job["next_action"] = "review_audiobook_playback_problem"
    _write_job(job_dir, job)
    _write_current_job_receipt_best_effort(job_dir)
    return job


def _audiobook_public_share_for_job(job: dict[str, object]) -> dict[str, object]:
    import_result = dict(job.get("audiobookshelf_import") or {})
    return dict(import_result.get("public_share") or {})


def _audiobook_publication_gate(job: dict[str, object]) -> dict[str, object]:
    gate = job.get("audio_publication_gate")
    return dict(gate) if isinstance(gate, dict) else {}


def _audiobook_publication_gate_reason(job: dict[str, object]) -> str:
    status = str(job.get("status") or "").strip()
    if status in {"waiting_voice_selection", "blocked_audio_quality"}:
        return status
    gate = _audiobook_publication_gate(job)
    gate_status = str(gate.get("status") or "").strip()
    if gate_status != "pass":
        return "audio_publication_gate_missing" if not gate_status else f"audio_publication_gate_{gate_status}"
    issues = gate.get("issues")
    if isinstance(issues, list) and issues:
        return "audio_publication_gate_has_issues"
    public_share = _audiobook_public_share_for_job(job)
    if str(public_share.get("status") or "").strip() == "revoked_wrong_voice":
        return "public_share_revoked_wrong_voice"
    voice_selection = dict(dict(job.get("provider") or {}).get("voice_selection") or {})
    local_fallback = dict(voice_selection.get("local_fallback_render") or {})
    if str(local_fallback.get("status") or "").strip() == "revoked_wrong_voice":
        return "audiobook_voice_revoked_wrong_voice"
    return ""


def _audiobook_publication_gate_passed(job: dict[str, object]) -> bool:
    return not _audiobook_publication_gate_reason(job)


def _audiobook_public_share_is_ready(job: dict[str, object]) -> bool:
    public_share = _audiobook_public_share_for_job(job)
    return (
        str(public_share.get("status") or "").strip() == "public_share_ready"
        and bool(str(public_share.get("absolute_url") or "").strip())
        and _audiobook_publication_gate_passed(job)
    )


def _audiobook_public_share_acceptance_callback_ready(job: dict[str, object]) -> bool:
    public_share = _audiobook_public_share_for_job(job)
    if str(public_share.get("status") or "").strip() != "public_share_ready":
        return False
    if not str(public_share.get("absolute_url") or "").strip():
        return False
    gate_reason = _audiobook_publication_gate_reason(job)
    return gate_reason in {"", "audio_publication_gate_missing"}


def _audiobook_playback_acceptance_callback_token(job: dict[str, object]) -> str:
    import_result = dict(job.get("audiobookshelf_import") or {})
    public_share = dict(import_result.get("public_share") or {})
    seed = "|".join(
        (
            str(job.get("job_id") or "").strip(),
            str(public_share.get("absolute_url") or "").strip(),
            str(import_result.get("target_path") or "").strip(),
            str(dict(job.get("telegram") or {}).get("chat_id") or "").strip(),
        )
    )
    return _sha256_bytes(seed.encode("utf-8"))[:14] if seed.strip("|") else ""


def ensure_audiobook_playback_acceptance_callback(job: dict[str, object]) -> dict[str, object]:
    if not _audiobook_public_share_acceptance_callback_ready(job):
        return job
    job_dir_raw = str(dict(job.get("storage") or {}).get("job_dir") or "").strip()
    job_dir = Path(job_dir_raw) if job_dir_raw else Path()
    current_job = dict(job)
    if job_dir_raw and job_dir.is_dir():
        try:
            current_job = _load_job(job_dir)
        except Exception:
            current_job = dict(job)
    import_result = dict(current_job.get("audiobookshelf_import") or {})
    public_share = dict(import_result.get("public_share") or {})
    if str(public_share.get("status") or "").strip() != "public_share_ready":
        return current_job
    callback = dict(public_share.get("playback_acceptance_callback") or {})
    token = str(callback.get("token") or "").strip() or _audiobook_playback_acceptance_callback_token(current_job)
    if not token:
        return current_job
    public_share["playback_acceptance_callback"] = {
        "status": "ready",
        "token": token,
        "created_at": str(callback.get("created_at") or _now_iso()).strip(),
        "raw_token_exposed": False,
    }
    import_result["public_share"] = public_share
    current_job["audiobookshelf_import"] = import_result
    current_job["updated_at"] = _now_iso()
    if job_dir_raw and job_dir.is_dir():
        _write_job(job_dir, current_job)
        _write_current_job_receipt_best_effort(job_dir)
    return current_job


def record_audiobook_playback_acceptance_by_callback_token(
    *,
    callback_token: str,
    accepted: bool = True,
    source: str = "telegram_button",
    message_id: str = "",
    feedback: str = "",
) -> dict[str, object]:
    normalized = str(callback_token or "").strip()
    if not normalized:
        raise RuntimeError("audiobook_playback_acceptance_token_missing")
    for manifest_path in iter_audiobook_job_manifests(newest_first=True):
        try:
            job = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        public_share = _audiobook_public_share_for_job(job)
        callback = dict(public_share.get("playback_acceptance_callback") or {})
        candidate = str(callback.get("token") or "").strip() or _audiobook_playback_acceptance_callback_token(job)
        if candidate and hmac.compare_digest(candidate, normalized):
            return record_audiobook_playback_acceptance(
                job_dir=manifest_path.parent,
                accepted=accepted,
                source=source,
                message_id=message_id,
                feedback=feedback,
            )
    raise RuntimeError("audiobook_playback_acceptance_token_not_found")


def _telegram_bot_token() -> str:
    return str(os.getenv("EA_TELEGRAM_BOT_TOKEN") or "").strip()


def _telegram_playback_callback_secret(*, bot_token: str) -> str:
    return str(os.getenv("EA_TELEGRAM_CALLBACK_SECRET") or "").strip() or str(bot_token or "").strip()


def _telegram_audiobook_playback_callback_signature(
    *,
    secret: str,
    action: str,
    token: str,
    chat_id: str,
    expires_at: int,
) -> str:
    payload = "|".join(
        (
            "ap",
            str(action or "").strip().lower(),
            str(token or "").strip(),
            str(chat_id or "").strip(),
            str(int(expires_at)),
        )
    )
    return hmac.new(str(secret or "").encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()[:10]


def _telegram_encode_audiobook_playback_callback(
    *,
    bot_token: str,
    action: str,
    token: str,
    chat_id: str,
) -> str:
    normalized_action = str(action or "").strip().lower()[:1]
    normalized_token = str(token or "").strip()
    normalized_chat_id = str(chat_id or "").strip()
    secret = _telegram_playback_callback_secret(bot_token=bot_token)
    if normalized_action not in {"a", "r"} or not normalized_token or not normalized_chat_id or not secret:
        return ""
    expires_at = int(time.time()) + _env_int("EA_TELEGRAM_CALLBACK_TTL_SECONDS", 3600, minimum=60, maximum=604800)
    signature = _telegram_audiobook_playback_callback_signature(
        secret=secret,
        action=normalized_action,
        token=normalized_token,
        chat_id=normalized_chat_id,
        expires_at=expires_at,
    )
    return f"ap|{normalized_action}|{normalized_token}|{expires_at}|{signature}"


def _telegram_audiobook_playback_acceptance_buttons(
    *,
    job: dict[str, object],
    chat_id: str,
    bot_token: str,
) -> list[list[tuple[str, str]]]:
    if not _audiobook_public_share_acceptance_callback_ready(job):
        return []
    public_share = _audiobook_public_share_for_job(job)
    callback = dict(public_share.get("playback_acceptance_callback") or {})
    token = str(callback.get("token") or "").strip() or _audiobook_playback_acceptance_callback_token(job)
    accepted_callback = _telegram_encode_audiobook_playback_callback(
        bot_token=bot_token,
        action="a",
        token=token,
        chat_id=chat_id,
    )
    rejected_callback = _telegram_encode_audiobook_playback_callback(
        bot_token=bot_token,
        action="r",
        token=token,
        chat_id=chat_id,
    )
    if not accepted_callback or not rejected_callback:
        return []
    return [[("Playback works", accepted_callback), ("Problem", rejected_callback)]]


def _send_telegram_audiobook_status(*, job: dict[str, object], text: str) -> dict[str, object]:
    token = _telegram_bot_token()
    telegram = dict(job.get("telegram") or {})
    chat_id = str(telegram.get("chat_id") or "").strip()
    if not token or not chat_id:
        return {"status": "skipped", "reason": "telegram_token_or_chat_missing"}
    params = {"chat_id": chat_id, "text": text}
    inline_buttons = _telegram_audiobook_playback_acceptance_buttons(job=job, chat_id=chat_id, bot_token=token)
    if inline_buttons:
        params["reply_markup"] = json.dumps(
            {
                "inline_keyboard": [
                    [
                        {"text": str(label or "").strip(), "callback_data": str(callback_data or "").strip()}
                        for label, callback_data in row
                        if str(label or "").strip() and str(callback_data or "").strip()
                    ]
                    for row in inline_buttons
                    if row
                ]
            },
            separators=(",", ":"),
        )
    message_id = str(telegram.get("message_id") or "").strip()
    if message_id:
        params["reply_to_message_id"] = message_id
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=urllib.parse.urlencode(params).encode("utf-8"),
    )
    try:
        with urllib.request.urlopen(request, timeout=_env_int("EA_AUDIOBOOK_TELEGRAM_NOTIFY_TIMEOUT_SECONDS", 30, minimum=3)) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {"status": "failed", "reason": type(exc).__name__}
    return {
        "status": "sent" if bool(payload.get("ok")) else "failed",
        "message_id": dict(payload.get("result") or {}).get("message_id"),
    }


def _telegram_audiobookshelf_public_share_reply_text(job: dict[str, object]) -> str:
    metadata = dict(job.get("metadata") or {})
    title = str(metadata.get("title") or metadata.get("source_filename") or "the audiobook").strip()
    imported = dict(job.get("audiobookshelf_import") or {})
    public_share = dict(imported.get("public_share") or {})
    public_share_url = str(public_share.get("absolute_url") or "").strip()
    if str(public_share.get("status") or "") == "public_share_ready" and public_share_url:
        return f"Audiobookshelf finished scanning {title}. Public share link: {public_share_url}."
    return telegram_epub_reply_text(job)


def _audiobook_public_share_attempt_mark_path(job_dir: Path) -> Path:
    return job_dir / "audiobookshelf_share_state.json"


def _recent_public_share_attempt_active(job_dir: Path, *, now: datetime) -> bool:
    path = _audiobook_public_share_attempt_mark_path(job_dir)
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    attempted_at = _parse_iso_datetime(payload.get("attempted_at"))
    if attempted_at is None:
        return False
    cooldown_seconds = _env_int("EA_AUDIOBOOK_PUBLIC_SHARE_ATTEMPT_COOLDOWN_SECONDS", 300, minimum=0, maximum=86400)
    return (now - attempted_at).total_seconds() < cooldown_seconds


def _write_public_share_attempt_mark(job_dir: Path, *, payload: dict[str, object]) -> None:
    path = _audiobook_public_share_attempt_mark_path(job_dir)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


_AUDIOBOOK_PUBLICATION_GATE_RETRYABLE_ISSUES = frozenset(
    {
        "stt_sample_extract_failed",
        "stt_transcription_failed",
    }
)


def _audiobook_publication_gate_issue_names(
    *,
    public_share: dict[str, object],
    gate: dict[str, object],
) -> set[str]:
    issues: set[str] = set()
    if str(public_share.get("status") or "").strip() == "blocked_audio_publication_gate":
        for key in ("reason", "issue"):
            raw = str(public_share.get(key) or "").strip()
            for item in re.split(r"[,;|]+", raw):
                normalized = str(item or "").strip()
                if normalized:
                    issues.add(normalized)
    for key in ("reason", "issue"):
        raw = str(gate.get(key) or "").strip()
        for item in re.split(r"[,;|]+", raw):
            normalized = str(item or "").strip()
            if normalized:
                issues.add(normalized)
    for issue in list(gate.get("issues") or []):
        normalized = str(issue or "").strip()
        if normalized:
            issues.add(normalized)
    stt_gate = dict(gate.get("stt") or {})
    stt_issue = str(stt_gate.get("issue") or "").strip()
    if stt_issue:
        issues.add(stt_issue)
    for sample in list(stt_gate.get("samples") or []):
        if not isinstance(sample, dict):
            continue
        sample_issue = str(sample.get("issue") or "").strip()
        if sample_issue:
            issues.add(sample_issue)
    return issues


def _audiobook_publication_gate_retryable_issues(
    *,
    public_share: dict[str, object],
    gate: dict[str, object],
) -> bool:
    issues = _audiobook_publication_gate_issue_names(public_share=public_share, gate=gate)
    if issues == {"stt_transcript_too_short"}:
        stt_gate = dict(gate.get("stt") or {})
        if str(stt_gate.get("short_book_text_tolerance") or "").strip() != "v1":
            return True
        for sample in list(stt_gate.get("samples") or []):
            if not isinstance(sample, dict):
                continue
            if str(sample.get("issue") or "").strip() != "stt_transcript_too_short":
                continue
            try:
                attempt_count = int(sample.get("attempt_count") or 1)
            except (TypeError, ValueError):
                attempt_count = 1
            if attempt_count <= 1 or str(sample.get("extractor_seek_mode") or "").strip() != "output_side_audio_stream":
                return True
        return False
    return bool(issues) and issues.issubset(_AUDIOBOOK_PUBLICATION_GATE_RETRYABLE_ISSUES)


def _audiobook_public_share_followup_pending(job: dict[str, object]) -> bool:
    if str(job.get("status") or "").strip() != "audiobookshelf_imported":
        return False
    import_result = dict(job.get("audiobookshelf_import") or {})
    if str(import_result.get("status") or "").strip() != "imported":
        return False
    public_share = dict(import_result.get("public_share") or {})
    public_share_status = str(public_share.get("status") or "").strip()
    publication_gate = dict(job.get("audio_publication_gate") or {})
    retryable_share_statuses = {
        "",
        "public_share_disabled",
        "audiobookshelf_api_not_configured",
        "public_share_create_failed",
        "share_failed",
        "audiobookshelf_scan_failed",
        "disabled",
        "missing_config",
        "waiting_for_imported_file",
    }
    if str(publication_gate.get("status") or "").strip() == "fail":
        return (
            audiobookshelf_public_share_enabled()
            and public_share_status in {*retryable_share_statuses, "blocked_audio_publication_gate", "waiting_for_audiobookshelf_scan"}
            and _audiobook_publication_gate_retryable_issues(
                public_share=public_share,
                gate=publication_gate,
            )
        )
    if audiobookshelf_public_share_enabled() and public_share_status in retryable_share_statuses:
        return True
    if (
        audiobookshelf_public_share_enabled()
        and public_share_status == "blocked_audio_publication_gate"
        and _audiobook_publication_gate_retryable_issues(
            public_share=public_share,
            gate=publication_gate,
        )
    ):
        return True
    if public_share_status == "waiting_for_audiobookshelf_scan":
        return True
    delivery = dict(public_share.get("telegram_delivery") or {})
    return (
        public_share_status == "public_share_ready"
        and bool(public_share.get("telegram_followup_pending"))
        and str(delivery.get("status") or "").strip() != "sent"
    )


def _audiobook_source_sha256(job: dict[str, object]) -> str:
    source = dict(job.get("source") or {})
    metadata = dict(job.get("metadata") or {})
    return str(source.get("source_sha256") or metadata.get("source_sha256") or "").strip()


def _audiobook_job_updated_at(job: dict[str, object]) -> datetime | None:
    return _parse_iso_datetime(job.get("updated_at")) or _parse_iso_datetime(job.get("created_at"))


def _audiobook_user_voice_intent_pending(job: dict[str, object]) -> bool:
    status = str(job.get("status") or "").strip()
    if status == "audiobookshelf_imported":
        return False
    provider = dict(job.get("provider") or {})
    voice_selection = dict(provider.get("voice_selection") or {})
    render_result = dict(job.get("render_result") or {})
    render_voice_selection = dict(render_result.get("voice_selection") or {})
    voice_status = str(voice_selection.get("status") or render_voice_selection.get("status") or "").strip()
    if voice_status == "waiting_user_choice":
        return True
    if voice_status == "selected_by_user":
        selected_key = str(
            voice_selection.get("selected_candidate_key") or render_voice_selection.get("selected_candidate_key") or ""
        ).strip()
        selected = dict(voice_selection.get("selected") or render_voice_selection.get("selected") or {})
        return bool(selected_key or selected)
    if status == "waiting_voice_selection" and str(voice_selection.get("reason") or "").strip():
        return True
    return bool(render_result.get("replacement_voice_required") and _provider_balance_blocker(render_result.get("reason")))


def _audiobook_job_has_user_selected_voice(job: dict[str, object]) -> bool:
    voice_selection = dict(dict(job.get("provider") or {}).get("voice_selection") or {})
    if str(voice_selection.get("status") or "").strip() != "selected_by_user":
        return False
    selected_key = str(voice_selection.get("selected_candidate_key") or "").strip()
    selected = dict(voice_selection.get("selected") or {})
    return bool(selected_key or selected)


def _clear_resolved_selected_voice_provider_blocker(
    job: dict[str, object],
    *,
    render_result: dict[str, object],
) -> dict[str, object]:
    render_status = str(render_result.get("status") or "").strip()
    if render_status not in {"rendered", "already_rendered"}:
        return job
    provider_payload = dict(job.get("provider") or {})
    voice_selection = dict(provider_payload.get("voice_selection") or {})
    if str(voice_selection.get("status") or "").strip() != "selected_by_user":
        return job
    selected_key = str(voice_selection.get("selected_candidate_key") or "").strip()
    selected = dict(voice_selection.get("selected") or {})
    if not selected_key and not selected:
        return job

    reason = str(voice_selection.get("reason") or "").strip()
    cleared = False
    if reason == "selected_voice_provider_balance_blocked" or _provider_balance_blocker(reason):
        voice_selection.pop("reason", None)
        cleared = True
    for key in ("pending_candidate_keys", "pending_batch", "replacement_candidate_keys"):
        if voice_selection.get(key):
            voice_selection[key] = []
            cleared = True
    last_action = dict(voice_selection.get("last_action") or {})
    if last_action:
        for key in ("replacement_candidate_keys", "replacement_count", "reason"):
            if key in last_action:
                last_action.pop(key, None)
                cleared = True
        if str(last_action.get("status") or "").strip() == "replacement_ready":
            last_action["status"] = "selected_by_user"
            last_action["action"] = "use"
            cleared = True
        voice_selection["last_action"] = last_action
    if cleared:
        voice_selection["provider_blocker_resolved"] = {
            "status": "cleared_after_selected_voice_render",
            "render_status": render_status,
            "cleared_at": _now_iso(),
            "raw_voice_ids_exposed": False,
        }
    provider_payload["voice_selection"] = voice_selection
    job["provider"] = provider_payload
    if isinstance(render_result.get("voice_selection"), dict):
        render_result["voice_selection"] = voice_selection
    return job


def _audiobook_default_voice_public_share_delivery_block(
    *,
    job_dir: Path,
    job: dict[str, object],
) -> dict[str, object]:
    if _audiobook_job_has_user_selected_voice(job):
        return {}
    source_sha = _audiobook_source_sha256(job)
    if not source_sha:
        return {}
    current_job_id = str(job.get("job_id") or job_dir.name).strip()
    current_created_at = _parse_iso_datetime(job.get("created_at"))
    for manifest_path in iter_audiobook_job_manifests(newest_first=True):
        if manifest_path.parent == job_dir:
            continue
        try:
            candidate = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if _audiobook_source_sha256(candidate) != source_sha:
            continue
        if not _audiobook_user_voice_intent_pending(candidate):
            continue
        candidate_updated_at = _audiobook_job_updated_at(candidate)
        if current_created_at is not None and candidate_updated_at is not None and candidate_updated_at < current_created_at:
            continue
        candidate_job_id = str(candidate.get("job_id") or manifest_path.parent.name).strip()
        return {
            "status": "blocked",
            "reason": "same_source_user_selected_voice_pending",
            "blocking_job_id_sha256": _sha256_bytes(candidate_job_id.encode("utf-8")) if candidate_job_id else "",
            "blocking_job_status": str(candidate.get("status") or "").strip(),
            "current_job_id_sha256": _sha256_bytes(current_job_id.encode("utf-8")) if current_job_id else "",
            "raw_voice_labels_exposed": False,
            "raw_source_sha_exposed": False,
        }
    return {}


def _refresh_audiobookshelf_public_share_for_job(job_dir: Path) -> dict[str, object]:
    job = _load_job(job_dir)
    metadata = _metadata_from_job(job)
    import_result = dict(job.get("audiobookshelf_import") or {})
    public_share = dict(import_result.get("public_share") or {})
    public_share_status = str(public_share.get("status") or "").strip()
    if (
        str(import_result.get("status") or "").strip() == "imported"
        and public_share_status == "public_share_ready"
        and bool(public_share.get("telegram_followup_pending"))
    ):
        return job
    previous_followup_pending = (
        bool(public_share.get("telegram_followup_pending"))
        or public_share_status == "waiting_for_audiobookshelf_scan"
    )
    publication_gate = dict(job.get("audio_publication_gate") or {})
    if (
        str(import_result.get("status") or "").strip() == "imported"
        and str(publication_gate.get("status") or "").strip() == "fail"
        and public_share_status
        in {
            "",
            "public_share_disabled",
            "audiobookshelf_api_not_configured",
            "public_share_create_failed",
            "share_failed",
            "audiobookshelf_scan_failed",
            "disabled",
            "missing_config",
            "waiting_for_imported_file",
            "waiting_for_audiobookshelf_scan",
            "blocked_audio_publication_gate",
        }
        and _audiobook_publication_gate_retryable_issues(
            public_share=public_share,
            gate=publication_gate,
        )
    ):
        target_path = Path(str(import_result.get("target_path") or ""))
        publication_gate = _build_audiobook_publication_gate(
            job={**job, "status": "audiobookshelf_imported", "audiobookshelf_import": import_result},
            target_path=target_path,
        )
        job["audio_publication_gate"] = publication_gate
        if str(publication_gate.get("status") or "") != "pass":
            reason = ",".join(str(issue) for issue in publication_gate.get("issues") or []) or "audio_publication_not_ready"
            import_result["player_scoped_reference"] = _blocked_player_scoped_reference(reason=reason)
            import_result["public_share"] = {
                "status": "blocked_audio_publication_gate",
                "reason": reason,
                "retried_at": _now_iso(),
                "token_exposed": False,
                "raw_library_path_exposed": False,
            }
            job["audiobookshelf_import"] = import_result
            job["updated_at"] = _now_iso()
            job["next_action"] = "wait_for_audio_publication_gate_then_send_public_share"
            _write_job(job_dir, job)
            _write_current_job_receipt_best_effort(job_dir)
            return job
        import_result["player_scoped_reference"] = create_player_scoped_audiobook_reference(
            job={**job, "status": "audiobookshelf_imported", "audiobookshelf_import": import_result},
            player_id=str(dict(job.get("source") or {}).get("player_id") or job.get("principal_id") or "").strip(),
            runner_id=str(dict(job.get("source") or {}).get("runner_id") or "").strip(),
        )
    if (
        str(import_result.get("status") or "").strip() == "imported"
        and str(dict(job.get("audio_publication_gate") or {}).get("status") or "").strip() == "pass"
        and str(dict(import_result.get("player_scoped_reference") or {}).get("status") or "").strip()
        != "signed_reference_ready"
    ):
        import_result["player_scoped_reference"] = create_player_scoped_audiobook_reference(
            job={**job, "status": "audiobookshelf_imported", "audiobookshelf_import": import_result},
            player_id=str(dict(job.get("source") or {}).get("player_id") or job.get("principal_id") or "").strip(),
            runner_id=str(dict(job.get("source") or {}).get("runner_id") or "").strip(),
        )
    refreshed = _create_or_reuse_audiobookshelf_public_share(
        job={**job, "audiobookshelf_import": import_result},
        import_result=import_result,
        metadata=metadata,
    )
    if previous_followup_pending and str(refreshed.get("status") or "") == "public_share_ready":
        refreshed["telegram_followup_pending"] = True
    import_result["public_share"] = refreshed
    job["audiobookshelf_import"] = import_result
    job["updated_at"] = _now_iso()
    if str(refreshed.get("status") or "") == "public_share_ready":
        job["next_action"] = (
            "send_whatsapp_audiobookshelf_public_share_link"
            if str(dict(job.get("whatsapp") or {}).get("sender_ref") or "").strip()
            else "send_telegram_audiobookshelf_public_share_link"
        )
    else:
        job["next_action"] = "wait_for_audiobookshelf_scan_then_send_public_share"
    _write_job(job_dir, job)
    _write_current_job_receipt_best_effort(job_dir)
    return job


def _record_audiobookshelf_public_share_telegram_delivery_block(
    *,
    job_dir: Path,
    job: dict[str, object],
    block: dict[str, object],
) -> dict[str, object]:
    import_result = dict(job.get("audiobookshelf_import") or {})
    public_share = dict(import_result.get("public_share") or {})
    delivery = {
        "status": "blocked",
        "notified_at": _now_iso(),
        "message_id": "",
        "reason": str(block.get("reason") or "same_source_user_selected_voice_pending").strip(),
        "blocking_job_id_sha256": str(block.get("blocking_job_id_sha256") or "").strip(),
        "blocking_job_status": str(block.get("blocking_job_status") or "").strip(),
        "callback_tokens_exposed": False,
        "audiobookshelf_token_exposed": False,
    }
    public_share["telegram_delivery"] = delivery
    public_share["telegram_followup_pending"] = False
    public_share["delivery_block"] = {
        "status": "blocked",
        "reason": delivery["reason"],
        "blocking_job_id_sha256": delivery["blocking_job_id_sha256"],
        "blocking_job_status": delivery["blocking_job_status"],
        "raw_voice_labels_exposed": False,
        "raw_source_sha_exposed": False,
    }
    import_result["public_share"] = public_share
    job["audiobookshelf_import"] = import_result
    job["next_action"] = "finish_user_selected_voice_audiobook_before_sending_public_share_link"
    job["updated_at"] = _now_iso()
    _write_job(job_dir, job)
    _write_current_job_receipt_best_effort(job_dir)
    return job


def _record_audiobookshelf_public_share_telegram_delivery(
    *,
    job_dir: Path,
    job: dict[str, object],
    notification: dict[str, object],
) -> dict[str, object]:
    import_result = dict(job.get("audiobookshelf_import") or {})
    public_share = dict(import_result.get("public_share") or {})
    delivery = {
        "status": str(notification.get("status") or "").strip() or "unknown",
        "notified_at": _now_iso(),
        "message_id": notification.get("message_id"),
        "reason": str(notification.get("reason") or "").strip(),
        "callback_tokens_exposed": False,
        "audiobookshelf_token_exposed": False,
    }
    public_share["telegram_delivery"] = delivery
    if delivery["status"] == "sent":
        public_share["telegram_followup_pending"] = False
        job["next_action"] = "done"
    else:
        public_share["telegram_followup_pending"] = True
        job["next_action"] = "retry_telegram_audiobookshelf_public_share_link"
    import_result["public_share"] = public_share
    job["audiobookshelf_import"] = import_result
    job["updated_at"] = _now_iso()
    _write_job(job_dir, job)
    _write_current_job_receipt_best_effort(job_dir)
    return job


def _m4b_tool_available() -> bool:
    return shutil.which(m4b_tool_bin()) is not None


def _ffmpeg_bin() -> str:
    return str(os.getenv("EA_FFMPEG_BIN") or "ffmpeg").strip() or "ffmpeg"


def _ffprobe_bin() -> str:
    return str(os.getenv("EA_FFPROBE_BIN") or "ffprobe").strip() or "ffprobe"


def _ffmpeg_m4b_fallback_available() -> bool:
    return ffmpeg_m4b_fallback_enabled() and shutil.which(_ffmpeg_bin()) is not None and shutil.which(_ffprobe_bin()) is not None


def _m4b_assembly_available() -> bool:
    return _m4b_tool_available() or _ffmpeg_m4b_fallback_available()


def _writable_or_creatable(path: Path) -> bool:
    current = path
    while not current.exists() and current.parent != current:
        current = current.parent
    return current.exists() and os.access(current, os.W_OK)


def audiobook_runtime_preflight() -> dict[str, object]:
    checks: list[dict[str, object]] = []

    def add(key: str, passed: bool, *, severity: str = "fail", detail: str = "") -> None:
        checks.append(
            {
                "key": key,
                "status": "pass" if passed else severity,
                "detail": detail,
            }
        )

    jobs_root = audiobook_jobs_root()
    import_root = audiobookshelf_import_root()
    job_storage_kind = _path_storage_kind(jobs_root)
    import_storage_kind = _path_storage_kind(import_root)
    jobs_root_durable_ready = _durable_or_allowed(jobs_root)
    import_root_durable_ready = _durable_or_allowed(import_root)
    voice_presets = load_unmixr_voice_presets()
    ffmpeg_available = shutil.which(_ffmpeg_bin()) is not None
    ffprobe_available = shutil.which(_ffprobe_bin()) is not None
    m4b_available = _m4b_tool_available()
    ffmpeg_fallback_available = _ffmpeg_m4b_fallback_available()
    auto_import = audiobookshelf_import_enabled()
    public_share_enabled = audiobookshelf_public_share_enabled()
    player_access_base_url_present = bool(str(os.getenv("EA_AUDIOBOOK_PLAYER_ACCESS_BASE_URL") or "").strip())
    bulk_pacing_enabled = _unmixr_max_segments_per_run() > 0

    telegram_audiobook_enabled = telegram_audiobook_skill_enabled()
    add("telegram_audiobook_enabled", telegram_audiobook_enabled, detail="Telegram audiobook intake switch.")
    add("telegram_epub_enabled", telegram_audiobook_enabled, detail="Legacy Telegram EPUB intake switch alias.")
    add(
        "jobs_root_durable",
        jobs_root_durable_ready,
        detail="Large source ebooks, WAV, and M4B artifacts stay on configured durable audiobook storage.",
    )
    add("jobs_root_writable", _writable_or_creatable(jobs_root), detail="Audiobook job root can be created or written.")
    add(
        "external_tts_enabled",
        external_tts_enabled(),
        detail="Raw book text may leave EA only through the explicit external-TTS gate.",
    )
    add(
        "unmixr_auto_render_enabled",
        unmixr_auto_render_enabled(),
        detail="Telegram audiobook jobs can render without a separate manual resume.",
    )
    add("voice_catalog_configured", bool(voice_presets), detail="At least one narration voice is configured or discovered.")
    add(
        "voice_catalog_audition_ready",
        len(voice_presets) >= audiobook_voice_audition_min_candidates(),
        severity="warn",
        detail="At least three configured or discovered voices are available for Telegram comparison samples.",
    )
    add("ffmpeg_available", ffmpeg_available, detail="ffmpeg is available for segment conversion and fallback M4B assembly.")
    add("ffprobe_available", ffprobe_available, detail="ffprobe is available for chapter-duration metadata.")
    add(
        "m4b_assembly_available",
        m4b_available or ffmpeg_fallback_available,
        detail="m4b-tool is available, or ffmpeg fallback is available.",
    )
    if auto_import:
        add(
            "audiobookshelf_import_root_durable",
            import_root_durable_ready,
            detail="Audiobookshelf import storage is on configured durable audiobook storage.",
        )
        add(
            "audiobookshelf_import_root_writable",
            _writable_or_creatable(import_root),
            detail="Audiobookshelf import root can be created or written.",
        )
    else:
        add("audiobookshelf_auto_import_enabled", False, severity="warn", detail="Auto-import is disabled.")
    if public_share_enabled:
        add(
            "audiobookshelf_public_share_configured",
            _audiobookshelf_api_ready(),
            severity="warn",
            detail="Audiobookshelf API base URL, admin token, and library ID are present for public share creation.",
        )
    add(
        "player_access_signing_secret_present",
        bool(_audiobook_access_secret()),
        detail="Player/runner-scoped playback references can be signed.",
    )
    add(
        "player_access_base_url_present",
        player_access_base_url_present,
        severity="warn",
        detail=(
            "EA can publish an absolute player-scoped playback URL when configured; public-share delivery still works without it."
        ),
    )
    add(
        "scheduler_resume_enabled",
        _env_bool("EA_SCHEDULER_AUDIOBOOK_RESUME_ENABLED", True),
        detail="Provider-throttled jobs can resume without operator babysitting.",
    )
    add(
        "unmixr_bulk_pacing_configured",
        bulk_pacing_enabled,
        severity="warn",
        detail=(
            "Large audiobook renders can pause between batches when a pacing ceiling is configured; disabling the ceiling keeps the lane uncapped."
        ),
    )

    failed = [row for row in checks if row["status"] == "fail"]
    warned = [row for row in checks if row["status"] == "warn"]
    overall_status = "fail" if failed else "warn" if warned else "pass"
    return {
        "contract_name": AUDIOBOOK_RUNTIME_PREFLIGHT_CONTRACT_NAME,
        "status": overall_status,
        "observed_at": _now_iso(),
        "storage": {
            "jobs_root_kind": job_storage_kind,
            "audiobookshelf_import_root_kind": import_storage_kind,
            "jobs_root_durable_ready": jobs_root_durable_ready,
            "audiobookshelf_import_root_durable_ready": import_root_durable_ready,
            "raw_paths_exposed": False,
        },
        "provider": {
            "provider": "unmixr",
            "external_tts_enabled": external_tts_enabled(),
            "unmixr_auto_render_enabled": unmixr_auto_render_enabled(),
            "api_key_slot_count": unmixr_api_key_slot_count(),
            "voice_catalog_count": len(voice_presets),
            "voice_discovery_enabled": audiobook_voice_discovery_enabled(),
            "voice_discovery_target_count": audiobook_voice_discovery_target_count(),
            "voice_audition_min_candidates": audiobook_voice_audition_min_candidates(),
            "voice_catalog": [
                {
                    "preset_key": preset.preset_key,
                    "label": preset.label,
                    "language": preset.language,
                    "supported_languages": list(preset.supported_languages[:20]),
                    "tags": list(preset.tags),
                    "default": preset.default,
                    "source": preset.source,
                    "voice_id_sha256": _sha256_bytes(preset.voice_id.encode("utf-8")),
                }
                for preset in voice_presets[:12]
            ],
            "raw_voice_ids_exposed": False,
            "provider_secrets_exposed": False,
            "bulk_pacing": {
                "max_segments_per_run": _unmixr_max_segments_per_run(),
                "pacing_wait_seconds": _unmixr_pacing_wait_seconds(),
                "bulk_char_threshold": _unmixr_bulk_pacing_char_threshold(),
                "priority_source_kinds": list(_priority_audiobook_source_kinds()),
            },
        },
        "assembly": {
            "m4b_tool_available": m4b_available,
            "ffmpeg_available": ffmpeg_available,
            "ffprobe_available": ffprobe_available,
            "ffmpeg_m4b_fallback_enabled": ffmpeg_m4b_fallback_enabled(),
            "ffmpeg_m4b_fallback_available": ffmpeg_fallback_available,
            "m4b_assembly_available": m4b_available or ffmpeg_fallback_available,
        },
        "access": {
            "audiobookshelf_auto_import_enabled": auto_import,
            "audiobookshelf_public_share_enabled": public_share_enabled,
            "audiobookshelf_public_share_configured": _audiobookshelf_api_ready(),
            "audiobookshelf_api_base_url_present": bool(_audiobookshelf_api_base_url()),
            "audiobookshelf_public_base_url_present": bool(_audiobookshelf_public_base_url()),
            "audiobookshelf_api_token_present": bool(_audiobookshelf_api_token()),
            "audiobookshelf_library_id_present": bool(_audiobookshelf_library_id()),
            "player_access_signing_secret_present": bool(_audiobook_access_secret()),
            "player_access_base_url_present": player_access_base_url_present,
            "tokens_exposed": False,
        },
        "scheduler": {
            "resume_enabled": _env_bool("EA_SCHEDULER_AUDIOBOOK_RESUME_ENABLED", True),
            "resume_interval_seconds": _env_int("EA_SCHEDULER_AUDIOBOOK_RESUME_INTERVAL_SECONDS", 300, minimum=30),
            "resume_due_limit": _env_int("EA_AUDIOBOOK_RESUME_DUE_LIMIT", 2, minimum=1, maximum=20),
            "resume_order": ("priority_source", "retry_at", "job_dir_name"),
            "priority_source_kinds": list(_priority_audiobook_source_kinds()),
        },
        "checks": checks,
        "failed_checks": [str(row["key"]) for row in failed],
        "warned_checks": [str(row["key"]) for row in warned],
    }


def write_audiobook_runtime_preflight(*, output_path: Path) -> dict[str, object]:
    receipt = audiobook_runtime_preflight()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def _ffmetadata_escape(value: object) -> str:
    return (
        str(value or "")
        .replace("\\", "\\\\")
        .replace("=", "\\=")
        .replace(";", "\\;")
        .replace("#", "\\#")
        .replace("\n", " ")
        .strip()
    )


def _probe_audio_duration_ms(path: Path) -> int:
    completed = subprocess.run(
        [
            _ffprobe_bin(),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=_env_int("EA_AUDIOBOOK_AUDIO_PROBE_TIMEOUT_SECONDS", 60, minimum=5),
    )
    if completed.returncode != 0:
        raise RuntimeError(f"audio_duration_probe_failed:{path.name}")
    try:
        payload = json.loads(str(completed.stdout or "{}"))
        seconds = float(dict(payload.get("format") or {}).get("duration") or 0.0)
    except Exception as exc:
        raise RuntimeError(f"audio_duration_probe_invalid:{path.name}") from exc
    return max(int(seconds * 1000), 1)


def _write_ffmpeg_concat_file(path: Path, audio_paths: tuple[Path, ...]) -> None:
    def _quote(item: Path) -> str:
        return str(item).replace("'", "'\\''")

    path.write_text("".join(f"file '{_quote(item)}'\n" for item in audio_paths), encoding="utf-8")


def _m4b_concat_sample_rate() -> int:
    return _env_int("EA_AUDIOBOOK_M4B_SAMPLE_RATE", 44100, minimum=8000, maximum=192000)


def _m4b_concat_channels() -> int:
    return _env_int("EA_AUDIOBOOK_M4B_CHANNELS", 1, minimum=1, maximum=2)


def _normalize_ffmpeg_concat_audio_inputs(
    *,
    job_dir: Path,
    audio_paths: tuple[Path, ...],
) -> dict[str, object]:
    sample_rate = _m4b_concat_sample_rate()
    channels = _m4b_concat_channels()
    normalized_dir = job_dir / "m4b" / "normalized-audio"
    normalized_dir.mkdir(parents=True, exist_ok=True)
    normalized_paths: list[Path] = []
    rows: list[dict[str, object]] = []
    for index, audio_path in enumerate(audio_paths, start=1):
        normalized_path = normalized_dir / f"{index:03d} - {_safe_filename(audio_path.stem, fallback=f'chapter-{index:03d}')}.wav"
        command = [
            _ffmpeg_bin(),
            "-hide_banner",
            "-nostats",
            "-y",
            "-i",
            str(audio_path),
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            str(channels),
            "-ar",
            str(sample_rate),
            "-c:a",
            "pcm_s16le",
            str(normalized_path),
        ]
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=_env_int("EA_AUDIOBOOK_M4B_AUDIO_NORMALIZE_TIMEOUT_SECONDS", 900, minimum=30, maximum=7200),
        )
        if completed.returncode != 0 or not normalized_path.is_file() or normalized_path.stat().st_size <= 0:
            return {
                "status": "failed",
                "failed_index": index,
                "failed_source_sha256": _sha256_file(audio_path) if audio_path.is_file() else "",
                "command": command,
                "returncode": completed.returncode,
                "stderr_tail": str(completed.stderr or "")[-1200:],
                "raw_paths_exposed": False,
            }
        normalized_paths.append(normalized_path)
        rows.append(
            {
                "index": index,
                "source_sha256": _sha256_file(audio_path),
                "normalized_sha256": _sha256_file(normalized_path),
                "sample_rate": sample_rate,
                "channels": channels,
                "raw_paths_exposed": False,
            }
        )
    return {
        "status": "ready",
        "audio_paths": normalized_paths,
        "sample_rate": sample_rate,
        "channels": channels,
        "items": rows,
        "raw_paths_exposed": False,
    }


def _write_ffmetadata_file(
    *,
    path: Path,
    metadata: EpubMetadata,
    chapters: tuple[EpubChapter, ...],
    audio_paths: tuple[Path, ...],
    cinematic_track: bool = False,
) -> None:
    lines = [
        ";FFMETADATA1",
        f"title={_ffmetadata_escape(metadata.title)}",
        f"artist={_ffmetadata_escape(metadata.author or 'EA Narration')}",
        f"album_artist={_ffmetadata_escape(metadata.author or 'EA Narration')}",
    ]
    if cinematic_track and audio_paths:
        duration_ms = _probe_audio_duration_ms(audio_paths[0])
        lines.extend(
            [
                "[CHAPTER]",
                "TIMEBASE=1/1000",
                "START=0",
                f"END={max(duration_ms, 0)}",
                f"title={_ffmetadata_escape(metadata.title)}",
            ]
        )
    else:
        cursor = 0
        for chapter, audio_path in zip(chapters, audio_paths, strict=False):
            duration_ms = _probe_audio_duration_ms(audio_path)
            end = cursor + duration_ms
            lines.extend(
                [
                    "[CHAPTER]",
                    "TIMEBASE=1/1000",
                    f"START={cursor}",
                    f"END={end}",
                    f"title={_ffmetadata_escape(chapter.title or audio_path.stem)}",
                ]
            )
            cursor = end
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _cover_image_path(job_dir: Path, metadata: EpubMetadata) -> Path | None:
    raw_path = str(metadata.cover_image_path or "").strip()
    if raw_path:
        path = Path(raw_path)
        if path.is_file():
            return path
    assets_dir = job_dir / "assets"
    for candidate in ("cover.jpg", "cover.jpeg", "cover.png", "cover.webp"):
        path = assets_dir / candidate
        if path.is_file():
            return path
    return None


def _fallback_cover_enabled() -> bool:
    return _env_bool("EA_AUDIOBOOK_GENERATE_FALLBACK_COVER", True)


def _cover_color(seed: str, *, offset: int = 0) -> str:
    digest = hashlib.sha256(f"{seed}:{offset}".encode("utf-8")).hexdigest()
    # Keep colors saturated enough to read as cover artwork, but not neon.
    channels = [96 + (int(digest[index : index + 2], 16) % 112) for index in (0, 2, 4)]
    return "".join(f"{channel:02x}" for channel in channels)


def _generated_fallback_cover_path(job_dir: Path, metadata: EpubMetadata) -> Path | None:
    if not _fallback_cover_enabled() or shutil.which(_ffmpeg_bin()) is None:
        return None
    assets_dir = job_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    target = assets_dir / "generated-audiobook-cover.jpg"
    if target.is_file() and target.stat().st_size > 0:
        return target
    seed = f"{metadata.title}|{metadata.author}|{metadata.source_sha256}|{metadata.source_filename}"
    background = _cover_color(seed, offset=0)
    accent = _cover_color(seed, offset=1)
    secondary = _cover_color(seed, offset=2)
    filter_graph = ",".join(
        (
            f"color=c=0x{background}:s=1400x1400",
            f"drawbox=x=96:y=96:w=1208:h=1208:color=0x{accent}@0.32:t=28",
            f"drawbox=x=180:y=220:w=1040:h=180:color=0x{secondary}@0.35:t=fill",
            "drawbox=x=180:y=920:w=1040:h=94:color=white@0.22:t=fill",
            "drawbox=x=180:y=1055:w=780:h=48:color=white@0.18:t=fill",
            "drawbox=x=180:y=1140:w=520:h=30:color=white@0.16:t=fill",
        )
    )
    completed = subprocess.run(
        [
            _ffmpeg_bin(),
            "-y",
            "-f",
            "lavfi",
            "-i",
            filter_graph,
            "-frames:v",
            "1",
            "-q:v",
            "3",
            str(target),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=_env_int("EA_AUDIOBOOK_FALLBACK_COVER_TIMEOUT_SECONDS", 30, minimum=5, maximum=300),
    )
    if completed.returncode == 0 and target.is_file() and target.stat().st_size > 0:
        return target
    target.unlink(missing_ok=True)
    return None


def _m4b_cover_image_path(job_dir: Path, metadata: EpubMetadata) -> Path | None:
    return _cover_image_path(job_dir, metadata) or _generated_fallback_cover_path(job_dir, metadata)


def _merge_m4b_with_ffmpeg(
    *,
    job_dir: Path,
    metadata: EpubMetadata,
    chapters: tuple[EpubChapter, ...],
    output_file: Path,
    cinematic_track_path: Path | None = None,
) -> dict[str, object]:
    audio_paths: list[Path] = []
    cinematic_merge = cinematic_track_path is not None and cinematic_track_path.is_file() and cinematic_track_path.stat().st_size > 0
    if cinematic_merge:
        audio_paths = [cinematic_track_path]
    else:
        audio_dir = job_dir / "audio"
        for chapter in chapters:
            audio_path = _chapter_audio_path(audio_dir, chapter)
            if audio_path is None:
                return {"status": "waiting_for_unmixr_export", "output_file": str(output_file)}
            audio_paths.append(audio_path)
    if not audio_paths:
        if cinematic_merge:
            return {"status": "waiting_for_unmixr_export", "output_file": str(output_file)}
    work_dir = job_dir / "m4b"
    work_dir.mkdir(parents=True, exist_ok=True)
    concat_file = work_dir / "concat.txt"
    metadata_file = work_dir / "chapters.ffmetadata"
    cover_path = _m4b_cover_image_path(job_dir, metadata)
    normalized = _normalize_ffmpeg_concat_audio_inputs(job_dir=job_dir, audio_paths=tuple(audio_paths))
    if str(normalized.get("status") or "") != "ready":
        return {
            "status": "m4b_merge_failed",
            "provider": "ffmpeg",
            "stage": "normalize_concat_audio",
            "normalization": normalized,
        }
    concat_audio_paths = tuple(path for path in normalized.get("audio_paths") or [] if isinstance(path, Path))
    _write_ffmpeg_concat_file(concat_file, concat_audio_paths)
    _write_ffmetadata_file(
        path=metadata_file,
        metadata=metadata,
        chapters=chapters,
        audio_paths=concat_audio_paths,
        cinematic_track=cinematic_merge,
    )
    command = [
        _ffmpeg_bin(),
        "-y",
    ]
    if len(concat_audio_paths) == 1:
        # Direct WAV input avoids AAC decode corruption observed from the concat
        # demuxer on single-chapter M4B jobs.
        command.extend(["-i", str(concat_audio_paths[0])])
    else:
        command.extend(
            [
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_file),
            ]
        )
    command.extend(["-i", str(metadata_file)])
    if cover_path is not None:
        command.extend(["-i", str(cover_path)])
    command.extend(
        [
            "-map",
            "0:a",
        ]
    )
    if cover_path is not None:
        command.extend(["-map", "2:v", "-disposition:v:0", "attached_pic"])
    else:
        command.append("-vn")
    command.extend(
        [
        "-map_metadata",
        "1",
        "-map_chapters",
        "1",
        "-c:a",
        "aac",
        "-b:a",
        str(os.getenv("EA_AUDIOBOOK_M4B_BITRATE") or "96k"),
        "-ac",
        str(_m4b_concat_channels()),
        "-ar",
        str(_m4b_concat_sample_rate()),
        ]
    )
    if cover_path is not None:
        command.extend(["-c:v", "copy"])
    command.extend(["-movflags", "+faststart"])
    command.append(str(output_file))
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=_env_int("EA_AUDIOBOOK_M4B_MERGE_TIMEOUT_SECONDS", 7200, minimum=30),
    )
    if completed.returncode != 0 or not output_file.is_file():
        return {
            "status": "m4b_merge_failed",
            "provider": "ffmpeg",
            "command": command,
            "returncode": completed.returncode,
            "stderr_tail": str(completed.stderr or "")[-1200:],
        }
    return {
        "status": "m4b_ready",
        "provider": "ffmpeg",
        "output_file": str(output_file),
        "command": command,
        "chapter_count": 1 if cinematic_merge else len(chapters),
        "cover_embedded": cover_path is not None,
        "cover_filename": cover_path.name if cover_path is not None else "",
        "normalized_audio": True,
        "normalized_sample_rate": int(normalized.get("sample_rate") or 0),
        "normalized_channels": int(normalized.get("channels") or 0),
        "normalized_audio_count": len(concat_audio_paths),
    }


def _merge_m4b_if_ready(
    *,
    job_dir: Path,
    metadata: EpubMetadata,
    chapters: tuple[EpubChapter, ...],
    cinematic_track_path: Path | None = None,
) -> dict[str, object]:
    audio_dir = job_dir / "audio"
    output_dir = job_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_title = _safe_filename(metadata.title, fallback=Path(metadata.source_filename).stem)
    output_file = output_dir / f"{safe_title}.m4b"
    command = build_m4b_tool_command(
        audio_dir=audio_dir,
        output_file=output_file,
        title=metadata.title,
        author=metadata.author,
        narrator=str(os.getenv("EA_AUDIOBOOK_NARRATOR_LABEL") or "EA Audio").strip(),
        cover_path=_m4b_cover_image_path(job_dir, metadata),
    )
    if _audiobook_cinematic_narration():
        # Keep cinematic narration continuous once enabled; do not fall back to
        # fragmented chapter tracks if cinematic master track is not available.
        if cinematic_track_path is not None:
            discovered_cinematic_track = _discover_or_build_cinematic_master_audio(job_dir=job_dir, chapters=chapters)
            if discovered_cinematic_track is None or discovered_cinematic_track.resolve() != cinematic_track_path.resolve():
                cinematic_track_path = None
            else:
                cinematic_track_path = discovered_cinematic_track
        else:
            cinematic_track_path = _discover_or_build_cinematic_master_audio(job_dir=job_dir, chapters=chapters)
        if cinematic_track_path is None:
            return {
                "status": "waiting_for_unmixr_export",
                "command": command,
                "output_file": str(output_file),
                "reason": "cinematic_master_track_missing",
            }
        if not cinematic_track_path.is_file() or cinematic_track_path.stat().st_size <= 0:
            return {
                "status": "waiting_for_unmixr_export",
                "command": command,
                "output_file": str(output_file),
                "reason": "cinematic_master_track_not_ready",
            }
        return _merge_m4b_with_ffmpeg(
            job_dir=job_dir,
            metadata=metadata,
            chapters=chapters,
            output_file=output_file,
            cinematic_track_path=cinematic_track_path,
        )

    if cinematic_track_path is not None:
        discovered_cinematic_track = _discover_or_build_cinematic_master_audio(job_dir=job_dir, chapters=chapters)
        if discovered_cinematic_track is None or discovered_cinematic_track.resolve() != cinematic_track_path.resolve():
            cinematic_track_path = None
    if cinematic_track_path is None:
        cinematic_track_path = _discover_or_build_cinematic_master_audio(job_dir=job_dir, chapters=chapters)
    if not _audio_inputs_ready(
        job_dir,
        chapters,
        cinematic_track_path=cinematic_track_path,
    ):
        return {"status": "waiting_for_unmixr_export", "command": command, "output_file": str(output_file)}
    if not m4b_auto_merge_enabled():
        return {"status": "waiting_for_operator_merge", "command": command, "output_file": str(output_file)}
    if cinematic_track_path is not None and cinematic_track_path.is_file() and cinematic_track_path.stat().st_size > 0:
        return _merge_m4b_with_ffmpeg(
            job_dir=job_dir,
            metadata=metadata,
            chapters=chapters,
            output_file=output_file,
            cinematic_track_path=cinematic_track_path,
        )
    if not _m4b_tool_available():
        if _ffmpeg_m4b_fallback_available():
            return _merge_m4b_with_ffmpeg(
                job_dir=job_dir,
                metadata=metadata,
                chapters=chapters,
                output_file=output_file,
            )
        return {"status": "waiting_for_m4b_assembly_tool", "command": command, "output_file": str(output_file)}
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=_env_int("EA_AUDIOBOOK_M4B_MERGE_TIMEOUT_SECONDS", 7200, minimum=30),
    )
    if completed.returncode != 0 or not output_file.is_file():
        return {
            "status": "m4b_merge_failed",
            "command": command,
            "returncode": completed.returncode,
            "stderr_tail": str(completed.stderr or "")[-1200:],
        }
    cover_path = _m4b_cover_image_path(job_dir, metadata)
    return {
        "status": "m4b_ready",
        "output_file": str(output_file),
        "command": command,
        "cover_embedded": cover_path is not None,
        "cover_filename": cover_path.name if cover_path is not None else "",
    }


def _import_to_audiobookshelf_if_ready(*, m4b_path: Path, metadata: EpubMetadata) -> dict[str, object]:
    if not m4b_path.is_file():
        return {"status": "waiting_for_m4b", "target": ""}
    configured_root = audiobookshelf_import_root()
    target_root, root_selection = _effective_audiobookshelf_import_root(configured_root)
    if not audiobookshelf_import_enabled():
        return {"status": "waiting_for_operator_import", "target_root": str(target_root)}
    if not _env_bool("EA_AUDIOBOOK_ALLOW_NON_DURABLE_STORAGE", False):
        try:
            target_root.expanduser().resolve().relative_to(_durable_storage_root().expanduser().resolve())
        except ValueError:
            return {"status": "blocked", "reason": "audiobookshelf_import_root_must_be_on_durable_storage", "target_root": str(target_root)}
    author_dir = _safe_filename(metadata.author or "Unknown Author", fallback="Unknown Author")
    title_dir = _safe_filename(metadata.title or m4b_path.stem, fallback=m4b_path.stem)
    target_dir = target_root / author_dir / title_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / m4b_path.name
    if target_path.resolve() != m4b_path.resolve():
        shutil.copy2(m4b_path, target_path)
    return {
        "status": "imported",
        "target_path": str(target_path),
        "target_root": str(target_root),
        "import_root_selection": root_selection,
    }


def _probe_audio_publication_file(path: Path) -> dict[str, object]:
    try:
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration,size:stream=codec_type,codec_name,sample_rate,channels,bit_rate,duration:chapters",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=_env_int("EA_AUDIOBOOK_PUBLICATION_PROBE_TIMEOUT_SECONDS", 60, minimum=5, maximum=600),
        )
        return json.loads(completed.stdout or "{}")
    except Exception as exc:
        return {"probe_error": type(exc).__name__}


def _audio_publication_volume(path: Path, *, position: str = "head") -> dict[str, object]:
    normalized_position = str(position or "head").strip().lower()
    seconds = _env_int("EA_AUDIOBOOK_PUBLICATION_VOLUME_WINDOW_SECONDS", 30, minimum=5, maximum=180)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
    ]
    if normalized_position == "tail":
        command.extend(["-sseof", f"-{seconds}"])
    command.extend(
        [
            "-t",
            str(seconds),
            "-i",
            str(path),
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ]
    )
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=_env_int("EA_AUDIOBOOK_PUBLICATION_VOLUME_TIMEOUT_SECONDS", 120, minimum=10, maximum=900),
        )
    except Exception as exc:
        return {"status": "failed", "reason": type(exc).__name__, "window_seconds": seconds, "position": normalized_position}
    mean_volume = ""
    max_volume = ""
    for line in str(completed.stderr or "").splitlines():
        if "mean_volume:" in line:
            mean_volume = line.rsplit("mean_volume:", 1)[1].strip().split(" ", 1)[0]
        elif "max_volume:" in line:
            max_volume = line.rsplit("max_volume:", 1)[1].strip().split(" ", 1)[0]
    return {
        "status": "checked" if mean_volume else "failed",
        "reason": "" if mean_volume else "volume_probe_missing_mean",
        "window_seconds": seconds,
        "position": normalized_position,
        "mean_volume_db": mean_volume,
        "max_volume_db": max_volume,
        "returncode": completed.returncode,
    }


def _audiobook_publication_stt_required() -> bool:
    return _env_bool("EA_AUDIOBOOK_PUBLICATION_STT_GATE_REQUIRED", True)


def _audiobook_publication_stt_enabled() -> bool:
    return _audiobook_publication_stt_required() or _env_bool("EA_AUDIOBOOK_PUBLICATION_STT_GATE_ENABLED", False)


def _publication_stt_tokens(text: object) -> list[str]:
    return re.findall(r"[a-z0-9\u00c0-\u024f]{2,}", str(text or "").lower())


def _audiobook_publication_source_text(job: dict[str, object]) -> str:
    job_dir = Path(str(dict(job.get("storage") or {}).get("job_dir") or "")).expanduser()
    if not job_dir:
        return ""
    max_chars = _env_int("EA_AUDIOBOOK_PUBLICATION_STT_SOURCE_MAX_CHARS", 500000, minimum=10000, maximum=3000000)
    chunks: list[str] = []
    total = 0
    for item in list(job.get("chapters") or []):
        if not isinstance(item, dict):
            continue
        text_name = Path(str(item.get("text_path") or "")).name
        if not text_name:
            continue
        text_path = job_dir / "chapters" / text_name
        if not text_path.is_file():
            continue
        try:
            text = text_path.read_text(encoding="utf-8")
        except Exception:
            continue
        if not text.strip():
            continue
        remaining = max_chars - total
        if remaining <= 0:
            break
        chunks.append(text[:remaining])
        total += min(len(text), remaining)
    return "\n".join(chunks)


def _audiobook_publication_stt_offsets(*, duration_seconds: float, sample_seconds: int, sample_count: int) -> list[float]:
    count = max(1, int(sample_count))
    window = max(1.0, float(sample_seconds))
    duration = max(0.0, float(duration_seconds or 0.0))
    if count == 1 or duration <= window:
        return [0.0]
    span = max(duration - window, 0.0)
    if count == 2:
        offsets = [0.0, span]
    else:
        offsets = [span * index / float(count - 1) for index in range(count)]
    deduped: list[float] = []
    for offset in offsets:
        rounded = round(max(0.0, offset), 3)
        if rounded not in deduped:
            deduped.append(rounded)
    return deduped


def _extract_audiobook_publication_stt_sample(
    *,
    target_path: Path,
    output_path: Path,
    offset_seconds: float,
    sample_seconds: int,
) -> dict[str, object]:
    command = [
        _ffmpeg_bin(),
        "-hide_banner",
        "-nostats",
        "-y",
        "-i",
        str(target_path),
        "-ss",
        str(max(float(offset_seconds), 0.0)),
        "-t",
        str(max(int(sample_seconds), 1)),
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        str(output_path),
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=_env_int("EA_AUDIOBOOK_PUBLICATION_STT_EXTRACT_TIMEOUT_SECONDS", 120, minimum=10, maximum=900),
        )
    except Exception as exc:
        return {"status": "failed", "reason": type(exc).__name__}
    if completed.returncode != 0 or not output_path.is_file():
        return {"status": "failed", "reason": "ffmpeg_sample_extract_failed", "returncode": completed.returncode}
    return {
        "status": "ready",
        "sample_file_size": int(output_path.stat().st_size),
        "seek_mode": "output_side_audio_stream",
    }


_AUDIOBOOK_CARTESIA_STT_URL = "https://api.cartesia.ai/stt"
_AUDIOBOOK_CARTESIA_VERSION = "2026-03-01"
_AUDIOBOOK_CARTESIA_STT_MODEL = "ink-whisper"
_AUDIOBOOK_CARTESIA_DIRECT_KEY_ENV_NAMES = ("CARTESIA_API_KEY", "EA_CARTESIA_API_KEY")
_AUDIOBOOK_CARTESIA_INLINE_CREDENTIAL_ENV_NAMES = (
    "CARTESIA_API_KEY_JSON",
    "EA_CARTESIA_API_KEY_JSON",
    "CARTESIA_CREDENTIALS_JSON",
    "EA_CARTESIA_CREDENTIALS_JSON",
)
_AUDIOBOOK_CARTESIA_CREDENTIAL_FILE_ENV_NAMES = (
    "CARTESIA_API_KEY_FILE",
    "EA_CARTESIA_API_KEY_FILE",
    "CARTESIA_CREDENTIALS_JSON_FILE",
    "EA_CARTESIA_CREDENTIALS_JSON_FILE",
)
_AUDIOBOOK_CARTESIA_DEFAULT_CREDENTIAL_FILES = (
    "/config/cartesia.local.json",
    "/app/config/cartesia.local.json",
    "config/cartesia.local.json",
)


def _audiobook_cartesia_api_key_from_payload(payload: object) -> str:
    if isinstance(payload, str):
        raw = payload.strip()
        if not raw:
            return ""
        try:
            parsed = json.loads(raw)
        except Exception:
            return raw
        return _audiobook_cartesia_api_key_from_payload(parsed)
    if isinstance(payload, list):
        for item in payload:
            value = _audiobook_cartesia_api_key_from_payload(item)
            if value:
                return value
        return ""
    if not isinstance(payload, dict):
        return ""
    for key in ("api_key", "key", "token", "secret", "value", "CARTESIA_API_KEY", "EA_CARTESIA_API_KEY"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    for key in ("cartesia", "credentials", "credential", "auth", "account"):
        value = _audiobook_cartesia_api_key_from_payload(payload.get(key))
        if value:
            return value
    return ""


def _audiobook_cartesia_credential_path_candidates(raw_path: object) -> tuple[Path, ...]:
    raw = str(raw_path or "").strip()
    if not raw:
        return ()
    try:
        path = Path(raw).expanduser()
    except Exception:
        return ()
    repo_root = Path(__file__).resolve().parents[3]
    candidates: list[Path] = []
    if path.is_absolute():
        candidates.append(path)
        if str(path).startswith("/config/"):
            candidates.append(repo_root / "config" / path.name)
    else:
        candidates.extend((repo_root / path, repo_root / "config" / path.name, path))
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = candidate.resolve(strict=False)
        key = normalized.as_posix()
        if key in seen:
            continue
        seen.add(key)
        unique.append(normalized)
    return tuple(unique)


def _load_audiobook_cartesia_credential_file(raw_path: object) -> object:
    for candidate in _audiobook_cartesia_credential_path_candidates(raw_path):
        try:
            text = candidate.read_text(encoding="utf-8").strip()
        except Exception:
            continue
        if not text:
            continue
        try:
            return json.loads(text)
        except Exception:
            return text
    return None


def _audiobook_cartesia_api_key() -> str:
    for name in _AUDIOBOOK_CARTESIA_DIRECT_KEY_ENV_NAMES:
        value = str(os.getenv(name) or "").strip()
        if value:
            return value
    for name in _AUDIOBOOK_CARTESIA_INLINE_CREDENTIAL_ENV_NAMES:
        value = _audiobook_cartesia_api_key_from_payload(os.getenv(name))
        if value:
            return value
    for name in _AUDIOBOOK_CARTESIA_CREDENTIAL_FILE_ENV_NAMES:
        value = _audiobook_cartesia_api_key_from_payload(_load_audiobook_cartesia_credential_file(os.getenv(name)))
        if value:
            return value
    for path in _AUDIOBOOK_CARTESIA_DEFAULT_CREDENTIAL_FILES:
        value = _audiobook_cartesia_api_key_from_payload(_load_audiobook_cartesia_credential_file(path))
        if value:
            return value
    return ""


def _audiobook_cartesia_language(language: str) -> str:
    normalized = str(language or "").strip().lower()
    if normalized.startswith("de"):
        return "de"
    return normalized or "de"


def _audiobook_cartesia_transcript_text(payload: object) -> str:
    if isinstance(payload, str):
        return payload.strip()
    if not isinstance(payload, dict):
        return ""
    for key in ("text", "transcript", "transcript_text"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    for key in ("result", "response", "data"):
        nested = _audiobook_cartesia_transcript_text(payload.get(key))
        if nested:
            return nested
    return ""


def _transcribe_audiobook_publication_stt_sample_with_cartesia(*, sample_path: Path, language: str) -> dict[str, object]:
    api_key = _audiobook_cartesia_api_key()
    if not api_key:
        return {"status": "failed", "reason": "cartesia_api_key_missing", "transcriber": "cartesia/ink-whisper"}
    try:
        import requests

        response = requests.post(
            _AUDIOBOOK_CARTESIA_STT_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Cartesia-Version": _AUDIOBOOK_CARTESIA_VERSION,
                "Accept": "application/json",
                "User-Agent": "EA-Audiobook-STT/1.0",
            },
            data={
                "model": _AUDIOBOOK_CARTESIA_STT_MODEL,
                "language": _audiobook_cartesia_language(language),
                "timestamp_granularities[]": "word",
            },
            files={"file": ("audiobook-publication-sample.wav", sample_path.read_bytes(), "audio/wav")},
            timeout=_env_int("EA_AUDIOBOOK_PUBLICATION_STT_TIMEOUT_SECONDS", 120, minimum=10, maximum=900),
        )
        if response.status_code >= 400:
            return {
                "status": "failed",
                "reason": f"cartesia_http_{response.status_code}",
                "transcriber": "cartesia/ink-whisper",
            }
        parsed = response.json()
    except Exception as exc:
        return {"status": "failed", "reason": type(exc).__name__, "transcriber": "cartesia/ink-whisper"}
    text = _audiobook_cartesia_transcript_text(parsed)
    return {
        "status": "transcribed" if text else "failed",
        "reason": "" if text else "cartesia_transcript_empty",
        "transcript_text": text,
        "transcriber": "cartesia/ink-whisper",
    }


def _transcribe_audiobook_publication_stt_sample(*, sample_path: Path, language: str) -> dict[str, object]:
    command_raw = str(os.getenv("EA_AUDIOBOOK_PUBLICATION_STT_COMMAND") or "").strip()
    if command_raw:
        try:
            command = [
                part.format(audio_path=str(sample_path), language=str(language or ""))
                for part in shlex.split(command_raw)
            ]
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=_env_int("EA_AUDIOBOOK_PUBLICATION_STT_TIMEOUT_SECONDS", 120, minimum=10, maximum=900),
            )
        except Exception as exc:
            return {"status": "failed", "reason": type(exc).__name__, "transcriber": "command"}
        text = str(completed.stdout or "").strip()
        if text.startswith("{"):
            try:
                payload = json.loads(text)
                text = str(payload.get("transcript_text") or payload.get("text") or payload.get("transcript") or "").strip()
            except Exception:
                pass
        return {
            "status": "transcribed" if completed.returncode == 0 and text else "failed",
            "reason": "" if completed.returncode == 0 and text else "stt_command_failed",
            "transcript_text": text,
            "transcriber": "command",
            "returncode": completed.returncode,
        }
    cartesia = _transcribe_audiobook_publication_stt_sample_with_cartesia(sample_path=sample_path, language=language)
    if str(cartesia.get("status") or "") == "transcribed" or str(cartesia.get("reason") or "") != "cartesia_api_key_missing":
        return cartesia
    try:
        from app.api.routes import public_memorials

        result = public_memorials._memorial_transcribe_audio_blob(  # noqa: SLF001
            payload=sample_path.read_bytes(),
            content_type="audio/wav",
        )
    except Exception as exc:
        return {"status": "failed", "reason": type(exc).__name__, "transcriber": "runtime"}
    return {
        "status": str(result.get("transcription_status") or "").strip() or "unknown",
        "reason": str(result.get("detail") or result.get("reason") or "").strip(),
        "transcript_text": str(result.get("transcript_text") or "").strip(),
        "transcriber": str(result.get("transcriber") or "runtime").strip(),
    }


def _audiobook_publication_stt_resample_shifts() -> tuple[float, ...]:
    raw = str(os.getenv("EA_AUDIOBOOK_PUBLICATION_STT_RESAMPLE_SHIFTS_SECONDS") or "45,-45,90,-90").strip()
    shifts: list[float] = []
    for item in re.split(r"[,;\s]+", raw):
        if not item:
            continue
        try:
            value = float(item)
        except ValueError:
            continue
        if value and abs(value) <= 600:
            shifts.append(value)
    return tuple(shifts)


def _audiobook_publication_stt_candidate_offsets(
    *,
    offset_seconds: float,
    duration_seconds: float,
    sample_seconds: int,
) -> tuple[float, ...]:
    max_offset = max(0.0, float(duration_seconds or 0.0) - float(sample_seconds))
    candidates: list[float] = []
    for shift in (0.0, *_audiobook_publication_stt_resample_shifts()):
        candidate = min(max(0.0, float(offset_seconds or 0.0) + shift), max_offset)
        rounded = round(candidate, 3)
        if rounded not in candidates:
            candidates.append(rounded)
    return tuple(candidates)


def _audiobook_publication_stt_sample_retryable_issue(issue: str) -> bool:
    return str(issue or "").strip() in {"stt_sample_extract_failed", "stt_transcript_too_short"}


def _build_audiobook_publication_stt_gate(
    *,
    job: dict[str, object],
    target_path: Path,
    duration_seconds: float,
) -> dict[str, object]:
    required = _audiobook_publication_stt_required()
    enabled = _audiobook_publication_stt_enabled()
    if not enabled:
        return {"status": "skipped", "required": required, "enabled": False, "raw_text_exposed": False}
    source_text = _audiobook_publication_source_text(job)
    source_tokens = _publication_stt_tokens(source_text)
    source_token_set = set(source_tokens)
    if not source_token_set:
        return {
            "status": "fail" if required else "skipped",
            "required": required,
            "enabled": enabled,
            "issue": "stt_source_text_missing",
            "source_text_sha256": _sha256_bytes(source_text.encode("utf-8")) if source_text else "",
            "source_token_count": len(source_tokens),
            "raw_text_exposed": False,
        }
    sample_seconds = _env_int("EA_AUDIOBOOK_PUBLICATION_STT_SAMPLE_SECONDS", 30, minimum=5, maximum=180)
    sample_count = _env_int("EA_AUDIOBOOK_PUBLICATION_STT_SAMPLE_COUNT", 3, minimum=1, maximum=7)
    min_tokens = _env_int("EA_AUDIOBOOK_PUBLICATION_STT_MIN_TRANSCRIPT_TOKENS", 8, minimum=1, maximum=200)
    min_overlap = _env_float("EA_AUDIOBOOK_PUBLICATION_STT_MIN_BOOK_TOKEN_OVERLAP", 0.55, minimum=0.1, maximum=1.0)
    offsets = _audiobook_publication_stt_offsets(
        duration_seconds=duration_seconds,
        sample_seconds=sample_seconds,
        sample_count=sample_count,
    )
    samples: list[dict[str, object]] = []
    issues: list[str] = []
    language = str(dict(job.get("metadata") or {}).get("language") or "").strip()
    with tempfile.TemporaryDirectory(prefix="ea-audiobook-stt-gate-") as tmp:
        tmp_root = Path(tmp)
        for index, offset in enumerate(offsets):
            attempts: list[dict[str, object]] = []
            for attempt_index, candidate_offset in enumerate(
                _audiobook_publication_stt_candidate_offsets(
                    offset_seconds=offset,
                    duration_seconds=duration_seconds,
                    sample_seconds=sample_seconds,
                ),
                start=1,
            ):
                sample_path = tmp_root / f"sample-{index + 1:02d}-{attempt_index:02d}.wav"
                extracted = _extract_audiobook_publication_stt_sample(
                    target_path=target_path,
                    output_path=sample_path,
                    offset_seconds=candidate_offset,
                    sample_seconds=sample_seconds,
                )
                if str(extracted.get("status") or "") != "ready":
                    attempt = {
                        "index": index + 1,
                        "offset_seconds": candidate_offset,
                        "status": "fail",
                        "issue": "stt_sample_extract_failed",
                        "reason": str(extracted.get("reason") or "").strip(),
                        "extractor_seek_mode": str(extracted.get("seek_mode") or "").strip(),
                        "raw_text_exposed": False,
                    }
                    attempts.append(attempt)
                    if _audiobook_publication_stt_sample_retryable_issue(str(attempt.get("issue") or "")):
                        continue
                    break
                transcribed = _transcribe_audiobook_publication_stt_sample(sample_path=sample_path, language=language)
                transcript = str(transcribed.get("transcript_text") or "").strip()
                transcript_tokens = _publication_stt_tokens(transcript)
                transcript_unique = set(transcript_tokens)
                token_overlap = (
                    sum(1 for token in transcript_tokens if token in source_token_set) / float(len(transcript_tokens))
                    if transcript_tokens
                    else 0.0
                )
                unique_overlap = (
                    len(transcript_unique & source_token_set) / float(len(transcript_unique))
                    if transcript_unique
                    else 0.0
                )
                issue = ""
                if str(transcribed.get("status") or "") not in {"transcribed", "ok"}:
                    issue = "stt_transcription_failed"
                elif len(transcript_tokens) < min_tokens:
                    issue = "stt_transcript_too_short"
                elif token_overlap < min_overlap or unique_overlap < min_overlap:
                    issue = "stt_transcript_not_book_text"
                attempt = {
                    "index": index + 1,
                    "offset_seconds": candidate_offset,
                    "status": "fail" if issue else "pass",
                    "issue": issue,
                    "transcriber": str(transcribed.get("transcriber") or "").strip(),
                    "extractor_seek_mode": str(extracted.get("seek_mode") or "").strip(),
                    "transcript_sha256": _sha256_bytes(transcript.encode("utf-8")) if transcript else "",
                    "transcript_token_count": len(transcript_tokens),
                    "book_token_overlap": round(token_overlap, 4),
                    "book_unique_token_overlap": round(unique_overlap, 4),
                    "raw_text_exposed": False,
                }
                attempts.append(attempt)
                if not _audiobook_publication_stt_sample_retryable_issue(issue):
                    break
            selected = next((attempt for attempt in attempts if str(attempt.get("status") or "") == "pass"), attempts[-1])
            selected["primary_offset_seconds"] = offset
            selected["attempt_count"] = len(attempts)
            if len(attempts) > 1:
                selected["alternate_offsets_tried"] = [attempt.get("offset_seconds") for attempt in attempts[1:]]
                selected["recovered_from_issue"] = str(attempts[0].get("issue") or "").strip()
            issue = str(selected.get("issue") or "").strip()
            if issue:
                issues.append(issue)
            samples.append(selected)
    warnings: list[str] = []
    if sorted(set(issues)) == ["stt_transcript_too_short"] and len(samples) >= 3:
        short_samples = [
            sample
            for sample in samples
            if str(sample.get("issue") or "").strip() == "stt_transcript_too_short"
        ]
        passed_count = sum(1 for sample in samples if str(sample.get("status") or "") == "pass")
        tolerated_short_limit = max(1, len(samples) // 3)
        short_samples_match_book = all(
            int(sample.get("transcript_token_count") or 0) > 0
            and float(sample.get("book_token_overlap") or 0.0) >= min_overlap
            and float(sample.get("book_unique_token_overlap") or 0.0) >= min_overlap
            for sample in short_samples
        )
        if (
            short_samples
            and len(short_samples) <= tolerated_short_limit
            and passed_count >= len(samples) - len(short_samples)
            and short_samples_match_book
        ):
            warnings.append("stt_transcript_too_short_tolerated_book_text")
            issues = []
            for sample in short_samples:
                sample["status"] = "pass"
                sample["warning"] = "stt_transcript_too_short_tolerated_book_text"
                sample["issue"] = ""
    return {
        "status": "fail" if issues else "pass",
        "required": required,
        "enabled": enabled,
        "issues": sorted(set(issues)),
        "warnings": sorted(set(warnings)),
        "sample_count": len(samples),
        "passed_samples": sum(1 for sample in samples if str(sample.get("status") or "") == "pass"),
        "failed_samples": sum(1 for sample in samples if str(sample.get("status") or "") == "fail"),
        "sample_seconds": sample_seconds,
        "min_transcript_tokens": min_tokens,
        "min_book_token_overlap": min_overlap,
        "short_book_text_tolerance": "v1",
        "source_text_sha256": _sha256_bytes(source_text.encode("utf-8")),
        "source_token_count": len(source_tokens),
        "samples": samples,
        "raw_text_exposed": False,
    }


def _build_audiobook_publication_gate(*, job: dict[str, object], target_path: Path) -> dict[str, object]:
    issues: list[str] = []
    if not target_path.is_file():
        issues.append("target_file_missing")
    import_root = audiobookshelf_import_root().expanduser().resolve()
    if target_path.is_file():
        resolved = target_path.resolve()
        if resolved != import_root and import_root not in resolved.parents:
            issues.append("target_file_outside_import_root")
    if str(job.get("status") or "").strip() in {"waiting_voice_selection", "blocked_audio_quality"}:
        issues.append("job_not_publication_ready")
    public_share = _audiobook_public_share_for_job(job)
    if str(public_share.get("status") or "").strip() == "revoked_wrong_voice":
        issues.append("public_share_revoked_wrong_voice")
    voice_selection = dict(dict(job.get("provider") or {}).get("voice_selection") or {})
    local_fallback = dict(voice_selection.get("local_fallback_render") or {})
    if str(local_fallback.get("status") or "").strip() == "revoked_wrong_voice":
        issues.append("audiobook_voice_revoked_wrong_voice")

    probe = _probe_audio_publication_file(target_path) if target_path.is_file() else {}
    streams = probe.get("streams") if isinstance(probe.get("streams"), list) else []
    chapters = probe.get("chapters") if isinstance(probe.get("chapters"), list) else []
    audio_streams = [stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "audio"]
    cover_streams = [stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "video"]
    if target_path.is_file() and probe.get("probe_error"):
        issues.append("ffprobe_failed")
    if target_path.is_file() and len(audio_streams) != 1:
        issues.append("audio_stream_count_invalid")
    if target_path.is_file() and len(chapters) < 1:
        issues.append("chapter_metadata_missing")
    if target_path.is_file() and len(cover_streams) < 1:
        issues.append("cover_art_missing")

    head_volume = _audio_publication_volume(target_path, position="head") if target_path.is_file() else {}
    tail_volume = _audio_publication_volume(target_path, position="tail") if target_path.is_file() else {}
    volume = {
        **head_volume,
        "head": head_volume,
        "tail": tail_volume,
    }
    min_mean_db = _env_float("EA_AUDIOBOOK_PUBLICATION_MIN_MEAN_VOLUME_DB", -30.0, minimum=-60.0, maximum=-10.0)
    min_tail_mean_db = _env_float("EA_AUDIOBOOK_PUBLICATION_TAIL_MIN_MEAN_VOLUME_DB", -35.0, minimum=-60.0, maximum=-10.0)
    mean_volume_raw = str(head_volume.get("mean_volume_db") or "").strip()
    tail_mean_volume_raw = str(tail_volume.get("mean_volume_db") or "").strip()
    if target_path.is_file() and str(head_volume.get("status") or "") != "checked":
        issues.append("volume_probe_failed")
    elif mean_volume_raw:
        try:
            if float(mean_volume_raw) < min_mean_db:
                issues.append("audio_too_quiet")
        except ValueError:
            issues.append("volume_probe_invalid")
    if target_path.is_file() and str(tail_volume.get("status") or "") != "checked":
        issues.append("tail_volume_probe_failed")
    elif tail_mean_volume_raw:
        try:
            if float(tail_mean_volume_raw) < min_tail_mean_db:
                issues.append("audio_tail_too_quiet")
        except ValueError:
            issues.append("tail_volume_probe_invalid")

    duration_seconds = float(dict(probe.get("format") or {}).get("duration") or 0.0) if isinstance(probe.get("format"), dict) else 0.0
    stt_gate = (
        _build_audiobook_publication_stt_gate(
            job=job,
            target_path=target_path,
            duration_seconds=duration_seconds,
        )
        if target_path.is_file()
        else {"status": "skipped", "required": _audiobook_publication_stt_required(), "enabled": False, "raw_text_exposed": False}
    )
    if str(stt_gate.get("status") or "") == "fail":
        for issue in list(stt_gate.get("issues") or []):
            normalized_issue = str(issue or "").strip()
            if normalized_issue:
                issues.append(normalized_issue)
        issue = str(stt_gate.get("issue") or "").strip()
        if issue:
            issues.append(issue)

    return {
        "contract_name": "ea.audiobook_publication_audio_gate.v1",
        "checked_at": _now_iso(),
        "status": "fail" if issues else "pass",
        "issues": sorted(set(issues)),
        "target_file_sha256": _sha256_file(target_path) if target_path.is_file() else "",
        "target_file_size": int(target_path.stat().st_size) if target_path.is_file() else 0,
        "audio_streams": len(audio_streams),
        "cover_streams": len(cover_streams),
        "chapters": len(chapters),
        "duration_seconds": duration_seconds,
        "volume": volume,
        "stt": stt_gate,
        "min_mean_volume_db": min_mean_db,
        "min_tail_mean_volume_db": min_tail_mean_db,
        "raw_paths_exposed": False,
    }


def _preserve_ready_audiobookshelf_access(
    *,
    import_result: dict[str, object],
    previous_import: dict[str, object],
) -> dict[str, object]:
    if not previous_import:
        return import_result
    current_share = dict(import_result.get("public_share") or {})
    if str(current_share.get("status") or "").strip() == "blocked_audio_publication_gate":
        import_result["player_scoped_reference"] = _blocked_player_scoped_reference(
            reason=str(current_share.get("reason") or "blocked_audio_publication_gate")
        )
        return import_result
    previous_reference = dict(previous_import.get("player_scoped_reference") or {})
    current_reference = dict(import_result.get("player_scoped_reference") or {})
    if (
        str(previous_reference.get("status") or "").strip() == "signed_reference_ready"
        and str(current_reference.get("status") or "").strip() != "signed_reference_ready"
    ):
        import_result["player_scoped_reference"] = previous_reference
    previous_share = dict(previous_import.get("public_share") or {})
    if (
        str(previous_share.get("status") or "").strip() == "public_share_ready"
        and str(current_share.get("status") or "").strip() != "public_share_ready"
    ):
        preserved = dict(previous_share)
        preserved["preserved_after_refresh_failure"] = True
        refresh_reason = str(current_share.get("reason") or current_share.get("detail") or "").strip()
        if refresh_reason:
            preserved["latest_refresh_reason"] = refresh_reason[:240]
        import_result["public_share"] = preserved
    return import_result


def _audiobookshelf_api_base_url() -> str:
    return str(os.getenv("EA_AUDIOBOOKSHELF_API_BASE_URL") or os.getenv("AUDIOBOOKSHELF_API_BASE_URL") or "").strip().rstrip("/")


def _audiobookshelf_public_base_url() -> str:
    return str(
        os.getenv("EA_AUDIOBOOKSHELF_PUBLIC_BASE_URL")
        or os.getenv("AUDIOBOOKSHELF_PUBLIC_BASE_URL")
        or _audiobookshelf_api_base_url()
    ).strip().rstrip("/")


def _audiobookshelf_api_token() -> str:
    return str(os.getenv("EA_AUDIOBOOKSHELF_API_TOKEN") or os.getenv("AUDIOBOOKSHELF_API_TOKEN") or "").strip()


def _audiobookshelf_library_id() -> str:
    return str(os.getenv("EA_AUDIOBOOKSHELF_LIBRARY_ID") or os.getenv("AUDIOBOOKSHELF_LIBRARY_ID") or "").strip()


def _audiobookshelf_share_expires_at_ms() -> int:
    days = _env_int("EA_AUDIOBOOKSHELF_PUBLIC_SHARE_EXPIRES_DAYS", _env_int("EA_AUDIOBOOK_ACCESS_EXPIRES_DAYS", 30, minimum=0), minimum=0, maximum=3650)
    if days <= 0:
        return 0
    return int((time.time() + days * 86400) * 1000)


def _audiobookshelf_public_share_downloadable() -> bool:
    return _env_bool("EA_AUDIOBOOKSHELF_PUBLIC_SHARE_DOWNLOADABLE", False)


def _audiobookshelf_item_lookup_limit() -> int:
    return _env_int("EA_AUDIOBOOKSHELF_ITEM_LOOKUP_LIMIT", 50, minimum=1, maximum=500)


def _audiobookshelf_scan_poll_seconds() -> int:
    return _env_int("EA_AUDIOBOOKSHELF_SCAN_POLL_SECONDS", 90, minimum=0, maximum=900)


def _audiobookshelf_scan_poll_interval_seconds() -> float:
    return _env_float("EA_AUDIOBOOKSHELF_SCAN_POLL_INTERVAL_SECONDS", 5.0, minimum=0.1, maximum=60.0)


def _audiobookshelf_api_ready() -> bool:
    return bool(_audiobookshelf_api_base_url() and _audiobookshelf_api_token() and _audiobookshelf_library_id())


def _audiobookshelf_library_folders() -> tuple[Path, ...]:
    if not _audiobookshelf_api_ready():
        return ()
    try:
        status, payload, _text = _audiobookshelf_json_request(
            method="GET",
            path=f"/api/libraries/{urllib.parse.quote(_audiobookshelf_library_id())}",
        )
    except Exception:
        return ()
    if status >= 400:
        return ()
    folders: list[Path] = []
    for row in list(payload.get("folders") or []):
        if not isinstance(row, dict):
            continue
        full_path = str(row.get("fullPath") or "").strip()
        if full_path:
            folders.append(Path(full_path))
    return tuple(folders)


def _path_is_within(candidate: Path, root: Path) -> bool:
    try:
        resolved_candidate = candidate.expanduser().resolve()
        resolved_root = root.expanduser().resolve()
    except Exception:
        resolved_candidate = candidate.expanduser()
        resolved_root = root.expanduser()
    return resolved_candidate == resolved_root or resolved_root in resolved_candidate.parents


def _path_is_existing_writable_dir(path: Path) -> bool:
    try:
        return path.expanduser().is_dir() and os.access(path.expanduser(), os.W_OK)
    except Exception:
        return False


def _trust_audiobookshelf_library_folder_paths() -> bool:
    return _env_bool("EA_AUDIOBOOKSHELF_TRUST_LIBRARY_FOLDER_PATHS", False)


def _effective_audiobookshelf_import_root(configured_root: Path) -> tuple[Path, dict[str, object]]:
    library_folders = _audiobookshelf_library_folders()
    if not library_folders:
        return configured_root, {"source": "configured_root", "library_folder_checked": False}
    if any(_path_is_within(configured_root, folder) for folder in library_folders):
        return configured_root, {"source": "configured_root", "library_folder_checked": True}
    if not _trust_audiobookshelf_library_folder_paths():
        return configured_root, {
            "source": "configured_root_library_folder_mismatch",
            "configured_root": str(configured_root),
            "configured_root_in_library": False,
            "library_folder_checked": True,
            "library_folder_paths_trusted": False,
        }
    preferred = [
        folder
        for folder in library_folders
        if _path_storage_kind(folder) in {"durable", "pcloud"} and _normalize_tag(folder.name) == "audiobooks"
    ]
    writable_preferred = [folder for folder in preferred if _path_is_existing_writable_dir(folder)]
    writable_durable = [
        folder
        for folder in library_folders
        if _path_storage_kind(folder) in {"durable", "pcloud"} and _path_is_existing_writable_dir(folder)
    ]
    writable_any = [folder for folder in library_folders if _path_is_existing_writable_dir(folder)]
    fallback = writable_preferred or writable_durable or writable_any
    if not fallback:
        return configured_root, {
            "source": "configured_root_library_folder_unavailable",
            "configured_root": str(configured_root),
            "configured_root_in_library": False,
            "library_folder_checked": True,
        }
    chosen = fallback[0] if fallback else configured_root
    return chosen, {
        "source": "audiobookshelf_library_folder",
        "configured_root": str(configured_root),
        "configured_root_in_library": False,
        "library_folder_checked": True,
    }


def _audiobookshelf_public_share_url(slug: str) -> str:
    base = _audiobookshelf_public_base_url()
    if not base or not slug:
        return ""
    return f"{base}/share/{urllib.parse.quote(slug.strip())}"


def _audiobookshelf_json_request(
    *,
    method: str,
    path: str,
    payload: dict[str, object] | None = None,
    query: dict[str, object] | None = None,
) -> tuple[int, dict[str, object], str]:
    base = _audiobookshelf_api_base_url()
    token = _audiobookshelf_api_token()
    if not base or not token:
        raise RuntimeError("audiobookshelf_api_not_configured")
    normalized_path = "/" + str(path or "").lstrip("/")
    url = f"{base}{normalized_path}"
    if query:
        url = f"{url}?{urllib.parse.urlencode({key: value for key, value in query.items() if value is not None})}"
    body = None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(request, timeout=_env_int("EA_AUDIOBOOKSHELF_API_TIMEOUT_SECONDS", 15, minimum=3, maximum=120)) as response:
            raw = response.read()
            status = int(getattr(response, "status", 200) or 200)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = int(exc.code)
    text = raw.decode("utf-8", errors="replace") if raw else ""
    parsed: dict[str, object] = {}
    if text.strip():
        try:
            loaded = json.loads(text)
            if isinstance(loaded, dict):
                parsed = loaded
        except Exception:
            parsed = {}
    return status, parsed, text


def _audiobookshelf_scan_library() -> dict[str, object]:
    library_id = _audiobookshelf_library_id()
    if not library_id:
        return {"status": "missing_config", "reason": "audiobookshelf_library_id_missing"}
    status, payload, text = _audiobookshelf_json_request(method="POST", path=f"/api/libraries/{urllib.parse.quote(library_id)}/scan")
    if status >= 400:
        return {"status": "scan_failed", "http_status": status, "detail": text[:240]}
    return {"status": "scan_requested", "http_status": status, "response_keys": sorted(payload.keys())[:12]}


def _normalize_match_text(value: object) -> str:
    return _normalize_tag(Path(str(value or "").strip()).stem)


def _audiobookshelf_item_media(row: dict[str, object]) -> dict[str, object]:
    media = row.get("media")
    return dict(media) if isinstance(media, dict) else {}


def _audiobookshelf_item_share(row: dict[str, object]) -> dict[str, object]:
    share = row.get("mediaItemShare")
    return dict(share) if isinstance(share, dict) else {}


def _audiobookshelf_item_has_audio(row: dict[str, object]) -> bool:
    media = _audiobookshelf_item_media(row)
    for payload in (row, media):
        for key in ("numAudioFiles", "audioFileCount", "audioFilesCount"):
            try:
                if int(payload.get(key) or 0) > 0:
                    return True
            except (TypeError, ValueError):
                continue
        audio_files = payload.get("audioFiles")
        if isinstance(audio_files, list) and audio_files:
            return True
    audio_extensions = {".m4b", ".m4a", ".mp3", ".aac", ".flac", ".ogg", ".opus", ".wav"}
    candidate_paths = [
        str(row.get("path") or ""),
        str(row.get("relPath") or ""),
    ]
    for library_file in list(row.get("libraryFiles") or []):
        if not isinstance(library_file, dict):
            continue
        file_metadata = dict(library_file.get("metadata") or {})
        candidate_paths.extend(
            [
                str(file_metadata.get("path") or ""),
                str(file_metadata.get("relPath") or ""),
                str(file_metadata.get("filename") or ""),
            ]
        )
    return any(Path(candidate).suffix.lower() in audio_extensions for candidate in candidate_paths if candidate)


def _audiobookshelf_item_matches_import(*, row: dict[str, object], target_path: Path, metadata: EpubMetadata) -> bool:
    target_name = target_path.name
    target_stem = _normalize_match_text(target_name)
    target_resolved = str(target_path)
    candidate_paths = [
        str(row.get("path") or ""),
        str(row.get("relPath") or ""),
    ]
    for library_file in list(row.get("libraryFiles") or []):
        if not isinstance(library_file, dict):
            continue
        file_metadata = dict(library_file.get("metadata") or {})
        candidate_paths.extend(
            [
                str(file_metadata.get("path") or ""),
                str(file_metadata.get("relPath") or ""),
                str(file_metadata.get("filename") or ""),
            ]
        )
    for candidate in candidate_paths:
        if candidate and (candidate == target_resolved or candidate.endswith(f"/{target_name}") or candidate.endswith(target_name)):
            return True
    media = _audiobookshelf_item_media(row)
    media_metadata = dict(media.get("metadata") or {})
    title_match = _normalize_match_text(media_metadata.get("title") or media.get("title") or "")
    return bool(target_stem and title_match and target_stem == title_match)


def _find_audiobookshelf_imported_item(*, target_path: Path, metadata: EpubMetadata) -> dict[str, object]:
    library_id = _audiobookshelf_library_id()
    status, payload, text = _audiobookshelf_json_request(
        method="GET",
        path=f"/api/libraries/{urllib.parse.quote(library_id)}/items",
        query={
            "limit": _audiobookshelf_item_lookup_limit(),
            "page": 0,
            "sort": "addedAt",
            "desc": 1,
            "include": "share",
        },
    )
    if status >= 400:
        return {"status": "lookup_failed", "http_status": status, "detail": text[:240]}
    for raw_row in list(payload.get("results") or []):
        if not isinstance(raw_row, dict):
            continue
        row = dict(raw_row)
        if str(row.get("mediaType") or "") != "book":
            continue
        if _audiobookshelf_item_matches_import(row=row, target_path=target_path, metadata=metadata):
            if not _audiobookshelf_item_has_audio(row):
                continue
            media = _audiobookshelf_item_media(row)
            media_id = str(media.get("id") or "").strip()
            if not media_id:
                return {"status": "item_missing_media_id", "library_item_id": str(row.get("id") or "").strip()}
            share = _audiobookshelf_item_share(row)
            return {
                "status": "item_found",
                "library_item_id": str(row.get("id") or "").strip(),
                "media_item_id": media_id,
                "existing_share": {
                    "id": str(share.get("id") or "").strip(),
                    "slug": str(share.get("slug") or "").strip(),
                    "expires_at": str(share.get("expiresAt") or "").strip(),
                    "is_downloadable": bool(share.get("isDownloadable")),
                }
                if share
                else {},
            }
    return {"status": "item_not_found", "checked": len(list(payload.get("results") or []))}


def _audiobookshelf_share_slug(*, job: dict[str, object], metadata: EpubMetadata, target_path: Path) -> str:
    base = _normalize_tag(f"{metadata.author} {metadata.title}") or _normalize_tag(target_path.stem) or "ea-audiobook"
    if len(base) > 48:
        base = base[:48].strip("_")
    digest = _sha256_bytes(f"{job.get('job_id') or target_path}:{target_path.name}".encode("utf-8"))[:10]
    return f"ea-{base.replace('_', '-')}-{digest}"


def _create_or_reuse_audiobookshelf_public_share(
    *,
    job: dict[str, object],
    import_result: dict[str, object],
    metadata: EpubMetadata,
) -> dict[str, object]:
    if not audiobookshelf_public_share_enabled():
        return {"status": "disabled"}
    if not _audiobookshelf_api_ready():
        return {
            "status": "missing_config",
            "api_base_url_present": bool(_audiobookshelf_api_base_url()),
            "api_token_present": bool(_audiobookshelf_api_token()),
            "library_id_present": bool(_audiobookshelf_library_id()),
            "token_exposed": False,
        }
    target_path = Path(str(import_result.get("target_path") or ""))
    if not target_path.is_file():
        return {"status": "waiting_for_imported_file"}
    try:
        scan = _audiobookshelf_scan_library()
        deadline = time.time() + _audiobookshelf_scan_poll_seconds()
        item: dict[str, object] = {"status": "item_not_found"}
        while True:
            item = _find_audiobookshelf_imported_item(target_path=target_path, metadata=metadata)
            if str(item.get("status") or "") == "item_found":
                break
            if time.time() >= deadline:
                break
            time.sleep(_audiobookshelf_scan_poll_interval_seconds())
        if str(item.get("status") or "") != "item_found":
            return {
                "status": "waiting_for_audiobookshelf_scan",
                "scan": scan,
                "lookup": item,
                "telegram_followup_pending": True,
                "token_exposed": False,
                "raw_library_path_exposed": False,
            }
        existing_share = dict(item.get("existing_share") or {})
        existing_slug = str(existing_share.get("slug") or "").strip()
        if existing_slug:
            return {
                "status": "public_share_ready",
                "source": "existing_audiobookshelf_share",
                "library_item_id_sha256": _sha256_bytes(str(item.get("library_item_id") or "").encode("utf-8")),
                "media_item_id_sha256": _sha256_bytes(str(item.get("media_item_id") or "").encode("utf-8")),
                "slug_sha256": _sha256_bytes(existing_slug.encode("utf-8")),
                "absolute_url": _audiobookshelf_public_share_url(existing_slug),
                "expires_at": existing_share.get("expires_at") or "",
                "is_downloadable": bool(existing_share.get("is_downloadable")),
                "token_exposed": False,
                "raw_library_path_exposed": False,
            }
        slug = _audiobookshelf_share_slug(job=job, metadata=metadata, target_path=target_path)
        payload = {
            "slug": slug,
            "expiresAt": _audiobookshelf_share_expires_at_ms(),
            "mediaItemType": "book",
            "mediaItemId": str(item.get("media_item_id") or ""),
            "isDownloadable": _audiobookshelf_public_share_downloadable(),
        }
        status, created, text = _audiobookshelf_json_request(method="POST", path="/api/share/mediaitem", payload=payload)
        if status == 409 and "already shared" in text.lower():
            item = _find_audiobookshelf_imported_item(target_path=target_path, metadata=metadata)
            existing_share = dict(item.get("existing_share") or {})
            existing_slug = str(existing_share.get("slug") or "").strip()
            if existing_slug:
                return {
                    "status": "public_share_ready",
                    "source": "existing_audiobookshelf_share",
                    "library_item_id_sha256": _sha256_bytes(str(item.get("library_item_id") or "").encode("utf-8")),
                    "media_item_id_sha256": _sha256_bytes(str(item.get("media_item_id") or "").encode("utf-8")),
                    "slug_sha256": _sha256_bytes(existing_slug.encode("utf-8")),
                    "absolute_url": _audiobookshelf_public_share_url(existing_slug),
                    "expires_at": existing_share.get("expires_at") or "",
                    "is_downloadable": bool(existing_share.get("is_downloadable")),
                    "token_exposed": False,
                    "raw_library_path_exposed": False,
                }
        if status >= 400:
            return {"status": "share_failed", "http_status": status, "detail": text[:240], "token_exposed": False}
        created_slug = str(created.get("slug") or slug).strip()
        return {
            "status": "public_share_ready",
            "source": "created_audiobookshelf_share",
            "library_item_id_sha256": _sha256_bytes(str(item.get("library_item_id") or "").encode("utf-8")),
            "media_item_id_sha256": _sha256_bytes(str(item.get("media_item_id") or "").encode("utf-8")),
            "share_id_sha256": _sha256_bytes(str(created.get("id") or "").encode("utf-8")) if created.get("id") else "",
            "slug_sha256": _sha256_bytes(created_slug.encode("utf-8")),
            "absolute_url": _audiobookshelf_public_share_url(created_slug),
            "expires_at": str(created.get("expiresAt") or "").strip(),
            "is_downloadable": bool(created.get("isDownloadable")),
            "token_exposed": False,
            "raw_library_path_exposed": False,
        }
    except Exception as exc:
        return {
            "status": "share_failed",
            "reason": _exception_detail(exc)[:240],
            "token_exposed": False,
            "raw_library_path_exposed": False,
        }


def _base64url_encode(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _base64url_decode(payload: str) -> bytes:
    padding = "=" * ((4 - len(payload) % 4) % 4)
    return base64.urlsafe_b64decode((payload + padding).encode("ascii"))


def _audiobook_access_secret() -> str:
    return str(os.getenv("EA_AUDIOBOOK_ACCESS_SIGNING_SECRET") or "").strip()


def _sign_player_access_payload(payload: dict[str, object]) -> str:
    secret = _audiobook_access_secret()
    if not secret:
        return ""
    header = {"alg": "HS256", "typ": "EA_AUDIOBOOK_ACCESS"}
    encoded_header = _base64url_encode(json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    encoded_payload = _base64url_encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(secret.encode("utf-8"), f"{encoded_header}.{encoded_payload}".encode("ascii"), hashlib.sha256).digest()
    return f"{encoded_header}.{encoded_payload}.{_base64url_encode(signature)}"


def verify_player_scoped_audiobook_token(token: str) -> dict[str, object]:
    secret = _audiobook_access_secret()
    if not secret:
        raise RuntimeError("audiobook_access_signing_secret_missing")
    parts = str(token or "").strip().split(".")
    if len(parts) != 3:
        raise RuntimeError("audiobook_access_token_invalid")
    signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
    expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    actual = _base64url_decode(parts[2])
    if not hmac.compare_digest(expected, actual):
        raise RuntimeError("audiobook_access_token_signature_invalid")
    payload = json.loads(_base64url_decode(parts[1]).decode("utf-8"))
    expires_at = str(dict(payload).get("expires_at") or "").strip()
    if expires_at:
        try:
            expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        except Exception as exc:
            raise RuntimeError("audiobook_access_token_expiry_invalid") from exc
        if expiry < datetime.now(UTC):
            raise RuntimeError("audiobook_access_token_expired")
    return dict(payload)


def resolve_player_scoped_audiobook_file(token: str) -> tuple[Path, dict[str, object]]:
    token_payload = verify_player_scoped_audiobook_token(token)
    job_id = str(token_payload.get("job_id") or "").strip()
    if not job_id or "/" in job_id or "\\" in job_id or job_id.startswith("."):
        raise RuntimeError("audiobook_access_job_id_invalid")
    job_dir = audiobook_jobs_root() / job_id
    job = _load_job(job_dir)
    gate_reason = _audiobook_publication_gate_reason(job)
    if gate_reason:
        raise RuntimeError(f"audiobook_access_publication_gate_failed:{gate_reason}")
    import_result = dict(job.get("audiobookshelf_import") or {})
    target_path = Path(str(import_result.get("target_path") or "")).expanduser()
    if str(import_result.get("status") or "") != "imported" or not target_path.is_file():
        raise RuntimeError("audiobook_access_file_not_ready")
    import_root = audiobookshelf_import_root().expanduser().resolve()
    resolved = target_path.resolve()
    if resolved != import_root and import_root not in resolved.parents:
        raise RuntimeError("audiobook_access_file_outside_import_root")
    expected_sha = str(token_payload.get("m4b_sha256") or "").strip()
    if expected_sha and _sha256_file(resolved) != expected_sha:
        raise RuntimeError("audiobook_access_file_hash_mismatch")
    return resolved, {
        "contract_name": PLAYER_AUDIOBOOK_ACCESS_CONTRACT_NAME,
        "status": "ready",
        "mode": "ea_scoped_audiobookshelf_reference",
        "job_id": job_id,
        "player_id": str(token_payload.get("player_id") or "").strip(),
        "runner_id": str(token_payload.get("runner_id") or "").strip(),
        "title": str(token_payload.get("title") or resolved.stem).strip(),
        "author": str(token_payload.get("author") or "").strip(),
        "library_scope": "single_player_runner_audiobook",
        "expires_at": str(token_payload.get("expires_at") or "").strip(),
        "filename": resolved.name,
        "content_type": "audio/mp4",
        "vendor_token_exposed": False,
        "raw_library_path_exposed": False,
    }


def create_player_scoped_audiobook_reference(
    *,
    job: dict[str, object],
    player_id: str = "",
    runner_id: str = "",
    expires_days: int | None = None,
) -> dict[str, object]:
    import_result = dict(job.get("audiobookshelf_import") or {})
    metadata = dict(job.get("metadata") or {})
    target_path = Path(str(import_result.get("target_path") or ""))
    gate_reason = _audiobook_publication_gate_reason(job)
    if gate_reason:
        return {
            "contract_name": PLAYER_AUDIOBOOK_ACCESS_CONTRACT_NAME,
            "status": "blocked",
            "reason": gate_reason,
        }
    if str(import_result.get("status") or "") != "imported" or not target_path.is_file():
        return {
            "contract_name": PLAYER_AUDIOBOOK_ACCESS_CONTRACT_NAME,
            "status": "blocked",
            "reason": "audiobookshelf_import_not_ready",
        }

    effective_player_id = str(player_id or job.get("principal_id") or "").strip()
    effective_runner_id = str(runner_id or dict(job.get("source") or {}).get("runner_id") or "").strip()
    days = expires_days if expires_days is not None else _env_int("EA_AUDIOBOOK_ACCESS_EXPIRES_DAYS", 30, minimum=1, maximum=365)
    issued_at = _now_iso()
    expires_at = (datetime.now(UTC) + timedelta(days=days)).isoformat().replace("+00:00", "Z")
    token_payload = {
        "contract_name": PLAYER_AUDIOBOOK_ACCESS_CONTRACT_NAME,
        "job_id": str(job.get("job_id") or "").strip(),
        "principal_id": str(job.get("principal_id") or "").strip(),
        "player_id": effective_player_id,
        "runner_id": effective_runner_id,
        "title": str(metadata.get("title") or target_path.stem).strip(),
        "author": str(metadata.get("author") or "").strip(),
        "m4b_sha256": _sha256_file(target_path),
        "audiobookshelf_import_path_sha256": _sha256_bytes(str(target_path).encode("utf-8")),
        "library_scope": "single_player_runner_audiobook",
        "audience": "chummer6_desktop",
        "issued_at": issued_at,
        "expires_at": expires_at,
    }
    token = _sign_player_access_payload(token_payload)
    relative_url = f"/internal/audiobooks/player/{token}" if token else ""
    base_url = str(os.getenv("EA_AUDIOBOOK_PLAYER_ACCESS_BASE_URL") or "").strip().rstrip("/")
    reference = {
        "contract_name": PLAYER_AUDIOBOOK_ACCESS_CONTRACT_NAME,
        "status": "signed_reference_ready" if token else "blocked",
        "reason": "" if token else "audiobook_access_signing_secret_missing",
        "mode": "ea_scoped_audiobookshelf_reference",
        "player_id": effective_player_id,
        "runner_id": effective_runner_id,
        "title": token_payload["title"],
        "author": token_payload["author"],
        "library_scope": token_payload["library_scope"],
        "expires_at": expires_at,
        "token_sha256": _sha256_bytes(token.encode("utf-8")) if token else "",
        "relative_url": relative_url,
        "absolute_url": f"{base_url}{relative_url}" if base_url and relative_url else "",
        "vendor_token_exposed": False,
        "raw_library_path_exposed": False,
    }
    job_dir = Path(str(dict(job.get("storage") or {}).get("job_dir") or ""))
    if job_dir:
        access_dir = job_dir / "player-access"
        access_dir.mkdir(parents=True, exist_ok=True)
        access_name = _safe_filename(effective_runner_id or effective_player_id or "player", fallback="player")
        (access_dir / f"{access_name}.json").write_text(
            json.dumps({**reference, "token_payload": token_payload}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return reference


def _build_job_payload(
    *,
    job_id: str,
    job_dir: Path,
    metadata: EpubMetadata,
    chapters: tuple[EpubChapter, ...],
    principal_id: str,
    source: dict[str, object],
    telegram: dict[str, object] | None = None,
    runner_id: str = "",
) -> dict[str, object]:
    total_chars = sum(chapter.char_count for chapter in chapters)
    eta = estimate_eta(
        total_chars=total_chars,
        chapter_count=len(chapters),
        has_external_tts=unmixr_auto_render_enabled(),
        has_m4b_assembly=_m4b_assembly_available(),
    )
    voice_selection = select_unmixr_voice_for_book(metadata=metadata, chapters=chapters, job_dir=job_dir)
    return {
        "contract_name": CONTRACT_NAME,
        "job_id": job_id,
        "status": "chapters_extracted",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "principal_id": str(principal_id or "").strip(),
        "source": {
            "kind": "epub",
            "runner_id": str(runner_id or "").strip(),
            **source,
        },
        "telegram": telegram or {},
        "storage": {
            "job_dir": str(job_dir),
            "source_epub": str(source.get("source_epub") or ""),
            "chapters_dir": str(job_dir / "chapters"),
            "audio_dir": str(job_dir / "audio"),
            "output_dir": str(job_dir / "output"),
        },
        "metadata": asdict(metadata),
        "chapters": [asdict(chapter) for chapter in chapters],
        "totals": {"chapter_count": len(chapters), "char_count": total_chars},
        "provider": {
            "preferred": "unmixr_ai",
            "external_tts_enabled": external_tts_enabled(),
            "unmixr_auto_render_enabled": unmixr_auto_render_enabled(),
            "raw_book_text_leaves_ea": unmixr_auto_render_enabled(),
            "voice_selection": dict(voice_selection.get("public") or {}),
        },
        "eta": eta,
        "next_action": "render_chapter_audio",
    }


def create_job_from_epub(
    *,
    epub_path: Path,
    original_filename: str,
    principal_id: str,
    chat_id: str = "",
    message_id: str = "",
    caption: str = "",
    source_url: str = "",
) -> dict[str, object]:
    root = audiobook_jobs_root()
    _require_audiobook_storage_root(root)
    source_is_kindle = _is_kindle_source_document(original_filename or epub_path.name)
    source_kind = Path(str(original_filename or epub_path.name)).suffix.lower().lstrip(".") if source_is_kindle else "epub"
    job_id = f"{source_kind}-audiobook-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    job_dir = root / job_id
    source_dir = job_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    source_suffix = Path(str(original_filename or epub_path.name)).suffix
    stored_source = source_dir / _safe_filename(
        original_filename,
        fallback="book",
        suffix=source_suffix if source_suffix else ".epub",
    )
    if epub_path.resolve() != stored_source.resolve():
        shutil.copy2(epub_path, stored_source)
    original_source_sha256 = _sha256_file(stored_source)
    extraction_epub = stored_source
    conversion: dict[str, object] = {"status": "not_required"}
    if source_is_kindle:
        extraction_epub = source_dir / f"{stored_source.stem}.converted.epub"
        conversion = _convert_kindle_source_to_epub(source_path=stored_source, output_path=extraction_epub)
        if str(conversion.get("status") or "") != "converted":
            raise RuntimeError(str(conversion.get("reason") or "kindle_to_epub_conversion_failed"))
    metadata, chapters = extract_epub_chapters(
        epub_path=extraction_epub,
        chapter_dir=job_dir / "chapters",
        source_filename=original_filename,
    )
    if source_is_kindle and metadata.source_sha256 != original_source_sha256:
        metadata = EpubMetadata(
            title=metadata.title,
            author=metadata.author,
            language=metadata.language,
            source_filename=metadata.source_filename,
            source_sha256=original_source_sha256,
            cover_image_path=metadata.cover_image_path,
            cover_media_type=metadata.cover_media_type,
        )
    payload = _build_job_payload(
        job_id=job_id,
        job_dir=job_dir,
        metadata=metadata,
        chapters=chapters,
        principal_id=principal_id,
        source={
            "kind": source_kind,
            "source_filename": original_filename,
            "source_sha256": metadata.source_sha256,
            "source_epub": str(extraction_epub),
            "source_original": str(stored_source),
            "source_kindle": str(stored_source) if source_is_kindle else "",
            "kindle_conversion": conversion,
            "rights_basis": "operator_supplied_kindle_file" if source_is_kindle else "operator_supplied_epub",
        },
        telegram={
            "chat_id": str(chat_id or "").strip(),
            "message_id": str(message_id or "").strip(),
            "caption": str(caption or "").strip(),
            "source_url_sha256": _sha256_bytes(str(source_url or "").encode("utf-8")) if source_url else "",
        },
    )
    _write_job(job_dir, payload)
    if audiobook_voice_audition_enabled() and external_tts_enabled():
        audition_job = prepare_audiobook_voice_audition(job_dir=job_dir)
        if str(audition_job.get("status") or "") in {
            "waiting_voice_selection",
            "blocked_voice_catalog",
            "voice_selection_exhausted",
            "blocked_external_tts",
        }:
            return audition_job
    return continue_job(job_dir)


def _normalize_text_chapter_rows(chapters: tuple[object, ...] | list[object]) -> tuple[dict[str, str], ...]:
    rows: list[dict[str, str]] = []
    for index, item in enumerate(chapters, start=1):
        if isinstance(item, str):
            title = f"Chapter {index}"
            text = item
        elif isinstance(item, dict):
            title = str(item.get("title") or item.get("name") or f"Chapter {index}").strip()
            text = str(item.get("text") or item.get("content") or "").strip()
        else:
            continue
        if text:
            rows.append({"title": title or f"Chapter {index}", "text": text})
    return tuple(rows)


def create_job_from_text_chapters(
    *,
    title: str,
    chapters: tuple[object, ...] | list[object],
    principal_id: str,
    author: str = "",
    language: str = "en-US",
    source_kind: str = "text_chapters",
    source_ref: str = "",
    rights_basis: str = "operator_approved_text",
    player_id: str = "",
    runner_id: str = "",
    caption: str = "",
    cover_image_path: Path | str | None = None,
) -> dict[str, object]:
    root = audiobook_jobs_root()
    _require_audiobook_storage_root(root)
    rows = _normalize_text_chapter_rows(chapters)
    if not rows:
        raise RuntimeError("audiobook_text_chapters_missing")
    safe_kind = _normalize_tag(source_kind) or "text"
    job_id = f"{safe_kind}-audiobook-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    job_dir = root / job_id
    chapter_dir = job_dir / "chapters"
    chapter_dir.mkdir(parents=True, exist_ok=True)
    joined_text = "\n\n".join(row["text"] for row in rows)
    text_sha = _sha256_bytes(joined_text.encode("utf-8"))
    source_filename = _safe_filename(title, fallback=safe_kind, suffix=".txt")
    source_dir = job_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / source_filename).write_text(joined_text + "\n", encoding="utf-8")
    copied_cover_path = ""
    copied_cover_media_type = ""
    if cover_image_path:
        source_cover = Path(str(cover_image_path)).expanduser()
        if source_cover.is_file():
            assets_dir = job_dir / "assets"
            assets_dir.mkdir(parents=True, exist_ok=True)
            suffix = source_cover.suffix.lower()
            copied_name = "cover.jpg" if suffix in {"", ".jpg", ".jpeg"} else f"cover{suffix}"
            copied_cover = assets_dir / copied_name
            if source_cover.resolve() != copied_cover.resolve():
                shutil.copy2(source_cover, copied_cover)
            copied_cover_path = str(copied_cover)
            copied_cover_media_type = "image/png" if suffix == ".png" else "image/jpeg"
    chapter_models: list[EpubChapter] = []
    for index, row in enumerate(rows, start=1):
        safe_title = _safe_filename(row["title"], fallback=f"Chapter {index:03d}")
        text_filename = f"{index:03d} - {safe_title}.txt"
        audio_filename = f"{index:03d} - {safe_title}.wav"
        (chapter_dir / text_filename).write_text(row["text"].strip() + "\n", encoding="utf-8")
        chapter_models.append(
            EpubChapter(
                index=index,
                title=row["title"],
                source_href=f"{safe_kind}:{source_ref or text_sha}:{index}",
                text_path=text_filename,
                audio_filename=audio_filename,
                char_count=len(row["text"]),
                sha256=_sha256_bytes(row["text"].encode("utf-8")),
            )
        )
    metadata = EpubMetadata(
        title=str(title or source_kind or "Audiobook").strip() or "Audiobook",
        author=str(author or "").strip(),
        language=str(language or "en-US").strip() or "en-US",
        source_filename=source_filename,
        source_sha256=text_sha,
        cover_image_path=copied_cover_path,
        cover_media_type=copied_cover_media_type,
    )
    payload = _build_job_payload(
        job_id=job_id,
        job_dir=job_dir,
        metadata=metadata,
        chapters=tuple(chapter_models),
        principal_id=principal_id,
        source={
            "kind": safe_kind,
            "source_ref": str(source_ref or "").strip(),
            "source_filename": source_filename,
            "source_sha256": text_sha,
            "source_text": str(source_dir / source_filename),
            "rights_basis": rights_basis,
            "player_id": str(player_id or "").strip(),
        },
        telegram={},
        runner_id=runner_id,
    )
    if caption:
        payload["operator_note"] = str(caption).strip()
    _write_job(job_dir, payload)
    return continue_job(job_dir)


def create_origin_dossier_audiobook_job(
    *,
    origin_story_text: str,
    runner_name: str,
    principal_id: str,
    dossier_id: str = "",
    player_id: str = "",
    runner_id: str = "",
    language: str = "en-US",
    chapter_title: str = "Origin Story",
    cover_image_path: Path | str | None = None,
) -> dict[str, object]:
    runner_label = str(runner_name or "Runner").strip() or "Runner"
    return create_job_from_text_chapters(
        title=f"{runner_label} - Origin Story",
        author="Chummer Origin Dossier",
        language=language,
        chapters=[{"title": chapter_title, "text": origin_story_text}],
        principal_id=principal_id,
        source_kind="origin_dossier_story",
        source_ref=dossier_id,
        rights_basis="player_or_gm_approved_origin_story",
        player_id=player_id,
        runner_id=runner_id or dossier_id,
        cover_image_path=cover_image_path,
    )


def continue_job(job_dir: Path) -> dict[str, object]:
    payload = _load_job(job_dir)
    metadata = _metadata_from_job(payload)
    metadata = _ensure_epub_cover_asset(job_dir, payload, metadata)
    chapters = _chapters_from_job(payload)
    previous_import = dict(payload.get("audiobookshelf_import") or {})
    voice_selection = dict(dict(payload.get("provider") or {}).get("voice_selection") or {})
    if str(voice_selection.get("status") or "") == "waiting_user_choice":
        recovered_voice_selection = selected_unmixr_voice_for_job(job_dir)
        if str(recovered_voice_selection.get("status") or "") == "selected":
            previous_candidate_key = str(voice_selection.get("selected_candidate_key") or "").strip()
            selected_public = dict(recovered_voice_selection.get("public") or {})
            selected_candidate_key = str(
                selected_public.get("selected_candidate_key")
                or selected_public.get("preset_key")
                or recovered_voice_selection.get("selected_candidate_key")
                or ""
            ).strip()
            render_reset = {}
            if _audiobook_publication_artifacts_require_voice_reset(payload):
                render_reset = _reset_audiobook_render_outputs_for_new_voice(job_dir)
            provider_payload = dict(payload.get("provider") or {})
            provider_payload["voice_selection"] = selected_public
            provider_payload["raw_book_text_leaves_ea"] = unmixr_auto_render_enabled()
            payload["provider"] = provider_payload
            payload["status"] = "voice_selected"
            payload["next_action"] = "render_chapter_audio"
            if render_reset:
                payload["render_result"] = {
                    "status": "reset_for_recovered_voice",
                    "previous_candidate_key_sha256": _sha256_bytes(previous_candidate_key.encode("utf-8"))
                    if previous_candidate_key
                    else "",
                    "selected_candidate_key_sha256": _sha256_bytes(selected_candidate_key.encode("utf-8"))
                    if selected_candidate_key
                    else "",
                }
                payload["merge_result"] = {"status": "waiting_for_chapter_audio"}
                payload["audiobookshelf_import"] = {
                    "status": "waiting_for_m4b",
                    "player_scoped_reference": _blocked_player_scoped_reference(reason="waiting_for_recovered_voice_render"),
                    "public_share": _blocked_audiobookshelf_public_share(reason="waiting_for_recovered_voice_render"),
                }
                payload["audio_publication_gate"] = {
                    "contract_name": "ea.audiobook_publication_audio_gate.v1",
                    "checked_at": _now_iso(),
                    "status": "pending",
                    "issues": ["waiting_for_recovered_voice_render"],
                    "raw_paths_exposed": False,
                }
            payload["updated_at"] = _now_iso()
            _write_job(job_dir, payload)
        else:
            payload["status"] = "waiting_voice_selection"
            payload["next_action"] = "choose_audiobook_voice"
            if str(dict(payload.get("merge_result") or {}).get("status") or "").strip() == "m4b_ready":
                payload["merge_result"] = {
                    "status": "waiting_for_voice_selection",
                    "reason": "stale_wrong_voice_m4b_blocked",
                }
            import_payload = dict(payload.get("audiobookshelf_import") or {})
            public_share = dict(import_payload.get("public_share") or {})
            if (
                str(import_payload.get("status") or "").strip() == "imported"
                or str(public_share.get("status") or "").strip() == "revoked_wrong_voice"
            ):
                public_share.pop("absolute_url", None)
                public_share.pop("share_url", None)
                import_payload.update(
                    {
                        "status": "waiting_for_voice_selection",
                        "reason": "stale_wrong_voice_publication_revoked",
                        "player_scoped_reference": _blocked_player_scoped_reference(reason="waiting_voice_selection"),
                        "public_share": {
                            **public_share,
                            "status": "revoked_wrong_voice",
                            "reason": "selected_voice_required_before_publication",
                            "raw_urls_exposed": False,
                        },
                    }
                )
                payload["audiobookshelf_import"] = import_payload
                payload["audio_publication_gate"] = {
                    "contract_name": "ea.audiobook_publication_audio_gate.v1",
                    "status": "blocked",
                    "issues": ["waiting_voice_selection", "stale_wrong_voice_m4b_blocked"],
                    "raw_paths_exposed": False,
                }
            payload["updated_at"] = _now_iso()
            _write_job(job_dir, payload)
            _write_current_job_receipt_best_effort(job_dir)
            return payload
    if str(payload.get("status") or "") in {"blocked_voice_catalog", "voice_selection_exhausted"}:
        _write_current_job_receipt_best_effort(job_dir)
        return payload
    render_result = render_unmixr_chapter_audio(job_dir=job_dir, chapters=chapters, metadata=metadata)
    provider_payload = dict(payload.get("provider") or {})
    if isinstance(render_result.get("voice_selection"), dict):
        provider_payload["voice_selection"] = dict(render_result.get("voice_selection") or {})
        payload["provider"] = provider_payload
    cinematic_master_audio = render_result.get("cinematic_master_audio")
    if isinstance(cinematic_master_audio, str) and cinematic_master_audio:
        provider_payload["cinematic_master_audio"] = cinematic_master_audio
        payload["provider"] = provider_payload
    if (
        str(render_result.get("status") or "").strip() == "blocked"
        and str(render_result.get("reason") or "").strip() == "selected_voice_language_mismatch"
    ):
        payload.update(
            {
                "status": "blocked_external_tts",
                "updated_at": _now_iso(),
                "render_result": render_result,
                "next_action": "selected_voice_language_mismatch",
            }
        )
        _write_job(job_dir, payload)
        reopened_job = reopen_audiobook_voice_selection_for_language_mismatch(job_dir=job_dir)
        if str(reopened_job.get("status") or "").strip() == "waiting_voice_selection":
            return reopened_job
        payload = reopened_job
    if (
        str(render_result.get("status") or "").strip() == "blocked"
        and bool(render_result.get("replacement_voice_required"))
        and _provider_balance_blocker(render_result.get("reason"))
    ):
        next_action = "restore_selected_voice_provider_balance"
        payload.update(
            {
                "status": "blocked_external_tts",
                "updated_at": _now_iso(),
                "render_result": render_result,
                "next_action": next_action,
            }
        )
        _write_job(job_dir, payload)
    payload = _clear_resolved_selected_voice_provider_blocker(payload, render_result=render_result)
    cinematic_track_path = None
    if isinstance(provider_payload.get("cinematic_master_audio"), str):
        cinematic_track_path = Path(str(provider_payload.get("cinematic_master_audio"))).resolve()
    merge_result = _merge_m4b_if_ready(
        job_dir=job_dir,
        metadata=metadata,
        chapters=chapters,
        cinematic_track_path=cinematic_track_path,
    )
    import_result: dict[str, object] = {"status": "waiting_for_m4b"}
    m4b_path = Path(str(merge_result.get("output_file") or ""))
    if str(merge_result.get("status") or "") == "m4b_ready" and m4b_path.is_file():
        import_result = _import_to_audiobookshelf_if_ready(m4b_path=m4b_path, metadata=metadata)
        if str(import_result.get("status") or "") == "imported":
            target_path = Path(str(import_result.get("target_path") or ""))
            gate_job = {**payload, "status": "audiobookshelf_imported", "audiobookshelf_import": import_result}
            publication_gate = _build_audiobook_publication_gate(job=gate_job, target_path=target_path)
            payload["audio_publication_gate"] = publication_gate
            access_reference = create_player_scoped_audiobook_reference(
                job={**payload, "status": "audiobookshelf_imported", "audiobookshelf_import": import_result},
                player_id=str(dict(payload.get("source") or {}).get("player_id") or payload.get("principal_id") or "").strip(),
                runner_id=str(dict(payload.get("source") or {}).get("runner_id") or "").strip(),
            )
            import_result["player_scoped_reference"] = access_reference
            if str(publication_gate.get("status") or "") == "pass":
                public_share = _create_or_reuse_audiobookshelf_public_share(
                    job={**payload, "status": "audiobookshelf_imported", "audiobookshelf_import": import_result},
                    import_result=import_result,
                    metadata=metadata,
                )
                import_result["public_share"] = public_share
            else:
                import_result["public_share"] = {
                    "status": "blocked_audio_publication_gate",
                    "reason": ",".join(str(issue) for issue in publication_gate.get("issues") or []),
                    "token_exposed": False,
                    "raw_library_path_exposed": False,
                }
            import_result = _preserve_ready_audiobookshelf_access(
                import_result=import_result,
                previous_import=previous_import,
            )
    if str(import_result.get("status") or "") == "imported":
        status = "audiobookshelf_imported"
        public_share_status = str(dict(import_result.get("public_share") or {}).get("status") or "").strip()
        if public_share_status == "waiting_for_audiobookshelf_scan":
            next_action = "wait_for_audiobookshelf_scan_then_send_public_share"
        elif public_share_status == "public_share_ready":
            next_action = "telegram_reply_includes_audiobookshelf_public_share"
        else:
            next_action = "scan_audiobookshelf_library"
    elif str(render_result.get("status") or "") in {"provider_throttled", "provider_pacing_wait"}:
        status = "waiting_provider_throttle"
        next_action = (
            "resume_after_unmixr_pacing"
            if str(render_result.get("status") or "") == "provider_pacing_wait"
            else "resume_after_unmixr_throttle"
        )
    elif str(render_result.get("status") or "") == "blocked":
        status = "blocked_external_tts"
        if bool(render_result.get("replacement_voice_required")) and _provider_balance_blocker(render_result.get("reason")):
            next_action = "restore_selected_voice_provider_balance"
        else:
            next_action = str(render_result.get("reason") or "enable_external_tts")
    elif str(merge_result.get("status") or "").startswith("waiting_for_m4b_assembly_tool"):
        status = "blocked_m4b_assembly_missing"
        next_action = "install_m4b_tool_or_enable_ffmpeg_fallback"
    elif str(merge_result.get("status") or "").startswith("waiting_for_unmixr"):
        status = "waiting_for_chapter_audio"
        next_action = "export_or_render_unmixr_chapter_audio"
    elif str(merge_result.get("status") or "") == "m4b_merge_failed":
        status = "failed_m4b_merge"
        next_action = "inspect_m4b_tool_error"
    else:
        status = str(merge_result.get("status") or render_result.get("status") or payload.get("status") or "processing")
        next_action = "continue_audiobook_job"
    payload.update(
        {
            "status": status,
            "updated_at": _now_iso(),
            "render_result": render_result,
            "merge_result": merge_result,
            "audiobookshelf_import": import_result,
            "next_action": next_action,
        }
    )
    if status == "audiobookshelf_imported":
        record_audiobook_completed_voice_feedback(payload)
    _write_job(job_dir, payload)
    _write_current_job_receipt_best_effort(job_dir)
    if status == "audiobookshelf_imported" and audiobook_job_cleanup_enabled():
        payload["cleanup"] = cleanup_audiobook_job_artifacts(job_dir)
    return payload


def process_telegram_epub_audiobook_job(
    *,
    download_url: str,
    filename: str,
    principal_id: str,
    file_size: int | None = None,
    chat_id: str = "",
    message_id: str = "",
    caption: str = "",
) -> dict[str, object]:
    if file_size is not None:
        if file_size <= 0:
            raise RuntimeError("telegram_epub_file_size_invalid")
        if file_size > _declared_epub_byte_limit():
            raise RuntimeError("telegram_epub_too_large_declared")
    root = audiobook_jobs_root()
    _require_audiobook_storage_root(root)
    staging_dir = root / "_incoming" / datetime.now(UTC).strftime("%Y%m%d")
    staging_dir.mkdir(parents=True, exist_ok=True)
    filename_suffix = Path(str(filename or "")).suffix
    safe_source = _safe_filename(filename, fallback="telegram-book", suffix=filename_suffix if filename_suffix else ".epub")
    staging_path = staging_dir / f"{uuid.uuid4().hex[:12]}-{safe_source}"
    download_telegram_epub(source_url=download_url, target_path=staging_path)
    try:
        return create_job_from_epub(
            epub_path=staging_path,
            original_filename=filename,
            principal_id=principal_id,
            chat_id=chat_id,
            message_id=message_id,
            caption=caption,
            source_url=download_url,
        )
    finally:
        with contextlib_suppress_unlink(staging_path):
            pass


def telegram_epub_reply_text(job: dict[str, object]) -> str:
    status = str(job.get("status") or "").strip()
    metadata = dict(job.get("metadata") or {})
    totals = dict(job.get("totals") or {})
    eta = dict(job.get("eta") or {})
    title = str(metadata.get("title") or metadata.get("source_filename") or "the source ebook").strip()
    chapter_count = int(totals.get("chapter_count") or 0)
    char_count = int(totals.get("char_count") or 0)
    minutes = int(eta.get("estimated_minutes_after_unblocked") or 0)
    voice_selection = dict(dict(job.get("provider") or {}).get("voice_selection") or {})
    selected_voice = dict(voice_selection.get("selected") or {})
    voice_line = (
        f" Selected voice: {selected_voice.get('label')}."
        if selected_voice.get("label")
        else ""
    )
    last_action = dict(voice_selection.get("last_action") or {})
    if str(last_action.get("status") or "").strip() == "stale_candidate_ignored":
        pending = list(voice_selection.get("pending_batch") or [])
        labels = [
            str(dict(row).get("label") or "").strip()
            for row in pending
            if isinstance(row, dict) and str(dict(row).get("label") or "").strip()
        ]
        if labels:
            label_line = f" Current valid sample: {labels[0]}."
        elif selected_voice.get("label"):
            label_line = f" Current selected voice: {selected_voice.get('label')}."
        else:
            label_line = ""
        return (
            "That audiobook voice button is stale, so I ignored it."
            f"{label_line} Use the latest voice sample buttons, or reply with the voice name or 'dismiss all'."
        )
    if status == "waiting_voice_selection":
        if str(voice_selection.get("reason") or "").strip() == "selected_voice_provider_balance_blocked":
            pending = list(voice_selection.get("pending_batch") or [])
            delivery = dict(dict(job.get("telegram") or {}).get("voice_sample_delivery") or {})
            sent_count = int(delivery.get("sent_count") or 0)
            sample_line = (
                f"I sent {sent_count} replacement voice sample."
                if sent_count
                else f"I prepared {len(pending)} replacement voice sample and am sending it in Telegram."
            )
            return (
                f"The selected voice for {title} is blocked by provider credits/balance. "
                "I stopped before publishing the book with a different voice. "
                f"{sample_line} Use it only if you want that replacement voice; otherwise restore the provider and I will render the selected voice.{voice_line}"
            )
        profile = dict(voice_selection.get("book_profile") or {})
        topic = str(profile.get("topic") or "").strip()
        language = str(profile.get("language") or "").strip()
        pending = list(voice_selection.get("pending_batch") or [])
        if str(last_action.get("status") or "").strip() == "replacement_failed":
            pending_count = len(pending)
            failed_count = int(last_action.get("sample_generation_failed_count") or voice_selection.get("sample_generation_failed_count") or 0)
            if pending_count:
                sample_word = "sample" if pending_count == 1 else "samples"
                return (
                    f"Dismissed that voice for {title}. "
                    f"I could not prepare a replacement sample from the provider right now"
                    f"{f' ({failed_count} failed)' if failed_count else ''}. "
                    f"{pending_count} voice {sample_word} remain available."
                )
            return (
                f"Dismissed that voice for {title}. "
                "I could not prepare more replacement samples from the provider right now. "
                "I will need a working voice provider response or more configured voices before this book can continue."
            )
        if str(last_action.get("status") or "").strip() == "stale_candidate_ignored":
            labels = [
                str(dict(row).get("label") or "").strip()
                for row in pending
                if isinstance(row, dict) and str(dict(row).get("label") or "").strip()
            ]
            label_line = f" Current valid sample: {labels[0]}." if labels else ""
            return (
                "That audiobook voice button is stale, so I ignored it."
                f"{label_line} Use the latest voice sample buttons, or reply with the voice name or 'dismiss all'."
            )
        delivery = dict(dict(job.get("telegram") or {}).get("voice_sample_delivery") or {})
        delivery_status = str(delivery.get("status") or "").strip()
        expected_count = int(delivery.get("expected_count") or len(pending))
        sent_count = int(delivery.get("sent_count") or 0)
        reason = str(delivery.get("reason") or "").strip()
        underfilled = bool(voice_selection.get("underfilled"))
        underfilled_reason = str(voice_selection.get("underfilled_reason") or voice_selection.get("reason") or "").strip()
        if underfilled:
            pending_count = len(pending)
            sample_generation_failed_count = int(voice_selection.get("sample_generation_failed_count") or 0)
            sample_word = "sample" if pending_count == 1 else "samples"
            verb = "remains" if pending_count == 1 else "remain"
            if pending_count <= 0 and sample_generation_failed_count > 0:
                sample_line = (
                    "I found matching voices, but the provider could not generate sample audio for them yet. "
                    "I did not send voice samples."
                )
            elif underfilled_reason == "voice_catalog_underfilled_after_dismissals":
                sample_line = (
                    f"{pending_count} language-matched voice {sample_word} {verb} after your dismissals; "
                    "the provider catalog has no more fitting voices for this book."
                )
            else:
                sample_line = (
                    f"I found {pending_count} language-matched voice {sample_word}; "
                    "the provider catalog has fewer fitting voices than requested."
                )
        elif delivery_status == "sent":
            sample_line = f"I sent {sent_count or len(pending)} short voice samples."
        elif delivery_status == "partial":
            sample_line = f"I prepared {expected_count or len(pending)} short voice samples, but Telegram only delivered {sent_count}."
        elif delivery_status == "failed":
            sample_line = (
                f"I prepared {expected_count or len(pending)} short voice samples, but Telegram could not deliver them"
                f"{f': {reason}' if reason else ''}."
            )
        else:
            sample_line = f"I prepared {len(pending)} short voice samples and am sending them in Telegram."
        return (
            f"I accepted the source ebook and extracted {chapter_count} chapters for {title}. "
            f"I detected language {language or 'unknown'}"
            f"{f' and topic {topic}' if topic else ''}. "
            f"{sample_line} Choose 'Use this' under the one that fits; dismiss any sample to replace it."
        )
    if status == "blocked_voice_catalog":
        profile = dict(voice_selection.get("book_profile") or {})
        topic = str(profile.get("topic") or "").strip()
        language = str(profile.get("language") or "").strip()
        candidate_count = int(voice_selection.get("candidate_count") or 0)
        required_count = int(voice_selection.get("required_candidate_count") or audiobook_voice_audition_min_candidates())
        target_count = int(voice_selection.get("target_catalog_count") or audiobook_voice_discovery_target_count())
        return (
            f"I accepted the source ebook and extracted {chapter_count} chapters for {title}. "
            f"I detected language {language or 'unknown'}"
            f"{f' and topic {topic}' if topic else ''}. "
            f"I need at least {required_count} available voices to send comparison samples, but the catalog currently has {candidate_count}. "
            f"Generic discovery target is {target_count} voices; enable voice discovery or add more presets."
        )
    if status == "audiobookshelf_imported":
        imported = dict(job.get("audiobookshelf_import") or {})
        public_share = dict(imported.get("public_share") or {})
        public_share_url = str(public_share.get("absolute_url") or "").strip()
        public_share_line = (
            f" Audiobookshelf public share link: {public_share_url}."
            if str(public_share.get("status") or "") == "public_share_ready" and public_share_url
            else ""
        )
        reference = dict(imported.get("player_scoped_reference") or {})
        if reference.get("status") == "signed_reference_ready":
            reference_url = str(reference.get("absolute_url") or "").strip()
            if reference_url:
                access_line = f" Player-scoped playback link: {reference_url}."
            else:
                access_line = " Player-scoped playback link is ready; configure EA_AUDIOBOOK_PLAYER_ACCESS_BASE_URL to open it."
        else:
            access_line = ""
        share_wait_line = ""
        if not public_share_line and str(public_share.get("status") or "") == "waiting_for_audiobookshelf_scan":
            share_wait_line = " Audiobookshelf scan is still catching up; I will keep the EA-scoped link available meanwhile."
        return f"Done. I made the audiobook for {title} and imported it into Audiobookshelf storage.{public_share_line}{access_line}{share_wait_line}"
    if status == "blocked_m4b_assembly_missing":
        return (
            f"I prepared {title} for audiobook production: {chapter_count} chapters, about {char_count:,} characters. "
            "Current blocker: no M4B assembly tool is available. Install m4b-tool or enable the ffmpeg fallback. "
            f"ETA after that and chapter audio are present: about {minutes} minutes.{voice_line}"
        )
    if status == "waiting_for_chapter_audio":
        return (
            f"I prepared {title} for audiobook production: {chapter_count} chapters, about {char_count:,} characters. "
            "Current blocker: chapter audio is not present yet. Export the generated chapter WAVs into the job audio folder or enable governed audio generation. "
            f"ETA after audio rendering is unblocked: about {minutes} minutes.{voice_line}"
        )
    if status == "waiting_provider_throttle":
        render_result = dict(job.get("render_result") or {})
        render_status = str(render_result.get("status") or "").strip()
        wait_seconds = int(render_result.get("provider_wait_seconds") or 0)
        retry_after = str(render_result.get("provider_retry_after") or "").strip()
        hours = wait_seconds / 3600.0 if wait_seconds else 0.0
        if render_status == "provider_pacing_wait":
            wait_line = (
                f"I paused bulk audio generation for about {hours:.1f} hours before hitting the provider throttle"
                if wait_seconds
                else "I paused bulk audio generation before hitting the provider throttle"
            )
        else:
            wait_line = (
                f"The audio generation lane is throttled for about {hours:.1f} hours"
                if wait_seconds
                else "The audio generation lane is throttled"
            )
        if retry_after:
            wait_line = f"{wait_line}; retry after {retry_after}"
        return (
            f"I accepted the source ebook and extracted {chapter_count} real audiobook chapters for {title}. "
            f"{wait_line}. The partial chapter audio is saved in the pCloud job folder and I can resume from there. "
            f"ETA after the provider window reopens: about {minutes} minutes.{voice_line}"
        )
    if status == "blocked_external_tts":
        reason = str(dict(job.get("render_result") or {}).get("reason") or "").strip()
        if reason and reason != "external_tts_disabled_or_auto_render_off":
            blocker_code = _external_tts_blocker_code(reason)
            if blocker_code:
                if blocker_code == "selected_voice_language_mismatch":
                    return (
                        f"I accepted the source ebook and extracted {chapter_count} chapters for {title}. "
                        "The selected voice does not match the book language, so I stopped before finishing it with the wrong voice. "
                        f"Choose another voice and I can continue from there.{voice_line}"
                    )
                retry_at = _audiobook_job_external_tts_retry_at(job)
                retry_line = (
                    f" I will retry after {retry_at.isoformat().replace('+00:00', 'Z')}."
                    if retry_at is not None and _external_tts_blocker_is_retryable(reason)
                    else ""
                )
                if blocker_code == "provider_balance_or_prebuilt_characters":
                    blocker_line = (
                        "The selected audiobook voice is blocked by provider credits/balance. "
                        "I stopped instead of publishing the book with a different voice."
                    )
                elif blocker_code == "provider_quota":
                    blocker_line = "The selected audiobook voice is temporarily blocked by provider quota."
                elif blocker_code in {"provider_rate_limit", "provider_timeout", "provider_temporary_failure"}:
                    blocker_line = "The selected audiobook voice is temporarily blocked by the provider."
                else:
                    blocker_line = "The selected audiobook voice is temporarily blocked by the external TTS provider."
                return (
                    f"I accepted the source ebook and extracted {chapter_count} chapters for {title}. "
                    f"{blocker_line}{retry_line} "
                    f"ETA after that clears: about {minutes} minutes.{voice_line}"
                )
            return (
                f"I accepted the source ebook and extracted {chapter_count} chapters for {title}. "
                f"Current audiobook TTS blocker: {reason[:220]}. "
                f"ETA after that clears: about {minutes} minutes.{voice_line}"
            )
        return (
            f"I accepted the source ebook and extracted {chapter_count} chapters for {title}. "
            "I did not send the book text to audio generation because external audiobook TTS is disabled. "
            f"ETA after operator approval: about {minutes} minutes, then I can merge and import it to Audiobookshelf.{voice_line}"
        )
    return (
        f"I accepted the source ebook and created an audiobook job for {title}: {chapter_count} chapters, about {char_count:,} characters. "
        f"Current status: {status or 'processing'}. ETA after any blocker clears: about {minutes} minutes.{voice_line}"
    )


def _audiobook_job_throttle_retry_at(job: dict[str, object]) -> datetime | None:
    if str(job.get("status") or "").strip() != "waiting_provider_throttle":
        return None
    render_result = dict(job.get("render_result") or {})
    if str(render_result.get("status") or "").strip() not in {"provider_throttled", "provider_pacing_wait"}:
        return None
    return _parse_iso_datetime(render_result.get("provider_retry_after"))


def _external_tts_blocker_retry_seconds() -> int:
    return _env_int("EA_AUDIOBOOK_EXTERNAL_TTS_BLOCKER_RETRY_SECONDS", 21600, minimum=60, maximum=604800)


def _external_tts_blocker_cooldown_seconds(reason: object) -> int:
    normalized = str(reason or "").strip().lower()
    if not normalized:
        return 0
    match = re.search(r"(?:slot|slots)[_\s-]+cooling[_\s-]+down[:=\s]+(\d+)", normalized)
    if not match:
        match = re.search(r"cooling[_\s-]+down[:=\s]+(\d+)", normalized)
    if not match:
        return 0
    try:
        seconds = int(match.group(1))
    except Exception:
        return 0
    return max(0, min(seconds, 604800))


def _external_tts_blocker_is_retryable(reason: object) -> bool:
    normalized = str(reason or "").strip().lower()
    if not normalized:
        return False
    if "external_tts_disabled_or_auto_render_off" in normalized:
        return False
    if "selected_voice_language_mismatch" in normalized:
        return False
    if _external_tts_blocker_cooldown_seconds(normalized) > 0:
        return True
    retryable_markers = (
        "insufficient api balance",
        "insufficient balance",
        "prebuilt character",
        "quota",
        "credit",
        "billing",
        "payment",
        "rate limit",
        "temporar",
        "timeout",
        "502",
        "503",
        "504",
    )
    return any(marker in normalized for marker in retryable_markers)


def _external_tts_blocker_code(reason: object) -> str:
    normalized = str(reason or "").strip().lower()
    if not normalized:
        return ""
    if "external_tts_disabled_or_auto_render_off" in normalized:
        return "external_tts_disabled"
    if "selected_voice_language_mismatch" in normalized:
        return "selected_voice_language_mismatch"
    if "insufficient api balance" in normalized or "insufficient balance" in normalized or "prebuilt character" in normalized:
        return "provider_balance_or_prebuilt_characters"
    if "quota" in normalized:
        return "provider_quota"
    if "credit" in normalized or "billing" in normalized or "payment" in normalized:
        return "provider_billing"
    if "rate limit" in normalized:
        return "provider_rate_limit"
    if "timeout" in normalized:
        return "provider_timeout"
    if _external_tts_blocker_cooldown_seconds(normalized) > 0:
        return "provider_cooling_down"
    if any(marker in normalized for marker in ("502", "503", "504", "temporar")):
        return "provider_temporary_failure"
    return "provider_tts_blocked"


def _audiobook_job_external_tts_retry_at(job: dict[str, object]) -> datetime | None:
    if str(job.get("status") or "").strip() != "blocked_external_tts":
        return None
    render_result = dict(job.get("render_result") or {})
    if str(render_result.get("status") or "").strip() != "blocked":
        return None
    reason = str(render_result.get("reason") or job.get("next_action") or "").strip()
    if not _external_tts_blocker_is_retryable(reason):
        return None
    updated_at = _parse_iso_datetime(job.get("updated_at"))
    if updated_at is None:
        updated_at = datetime.fromtimestamp(0, tz=UTC)
    cooldown_seconds = _external_tts_blocker_cooldown_seconds(reason)
    if cooldown_seconds > 0:
        return updated_at + timedelta(seconds=cooldown_seconds)
    return updated_at + timedelta(seconds=_external_tts_blocker_retry_seconds())


def _audiobook_job_retry_at(job: dict[str, object]) -> datetime | None:
    return _audiobook_job_throttle_retry_at(job) or _audiobook_job_external_tts_retry_at(job)


def _audiobook_completed_terminal_reason(job: dict[str, object]) -> str:
    status = str(job.get("status") or "").strip()
    if status != "audiobookshelf_imported":
        return ""
    if _audiobook_public_share_followup_pending(job):
        return ""
    playback_acceptance = dict(job.get("playback_acceptance") or {})
    playback_status = str(playback_acceptance.get("status") or "").strip()
    if playback_status == "accepted":
        return "playback_accepted"
    return ""


def _audiobook_ignored_terminal_reason(job: dict[str, object]) -> str:
    status = str(job.get("status") or "").strip()
    if status == "superseded_duplicate":
        return status
    return ""


def _audiobook_operator_review_reason(job: dict[str, object]) -> str:
    status = str(job.get("status") or "").strip()
    if status != "audiobookshelf_imported":
        return ""
    if _audiobook_public_share_followup_pending(job):
        return ""
    playback_acceptance = dict(job.get("playback_acceptance") or {})
    playback_status = str(playback_acceptance.get("status") or "").strip()
    if playback_status == "rejected":
        source = str(playback_acceptance.get("source") or "").strip()
        if source == "whatsapp_button_recovered":
            public_share = _audiobook_public_share_for_job(job)
            playback_e2e = dict(public_share.get("playback_e2e") or {})
            if str(playback_e2e.get("status") or "").strip() == "pass":
                checked_at = _parse_iso_datetime(playback_e2e.get("checked_at"))
                recorded_at = _parse_iso_datetime(playback_acceptance.get("recorded_at"))
                if checked_at is not None and recorded_at is not None and checked_at >= recorded_at:
                    return ""
    if playback_status == "rejected" or str(job.get("next_action") or "").strip() == "review_audiobook_playback_problem":
        return "review_audiobook_playback_problem"
    return ""


def _audiobook_resume_skip_reason(job: dict[str, object]) -> str:
    completed_terminal_reason = _audiobook_completed_terminal_reason(job)
    if completed_terminal_reason:
        return completed_terminal_reason
    status = str(job.get("status") or "").strip()
    if status:
        return status
    if _audiobook_public_share_followup_pending(job):
        return "public_share_followup_pending"
    return "no_retry_due"


def _audiobook_resume_priority(job: dict[str, object]) -> int:
    source_kind = _normalize_tag(dict(job.get("source") or {}).get("kind"))
    if source_kind in _priority_audiobook_source_kinds():
        return 0
    return 10


def _audiobook_resume_priority_label(job: dict[str, object]) -> str:
    return "priority_small_narration" if _audiobook_resume_priority(job) == 0 else "bulk_or_standard"


def _audiobook_wait_kind(render_result: dict[str, object]) -> str:
    status = str(render_result.get("status") or "").strip()
    if status == "provider_pacing_wait":
        return "bulk_pacing"
    if status == "provider_throttled":
        return "provider_throttle"
    return ""


def _audiobook_resume_mark_path(job_dir: Path) -> Path:
    return job_dir / "resume_state.json"


def _recent_resume_attempt_active(job_dir: Path, *, now: datetime) -> bool:
    path = _audiobook_resume_mark_path(job_dir)
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    attempted_at = _parse_iso_datetime(payload.get("attempted_at"))
    if attempted_at is None:
        return False
    cooldown_seconds = _env_int("EA_AUDIOBOOK_RESUME_ATTEMPT_COOLDOWN_SECONDS", 900, minimum=0, maximum=86400)
    return (now - attempted_at).total_seconds() < cooldown_seconds


def _write_resume_attempt_mark(job_dir: Path, *, payload: dict[str, object]) -> None:
    path = _audiobook_resume_mark_path(job_dir)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _resume_due_job_with_external_tts_consent(job_dir: Path) -> dict[str, object]:
    job = _load_job(job_dir)
    provider = dict(job.get("provider") or {})
    voice_selection = dict(provider.get("voice_selection") or {})
    selected_voice = dict(voice_selection.get("selected") or {})
    selected_provider = str(selected_voice.get("provider") or "").strip()
    has_selected_unmixr_voice = (
        str(voice_selection.get("status") or "").strip() == "selected_by_user"
        and bool(str(voice_selection.get("selected_candidate_key") or "").strip())
        and selected_provider != "piper_local_fast"
    )
    allow_external = bool(provider.get("raw_book_text_leaves_ea")) and (
        str(provider.get("preferred") or "") == "unmixr_ai"
        or has_selected_unmixr_voice
    )
    previous_external = os.environ.get("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED")
    previous_unmixr = os.environ.get("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER")
    if allow_external:
        os.environ["EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED"] = "1"
        os.environ["EA_AUDIOBOOK_UNMIXR_AUTO_RENDER"] = "1"
    try:
        return continue_job(job_dir)
    finally:
        if previous_external is None:
            os.environ.pop("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED", None)
        else:
            os.environ["EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED"] = previous_external
        if previous_unmixr is None:
            os.environ.pop("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER", None)
        else:
            os.environ["EA_AUDIOBOOK_UNMIXR_AUTO_RENDER"] = previous_unmixr


def resume_due_audiobook_jobs(
    *,
    now: datetime | None = None,
    limit: int | None = None,
    notify_telegram: bool = True,
    force_public_share_followup: bool = False,
) -> dict[str, object]:
    observed_at = now or datetime.now(UTC)
    max_jobs = limit if limit is not None else _env_int("EA_AUDIOBOOK_RESUME_DUE_LIMIT", 2, minimum=1, maximum=20)
    roots = audiobook_job_discovery_roots()
    effective_job_root = audiobook_jobs_root()
    job_root_probe = _storage_path_probe(effective_job_root)
    if not bool(job_root_probe.get("accessible")):
        return {
            "ran": True,
            "attempted": 0,
            "resumed": 0,
            "pending": 0,
            "skipped": 0,
            "errors": 0,
            "share_link_attempted": 0,
            "share_links_ready": 0,
            "share_link_pending": 0,
            "share_link_notifications": [],
            "reason": "job_root_missing",
            "job_root": job_root_probe,
        }
    manifests = list(iter_audiobook_job_manifests())
    if not roots:
        return {
            "ran": True,
            "attempted": 0,
            "resumed": 0,
            "pending": 0,
            "skipped": 0,
            "errors": 0,
            "share_link_attempted": 0,
            "share_links_ready": 0,
            "share_link_pending": 0,
            "share_link_notifications": [],
            "reason": "job_root_missing",
            "job_root": job_root_probe,
        }
    rows: list[tuple[int, datetime, Path, dict[str, object]]] = []
    share_rows: list[tuple[int, Path, dict[str, object]]] = []
    pending = 0
    share_link_pending = 0
    skipped = 0
    skip_reasons: dict[str, int] = {}
    completed_terminal = 0
    completed_terminal_reasons: dict[str, int] = {}
    ignored_terminal = 0
    ignored_terminal_reasons: dict[str, int] = {}
    operator_review_pending = 0
    operator_review_reasons: dict[str, int] = {}
    errors = 0
    for manifest_path in manifests:
        try:
            job = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            errors += 1
            continue
        retry_at = _audiobook_job_retry_at(job)
        if retry_at is None:
            if _audiobook_public_share_followup_pending(job):
                job_dir = manifest_path.parent
                if not force_public_share_followup and _recent_public_share_attempt_active(job_dir, now=observed_at):
                    share_link_pending += 1
                else:
                    share_rows.append((_audiobook_resume_priority(job), job_dir, job))
            else:
                ignored_reason = _audiobook_ignored_terminal_reason(job)
                if ignored_reason:
                    ignored_terminal += 1
                    ignored_terminal_reasons[ignored_reason] = int(ignored_terminal_reasons.get(ignored_reason) or 0) + 1
                    continue
                review_reason = _audiobook_operator_review_reason(job)
                if review_reason:
                    operator_review_pending += 1
                    operator_review_reasons[review_reason] = int(operator_review_reasons.get(review_reason) or 0) + 1
                    continue
                reason = _audiobook_resume_skip_reason(job)
                if reason == "playback_accepted":
                    completed_terminal += 1
                    completed_terminal_reasons[reason] = int(completed_terminal_reasons.get(reason) or 0) + 1
                else:
                    skipped += 1
                    skip_reasons[reason] = int(skip_reasons.get(reason) or 0) + 1
            continue
        if retry_at > observed_at:
            pending += 1
            continue
        job_dir = manifest_path.parent
        if _recent_resume_attempt_active(job_dir, now=observed_at):
            pending += 1
            continue
        rows.append((_audiobook_resume_priority(job), retry_at, job_dir, job))
    rows.sort(key=lambda row: (row[0], row[1], row[2].name))
    share_rows.sort(key=lambda row: (row[0], row[1].name))
    attempted = 0
    resumed = 0
    imported = 0
    throttled = 0
    notifications: list[dict[str, object]] = []
    for _priority, _retry_at, job_dir, _job in rows[:max_jobs]:
        attempted += 1
        _write_resume_attempt_mark(
            job_dir,
            payload={"attempted_at": observed_at.isoformat().replace("+00:00", "Z"), "status": "started"},
        )
        try:
            resumed_job = _resume_due_job_with_external_tts_consent(job_dir)
            resumed += 1
            status = str(resumed_job.get("status") or "").strip()
            if status == "audiobookshelf_imported":
                imported += 1
            if status == "waiting_provider_throttle":
                throttled += 1
            notification = {"status": "skipped"}
            if notify_telegram:
                notification = _send_telegram_audiobook_status(
                    job=resumed_job,
                    text=telegram_epub_reply_text(resumed_job),
                )
            notifications.append(
                {
                    "job_id": str(resumed_job.get("job_id") or job_dir.name),
                    "status": status,
                    "notification": notification,
                }
            )
            _write_resume_attempt_mark(
                job_dir,
                payload={
                    "attempted_at": observed_at.isoformat().replace("+00:00", "Z"),
                    "completed_at": _now_iso(),
                    "status": status,
                    "notification": notification,
                },
            )
        except Exception as exc:
            errors += 1
            _write_resume_attempt_mark(
                job_dir,
                payload={
                    "attempted_at": observed_at.isoformat().replace("+00:00", "Z"),
                    "completed_at": _now_iso(),
                    "status": "failed",
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )
    share_link_attempted = 0
    share_links_ready = 0
    share_links_blocked = 0
    share_links_waiting = 0
    share_link_notifications: list[dict[str, object]] = []
    for _priority, job_dir, _job in share_rows[:max_jobs]:
        share_link_attempted += 1
        _write_public_share_attempt_mark(
            job_dir,
            payload={"attempted_at": observed_at.isoformat().replace("+00:00", "Z"), "status": "started"},
        )
        try:
            refreshed_job = _refresh_audiobookshelf_public_share_for_job(job_dir)
            import_result = dict(refreshed_job.get("audiobookshelf_import") or {})
            public_share = dict(import_result.get("public_share") or {})
            public_share_status = str(public_share.get("status") or "").strip()
            notification = {"status": "skipped"}
            if public_share_status == "public_share_ready":
                delivery_block = _audiobook_default_voice_public_share_delivery_block(job_dir=job_dir, job=refreshed_job)
                if delivery_block:
                    share_links_blocked += 1
                    notification = {
                        "status": "blocked",
                        "reason": str(delivery_block.get("reason") or "").strip(),
                    }
                    refreshed_job = _record_audiobookshelf_public_share_telegram_delivery_block(
                        job_dir=job_dir,
                        job=refreshed_job,
                        block=delivery_block,
                    )
                else:
                    share_links_ready += 1
                    refreshed_job = ensure_audiobook_playback_acceptance_callback(refreshed_job)
                    if notify_telegram:
                        notification = _send_telegram_audiobook_status(
                            job=refreshed_job,
                            text=_telegram_audiobookshelf_public_share_reply_text(refreshed_job),
                        )
                        refreshed_job = _record_audiobookshelf_public_share_telegram_delivery(
                            job_dir=job_dir,
                            job=refreshed_job,
                            notification=notification,
                        )
            else:
                share_links_waiting += 1
            share_link_notifications.append(
                {
                    "job_id": str(refreshed_job.get("job_id") or job_dir.name),
                    "status": public_share_status,
                    "notification": notification,
                }
            )
            _write_public_share_attempt_mark(
                job_dir,
                payload={
                    "attempted_at": observed_at.isoformat().replace("+00:00", "Z"),
                    "completed_at": _now_iso(),
                    "status": public_share_status,
                    "notification": notification,
                },
            )
        except Exception as exc:
            errors += 1
            _write_public_share_attempt_mark(
                job_dir,
                payload={
                    "attempted_at": observed_at.isoformat().replace("+00:00", "Z"),
                    "completed_at": _now_iso(),
                    "status": "failed",
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )
    return {
        "ran": True,
        "attempted": attempted,
        "resumed": resumed,
        "imported": imported,
        "throttled": throttled,
        "pending": pending + max(len(rows) - max_jobs, 0),
        "skipped": skipped,
        "skip_reasons": dict(sorted(skip_reasons.items())),
        "ignored_terminal": ignored_terminal,
        "ignored_terminal_reasons": dict(sorted(ignored_terminal_reasons.items())),
        "operator_review_pending": operator_review_pending,
        "operator_review_reasons": dict(sorted(operator_review_reasons.items())),
        "completed_terminal": completed_terminal,
        "completed_terminal_reasons": dict(sorted(completed_terminal_reasons.items())),
        "errors": errors,
        "notifications": notifications[:10],
        "share_link_attempted": share_link_attempted,
        "share_links_ready": share_links_ready,
        "share_links_blocked": share_links_blocked,
        "share_link_pending": share_link_pending + max(len(share_rows) - max_jobs, 0) + share_links_waiting,
        "share_link_notifications": share_link_notifications[:10],
    }
