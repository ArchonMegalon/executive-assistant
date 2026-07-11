from __future__ import annotations

import contextlib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
import base64
import errno
import fcntl
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
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave
import zipfile
import xml.etree.ElementTree as ET

from app.services.memorial_openvoice import (
    piper_fast_synthesize_request,  # noqa: F401 - compatibility patch surface
    unmixr_language,  # noqa: F401 - compatibility patch surface
    unmixr_api_key,
    unmixr_api_key_slot_count,
    unmixr_memorial_voice_id,
    unmixr_pronunciation_dict,
    unmixr_speaking_pitch,
    unmixr_speaking_rate,
    unmixr_speaking_volume,
    unmixr_synthesize_request,
)
from app.services.audiobook_narration_planner import (
    BOUNDARY_POLICY_NAME,
    PLANNER_CONTRACT_NAME,
    PlannerChapter,
    plan_narration,
)


CONTRACT_NAME = "ea.telegram_epub_to_audiobook.v1"
SOURCE_DOCUMENT_CONTRACT_NAME = "ea.audiobook_source_document.v1"
NARRATION_PLAN_CONTRACT_NAME = PLANNER_CONTRACT_NAME
SPEAKER_CAST_SNAPSHOT_CONTRACT_NAME = "ea.audiobook_speaker_cast_snapshot.v1"
SPEAKER_CAST_POLICY_NAME = "ea.audiobook_speaker_cast_policy.v3"
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
_PROVIDER_WAIT_RE = re.compile(
    r"(?:available|retry|try again)[^0-9]{0,40}(\d{1,7})[_\s-]*seconds?",
    re.IGNORECASE,
)
_EPUB_SCENE_BREAK_SENTINEL = "\u241eEA_AUDIOBOOK_SCENE_BREAK\u241e"
_EPUB_BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "dd",
    "div",
    "dl",
    "dt",
    "figcaption",
    "figure",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "td",
    "th",
    "tr",
    "ul",
}
_EPUB_SCENE_BREAK_HINTS = {
    "asterism",
    "dinkus",
    "ornament",
    "scene",
    "scene-break",
    "scene_break",
    "separator",
    "section-break",
    "section_break",
    "transition",
}
_DIALOGUE_OPENERS = ('"', "“", "„", "«", "»", "‹", "›")
_DIALOGUE_DASH_OPENERS = ("— ", "– ")
_VOICE_DISCOVERY_CACHE: dict[str, tuple[float, tuple["VoicePreset", ...]]] = {}
_DOTENV_CACHE: dict[tuple[Path, ...], dict[str, str]] = {}
_AUDIOBOOK_EXTERNAL_TTS_ENV_LOCK = threading.RLock()
_AUDIOBOOK_CLEANUP_MISSING_ERRNOS = {
    errno.ENOENT,
    errno.ENOTDIR,
    getattr(errno, "ESTALE", errno.ENOENT),
    getattr(errno, "ENOTCONN", errno.ENOENT),
}
_PERSON_NAME_TITLES = {
    "dr",
    "frau",
    "herr",
    "ii",
    "iii",
    "iv",
    "jr",
    "lady",
    "miss",
    "mr",
    "mrs",
    "ms",
    "phd",
    "prof",
    "sir",
    "sr",
}
_KNOWN_FEMALE_FIRST_NAMES = {
    "alice",
    "anna",
    "anne",
    "barbara",
    "bettina",
    "birgit",
    "brigitte",
    "charlotte",
    "christine",
    "claudia",
    "diana",
    "donna",
    "elena",
    "elisabeth",
    "elizabeth",
    "emily",
    "eva",
    "franziska",
    "helga",
    "isabel",
    "jane",
    "jennifer",
    "jessica",
    "joanne",
    "julia",
    "katharina",
    "katherine",
    "laura",
    "lisa",
    "margaret",
    "maria",
    "marie",
    "mary",
    "nicole",
    "patricia",
    "rachel",
    "rebecca",
    "sabine",
    "sandra",
    "sarah",
    "seraphina",
    "susan",
    "susanne",
    "theresa",
    "ursula",
    "victoria",
    "amala",
    "gisela",
}
_KNOWN_MALE_FIRST_NAMES = {
    "alexander",
    "andreas",
    "anthony",
    "ben",
    "bernd",
    "brandon",
    "christian",
    "daniel",
    "david",
    "florian",
    "frank",
    "george",
    "georg",
    "hans",
    "henry",
    "james",
    "jason",
    "john",
    "johannes",
    "josef",
    "jurgen",
    "karl",
    "kevin",
    "luke",
    "mark",
    "markus",
    "martin",
    "max",
    "michael",
    "nassim",
    "neil",
    "nicholas",
    "noah",
    "patrick",
    "peter",
    "robert",
    "robin",
    "scott",
    "sebastian",
    "stefan",
    "stephen",
    "steve",
    "terry",
    "thomas",
    "tobias",
    "victor",
    "wolfgang",
    "yuval",
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
    structure_path: str = ""


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


class _AudiobookLockTimeout(TimeoutError):
    """Raised only when an audiobook transaction lock cannot be acquired."""


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


def _audiobook_max_automatic_speaker_voices() -> int:
    return _env_int(
        "EA_AUDIOBOOK_MAX_AUTOMATIC_SPEAKER_VOICES",
        8,
        minimum=1,
        maximum=32,
    )


def _audiobook_cinematic_narration() -> bool:
    return _env_bool("EA_AUDIOBOOK_CINEMATIC_NARRATION", True)


def _audiobook_cinematic_single_pass() -> bool:
    # The active Unmixr adapter uses the short-TTS contract. A whole-book request is
    # therefore an explicit compatibility escape hatch, never the safe default.
    return _env_bool("EA_AUDIOBOOK_CINEMATIC_SINGLE_PASS", False)


def _audiobook_cinematic_max_chars_per_request() -> int:
    return _env_int(
        "EA_AUDIOBOOK_CINEMATIC_MAX_CHARS_PER_REQUEST",
        _env_int("EA_AUDIOBOOK_UNMIXR_MAX_CHARS_PER_REQUEST", 1800, minimum=1000, maximum=200000),
        minimum=1000,
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
        expected_hash = str(chapter.sha256 or "").strip().lower()
        if (
            source_text.endswith("\n")
            and re.fullmatch(r"[0-9a-f]{64}", expected_hash)
            and _sha256_bytes(source_text.encode("utf-8")) != expected_hash
            and _sha256_bytes(source_text[:-1].encode("utf-8")) == expected_hash
        ):
            # extract_epub_chapters adds one storage newline after hashing the
            # source text. Remove only that proven synthetic byte; never strip
            # authorial leading/trailing whitespace heuristically.
            source_text = source_text[:-1]
        values.append((chapter, source_text))
    return tuple(values)


def _build_exact_narration_plan(
    *,
    chapter_inputs: tuple[tuple[EpubChapter, str], ...],
    render_language: str,
    max_chars: int,
) -> dict[str, object]:
    planner_chapters = tuple(
        PlannerChapter(
            index=chapter.index,
            source_href=chapter.source_href,
            text=text,
            expected_sha256=(
                str(chapter.sha256).strip().lower()
                if re.fullmatch(r"[0-9a-f]{64}", str(chapter.sha256 or "").strip().lower())
                else ""
            ),
        )
        for chapter, text in chapter_inputs
        if text
    )
    if not planner_chapters:
        return {
            "contract_name": NARRATION_PLAN_CONTRACT_NAME,
            "status": "ready",
            "source_coverage": "complete",
            "coverage_complete": True,
            "source_integrity_verified": True,
            "source_integrity_issues": [],
            "passages": [],
            "speakers": [],
            "dialogue_span_count": 0,
            "plan_sha256": _sha256_bytes(b"empty-audiobook-plan-v2"),
        }
    return plan_narration(
        planner_chapters,
        language=render_language,
        max_chars=max_chars,
        batch_paragraphs_with_natural_pauses=(
            _audiobook_batch_paragraphs_with_natural_pauses()
        ),
        pause_policy={
            "continuation": _env_float(
                "EA_AUDIOBOOK_CONTINUATION_PAUSE_SECONDS",
                0.12,
                minimum=0.0,
                maximum=1.0,
            ),
            "sentence": _env_float(
                "EA_AUDIOBOOK_SENTENCE_PAUSE_SECONDS",
                0.18,
                minimum=0.0,
                maximum=1.5,
            ),
            "paragraph": _audiobook_paragraph_pause_seconds(),
            "speaker": _audiobook_speaker_pause_seconds(),
            "scene": _audiobook_scene_pause_seconds(),
            "chapter": _env_float(
                "EA_AUDIOBOOK_CHAPTER_PAUSE_SECONDS",
                1.5,
                minimum=0.0,
                maximum=8.0,
            ),
        },
    )


def _public_exact_narration_plan_summary(plan: dict[str, object]) -> dict[str, object]:
    return {
        "contract_name": str(plan.get("contract_name") or NARRATION_PLAN_CONTRACT_NAME),
        "status": str(plan.get("status") or "blocked"),
        "plan_sha256": str(plan.get("plan_sha256") or ""),
        "source_aggregate_sha256": str(plan.get("source_aggregate_sha256") or ""),
        "source_coverage": str(plan.get("source_coverage") or "mismatch"),
        "coverage_complete": bool(plan.get("coverage_complete")),
        "source_integrity_verified": bool(plan.get("source_integrity_verified")),
        "chapter_count": int(plan.get("chapter_count") or 0),
        "passage_count": int(plan.get("passage_count") or 0),
        "dialogue_span_count": int(plan.get("dialogue_span_count") or 0),
        "attributed_dialogue_span_count": int(
            plan.get("attributed_dialogue_span_count") or 0
        ),
        "uncertain_dialogue_span_count": int(
            plan.get("uncertain_dialogue_span_count") or 0
        ),
        "speaker_count": int(plan.get("speaker_count") or 0),
        "boundary_counts": dict(plan.get("boundary_counts") or {}),
        "raw_text_exposed": False,
        "raw_voice_ids_exposed": False,
    }


def _exact_narration_plan_block_reason(plan: dict[str, object]) -> str:
    if not bool(plan.get("coverage_complete")) or not bool(
        plan.get("source_integrity_verified")
    ):
        # Retain the established public render reason while the v2 private plan
        # carries the more precise integrity issue list.
        return "blocked_source_integrity_or_coverage_mismatch"
    return str(plan.get("status") or "blocked_source_integrity_or_planning")


def _public_dialogue_voice_selection_from_cast(
    speaker_cast: dict[str, object],
) -> dict[str, object]:
    public = dict(speaker_cast.get("public") or {})
    status = str(public.get("status") or speaker_cast.get("status") or "not_required")
    resolved = int(public.get("resolved_speaker_count") or 0)
    return {
        **public,
        "status": status,
        "source": "automatic_or_approved_per_speaker_cast",
        "distinct_from_narrator": status == "ready" and resolved > 0,
        "raw_voice_id_exposed": False,
        "identity_or_gender_inferred": False,
    }


def _cinematic_track_signature(
    *,
    chapter_inputs: tuple[tuple[EpubChapter, str], ...],
    narrator_voice_id: str = "",
    dialogue_voice_id: str = "",
    render_language: str = "",
    planner_plan_sha256: str = "",
    cast_map_sha256: str = "",
) -> str:
    payload = {
        "chapters": [
            {
                "index": chapter.index,
                "source_href": chapter.source_href,
                "text_sha256": _sha256_bytes(text.encode("utf-8")),
            }
            for chapter, text in chapter_inputs
        ],
        "single_pass": _audiobook_cinematic_single_pass(),
        "narrator_voice_id_sha256": (
            _sha256_bytes(narrator_voice_id.encode("utf-8")) if narrator_voice_id else ""
        ),
        "dialogue_voice_id_sha256": (
            _sha256_bytes(dialogue_voice_id.encode("utf-8")) if dialogue_voice_id else ""
        ),
        "render_language": _normalize_language(render_language),
        "planner_plan_sha256": planner_plan_sha256,
        "cast_map_sha256": cast_map_sha256,
        "mastering_contract": _audiobook_mastering_contract(),
        "provider_segment_edge_trim_contract": _audiobook_segment_edge_trim_contract(),
        "speaking_rate": unmixr_speaking_rate(),
        "speaking_pitch": unmixr_speaking_pitch(),
        "speaking_volume": unmixr_speaking_volume(),
        "pronunciation_dictionary_sha256": _sha256_bytes(
            str(os.getenv("EA_AUDIOBOOK_UNMIXR_PRONUNCIATION_DICT_JSON") or "").encode("utf-8")
        ),
        "max_chars_per_request": _audiobook_cinematic_max_chars_per_request(),
        "batch_paragraphs": _audiobook_batch_paragraphs_with_natural_pauses(),
        "paragraph_pause_seconds": _audiobook_paragraph_pause_seconds(),
        "scene_pause_seconds": _audiobook_scene_pause_seconds(),
        "speaker_pause_seconds": _audiobook_speaker_pause_seconds(),
        "segmentation": "semantic_sentence_source_boundary_and_explicit_dialogue_v1",
        "narration_plan_contract": NARRATION_PLAN_CONTRACT_NAME,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


_CINEMATIC_MASTER_SINGLE_PASS_MODE = "unmixr_cinematic_single_pass"
_CINEMATIC_MASTER_SEGMENTED_FALLBACK_MODE = "unmixr_cinematic_segmented_fallback"
_CINEMATIC_MASTER_SEMANTIC_PASS_MODE = "unmixr_cinematic_semantic_pass"
_CINEMATIC_MASTER_VALID_MODES = {
    _CINEMATIC_MASTER_SINGLE_PASS_MODE,
    _CINEMATIC_MASTER_SEGMENTED_FALLBACK_MODE,
    _CINEMATIC_MASTER_SEMANTIC_PASS_MODE,
}


def _cinematic_master_mode_compatible(mode: str, *, dialogue_voice_enabled: bool = False) -> bool:
    if _audiobook_cinematic_single_pass() and not dialogue_voice_enabled:
        return mode in {
            _CINEMATIC_MASTER_SINGLE_PASS_MODE,
            _CINEMATIC_MASTER_SEGMENTED_FALLBACK_MODE,
        }
    return mode == _CINEMATIC_MASTER_SEMANTIC_PASS_MODE


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
    configured_dialogue_voice_selection = _configured_dialogue_voice_selection(job_dir)
    configured_dialogue_voice_id = str(
        configured_dialogue_voice_selection.get("voice_id") or ""
    ).strip()
    try:
        job_payload = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    except Exception:
        job_payload = {}
    selected_voice = selected_unmixr_voice_for_job(job_dir)
    if not str(selected_voice.get("voice_id") or "").strip() and job_payload:
        try:
            selected_voice = select_unmixr_voice_for_book(
                metadata=_metadata_from_job(job_payload),
                chapters=chapters,
                job_dir=job_dir,
            )
        except Exception:
            selected_voice = {}
    narrator_voice_id = str(selected_voice.get("voice_id") or "").strip()
    if configured_dialogue_voice_id == narrator_voice_id:
        configured_dialogue_voice_id = ""
    render_language = _normalize_language(
        dict(job_payload.get("metadata") or {}).get("language")
    )
    exact_plan = _build_exact_narration_plan(
        chapter_inputs=tuple(cinematic_track_input),
        render_language=render_language,
        max_chars=_audiobook_cinematic_max_chars_per_request(),
    )
    if exact_plan.get("status") != "ready":
        return None
    speaker_cast = (
        _resolve_speaker_cast_for_narration_plan(
            job_dir=job_dir,
            narration_plan=exact_plan,
            narrator_voice_id=narrator_voice_id,
            render_language=render_language,
            default_dialogue_selection=configured_dialogue_voice_selection,
        )
        if narrator_voice_id
        else {"status": "not_required", "cast_map_sha256": ""}
    )
    if speaker_cast.get("status") == "blocked":
        return None
    dialogue_voice_enabled = bool(
        configured_dialogue_voice_id
        or int(exact_plan.get("dialogue_span_count") or 0)
    )
    cinematic_signature_expected = _cinematic_track_signature(
        chapter_inputs=tuple(cinematic_track_input),
        narrator_voice_id=narrator_voice_id,
        dialogue_voice_id=configured_dialogue_voice_id,
        render_language=render_language,
        planner_plan_sha256=str(exact_plan.get("plan_sha256") or ""),
        cast_map_sha256=str(speaker_cast.get("cast_map_sha256") or ""),
    )

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
        cinematic_mode not in _CINEMATIC_MASTER_VALID_MODES
        or not _cinematic_master_mode_compatible(
            cinematic_mode,
            dialogue_voice_enabled=dialogue_voice_enabled,
        )
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
    configured = tuple(_split_configured_paths(str(os.getenv("EA_AUDIOBOOK_JOB_DISCOVERY_ROOTS") or "")))
    if configured:
        candidates: tuple[Path, ...] = configured
    else:
        candidates = (
            *_split_configured_paths(str(os.getenv("EA_AUDIOBOOK_JOBS_ROOT") or "")),
            *_split_configured_paths(str(os.getenv("EA_AUDIOBOOK_JOBS_HOST_ROOT") or "")),
            audiobook_jobs_root(),
            DEFAULT_JOB_ROOT,
        )
    roots: list[Path] = []
    seen: set[str] = set()
    for root in candidates:
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


def _normalize_person_name_token(value: object) -> str:
    raw = unicodedata.normalize("NFKD", str(value or ""))
    stripped = "".join(char for char in raw if not unicodedata.combining(char))
    return re.sub(r"[^A-Za-z-]+", "", stripped).strip("-").lower()


def _person_name_tokens(value: object) -> tuple[str, ...]:
    raw = str(value or "").strip()
    if not raw:
        return ()
    if "," in raw:
        parts = [part.strip() for part in raw.split(",") if part.strip()]
        if len(parts) >= 2:
            raw = f"{parts[1]} {parts[0]}"
    tokens: list[str] = []
    for part in raw.replace(",", " ").split():
        token = _normalize_person_name_token(part)
        if not token or token in _PERSON_NAME_TITLES or len(token) <= 1:
            continue
        tokens.append(token)
    return tuple(tokens)


def _person_first_name(value: object) -> str:
    tokens = _person_name_tokens(value)
    return tokens[0] if tokens else ""


def _person_gender_candidate_tokens(value: object) -> tuple[str, ...]:
    expanded: list[str] = []
    seen: set[str] = set()
    for token in _person_name_tokens(value):
        for candidate in (token, *[part for part in token.split("-") if part]):
            if candidate and candidate not in seen:
                seen.add(candidate)
                expanded.append(candidate)
    return tuple(expanded)


def _infer_person_name_gender(value: object) -> str:
    candidates = _person_gender_candidate_tokens(value)
    if not candidates:
        return ""
    first = candidates[0]
    if first in _KNOWN_FEMALE_FIRST_NAMES:
        return "female"
    if first in _KNOWN_MALE_FIRST_NAMES:
        return "male"
    inferred: set[str] = set()
    for token in candidates:
        if token in _KNOWN_FEMALE_FIRST_NAMES:
            inferred.add("female")
        if token in _KNOWN_MALE_FIRST_NAMES:
            inferred.add("male")
    if len(inferred) == 1:
        return next(iter(inferred))
    return ""


def _voice_tags_with_inferred_gender(
    tags: tuple[str, ...],
    *,
    label: object = "",
    gender_hint: object = "",
) -> tuple[str, ...]:
    # Provider labels and person names are not demographic evidence. Keep
    # ``label`` in the signature for compatibility, but only use explicit
    # catalog fields/tags when ranking a voice by gender presentation.
    del label
    normalized = list(_split_tags(tags))
    canonical_gender_tags = {
        _speaker_trait_value(
            "gender_presentation",
            tag.removeprefix("gender_"),
        )
        for tag in normalized
    }.intersection({"male", "female", "nonbinary", "neutral"})
    if canonical_gender_tags:
        normalized.extend(sorted(canonical_gender_tags))
        return tuple(dict.fromkeys(normalized))
    explicit_gender = _speaker_trait_value("gender_presentation", gender_hint)
    if explicit_gender in {"male", "female", "nonbinary", "neutral"}:
        normalized.append(explicit_gender)
    return tuple(dict.fromkeys(normalized))


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
    explicit_trait_fields = {
        "gender_presentation": ("gender", "gender_presentation"),
        "approximate_age": ("age", "age_band", "age_range", "approximate_age"),
        "accent": ("accent", "dialect"),
        "ethnicity": (
            "ethnicity",
            "ethnic_background",
            "cultural_background",
            "cultural_or_ethnic_background",
            "cultural_identity",
        ),
        "role": ("role", "character_role"),
        "style": ("style", "performance_style"),
    }
    for kind, keys in explicit_trait_fields.items():
        raw_value: object = None
        for key in keys:
            if row.get(key) not in (None, ""):
                raw_value = row.get(key)
                break
        raw_items = (
            list(raw_value)
            if isinstance(raw_value, (list, tuple, set))
            else [raw_value]
        )
        for raw_item in raw_items:
            normalized = _speaker_trait_value(kind, raw_item)
            if normalized in {"", "unknown", "unspecified", "none"}:
                continue
            values.append(normalized)
            if kind == "gender_presentation":
                values.append(f"gender_{normalized}")
            elif kind == "approximate_age":
                values.append(f"age_{normalized}")
            elif kind == "accent":
                values.append(f"accent_{normalized}")
            elif kind == "ethnicity":
                values.extend(
                    (
                        f"ethnicity_{normalized}",
                        f"cultural_background_{normalized}",
                    )
                )
            elif kind == "role":
                values.append(f"role_{normalized}")
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
            return
        if self._skip_depth:
            return
        attribute_tokens: set[str] = set()
        for name, value in attrs or ():
            if str(name or "").strip().lower() not in {"class", "id", "role", "epub:type"}:
                continue
            attribute_tokens.update(
                token
                for token in re.split(r"[^a-z0-9_-]+", str(value or "").strip().lower())
                if token
            )
        if lowered == "hr" or attribute_tokens.intersection(_EPUB_SCENE_BREAK_HINTS):
            self.parts.append(_EPUB_SCENE_BREAK_SENTINEL)
        elif lowered == "br":
            self.parts.append("\n")
        elif lowered in _EPUB_BLOCK_TAGS:
            # A boundary is emitted only on block entry. Emitting on both entry and
            # exit makes nested section/div/p markup look like a false scene break.
            self.parts.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style", "svg", "math"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_startendtag(self, tag: str, attrs) -> None:  # type: ignore[override]
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if data:
            # Retain the source's inline spacing here. _clean_epub_text normalizes
            # horizontal whitespace without erasing structural line boundaries.
            self.parts.append(re.sub(r"\s+", " ", str(data)))

    def text(self) -> str:
        return unescape("".join(self.parts)).strip()


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
    cleaned = str(text or "").replace("\ufeff", " ").replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(
        r"(?m)^[ \t]*(?:\*\s*\*\s*\*+|[•·◆◇❦⁂]{1,4}|[-–—]\s*[-–—]\s*[-–—]+)[ \t]*$",
        _EPUB_SCENE_BREAK_SENTINEL,
        cleaned,
    )
    chunks: list[str] = []
    for raw_chunk in cleaned.split(_EPUB_SCENE_BREAK_SENTINEL):
        chunk = re.sub(r"[ \t\f\v]+", " ", raw_chunk)
        chunk = re.sub(r" *\n *", "\n", chunk)
        chunk = re.sub(r"\n{2,}", "\n\n", chunk).strip()
        if chunk:
            chunks.append(chunk)
    return "\n\n\n".join(chunks).strip()


def _source_document_manifest(*, text: str, source_payload: bytes, source_href: str) -> dict[str, object]:
    blocks: list[dict[str, object]] = []
    cursor = 0
    block_index = 0
    scene_index = 0
    for scene_text in text.split("\n\n\n"):
        if not scene_text:
            continue
        if blocks:
            scene_index += 1
        for paragraph in scene_text.split("\n\n"):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            start = text.find(paragraph, cursor)
            if start < 0:
                start = cursor
            end = start + len(paragraph)
            block_index += 1
            blocks.append(
                {
                    "block_index": block_index,
                    "kind": "passage",
                    "scene_index": scene_index,
                    "char_start": start,
                    "char_end": end,
                    "char_count": len(paragraph),
                    "text_sha256": _sha256_bytes(paragraph.encode("utf-8")),
                }
            )
            cursor = end
    return {
        "contract_name": SOURCE_DOCUMENT_CONTRACT_NAME,
        "source_href": source_href,
        "source_html_sha256": _sha256_bytes(source_payload),
        "extracted_text_sha256": _sha256_bytes(text.encode("utf-8")),
        "extracted_char_count": len(text),
        "block_count": len(blocks),
        "scene_count": (max((int(block["scene_index"]) for block in blocks), default=-1) + 1),
        "raw_source_text_embedded": False,
        "blocks": blocks,
    }


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
            structure_filename = f"{index:03d} - {safe_title}.source.json"
            audio_filename = f"{index:03d} - {safe_title}.wav"
            text_path = chapter_dir / text_filename
            text_path.write_text(text + "\n", encoding="utf-8")
            structure_path = chapter_dir / structure_filename
            structure_path.write_text(
                json.dumps(
                    _source_document_manifest(
                        text=text,
                        source_payload=payload,
                        source_href=chapter_member,
                    ),
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            chapters.append(
                EpubChapter(
                    index=index,
                    title=chapter_title,
                    source_href=chapter_member,
                    text_path=text_path.name,
                    audio_filename=audio_filename,
                    char_count=len(text),
                    sha256=_sha256_bytes(text.encode("utf-8")),
                    structure_path=structure_path.name,
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
        language = _normalize_language(
            row.get("language")
            or row.get("locale")
            or row.get("lang")
            or os.getenv("UNMIXR_LANGUAGE")
            or "en-US"
        )
        supported_languages = _split_languages(
            row.get("supported_languages")
            or row.get("supported_locales")
            or row.get("other_languages")
            or row.get("languages")
            or language
        )
        tags = _voice_tags_with_inferred_gender(
            _split_tags(_row_tag_values(row)),
            label=label,
            gender_hint=row.get("gender"),
        )
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
    values: list[object] = [use_case, *_row_tag_values(row)]
    if any(term in normalized_use_case for term in ("audiobook", "narration", "documentary", "podcast")):
        values.extend(["audiobook", "narration"])
    for key in ("quality", "capabilities", "roles", "use_cases", "personality"):
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
    return _voice_tags_with_inferred_gender(
        _split_tags(values),
        label=row.get("character") or row.get("label") or row.get("name"),
        gender_hint=row.get("gender"),
    )


def _voice_preset_from_unmixr_row(row: dict[str, object], *, use_case: str, index: int) -> VoicePreset | None:
    if row.get("is_available") is False:
        return None
    voice_id = str(row.get("uuid") or row.get("voice_id") or row.get("id") or "").strip()
    if not voice_id:
        return None
    label = str(row.get("character") or row.get("label") or row.get("name") or f"Audio Voice {index}").strip()
    base_key = _normalize_tag(label) or f"voice_{index:02d}"
    preset_key = f"unmixr_{base_key}_{voice_id[:8].lower()}"
    language = _normalize_language(
        row.get("language")
        or row.get("locale")
        or os.getenv("UNMIXR_LANGUAGE")
        or "en-US"
    )
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
            default_label = str(os.getenv("EA_AUDIOBOOK_DEFAULT_VOICE_LABEL") or "Configured audio voice").strip()
            default_tags = _voice_tags_with_inferred_gender(
                _split_tags(os.getenv("EA_AUDIOBOOK_DEFAULT_VOICE_TAGS") or "narration,neutral,general"),
                label=default_label,
            )
            discovered = (
                VoicePreset(
                    preset_key="default_env_voice",
                    voice_id=default_voice_id,
                    label=default_label,
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
    default_label = str(os.getenv("EA_AUDIOBOOK_DEFAULT_VOICE_LABEL") or "Configured audio voice").strip()
    default_tags = _voice_tags_with_inferred_gender(
        _split_tags(os.getenv("EA_AUDIOBOOK_DEFAULT_VOICE_TAGS") or "narration,neutral,general"),
        label=default_label,
    )
    default_language = _audiobook_voice_language_from_tags(default_tags)
    return (
        VoicePreset(
            preset_key="default_env_voice",
            voice_id=default_voice_id,
            label=default_label,
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
    # An author's name is not reliable or consented demographic evidence.
    # A future explicit, approved metadata field may provide this signal.
    del author
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
        "author_gender_signal_provenance": "not_available_without_explicit_approved_metadata",
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
        "author_gender_signal_provenance": profile.get(
            "author_gender_signal_provenance",
            "not_available_without_explicit_approved_metadata",
        ),
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
        for row in candidate_rows:
            if not bool(row.get("language_match")):
                continue
            declared_gender_tokens = {
                _normalize_tag(value)
                for value in [
                    *list(row.get("tags") or []),
                    row.get("gender"),
                    row.get("gender_presentation"),
                ]
                if _normalize_tag(value)
            }
            if not declared_gender_tokens.intersection(
                {"male", "female", "masculine", "feminine"}
            ):
                # An unlabelled, language-compatible voice is neutral evidence,
                # not a conflict. Language compatibility remains the hard gate.
                return dict(row), False
        if not _env_bool("EA_AUDIOBOOK_ALLOW_AUTHOR_GENDER_FALLBACK", False):
            # Preserve the fact that a gender preference was requested even
            # when the catalog cannot satisfy it. The caller must fail closed
            # instead of silently selecting a conflicting voice.
            return {}, True
    selected = _first_match(require_author_gender_match=False, require_language_match=True)
    if selected:
        return selected, bool(normalized_author_gender_signal)
    if normalized_author_gender_signal and _env_bool("EA_AUDIOBOOK_ALLOW_AUTHOR_GENDER_FALLBACK", False):
        selected = _first_match(require_author_gender_match=True, require_language_match=False)
        if selected:
            return selected, True
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


def _public_selected_voice_payload(voice_selection: dict[str, object]) -> tuple[dict[str, object], dict[str, object]]:
    public = (
        dict(voice_selection.get("public") or {})
        if isinstance(voice_selection.get("public"), dict)
        else dict(voice_selection or {})
    )
    selected = dict(public.get("selected") or {})
    if not selected:
        selected = dict(public)
    return public, selected


def _selected_voice_language_mismatch(*, metadata: EpubMetadata, voice_selection: dict[str, object]) -> dict[str, object]:
    if _env_bool("EA_AUDIOBOOK_ALLOW_VOICE_LANGUAGE_MISMATCH", False):
        return {}
    public, selected = _public_selected_voice_payload(voice_selection)
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


def _selected_voice_author_gender_signal(*, metadata: EpubMetadata, voice_selection: dict[str, object]) -> str:
    del metadata
    public, _selected = _public_selected_voice_payload(voice_selection)
    profile = dict(public.get("book_profile") or voice_selection.get("book_profile") or {})
    if (
        str(profile.get("author_gender_signal_provenance") or "").strip()
        != "explicit_approved_metadata"
    ):
        return ""
    author_gender_signal = str(profile.get("author_gender_signal") or "").strip().lower()
    if author_gender_signal in {"male", "female"}:
        return author_gender_signal
    return ""


def _author_gender_mismatch_replacement_candidates(
    *,
    job_dir: Path,
    metadata: EpubMetadata,
    voice_selection: dict[str, object],
    limit: int = 3,
    include_current_selected: bool = False,
) -> tuple[str, list[dict[str, object]]]:
    public, selected = _public_selected_voice_payload(voice_selection)
    author_gender_signal = _selected_voice_author_gender_signal(metadata=metadata, voice_selection=voice_selection)
    if author_gender_signal not in {"male", "female"} or limit <= 0:
        return author_gender_signal, []
    selected_key = str(public.get("selected_candidate_key") or selected.get("preset_key") or "").strip()
    selected_token = str(public.get("selected_callback_token") or selected.get("callback_token") or "").strip()
    selected_identities = _voice_candidate_identity_keys(selected)
    dismissed_keys = {
        str(item or "").strip()
        for item in list(public.get("dismissed_candidate_keys") or [])
        if str(item or "").strip()
    }
    dismissed_identity_keys = {
        str(item or "").strip()
        for item in list(public.get("dismissed_voice_identity_keys") or [])
        if str(item or "").strip()
    }
    private_payload = _load_voice_audition_private(job_dir)
    private_candidates = dict(private_payload.get("candidates") or {})
    sample_dir = _voice_audition_dir(job_dir) / "samples"
    current_selected_public: dict[str, object] = {}
    replacement_rows: list[dict[str, object]] = []
    seen_preset_keys: set[str] = set()
    seen_identity_keys: set[str] = set()
    for token, candidate in private_candidates.items():
        if not isinstance(candidate, dict):
            continue
        candidate_public = dict(candidate.get("public") or {})
        preset_key = str(candidate_public.get("preset_key") or candidate.get("candidate_key") or "").strip()
        if not preset_key:
            continue
        token_value = str(candidate_public.get("callback_token") or token).strip()
        sample_file = Path(str(candidate_public.get("sample_file") or "")).name
        if not sample_file or not token_value:
            continue
        sample_path = sample_dir / sample_file
        if not sample_path.is_file():
            continue
        if not _voice_candidate_allowed_for_audition(candidate_public):
            continue
        candidate_public["callback_token"] = token_value
        identity_keys = _voice_candidate_identity_keys(candidate_public)
        if identity_keys and identity_keys.intersection(dismissed_identity_keys):
            continue
        if preset_key in dismissed_keys:
            continue
        matches_selected = bool(
            (selected_token and token_value == selected_token)
            or (selected_key and preset_key == selected_key)
            or (selected_identities and identity_keys.intersection(selected_identities))
        )
        if matches_selected:
            current_selected_public = dict(candidate_public)
            continue
        if _voice_candidate_gender(candidate_public) != author_gender_signal:
            continue
        if not _voice_language_matches(
            metadata.language,
            str(candidate_public.get("language") or ""),
            _split_languages(candidate_public.get("supported_languages") or candidate_public.get("language")),
        ):
            continue
        if preset_key in seen_preset_keys:
            continue
        if identity_keys and identity_keys.intersection(seen_identity_keys):
            continue
        replacement_rows.append(candidate_public)
        seen_preset_keys.add(preset_key)
        seen_identity_keys.update(identity_keys)
    replacement_rows.sort(
        key=lambda row: (
            bool(row.get("language_match")),
            int(row.get("score") or 0),
            bool(_voice_candidate_has_tag(row, "premium")),
        ),
        reverse=True,
    )
    available_slots = max(limit - (1 if include_current_selected and current_selected_public else 0), 0)
    selected_rows = replacement_rows[:available_slots]
    if include_current_selected and current_selected_public:
        selected_rows.append(current_selected_public)
    return author_gender_signal, selected_rows


def _selected_voice_author_gender_mismatch(
    *,
    job_dir: Path,
    metadata: EpubMetadata,
    voice_selection: dict[str, object],
) -> dict[str, object]:
    if _env_bool("EA_AUDIOBOOK_ALLOW_VOICE_AUTHOR_GENDER_MISMATCH", False):
        return {}
    public, selected = _public_selected_voice_payload(voice_selection)
    if (
        bool(voice_selection.get("voice_author_gender_override_by_user"))
        or bool(public.get("voice_author_gender_override_by_user"))
        or bool(selected.get("voice_author_gender_override_by_user"))
    ):
        return {}
    author_gender_signal = _selected_voice_author_gender_signal(metadata=metadata, voice_selection=voice_selection)
    if author_gender_signal not in {"male", "female"}:
        return {}
    selected_gender = _voice_candidate_gender(selected)
    if selected_gender not in {"male", "female"} or selected_gender == author_gender_signal:
        return {}
    _signal, replacement_rows = _author_gender_mismatch_replacement_candidates(
        job_dir=job_dir,
        metadata=metadata,
        voice_selection=voice_selection,
        limit=3,
    )
    if not replacement_rows:
        return {}
    return {
        "author_gender_signal": author_gender_signal,
        "selected_gender": selected_gender,
        "replacement_candidate_count": len(replacement_rows),
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
        narrator_eligible = bool(
            preset.default
            or "narration" in tags
            or (
                "audiobook" in tags
                and not tags.intersection({"dialogue", "character", "actor"})
            )
        )
        candidate_rows.append(
            {
                "preset_key": preset.preset_key,
                "label": _safe_authenticated_catalog_voice_label(
                    preset.label,
                    preset.voice_id,
                ),
                "language": preset.language,
                "supported_languages": list(preset.supported_languages[:20]),
                "language_match": language_match,
                "language_score": language_score,
                "tags": list(preset.tags),
                "score": score,
                "matched_tags": tag_overlap,
                "author_gender_match": bool(author_gender_signal and author_gender_signal in tags),
                "default": preset.default,
                "narrator_eligible": narrator_eligible,
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
        key=lambda row: (
            bool(row.get("language_match")),
            bool(row.get("narrator_eligible")),
            int(row["score"]),
            bool(row["default"]),
        ),
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
        if author_gender_preference_used and not _env_bool("EA_AUDIOBOOK_ALLOW_AUTHOR_GENDER_FALLBACK", False):
            public_candidate_rows = [
                {key: value for key, value in row.items() if key != "_voice_id"}
                for row in candidate_rows[:8]
            ]
            return {
                "status": "blocked",
                "reason": "author_gender_matching_voice_missing",
                "voice_id": "",
                "public": {
                    "status": "blocked",
                    "reason": "author_gender_matching_voice_missing",
                    "strategy": "book_profile_voice_selection",
                    "author_gender_preference_used": True,
                    "book_profile": _public_book_profile(profile),
                    "candidate_count": len(candidate_rows),
                    "candidate_scores": public_candidate_rows,
                    "raw_voice_ids_exposed": False,
                },
            }
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


def _write_private_json(path: Path, payload: dict[str, object], *, private_parent: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if private_parent:
        path.parent.chmod(0o700)
        if path.parent.stat().st_mode & 0o777 != 0o700:
            raise OSError("private_parent_mode_not_enforced")
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.stem}-",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temp_path: Path | None = Path(temp_name)
    replaced = False
    descriptor_owned = True
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor_owned = False
            handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        temp_path = None
        replaced = True
        path.chmod(0o600)
        if path.stat().st_mode & 0o777 != 0o600:
            raise OSError("private_file_mode_not_enforced")
        directory_descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except Exception:
        if descriptor_owned:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if replaced:
            try:
                if path.is_file() and path.stat().st_mode & 0o077:
                    path.unlink()
            except OSError:
                pass
        raise
    finally:
        if temp_path is not None and temp_path.is_file():
            temp_path.unlink(missing_ok=True)


def _write_voice_audition_private(job_dir: Path, payload: dict[str, object]) -> None:
    path = _voice_audition_private_path(job_dir)
    _write_private_json(path, payload, private_parent=True)


def _clear_voice_audition_private_selection(job_dir: Path) -> None:
    private_payload = _load_voice_audition_private(job_dir)
    changed = False
    for key in ("selected_callback_token", "selected_candidate_key"):
        if str(private_payload.get(key) or "").strip():
            private_payload[key] = ""
            changed = True
    if not changed:
        return
    private_payload["updated_at"] = _now_iso()
    _write_voice_audition_private(job_dir, private_payload)


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


def _voice_candidate_gender(row: dict[str, object]) -> str:
    tags = {
        _normalize_tag(item)
        for item in list(row.get("tags") or [])
        if _normalize_tag(item)
    }
    for gender in ("male", "female", "nonbinary", "neutral"):
        if gender in tags or f"gender_{gender}" in tags:
            return gender
    return ""


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


def _rebalance_voice_rows_for_gender_diversity(
    *,
    source_rows: list[dict[str, object]],
    selected_rows: list[dict[str, object]],
    book_language: str,
    exclude_keys: set[str],
    exclude_identity_keys: set[str],
    prefer_nonpremium: bool,
    require_language_match: bool,
    limit: int,
    frontload_count: int,
) -> tuple[list[dict[str, object]], bool]:
    if limit <= 1 or len(selected_rows) <= 1:
        return selected_rows, False
    target_prefix_count = max(2, min(frontload_count, limit, len(selected_rows)))
    prefix_rows = selected_rows[:target_prefix_count]
    selected_genders = []
    for row in prefix_rows:
        gender = _voice_candidate_gender(row)
        if gender in {"male", "female"}:
            selected_genders.append(gender)
    if not selected_genders or len(set(selected_genders)) != 1:
        return selected_rows, False
    dominant_gender = selected_genders[0]
    alternate_gender = "male" if dominant_gender == "female" else "female"
    selected_keys = {
        str(row.get("preset_key") or "").strip()
        for row in selected_rows
        if str(row.get("preset_key") or "").strip()
    }
    selected_identity_keys: set[str] = set()
    for row in selected_rows:
        selected_identity_keys.update(_voice_candidate_identity_keys(row))
    alternate_row: dict[str, object] = {}
    for row in selected_rows[1:]:
        if _voice_candidate_gender(row) == alternate_gender:
            alternate_row = dict(row)
            break
    for row in source_rows:
        if alternate_row:
            break
        preset_key = str(row.get("preset_key") or "").strip()
        if not preset_key or preset_key in exclude_keys or preset_key in selected_keys:
            continue
        identity_keys = _voice_candidate_identity_keys(row)
        if identity_keys and identity_keys.intersection(exclude_identity_keys | selected_identity_keys):
            continue
        if not _voice_candidate_allowed_for_audition(row):
            continue
        if prefer_nonpremium and _voice_candidate_has_tag(row, "premium"):
            continue
        if _voice_candidate_gender(row) != alternate_gender:
            continue
        if require_language_match and not _voice_language_matches(
            book_language,
            str(row.get("language") or ""),
            _split_languages(row.get("supported_languages") or row.get("language")),
        ):
            continue
        alternate_row = dict(row)
        break
    if not alternate_row:
        return selected_rows, False
    diversified: list[dict[str, object]] = [selected_rows[0]]
    alternate_inserted = False
    alternate_identities = _voice_candidate_identity_keys(alternate_row)
    alternate_key = str(alternate_row.get("preset_key") or "").strip()
    for row in selected_rows[1:]:
        row_key = str(row.get("preset_key") or "").strip()
        if row_key and row_key == alternate_key:
            continue
        row_identities = _voice_candidate_identity_keys(row)
        if row_identities and row_identities.intersection(alternate_identities):
            continue
        if not alternate_inserted and len(diversified) < target_prefix_count:
            diversified.append(alternate_row)
            alternate_inserted = True
        diversified.append(row)
    if not alternate_inserted and len(diversified) < limit:
        diversified.insert(min(1, len(diversified)), alternate_row)
    return diversified[:limit], True


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
            structure_path=str(dict(item).get("structure_path") or "").strip(),
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
    active_sample_hashes: set[str] = set()
    for row in current_pending_batch_raw:
        identity_keys = _voice_candidate_identity_keys(row)
        if identity_keys and identity_keys.intersection(dismissed_identity_keys | active_identity_keys):
            continue
        sample_sha256 = str(row.get("sample_sha256") or "").strip()
        if sample_sha256 and sample_sha256 in active_sample_hashes:
            continue
        current_pending_batch.append(row)
        active_identity_keys.update(identity_keys)
        if sample_sha256:
            active_sample_hashes.add(sample_sha256)
    pending_still_active = [
        str(row.get("preset_key") or "").strip()
        for row in current_pending_batch
        if isinstance(row, dict) and str(row.get("preset_key") or "").strip()
    ]
    stored_book_profile = dict(current_selection.get("book_profile") or {})
    stored_author_gender_signal = str(stored_book_profile.get("author_gender_signal") or "").strip().lower()
    refreshed_author_gender_signal = str(profile.get("author_gender_signal") or "").strip().lower()
    refresh_pending_batch_for_author_gender_mismatch = (
        str(current_selection.get("status") or "").strip() == "waiting_user_choice"
        and bool(current_pending_batch)
        and refreshed_author_gender_signal in {"male", "female"}
        and any(
            _voice_candidate_gender(row) not in {"", refreshed_author_gender_signal}
            for row in current_pending_batch
            if isinstance(row, dict)
        )
    )
    refresh_pending_batch_for_author_gender_signal = (
        str(current_selection.get("status") or "").strip() == "waiting_user_choice"
        and bool(current_pending_batch)
        and bool(refreshed_author_gender_signal)
        and refreshed_author_gender_signal != stored_author_gender_signal
    )
    if refresh_pending_batch_for_author_gender_signal or refresh_pending_batch_for_author_gender_mismatch:
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
    author_gender_match_only_batch_used = False
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
        nonlocal author_gender_match_only_batch_used
        author_gender_match_only_batch_used = False
        if not author_gender_signal:
            selected_rows = _pick_pending_rows(
                source_rows,
                exclude_keys=exclude_keys,
                exclude_identity_keys=exclude_identity_keys,
                limit=limit,
                require_language_match=require_language_match,
                prefer_nonpremium=prefer_nonpremium,
            )
            selected_rows, _gender_diversity_used = _rebalance_voice_rows_for_gender_diversity(
                source_rows=source_rows,
                selected_rows=selected_rows,
                book_language=metadata.language,
                exclude_keys=exclude_keys,
                exclude_identity_keys=exclude_identity_keys,
                prefer_nonpremium=prefer_nonpremium,
                require_language_match=require_language_match,
                limit=limit,
                frontload_count=requested_batch_size,
            )
            return selected_rows
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
            if not _env_bool("EA_AUDIOBOOK_ALLOW_AUTHOR_GENDER_FALLBACK", False):
                author_gender_preference_used = True
                author_gender_match_only_batch_used = True
                return []
            return _pick_pending_rows(
                source_rows,
                exclude_keys=exclude_keys,
                exclude_identity_keys=exclude_identity_keys,
                limit=limit,
                require_language_match=require_language_match,
                prefer_nonpremium=prefer_nonpremium,
            )
        author_gender_preference_used = True
        author_gender_match_only_batch_used = True
        return preferred_rows

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
                    "reason": _public_unmixr_error_reason(exc),
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
    elif refill_pending and underfilled and author_gender_match_only_batch_used:
        underfilled_reason = "voice_catalog_author_gender_underfilled_after_dismissals"
    elif refill_pending and underfilled:
        underfilled_reason = "voice_catalog_underfilled_after_dismissals"
    elif language_fallback_used:
        underfilled_reason = "voice_catalog_language_relaxed_after_dismissals"
    elif underfilled and sample_generation_failures:
        underfilled_reason = "voice_sample_generation_failed"
    elif underfilled and author_gender_match_only_batch_used:
        underfilled_reason = "voice_catalog_author_gender_underfilled"
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
    profile = dict(voice_selection.get("book_profile") or {})
    author_gender_signal = str(profile.get("author_gender_signal") or "").strip().lower()
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
        candidate_gender = _voice_candidate_gender(candidate)
        rows.append(
            {
                "token": token,
                "label": str(candidate.get("label") or "Voice sample").strip(),
                "score": int(candidate.get("score") or 0),
                "matched_tags": list(candidate.get("matched_tags") or []),
                "tags": list(candidate.get("tags") or []),
                "gender": candidate_gender,
                "author_gender_signal": author_gender_signal,
                "author_gender_match": bool(
                    author_gender_signal in {"male", "female"} and candidate_gender == author_gender_signal
                ),
                "voice_selection_reason": str(voice_selection.get("reason") or "").strip(),
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
        "replacement_candidate_keys": pending_keys,
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
    _reset_audiobook_voice_sample_deliveries(job=job, expected_count=len(selected_rows))
    job["status"] = "waiting_voice_selection"
    job["next_action"] = "choose_audiobook_voice"
    job["render_result"] = {
        "status": "waiting_voice_selection",
        "reason": "selected_voice_language_mismatch",
        "voice_selection": reopened_selection,
    }
    job["updated_at"] = _now_iso()
    _write_job(job_dir, job)
    _clear_voice_audition_private_selection(job_dir)
    _write_current_job_receipt_best_effort(job_dir)
    if dismissed_keys and len(selected_rows) < max(1, int(limit or 3)):
        return prepare_audiobook_voice_audition(
            job_dir=job_dir,
            batch_size=max(1, int(limit or 3)),
            refill_pending=True,
        )
    return job


def reopen_audiobook_voice_selection_for_author_gender_mismatch(*, job_dir: Path, limit: int = 3) -> dict[str, object]:
    job = _load_job(job_dir)
    metadata = _metadata_from_job(job)
    provider_payload = dict(job.get("provider") or {})
    current_selection = dict(provider_payload.get("voice_selection") or {})
    author_gender_signal, selected_rows = _author_gender_mismatch_replacement_candidates(
        job_dir=job_dir,
        metadata=metadata,
        voice_selection=current_selection,
        limit=max(1, int(limit or 3)),
        include_current_selected=False,
    )
    if author_gender_signal not in {"male", "female"} or not selected_rows:
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
        "reason": "selected_voice_author_gender_mismatch",
        "pending_candidate_keys": pending_keys,
        "replacement_candidate_keys": pending_keys,
        "pending_batch": selected_rows,
        "selected": {},
        "selected_candidate_key": "",
        "selected_callback_token": "",
        "voice_author_gender_override_by_user": False,
        "raw_voice_ids_exposed": False,
        "sample_text_exposed": False,
        "last_action": {
            "action": "reopen",
            "status": "replacement_ready",
            "reason": "selected_voice_author_gender_mismatch",
            "replacement_count": len(selected_rows),
            "replacement_candidate_keys": pending_keys,
            "author_gender_signal": author_gender_signal,
        },
    }
    provider_payload["voice_selection"] = reopened_selection
    provider_payload["raw_book_text_leaves_ea"] = False
    job["provider"] = provider_payload
    _reset_audiobook_voice_sample_deliveries(job=job, expected_count=len(selected_rows))
    job["status"] = "waiting_voice_selection"
    job["next_action"] = "choose_audiobook_voice"
    job["render_result"] = {
        "status": "waiting_voice_selection",
        "reason": "selected_voice_author_gender_mismatch",
        "voice_selection": reopened_selection,
        "voice_author_gender_mismatch": {
            "author_gender_signal": author_gender_signal,
            "replacement_candidate_count": len(selected_rows),
        },
    }
    job["updated_at"] = _now_iso()
    _write_job(job_dir, job)
    _clear_voice_audition_private_selection(job_dir)
    _write_current_job_receipt_best_effort(job_dir)
    return job


def _audiobook_voice_sample_delivery_summary(
    *,
    expected_count: int,
    sample_receipts: list[dict[str, object]] | tuple[dict[str, object], ...],
) -> dict[str, object]:
    receipts_by_token_sha: dict[str, dict[str, object]] = {}
    receipts_without_token: list[dict[str, object]] = []
    for item in list(sample_receipts or []):
        if not isinstance(item, dict):
            continue
        normalized = dict(item)
        token_sha256 = str(normalized.get("token_sha256") or "").strip()
        if not token_sha256:
            token = str(normalized.get("token") or "").strip()
            if token:
                token_sha256 = _sha256_bytes(token.encode("utf-8"))
        normalized["token_sha256"] = token_sha256
        if token_sha256:
            receipts_by_token_sha[token_sha256] = normalized
        else:
            receipts_without_token.append(normalized)
    receipts = list(receipts_by_token_sha.values()) + receipts_without_token
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
            str(item.get("token_sha256") or "").strip()
            for item in receipts
            if str(item.get("token_sha256") or "").strip()
        ],
        "samples": [
            {
                "token_sha256": str(item.get("token_sha256") or "").strip(),
                "status": str(item.get("status") or "").strip(),
                "media_message_id_sha256": str(item.get("media_message_id_sha256") or "").strip(),
                "button_message_id_sha256": str(item.get("button_message_id_sha256") or "").strip(),
                "button_count": int(item.get("button_count") or 0),
                "buttons_fallback": bool(item.get("buttons_fallback")),
                "control_kind": str(item.get("control_kind") or "").strip(),
            }
            for item in receipts
            if str(item.get("token_sha256") or "").strip()
        ],
        "updated_at": _now_iso(),
    }


def _reset_audiobook_voice_sample_deliveries(*, job: dict[str, object], expected_count: int) -> None:
    summary = _audiobook_voice_sample_delivery_summary(expected_count=max(int(expected_count or 0), 0), sample_receipts=[])
    for channel_key in ("telegram", "whatsapp"):
        current_channel = job.get(channel_key)
        if current_channel is None and channel_key not in job:
            continue
        channel = dict(current_channel or {})
        channel["voice_sample_delivery"] = dict(summary)
        job[channel_key] = channel


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
    current_samples = audiobook_voice_audition_sample_messages(current_job)
    current_sample_hashes = _audiobook_voice_current_pending_token_hashes(current_job)
    receipt_entries = [dict(item) for item in list(sample_receipts or []) if isinstance(item, dict)]
    telegram = dict(current_job.get("telegram") or {})
    existing_delivery = dict(telegram.get("voice_sample_delivery") or {})
    existing_entries = [dict(item) for item in list(existing_delivery.get("samples") or []) if isinstance(item, dict)]
    if not existing_entries:
        raw_hashes = existing_delivery.get("token_sha256")
        if isinstance(raw_hashes, list):
            candidate_hashes = [str(item or "").strip() for item in raw_hashes]
        else:
            candidate_hashes = [str(raw_hashes or "").strip()]
        fallback_status = str(existing_delivery.get("status") or "").strip()
        fallback_reason = str(existing_delivery.get("reason") or "").strip()
        existing_entries = [
            {
                "token_sha256": token_sha256,
                "status": fallback_status,
                "reason": fallback_reason,
            }
            for token_sha256 in candidate_hashes
            if token_sha256
        ]
    if current_sample_hashes:
        existing_entries = [
            item
            for item in existing_entries
            if str(item.get("token_sha256") or "").strip() in current_sample_hashes
        ]
    expected_count = len(current_sample_hashes) or len(current_samples)
    if expected_count <= 0:
        expected_count = len(receipt_entries) or len(existing_entries)
    summary = _audiobook_voice_sample_delivery_summary(
        expected_count=expected_count,
        sample_receipts=existing_entries + receipt_entries,
    )
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
        render_result = dict(job.get("render_result") or {})
        if isinstance(render_result.get("voice_selection"), dict):
            render_result["voice_selection"] = dict(repaired_selection)
            job["render_result"] = render_result
        job["updated_at"] = _now_iso()
        _write_job(job_dir, job)
        _write_current_job_receipt_best_effort(job_dir)
        voice_selection = repaired_selection
    render_result = dict(job.get("render_result") or {})
    if str(voice_selection.get("status") or "").strip() == "selected_by_user" and isinstance(
        render_result.get("voice_selection"), dict
    ):
        render_voice_selection = dict(render_result.get("voice_selection") or {})
        if render_voice_selection != voice_selection:
            render_result["voice_selection"] = dict(voice_selection)
            job["render_result"] = render_result
            job["updated_at"] = _now_iso()
            _write_job(job_dir, job)
            _write_current_job_receipt_best_effort(job_dir)
    if str(voice_selection.get("status") or "").strip() == "waiting_user_choice":
        return {
            "status": "blocked",
            "reason": "voice_selection_pending",
            "voice_id": "",
            "public": voice_selection,
        }
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


def apply_audiobook_voice_audition_action(
    *, callback_token: str, action: str
) -> dict[str, object]:
    job_dir, _private_payload, _candidate = _find_voice_audition_job_by_token(
        callback_token
    )
    try:
        with _AUDIOBOOK_EXTERNAL_TTS_ENV_LOCK:
            with _exclusive_audiobook_job_lock(job_dir):
                private_payload = _load_voice_audition_private(job_dir)
                candidate = dict(
                    dict(private_payload.get("candidates") or {}).get(callback_token)
                    or {}
                )
                if not candidate:
                    raise RuntimeError("voice_audition_token_not_found")
                return _apply_audiobook_voice_audition_action_locked(
                    job_dir=job_dir,
                    private_payload=private_payload,
                    candidate=candidate,
                    callback_token=callback_token,
                    action=action,
                )
    except _AudiobookLockTimeout:
        current = _load_job(job_dir)
        return {
            **current,
            "status": "voice_selection_in_progress",
            "next_action": "retry_voice_selection_action",
            "voice_selection_action": {
                "status": "render_in_progress",
                "reason": "audiobook_job_lock_timeout",
                "retryable": True,
            },
        }


def _apply_audiobook_voice_audition_action_locked(
    *,
    job_dir: Path,
    private_payload: dict[str, object],
    candidate: dict[str, object],
    callback_token: str,
    action: str,
) -> dict[str, object]:
    normalized_action = _normalize_tag(action)
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
        or str(voice_selection.get("reason") or "").strip() == "selected_voice_author_gender_mismatch"
        or str((job.get("render_result") or {}).get("reason") or "").strip() == "selected_voice_language_mismatch"
        or str((job.get("render_result") or {}).get("reason") or "").strip() == "selected_voice_author_gender_mismatch"
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
        author_gender_signal = _selected_voice_author_gender_signal(
            metadata=_metadata_from_job(job),
            voice_selection=voice_selection,
        )
        selected_gender = _voice_candidate_gender(selected)
        explicit_author_gender_override = bool(voice_selection.get("voice_author_gender_override_by_user")) or bool(
            selected.get("voice_author_gender_override_by_user")
        )
        if (
            str(voice_selection.get("reason") or "").strip() == "selected_voice_author_gender_mismatch"
            or str((job.get("render_result") or {}).get("reason") or "").strip() == "selected_voice_author_gender_mismatch"
        ):
            explicit_author_gender_override = bool(
                author_gender_signal in {"male", "female"}
                and selected_gender in {"male", "female"}
                and selected_gender != author_gender_signal
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
                "voice_author_gender_override_by_user": explicit_author_gender_override,
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
        return _continue_job_locked(job_dir) if unmixr_auto_render_enabled() else job
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


def _audiobook_audio_normalization_filter() -> str:
    return str(
        os.getenv("EA_AUDIOBOOK_AUDIO_NORMALIZATION_FILTER")
        or "dynaudnorm=f=150:g=15,loudnorm=I=-16:TP=-1.5:LRA=11"
    ).strip()


def _audiobook_mastering_contract() -> str:
    payload = {
        "contract_name": "ea.audiobook_final_track_mastering.v2",
        "normalization_enabled": _audio_normalization_enabled(),
        "filter_sha256": _sha256_bytes(
            _audiobook_audio_normalization_filter().encode("utf-8")
        ),
        "scope": "assembled_chapter_or_cinematic_master_only",
        "segment_mastering": False,
    }
    return _sha256_bytes(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def _normalize_rendered_audio_file(path: Path) -> Path:
    if not _audio_normalization_enabled():
        return path
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError("audiobook_audio_normalization_input_missing")
    ffmpeg = shutil.which(str(os.getenv("EA_FFMPEG_BIN") or "ffmpeg").strip() or "ffmpeg")
    if not ffmpeg:
        raise RuntimeError("audiobook_audio_normalization_ffmpeg_missing")
    target = path.with_name(f"{path.stem}.normalized{path.suffix}")
    filter_chain = _audiobook_audio_normalization_filter()
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
        raise RuntimeError("audiobook_audio_normalization_failed")
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


def _audiobook_segment_edge_trim_policy() -> dict[str, object]:
    return {
        "contract_name": "ea.audiobook_provider_segment_edge_trim.v1",
        "enabled": _env_bool("EA_AUDIOBOOK_SEGMENT_EDGE_TRIM_ENABLED", True),
        "audible_threshold": _env_float(
            "EA_AUDIOBOOK_SEGMENT_EDGE_TRIM_AUDIBLE_THRESHOLD",
            0.0015,
            minimum=0.0001,
            maximum=0.05,
        ),
        "minimum_silence_seconds": _env_float(
            "EA_AUDIOBOOK_SEGMENT_EDGE_TRIM_MIN_SILENCE_SECONDS",
            0.18,
            minimum=0.0,
            maximum=2.0,
        ),
        "preserve_head_seconds": _env_float(
            "EA_AUDIOBOOK_SEGMENT_EDGE_TRIM_PRESERVE_HEAD_SECONDS",
            0.08,
            minimum=0.0,
            maximum=0.5,
        ),
        "preserve_tail_seconds": _env_float(
            "EA_AUDIOBOOK_SEGMENT_EDGE_TRIM_PRESERVE_TAIL_SECONDS",
            0.12,
            minimum=0.0,
            maximum=0.75,
        ),
        "maximum_trim_seconds_per_edge": _env_float(
            "EA_AUDIOBOOK_SEGMENT_EDGE_TRIM_MAX_SECONDS_PER_EDGE",
            2.0,
            minimum=0.0,
            maximum=10.0,
        ),
    }


def _audiobook_segment_edge_trim_contract() -> str:
    return _sha256_bytes(
        json.dumps(
            _audiobook_segment_edge_trim_policy(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _trim_provider_wav_edge_silence(path: Path) -> Path:
    """Remove only measured provider padding while retaining speech-edge guards."""
    policy = _audiobook_segment_edge_trim_policy()
    if not bool(policy["enabled"]) or path.suffix.lower() != ".wav":
        return path
    try:
        with wave.open(str(path), "rb") as wav_file:
            params = wav_file.getparams()
            channels = int(wav_file.getnchannels() or 0)
            sample_width = int(wav_file.getsampwidth() or 0)
            frame_rate = int(wav_file.getframerate() or 0)
            frame_count = int(wav_file.getnframes() or 0)
            payload = wav_file.readframes(frame_count)
    except Exception:
        return path
    if (
        channels <= 0
        or sample_width not in {1, 2, 3, 4}
        or frame_rate <= 0
        or frame_count <= 0
    ):
        return path
    stats = _pcm_window_stats(
        payload=payload,
        sample_width=sample_width,
        channels=channels,
        audible_threshold=float(policy["audible_threshold"]),
    )
    first_audible = int(stats.get("first_audible_frame", -1))
    last_audible = int(stats.get("last_audible_frame", -1))
    if first_audible < 0 or last_audible < first_audible:
        return path
    leading_silence_seconds = first_audible / float(frame_rate)
    trailing_silence_seconds = (frame_count - last_audible - 1) / float(frame_rate)
    minimum_silence = float(policy["minimum_silence_seconds"])
    maximum_trim_frames = int(
        float(policy["maximum_trim_seconds_per_edge"]) * frame_rate
    )
    preserve_head_frames = int(float(policy["preserve_head_seconds"]) * frame_rate)
    preserve_tail_frames = int(float(policy["preserve_tail_seconds"]) * frame_rate)
    trim_head_frames = (
        min(max(first_audible - preserve_head_frames, 0), maximum_trim_frames)
        if leading_silence_seconds >= minimum_silence
        else 0
    )
    trim_tail_frames = (
        min(
            max(frame_count - last_audible - 1 - preserve_tail_frames, 0),
            maximum_trim_frames,
        )
        if trailing_silence_seconds >= minimum_silence
        else 0
    )
    if trim_head_frames <= 0 and trim_tail_frames <= 0:
        return path
    start_frame = trim_head_frames
    end_frame = frame_count - trim_tail_frames
    minimum_output_frames = max(1, int(frame_rate * 0.08))
    if end_frame - start_frame < minimum_output_frames:
        return path
    frame_width = channels * sample_width
    trimmed_payload = payload[start_frame * frame_width : end_frame * frame_width]
    temporary = path.with_name(f"{path.stem}.edge-trim{path.suffix}")
    try:
        with wave.open(str(temporary), "wb") as wav_file:
            wav_file.setparams(params)
            wav_file.writeframes(trimmed_payload)
        if temporary.is_file() and temporary.stat().st_size > 0:
            temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
    return path


def _write_provider_audio_file(
    *,
    audio_bytes: bytes,
    content_type: str,
    target_wav: Path,
    normalize: bool = True,
) -> Path:
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
            return _normalize_rendered_audio_file(target_wav) if normalize else target_wav
        return provider_target
    return _normalize_rendered_audio_file(provider_target) if normalize else provider_target


def _write_provider_audio_segment_file(
    *,
    audio_bytes: bytes,
    content_type: str,
    target_wav: Path,
) -> Path:
    """Convert one provider passage without independently mastering it."""
    rendered = _write_provider_audio_file(
        audio_bytes=audio_bytes,
        content_type=content_type,
        target_wav=target_wav,
        normalize=False,
    )
    return _trim_provider_wav_edge_silence(rendered)


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


def _audiobook_scene_pause_seconds() -> float:
    return _env_float("EA_AUDIOBOOK_SCENE_PAUSE_SECONDS", 1.25, minimum=0.0, maximum=5.0)


def _audiobook_batch_paragraphs_with_natural_pauses() -> bool:
    return _env_bool("EA_AUDIOBOOK_BATCH_PARAGRAPHS_WITH_NATURAL_PAUSES", True)


def _audiobook_speaker_pause_seconds() -> float:
    return _env_float("EA_AUDIOBOOK_SPEAKER_PAUSE_SECONDS", 0.22, minimum=0.0, maximum=2.0)


def _explicit_dialogue_paragraph(text: str) -> bool:
    normalized = str(text or "").strip()
    if len(normalized) < 3:
        return False
    if normalized.startswith(_DIALOGUE_DASH_OPENERS):
        return re.fullmatch(r"[-–—\s]+", normalized) is None
    opener = normalized[0]
    if opener not in _DIALOGUE_OPENERS:
        return False
    closing_markers = {
        '"': ('"',),
        "“": ("”",),
        "„": ("“", "”"),
        "«": ("»",),
        "»": ("«",),
        "‹": ("›",),
        "›": ("‹",),
    }.get(opener, ())
    return any(marker in normalized[1:] for marker in closing_markers)


def _speaker_id_from_label(label: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(label or "")).casefold()
    normalized = re.sub(r"[^\w'\-’]+", " ", normalized, flags=re.UNICODE).strip()
    if not normalized:
        return "speaker_unknown"
    return f"speaker_{_sha256_bytes(normalized.encode('utf-8'))[:16]}"


def _scene_performance_rows(
    scene_text: str,
    *,
    max_chars: int,
    dialogue_voice_enabled: bool,
    batch_paragraphs: bool,
    pauses_enabled: bool,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n{2,}", scene_text) if paragraph.strip()]
    for paragraph_index, paragraph in enumerate(paragraphs):
        speaker_role = "dialogue" if dialogue_voice_enabled and _explicit_dialogue_paragraph(paragraph) else "narrator"
        speaker = (
            {
                "speaker_id": "speaker_unknown",
                "speaker_label": "",
                "evidence": {
                    "kind": "unattributed_dialogue",
                    "provenance": "legacy_paragraph_segmentation",
                    "confidence": 0.0,
                    "explicit": False,
                },
            }
            if speaker_role == "dialogue"
            else {
                "speaker_id": "narrator",
                "speaker_label": "Narrator",
                "evidence": {
                    "kind": "narration",
                    "provenance": "segmentation",
                    "confidence": 1.0,
                    "explicit": True,
                },
            }
        )
        for chunk in _semantic_text_chunks(paragraph, max_chars=max_chars):
            if (
                batch_paragraphs
                and rows
                and rows[-1].get("speaker_role") == speaker_role
                and rows[-1].get("speaker_id") == speaker.get("speaker_id")
            ):
                candidate = f"{rows[-1]['text']}\n\n{chunk}"
                if len(candidate) <= max_chars:
                    rows[-1]["text"] = candidate
                    rows[-1]["source_paragraph_end"] = paragraph_index
                    continue
            rows.append(
                {
                    "text": chunk,
                    "speaker_role": speaker_role,
                    "speaker_id": str(speaker.get("speaker_id") or "speaker_unknown"),
                    "speaker_label": str(speaker.get("speaker_label") or ""),
                    "speaker_evidence": dict(speaker.get("evidence") or {}),
                    "source_paragraph_start": paragraph_index,
                    "source_paragraph_end": paragraph_index,
                    "paragraph_break_after": False,
                    "pause_kind": "",
                    "pause_seconds_after": 0.0,
                }
            )
    if not pauses_enabled:
        return rows
    for index, row in enumerate(rows[:-1]):
        next_row = rows[index + 1]
        if row.get("speaker_role") != next_row.get("speaker_role"):
            row["paragraph_break_after"] = _audiobook_speaker_pause_seconds() > 0
            row["pause_kind"] = "speaker"
            row["pause_seconds_after"] = _audiobook_speaker_pause_seconds()
        elif (
            not batch_paragraphs
            and row.get("source_paragraph_end") != next_row.get("source_paragraph_start")
        ):
            row["paragraph_break_after"] = _audiobook_paragraph_pause_seconds() > 0
            row["pause_kind"] = "paragraph"
            row["pause_seconds_after"] = _audiobook_paragraph_pause_seconds()
    return rows


def _write_silence_wav(path: Path, *, seconds: float, sample_rate: int = 44100) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame_count = max(int(float(seconds) * sample_rate), 1)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * frame_count)
    return path


def _chapter_text_segment_rows(
    text: str,
    *,
    max_chars: int,
    dialogue_voice_enabled: bool = False,
) -> tuple[dict[str, object], ...]:
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return ()
    rows: list[dict[str, object]] = []
    pauses_enabled = _audiobook_paragraph_pauses_enabled()
    batch_paragraphs = _audiobook_batch_paragraphs_with_natural_pauses()
    scene_parts = re.split(r"(\n{3,})", normalized)
    source_scene_index = 0
    for part_index in range(0, len(scene_parts), 2):
        scene_text = scene_parts[part_index].strip()
        if not scene_text:
            continue
        separator = scene_parts[part_index + 1] if part_index + 1 < len(scene_parts) else ""
        scene_rows = _scene_performance_rows(
            scene_text,
            max_chars=max_chars,
            dialogue_voice_enabled=dialogue_voice_enabled,
            batch_paragraphs=batch_paragraphs,
            pauses_enabled=pauses_enabled,
        )
        for row in scene_rows:
            row["source_scene_index"] = source_scene_index
        if scene_rows and separator and pauses_enabled:
            scene_rows[-1]["paragraph_break_after"] = _audiobook_scene_pause_seconds() > 0
            scene_rows[-1]["pause_kind"] = "scene"
            scene_rows[-1]["pause_seconds_after"] = _audiobook_scene_pause_seconds()
        rows.extend(scene_rows)
        source_scene_index += 1
    return tuple(rows)


def _semantic_text_chunks(text: str, *, max_chars: int) -> tuple[str, ...]:
    remaining = str(text or "").strip()
    if not remaining:
        return ()
    if max_chars <= 0 or len(remaining) <= max_chars:
        return (remaining,)
    chunks: list[str] = []
    sentence_boundary = re.compile(r"[.!?…]+(?:[\"'”’»›)\]]+)?(?=\s|$)")
    clause_boundary = re.compile(r"[;:](?:[\"'”’»›)\]]+)?(?=\s|$)")
    while len(remaining) > max_chars:
        window = remaining[: max_chars + 1]
        minimum_natural_boundary = max(1, int(max_chars * 0.35))
        split_at = 0
        for match in sentence_boundary.finditer(window):
            if match.end() >= minimum_natural_boundary and match.end() <= max_chars:
                split_at = match.end()
        if not split_at:
            for match in clause_boundary.finditer(window):
                if match.end() >= minimum_natural_boundary and match.end() <= max_chars:
                    split_at = match.end()
        if not split_at:
            split_at = remaining.rfind(" ", 0, max_chars + 1)
        if split_at <= 0:
            split_at = max_chars
        chunk = remaining[:split_at].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return tuple(chunks)


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
        paragraph_chunks = _semantic_text_chunks(paragraph, max_chars=max_chars)
        if len(paragraph_chunks) > 1:
            segments.extend(paragraph_chunks[:-1])
        current = paragraph_chunks[-1] if paragraph_chunks else ""
    if current:
        segments.append(current)
    return tuple(segment for segment in segments if segment)


def _exception_detail(exc: BaseException) -> str:
    detail = getattr(exc, "detail", "")
    if detail:
        return str(detail)
    return str(exc)


def _redact_render_sensitive_detail(value: object, *voice_ids: str) -> str:
    redacted = str(value or "")
    for voice_id in voice_ids:
        normalized = str(voice_id or "").strip()
        if normalized:
            redacted = redacted.replace(normalized, "[voice_id_redacted]")
    return redacted


def _public_unmixr_error_reason(exc: BaseException) -> str:
    """Project provider/library failures to a bounded, source-text-safe code."""
    detail = _exception_detail(exc).strip().lower()
    safe_match = re.search(
        r"unmixr_(?:synthesize|request|tts)_"
        r"(rate_limited|balance_exhausted|input_too_long|authentication_failed|"
        r"access_denied|invalid_request|upstream_unavailable|failed)"
        r"(?::retry_after_(\d{1,7})_seconds)?",
        detail,
    )
    if safe_match:
        reason = f"unmixr_synthesize_{safe_match.group(1)}"
        if safe_match.group(1) == "rate_limited" and safe_match.group(2):
            retry_after = min(max(int(safe_match.group(2)), 0), 604800)
            if retry_after:
                reason = f"{reason}:retry_after_{retry_after}_seconds"
        return reason
    if "unmixr_api_key_missing" in detail:
        return "unmixr_synthesize_authentication_failed"
    if _unmixr_input_too_long_error(detail):
        return "unmixr_synthesize_input_too_long"
    if any(
        marker in detail
        for marker in (
            "balance_exhausted",
            "insufficient api balance",
            "insufficient balance",
            "prebuilt character",
        )
    ):
        return "unmixr_synthesize_balance_exhausted"
    wait_seconds = _provider_wait_seconds_from_text(detail)
    if wait_seconds or any(
        marker in detail for marker in ("rate_limited", "rate limit", "too many requests")
    ):
        reason = "unmixr_synthesize_rate_limited"
        if wait_seconds:
            reason = f"{reason}:retry_after_{min(wait_seconds, 604800)}_seconds"
        return reason
    if any(marker in detail for marker in ("authentication_failed", "unauthorized", "401")):
        return "unmixr_synthesize_authentication_failed"
    if any(marker in detail for marker in ("access_denied", "forbidden", "403")):
        return "unmixr_synthesize_access_denied"
    if any(marker in detail for marker in ("invalid_request", "unprocessable", "400", "422")):
        return "unmixr_synthesize_invalid_request"
    if any(
        marker in detail
        for marker in (
            "upstream_unavailable",
            "upstream_unreachable",
            "audio_fetch_failed",
            "no_audio_url",
            "temporar",
            "timeout",
            "502",
            "503",
            "504",
        )
    ):
        return "unmixr_synthesize_upstream_unavailable"
    return "unmixr_synthesize_failed"


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
    if any(
        marker in detail
        for marker in (
            "input too long",
            "limit your input",
            "input_too_long",
            "authentication_failed",
            "access_denied",
            "invalid_request",
            "balance_exhausted",
        )
    ):
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


def _unmixr_input_too_long_error(detail: object) -> bool:
    normalized = str(detail or "").strip().lower()
    if not normalized:
        return False
    return any(
        marker in normalized
        for marker in (
            "input too long",
            "limit your input",
            "request entity too large",
            "payload too large",
            "input_too_long",
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
                pronunciation_dict=unmixr_pronunciation_dict(),
            )
            return audio_bytes, content_type, errors
        except Exception as exc:
            errors.append(f"attempt_{attempt}:{_public_unmixr_error_reason(exc)}")
            if attempt >= attempts or not _unmixr_retryable_error(exc):
                raise
            if base_sleep > 0:
                time.sleep(base_sleep * attempt)
    raise RuntimeError("unmixr_retry_exhausted")


def _segment_render_fingerprint(
    *,
    text: str,
    voice_id: str,
    speaker_role: str,
    render_language: str,
    speaker_id: str = "",
) -> str:
    payload = {
        "provider_contract": "unmixr_short_tts",
        "text_sha256": _sha256_bytes(text.encode("utf-8")),
        "voice_id_sha256": _sha256_bytes(voice_id.encode("utf-8")),
        "speaker_role": speaker_role,
        "speaker_id": speaker_id,
        "render_language": _normalize_language(render_language),
        "speaking_rate": unmixr_speaking_rate(),
        "speaking_pitch": unmixr_speaking_pitch(),
        "speaking_volume": unmixr_speaking_volume(),
        "pronunciation_dictionary_sha256": _sha256_bytes(
            str(os.getenv("EA_AUDIOBOOK_UNMIXR_PRONUNCIATION_DICT_JSON") or "").encode("utf-8")
        ),
        "provider_segment_edge_trim_contract": _audiobook_segment_edge_trim_contract(),
        "narration_plan_contract": NARRATION_PLAN_CONTRACT_NAME,
    }
    return _sha256_bytes(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def _chapter_master_render_signature(
    *,
    chapter: EpubChapter,
    segment_rows: tuple[dict[str, object], ...],
    narrator_voice_id: str,
    speaker_cast: dict[str, object],
    render_language: str,
) -> str:
    payload = {
        "contract_name": "ea.audiobook_chapter_master_signature.v1",
        "chapter_index": chapter.index,
        "source_href": chapter.source_href,
        "source_text_sha256": str(chapter.sha256 or ""),
        "mastering_contract": _audiobook_mastering_contract(),
        "passages": [
            {
                "render_fingerprint": _segment_render_fingerprint(
                    text=str(row.get("text") or ""),
                    voice_id=_speaker_voice_id(
                        row,
                        narrator_voice_id=narrator_voice_id,
                        speaker_cast=speaker_cast,
                    ),
                    speaker_role=str(row.get("speaker_role") or "narrator"),
                    speaker_id=str(row.get("speaker_id") or ""),
                    render_language=render_language,
                ),
                "pause_kind_after": str(
                    row.get("boundary_kind_after") or row.get("pause_kind") or ""
                ),
                "pause_seconds_after": float(row.get("pause_seconds_after") or 0.0),
            }
            for row in segment_rows
        ],
    }
    return _sha256_bytes(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


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


def _configured_dialogue_voice_selection(job_dir: Path) -> dict[str, str]:
    configured = str(os.getenv("EA_AUDIOBOOK_UNMIXR_DIALOGUE_VOICE_ID") or "").strip()
    if configured:
        return {"voice_id": configured, "source": "explicit_operator_environment"}
    try:
        job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    except Exception:
        return {}
    provider = dict(job.get("provider") or {}) if isinstance(job, dict) else {}
    selection = dict(provider.get("dialogue_voice_selection") or {})
    status = _normalize_tag(selection.get("status"))
    approved = (
        selection.get("approved_by_user") is True
        or status in {"approved", "selected_by_user", "accepted_by_user"}
    )
    if not approved:
        return {}
    private_payload = _load_voice_audition_private(job_dir)
    token = str(
        selection.get("selected_callback_token")
        or private_payload.get("selected_dialogue_callback_token")
        or ""
    ).strip()
    candidates = dict(private_payload.get("candidates") or {})
    candidate = dict(candidates.get(token) or {}) if token else {}
    voice_id = str(candidate.get("voice_id") or "").strip()
    if not token or not voice_id:
        return {}
    recorded_hash = str(candidate.get("voice_id_sha256") or "").strip()
    if recorded_hash and recorded_hash != _sha256_bytes(voice_id.encode("utf-8")):
        return {}
    return {
        "voice_id": voice_id,
        "source": "approved_private_dialogue_voice_selection",
    }


def _public_dialogue_voice_selection(
    selection: dict[str, str],
    *,
    narrator_voice_id: str,
) -> dict[str, object]:
    voice_id = str(selection.get("voice_id") or "").strip()
    active = bool(voice_id and voice_id != narrator_voice_id)
    return {
        "status": "active" if active else "narrator_fallback",
        "source": str(selection.get("source") or "none"),
        "distinct_from_narrator": active,
        "voice_id_sha256": _sha256_bytes(voice_id.encode("utf-8")) if active else "",
        "raw_voice_id_exposed": False,
        "identity_or_gender_inferred": False,
    }


def _split_trait_components(value: str) -> tuple[str, ...]:
    normalized = _normalize_tag(value)
    if not normalized:
        return ()
    parts: list[str] = []
    for part in re.split(r"[_\-]+|\s+", normalized):
        cleaned = str(part or "").strip()
        if cleaned and cleaned not in parts:
            parts.append(cleaned)
    return tuple(parts)


def _speaker_trait_value(kind: str, value: object) -> str:
    normalized = _normalize_tag(value)
    if kind == "gender_presentation":
        aliases = {
            "f": "female",
            "feminine": "female",
            "girl": "female",
            "woman": "female",
            "m": "male",
            "man": "male",
            "masculine": "male",
            "boy": "male",
            "nb": "nonbinary",
            "non_binary": "nonbinary",
            "gender_neutral": "neutral",
            "unspecified": "unknown",
        }
        return aliases.get(normalized, normalized)
    if kind == "approximate_age":
        try:
            years = int(float(str(value).strip()))
        except Exception:
            years = -1
        if years < 0:
            range_years = [
                int(item)
                for item in re.findall(r"\d{1,3}", str(value or ""))[:2]
            ]
            if range_years:
                years = int(sum(range_years) / len(range_years))
        if years >= 0:
            if years < 13:
                return "child"
            if years < 20:
                return "teen"
            if years < 35:
                return "young_adult"
            if years < 55:
                return "adult"
            if years < 70:
                return "mature"
            return "senior"
        aliases = {
            "kid": "child",
            "young": "young_adult",
            "youngadult": "young_adult",
            "mature_adult": "mature",
            "younger_adult": "young_adult",
            "middle_age": "mature",
            "middle_aged": "mature",
            "older_adult": "senior",
            "older_adults": "senior",
            "older": "senior",
            "elderly": "senior",
            "old": "senior",
        }
        return aliases.get(normalized, normalized)
    if kind == "language":
        return _normalize_language(value)
    return normalized


def _speaker_trait_evidence(
    kind: str,
    value: object,
    *,
    default_provenance: str,
) -> dict[str, object] | None:
    raw_value = value
    explicit = True
    provenance = default_provenance
    confidence = 1.0
    if isinstance(value, dict):
        raw_value = value.get("value")
        explicit = value.get("explicit") is not False
        provenance = str(value.get("provenance") or value.get("source") or default_provenance).strip()
        try:
            confidence = float(value.get("confidence", 1.0))
        except Exception:
            confidence = 1.0
    if not explicit:
        return None
    raw_values = (
        list(raw_value)
        if isinstance(raw_value, (list, tuple, set))
        else [raw_value]
    )
    normalized_values = [
        _speaker_trait_value(kind, item)
        for item in raw_values
        if _speaker_trait_value(kind, item)
        not in {"", "unknown", "unspecified", "none"}
    ]
    normalized_values = list(dict.fromkeys(normalized_values))
    if not normalized_values:
        return None
    return {
        "value": normalized_values[0],
        "values": normalized_values,
        "provenance": provenance[:120],
        "confidence": round(min(max(confidence, 0.0), 1.0), 3),
        "explicit": True,
        "ranking_hint_only": True,
    }


_SPEAKER_TRAIT_KIND_ALIASES = {
    "gender": "gender_presentation",
    "age": "approximate_age",
    "age_range": "approximate_age",
    "age_band": "approximate_age",
    "locale": "language",
    "spoken_language": "language",
    "native_language": "language",
    "dialect": "accent",
    "cultural_background": "ethnicity",
    "cultural_or_ethnic_background": "ethnicity",
    "cultural_identity": "ethnicity",
    "ethnic_background": "ethnicity",
    "character_role": "role",
    "performance_style": "style",
}
_SINGULAR_SPEAKER_TRAIT_KINDS = {
    "gender_presentation",
    "approximate_age",
    "accent",
    "ethnicity",
}


def _canonical_speaker_trait_kind(kind: object) -> str:
    normalized = _normalize_tag(kind)
    return _SPEAKER_TRAIT_KIND_ALIASES.get(normalized, normalized)


def _merge_speaker_trait_observations(
    observations: list[dict[str, object]],
) -> tuple[dict[str, dict[str, object]], list[str]]:
    merged: dict[str, dict[str, object]] = {}
    ambiguous: set[str] = set()
    for observation in observations:
        for raw_kind, raw_evidence in observation.items():
            kind = _canonical_speaker_trait_kind(raw_kind)
            if not kind or kind in ambiguous:
                continue
            evidence = _speaker_trait_evidence(
                kind,
                raw_evidence,
                default_provenance="private_exact_span_planner",
            )
            if evidence is None:
                continue
            evidence_values = {
                str(value or "").strip()
                for value in list(evidence.get("values") or [evidence.get("value")])
                if str(value or "").strip()
            }
            if not evidence_values:
                continue
            if kind in _SINGULAR_SPEAKER_TRAIT_KINDS and len(evidence_values) != 1:
                merged.pop(kind, None)
                ambiguous.add(kind)
                continue
            existing = merged.get(kind)
            if existing is None:
                merged[kind] = evidence
                continue
            existing_values = {
                str(value or "").strip()
                for value in list(existing.get("values") or [existing.get("value")])
                if str(value or "").strip()
            }
            if kind in _SINGULAR_SPEAKER_TRAIT_KINDS and existing_values != evidence_values:
                merged.pop(kind, None)
                ambiguous.add(kind)
                continue
            if existing_values == evidence_values:
                merged[kind] = sorted(
                    (existing, evidence),
                    key=lambda row: (
                        -float(row.get("confidence") or 0.0),
                        str(row.get("provenance") or ""),
                    ),
                )[0]
                continue
            combined_values = sorted(existing_values | evidence_values)
            combined_provenance = "+".join(
                sorted(
                    {
                        str(existing.get("provenance") or ""),
                        str(evidence.get("provenance") or ""),
                    }
                    - {""}
                )
            )[:120]
            merged[kind] = {
                "value": combined_values[0],
                "values": combined_values,
                "provenance": combined_provenance or "combined_explicit_evidence",
                "confidence": round(
                    min(
                        float(existing.get("confidence") or 0.0),
                        float(evidence.get("confidence") or 0.0),
                    ),
                    3,
                ),
                "explicit": True,
                "ranking_hint_only": True,
            }
    return merged, sorted(ambiguous)


def _speaker_profile_rows(job_dir: Path) -> tuple[dict[str, object], ...]:
    try:
        job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    except Exception:
        job = {}
    provider = dict(job.get("provider") or {}) if isinstance(job, dict) else {}
    narration = dict(job.get("narration") or {}) if isinstance(job, dict) else {}
    configured_sources: list[tuple[object, str]] = [
        (job.get("speaker_profiles") if isinstance(job, dict) else None, "private_job_profile"),
        (narration.get("speaker_profiles"), "private_narration_profile"),
        (provider.get("speaker_profiles"), "private_provider_profile"),
    ]
    raw_env = str(os.getenv("EA_AUDIOBOOK_SPEAKER_PROFILES_JSON") or "").strip()
    if raw_env:
        try:
            configured_sources.append((json.loads(raw_env), "explicit_operator_environment"))
        except Exception:
            pass

    rows: list[dict[str, object]] = []
    by_speaker_id: dict[str, int] = {}

    def _iter_rows(value: object) -> list[dict[str, object]]:
        if isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            return [
                {"speaker_label": key, **dict(item)}
                for key, item in value.items()
                if isinstance(item, dict)
            ]
        return []

    for raw_profiles, source in configured_sources:
        for raw_profile in _iter_rows(raw_profiles):
            label = str(
                raw_profile.get("speaker_label")
                or raw_profile.get("speaker")
                or raw_profile.get("name")
                or ""
            ).strip()
            explicit_id = str(raw_profile.get("speaker_id") or "").strip()
            speaker_id = explicit_id if explicit_id.startswith("speaker_") else _speaker_id_from_label(label)
            if speaker_id == "speaker_unknown" and not label and explicit_id != "speaker_unknown":
                continue
            aliases = [label]
            aliases.extend(
                str(item or "").strip()
                for item in list(raw_profile.get("aliases") or [])
                if str(item or "").strip()
            )
            alias_ids = sorted({_speaker_id_from_label(alias) for alias in aliases if alias})
            if explicit_id == "speaker_unknown":
                alias_ids.append("speaker_unknown")
            raw_traits = dict(raw_profile.get("traits") or {})
            profile_approval_status = _normalize_tag(
                raw_profile.get("trait_approval_status")
                or raw_profile.get("profile_approval_status")
            )
            profile_traits_approved = (
                source == "explicit_operator_environment"
                or raw_profile.get("traits_approved_by_user") is True
                or raw_profile.get("casting_traits_approved_by_user") is True
                or raw_profile.get("approved_by_user") is True
                or profile_approval_status
                in {"approved", "selected_by_user", "accepted_by_user"}
            )
            trait_aliases = {
                "gender_presentation": ("gender_presentation", "gender"),
                "approximate_age": (
                    "approximate_age",
                    "age_band",
                    "age_range",
                    "age",
                ),
                "language": (
                    "language",
                    "locale",
                    "spoken_language",
                    "native_language",
                ),
                "accent": ("accent", "dialect"),
                "ethnicity": (
                    "ethnicity",
                    "ethnic_background",
                    "cultural_background",
                    "cultural_or_ethnic_background",
                    "cultural_identity",
                ),
                "role": ("role", "character_role"),
                "style": ("style", "performance_style"),
            }
            traits: dict[str, dict[str, object]] = {}
            for kind, keys in trait_aliases.items():
                raw_value: object = None
                for key in keys:
                    if key in raw_traits:
                        raw_value = raw_traits[key]
                        break
                    if key in raw_profile:
                        raw_value = raw_profile[key]
                        break
                evidence_approval_status = (
                    _normalize_tag(raw_value.get("approval_status") or raw_value.get("status"))
                    if isinstance(raw_value, dict)
                    else ""
                )
                trait_approved = profile_traits_approved or (
                    isinstance(raw_value, dict)
                    and (
                        raw_value.get("approved_by_user") is True
                        or evidence_approval_status
                        in {"approved", "selected_by_user", "accepted_by_user"}
                    )
                )
                if not trait_approved:
                    continue
                evidence = _speaker_trait_evidence(
                    kind,
                    raw_value,
                    default_provenance=source,
                )
                if evidence is not None:
                    traits[kind] = evidence
            normalized = {
                "speaker_id": speaker_id,
                "speaker_label": label,
                "alias_ids": alias_ids,
                "traits": traits,
                "voice_selection": dict(
                    raw_profile.get("voice_selection")
                    or raw_profile.get("selection")
                    or {}
                ),
                "profile_provenance": source,
            }
            existing_index = by_speaker_id.get(speaker_id)
            if existing_index is None:
                by_speaker_id[speaker_id] = len(rows)
                rows.append(normalized)
            else:
                merged = dict(rows[existing_index])
                merged["traits"] = {**dict(merged.get("traits") or {}), **traits}
                merged["alias_ids"] = sorted(
                    set(list(merged.get("alias_ids") or []) + alias_ids)
                )
                if normalized["voice_selection"]:
                    merged["voice_selection"] = normalized["voice_selection"]
                rows[existing_index] = merged

    raw_selections = provider.get("speaker_voice_selections")
    for selection_row in _iter_rows(raw_selections):
        label = str(
            selection_row.get("speaker_label")
            or selection_row.get("speaker")
            or selection_row.get("name")
            or ""
        ).strip()
        explicit_id = str(selection_row.get("speaker_id") or "").strip()
        speaker_id = explicit_id if explicit_id.startswith("speaker_") else _speaker_id_from_label(label)
        selection = dict(selection_row.get("voice_selection") or selection_row)
        existing_index = by_speaker_id.get(speaker_id)
        if existing_index is None:
            by_speaker_id[speaker_id] = len(rows)
            rows.append(
                {
                    "speaker_id": speaker_id,
                    "speaker_label": label,
                    "alias_ids": [_speaker_id_from_label(label)] if label else [speaker_id],
                    "traits": {},
                    "voice_selection": selection,
                    "profile_provenance": "approved_private_speaker_selection",
                }
            )
        else:
            rows[existing_index]["voice_selection"] = selection
    return tuple(rows)


def _profile_for_speaker(
    profiles: tuple[dict[str, object], ...],
    *,
    speaker_id: str,
) -> dict[str, object]:
    for profile in profiles:
        if speaker_id == str(profile.get("speaker_id") or ""):
            return dict(profile)
        if speaker_id in list(profile.get("alias_ids") or []):
            return dict(profile)
    return {
        "speaker_id": speaker_id,
        "speaker_label": "",
        "alias_ids": [speaker_id],
        "traits": {},
        "voice_selection": {},
        "profile_provenance": "unknown_neutral_fallback",
    }


def _approved_speaker_voice(
    *,
    profile: dict[str, object],
    private_candidates: dict[str, object],
) -> dict[str, object]:
    selection = dict(profile.get("voice_selection") or {})
    status = _normalize_tag(selection.get("status"))
    if not (
        selection.get("approved_by_user") is True
        or status in {"approved", "selected_by_user", "accepted_by_user"}
    ):
        return {}
    token = str(selection.get("selected_callback_token") or selection.get("callback_token") or "").strip()
    candidate = dict(private_candidates.get(token) or {}) if token else {}
    voice_id = str(candidate.get("voice_id") or "").strip()
    if (
        not voice_id
        and str(profile.get("profile_provenance") or "")
        == "explicit_operator_environment"
    ):
        # Environment configuration is already private operator state. Ordinary
        # job manifests must resolve raw IDs through a private callback token.
        voice_id = str(selection.get("voice_id") or "").strip()
    if not voice_id:
        return {}
    recorded_hash = str(selection.get("voice_id_sha256") or candidate.get("voice_id_sha256") or "").strip()
    if recorded_hash and recorded_hash != _sha256_bytes(voice_id.encode("utf-8")):
        return {}
    public_candidate = dict(candidate.get("public") or {})
    return {
        "voice_id": voice_id,
        "label": str(selection.get("label") or public_candidate.get("label") or "Approved voice").strip(),
        "source": "approved_private_speaker_selection",
        "language": str(
            selection.get("language") or public_candidate.get("language") or ""
        ).strip(),
        "supported_languages": list(
            selection.get("supported_languages")
            or public_candidate.get("supported_languages")
            or []
        ),
    }


def _voice_tag_match(tags: set[str], *, kind: str, value: str) -> bool:
    normalized = _speaker_trait_value(kind, value)
    if not normalized:
        return False
    components = _split_trait_components(normalized)
    candidates = {normalized, f"{kind}_{normalized}", *components}
    candidates.update(f"{kind}_{part}" for part in components)
    if kind == "gender_presentation":
        candidates.add(f"gender_{normalized}")
    elif kind == "approximate_age":
        candidates.update({f"age_{normalized}", normalized.replace("_", "")})
        candidates.update(
            f"age_{part}"
            for part in components
            if part and part not in {"age", "child", "teen", "young", "adult", "mature", "senior"}
        )
    elif kind == "accent":
        candidates.add(f"accent_{normalized}")
        candidates.update(f"accent_{part}" for part in components)
    elif kind == "ethnicity":
        candidates.update({f"ethnicity_{normalized}", f"cultural_background_{normalized}"})
        candidates.update(
            f"ethnicity_{part}"
            for part in components
            if part and part not in {"other", "unknown"}
        )
        candidates.update(
            f"cultural_background_{part}"
            for part in components
            if part and part not in {"other", "unknown"}
        )
    return bool(tags.intersection(candidates))


def _speaker_voice_candidate_score(
    *,
    preset: VoicePreset,
    profile: dict[str, object],
    render_language: str,
) -> tuple[int, list[str], list[str]]:
    score = _voice_language_score(render_language, preset.language, preset.supported_languages)
    tags = set(_split_tags(preset.tags))
    # Prefer voices the provider explicitly exposes for narrated long-form
    # performance. A generic speech voice may still be used when no better
    # eligible voice exists, but it must not beat an equally compatible
    # audiobook voice merely because both share one demographic hint.
    if "audiobook_voices" in tags:
        score += 14
    if "audiobook" in tags or "audiobooks" in tags:
        score += 10
    if "narration" in tags:
        score += 8
    if tags.intersection({"storytelling", "dialogue", "character", "expressive"}):
        score += 4
    matched: list[str] = []
    unmatched: list[str] = []
    weights = {
        "gender_presentation": 30,
        "approximate_age": 18,
        "language": 18,
        "accent": 14,
        "ethnicity": 14,
        "role": 8,
        "style": 8,
    }
    traits = dict(profile.get("traits") or {})
    for kind, evidence in traits.items():
        if not isinstance(evidence, dict):
            continue
        values = [
            str(item or "").strip()
            for item in list(evidence.get("values") or [evidence.get("value")])
            if str(item or "").strip()
        ]
        confidence = float(evidence.get("confidence") or 0.0)
        if kind == "language":
            matched_trait = any(
                _voice_language_matches(
                    value,
                    preset.language,
                    preset.supported_languages,
                )
                for value in values
            )
        else:
            matched_trait = any(
                _voice_tag_match(tags, kind=kind, value=value)
                for value in values
            )
        if matched_trait:
            matched.append(kind)
            score += int(weights.get(kind, 5) * confidence)
        else:
            unmatched.append(kind)
            if kind == "gender_presentation" and tags.intersection({"male", "female", "nonbinary"}):
                score -= int(20 * confidence)
            elif kind == "approximate_age" and tags.intersection(
                {"child", "teen", "young_adult", "adult", "mature", "senior", "elderly"}
            ):
                score -= int(8 * confidence)
    if not traits:
        if "neutral" in tags:
            score += 12
            matched.append("unknown_neutral_fallback")
        elif tags.intersection({"dialogue", "character", "expressive", "storytelling"}):
            score += 4
    if preset.default:
        score += 1
    return score, sorted(set(matched)), sorted(set(unmatched))


def _resolve_audiobook_speaker_cast(
    *,
    job_dir: Path,
    segment_rows: tuple[dict[str, object], ...],
    speaker_rows: tuple[dict[str, object], ...] = (),
    narrator_voice_id: str,
    render_language: str,
    default_dialogue_selection: dict[str, str] | None = None,
) -> dict[str, object]:
    dialogue_speakers: dict[str, dict[str, object]] = {}
    for row in (*speaker_rows, *segment_rows):
        speaker_role = str(row.get("speaker_role") or row.get("role") or "dialogue")
        if speaker_role != "dialogue" or str(row.get("speaker_id") or "") == "narrator":
            continue
        speaker_id = str(row.get("speaker_id") or "speaker_unknown")
        row_evidence = dict(row.get("speaker_evidence") or {})
        if not row_evidence:
            row_evidence = {
                "kind": str(row.get("attribution_kind") or "planner_attribution"),
                "provenance": str(row.get("attribution_provenance") or "private_exact_span_planner"),
                "confidence": float(row.get("attribution_confidence") or 0.0),
                "explicit": bool(row.get("attribution_explicit", False)),
            }
        row_traits = dict(row.get("traits") or row.get("speaker_traits") or {})
        existing_speaker = dialogue_speakers.get(speaker_id)
        if existing_speaker is None:
            dialogue_speakers[speaker_id] = {
                "speaker_id": speaker_id,
                "speaker_label": str(row.get("speaker_label") or ""),
                "evidence": row_evidence,
                "trait_observations": [row_traits],
            }
        else:
            observations = list(existing_speaker.get("trait_observations") or [])
            observations.append(row_traits)
            existing_speaker["trait_observations"] = observations
            if not str(existing_speaker.get("speaker_label") or ""):
                existing_speaker["speaker_label"] = str(row.get("speaker_label") or "")
            if float(row_evidence.get("confidence") or 0.0) > float(
                dict(existing_speaker.get("evidence") or {}).get("confidence") or 0.0
            ):
                existing_speaker["evidence"] = row_evidence
    for speaker in dialogue_speakers.values():
        speaker["span_count"] = 0
        speaker["explicit_span_count"] = 0
        speaker["max_attribution_confidence"] = 0.0
    for row in segment_rows:
        if str(row.get("speaker_role") or "narrator") != "dialogue":
            continue
        speaker_id = str(row.get("speaker_id") or "speaker_unknown")
        speaker = dialogue_speakers.get(speaker_id)
        if speaker is None:
            continue
        speaker["span_count"] = int(speaker.get("span_count") or 0) + 1
        confidence = float(row.get("attribution_confidence") or 0.0)
        speaker["max_attribution_confidence"] = max(
            float(speaker.get("max_attribution_confidence") or 0.0),
            confidence,
        )
        if str(row.get("attribution_provenance") or "").startswith("explicit_"):
            speaker["explicit_span_count"] = int(
                speaker.get("explicit_span_count") or 0
            ) + 1
    if not dialogue_speakers:
        public = {
            "status": "not_required",
            "speaker_count": 0,
            "cast": [],
            "cast_map_sha256": "",
            "raw_voice_ids_exposed": False,
        }
        return {"status": "not_required", "private": {}, "public": public, "cast_map_sha256": ""}

    profiles = _speaker_profile_rows(job_dir)
    private_payload = _load_voice_audition_private(job_dir)
    private_candidates = dict(private_payload.get("candidates") or {})
    presets = load_unmixr_voice_presets(target_count=max(len(dialogue_speakers) + 1, 3))
    compatible_presets = [
        preset
        for preset in presets
        if preset.voice_id != narrator_voice_id
        and _voice_language_matches(render_language, preset.language, preset.supported_languages)
    ]
    compatible_presets.sort(key=lambda preset: (preset.preset_key, preset.label, preset.voice_id))
    preset_by_voice_id = {preset.voice_id: preset for preset in presets}
    generic_selection = dict(default_dialogue_selection or {})
    generic_voice_id = str(generic_selection.get("voice_id") or "").strip()
    if generic_voice_id == narrator_voice_id:
        generic_voice_id = ""
    used_voice_ids: set[str] = set()
    automatic_voice_ids: set[str] = set()
    private_cast: dict[str, dict[str, object]] = {}
    public_cast: list[dict[str, object]] = []
    book_seed = ""
    try:
        job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
        book_seed = str(dict(job.get("metadata") or {}).get("source_sha256") or job.get("job_id") or "")
    except Exception:
        book_seed = str(job_dir.name)

    automatic_voice_cap = _audiobook_max_automatic_speaker_voices()
    neutral_presets = [
        preset
        for preset in compatible_presets
        if "neutral" in set(_split_tags(preset.tags))
    ]
    neutral_candidates = neutral_presets or compatible_presets
    neutral_candidates.sort(
        key=lambda preset: (
            _sha256_bytes(
                f"{book_seed}|neutral-anchor|{preset.preset_key}".encode("utf-8")
            ),
            preset.preset_key,
        )
    )
    neutral_anchor = neutral_candidates[0] if neutral_candidates else None
    bounded_sharing_expected = len(dialogue_speakers) > automatic_voice_cap
    if bounded_sharing_expected and neutral_anchor is not None:
        automatic_voice_ids.add(neutral_anchor.voice_id)

    ordered_speaker_ids = sorted(
        dialogue_speakers,
        key=lambda value: (
            -int(dialogue_speakers[value].get("explicit_span_count") or 0),
            -int(dialogue_speakers[value].get("span_count") or 0),
            -float(
                dialogue_speakers[value].get("max_attribution_confidence") or 0.0
            ),
            value,
        ),
    )
    for speaker_id in ordered_speaker_ids:
        speaker = dialogue_speakers[speaker_id]
        profile = _profile_for_speaker(profiles, speaker_id=speaker_id)
        detected_label = str(speaker.get("speaker_label") or "").strip()
        if (
            str(profile.get("profile_provenance") or "") == "unknown_neutral_fallback"
            and detected_label
        ):
            profile = _profile_for_speaker(
                profiles,
                speaker_id=_speaker_id_from_label(detected_label),
            )
        if not str(profile.get("speaker_label") or "").strip():
            profile["speaker_label"] = detected_label
        planner_traits, ambiguous_trait_kinds = _merge_speaker_trait_observations(
            [
                dict(observation)
                for observation in list(speaker.get("trait_observations") or [])
                if isinstance(observation, dict)
            ]
        )
        approved_profile_traits = dict(profile.get("traits") or {})
        if planner_traits:
            profile["traits"] = {
                **planner_traits,
                **approved_profile_traits,
            }
        ambiguous_trait_kinds = [
            kind for kind in ambiguous_trait_kinds if kind not in approved_profile_traits
        ]
        approved = _approved_speaker_voice(
            profile=profile,
            private_candidates=private_candidates,
        )
        if not approved and generic_voice_id:
            preset = preset_by_voice_id.get(generic_voice_id)
            approved = {
                "voice_id": generic_voice_id,
                "label": preset.label if preset is not None else "Approved dialogue voice",
                "source": str(generic_selection.get("source") or "approved_dialogue_default"),
            }
        selected_preset: VoicePreset | None = None
        matched_traits: list[str] = []
        unmatched_traits: list[str] = []
        selection_source = ""
        voice_id = str(approved.get("voice_id") or "").strip()
        voice_label = str(approved.get("label") or "").strip()
        if voice_id:
            selection_source = str(approved.get("source") or "approved_private_speaker_selection")
            selected_preset = preset_by_voice_id.get(voice_id)
            if selected_preset is not None:
                approved_language_compatible = _voice_language_matches(
                    render_language,
                    selected_preset.language,
                    selected_preset.supported_languages,
                )
            else:
                approved_language = str(approved.get("language") or "").strip()
                approved_supported_languages = tuple(
                    str(value or "").strip()
                    for value in list(approved.get("supported_languages") or [])
                    if str(value or "").strip()
                )
                approved_language_compatible = bool(
                    approved_language or approved_supported_languages
                ) and _voice_language_matches(
                    render_language,
                    approved_language,
                    approved_supported_languages,
                )
            if not approved_language_compatible:
                public = {
                    "status": "blocked",
                    "reason": (
                        "speaker_approved_voice_language_incompatible_or_unverified"
                    ),
                    "speaker_count": len(dialogue_speakers),
                    "resolved_speaker_count": len(private_cast),
                    "cast": public_cast,
                    "raw_voice_ids_exposed": False,
                }
                return {
                    "status": "blocked",
                    "reason": public["reason"],
                    "private": private_cast,
                    "public": public,
                    "cast_map_sha256": "",
                }
            if selected_preset is not None and not voice_label:
                voice_label = selected_preset.label
        else:
            if not compatible_presets:
                public = {
                    "status": "blocked",
                    "reason": "speaker_voice_catalog_requires_distinct_language_compatible_voice",
                    "speaker_count": len(dialogue_speakers),
                    "resolved_speaker_count": len(private_cast),
                    "cast": public_cast,
                    "raw_voice_ids_exposed": False,
                }
                return {
                    "status": "blocked",
                    "reason": public["reason"],
                    "private": private_cast,
                    "public": public,
                    "cast_map_sha256": "",
                }
            candidate_rows: list[tuple[int, int, str, VoicePreset, list[str], list[str]]] = []
            for preset in compatible_presets:
                score, matched, unmatched = _speaker_voice_candidate_score(
                    preset=preset,
                    profile=profile,
                    render_language=render_language,
                )
                reuse_penalty = 1 if preset.voice_id in used_voice_ids else 0
                stable_tie = _sha256_bytes(
                    f"{book_seed}|{speaker_id}|{preset.preset_key}".encode("utf-8")
                )
                candidate_rows.append(
                    (-score, reuse_penalty, stable_tie, preset, matched, unmatched)
                )
            candidate_rows.sort(key=lambda item: (item[0], item[1], item[2], item[3].preset_key))
            _negative_score, _reuse, _stable, selected_preset, matched_traits, unmatched_traits = candidate_rows[0]
            if (
                selected_preset.voice_id not in automatic_voice_ids
                and len(automatic_voice_ids) >= automatic_voice_cap
                and neutral_anchor is not None
            ):
                selected_preset = neutral_anchor
                _score, matched_traits, unmatched_traits = _speaker_voice_candidate_score(
                    preset=selected_preset,
                    profile=profile,
                    render_language=render_language,
                )
                selection_source = "deterministic_shared_minor_speaker_fallback"
            else:
                selection_source = "deterministic_evidence_ranked_catalog"
            voice_id = selected_preset.voice_id
            voice_label = selected_preset.label
            automatic_voice_ids.add(voice_id)
        if not voice_id or voice_id == narrator_voice_id:
            public = {
                "status": "blocked",
                "reason": "speaker_voice_must_be_distinct_from_narrator",
                "speaker_count": len(dialogue_speakers),
                "resolved_speaker_count": len(private_cast),
                "cast": public_cast,
                "raw_voice_ids_exposed": False,
            }
            return {
                "status": "blocked",
                "reason": public["reason"],
                "private": private_cast,
                "public": public,
                "cast_map_sha256": "",
            }
        if selected_preset is not None and not matched_traits and not unmatched_traits:
            _score, matched_traits, unmatched_traits = _speaker_voice_candidate_score(
                preset=selected_preset,
                profile=profile,
                render_language=render_language,
            )
        used_voice_ids.add(voice_id)
        traits = dict(profile.get("traits") or {})
        trait_confidences = [
            float(evidence.get("confidence") or 0.0)
            for evidence in traits.values()
            if isinstance(evidence, dict)
        ]
        evidence_confidence = (
            round(sum(trait_confidences) / len(trait_confidences), 3)
            if trait_confidences
            else 0.0
        )
        private_entry = {
            "speaker_id": speaker_id,
            "speaker_label": str(profile.get("speaker_label") or speaker.get("speaker_label") or ""),
            "speaker_detection_evidence": dict(speaker.get("evidence") or {}),
            "traits": traits,
            "voice_id": voice_id,
            "voice_id_sha256": _sha256_bytes(voice_id.encode("utf-8")),
            "voice_label": voice_label,
            "voice_catalog_source": (
                selected_preset.source
                if selected_preset is not None
                else str(approved.get("source") or selection_source)
            ),
            "render_language_compatible": True,
            "selection_source": selection_source,
            "matched_trait_kinds": matched_traits,
            "unmatched_trait_kinds": unmatched_traits,
            "ambiguous_trait_kinds": ambiguous_trait_kinds,
            "evidence_confidence": evidence_confidence,
            "traits_are_ranking_hints_only": True,
            "identity_asserted": False,
        }
        private_cast[speaker_id] = private_entry
        public_cast.append(
            {
                "speaker_id": speaker_id,
                "speaker_label_sha256": (
                    _sha256_bytes(private_entry["speaker_label"].encode("utf-8"))
                    if private_entry["speaker_label"]
                    else ""
                ),
                "voice_id_sha256": private_entry["voice_id_sha256"],
                "voice_label": _safe_public_voice_label(
                    voice_label,
                    narrator_voice_id,
                    voice_id,
                ),
                "selection_source": selection_source,
                "matched_trait_kinds": matched_traits,
                "unmatched_trait_kinds": unmatched_traits,
                "ambiguous_trait_kinds": ambiguous_trait_kinds,
                "trait_evidence_confidence": evidence_confidence,
                "unknown_neutral_fallback": not bool(traits),
                "raw_voice_id_exposed": False,
                "identity_asserted": False,
            }
        )

    return _speaker_cast_result_from_private_entries(
        private_cast,
        narrator_voice_id=narrator_voice_id,
        reused_private_snapshot=False,
    )


def _speaker_voice_id(
    row: dict[str, object],
    *,
    narrator_voice_id: str,
    speaker_cast: dict[str, object],
) -> str:
    if str(row.get("speaker_role") or "narrator") != "dialogue":
        return narrator_voice_id
    private_cast = dict(speaker_cast.get("private") or {})
    entry = dict(
        private_cast.get(str(row.get("speaker_id") or "speaker_unknown"))
        or private_cast.get("speaker_unknown")
        or {}
    )
    return str(entry.get("voice_id") or "").strip()


def _speaker_cast_private_voice_ids(speaker_cast: dict[str, object]) -> tuple[str, ...]:
    values = {
        str(dict(entry).get("voice_id") or "").strip()
        for entry in dict(speaker_cast.get("private") or {}).values()
        if isinstance(entry, dict)
    }
    return tuple(sorted(value for value in values if value))


def _speaker_cast_effective_inputs_sha256(
    job_dir: Path,
    *,
    default_dialogue_selection: dict[str, str] | None = None,
) -> str:
    """Bind snapshots to approved casting inputs without binding catalog churn."""
    private_payload = _load_voice_audition_private(job_dir)
    private_candidates = dict(private_payload.get("candidates") or {})
    effective_profiles: list[dict[str, object]] = []
    for profile in _speaker_profile_rows(job_dir):
        selection = dict(profile.get("voice_selection") or {})
        selection_status = _normalize_tag(selection.get("status"))
        selection_approved = (
            selection.get("approved_by_user") is True
            or selection_status
            in {"approved", "selected_by_user", "accepted_by_user"}
        )
        token = str(
            selection.get("selected_callback_token")
            or selection.get("callback_token")
            or ""
        ).strip() if selection_approved else ""
        candidate = dict(private_candidates.get(token) or {}) if token else {}
        candidate_voice_id = str(candidate.get("voice_id") or "").strip()
        if (
            not candidate_voice_id
            and selection_approved
            and str(profile.get("profile_provenance") or "")
            == "explicit_operator_environment"
        ):
            candidate_voice_id = str(selection.get("voice_id") or "").strip()
        traits = dict(profile.get("traits") or {})
        if not traits and not selection_approved:
            continue
        public_candidate = dict(candidate.get("public") or {})
        effective_profiles.append(
            {
                "speaker_id": str(profile.get("speaker_id") or ""),
                "alias_ids": sorted(
                    str(value)
                    for value in list(profile.get("alias_ids") or [])
                    if str(value)
                ),
                "profile_provenance": str(
                    profile.get("profile_provenance") or ""
                ),
                "traits": traits,
                "selection_approved": selection_approved,
                "selection_status": selection_status,
                "callback_token_sha256": (
                    _sha256_bytes(token.encode("utf-8")) if token else ""
                ),
                "voice_id_sha256": (
                    _sha256_bytes(candidate_voice_id.encode("utf-8"))
                    if candidate_voice_id
                    else ""
                ),
                "language": str(
                    selection.get("language")
                    or public_candidate.get("language")
                    or ""
                ).strip()
                if selection_approved
                else "",
                "supported_languages": (
                    sorted(
                        str(value).strip()
                        for value in list(
                            selection.get("supported_languages")
                            or public_candidate.get("supported_languages")
                            or []
                        )
                        if str(value).strip()
                    )
                    if selection_approved
                    else []
                ),
                "voice_label_sha256": (
                    _sha256_bytes(
                        str(
                            selection.get("label")
                            or public_candidate.get("label")
                            or ""
                        ).encode("utf-8")
                    )
                    if selection_approved
                    and str(
                        selection.get("label")
                        or public_candidate.get("label")
                        or ""
                    )
                    else ""
                ),
            }
        )
    generic_selection = dict(
        default_dialogue_selection
        if default_dialogue_selection is not None
        else _configured_dialogue_voice_selection(job_dir)
    )
    generic_voice_id = str(generic_selection.get("voice_id") or "").strip()
    payload = {
        "profiles": sorted(
            effective_profiles,
            key=lambda row: (
                str(row.get("speaker_id") or ""),
                str(row.get("profile_provenance") or ""),
            ),
        ),
        "default_dialogue_selection": {
            "source": str(generic_selection.get("source") or ""),
            "voice_id_sha256": (
                _sha256_bytes(generic_voice_id.encode("utf-8"))
                if generic_voice_id
                else ""
            ),
            "language": str(generic_selection.get("language") or "").strip(),
            "supported_languages": sorted(
                str(value).strip()
                for value in list(generic_selection.get("supported_languages") or [])
                if str(value).strip()
            ),
        },
    }
    return _sha256_bytes(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def _speaker_cast_snapshot_path(
    job_dir: Path,
    narration_plan: dict[str, object],
    *,
    narrator_voice_id: str,
    render_language: str,
    default_dialogue_selection: dict[str, str] | None = None,
) -> Path:
    binding = {
        "casting_policy": SPEAKER_CAST_POLICY_NAME,
        "source_aggregate_sha256": str(
            narration_plan.get("source_aggregate_sha256") or ""
        ),
        "plan_sha256": str(narration_plan.get("plan_sha256") or ""),
        "narrator_voice_id_sha256": _sha256_bytes(
            narrator_voice_id.encode("utf-8")
        ),
        "render_language": _normalize_language(render_language),
        "automatic_voice_cap": _audiobook_max_automatic_speaker_voices(),
        "sharing_policy": "bounded_neutral_sharing_v1",
        "effective_cast_inputs_sha256": _speaker_cast_effective_inputs_sha256(
            job_dir,
            default_dialogue_selection=default_dialogue_selection,
        ),
    }
    encoded = json.dumps(binding, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return job_dir / "speaker_casts" / f"{_sha256_bytes(encoded)}.json"


def _safe_authenticated_catalog_voice_label(
    label: object,
    *private_voice_ids: str,
) -> str:
    normalized_label = " ".join(str(label or "").split()).strip()
    folded_label = normalized_label.casefold()
    if not normalized_label:
        return "Dialogue voice"
    for voice_id in private_voice_ids:
        normalized_id = str(voice_id or "").strip()
        if normalized_id and normalized_id.casefold() in folded_label:
            return "Dialogue voice"
    return normalized_label[:120]


def _safe_public_voice_label(label: object, *private_voice_ids: str) -> str:
    # Catalog labels can themselves encode a person's name or demographic
    # descriptors. Those values remain available in the private cast snapshot;
    # public receipts expose only a neutral role label and stable hashes.
    del label, private_voice_ids
    return "Dialogue voice"


def _speaker_cast_result_from_private_entries(
    private_cast: dict[str, dict[str, object]],
    *,
    narrator_voice_id: str,
    reused_private_snapshot: bool,
) -> dict[str, object]:
    public_cast: list[dict[str, object]] = []
    used_voice_ids: set[str] = set()
    private_voice_ids = tuple(
        str(entry.get("voice_id") or "").strip()
        for entry in private_cast.values()
        if str(entry.get("voice_id") or "").strip()
    )
    for speaker_id, entry in sorted(private_cast.items()):
        voice_id = str(entry.get("voice_id") or "").strip()
        if not voice_id or voice_id == narrator_voice_id:
            return {}
        recorded_hash = str(entry.get("voice_id_sha256") or "").strip()
        voice_hash = _sha256_bytes(voice_id.encode("utf-8"))
        if recorded_hash and recorded_hash != voice_hash:
            return {}
        entry["voice_id_sha256"] = voice_hash
        used_voice_ids.add(voice_id)
        speaker_label = str(entry.get("speaker_label") or "")
        public_cast.append(
            {
                "speaker_id": speaker_id,
                "speaker_label_sha256": (
                    _sha256_bytes(speaker_label.encode("utf-8"))
                    if speaker_label
                    else ""
                ),
                "voice_id_sha256": voice_hash,
                "voice_label": _safe_public_voice_label(
                    entry.get("voice_label"),
                    narrator_voice_id,
                    *private_voice_ids,
                ),
                "selection_source": str(entry.get("selection_source") or ""),
                "matched_trait_kinds": sorted(
                    {
                        str(value)
                        for value in list(entry.get("matched_trait_kinds") or [])
                        if str(value)
                    }
                ),
                "unmatched_trait_kinds": sorted(
                    {
                        str(value)
                        for value in list(entry.get("unmatched_trait_kinds") or [])
                        if str(value)
                    }
                ),
                "ambiguous_trait_kinds": sorted(
                    {
                        str(value)
                        for value in list(entry.get("ambiguous_trait_kinds") or [])
                        if str(value)
                    }
                ),
                "trait_evidence_confidence": float(
                    entry.get("evidence_confidence") or 0.0
                ),
                "unknown_neutral_fallback": not bool(entry.get("traits")),
                "raw_voice_id_exposed": False,
                "identity_asserted": False,
            }
        )
    fingerprint_rows = [
        {
            "speaker_id": speaker_id,
            "voice_id_sha256": str(entry.get("voice_id_sha256") or ""),
            "selection_source": str(entry.get("selection_source") or ""),
        }
        for speaker_id, entry in sorted(private_cast.items())
    ]
    cast_map_sha256 = _sha256_bytes(
        json.dumps(fingerprint_rows, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    )
    automatic_entries = [
        entry
        for entry in private_cast.values()
        if str(entry.get("selection_source") or "").startswith("deterministic_")
    ]
    automatic_voice_hashes = {
        str(entry.get("voice_id_sha256") or "")
        for entry in automatic_entries
        if str(entry.get("voice_id_sha256") or "")
    }
    automatic_voice_counts: dict[str, int] = {}
    for entry in automatic_entries:
        voice_hash = str(entry.get("voice_id_sha256") or "")
        if voice_hash:
            automatic_voice_counts[voice_hash] = automatic_voice_counts.get(voice_hash, 0) + 1
    automatic_shared_speaker_count = sum(
        max(count - 1, 0) for count in automatic_voice_counts.values()
    )
    public = {
        "status": "ready",
        "casting_policy": SPEAKER_CAST_POLICY_NAME,
        "speaker_count": len(private_cast),
        "resolved_speaker_count": len(private_cast),
        "distinct_dialogue_voice_count": len(used_voice_ids),
        "narrator_voice_excluded": narrator_voice_id not in used_voice_ids,
        "cast_map_sha256": cast_map_sha256,
        "cast": public_cast,
        "raw_voice_ids_exposed": False,
        "trait_values_exposed": False,
        "traits_are_ranking_hints_only": True,
        "identity_or_demographics_claimed": False,
        "trait_hints_used": any(
            bool(row.get("matched_trait_kinds") or row.get("unmatched_trait_kinds"))
            for row in public_cast
        ),
        "reused_private_snapshot": reused_private_snapshot,
        "snapshot_status": "reused" if reused_private_snapshot else "created",
        "automatic_voice_cap": _audiobook_max_automatic_speaker_voices(),
        "automatic_distinct_voice_count": len(automatic_voice_hashes),
        "automatic_shared_speaker_count": automatic_shared_speaker_count,
        "automatic_sharing_used": automatic_shared_speaker_count > 0,
        "sharing_policy": "bounded_neutral_sharing_v1",
    }
    return {
        "status": "ready",
        "private": private_cast,
        "public": public,
        "cast_map_sha256": cast_map_sha256,
    }


def _load_private_speaker_cast_snapshot(
    *,
    job_dir: Path,
    narration_plan: dict[str, object],
    narrator_voice_id: str,
    render_language: str,
    default_dialogue_selection: dict[str, str] | None = None,
) -> dict[str, object]:
    effective_cast_inputs_sha256 = _speaker_cast_effective_inputs_sha256(
        job_dir,
        default_dialogue_selection=default_dialogue_selection,
    )
    path = _speaker_cast_snapshot_path(
        job_dir,
        narration_plan,
        narrator_voice_id=narrator_voice_id,
        render_language=render_language,
        default_dialogue_selection=default_dialogue_selection,
    )
    if not path.exists():
        return {}

    def _invalid() -> dict[str, object]:
        return {
            "status": "blocked",
            "reason": "speaker_cast_snapshot_invalid",
            "private": {},
            "public": {
                "status": "blocked",
                "reason": "speaker_cast_snapshot_invalid",
                "raw_voice_ids_exposed": False,
                "trait_values_exposed": False,
                "identity_or_demographics_claimed": False,
                "snapshot_status": "invalid",
            },
            "cast_map_sha256": "",
        }

    try:
        path_stat = path.lstat()
        parent_stat = path.parent.stat()
        job_stat = job_dir.stat()
        if (
            path.is_symlink()
            or not path.is_file()
            or path_stat.st_mode & 0o077
            or parent_stat.st_mode & 0o077
            or path_stat.st_uid != job_stat.st_uid
            or parent_stat.st_uid != job_stat.st_uid
        ):
            return _invalid()
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _invalid()
    if not isinstance(payload, dict):
        return _invalid()
    if payload.get("contract_name") != SPEAKER_CAST_SNAPSHOT_CONTRACT_NAME:
        return _invalid()
    if payload.get("casting_policy") != SPEAKER_CAST_POLICY_NAME:
        return _invalid()
    if str(payload.get("plan_sha256") or "") != str(
        narration_plan.get("plan_sha256") or ""
    ):
        return _invalid()
    if str(payload.get("source_aggregate_sha256") or "") != str(
        narration_plan.get("source_aggregate_sha256") or ""
    ):
        return _invalid()
    if str(payload.get("narrator_voice_id_sha256") or "") != _sha256_bytes(
        narrator_voice_id.encode("utf-8")
    ):
        return _invalid()
    if _normalize_language(payload.get("render_language")) != _normalize_language(
        render_language
    ):
        return _invalid()
    if int(payload.get("automatic_voice_cap") or 0) != _audiobook_max_automatic_speaker_voices():
        return _invalid()
    if str(payload.get("sharing_policy") or "") != "bounded_neutral_sharing_v1":
        return _invalid()
    if str(payload.get("effective_cast_inputs_sha256") or "") != (
        effective_cast_inputs_sha256
    ):
        return _invalid()
    required_speaker_ids = {
        str(row.get("speaker_id") or "speaker_unknown")
        for row in list(narration_plan.get("passages") or [])
        if isinstance(row, dict)
        and str(row.get("speaker_role") or "narrator") == "dialogue"
    }
    raw_entries = dict(payload.get("entries") or {})
    if not required_speaker_ids or set(raw_entries) != required_speaker_ids:
        return _invalid()
    private_cast = {
        speaker_id: dict(raw_entries[speaker_id])
        for speaker_id in sorted(required_speaker_ids)
        if isinstance(raw_entries.get(speaker_id), dict)
    }
    if set(private_cast) != required_speaker_ids:
        return _invalid()
    rebuilt = _speaker_cast_result_from_private_entries(
        private_cast,
        narrator_voice_id=narrator_voice_id,
        reused_private_snapshot=True,
    )
    if not rebuilt or str(payload.get("cast_map_sha256") or "") != str(
        rebuilt.get("cast_map_sha256") or ""
    ):
        return _invalid()
    return rebuilt


def _write_private_speaker_cast_snapshot(
    *,
    job_dir: Path,
    narration_plan: dict[str, object],
    narrator_voice_id: str,
    render_language: str,
    speaker_cast: dict[str, object],
    default_dialogue_selection: dict[str, str] | None = None,
) -> None:
    if speaker_cast.get("status") != "ready":
        return
    entries = {
        str(speaker_id): dict(entry)
        for speaker_id, entry in dict(speaker_cast.get("private") or {}).items()
        if isinstance(entry, dict)
    }
    if not entries:
        return
    payload = {
        "contract_name": SPEAKER_CAST_SNAPSHOT_CONTRACT_NAME,
        "casting_policy": SPEAKER_CAST_POLICY_NAME,
        "plan_sha256": str(narration_plan.get("plan_sha256") or ""),
        "source_aggregate_sha256": str(
            narration_plan.get("source_aggregate_sha256") or ""
        ),
        "narrator_voice_id_sha256": _sha256_bytes(
            narrator_voice_id.encode("utf-8")
        ),
        "render_language": _normalize_language(render_language),
        "cast_map_sha256": str(speaker_cast.get("cast_map_sha256") or ""),
        "automatic_voice_cap": _audiobook_max_automatic_speaker_voices(),
        "sharing_policy": "bounded_neutral_sharing_v1",
        "effective_cast_inputs_sha256": _speaker_cast_effective_inputs_sha256(
            job_dir,
            default_dialogue_selection=default_dialogue_selection,
        ),
        "entries": entries,
        "raw_voice_ids_embedded": True,
        "private_payload": True,
    }
    _write_private_json(
        _speaker_cast_snapshot_path(
            job_dir,
            narration_plan,
            narrator_voice_id=narrator_voice_id,
            render_language=render_language,
            default_dialogue_selection=default_dialogue_selection,
        ),
        payload,
        private_parent=True,
    )


def _resolve_speaker_cast_for_narration_plan(
    *,
    job_dir: Path,
    narration_plan: dict[str, object],
    narrator_voice_id: str,
    render_language: str,
    default_dialogue_selection: dict[str, str] | None = None,
) -> dict[str, object]:
    persisted = _load_private_speaker_cast_snapshot(
        job_dir=job_dir,
        narration_plan=narration_plan,
        narrator_voice_id=narrator_voice_id,
        render_language=render_language,
        default_dialogue_selection=default_dialogue_selection,
    )
    if persisted:
        return persisted
    passages = tuple(
        dict(row)
        for row in list(narration_plan.get("passages") or [])
        if isinstance(row, dict)
    )
    raw_speakers = narration_plan.get("speakers") or []
    if isinstance(raw_speakers, dict):
        speakers = tuple(
            {"speaker_id": key, **dict(row)}
            for key, row in raw_speakers.items()
            if isinstance(row, dict)
        )
    else:
        speakers = tuple(
            dict(row)
            for row in list(raw_speakers)
            if isinstance(row, dict)
        )
    resolved = _resolve_audiobook_speaker_cast(
        job_dir=job_dir,
        segment_rows=passages,
        speaker_rows=speakers,
        narrator_voice_id=narrator_voice_id,
        render_language=render_language,
        default_dialogue_selection=default_dialogue_selection,
    )
    try:
        _write_private_speaker_cast_snapshot(
            job_dir=job_dir,
            narration_plan=narration_plan,
            narrator_voice_id=narrator_voice_id,
            render_language=render_language,
            speaker_cast=resolved,
            default_dialogue_selection=default_dialogue_selection,
        )
    except (OSError, RuntimeError, ValueError):
        return {
            "status": "blocked",
            "reason": "speaker_cast_snapshot_write_failed",
            "private": {},
            "public": {
                "status": "blocked",
                "reason": "speaker_cast_snapshot_write_failed",
                "raw_voice_ids_exposed": False,
                "trait_values_exposed": False,
                "identity_or_demographics_claimed": False,
                "snapshot_status": "write_failed",
            },
            "cast_map_sha256": "",
        }
    return resolved


def _cinematic_performance_rows(
    *,
    chapter_inputs: tuple[tuple[EpubChapter, str], ...],
    max_chars: int,
    dialogue_voice_enabled: bool,
) -> tuple[dict[str, object], ...]:
    populated = [(chapter, text) for chapter, text in chapter_inputs if str(text or "").strip()]
    rows: list[dict[str, object]] = []
    for chapter_position, (chapter, text) in enumerate(populated):
        chapter_rows = [
            {
                **row,
                "source_chapter_index": chapter.index,
                "source_href": chapter.source_href,
            }
            for row in _chapter_text_segment_rows(
                text,
                max_chars=max_chars,
                dialogue_voice_enabled=dialogue_voice_enabled,
            )
        ]
        if chapter_rows and chapter_position < len(populated) - 1:
            chapter_rows[-1]["paragraph_break_after"] = _audiobook_scene_pause_seconds() > 0
            chapter_rows[-1]["pause_kind"] = "scene"
            chapter_rows[-1]["pause_seconds_after"] = _audiobook_scene_pause_seconds()
        rows.extend(chapter_rows)
    return tuple(rows)


def _canonical_narration_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _write_private_narration_plan(
    *,
    job_dir: Path,
    chapter_inputs: tuple[tuple[EpubChapter, str], ...],
    segment_rows: tuple[dict[str, object], ...],
    narrator_voice_id: str,
    dialogue_voice_id: str,
    render_language: str,
    render_mode: str,
    speaker_cast: dict[str, object] | None = None,
    planner_plan: dict[str, object] | None = None,
) -> dict[str, object]:
    exact_plan = dict(planner_plan or {})
    source_integrity_issues: list[str] = [
        str(value)
        for value in list(exact_plan.get("source_integrity_issues") or [])
        if str(value)
    ]
    actual_text_hashes: dict[int, str] = {}
    source_provenance: dict[int, dict[str, object]] = {}
    chapter_root = (job_dir / "chapters").resolve()
    for chapter, text in chapter_inputs:
        actual_text_hash = _sha256_bytes(text.encode("utf-8"))
        actual_text_hashes[chapter.index] = actual_text_hash
        expected_text_hash = str(chapter.sha256 or "").strip().lower()
        if re.fullmatch(r"[0-9a-f]{64}", expected_text_hash) and expected_text_hash != actual_text_hash:
            source_integrity_issues.append(f"chapter_text_hash_mismatch:{chapter.index}")
        structure_name = str(chapter.structure_path or "").strip()
        if not structure_name:
            source_provenance[chapter.index] = {"status": "legacy_structure_unverified"}
            continue
        try:
            structure_path = (chapter_root / structure_name).resolve()
            structure_path.relative_to(chapter_root)
        except (OSError, ValueError):
            source_integrity_issues.append(f"chapter_structure_path_invalid:{chapter.index}")
            source_provenance[chapter.index] = {"status": "invalid"}
            continue
        try:
            source_document_bytes = structure_path.read_bytes()
            source_document = json.loads(source_document_bytes.decode("utf-8"))
        except Exception:
            source_integrity_issues.append(f"chapter_structure_unreadable:{chapter.index}")
            source_provenance[chapter.index] = {"status": "invalid"}
            continue
        if not isinstance(source_document, dict):
            source_integrity_issues.append(f"chapter_structure_contract_mismatch:{chapter.index}")
            source_provenance[chapter.index] = {"status": "invalid"}
            continue
        if source_document.get("contract_name") != SOURCE_DOCUMENT_CONTRACT_NAME:
            source_integrity_issues.append(f"chapter_structure_contract_mismatch:{chapter.index}")
        if str(source_document.get("source_href") or "").strip() != str(chapter.source_href or "").strip():
            source_integrity_issues.append(f"chapter_structure_source_href_mismatch:{chapter.index}")
        if str(source_document.get("extracted_text_sha256") or "").strip() != actual_text_hash:
            source_integrity_issues.append(f"chapter_structure_text_hash_mismatch:{chapter.index}")
        source_provenance[chapter.index] = {
            "status": "verified",
            "source_html_sha256": str(source_document.get("source_html_sha256") or "").strip(),
            "source_document_sha256": _sha256_bytes(source_document_bytes),
        }

    source_canonical = _canonical_narration_text(" ".join(text for _, text in chapter_inputs))
    planned_canonical = _canonical_narration_text(" ".join(str(row.get("text") or "") for row in segment_rows))
    source_canonical_sha256 = _sha256_bytes(source_canonical.encode("utf-8"))
    planned_canonical_sha256 = _sha256_bytes(planned_canonical.encode("utf-8"))
    coverage_matches = (
        bool(exact_plan.get("coverage_complete"))
        if exact_plan
        else source_canonical_sha256 == planned_canonical_sha256
    )
    narrator_voice_hash = (
        _sha256_bytes(narrator_voice_id.encode("utf-8")) if narrator_voice_id else ""
    )
    normalized_speaker_cast = dict(speaker_cast or {})
    if not normalized_speaker_cast and dialogue_voice_id and dialogue_voice_id != narrator_voice_id:
        normalized_speaker_cast = {
            "status": "ready",
            "private": {
                "speaker_unknown": {
                    "speaker_id": "speaker_unknown",
                    "speaker_label": "",
                    "voice_id": dialogue_voice_id,
                    "voice_id_sha256": _sha256_bytes(dialogue_voice_id.encode("utf-8")),
                    "voice_label": "Approved dialogue voice",
                    "selection_source": "legacy_approved_dialogue_default",
                    "traits": {},
                    "identity_asserted": False,
                }
            },
            "public": {
                "status": "ready",
                "speaker_count": 1,
                "raw_voice_ids_exposed": False,
            },
        }
    private_speaker_cast = dict(normalized_speaker_cast.get("private") or {})
    chapter_coverage: list[dict[str, object]] = []
    exact_chapter_coverage = {
        int(row.get("chapter_index") or 0): dict(row)
        for row in list(exact_plan.get("chapter_coverage") or [])
        if isinstance(row, dict) and int(row.get("chapter_index") or 0) > 0
    }
    for chapter, text in chapter_inputs:
        exact_chapter = exact_chapter_coverage.get(chapter.index)
        if exact_chapter is not None:
            exact_reconstruction = bool(exact_chapter.get("exact_reconstruction"))
            exact_hash = str(exact_chapter.get("source_text_sha256") or "")
            chapter_coverage.append(
                {
                    "chapter_index": chapter.index,
                    "status": "complete" if exact_reconstruction else "mismatch",
                    "source_canonical_sha256": exact_hash,
                    "planned_canonical_sha256": exact_hash if exact_reconstruction else "",
                    "exact_span_reconstruction": exact_reconstruction,
                }
            )
            if not exact_reconstruction:
                source_integrity_issues.append(
                    f"chapter_exact_reconstruction_mismatch:{chapter.index}"
                )
            continue
        chapter_rows = [
            row
            for row in segment_rows
            if int(row.get("source_chapter_index") or 0) == chapter.index
        ]
        if chapter_rows:
            source_chapter_canonical = _canonical_narration_text(text)
            planned_chapter_canonical = _canonical_narration_text(
                " ".join(str(row.get("text") or "") for row in chapter_rows)
            )
            chapter_matches = source_chapter_canonical == planned_chapter_canonical
            chapter_coverage.append(
                {
                    "chapter_index": chapter.index,
                    "status": "complete" if chapter_matches else "mismatch",
                    "source_canonical_sha256": _sha256_bytes(source_chapter_canonical.encode("utf-8")),
                    "planned_canonical_sha256": _sha256_bytes(planned_chapter_canonical.encode("utf-8")),
                }
            )
            if not chapter_matches:
                source_integrity_issues.append(f"chapter_plan_coverage_mismatch:{chapter.index}")
        else:
            covered_by_combined_passage = any(
                chapter.index in list(row.get("source_chapter_indexes") or [])
                for row in segment_rows
            )
            chapter_coverage.append(
                {
                    "chapter_index": chapter.index,
                    "status": "covered_by_combined_legacy_passage" if covered_by_combined_passage else "missing",
                    "source_canonical_sha256": _sha256_bytes(
                        _canonical_narration_text(text).encode("utf-8")
                    ),
                    "planned_canonical_sha256": "",
                }
            )
            if not covered_by_combined_passage:
                source_integrity_issues.append(f"chapter_plan_coverage_missing:{chapter.index}")
    passages: list[dict[str, object]] = []
    for passage_index, row in enumerate(segment_rows, start=1):
        speaker_role = str(row.get("speaker_role") or "narrator")
        speaker_id = str(
            row.get("speaker_id")
            or ("speaker_unknown" if speaker_role == "dialogue" else "narrator")
        )
        cast_entry = dict(private_speaker_cast.get(speaker_id) or {})
        cast_voice_id = str(cast_entry.get("voice_id") or "").strip()
        voice_hash = (
            _sha256_bytes(cast_voice_id.encode("utf-8"))
            if speaker_role == "dialogue" and cast_voice_id
            else narrator_voice_hash
        )
        passage_text = str(row.get("text") or "")
        passages.append(
            {
                "passage_index": passage_index,
                "source_chapter_index": int(row.get("source_chapter_index") or 0),
                "source_chapter_indexes": [
                    int(value)
                    for value in list(row.get("source_chapter_indexes") or [])
                    if int(value) > 0
                ],
                "source_href": str(row.get("source_href") or ""),
                "source_scene_index": int(row.get("source_scene_index") or 0),
                "source_paragraph_start": int(row.get("source_paragraph_start") or 0),
                "source_paragraph_end": int(row.get("source_paragraph_end") or 0),
                "char_start": int(row.get("char_start") or 0),
                "char_end": int(row.get("char_end") or 0),
                "text": passage_text,
                "text_sha256": _sha256_bytes(passage_text.encode("utf-8")),
                "char_count": len(passage_text),
                "speaker_role": speaker_role,
                "speaker_id": speaker_id,
                "speaker_label": str(row.get("speaker_label") or ""),
                "speaker_detection_evidence": dict(row.get("speaker_evidence") or {}),
                "attribution_provenance": str(row.get("attribution_provenance") or ""),
                "attribution_confidence": float(row.get("attribution_confidence") or 0.0),
                "voice_ref_sha256": voice_hash,
                "pause_kind_after": str(
                    row.get("boundary_kind_after") or row.get("pause_kind") or ""
                ),
                "pause_seconds_after": float(row.get("pause_seconds_after") or 0.0),
                "passage_fingerprint": str(row.get("passage_fingerprint") or ""),
            }
        )
    render_signature = _sha256_bytes(
        json.dumps(
            {
                "planner_plan_sha256": str(exact_plan.get("plan_sha256") or ""),
                "boundary_policy": str(exact_plan.get("boundary_policy") or BOUNDARY_POLICY_NAME),
                "speaker_cast_sha256": str(normalized_speaker_cast.get("cast_map_sha256") or ""),
                "mastering_contract": _audiobook_mastering_contract(),
                "passages": [
                {
                    "segment_render_fingerprint": _segment_render_fingerprint(
                        text=str(row["text"]),
                        voice_id=_speaker_voice_id(
                            row,
                            narrator_voice_id=narrator_voice_id,
                            speaker_cast=normalized_speaker_cast,
                        ),
                        speaker_role=str(row["speaker_role"]),
                        speaker_id=str(row.get("speaker_id") or ""),
                        render_language=render_language,
                    ),
                    "pause_kind_after": row["pause_kind_after"],
                    "pause_seconds_after": row["pause_seconds_after"],
                }
                for row in passages
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    plan = {
        "contract_name": NARRATION_PLAN_CONTRACT_NAME,
        "generated_at": _now_iso(),
        "render_mode": render_mode,
        "render_language": _normalize_language(render_language),
        "status": (
            "ready"
            if coverage_matches and not source_integrity_issues
            else "blocked_source_integrity_or_coverage_mismatch"
        ),
        "source_chapters": [
            {
                "chapter_index": chapter.index,
                "source_href": chapter.source_href,
                "source_text_sha256": chapter.sha256,
                "actual_source_text_sha256": actual_text_hashes.get(chapter.index, ""),
                "structure_path": chapter.structure_path,
                **source_provenance.get(
                    chapter.index,
                    {"status": "legacy_structure_unverified"},
                ),
            }
            for chapter, _ in chapter_inputs
        ],
        "passage_count": len(passages),
        "dialogue_passage_count": sum(1 for row in passages if row["speaker_role"] == "dialogue"),
        "source_canonical_sha256": source_canonical_sha256,
        "planned_canonical_sha256": planned_canonical_sha256,
        "source_coverage": "complete" if coverage_matches else "mismatch",
        "coverage_complete": coverage_matches,
        "source_integrity_verified": coverage_matches and not source_integrity_issues,
        "chapter_coverage": chapter_coverage,
        "source_integrity_issues": source_integrity_issues,
        "planner_plan_sha256": str(exact_plan.get("plan_sha256") or ""),
        "source_aggregate_sha256": str(exact_plan.get("source_aggregate_sha256") or ""),
        "boundary_policy": str(exact_plan.get("boundary_policy") or BOUNDARY_POLICY_NAME),
        "boundary_counts": dict(exact_plan.get("boundary_counts") or {}),
        "total_inserted_pause_seconds": float(
            exact_plan.get("total_inserted_pause_seconds") or 0.0
        ),
        "span_count": int(exact_plan.get("span_count") or 0),
        "dialogue_span_count": int(exact_plan.get("dialogue_span_count") or 0),
        "attributed_dialogue_span_count": int(
            exact_plan.get("attributed_dialogue_span_count") or 0
        ),
        "uncertain_dialogue_span_count": int(
            exact_plan.get("uncertain_dialogue_span_count") or 0
        ),
        "speaker_count": int(exact_plan.get("speaker_count") or 0),
        "unsafe_or_very_short_passage_count": int(
            exact_plan.get("unsafe_or_very_short_passage_count") or 0
        ),
        "speakers": list(exact_plan.get("speakers") or []),
        "source_spans": list(exact_plan.get("spans") or []),
        "render_signature": render_signature,
        "private_payload": True,
        "raw_text_embedded": True,
        "public_projection_raw_text_allowed": False,
        "raw_voice_ids_embedded": False,
        "speaker_cast": {
            "status": str(normalized_speaker_cast.get("status") or "not_required"),
            "cast_map_sha256": str(normalized_speaker_cast.get("cast_map_sha256") or ""),
            "trait_values_are_ranking_hints_only": True,
            "identity_asserted": False,
            "entries": [
                {
                    key: value
                    for key, value in dict(entry).items()
                    if key != "voice_id"
                }
                for _speaker_id, entry in sorted(private_speaker_cast.items())
            ],
        },
        "voice_provenance": (
            "unknown_existing_external_audio"
            if render_mode == "existing_external_chapter_audio"
            else "approved_or_selected_runtime_voice"
        ),
        "passages": passages,
    }
    path = job_dir / "narration_plan.json"
    try:
        _write_private_json(path, plan)
        cache_digest = str(exact_plan.get("source_aggregate_sha256") or "").strip()
        if re.fullmatch(r"[0-9a-f]{64}", cache_digest):
            cache_path = (
                job_dir
                / "narration_plans"
                / f"{NARRATION_PLAN_CONTRACT_NAME.replace('.', '_')}-{cache_digest}.json"
            )
            _write_private_json(cache_path, plan, private_parent=True)
    except (OSError, RuntimeError) as exc:
        return {
            "status": "blocked_private_plan_write",
            "contract_name": NARRATION_PLAN_CONTRACT_NAME,
            "path": path.name,
            "passage_count": len(passages),
            "dialogue_passage_count": sum(1 for row in passages if row["speaker_role"] == "dialogue"),
            "source_coverage": plan["source_coverage"],
            "private_payload": True,
            "raw_text_exposed": False,
            "raw_voice_ids_exposed": False,
            "error_type": type(exc).__name__,
        }
    return {
        "status": plan["status"],
        "contract_name": NARRATION_PLAN_CONTRACT_NAME,
        "path": path.name,
        "passage_count": plan["passage_count"],
        "dialogue_passage_count": plan["dialogue_passage_count"],
        "speaker_cast": dict(normalized_speaker_cast.get("public") or {}),
        "cast_map_sha256": str(normalized_speaker_cast.get("cast_map_sha256") or ""),
        "source_coverage": plan["source_coverage"],
        "coverage_complete": bool(plan["coverage_complete"]),
        "source_integrity_verified": bool(plan["source_integrity_verified"]),
        "plan_sha256": str(exact_plan.get("plan_sha256") or ""),
        "source_aggregate_sha256": str(exact_plan.get("source_aggregate_sha256") or ""),
        "boundary_counts": dict(exact_plan.get("boundary_counts") or {}),
        "speaker_count": int(exact_plan.get("speaker_count") or 0),
        "attributed_dialogue_span_count": int(
            exact_plan.get("attributed_dialogue_span_count") or 0
        ),
        "uncertain_dialogue_span_count": int(
            exact_plan.get("uncertain_dialogue_span_count") or 0
        ),
        "render_signature": render_signature,
        "private_payload": True,
        "raw_text_exposed": False,
        "raw_voice_ids_exposed": False,
    }


@contextlib.contextmanager
def _exclusive_audiobook_render_lock(job_dir: Path):
    job_dir.mkdir(parents=True, exist_ok=True)
    lock_path = job_dir / ".audiobook-render.lock"
    timeout_seconds = _env_float(
        "EA_AUDIOBOOK_RENDER_LOCK_TIMEOUT_SECONDS",
        30.0,
        minimum=0.1,
        maximum=600.0,
    )
    with lock_path.open("a+b") as handle:
        try:
            lock_path.chmod(0o600)
        except OSError:
            pass
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise _AudiobookLockTimeout("audiobook_render_lock_timeout")
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def _exclusive_audiobook_job_lock(job_dir: Path):
    job_dir.mkdir(parents=True, exist_ok=True)
    lock_path = job_dir / ".audiobook-job.lock"
    timeout_seconds = _env_float(
        "EA_AUDIOBOOK_JOB_LOCK_TIMEOUT_SECONDS",
        30.0,
        minimum=0.1,
        maximum=600.0,
    )
    with lock_path.open("a+b") as handle:
        with contextlib.suppress(OSError):
            lock_path.chmod(0o600)
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise _AudiobookLockTimeout("audiobook_job_lock_timeout")
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def render_unmixr_chapter_audio(
    *,
    job_dir: Path,
    chapters: tuple[EpubChapter, ...],
    metadata: EpubMetadata,
) -> dict[str, object]:
    try:
        with _exclusive_audiobook_render_lock(job_dir):
            return _render_unmixr_chapter_audio_locked(
                job_dir=job_dir,
                chapters=chapters,
                metadata=metadata,
            )
    except _AudiobookLockTimeout:
        return {
            "status": "render_in_progress",
            "reason": "audiobook_render_lock_timeout",
            "retryable": True,
        }


def _render_unmixr_chapter_audio_locked(*, job_dir: Path, chapters: tuple[EpubChapter, ...], metadata: EpubMetadata) -> dict[str, object]:
    audio_dir = job_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    resolved_voice_selection = selected_unmixr_voice_for_job(job_dir) or select_unmixr_voice_for_book(
        metadata=metadata,
        chapters=chapters,
        job_dir=job_dir,
    )
    resolved_narrator_voice_id = str(resolved_voice_selection.get("voice_id") or "").strip()
    public_voice_selection = dict(resolved_voice_selection.get("public") or {})
    selected_public = dict(public_voice_selection.get("selected") or {})
    if str(selected_public.get("provider") or "").strip() == "piper_local_fast":
        # Provider-policy gates precede source planning. A stale callback for a
        # removed local fallback must never reach any synthesis or planning
        # path, irrespective of the age or shape of the stored job manifest.
        return _removed_local_piper_render_result(public_voice_selection)
    active_voice_id = ""
    if unmixr_auto_render_enabled():
        active_voice_id = str(resolved_voice_selection.get("voice_id") or "").strip()
        if not active_voice_id:
            return {
                "status": "blocked",
                "reason": str(
                    resolved_voice_selection.get("reason")
                    or "unmixr_voice_selection_missing"
                ),
                "voice_selection": public_voice_selection,
            }
        language_mismatch = _selected_voice_language_mismatch(
            metadata=metadata,
            voice_selection=resolved_voice_selection,
        )
        if language_mismatch:
            return {
                "status": "blocked",
                "reason": "selected_voice_language_mismatch",
                "provider": "unmixr",
                "voice_selection": public_voice_selection,
                "voice_language_mismatch": language_mismatch,
            }
        author_gender_mismatch = _selected_voice_author_gender_mismatch(
            job_dir=job_dir,
            metadata=metadata,
            voice_selection=resolved_voice_selection,
        )
        if author_gender_mismatch:
            return {
                "status": "blocked",
                "reason": "selected_voice_author_gender_mismatch",
                "provider": "unmixr",
                "voice_selection": public_voice_selection,
                "voice_author_gender_mismatch": author_gender_mismatch,
            }
    render_language = _normalize_language(metadata.language)
    configured_dialogue_voice_selection = _configured_dialogue_voice_selection(job_dir)
    raw_configured_dialogue_voice_id = str(
        configured_dialogue_voice_selection.get("voice_id") or ""
    ).strip()
    configured_dialogue_voice_id = (
        raw_configured_dialogue_voice_id
        if raw_configured_dialogue_voice_id
        and raw_configured_dialogue_voice_id != resolved_narrator_voice_id
        else ""
    )
    cinematic_track_input = _collect_cinematic_track_input(job_dir=job_dir, chapters=chapters) if _audiobook_cinematic_narration() else ()
    cinematic_exact_plan = (
        _build_exact_narration_plan(
            chapter_inputs=cinematic_track_input,
            render_language=render_language,
            max_chars=_audiobook_cinematic_max_chars_per_request(),
        )
        if cinematic_track_input
        else {}
    )
    cinematic_speaker_cast = (
        _resolve_speaker_cast_for_narration_plan(
            job_dir=job_dir,
            narration_plan=cinematic_exact_plan,
            narrator_voice_id=resolved_narrator_voice_id,
            render_language=render_language,
            default_dialogue_selection=configured_dialogue_voice_selection,
        )
        if cinematic_exact_plan and resolved_narrator_voice_id
        else {"status": "not_required", "private": {}, "public": {"status": "not_required"}}
    )
    cinematic_track_signature = _cinematic_track_signature(
        chapter_inputs=cinematic_track_input,
        narrator_voice_id=resolved_narrator_voice_id,
        dialogue_voice_id=configured_dialogue_voice_id,
        render_language=render_language,
        planner_plan_sha256=str(cinematic_exact_plan.get("plan_sha256") or ""),
        cast_map_sha256=str(cinematic_speaker_cast.get("cast_map_sha256") or ""),
    )
    if cinematic_exact_plan and cinematic_exact_plan.get("status") != "ready":
        blocked_private_plan = _write_private_narration_plan(
            job_dir=job_dir,
            chapter_inputs=cinematic_track_input,
            segment_rows=tuple(
                dict(row)
                for row in list(cinematic_exact_plan.get("passages") or [])
                if isinstance(row, dict)
            ),
            narrator_voice_id=resolved_narrator_voice_id,
            dialogue_voice_id=configured_dialogue_voice_id,
            render_language=render_language,
            render_mode="blocked_exact_plan",
            speaker_cast=cinematic_speaker_cast,
            planner_plan=cinematic_exact_plan,
        )
        return {
            "status": "blocked",
            "reason": _exact_narration_plan_block_reason(cinematic_exact_plan),
            "narration_plan": {
                **_public_exact_narration_plan_summary(cinematic_exact_plan),
                "private_plan_status": str(blocked_private_plan.get("status") or ""),
                "private_plan_path": str(blocked_private_plan.get("path") or ""),
            },
            "voice_selection": dict(resolved_voice_selection.get("public") or {}),
        }
    if (
        cinematic_exact_plan
        and int(cinematic_exact_plan.get("dialogue_span_count") or 0) > 0
        and cinematic_speaker_cast.get("status") == "blocked"
        and unmixr_auto_render_enabled()
    ):
        return {
            "status": "blocked",
            "reason": str(
                cinematic_speaker_cast.get("reason")
                or "speaker_voice_cast_unavailable"
            ),
            "narration_plan": _public_exact_narration_plan_summary(cinematic_exact_plan),
            "speaker_cast": dict(cinematic_speaker_cast.get("public") or {}),
            "voice_selection": dict(resolved_voice_selection.get("public") or {}),
        }
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
            and cinematic_mode in _CINEMATIC_MASTER_VALID_MODES
            and _cinematic_master_mode_compatible(
                cinematic_mode,
                dialogue_voice_enabled=bool(
                    configured_dialogue_voice_id
                    or int(cinematic_exact_plan.get("dialogue_span_count") or 0)
                ),
            )
            and cinematic_cached_signature == cinematic_track_signature
        ):
            cached_chapter_inputs = tuple(
                (chapter, text)
                for chapter, text in cinematic_track_input
                if str(text or "").strip()
            )
            cached_segment_rows = tuple(
                dict(row)
                for row in list(cinematic_exact_plan.get("passages") or [])
                if isinstance(row, dict)
            )
            cached_narration_plan = _write_private_narration_plan(
                job_dir=job_dir,
                chapter_inputs=cached_chapter_inputs,
                segment_rows=cached_segment_rows,
                narrator_voice_id=resolved_narrator_voice_id,
                dialogue_voice_id=configured_dialogue_voice_id,
                render_language=render_language,
                render_mode=cinematic_mode,
                speaker_cast=cinematic_speaker_cast,
                planner_plan=cinematic_exact_plan,
            )
            if cached_narration_plan.get("status") != "ready":
                return {
                    "status": "blocked",
                    "reason": str(
                        cached_narration_plan.get("status") or "narration_plan_blocked"
                    ),
                    "narration_plan": cached_narration_plan,
                    "voice_selection": dict(resolved_voice_selection.get("public") or {}),
                    "dialogue_voice_selection": _public_dialogue_voice_selection_from_cast(
                        cinematic_speaker_cast
                    ),
                    "speaker_cast": dict(cinematic_speaker_cast.get("public") or {}),
                }
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
                    "voice_selection": dict(resolved_voice_selection.get("public") or {}),
                    "dialogue_voice_selection": _public_dialogue_voice_selection_from_cast(
                        cinematic_speaker_cast
                    ),
                    "speaker_cast": dict(cinematic_speaker_cast.get("public") or {}),
                    "narration_plan": cached_narration_plan,
                    "cinematic_master_audio": str(cinematic_master),
                }

        if cinematic_master.is_file() and cinematic_master.stat().st_size > 0:
            try:
                cinematic_master.unlink()
                cinematic_mode_path.unlink()
                cinematic_signature_path.unlink()
            except OSError:
                pass
    voice_selection = resolved_voice_selection
    if not unmixr_auto_render_enabled():
        if _audio_inputs_ready(job_dir, chapters) and not configured_dialogue_voice_id:
            existing_chapter_inputs = _collect_cinematic_track_input(
                job_dir=job_dir,
                chapters=chapters,
            )
            existing_plan_rows: list[dict[str, object]] = []
            existing_max_chars = _env_int(
                "EA_AUDIOBOOK_UNMIXR_MAX_CHARS_PER_REQUEST",
                1800,
                minimum=1000,
                maximum=200000,
            )
            for chapter, source_text in existing_chapter_inputs:
                existing_plan_rows.extend(
                    {
                        **row,
                        "source_chapter_index": chapter.index,
                        "source_href": chapter.source_href,
                    }
                    for row in _chapter_text_segment_rows(
                        source_text,
                        max_chars=existing_max_chars,
                    )
                )
            existing_plan = _write_private_narration_plan(
                job_dir=job_dir,
                chapter_inputs=existing_chapter_inputs,
                segment_rows=tuple(existing_plan_rows),
                narrator_voice_id="",
                dialogue_voice_id="",
                render_language=render_language,
                render_mode="existing_external_chapter_audio",
            )
            if existing_plan.get("status") == "ready":
                return {
                    "status": "already_rendered",
                    "reason": "chapter_audio_present",
                    "narration_plan": existing_plan,
                    "voice_selection": public_voice_selection,
                    "dialogue_voice_selection": _public_dialogue_voice_selection(
                        {},
                        narrator_voice_id=resolved_narrator_voice_id,
                    ),
                }
            return {
                "status": "blocked",
                "reason": str(existing_plan.get("status") or "narration_plan_blocked"),
                "narration_plan": existing_plan,
                "voice_selection": public_voice_selection,
            }
        return {"status": "blocked", "reason": "external_tts_disabled_or_auto_render_off"}
    voice_id = active_voice_id
    dialogue_voice_id = (
        configured_dialogue_voice_id
        if configured_dialogue_voice_id and configured_dialogue_voice_id != voice_id
        else ""
    )
    speaker_cast = cinematic_speaker_cast if cinematic_exact_plan else {
        "status": "not_required",
        "private": {},
        "public": {"status": "not_required"},
        "cast_map_sha256": "",
    }
    public_dialogue_voice_selection = _public_dialogue_voice_selection_from_cast(
        speaker_cast
    )
    # This path uses Unmixr's short TTS endpoint. Keep segments conservative; long-form
    # Studio/Narration imports are a separate provider workflow.
    max_chars = _env_int("EA_AUDIOBOOK_UNMIXR_MAX_CHARS_PER_REQUEST", 1800, minimum=1000, maximum=200000)
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

        # Chapter boundaries are real performance boundaries. Preserve them as
        # scene breaks instead of flattening the whole book into one sentence.
        cinematic_text = "\n\n\n".join(source_text for _, source_text in cinematic_track_chapters)
        if (
            _audiobook_cinematic_single_pass()
            and int(cinematic_exact_plan.get("dialogue_span_count") or 0) == 0
        ):
            segment_rows = (
                {
                    "text": cinematic_text,
                    "speaker_role": "narrator",
                    "source_chapter_index": 0,
                    "source_chapter_indexes": [
                        chapter.index for chapter, _ in cinematic_track_chapters
                    ],
                    "source_href": "",
                    "paragraph_break_after": False,
                    "pause_kind": "",
                    "pause_seconds_after": 0.0,
                },
            )
            cinematic_render_mode = _CINEMATIC_MASTER_SINGLE_PASS_MODE
        else:
            segment_rows = tuple(
                dict(row)
                for row in list(cinematic_exact_plan.get("passages") or [])
                if isinstance(row, dict)
            )
            cinematic_render_mode = _CINEMATIC_MASTER_SEMANTIC_PASS_MODE
        if not segment_rows:
            for chapter, _ in cinematic_track_chapters:
                rendered.append({"chapter": chapter.index, "status": "skipped_empty"})
            return {"status": "rendered", "chapters": rendered, "voice_selection": dict(voice_selection.get("public") or {})}

        narration_plan = _write_private_narration_plan(
            job_dir=job_dir,
            chapter_inputs=tuple(cinematic_track_chapters),
            segment_rows=tuple(segment_rows),
            narrator_voice_id=voice_id,
            dialogue_voice_id=dialogue_voice_id,
            render_language=render_language,
            render_mode=cinematic_render_mode,
            speaker_cast=speaker_cast,
            planner_plan=cinematic_exact_plan,
        )
        if narration_plan.get("status") != "ready":
            return {
                "status": "blocked",
                "reason": str(narration_plan.get("status") or "narration_plan_blocked"),
                "narration_plan": narration_plan,
                "voice_selection": dict(voice_selection.get("public") or {}),
                "dialogue_voice_selection": public_dialogue_voice_selection,
                "speaker_cast": dict(speaker_cast.get("public") or {}),
            }

        while True:
            part_dir = audio_dir / "_cinematic-parts"
            segment_paths: list[Path] = []
            merge_paths: list[Path] = []
            content_types: list[str] = []
            retry_errors: list[str] = []
            segment_audio_quality: list[dict[str, object]] = []
            paragraph_pause_count = 0
            chapter_pause_count = 0
            scene_pause_count = 0
            speaker_pause_count = 0
            total_pause_count = 0
            total_pause_seconds = 0.0
            dialogue_passage_count = 0
            reused_segment_count = 0
            regenerated_segment_count = 0
            retry_with_segmented_fallback = False

            for segment_index, segment_row in enumerate(segment_rows, start=1):
                segment = str(segment_row.get("text") or "").strip()
                if not segment:
                    continue
                speaker_role = str(segment_row.get("speaker_role") or "narrator")
                segment_voice_id = _speaker_voice_id(
                    segment_row,
                    narrator_voice_id=voice_id,
                    speaker_cast=speaker_cast,
                )
                if speaker_role == "dialogue" and segment_voice_id:
                    dialogue_passage_count += 1
                segment_render_hash = _segment_render_fingerprint(
                    text=segment,
                    voice_id=segment_voice_id,
                    speaker_role=speaker_role,
                    speaker_id=str(segment_row.get("speaker_id") or ""),
                    render_language=render_language,
                )[:16]
                segment_target = (
                    cinematic_master
                    if cinematic_render_mode == _CINEMATIC_MASTER_SINGLE_PASS_MODE
                    else part_dir
                    / f"passage-{segment_render_hash}.wav"
                )
                if segment_target.is_file() and segment_target.stat().st_size > 0:
                    reused_segment_count += 1
                    segment_paths.append(segment_target)
                    merge_paths.append(segment_target)
                    content_types.append("existing")
                    segment_audio_quality.append(_rendered_audio_quality_report(segment_target))
                    if bool(segment_row.get("paragraph_break_after")) and len(segment_rows) > 1:
                        pause_kind = str(segment_row.get("pause_kind") or "paragraph")
                        pause_seconds_after = float(
                            segment_row.get("pause_seconds_after")
                            or (
                                _audiobook_scene_pause_seconds()
                                if pause_kind == "scene"
                                else _audiobook_paragraph_pause_seconds()
                            )
                        )
                        total_pause_count += 1
                        total_pause_seconds += pause_seconds_after
                        if pause_kind == "chapter":
                            chapter_pause_count += 1
                        elif pause_kind == "scene":
                            scene_pause_count += 1
                        elif pause_kind == "speaker":
                            speaker_pause_count += 1
                        else:
                            paragraph_pause_count += 1
                        merge_paths.append(
                            _write_silence_wav(
                                part_dir / f"_cinematic-{segment_index:03d}-{pause_kind}-pause.wav",
                                seconds=pause_seconds_after,
                            )
                        )
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
                        voice_id=segment_voice_id,
                        lang=render_language,
                        speaking_rate=unmixr_speaking_rate(),
                        speaking_pitch=unmixr_speaking_pitch(),
                        speaking_volume=unmixr_speaking_volume(),
                    )
                except Exception as exc:
                    raw_detail = _exception_detail(exc)
                    detail = _public_unmixr_error_reason(exc)
                    if (
                        cinematic_render_mode == _CINEMATIC_MASTER_SINGLE_PASS_MODE
                        and len(segment_rows) == 1
                        and _unmixr_input_too_long_error(raw_detail)
                    ):
                        fallback_exact_plan = _build_exact_narration_plan(
                            chapter_inputs=tuple(cinematic_track_chapters),
                            render_language=render_language,
                            max_chars=max_chars,
                        )
                        fallback_rows = tuple(
                            dict(row)
                            for row in list(fallback_exact_plan.get("passages") or [])
                            if isinstance(row, dict)
                        )
                        if len(fallback_rows) > 1:
                            segment_rows = fallback_rows
                            cinematic_render_mode = _CINEMATIC_MASTER_SEGMENTED_FALLBACK_MODE
                            narration_plan = _write_private_narration_plan(
                                job_dir=job_dir,
                                chapter_inputs=tuple(cinematic_track_chapters),
                                segment_rows=tuple(segment_rows),
                                narrator_voice_id=voice_id,
                                dialogue_voice_id=dialogue_voice_id,
                                render_language=render_language,
                                render_mode=cinematic_render_mode,
                                speaker_cast=speaker_cast,
                                planner_plan=fallback_exact_plan,
                            )
                            if narration_plan.get("status") != "ready":
                                return {
                                    "status": "blocked",
                                    "reason": str(narration_plan.get("status") or "narration_plan_blocked"),
                                    "narration_plan": narration_plan,
                                    "voice_selection": dict(voice_selection.get("public") or {}),
                                    "dialogue_voice_selection": public_dialogue_voice_selection,
                                }
                            retry_with_segmented_fallback = True
                            break
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
                retry_errors.extend(
                    _redact_render_sensitive_detail(error, voice_id, dialogue_voice_id)
                    for error in segment_retry_errors
                )
                rendered_segment = _write_provider_audio_segment_file(
                    audio_bytes=audio_bytes,
                    content_type=content_type,
                    target_wav=segment_target,
                )
                segments_rendered_this_run += 1
                regenerated_segment_count += 1
                segment_paths.append(rendered_segment)
                merge_paths.append(rendered_segment)
                content_types.append(content_type)
                segment_audio_quality.append(_rendered_audio_quality_report(rendered_segment))
                if bool(segment_row.get("paragraph_break_after")) and len(segment_rows) > 1:
                    pause_kind = str(segment_row.get("pause_kind") or "paragraph")
                    pause_seconds_after = float(
                        segment_row.get("pause_seconds_after")
                        or (
                            _audiobook_scene_pause_seconds()
                            if pause_kind == "scene"
                            else _audiobook_paragraph_pause_seconds()
                        )
                    )
                    total_pause_count += 1
                    total_pause_seconds += pause_seconds_after
                    if pause_kind == "chapter":
                        chapter_pause_count += 1
                    elif pause_kind == "scene":
                        scene_pause_count += 1
                    elif pause_kind == "speaker":
                        speaker_pause_count += 1
                    else:
                        paragraph_pause_count += 1
                    merge_paths.append(
                        _write_silence_wav(
                            part_dir / f"_cinematic-{segment_index:03d}-{pause_kind}-pause.wav",
                            seconds=pause_seconds_after,
                        )
                    )
            if retry_with_segmented_fallback:
                continue
            break
        if (
            cinematic_render_mode != _CINEMATIC_MASTER_SINGLE_PASS_MODE
            and not _merge_audio_segments_to_wav(segment_paths=tuple(merge_paths), target=cinematic_master)
        ):
            return {
                "status": "blocked",
                "reason": "cinematic_master_merge_failed",
                "segment_count": len(segment_paths),
                "segment_merge_input_count": len(merge_paths),
            }
        try:
            cinematic_master = _normalize_rendered_audio_file(cinematic_master)
        except Exception as exc:
            return {
                "status": "blocked",
                "reason": "audiobook_final_mastering_failed",
                "mastering": {
                    "status": "blocked",
                    "error_code": str(exc)
                    if str(exc).startswith("audiobook_audio_normalization_")
                    else type(exc).__name__,
                    "contract_sha256": _audiobook_mastering_contract(),
                    "segment_mastering": False,
                    "signature_published": False,
                },
            }
        cinematic_audio_quality = _rendered_audio_quality_report(cinematic_master)
        try:
            cinematic_mode_path.write_text(cinematic_render_mode, encoding="utf-8")
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
                    "segment_count": len(segment_paths),
                    "paragraph_pause_count": paragraph_pause_count,
                    "paragraph_pause_seconds": (
                        round(_audiobook_paragraph_pause_seconds(), 3)
                        if paragraph_pause_count
                        else 0.0
                    ),
                    "chapter_pause_count": chapter_pause_count,
                    "chapter_pause_seconds": (
                        round(
                            _env_float(
                                "EA_AUDIOBOOK_CHAPTER_PAUSE_SECONDS",
                                1.5,
                                minimum=0.0,
                                maximum=8.0,
                            ),
                            3,
                        )
                        if chapter_pause_count
                        else 0.0
                    ),
                    "scene_pause_count": scene_pause_count,
                    "scene_pause_seconds": (
                        round(_audiobook_scene_pause_seconds(), 3) if scene_pause_count else 0.0
                    ),
                    "speaker_pause_count": speaker_pause_count,
                    "speaker_pause_seconds": (
                        round(_audiobook_speaker_pause_seconds(), 3)
                        if speaker_pause_count
                        else 0.0
                    ),
                    "dialogue_passage_count": dialogue_passage_count,
                    "reused_passage_count": reused_segment_count,
                    "regenerated_passage_count": regenerated_segment_count,
                    "total_pause_count": total_pause_count,
                    "total_pause_seconds": round(total_pause_seconds, 3),
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
            "dialogue_voice_selection": public_dialogue_voice_selection,
            "speaker_cast": dict(speaker_cast.get("public") or {}),
            "narration_plan": narration_plan,
            "cinematic_master_audio": str(cinematic_master),
        }

    chapter_inputs = _collect_cinematic_track_input(job_dir=job_dir, chapters=chapters)
    exact_plan = _build_exact_narration_plan(
        chapter_inputs=chapter_inputs,
        render_language=render_language,
        max_chars=max_chars,
    )
    if exact_plan.get("status") != "ready":
        blocked_private_plan = _write_private_narration_plan(
            job_dir=job_dir,
            chapter_inputs=chapter_inputs,
            segment_rows=tuple(
                dict(row)
                for row in list(exact_plan.get("passages") or [])
                if isinstance(row, dict)
            ),
            narrator_voice_id=voice_id,
            dialogue_voice_id=dialogue_voice_id,
            render_language=render_language,
            render_mode="blocked_exact_plan",
            planner_plan=exact_plan,
        )
        return {
            "status": "blocked",
            "reason": _exact_narration_plan_block_reason(exact_plan),
            "narration_plan": {
                **_public_exact_narration_plan_summary(exact_plan),
                "private_plan_status": str(blocked_private_plan.get("status") or ""),
                "private_plan_path": str(blocked_private_plan.get("path") or ""),
            },
            "voice_selection": dict(voice_selection.get("public") or {}),
        }
    speaker_cast = _resolve_speaker_cast_for_narration_plan(
        job_dir=job_dir,
        narration_plan=exact_plan,
        narrator_voice_id=voice_id,
        render_language=render_language,
        default_dialogue_selection=configured_dialogue_voice_selection,
    )
    if speaker_cast.get("status") == "blocked":
        return {
            "status": "blocked",
            "reason": str(speaker_cast.get("reason") or "speaker_voice_cast_unavailable"),
            "narration_plan": _public_exact_narration_plan_summary(exact_plan),
            "speaker_cast": dict(speaker_cast.get("public") or {}),
            "voice_selection": dict(voice_selection.get("public") or {}),
        }
    public_dialogue_voice_selection = _public_dialogue_voice_selection_from_cast(speaker_cast)
    narration_plan_rows = tuple(
        dict(row)
        for row in list(exact_plan.get("passages") or [])
        if isinstance(row, dict)
    )
    chapter_segment_rows = {
        chapter.index: tuple(
            row
            for row in narration_plan_rows
            if int(row.get("source_chapter_index") or 0) == chapter.index
        )
        for chapter in chapters
    }
    narration_plan = _write_private_narration_plan(
        job_dir=job_dir,
        chapter_inputs=chapter_inputs,
        segment_rows=narration_plan_rows,
        narrator_voice_id=voice_id,
        dialogue_voice_id=dialogue_voice_id,
        render_language=render_language,
        render_mode="unmixr_chapter_semantic_pass",
        speaker_cast=speaker_cast,
        planner_plan=exact_plan,
    )
    if narration_plan.get("status") != "ready":
        return {
            "status": "blocked",
            "reason": str(narration_plan.get("status") or "narration_plan_blocked"),
            "narration_plan": narration_plan,
            "voice_selection": dict(voice_selection.get("public") or {}),
            "dialogue_voice_selection": public_dialogue_voice_selection,
            "speaker_cast": dict(speaker_cast.get("public") or {}),
        }

    for chapter in chapters:
        target = audio_dir / chapter.audio_filename
        target_signature_path = target.with_suffix(target.suffix + ".narration.signature")
        segment_rows = chapter_segment_rows.get(chapter.index, ())
        chapter_master_signature = _chapter_master_render_signature(
            chapter=chapter,
            segment_rows=segment_rows,
            narrator_voice_id=voice_id,
            speaker_cast=speaker_cast,
            render_language=render_language,
        )
        existing_master_stale = False
        if target.is_file() and target.stat().st_size > 0:
            try:
                existing_signature = target_signature_path.read_text(encoding="utf-8").strip()
            except OSError:
                existing_signature = ""
            if existing_signature != chapter_master_signature:
                existing_master_stale = True
            else:
                rendered.append(
                    {
                        "chapter": chapter.index,
                        "status": "already_present",
                        "path": target.name,
                        "audio_quality": _rendered_audio_quality_report(target),
                        "cache_reused": True,
                    }
                )
                continue
        source_text = (job_dir / "chapters" / chapter.text_path).read_text(encoding="utf-8")
        normalized_source_text = str(source_text or "").strip()
        if not normalized_source_text:
            rendered.append({"chapter": chapter.index, "status": "skipped_empty"})
            continue

        if not segment_rows:
            rendered.append({"chapter": chapter.index, "status": "skipped_empty"})
            continue

        segment_paths: list[Path] = []
        merge_paths: list[Path] = []
        content_types: list[str] = []
        retry_errors: list[str] = []
        segment_audio_quality: list[dict[str, object]] = []
        paragraph_pause_count = 0
        chapter_pause_count = 0
        scene_pause_count = 0
        speaker_pause_count = 0
        total_pause_count = 0
        total_pause_seconds = 0.0
        dialogue_passage_count = 0
        reused_segment_count = 0
        regenerated_segment_count = 0
        paragraph_pause_seconds = _audiobook_paragraph_pause_seconds() if _audiobook_paragraph_pauses_enabled() else 0.0
        scene_pause_seconds = _audiobook_scene_pause_seconds() if _audiobook_paragraph_pauses_enabled() else 0.0
        part_dir = audio_dir / f"{chapter.index:03d}-parts"
        for segment_index, segment_row in enumerate(segment_rows, start=1):
            segment = str(segment_row.get("text") or "")
            speaker_role = str(segment_row.get("speaker_role") or "narrator")
            segment_voice_id = _speaker_voice_id(
                segment_row,
                narrator_voice_id=voice_id,
                speaker_cast=speaker_cast,
            )
            if speaker_role == "dialogue" and segment_voice_id:
                dialogue_passage_count += 1
            segment_render_hash = _segment_render_fingerprint(
                text=segment,
                voice_id=segment_voice_id,
                speaker_role=speaker_role,
                speaker_id=str(segment_row.get("speaker_id") or ""),
                render_language=render_language,
            )[:16]
            segment_target = part_dir / f"passage-{segment_render_hash}.wav"
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
                reused_segment_count += 1
                segment_paths.append(existing_segment)
                merge_paths.append(existing_segment)
                if bool(segment_row.get("paragraph_break_after")) and len(segment_rows) > 1:
                    pause_kind = str(segment_row.get("pause_kind") or "paragraph")
                    pause_seconds_after = float(
                        segment_row.get("pause_seconds_after") or paragraph_pause_seconds
                    )
                    total_pause_count += 1
                    total_pause_seconds += pause_seconds_after
                    if pause_kind == "chapter":
                        chapter_pause_count += 1
                    elif pause_kind == "scene":
                        scene_pause_count += 1
                    elif pause_kind == "speaker":
                        speaker_pause_count += 1
                    else:
                        paragraph_pause_count += 1
                    merge_paths.append(
                        _write_silence_wav(
                            part_dir / f"{chapter.index:03d}-{segment_index:02d}-paragraph-pause.wav",
                            seconds=pause_seconds_after,
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
                    voice_id=segment_voice_id,
                    lang=render_language,
                    speaking_rate=unmixr_speaking_rate(),
                    speaking_pitch=unmixr_speaking_pitch(),
                    speaking_volume=unmixr_speaking_volume(),
                )
            except Exception as exc:
                detail = _public_unmixr_error_reason(exc)
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
            retry_errors.extend(
                _redact_render_sensitive_detail(error, voice_id, dialogue_voice_id)
                for error in segment_retry_errors
            )
            rendered_segment = _write_provider_audio_segment_file(
                audio_bytes=audio_bytes,
                content_type=content_type,
                target_wav=segment_target,
            )
            segments_rendered_this_run += 1
            regenerated_segment_count += 1
            segment_paths.append(rendered_segment)
            merge_paths.append(rendered_segment)
            if bool(segment_row.get("paragraph_break_after")) and len(segment_rows) > 1:
                pause_kind = str(segment_row.get("pause_kind") or "paragraph")
                pause_seconds_after = float(
                    segment_row.get("pause_seconds_after") or paragraph_pause_seconds
                )
                total_pause_count += 1
                total_pause_seconds += pause_seconds_after
                if pause_kind == "chapter":
                    chapter_pause_count += 1
                elif pause_kind == "scene":
                    scene_pause_count += 1
                elif pause_kind == "speaker":
                    speaker_pause_count += 1
                else:
                    paragraph_pause_count += 1
                merge_paths.append(
                    _write_silence_wav(
                        part_dir / f"{chapter.index:03d}-{segment_index:02d}-paragraph-pause.wav",
                        seconds=pause_seconds_after,
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
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(merge_paths[0], target)
            rendered_path = target
        try:
            rendered_path = _normalize_rendered_audio_file(rendered_path)
        except Exception as exc:
            return {
                "status": "blocked",
                "reason": "audiobook_final_mastering_failed",
                "chapter_index": chapter.index,
                "mastering": {
                    "status": "blocked",
                    "error_code": str(exc)
                    if str(exc).startswith("audiobook_audio_normalization_")
                    else type(exc).__name__,
                    "contract_sha256": _audiobook_mastering_contract(),
                    "segment_mastering": False,
                    "signature_published": False,
                },
            }
        chapter_audio_quality = _rendered_audio_quality_report(rendered_path)
        try:
            target_signature_path.write_text(
                chapter_master_signature,
                encoding="utf-8",
            )
        except OSError:
            pass
        rendered.append(
            {
                "chapter": chapter.index,
                "status": "rendered",
                "path": rendered_path.name,
                "segment_count": len(segment_paths),
                "paragraph_pause_count": paragraph_pause_count,
                "paragraph_pause_seconds": round(paragraph_pause_seconds, 3) if paragraph_pause_count else 0.0,
                "chapter_pause_count": chapter_pause_count,
                "chapter_pause_seconds": (
                    round(
                        _env_float(
                            "EA_AUDIOBOOK_CHAPTER_PAUSE_SECONDS",
                            1.5,
                            minimum=0.0,
                            maximum=8.0,
                        ),
                        3,
                    )
                    if chapter_pause_count
                    else 0.0
                ),
                "scene_pause_count": scene_pause_count,
                "scene_pause_seconds": round(scene_pause_seconds, 3) if scene_pause_count else 0.0,
                "speaker_pause_count": speaker_pause_count,
                "speaker_pause_seconds": (
                    round(_audiobook_speaker_pause_seconds(), 3)
                    if speaker_pause_count
                    else 0.0
                ),
                "dialogue_passage_count": dialogue_passage_count,
                "reused_passage_count": reused_segment_count,
                "regenerated_passage_count": regenerated_segment_count,
                "stale_master_rebuilt": existing_master_stale,
                "total_pause_count": total_pause_count,
                "total_pause_seconds": round(total_pause_seconds, 3),
                "content_types": content_types,
                "retry_errors": retry_errors,
                "audio_quality": chapter_audio_quality,
                "segment_audio_quality": segment_audio_quality,
            }
        )
    return {
        "status": "rendered",
        "chapters": rendered,
        "voice_selection": dict(voice_selection.get("public") or {}),
        "dialogue_voice_selection": public_dialogue_voice_selection,
        "speaker_cast": dict(speaker_cast.get("public") or {}),
        "narration_plan": narration_plan,
    }


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


def _sanitize_job_speaker_voice_overrides(
    payload: dict[str, object],
) -> dict[str, object]:
    sanitized = json.loads(json.dumps(payload))
    provider = dict(sanitized.get("provider") or {})
    narration = dict(sanitized.get("narration") or {})
    containers = [
        sanitized.get("speaker_profiles"),
        narration.get("speaker_profiles"),
        provider.get("speaker_profiles"),
        provider.get("speaker_voice_selections"),
    ]

    def _rows(value: object) -> list[dict[str, object]]:
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
        if isinstance(value, dict):
            if any(
                key in value
                for key in ("voice_selection", "selection", "voice_id", "speaker_id")
            ):
                return [value]
            return [row for row in value.values() if isinstance(row, dict)]
        return []

    for container in containers:
        for row in _rows(container):
            selections = [row]
            for key in ("voice_selection", "selection"):
                nested = row.get(key)
                if isinstance(nested, dict):
                    selections.append(nested)
            raw_id_removed = False
            for selection in selections:
                if str(selection.get("voice_id") or "").strip():
                    selection.pop("voice_id", None)
                    raw_id_removed = True
            if raw_id_removed:
                row["raw_voice_id_ignored"] = True
                row["raw_voice_id_reason"] = (
                    "raw_voice_id_requires_private_callback_token"
                )
    return sanitized


def _write_job(job_dir: Path, payload: dict[str, object]) -> None:
    job_dir.mkdir(parents=True, exist_ok=True)
    _write_private_json(
        job_dir / "job.json",
        _sanitize_job_speaker_voice_overrides(payload),
    )


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


def _receipt_sha256(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        return ""
    return normalized


def _safe_receipt_public_string(value: object, *, max_length: int = 240) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > max_length:
        return ""
    lowered = normalized.casefold()
    sensitive_markers = (
        "callback_token",
        "callback-token",
        "selected_callback",
        "selected-callback",
        "api_key",
        "api-key",
        "secret",
        "voice_id",
        "voice-id",
        "sample_path",
        "sample-path",
        "sample_file",
        "sample-file",
    )
    if any(marker in lowered for marker in sensitive_markers):
        return ""
    if "://" in normalized or "/" in normalized or "\\" in normalized:
        return ""
    if lowered.endswith((".wav", ".mp3", ".m4a", ".json", ".txt")):
        return ""
    if re.fullmatch(r"[0-9a-f]{8}-[0-9a-f-]{27,}", lowered):
        return ""
    return normalized


def _safe_receipt_string_list(value: object) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    rows: list[str] = []
    for item in value:
        if not isinstance(item, (str, int, float, bool)):
            continue
        normalized = _safe_receipt_public_string(item, max_length=160)
        if normalized and normalized not in rows:
            rows.append(normalized)
    return rows


def _safe_receipt_score_map(value: object) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    scores: dict[str, float] = {}
    for raw_key, raw_value in value.items():
        key = _normalize_tag(str(raw_key or ""))
        if not key or isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            continue
        numeric_value = float(raw_value)
        if math.isfinite(numeric_value):
            scores[key[:80]] = numeric_value
    return scores


def _safe_receipt_voice_candidate(value: object) -> dict[str, object]:
    candidate = dict(value or {}) if isinstance(value, dict) else {}
    public: dict[str, object] = {}
    for key in (
        "preset_key",
        "label",
        "provider",
        "language",
        "status",
        "selection_basis",
        "display_family",
    ):
        normalized = _safe_receipt_public_string(candidate.get(key))
        if normalized:
            public[key] = normalized
    for key in ("supported_languages", "tags", "matched_tags", "matched_use_cases"):
        values = _safe_receipt_string_list(candidate.get(key))
        if values:
            public[key] = values
    for key in ("score", "language_score", "tag_score", "feedback_score"):
        raw_value = candidate.get(key)
        if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool):
            numeric_value = float(raw_value)
            if math.isfinite(numeric_value):
                public[key] = numeric_value
    score_breakdown = _safe_receipt_score_map(candidate.get("score_breakdown"))
    if score_breakdown:
        public["score_breakdown"] = score_breakdown
    for key in ("default", "language_match", "approved_by_user", "selected_by_user"):
        if isinstance(candidate.get(key), bool):
            public[key] = bool(candidate.get(key))
    voice_hash = _receipt_sha256(candidate.get("voice_id_sha256"))
    if voice_hash:
        public["voice_id_sha256"] = voice_hash
    return public


def _safe_receipt_voice_selection(value: object) -> dict[str, object]:
    selection = dict(value or {}) if isinstance(value, dict) else {}
    public: dict[str, object] = {}
    for key in (
        "contract_name",
        "status",
        "source",
        "mode",
        "strategy",
        "language",
        "requested_language",
        "selection_basis",
        "selected_preset_key",
        "selected_label",
    ):
        normalized = _safe_receipt_public_string(selection.get(key))
        if normalized:
            public[key] = normalized
    for key in (
        "approved_by_user",
        "selected_by_user",
        "defaulted",
        "language_match",
        "explicit_operator_choice",
    ):
        if isinstance(selection.get(key), bool):
            public[key] = bool(selection.get(key))
    for key in ("candidate_count", "auditioned_candidate_count", "dismissed_candidate_count"):
        raw_value = selection.get(key)
        if isinstance(raw_value, int) and not isinstance(raw_value, bool):
            public[key] = max(0, raw_value)
    for key in ("matched_tags", "supported_languages"):
        values = _safe_receipt_string_list(selection.get(key))
        if values:
            public[key] = values
    for key in ("voice_id_sha256", "selected_voice_id_sha256", "selection_sha256"):
        digest = _receipt_sha256(selection.get(key))
        if digest:
            public[key] = digest
    selected_candidate = _safe_receipt_voice_candidate(selection.get("selected_candidate"))
    if not selected_candidate:
        selected_candidate = _safe_receipt_voice_candidate(selection.get("candidate"))
    if selected_candidate:
        public["selected_candidate"] = selected_candidate
    return public


def _safe_receipt_dialogue_voice_selection(value: object) -> dict[str, object]:
    selection = dict(value or {}) if isinstance(value, dict) else {}
    public = _safe_receipt_voice_selection(selection)
    for key in (
        "enabled",
        "distinct_from_narrator",
        "narrator_voice_excluded",
        "traits_are_ranking_hints_only",
        "identity_or_demographics_claimed",
        "trait_hints_used",
        "automatic_sharing_used",
    ):
        if isinstance(selection.get(key), bool):
            public[key] = bool(selection.get(key))
    speaker_cast = _safe_receipt_speaker_cast(selection)
    if speaker_cast:
        public["speaker_cast"] = speaker_cast
    return public


def _safe_receipt_speaker_cast(value: object) -> dict[str, object]:
    speaker_cast = dict(value or {}) if isinstance(value, dict) else {}
    if not any(
        key in speaker_cast
        for key in (
            "cast",
            "cast_map_sha256",
            "speaker_count",
            "resolved_speaker_count",
            "narrator_voice_excluded",
            "snapshot_status",
            "sharing_policy",
        )
    ):
        return {}
    public: dict[str, object] = {}
    for key in (
        "status",
        "reason",
        "snapshot_status",
        "sharing_policy",
        "casting_policy",
    ):
        normalized = _safe_receipt_public_string(speaker_cast.get(key))
        if normalized:
            public[key] = normalized
    for key in (
        "speaker_count",
        "resolved_speaker_count",
        "distinct_dialogue_voice_count",
        "automatic_voice_cap",
        "automatic_distinct_voice_count",
        "automatic_shared_speaker_count",
    ):
        raw_value = speaker_cast.get(key)
        if isinstance(raw_value, int) and not isinstance(raw_value, bool):
            public[key] = max(raw_value, 0)
    for key in (
        "narrator_voice_excluded",
        "raw_voice_ids_exposed",
        "trait_values_exposed",
        "traits_are_ranking_hints_only",
        "identity_or_demographics_claimed",
        "trait_hints_used",
        "automatic_sharing_used",
        "reused_private_snapshot",
    ):
        if isinstance(speaker_cast.get(key), bool):
            public[key] = bool(speaker_cast.get(key))
    cast_hash = _receipt_sha256(speaker_cast.get("cast_map_sha256"))
    if cast_hash:
        public["cast_map_sha256"] = cast_hash
    cast_rows: list[dict[str, object]] = []
    for raw_row in list(speaker_cast.get("cast") or [])[:32]:
        if not isinstance(raw_row, dict):
            continue
        row: dict[str, object] = {}
        speaker_id = _safe_receipt_public_string(raw_row.get("speaker_id"))
        if speaker_id:
            row["speaker_id"] = speaker_id
        for key in ("speaker_label_sha256", "voice_id_sha256"):
            digest = _receipt_sha256(raw_row.get(key))
            if digest:
                row[key] = digest
        for key in ("selection_source", "voice_label"):
            normalized = _safe_receipt_public_string(raw_row.get(key))
            if normalized:
                row[key] = normalized
        for key in (
            "matched_trait_kinds",
            "unmatched_trait_kinds",
            "ambiguous_trait_kinds",
        ):
            values = _safe_receipt_string_list(raw_row.get(key))
            if values:
                row[key] = values
        confidence = raw_row.get("trait_evidence_confidence")
        if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
            row["trait_evidence_confidence"] = max(
                0.0,
                min(float(confidence), 1.0),
            )
        for key in (
            "unknown_neutral_fallback",
            "raw_voice_id_exposed",
            "identity_asserted",
        ):
            if isinstance(raw_row.get(key), bool):
                row[key] = bool(raw_row.get(key))
        if row:
            cast_rows.append(row)
    if cast_rows:
        public["cast"] = cast_rows
    return public


def _safe_receipt_narration_plan(value: object) -> dict[str, object]:
    plan = dict(value or {}) if isinstance(value, dict) else {}
    public: dict[str, object] = {}
    for key in (
        "contract_name",
        "status",
        "version",
        "semantic_mode",
        "provider",
        "boundary_policy",
        "source_coverage",
        "private_plan_status",
    ):
        normalized = _safe_receipt_public_string(plan.get(key))
        if normalized:
            public[key] = normalized
    for key in (
        "chapter_count",
        "passage_count",
        "source_document_count",
        "source_char_count",
        "covered_char_count",
        "dialogue_passage_count",
        "narrator_passage_count",
        "span_count",
        "dialogue_span_count",
        "attributed_dialogue_span_count",
        "uncertain_dialogue_span_count",
        "speaker_count",
        "unsafe_or_very_short_passage_count",
    ):
        raw_value = plan.get(key)
        if isinstance(raw_value, int) and not isinstance(raw_value, bool):
            public[key] = max(0, raw_value)
    for key in (
        "coverage_complete",
        "source_integrity_verified",
        "private_plan_present",
    ):
        if isinstance(plan.get(key), bool):
            public[key] = bool(plan.get(key))
    for key in ("plan_sha256", "file_sha256", "render_signature", "source_aggregate_sha256"):
        digest = _receipt_sha256(plan.get(key))
        if digest:
            public[key] = digest
    boundary_counts = plan.get("boundary_counts")
    if isinstance(boundary_counts, dict):
        public["boundary_counts"] = {
            _normalize_tag(key): max(int(value), 0)
            for key, value in boundary_counts.items()
            if _normalize_tag(key)
            and isinstance(value, int)
            and not isinstance(value, bool)
        }
    pause_seconds = plan.get("total_inserted_pause_seconds")
    if isinstance(pause_seconds, (int, float)) and not isinstance(pause_seconds, bool):
        public["total_inserted_pause_seconds"] = max(float(pause_seconds), 0.0)
    speaker_cast = _safe_receipt_speaker_cast(plan.get("speaker_cast"))
    if speaker_cast:
        public["speaker_cast"] = speaker_cast
    if public and (
        str(plan.get("contract_name") or "") == NARRATION_PLAN_CONTRACT_NAME
        or plan.get("raw_text_exposed") is False
        or plan.get("raw_voice_ids_exposed") is False
    ):
        public["raw_text_exposed"] = False
        public["raw_voice_ids_exposed"] = False
    return public


def _safe_receipt_pacing(value: object) -> dict[str, object]:
    pacing = dict(value or {}) if isinstance(value, dict) else {}
    public: dict[str, object] = {}
    source_kind = _normalize_tag(str(pacing.get("source_kind") or ""))
    if source_kind in {
        "azw",
        "azw3",
        "epub",
        "memorial",
        "mobi",
        "origin_dossier",
        "prc",
        "text",
    }:
        public["source_kind"] = source_kind
    for raw_key, raw_value in pacing.items():
        key = _normalize_tag(str(raw_key or ""))
        if not key or key != str(raw_key or "").strip().casefold() or len(key) > 80:
            continue
        if isinstance(raw_value, bool):
            public[key] = raw_value
        elif isinstance(raw_value, (int, float)):
            numeric_value = float(raw_value)
            if math.isfinite(numeric_value):
                public[key] = raw_value
    return public


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
    render_chapter_rows = [
        dict(row)
        for row in list(render_result.get("chapters") or [])
        if isinstance(row, dict)
    ]
    privacy = {
        "raw_book_text_in_receipt": False,
        "source_epub_path_exposed": False,
        "chapter_text_path_exposed": False,
        "telegram_chat_id_exposed": False,
        "telegram_message_id_exposed": False,
        "telegram_file_url_exposed": False,
        "telegram_token_exposed": False,
        "provider_voice_id_exposed": False,
        "dialogue_voice_id_exposed": False,
        "voice_audition_callback_token_exposed": False,
        "voice_sample_path_exposed": False,
        "private_narration_plan_path_exposed": False,
        "private_narration_plan_text_exposed": False,
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
            "pacing": _safe_receipt_pacing(render_result.get("pacing")),
            "chapter_audio_files": chapter_audio["count"],
            "chapter_audio_bytes": chapter_audio["bytes"],
            "segment_part_files": len(part_files),
            "segment_part_bytes": sum(int(item.stat().st_size or 0) for item in part_files),
            "voice_selection": _safe_receipt_voice_selection(provider.get("voice_selection"))
            or _safe_receipt_voice_selection(render_result.get("voice_selection")),
            "dialogue_voice_selection": _safe_receipt_dialogue_voice_selection(
                render_result.get("dialogue_voice_selection")
            )
            or _safe_receipt_dialogue_voice_selection(provider.get("dialogue_voice_selection")),
            "speaker_cast": _safe_receipt_speaker_cast(
                render_result.get("speaker_cast")
            ),
            "narration_plan": _safe_receipt_narration_plan(render_result.get("narration_plan"))
            or _safe_receipt_narration_plan(job.get("narration_plan")),
            "cache": {
                "reused_passage_count": sum(
                    int(row.get("reused_passage_count") or 0)
                    for row in render_chapter_rows
                ),
                "regenerated_passage_count": sum(
                    int(row.get("regenerated_passage_count") or 0)
                    for row in render_chapter_rows
                ),
                "stale_master_rebuilt_count": sum(
                    1
                    for row in render_chapter_rows
                    if row.get("stale_master_rebuilt") is True
                ),
                "content_addressed_passage_cache": True,
            },
            "mastering": {
                "contract_sha256": _audiobook_mastering_contract(),
                "normalization_enabled": _audio_normalization_enabled(),
                "scope": "assembled_chapter_or_cinematic_master_only",
                "segment_mastering": False,
                "final_track_count": sum(
                    1
                    for row in render_chapter_rows
                    if str(row.get("status") or "") in {"rendered", "already_present"}
                ),
            },
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


def _telegram_inline_keyboard(button_rows: list[list[tuple[str, str]]]) -> dict[str, object]:
    return {
        "inline_keyboard": [
            [
                {"text": str(label or "").strip(), "callback_data": str(callback_data or "").strip()}
                for label, callback_data in row
                if str(label or "").strip() and str(callback_data or "").strip()
            ]
            for row in button_rows
            if row
        ]
    }


def _base36_encode(value: int) -> str:
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    normalized = max(int(value), 0)
    if normalized == 0:
        return "0"
    chars: list[str] = []
    while normalized:
        normalized, remainder = divmod(normalized, 36)
        chars.append(alphabet[remainder])
    return "".join(reversed(chars))


def _telegram_playback_callback_secret(*, bot_token: str) -> str:
    return str(os.getenv("EA_TELEGRAM_CALLBACK_SECRET") or "").strip() or str(bot_token or "").strip()


def _telegram_voice_callback_secret(*, bot_token: str) -> str:
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


def _telegram_audiobook_voice_callback_signature(
    *,
    secret: str,
    action: str,
    token: str,
    chat_id: str,
    expires_at: int,
) -> str:
    payload = "|".join(
        (
            "ab",
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


def _telegram_encode_audiobook_voice_callback(
    *,
    bot_token: str,
    action: str,
    token: str,
    chat_id: str,
) -> str:
    normalized_action = str(action or "").strip().lower()[:1]
    normalized_token = str(token or "").strip()
    normalized_chat_id = str(chat_id or "").strip()
    secret = _telegram_voice_callback_secret(bot_token=bot_token)
    if normalized_action not in {"u", "d"} or not normalized_token or not normalized_chat_id or not secret:
        return ""
    expires_at = int(time.time()) + _env_int(
        "EA_TELEGRAM_AUDIOBOOK_VOICE_CALLBACK_TTL_SECONDS",
        604800,
        minimum=3600,
        maximum=604800,
    )
    signature = _telegram_audiobook_voice_callback_signature(
        secret=secret,
        action=normalized_action,
        token=normalized_token,
        chat_id=normalized_chat_id,
        expires_at=expires_at,
    )
    return f"ab|{normalized_action}|{normalized_token}|{_base36_encode(expires_at)}|{signature}"


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


def _telegram_send_audio(
    *,
    bot_token: str,
    chat_id: str,
    audio_path: str,
    caption: str,
    inline_buttons: list[list[tuple[str, str]]] | None = None,
) -> dict[str, object]:
    normalized_token = str(bot_token or "").strip()
    normalized_chat_id = str(chat_id or "").strip()
    path = Path(str(audio_path or "")).expanduser()
    if not normalized_token or not normalized_chat_id or not path.is_file():
        return {}
    boundary = f"----ea-telegram-audio-{uuid.uuid4().hex}"
    fields: dict[str, object] = {
        "chat_id": normalized_chat_id,
        "caption": str(caption or "").strip()[:1024],
    }
    if inline_buttons:
        fields["reply_markup"] = json.dumps(_telegram_inline_keyboard(inline_buttons), separators=(",", ":"))
    body = bytearray()
    for key, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        body.extend(str(value or "").encode("utf-8"))
        body.extend(b"\r\n")
    content_type = mimetypes.guess_type(path.name)[0] or "audio/wav"
    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(
        (
            f'Content-Disposition: form-data; name="audio"; filename="{path.name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
    )
    body.extend(path.read_bytes())
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{normalized_token}/sendAudio",
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=_env_int("EA_TELEGRAM_SEND_TIMEOUT_SECONDS", 10, minimum=1, maximum=120),
        ) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {"ok": False, "description": type(exc).__name__}


def _send_telegram_audiobook_voice_samples(
    *,
    job: dict[str, object],
    bot_token: str,
    chat_id: str,
    samples: list[dict[str, object]] | tuple[dict[str, object], ...] | None = None,
) -> list[dict[str, object]]:
    receipts: list[dict[str, object]] = []
    sample_messages = [
        dict(item)
        for item in (
            list(samples)
            if samples is not None
            else audiobook_voice_audition_sample_messages(job)
        )
        if isinstance(item, dict)
    ]
    for sample in sample_messages:
        token = str(sample.get("token") or "").strip()
        use_callback = _telegram_encode_audiobook_voice_callback(
            bot_token=bot_token,
            action="u",
            token=token,
            chat_id=chat_id,
        )
        dismiss_callback = _telegram_encode_audiobook_voice_callback(
            bot_token=bot_token,
            action="d",
            token=token,
            chat_id=chat_id,
        )
        caption = str(sample.get("label") or "Voice sample").strip()
        matched_tags = [str(item).strip() for item in list(sample.get("matched_tags") or []) if str(item).strip()]
        if matched_tags:
            caption = f"{caption} · {', '.join(matched_tags[:4])}"
        receipt = _telegram_send_audio(
            bot_token=bot_token,
            chat_id=chat_id,
            audio_path=str(sample.get("audio_path") or ""),
            caption=caption,
            inline_buttons=[[("Use this", use_callback), ("Dismiss", dismiss_callback)]],
        )
        sent = bool(receipt) and bool(dict(receipt).get("ok", True))
        reason = str(dict(receipt).get("description") or "").strip() if receipt else "telegram_audio_send_skipped"
        result = dict(dict(receipt).get("result") or {}) if isinstance(receipt, dict) else {}
        media_message_id = str(result.get("message_id") or "").strip()
        controls_ready = bool(use_callback and dismiss_callback)
        receipts.append(
            {
                "token": token,
                "status": "sent" if sent else "skipped",
                "reason": "" if sent else reason,
                "media_message_id_sha256": hashlib.sha256(media_message_id.encode("utf-8")).hexdigest()
                if media_message_id
                else "",
                "button_count": 2 if controls_ready else 0,
                "buttons_fallback": False,
                "control_kind": "inline_keyboard" if controls_ready else "",
            }
        )
    return receipts


def _audiobook_voice_sample_delivery_token_hashes(delivery: dict[str, object]) -> tuple[str, ...]:
    hashes: list[str] = []
    for item in list(delivery.get("samples") or []):
        if not isinstance(item, dict):
            continue
        token_sha256 = str(item.get("token_sha256") or "").strip()
        if token_sha256 and token_sha256 not in hashes:
            hashes.append(token_sha256)
    if hashes:
        return tuple(hashes)
    raw_hashes = delivery.get("token_sha256")
    if isinstance(raw_hashes, list):
        candidates = [str(item or "").strip() for item in raw_hashes]
    else:
        candidates = [str(raw_hashes or "").strip()]
    for token_sha256 in candidates:
        if token_sha256 and token_sha256 not in hashes:
            hashes.append(token_sha256)
    return tuple(hashes)


def _audiobook_voice_current_pending_token_hashes(job: dict[str, object]) -> set[str]:
    hashes = {
        _sha256_bytes(str(item.get("token") or "").encode("utf-8"))
        for item in audiobook_voice_audition_sample_messages(job)
        if str(item.get("token") or "").strip()
    }
    voice_selection = dict(dict(job.get("provider") or {}).get("voice_selection") or {})
    for row in list(voice_selection.get("pending_batch") or []):
        if not isinstance(row, dict):
            continue
        token = str(row.get("callback_token") or "").strip()
        if token:
            hashes.add(_sha256_bytes(token.encode("utf-8")))
    return hashes


def _telegram_audiobook_voice_samples_pending_delivery(job: dict[str, object]) -> list[dict[str, object]]:
    sample_messages = audiobook_voice_audition_sample_messages(job)
    current_token_hashes = _audiobook_voice_current_pending_token_hashes(job)
    delivery = dict(dict(job.get("telegram") or {}).get("voice_sample_delivery") or {})
    delivered_hashes = set(_audiobook_voice_sample_delivery_token_hashes(delivery))
    if not sample_messages:
        return []
    if not delivered_hashes:
        delivery_status = str(delivery.get("status") or "").strip().lower()
        expected_count = max(int(delivery.get("expected_count") or 0), 0)
        sent_count = max(int(delivery.get("sent_count") or 0), 0)
        expected_current_count = len(current_token_hashes) or len(sample_messages)
        if delivery_status == "sent" and expected_count == expected_current_count and sent_count >= expected_current_count:
            return []
        return sample_messages
    pending_messages: list[dict[str, object]] = []
    for sample in sample_messages:
        token = str(sample.get("token") or "").strip()
        if not token:
            pending_messages.append(sample)
            continue
        token_sha256 = _sha256_bytes(token.encode("utf-8"))
        if token_sha256 not in delivered_hashes:
            pending_messages.append(sample)
    return pending_messages


def _telegram_status_needs_voice_sample_delivery(job: dict[str, object]) -> bool:
    if str(job.get("status") or "").strip() != "waiting_voice_selection":
        return False
    voice_selection = dict(dict(job.get("provider") or {}).get("voice_selection") or {})
    if str(voice_selection.get("status") or "").strip() != "waiting_user_choice":
        return False
    return bool(_telegram_audiobook_voice_samples_pending_delivery(job))


def _send_telegram_audiobook_status(*, job: dict[str, object], text: str) -> dict[str, object]:
    token = _telegram_bot_token()
    current_job = dict(job)
    telegram = dict(current_job.get("telegram") or {})
    chat_id = str(telegram.get("chat_id") or "").strip()
    if not token or not chat_id:
        return {"status": "skipped", "reason": "telegram_token_or_chat_missing"}
    if _telegram_status_needs_voice_sample_delivery(current_job):
        pending_samples = _telegram_audiobook_voice_samples_pending_delivery(current_job)
        sample_receipts = _send_telegram_audiobook_voice_samples(
            job=current_job,
            bot_token=token,
            chat_id=chat_id,
            samples=pending_samples,
        )
        if sample_receipts:
            current_job = record_audiobook_voice_sample_delivery(job=current_job, sample_receipts=sample_receipts)
            telegram = dict(current_job.get("telegram") or {})
            text = telegram_epub_reply_text(current_job)
    params = {"chat_id": chat_id, "text": text}
    inline_buttons = _telegram_audiobook_playback_acceptance_buttons(job=current_job, chat_id=chat_id, bot_token=token)
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
        "voice_sample_delivery": dict(dict(current_job.get("telegram") or {}).get("voice_sample_delivery") or {}),
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
    candidate_jobs: tuple[tuple[Path, dict[str, object]], ...] | None = None,
) -> dict[str, object]:
    if _audiobook_job_has_user_selected_voice(job):
        return {}
    source_sha = _audiobook_source_sha256(job)
    if not source_sha:
        return {}
    current_job_id = str(job.get("job_id") or job_dir.name).strip()
    current_created_at = _parse_iso_datetime(job.get("created_at"))
    if candidate_jobs is None:
        loaded_candidates: list[tuple[Path, dict[str, object]]] = []
        for manifest_path in iter_audiobook_job_manifests(newest_first=True):
            try:
                loaded_candidates.append(
                    (manifest_path.parent, json.loads(manifest_path.read_text(encoding="utf-8")))
                )
            except Exception:
                continue
        candidate_jobs = tuple(loaded_candidates)
    for candidate_job_dir, candidate in candidate_jobs:
        if candidate_job_dir == job_dir:
            continue
        if _audiobook_source_sha256(candidate) != source_sha:
            continue
        if not _audiobook_user_voice_intent_pending(candidate):
            continue
        candidate_updated_at = _audiobook_job_updated_at(candidate)
        if current_created_at is not None and candidate_updated_at is not None and candidate_updated_at < current_created_at:
            continue
        candidate_job_id = str(candidate.get("job_id") or candidate_job_dir.name).strip()
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
    try:
        current = path
        while not current.exists() and current.parent != current:
            current = current.parent
        return current.exists() and os.access(current, os.W_OK)
    except OSError:
        return False


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
    if _audiobook_cinematic_narration() and (
        external_tts_enabled() or cinematic_track_path is not None
    ):
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
    current_target_path = str(import_result.get("target_path") or "").strip()
    current_target_hash = _sha256_bytes(current_target_path.encode("utf-8")) if current_target_path else ""
    previous_share_target_hash = str(previous_share.get("audiobookshelf_target_path_sha256") or "").strip()
    previous_match_kind = str(previous_share.get("audiobookshelf_item_match_kind") or "").strip()
    if (
        str(previous_share.get("status") or "").strip() == "public_share_ready"
        and str(current_share.get("status") or "").strip() != "public_share_ready"
        and previous_share_target_hash
        and previous_share_target_hash == current_target_hash
        and previous_match_kind in {"exact_absolute_path", "exact_absolute_parent", "import_root_relative_path"}
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


def _audiobookshelf_item_import_match_kind(*, row: dict[str, object], target_path: Path, metadata: EpubMetadata) -> str:
    target_name = target_path.name
    target_resolved = str(target_path)
    target_parent_resolved = str(target_path.parent)
    relative_targets: set[str] = set()
    try:
        target_relative = target_path.expanduser().resolve().relative_to(audiobookshelf_import_root().expanduser().resolve())
        relative_targets.add(target_relative.as_posix().strip("/"))
        relative_targets.add(target_relative.parent.as_posix().strip("/"))
    except Exception:
        relative_targets = set()
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
    absolute_candidates = [str(candidate or "").strip() for candidate in candidate_paths if Path(str(candidate or "")).is_absolute()]
    if absolute_candidates:
        if target_resolved in absolute_candidates:
            return "exact_absolute_path"
        if target_parent_resolved in absolute_candidates:
            return "exact_absolute_parent"
        return ""
    for candidate in candidate_paths:
        candidate_text = str(candidate or "").strip()
        if not candidate_text:
            continue
        candidate_path = Path(candidate_text)
        if candidate_path.is_absolute():
            continue
        normalized_relative = candidate_text.replace("\\", "/").strip("/")
        if normalized_relative and normalized_relative in relative_targets:
            return "import_root_relative_path"
    if not _env_bool("EA_AUDIOBOOKSHELF_ALLOW_TITLE_ONLY_ITEM_MATCH", False):
        return ""
    target_stem = _normalize_match_text(target_name)
    media = _audiobookshelf_item_media(row)
    media_metadata = dict(media.get("metadata") or {})
    title_match = _normalize_match_text(media_metadata.get("title") or media.get("title") or "")
    return "title_only_legacy" if target_stem and title_match and target_stem == title_match else ""


def _audiobookshelf_item_matches_import(*, row: dict[str, object], target_path: Path, metadata: EpubMetadata) -> bool:
    return bool(_audiobookshelf_item_import_match_kind(row=row, target_path=target_path, metadata=metadata))


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
        match_kind = _audiobookshelf_item_import_match_kind(row=row, target_path=target_path, metadata=metadata)
        if match_kind:
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
                "match_kind": match_kind,
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
        target_path_sha256 = _sha256_bytes(str(target_path).encode("utf-8"))
        if existing_slug:
            return {
                "status": "public_share_ready",
                "source": "existing_audiobookshelf_share",
                "library_item_id_sha256": _sha256_bytes(str(item.get("library_item_id") or "").encode("utf-8")),
                "media_item_id_sha256": _sha256_bytes(str(item.get("media_item_id") or "").encode("utf-8")),
                "slug_sha256": _sha256_bytes(existing_slug.encode("utf-8")),
                "audiobookshelf_target_path_sha256": target_path_sha256,
                "audiobookshelf_item_match_kind": str(item.get("match_kind") or "").strip(),
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
                    "audiobookshelf_target_path_sha256": target_path_sha256,
                    "audiobookshelf_item_match_kind": str(item.get("match_kind") or "").strip(),
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
            "audiobookshelf_target_path_sha256": target_path_sha256,
            "audiobookshelf_item_match_kind": str(item.get("match_kind") or "").strip(),
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
    with _AUDIOBOOK_EXTERNAL_TTS_ENV_LOCK:
        try:
            with _exclusive_audiobook_job_lock(job_dir):
                return _continue_job_locked(job_dir)
        except _AudiobookLockTimeout:
            current = _load_job(job_dir)
            return {
                **current,
                "status": "render_in_progress",
                "next_action": "retry_after_active_audiobook_job_transaction",
                "render_result": {
                    "status": "render_in_progress",
                    "reason": "audiobook_job_lock_timeout",
                    "retryable": True,
                },
            }


def _continue_job_locked(job_dir: Path) -> dict[str, object]:
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
        and str(render_result.get("reason") or "").strip() == "selected_voice_author_gender_mismatch"
    ):
        payload.update(
            {
                "status": "blocked_external_tts",
                "updated_at": _now_iso(),
                "render_result": render_result,
                "next_action": "selected_voice_author_gender_mismatch",
            }
        )
        _write_job(job_dir, payload)
        reopened_job = reopen_audiobook_voice_selection_for_author_gender_mismatch(job_dir=job_dir)
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
        if str(voice_selection.get("reason") or "").strip() == "selected_voice_author_gender_mismatch":
            pending = list(voice_selection.get("pending_batch") or [])
            profile = dict(voice_selection.get("book_profile") or {})
            author_gender_signal = str(profile.get("author_gender_signal") or "").strip().lower()
            selected_gender = _voice_candidate_gender(selected_voice)
            gender_line = (
                f"I inferred a {author_gender_signal} author signal"
                if author_gender_signal in {"male", "female"}
                else "The selected voice does not match the author gender signal"
            )
            mismatch_line = (
                f"{gender_line}, but the selected voice is tagged {selected_gender}"
                if selected_gender in {"male", "female"} and author_gender_signal in {"male", "female"}
                else gender_line
            )
            replacement_labels = [
                str(dict(row).get("label") or "").strip()
                for row in pending
                if isinstance(row, dict) and str(dict(row).get("label") or "").strip()
            ]
            suggested_labels = ", ".join(replacement_labels[:2])
            keep_line = (
                f" You can also keep {selected_voice.get('label')} if that is the intended voice."
                if selected_voice.get("label")
                else ""
            )
            suggestion_line = (
                f" I staged better-matching alternatives: {suggested_labels}."
                if suggested_labels
                else " I staged better-matching voice alternatives."
            )
            return (
                f"{mismatch_line} for {title}, so I stopped before finishing the book with the stale voice choice."
                f"{suggestion_line}{keep_line} Choose 'Use this' on the one you want."
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
            elif underfilled_reason == "voice_catalog_author_gender_underfilled_after_dismissals":
                sample_line = (
                    f"{pending_count} author-gender-matched voice {sample_word} {verb} after your dismissals; "
                    "the provider catalog has no more fitting matches for this book."
                )
            elif underfilled_reason == "voice_catalog_author_gender_underfilled":
                sample_line = (
                    f"I found {pending_count} author-gender-matched voice {sample_word}; "
                    "the provider catalog has fewer matching voices than requested."
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
                if blocker_code == "selected_voice_author_gender_mismatch":
                    return (
                        f"I accepted the source ebook and extracted {chapter_count} chapters for {title}. "
                        "The selected voice does not match the author gender signal, so I stopped before finishing it with the stale voice choice. "
                        f"Choose one of the staged replacement voices, or keep the current one explicitly if that is what you want.{voice_line}"
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
    if "selected_voice_author_gender_mismatch" in normalized:
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
    if "selected_voice_author_gender_mismatch" in normalized:
        return "selected_voice_author_gender_mismatch"
    if (
        "insufficient api balance" in normalized
        or "insufficient balance" in normalized
        or "prebuilt character" in normalized
        or "balance_exhausted" in normalized
    ):
        return "provider_balance_or_prebuilt_characters"
    if "quota" in normalized:
        return "provider_quota"
    if "credit" in normalized or "billing" in normalized or "payment" in normalized:
        return "provider_billing"
    if "rate limit" in normalized or "rate_limited" in normalized:
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


def recover_audiobook_job_without_external_side_effects(job_dir: Path) -> dict[str, object]:
    job = _load_job(job_dir)
    status = str(job.get("status") or "").strip()
    provider_payload = dict(job.get("provider") or {})
    voice_selection = dict(provider_payload.get("voice_selection") or {})
    if not voice_selection:
        return {"recovered": False, "reason": "voice_selection_missing", "job": job}
    metadata = _metadata_from_job(job)
    render_result = dict(job.get("render_result") or {})
    render_reason = str(render_result.get("reason") or "").strip()

    language_mismatch = _selected_voice_language_mismatch(
        metadata=metadata,
        voice_selection={"public": voice_selection},
    )
    if language_mismatch and status in {"blocked_external_tts", "voice_selected"}:
        reopened = reopen_audiobook_voice_selection_for_language_mismatch(job_dir=job_dir)
        return {
            "recovered": str(reopened.get("status") or "").strip() == "waiting_voice_selection",
            "reason": "selected_voice_language_mismatch",
            "job": reopened,
        }

    author_gender_mismatch = _selected_voice_author_gender_mismatch(
        job_dir=job_dir,
        metadata=metadata,
        voice_selection={"public": voice_selection},
    )
    if author_gender_mismatch and status in {"blocked_external_tts", "voice_selected"}:
        reopened = reopen_audiobook_voice_selection_for_author_gender_mismatch(job_dir=job_dir)
        return {
            "recovered": str(reopened.get("status") or "").strip() == "waiting_voice_selection",
            "reason": "selected_voice_author_gender_mismatch",
            "job": reopened,
        }

    if status == "blocked_external_tts" and render_reason in {
        "selected_voice_language_mismatch",
        "selected_voice_author_gender_mismatch",
    }:
        return {
            "recovered": False,
            "reason": render_reason,
            "job": job,
        }
    return {"recovered": False, "reason": "", "job": job}


def recover_stale_audiobook_jobs_without_external_side_effects(
    *,
    newest_first: bool = True,
    limit: int | None = None,
) -> dict[str, object]:
    manifests = list(iter_audiobook_job_manifests(newest_first=newest_first))
    if limit is not None:
        manifests = manifests[: max(int(limit), 0)]
    attempted = 0
    recovered = 0
    recovery_reasons: dict[str, int] = {}
    changed_jobs: list[dict[str, object]] = []
    errors: list[str] = []
    for manifest_path in manifests:
        attempted += 1
        job_dir = manifest_path.parent
        try:
            result = recover_audiobook_job_without_external_side_effects(job_dir)
        except Exception as exc:
            errors.append(f"{job_dir.name}:{type(exc).__name__}:{exc}")
            continue
        if not bool(result.get("recovered")):
            continue
        recovered += 1
        reason = str(result.get("reason") or "").strip() or "recovered"
        recovery_reasons[reason] = int(recovery_reasons.get(reason) or 0) + 1
        job = dict(result.get("job") or {})
        changed_jobs.append(
            {
                "job_id": str(job.get("job_id") or job_dir.name),
                "job_dir_name": job_dir.name,
                "status": str(job.get("status") or "").strip(),
                "next_action": str(job.get("next_action") or "").strip(),
                "reason": reason,
            }
        )
    return {
        "attempted": attempted,
        "recovered": recovered,
        "recovery_reasons": dict(sorted(recovery_reasons.items())),
        "changed_jobs": changed_jobs[:20],
        "errors": errors[:20],
    }


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
    with _AUDIOBOOK_EXTERNAL_TTS_ENV_LOCK:
        job = _load_job(job_dir)
        provider = dict(job.get("provider") or {})
        voice_selection = dict(provider.get("voice_selection") or {})
        selected_voice = dict(voice_selection.get("selected") or {})
        selected_provider = str(selected_voice.get("provider") or "").strip()
        has_selected_unmixr_voice = (
            str(voice_selection.get("status") or "").strip()
            == "selected_by_user"
            and bool(str(voice_selection.get("selected_candidate_key") or "").strip())
            and selected_provider != "piper_local_fast"
        )
        allow_external = bool(provider.get("raw_book_text_leaves_ea")) and (
            str(provider.get("preferred") or "") == "unmixr_ai"
            or has_selected_unmixr_voice
        )
        previous_external = os.environ.get("EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED")
        previous_unmixr = os.environ.get("EA_AUDIOBOOK_UNMIXR_AUTO_RENDER")
        target_value = "1" if allow_external else "0"
        os.environ["EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED"] = target_value
        os.environ["EA_AUDIOBOOK_UNMIXR_AUTO_RENDER"] = target_value
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
    public_share_delivery_gate_snapshot: list[tuple[Path, dict[str, object]]] = []
    for manifest_path in manifests:
        try:
            public_share_delivery_gate_snapshot.append(
                (manifest_path.parent, json.loads(manifest_path.read_text(encoding="utf-8")))
            )
        except Exception:
            continue
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
    safe_recovered = 0
    safe_recovery_reasons: dict[str, int] = {}
    notifications: list[dict[str, object]] = []
    for manifest_path in manifests:
        try:
            job_dir = manifest_path.parent
            recovery = recover_audiobook_job_without_external_side_effects(job_dir)
            if bool(recovery.get("recovered")):
                safe_recovered += 1
                recovery_reason = str(recovery.get("reason") or "").strip() or "recovered"
                safe_recovery_reasons[recovery_reason] = int(safe_recovery_reasons.get(recovery_reason) or 0) + 1
            job = dict(recovery.get("job") or {})
            if not job:
                job = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            errors += 1
            continue
        if notify_telegram and _telegram_status_needs_voice_sample_delivery(job):
            notification = _send_telegram_audiobook_status(
                job=job,
                text=telegram_epub_reply_text(job),
            )
            notifications.append(
                {
                    "job_id": str(job.get("job_id") or job_dir.name),
                    "status": str(job.get("status") or "").strip(),
                    "notification": notification,
                }
            )
            with contextlib.suppress(Exception):
                job = _load_job(job_dir)
        retry_at = _audiobook_job_retry_at(job)
        if retry_at is None:
            if _audiobook_public_share_followup_pending(job):
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
                    "error_code": "audiobook_resume_failed",
                    "error_detail_sha256": _sha256_bytes(str(exc).encode("utf-8")),
                    "error_type": type(exc).__name__,
                    "raw_error_exposed": False,
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
                delivery_block = _audiobook_default_voice_public_share_delivery_block(
                    job_dir=job_dir,
                    job=refreshed_job,
                    candidate_jobs=tuple(public_share_delivery_gate_snapshot),
                )
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
                    "error_code": "audiobook_public_share_refresh_failed",
                    "error_detail_sha256": _sha256_bytes(str(exc).encode("utf-8")),
                    "error_type": type(exc).__name__,
                    "raw_error_exposed": False,
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
        "safe_recovered": safe_recovered,
        "safe_recovery_reasons": dict(sorted(safe_recovery_reasons.items())),
        "notifications": notifications[:10],
        "share_link_attempted": share_link_attempted,
        "share_links_ready": share_links_ready,
        "share_links_blocked": share_links_blocked,
        "share_link_pending": share_link_pending + max(len(share_rows) - max_jobs, 0) + share_links_waiting,
        "share_link_notifications": share_link_notifications[:10],
    }
