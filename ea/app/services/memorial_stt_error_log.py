from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.memorial_paths import memorial_data_root


def _default_stt_error_root() -> Path:
    return memorial_data_root() / "memorial_data" / "private_memorial_stt_errors"


_DEFAULT_STT_ERROR_ROOT = _default_stt_error_root()
_GENERIC_FALLBACK_MARKERS = (
    "sag mir den konkreten punkt",
    "dann antworte ich dir direkt darauf",
    "wenn du den punkt enger ziehst",
    "sag mir den aktuellen stand kurz",
)
_EXPECTED_NON_ERROR_FALLBACK_REASONS = {
    "current_speculation_guardrail",
    "present_world_guardrail",
    "direct_contact_opening",
    "multi_question_retry_required",
    "difficult_memory_guardrail",
    "memorial_values_guardrail",
    "memorial_anchor_memory_guardrail",
    "family_mail_guardrail",
    "colleague_mail_guardrail",
    "mail_style_without_imported_mail",
    "mail_practice_guardrail",
    "transcript_relationship_guardrail",
}
_SUSPICIOUS_FALLBACK_REASONS = {
    "conversation_turn_llm_timeout",
    "realtime_llm_timeout",
    "rescue_ooda_loop",
    "memorial_ooda_guardrail",
}
_DROP_FIELDS = {
    "sources",
    "source_documents",
    "source_chunks",
    "raw_response",
    "messages",
    "audio_base64",
    "audio_bytes",
}
_REDACTED_TEXT_FIELDS = {
    "answer",
    "question",
    "text",
    "transcript_text",
    "transcript_original_text",
    "transcript_effective_text",
}
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_SECRET_RE = re.compile(
    r"(?:sk_[A-Za-z0-9._-]+|Bearer\s+[A-Za-z0-9._-]+|AIza[0-9A-Za-z_-]+)",
    re.IGNORECASE,
)


def memorial_stt_error_logging_enabled() -> bool:
    raw = str(os.getenv("EA_MEMORIAL_STT_ERROR_LOG_ENABLED") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def memorial_stt_error_log_root() -> Path:
    configured = str(os.getenv("EA_MEMORIAL_STT_ERROR_LOG_DIR") or "").strip()
    return Path(configured).expanduser() if configured else _default_stt_error_root()


def memorial_stt_error_retention_days() -> int | None:
    raw = os.getenv("EA_MEMORIAL_STT_ERROR_LOG_RETENTION_DAYS")
    if raw is None or not str(raw).strip():
        return None
    try:
        parsed = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return max(1, min(365, parsed))


def memorial_stt_error_text_mode() -> str:
    requested = str(os.getenv("EA_MEMORIAL_STT_ERROR_LOG_TEXT_MODE") or "").strip().lower()
    full_allowed = str(os.getenv("EA_MEMORIAL_STT_ERROR_LOG_FULL_TEXT_ALLOWED") or "").strip().lower()
    if requested == "full" and full_allowed in {"1", "true", "yes", "on"}:
        return "full"
    return "redacted"


def classify_memorial_stt_issue(
    *,
    transcription_status: str = "",
    transcript_text: str = "",
    answer_text: str = "",
    fallback_reason: str = "",
) -> str:
    normalized_status = str(transcription_status or "").strip().lower()
    normalized_transcript = " ".join(str(transcript_text or "").split()).strip()
    normalized_answer = " ".join(str(answer_text or "").split()).strip().lower()
    normalized_reason = str(fallback_reason or "").strip().lower()
    if normalized_status and normalized_status != "transcribed":
        return f"stt_{normalized_status}"
    if not normalized_transcript:
        return "stt_empty_transcript"
    if any(marker in normalized_answer for marker in _GENERIC_FALLBACK_MARKERS):
        return "generic_fallback_answer"
    if normalized_reason.startswith("upstream_unavailable:"):
        return "upstream_unavailable"
    if normalized_reason in _SUSPICIOUS_FALLBACK_REASONS:
        return normalized_reason
    if normalized_reason and normalized_reason not in _EXPECTED_NON_ERROR_FALLBACK_REASONS:
        return f"fallback_{normalized_reason}"
    return ""


def log_memorial_stt_issue(
    *,
    slug: str,
    route: str,
    reason: str,
    audio_payload: bytes,
    content_type: str,
    transcription_payload: dict[str, Any] | None = None,
    answer_payload: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, str]:
    if not memorial_stt_error_logging_enabled():
        return {"status": "disabled", "reason": "logging_disabled"}
    retention_days = memorial_stt_error_retention_days()
    if retention_days is None:
        return {"status": "disabled", "reason": "retention_policy_missing"}
    storage_policy = _storage_policy()
    if not storage_policy["allowed"]:
        return {"status": "disabled", "reason": str(storage_policy["reason"])}
    root = Path(str(storage_policy["root"]))
    timestamp = datetime.now(timezone.utc)
    token = uuid.uuid4().hex[:12]
    safe_slug = _safe_path_token(slug, fallback="memorial")
    safe_route = _safe_path_token(route, fallback="route")
    safe_reason = _safe_path_token(reason, fallback="issue")
    target_dir = root / safe_slug / timestamp.strftime("%Y/%m/%d") / f"{timestamp.strftime('%H%M%S')}_{safe_route}_{safe_reason}_{token}"
    target_dir.mkdir(parents=True, exist_ok=True)

    wav_payload = _best_effort_wav_payload(payload=audio_payload, content_type=content_type)
    audio_filename = "input.wav" if wav_payload is not None else f"input{_content_type_suffix(content_type)}"
    if wav_payload is not None:
        _write_bytes_atomic(target_dir / audio_filename, wav_payload)
    elif audio_payload:
        _write_bytes_atomic(target_dir / audio_filename, audio_payload)

    text_mode = memorial_stt_error_text_mode()
    metadata = {
        "status": "open",
        "severity": "error",
        "needs_fix": True,
        "slug": slug,
        "route": route,
        "reason": reason,
        "occurred_at": timestamp.isoformat(),
        "content_type": str(content_type or "application/octet-stream"),
        "audio_bytes": len(audio_payload or b""),
        "stored_wav": bool(wav_payload is not None),
        "retention_days": retention_days,
        "consent_mode": "explicit_operator_opt_in",
        "text_mode": text_mode,
        "storage_policy": {
            "storage_mode": str(storage_policy["storage_mode"]),
            "root": str(root),
        },
        "transcription": _scrub_payload(dict(transcription_payload or {}), text_mode=text_mode),
        "answer": _scrub_payload(dict(answer_payload or {}), text_mode=text_mode),
        "extra": _scrub_payload(dict(extra or {}), text_mode=text_mode),
    }
    _write_text_atomic(
        target_dir / "error.json",
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True),
    )
    return {
        "status": "logged",
        "directory": str(target_dir),
        "metadata_path": str(target_dir / "error.json"),
        "audio_path": str(target_dir / audio_filename),
    }


def _storage_policy() -> dict[str, object]:
    root = memorial_stt_error_log_root()
    allow_local = str(os.getenv("EA_MEMORIAL_STT_ERROR_LOG_ALLOW_LOCAL") or "").strip().lower() in {"1", "true", "yes", "on"}
    if allow_local:
        return {
            "allowed": True,
            "reason": "",
            "root": root,
            "storage_mode": "operator_local_override",
        }
    root_text = str(root)
    if root_text.startswith("/private/"):
        if not _private_storage_available():
            return {
                "allowed": False,
                "reason": "private_storage_missing",
                "root": root,
                "storage_mode": "private_storage",
            }
        return {
            "allowed": True,
            "reason": "",
            "root": root,
            "storage_mode": "private_storage",
        }
    try:
        resolved_root = root.resolve(strict=False)
        default_root = _default_stt_error_root().resolve(strict=False)
        under_default = resolved_root == default_root or default_root in resolved_root.parents
    except Exception:
        under_default = False
    if not under_default:
        return {
            "allowed": False,
            "reason": "root_not_under_memorial_stt_error_root",
            "root": root,
            "storage_mode": "rejected",
        }
    return {
        "allowed": True,
        "reason": "",
        "root": root,
        "storage_mode": "managed_private_root",
    }


def _private_storage_available() -> bool:
    return Path("/private").exists()


def _scrub_payload(payload: dict[str, Any], *, text_mode: str) -> dict[str, Any]:
    scrubbed: dict[str, Any] = {}
    for key, value in payload.items():
        normalized_key = str(key).strip()
        if normalized_key.lower() in _DROP_FIELDS:
            continue
        scrubbed[normalized_key] = _scrub_value(value, key=normalized_key, text_mode=text_mode)
    return scrubbed


def _scrub_value(value: Any, *, key: str, text_mode: str) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        normalized = _sanitize_public_text(value)
        if key.lower() in _REDACTED_TEXT_FIELDS:
            if text_mode == "full":
                return normalized
            return {
                "redacted": True,
                "chars": len(normalized),
                "sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
            }
        return normalized[:500]
    if isinstance(value, list):
        return [_scrub_value(item, key=key, text_mode=text_mode) for item in value[:10]]
    if isinstance(value, dict):
        nested: dict[str, Any] = {}
        for nested_key, nested_value in list(value.items())[:20]:
            nested[str(nested_key)] = _scrub_value(nested_value, key=str(nested_key), text_mode=text_mode)
        return nested
    return _sanitize_public_text(str(value))[:200]


def _sanitize_public_text(value: str) -> str:
    normalized = " ".join(str(value or "").split()).strip()
    normalized = _URL_RE.sub("[url]", normalized)
    normalized = _SECRET_RE.sub("[secret]", normalized)
    return normalized


def _safe_path_token(value: object, *, fallback: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip()).strip("._-")
    return normalized[:80] or fallback


def _content_type_suffix(content_type: str) -> str:
    normalized = str(content_type or "").split(";", 1)[0].strip().lower()
    return {
        "audio/wav": ".wav",
        "audio/wave": ".wav",
        "audio/x-wav": ".wav",
        "audio/webm": ".webm",
        "audio/ogg": ".ogg",
        "audio/mp4": ".m4a",
        "audio/mpeg": ".mp3",
        "audio/pcm": ".pcm",
        "application/octet-stream": ".bin",
    }.get(normalized, ".bin")


def _best_effort_wav_payload(*, payload: bytes, content_type: str) -> bytes | None:
    if not payload:
        return None
    normalized = str(content_type or "").strip().lower()
    if normalized.startswith(("audio/wav", "audio/wave", "audio/x-wav")) or payload.startswith(b"RIFF"):
        return payload
    if normalized.startswith("audio/pcm"):
        return _pcm16_to_wav(payload, sample_rate=_pcm_sample_rate_from_content_type(content_type))
    ffmpeg_format = _ffmpeg_input_format_for_content_type(content_type)
    if ffmpeg_format:
        return _ffmpeg_audio_to_wav(payload=payload, input_format=ffmpeg_format)
    return None


def _ffmpeg_input_format_for_content_type(content_type: str) -> str:
    normalized = str(content_type or "").split(";", 1)[0].strip().lower()
    if normalized == "audio/webm":
        return "webm"
    if normalized == "audio/ogg":
        return "ogg"
    if normalized == "audio/mp4":
        return "mp4"
    if normalized == "audio/mpeg":
        return "mp3"
    return ""


def _ffmpeg_audio_to_wav(*, payload: bytes, input_format: str) -> bytes | None:
    if not payload or not input_format:
        return None
    try:
        completed = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                input_format,
                "-i",
                "pipe:0",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "s16le",
                "pipe:1",
            ],
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return None
    if completed.returncode != 0:
        return None
    converted = bytes(completed.stdout or b"")
    if len(converted) < 2:
        return None
    return _pcm16_to_wav(converted, sample_rate=16000)


def _pcm_sample_rate_from_content_type(content_type: str) -> int:
    match = re.search(r"rate=(\d+)", str(content_type or ""))
    if not match:
        return 16000
    try:
        parsed = int(match.group(1))
    except (TypeError, ValueError):
        return 16000
    return max(8000, min(48000, parsed))


def _pcm16_to_wav(payload: bytes, *, sample_rate: int) -> bytes:
    trimmed = payload[: len(payload) - (len(payload) % 2)]
    with tempfile.SpooledTemporaryFile(max_size=1024 * 1024) as buffer:
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(trimmed)
        buffer.seek(0)
        return buffer.read()


def _write_text_atomic(path: Path, payload: str) -> None:
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp_path.write_text(payload, encoding="utf-8")
    temp_path.replace(path)


def _write_bytes_atomic(path: Path, payload: bytes) -> None:
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp_path.write_bytes(payload)
    temp_path.replace(path)
